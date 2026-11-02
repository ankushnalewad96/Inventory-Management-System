"""
Indian states / union territories, and the GST tax split.

Shops store their state as a short key ("maharashtra", "up", ...: the
values of the registration form). Suppliers and older records may hold
a full name ("Maharashtra", "Uttar Pradesh"). same_state() compares any
of these forms.

GST split (features.b2b_tax_split):
    same state as the shop  -> CGST + SGST (half each)
    another state           -> IGST (full rate)
    party state unknown     -> treated as the shop's state (CGST + SGST)
"""

import re
from decimal import Decimal

# (key, name). Keys match the registration form's existing values.
STATE_CHOICES = [
    ("andhra", "Andhra Pradesh"),
    ("arunachal", "Arunachal Pradesh"),
    ("assam", "Assam"),
    ("bihar", "Bihar"),
    ("chhattisgarh", "Chhattisgarh"),
    ("goa", "Goa"),
    ("gujarat", "Gujarat"),
    ("haryana", "Haryana"),
    ("himachal", "Himachal Pradesh"),
    ("jharkhand", "Jharkhand"),
    ("karnataka", "Karnataka"),
    ("kerala", "Kerala"),
    ("mp", "Madhya Pradesh"),
    ("maharashtra", "Maharashtra"),
    ("manipur", "Manipur"),
    ("meghalaya", "Meghalaya"),
    ("mizoram", "Mizoram"),
    ("nagaland", "Nagaland"),
    ("odisha", "Odisha"),
    ("punjab", "Punjab"),
    ("rajasthan", "Rajasthan"),
    ("sikkim", "Sikkim"),
    ("tamilnadu", "Tamil Nadu"),
    ("telangana", "Telangana"),
    ("tripura", "Tripura"),
    ("up", "Uttar Pradesh"),
    ("uttarakhand", "Uttarakhand"),
    ("westbengal", "West Bengal"),
    ("andaman", "Andaman and Nicobar Islands"),
    ("chandigarh", "Chandigarh"),
    ("dnhdd", "Dadra and Nagar Haveli and Daman and Diu"),
    ("delhi", "Delhi"),
    ("jk", "Jammu and Kashmir"),
    ("ladakh", "Ladakh"),
    ("lakshadweep", "Lakshadweep"),
    ("puducherry", "Puducherry"),
]

STATE_NAMES = dict(STATE_CHOICES)

# Other spellings people type.
_ALIASES = {
    "orissa": "odisha",
    "pondicherry": "puducherry",
    "newdelhi": "delhi",
    "nctofdelhi": "delhi",
    "uttaranchal": "uttarakhand",
    "jammukashmir": "jk",
    "jammuandkashmir": "jk",
    "andhrapradesh": "andhra",
    "madhyapradesh": "mp",
    "uttarpradesh": "up",
}


def _squash(value):
    return re.sub(r"[^a-z]", "", (value or "").lower())


_LOOKUP = {}
for _key, _name in STATE_CHOICES:
    _LOOKUP[_squash(_key)] = _key
    _LOOKUP[_squash(_name)] = _key
_LOOKUP.update(_ALIASES)


def state_key(value):
    """The state's key for any known spelling, or "" when unknown/empty."""

    return _LOOKUP.get(_squash(value), "")


def state_name(value):
    """Display name for a stored state value (falls back to the value)."""

    key = state_key(value)
    return STATE_NAMES.get(key, value or "")


def is_inter_state(shop_state, party_state):
    """True when the party is in a known state different from the shop's."""

    shop = state_key(shop_state)
    party = state_key(party_state)
    return bool(shop and party and shop != party)


# ---------------------------------------------------------------- tax split

TAX_INTRA = "intra"   # CGST + SGST
TAX_INTER = "inter"   # IGST
TAX_TYPE_CHOICES = [
    (TAX_INTRA, "CGST + SGST"),
    (TAX_INTER, "IGST"),
]

_PAISA = Decimal("0.01")


def split_amount(gst_amount, tax_type):
    """
    {"cgst", "sgst", "igst"} for a GST amount. CGST takes the rounded
    half and SGST the rest, so the parts always add up to the total.
    Empty tax type (split switched off) -> all zero.
    """

    gst_amount = Decimal(gst_amount or 0).quantize(_PAISA)
    zero = Decimal("0.00")

    if tax_type == TAX_INTER:
        return {"cgst": zero, "sgst": zero, "igst": gst_amount}

    if tax_type == TAX_INTRA:
        cgst = (gst_amount / 2).quantize(_PAISA)
        return {"cgst": cgst, "sgst": gst_amount - cgst, "igst": zero}

    return {"cgst": zero, "sgst": zero, "igst": zero}


def tax_fields(features, shop_state, party_state, gst_amount):
    """
    Model field values (tax_type, cgst, sgst, igst) for a bill.
    With features.b2b_tax_split off the tax type stays empty (no split).
    """

    if not features.b2b_tax_split:
        tax_type = ""
    elif is_inter_state(shop_state, party_state):
        tax_type = TAX_INTER
    else:
        tax_type = TAX_INTRA

    return {"tax_type": tax_type, **split_amount(gst_amount, tax_type)}


def rate_wise_summary(lines, tax_type):
    """
    GST summary per rate for an invoice:
        [{"rate", "taxable", "tax", "cgst", "sgst", "igst"}, ...]
    `lines` are (rate, taxable_amount) pairs.
    """

    by_rate = {}

    for rate, taxable in lines:
        rate = Decimal(rate or 0)
        by_rate[rate] = by_rate.get(rate, Decimal("0")) + Decimal(taxable)

    rows = []
    for rate in sorted(by_rate):
        taxable = by_rate[rate].quantize(_PAISA)
        tax = (taxable * rate / 100).quantize(_PAISA)
        rows.append({"rate": rate, "taxable": taxable, "tax": tax, **split_amount(tax, tax_type)})

    return rows
