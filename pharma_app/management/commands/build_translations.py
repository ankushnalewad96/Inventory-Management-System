"""
Build the language files without GNU gettext.

    python manage.py build_translations            # compile .po -> .mo
    python manage.py build_translations --update   # also add new texts to the .po files

The page and server texts go in  locale/<lang>/LC_MESSAGES/django.po,
the JavaScript texts in          locale/<lang>/LC_MESSAGES/djangojs.po.

--update finds every text marked for translation:
    templates   {% translate "..." %}, {% blocktranslate %}...{% endblocktranslate %}
    Python      gettext("...")
    JavaScript  gettext('...') inside templates' <script> blocks
and adds the new ones to each .po file (existing translations are kept).
Then it compiles every .po file into the .mo file Django reads.
"""

import ast
import re
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

APP_DIR = Path(__file__).resolve().parents[2]
LOCALE_DIR = APP_DIR / "locale"

TRANSLATE_TAG = re.compile(r"""\{%\s*(?:translate|trans)\s+(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')(?:\s+(?:noop|as\s+\w+|context\s+\S+))*\s*%\}""")
BLOCK_TAG = re.compile(r"\{%\s*blocktrans(?:late)?\b([^%]*)%\}(.*?)\{%\s*endblocktrans(?:late)?\s*%\}", re.S)
PLURAL_TAG = re.compile(r"\{%\s*plural\s*%\}")
BLOCK_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)
JS_GETTEXT = re.compile(r"""\bgettext\(\s*'((?:[^'\\]|\\.)*)'\s*\)""")

# Status words the scripts translate from a variable: gettext(paymentStatus).
JS_EXTRA = ["Paid", "Unpaid", "Partial"]


def _unescape(text):
    return text.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")


def _block_text(text, trimmed):
    if trimmed:
        text = " ".join(line.strip() for line in text.strip().splitlines())
    return BLOCK_VAR.sub(lambda m: f"%({m.group(1)})s", text.replace("%", "%%"))


