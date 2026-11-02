"""
Unit conversion: buy in one unit, stock and sell in another.

    Product.unit              base unit (stocked and sold in it), e.g. "pc"
    Product.purchase_unit     optional bigger unit it is bought in, e.g. "Box"
    Product.conversion_factor base units in one purchase unit, e.g. 100

Only active for shops with features.unit_conversion. When the feature is
off, every quantity is in the base unit (factor 1).
"""

from decimal import Decimal, InvalidOperation

from .quantities import QUANTITY_PLACES, QUANTITY_STEP, QuantityError
from django.utils.translation import gettext

ONE = Decimal("1")


def conversion_factor_for(product, unit, features):
    """
    Base units in one `unit` of `product` for a purchase line.

    Returns the product's factor when the line is entered in the
    product's purchase unit and the shop uses unit conversion;
    otherwise 1 (the line is in base units).
    """

    if (
        features.unit_conversion
        and product.has_purchase_unit
        and unit is not None
        and unit.id == product.purchase_unit_id
    ):
        return product.conversion_factor

    return ONE


def to_base_quantity(quantity, factor, label, *, allow_fraction):
    """
    quantity x factor in base units, with at most 3 decimals and, for
    shops without loose quantities, a whole number.
    """

    base = Decimal(quantity) * Decimal(factor)

    if base.normalize().as_tuple().exponent < -QUANTITY_PLACES:
        raise QuantityError((gettext('%(label)s gives more than %(QUANTITY_PLACES)s decimal places in base units.') % {'label': label, 'QUANTITY_PLACES': QUANTITY_PLACES}))

    if not allow_fraction and base != base.to_integral_value():
        raise QuantityError((gettext('%(label)s must come to a whole number of base units for this shop.') % {'label': label}))

    return base.quantize(QUANTITY_STEP)


def clean_purchase_unit(base_unit_id, purchase_unit_id, factor_value, features, units):
    """
    Validate a product's purchase unit + conversion factor from a form.

    `units` is the Unit queryset/model used to look the unit up.
    Returns (purchase_unit or None, factor). With the feature off, or no
    purchase unit chosen, the product has no purchase unit (factor 1).
    Raises QuantityError with a user-friendly message.
    """

    purchase_unit_id = (str(purchase_unit_id or "")).strip()

    if not features.unit_conversion or not purchase_unit_id:
        return None, ONE

    if not purchase_unit_id.isdigit():
        raise QuantityError(gettext('Please select a valid purchase unit.'))

    purchase_unit = units.filter(pk=purchase_unit_id).first()

    if purchase_unit is None:
        raise QuantityError(gettext('Please select a valid purchase unit.'))

    if str(purchase_unit.id) == str(base_unit_id):
        raise QuantityError(gettext('Purchase unit must be different from the selling unit.'))

    text = (str(factor_value or "")).strip()

    try:
        factor = Decimal(text)
    except (InvalidOperation, ValueError):
        raise QuantityError(gettext('Enter how many selling units are in one purchase unit.'))

    if not factor.is_finite() or factor <= ONE:
        raise QuantityError(gettext('Conversion must be more than 1 (e.g. 1 Box = 100 pc).'))

    if factor.normalize().as_tuple().exponent < -QUANTITY_PLACES:
        raise QuantityError((gettext('Conversion can have at most %(QUANTITY_PLACES)s decimal places.') % {'QUANTITY_PLACES': QUANTITY_PLACES}))

    if not features.decimal_quantity and factor != factor.to_integral_value():
        raise QuantityError(gettext('Conversion must be a whole number for this shop.'))

    return purchase_unit, factor.quantize(QUANTITY_STEP)
