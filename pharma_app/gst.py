"""
GST rates: the ONE place to edit them.

GST_RATES are the slabs that can be chosen for new products and new
purchase lines. They follow the GST change of 22 Sept 2025
(0 / 0.25 / 3 / 5 / 18 / 40 %). Please confirm them with your
accountant and edit this list when the law changes.

LEGACY_GST_RATES are old slabs that are no longer offered for new entries,
but bills and products already saved with them must still display, print
and (for products) be kept unchanged.
"""

from decimal import Decimal, InvalidOperation

GST_RATES = (
    Decimal("0"),
    Decimal("0.25"),
    Decimal("3"),
    Decimal("5"),
    Decimal("18"),
    Decimal("40"),
)

LEGACY_GST_RATES = (
    Decimal("12"),
    Decimal("28"),
)


def format_rate(rate):
    """Decimal('5.00') -> '5', Decimal('0.25') -> '0.25'."""

    rate = Decimal(rate)
    text = format(rate.normalize(), "f")
    return text


def gst_choices():
    """[(value, label)] for <select>s: [('0', '0%'), ('0.25', '0.25%'), ...]."""

    return [(format_rate(rate), f"{format_rate(rate)}%") for rate in GST_RATES]


def is_allowed_rate(rate):
    """True when `rate` is one of the current slabs."""

    try:
        return Decimal(rate) in GST_RATES
    except (InvalidOperation, TypeError, ValueError):
        return False


def is_known_rate(rate):
    """Current or legacy slab (used only to keep old data unchanged)."""

    try:
        rate = Decimal(rate)
    except (InvalidOperation, TypeError, ValueError):
        return False
    return rate in GST_RATES or rate in LEGACY_GST_RATES


def parse_rate(value):
    """
    Read a GST rate from a form value.

    Accepts plain numbers ("5", "0.25", "18.00") and, for older forms,
    the codes "none" and "gstN". Returns a Decimal, or raises ValueError
    when the value is not a number or not a current slab.
    """

    text = str(value if value is not None else "").strip().lower()

    if text in ("", "none"):
        text = "0"
    elif text.startswith("gst"):
        text = text[3:]

    try:
        rate = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid GST rate.")

    if not rate.is_finite() or rate not in GST_RATES:
        allowed = ", ".join(f"{format_rate(r)}%" for r in GST_RATES)
        raise ValueError(f"GST must be one of: {allowed}.")

    return rate