def collect():
    """{domain: {(msgid, msgid_plural): set(sources)}}"""

    found = {"django": {}, "djangojs": {}}

    def add(domain, msgid, plural=None, source=""):
        if msgid:
            found[domain].setdefault((msgid, plural), set()).add(source)

    for path in sorted((APP_DIR / "templates").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in TRANSLATE_TAG.finditer(text):
            add("django", _unescape(match.group(1) if match.group(1) is not None else match.group(2)), source=path.name)
        for match in BLOCK_TAG.finditer(text):
            trimmed = "trimmed" in match.group(1)
            parts = PLURAL_TAG.split(match.group(2))
            singular = _block_text(parts[0], trimmed)
            plural = _block_text(parts[1], trimmed) if len(parts) > 1 else None
            add("django", singular, plural, path.name)
        for block in SCRIPT.findall(text):
            for match in JS_GETTEXT.finditer(block):
                add("djangojs", _unescape(match.group(1)), source=path.name)

    for word in JS_EXTRA:
        add("djangojs", word, source="scripts")

    for path in sorted(APP_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = getattr(node.func, "id", None)
            strings = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if name in ("gettext", "gettext_lazy", "_") and strings:
                add("django", strings[0], source=path.name)
            elif name == "ngettext" and len(strings) >= 2:
                add("django", strings[0], strings[1], source=path.name)

    # Stored values shown on pages with {% translate value %}.
    for text in stored_value_labels():
        add("django", text, source="stored values")
    return found


def stored_value_labels():
    """Choice labels and names that pages show from the database."""

    from pharma_app import models, shop_types, states

    labels = set(shop_types.SHOP_TYPE_LABELS.values()) | set(shop_types.FEATURE_LABELS.values())
    labels |= set(states.STATE_NAMES.values())
    for choices in (
        models.Sale.PAYMENT_TYPE_CHOICES, models.Sale.PAYMENT_STATUS_CHOICES,
        models.Purchase.PAYMENT_TYPE, models.Purchase.PAYMENT_STATUS,
        models.Customer.PRICE_LEVEL_CHOICES, models.Quotation.STATUS_CHOICES,
        models.SaleReturn.REFUND_CHOICES, models.Product.SCHEDULE_CHOICES,
        states.TAX_TYPE_CHOICES,
    ):
        labels |= {label for _, label in choices}
    return sorted(labels)


# ------------------------------------------------------------------ .po files

def _po_quote(text):
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return f'"{text}"'


def _po_unquote(text):
    out, i = [], 0
    text = text[1:-1]
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def read_po(path):
    """{(msgid, msgid_plural): [translations]} and the header text."""

    entries, header = {}, ""
    if not path.exists():
        return entries, header

    current, key = {}, None

    def flush():
        if "msgid" in current:
            msgid = current["msgid"]
            plural = current.get("msgid_plural")
            if msgid == "" and plural is None:
                nonlocal header
                header = current.get("msgstr", "")
            else:
                if plural is None:
                    entries[(msgid, None)] = [current.get("msgstr", "")]
                else:
                    forms = sorted((k for k in current if k.startswith("msgstr[")), key=lambda k: int(k[7:-1]))
                    entries[(msgid, plural)] = [current[k] for k in forms]

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if not line:
                flush()
                current, key = {}, None
            continue
        if line.startswith('"'):
            if key:
                current[key] += _po_unquote(line)
            continue
        name, _, rest = line.partition(" ")
        key = name
        current[key] = _po_unquote(rest.strip())
    flush()
    return entries, header


def write_po(path, entries, language, sources):
    nplurals = "nplurals=2; plural=(n != 1);"
    lines = [
        "# DukaanPro translations. Edit the msgstr lines, then run: python manage.py build_translations",
        'msgid ""',
        'msgstr ""',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        f'"Language: {language}\\n"',
        f'"Plural-Forms: {nplurals}\\n"',
        "",
    ]
    for (msgid, plural), translations in sorted(entries.items(), key=lambda item: item[0][0].lower()):
        where = ", ".join(sorted(sources.get((msgid, plural), [])))
        if where:
            lines.append(f"#: {where}")
        lines.append(f"msgid {_po_quote(msgid)}")
        if plural is None:
            lines.append(f"msgstr {_po_quote(translations[0] if translations else '')}")
        else:
            lines.append(f"msgid_plural {_po_quote(plural)}")
            forms = (translations + ["", ""])[:2]
            for index, form in enumerate(forms):
                lines.append(f"msgstr[{index}] {_po_quote(form)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------------------ .mo files

def write_mo(path, entries, language):
    header = (
        "Content-Type: text/plain; charset=UTF-8\n"
        f"Language: {language}\n"
        "Plural-Forms: nplurals=2; plural=(n != 1);\n"
    )
    catalog = {"": header}
    for (msgid, plural), translations in entries.items():
        if not any(translations):
            continue                       # untranslated: Django shows the English text
        if plural is None:
            catalog[msgid] = translations[0]
        else:
            forms = [t or (msgid if i == 0 else plural) for i, t in enumerate((translations + ["", ""])[:2])]
            catalog[msgid + "\x00" + plural] = "\x00".join(forms)

    keys = sorted(catalog)
    ids = b""
    strs = b""
    offsets = []
    for key in keys:
        key_bytes, value_bytes = key.encode("utf-8"), catalog[key].encode("utf-8")
        offsets.append((len(ids), len(key_bytes), len(strs), len(value_bytes)))
        ids += key_bytes + b"\x00"
        strs += value_bytes + b"\x00"

    count = len(keys)
    key_start = 7 * 4 + 16 * count
    value_start = key_start + len(ids)
    key_table, value_table = [], []
    for id_offset, id_len, str_offset, str_len in offsets:
        key_table += [id_len, key_start + id_offset]
        value_table += [str_len, value_start + str_offset]

    data = struct.pack("Iiiiiii", 0x950412DE, 0, count, 7 * 4, 7 * 4 + count * 8, 0, 0)
    data += struct.pack(f"{len(key_table)}i", *key_table)
    data += struct.pack(f"{len(value_table)}i", *value_table)
    data += ids + strs
    path.write_bytes(data)


class Command(BaseCommand):
    help = "Compile the translation files (and with --update, add newly marked texts to them)."

    def add_arguments(self, parser):
        parser.add_argument("--update", action="store_true", help="Add new texts to the .po files first.")

    def handle(self, *args, **options):
        found = collect() if options["update"] else None
        languages = [code for code, _ in settings.LANGUAGES if code != "en"]

        for language in languages:
            for domain in ("django", "djangojs"):
                po_path = LOCALE_DIR / language / "LC_MESSAGES" / f"{domain}.po"
                entries, _ = read_po(po_path)

                if found is not None:
                    sources = {key: value for key, value in found[domain].items()}
                    merged = {key: entries.get(key, [""]) for key in sources}
                    write_po(po_path, merged, language, sources)
                    entries = merged
                    missing = sum(1 for value in merged.values() if not any(value))
                    self.stdout.write(f"{language}/{domain}.po: {len(merged)} texts, {missing} not translated yet")

                if po_path.exists():
                    write_mo(po_path.with_suffix(".mo"), entries, language)

        self.stdout.write(self.style.SUCCESS("Translations built."))
