"""
{% load qty %}

    {{ product.current_stock|qty }}           -> "10", "2.5"
    {{ product.current_stock|qty_unit:product.unit.short_name }}  -> "2.5 kg"
"""

from django import template

from ..quantities import format_quantity

register = template.Library()


@register.filter
def qty(value):
    """Clean quantity: no trailing zeros (10.000 -> 10, 2.500 -> 2.5)."""

    return format_quantity(value)


@register.filter
def qty_unit(value, unit):
    """Quantity with its unit: '2.5 kg', '10 pcs'."""

    text = format_quantity(value)
    return f"{text} {unit}".strip() if unit else text
