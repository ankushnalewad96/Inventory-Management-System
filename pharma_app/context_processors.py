"""
Template context available on every page.

    features         -> on/off switches (see shop_types.py)
    shop_type        -> "pharmacy", ... (None for the admin)
    shop_type_label  -> "Pharmacy", ...
    current_shop     -> the logged-in retailer's shop (None for the admin)

A retailer gets their own shop's features. The admin manages every shop,
so their menus show the union of the features of the active shops that
exist (e.g. a Quotations menu once there is a hardware shop); server-side
checks for a particular shop still use get_features(that_shop).
"""

from django.conf import settings

from .shop_types import SHOP_TYPE_LABELS, features_for_types, get_features

_CACHE_ATTR = "_shop_features_context"


def app_branding(request):
    """`app_name` on every page, from settings.APP_DISPLAY_NAME."""

    return {"app_name": getattr(settings, "APP_DISPLAY_NAME", "DukaanPro")}


def shop_features(request):
    user = getattr(request, "user", None)

    if user is None or not user.is_authenticated:
        return {}

    # Templates can render several times per request; look the shop up once.
    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None:
        return cached

    if user.is_superuser:
        from .models import Retailer  # avoid importing models at settings load

        # Menus for the features of the shops that exist: no Quotations
        # menu until there is a shop that uses quotations, and so on.
        shop_types = (
            Retailer.objects.filter(is_active=True)
            .values_list("shop_type", flat=True)
            .distinct()
        )
        context = {
            "features": features_for_types(shop_types),
            "shop_type": None,
            "shop_type_label": "",
            "current_shop": None,
        }
    else:
        from .models import Retailer  # avoid importing models at settings load

        shop = Retailer.objects.filter(user=user, is_active=True).first()
        features = get_features(shop)
        context = {
            "features": features,
            "shop_type": features.shop_type,
            "shop_type_label": SHOP_TYPE_LABELS.get(features.shop_type, ""),
            "current_shop": shop,
        }

    setattr(request, _CACHE_ATTR, context)
    return context
