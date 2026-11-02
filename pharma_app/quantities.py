"""
Stock and line quantities.

Quantities are Decimals with up to 3 decimal places (0.001 kg = 1 g).
Whether a shop may use fractions (2.5 kg, 1.5 m) is a feature:
features.decimal_quantity. Shops without it work in whole units only.

    qty = parse_quantity(request.POST.get("qty"), "Quantity",
                         allow_fraction=features.decimal_quantity)

    {{ product.current_stock|qty }}   ->  "2.5", "10"   (templatetags/qty.py)
"""

from decimal import Decimal, InvalidOperation
from django.utils.translation import gettext

QUANTITY_PLACES = 3
QUANTITY_STEP = Decimal("0.001")


class QuantityError(ValueError):
    """A quantity the user typed is not acceptable (message is user-friendly)."""


def parse_quantity(value, label, *, allow_fraction, allow_zero=False, default=None):
    """
    Read a quantity from a form value.

    - empty -> `default` (or an error when no default is given)
    - must be a finite number, not negative
    - zero only when allow_zero=True
    - at most 3 decimal places
    - whole number unless allow_fraction=True
    Returns a Decimal with 3 decimal places.
    """

    text = "" if value is None else str(value).strip()

    if text == "":
        if default is not None:
            return Decimal(default).quantize(QUANTITY_STEP)
        raise QuantityError((gettext('%(label)s is required.') % {'label': label}))

    try:
        quantity = Decimal(text)
    except (InvalidOperation, ValueError):
        raise QuantityError((gettext('%(label)s must be a valid number.') % {'label': label}))

    if not quantity.is_finite():
        raise QuantityError((gettext('%(label)s must be a valid number.') % {'label': label}))

    if quantity < 0:
        raise QuantityError((gettext('%(label)s cannot be negative.') % {'label': label}))

    if quantity == 0 and not allow_zero:
        raise QuantityError((gettext('%(label)s must be greater than zero.') % {'label': label}))

    if quantity.normalize().as_tuple().exponent < -QUANTITY_PLACES:
        raise QuantityError((gettext('%(label)s can have at most %(QUANTITY_PLACES)s decimal places.') % {'label': label, 'QUANTITY_PLACES': QUANTITY_PLACES}))

    if not allow_fraction and quantity != quantity.to_integral_value():
        raise QuantityError((gettext('%(label)s must be a whole number for this shop.') % {'label': label}))

    return quantity.quantize(QUANTITY_STEP)


def format_quantity(value):
    """Decimal('10.000') -> '10', Decimal('2.500') -> '2.5', None -> '0'."""

    if value is None or value == "":
        return "0"

    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)

    if quantity == quantity.to_integral_value():
        return str(quantity.quantize(Decimal("1")))

    return format(quantity.normalize(), "f")


def quantity_input_attrs(features):
    """step/min for <input type=number> quantity fields of a shop."""

    if features.decimal_quantity:
        return {"step": "0.001", "min": "0.001"}
    return {"step": "1", "min": "1"}
