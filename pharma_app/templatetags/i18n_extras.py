"""
{{ value|tr }}  - show a stored value (status, payment type, shop type,
choice label...) in the user's language. Empty values stay as they are,
so {{ purchase.payment_type|tr|default:"—" }} is safe.

The words themselves are in the translation files (see
build_translations: stored_value_labels).
"""

from django import template
from django.utils.translation import gettext

register = template.Library()


@register.filter
def tr(value):
    if value in (None, ""):
        return value
    return gettext(str(value))
