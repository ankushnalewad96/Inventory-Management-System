"""
Shop type services: the admin can switch a whole shop type off and on.

While a shop type is OFF:
    - its shops and every record of those shops are hidden everywhere
      (pages, totals, dashboard, Django admin) for every user, admin too;
    - owners of those shops are signed out and cannot sign in;
    - no new shop of that type can be registered.
Nothing is deleted. Switching the type ON shows everything again.

How the hiding works: every shop-owned model uses ShopScopedManager as
its default manager (`Model.objects`). It leaves out rows whose shop type
is switched off. `Model.all_objects` still sees everything (used only by
the service switch page and maintenance code).

The list of switched-off types is read once per request (see
ShopServiceMiddleware) instead of on every query.
"""

import threading

from django.contrib import messages
from django.contrib.auth import logout
from django.db import models
from django.shortcuts import redirect
from django.utils.translation import gettext

_state = threading.local()


def inactive_shop_types():
    """Shop types switched off right now (a frozenset of codes)."""

    cached = getattr(_state, "inactive", None)
    if cached is not None:
        return cached

    from .models import ShopTypeService  # models import this module

    try:
        return frozenset(
            ShopTypeService.all_objects.filter(is_active=False).values_list("shop_type", flat=True)
        )
    except Exception:
        # Table not created yet (first migrate) -> nothing is switched off.
        return frozenset()


def set_request_cache(value):
    _state.inactive = value


def clear_request_cache():
    _state.inactive = None


def is_shop_type_active(shop_type):
    return shop_type not in inactive_shop_types()


def active_shop_type_choices():
    """Shop type choices without the types the admin has switched off."""

    from .shop_types import SHOP_TYPE_CHOICES

    inactive = inactive_shop_types()
    return [(code, label) for code, label in SHOP_TYPE_CHOICES if code not in inactive]


class ShopScopedQuerySet(models.QuerySet):
    pass


class ShopScopedManager(models.Manager.from_queryset(ShopScopedQuerySet)):
    """
    Default manager of shop-owned models: hides rows of switched-off shop
    types. `lookup` is the path to the shop type, e.g. "retailer__shop_type"
    or "sale__retailer__shop_type".
    """

    lookup = None

    def __init__(self, lookup=None):
        super().__init__()
        if lookup:
            self.lookup = lookup

    def deconstruct(self):
        # Managers are not used in migrations; keep the constructor argument.
        name, path, args, kwargs = super().deconstruct()
        return name, path, [self.lookup], kwargs

    def _shop_type_lookup(self):
        # Reverse relations (e.g. purchase.payments) build this manager
        # again without arguments; take the lookup from the model then.
        if self.lookup:
            return self.lookup
        return getattr(self.model._default_manager, "lookup", None)

    def get_queryset(self):
        queryset = super().get_queryset()
        inactive = inactive_shop_types()
        lookup = self._shop_type_lookup()
        if inactive and lookup:
            queryset = queryset.exclude(**{f"{lookup}__in": list(inactive)})
        return queryset


class ShopServiceMiddleware:
    """
    Per request: remember which shop types are off, and sign out owners
    of a switched-off shop type.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_request_cache()
        inactive = inactive_shop_types()
        set_request_cache(inactive)

        try:
            user = getattr(request, "user", None)
            if inactive and user is not None and user.is_authenticated and not user.is_superuser:
                from .models import Retailer

                shop = Retailer.all_objects.filter(user=user).only("shop_type").first()
                if shop is not None and shop.shop_type in inactive:
                    logout(request)
                    messages.error(request, service_paused_message(shop.shop_type))
                    return redirect("user_login")

            return self.get_response(request)
        finally:
            clear_request_cache()


def service_paused_message(shop_type):
    from .shop_types import SHOP_TYPE_LABELS

    label = gettext(SHOP_TYPE_LABELS.get(shop_type, shop_type))
    return gettext(
        "The %(label)s service is paused by the admin. Please contact the admin."
    ) % {"label": label}
