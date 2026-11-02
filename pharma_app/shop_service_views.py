"""
Shop Types page (admin only): switch a whole shop type ON or OFF.

OFF hides that type's shops and all their records for everyone and
signs their owners out. Nothing is deleted; ON brings everything back.
See shop_services.py for how the hiding works.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from .models import (
    Customer,
    Product,
    Purchase,
    Retailer,
    Sale,
    ShopTypeService,
    Supplier,
)
from .shop_services import clear_request_cache, inactive_shop_types, set_request_cache
from .shop_types import SHOP_TYPE_CHOICES, SHOP_TYPE_LABELS, shop_type_feature_labels
from .views import _is_admin

logger = logging.getLogger("pharma_app")

LOGIN_URL = "/user-login/"


def _counts(model, lookup):
    """{shop type: number of rows}, switched-off types included."""

    return dict(
        model.all_objects.values_list(lookup).annotate(total=Count("id")).order_by()
    )


def _service_rows():
    services = {row.shop_type: row for row in ShopTypeService.all_objects.select_related("changed_by")}

    shops = _counts(Retailer, "shop_type")
    products = _counts(Product, "retailer__shop_type")
    sales = _counts(Sale, "retailer__shop_type")
    purchases = _counts(Purchase, "retailer__shop_type")
    customers = _counts(Customer, "retailer__shop_type")
    suppliers = _counts(Supplier, "retailer__shop_type")
    feature_labels = shop_type_feature_labels()

    rows = []
    for code, label in SHOP_TYPE_CHOICES:
        service = services.get(code)
        rows.append({
            "code": code,
            "label": label,
            "is_active": service.is_active if service else True,
            "changed_at": service.changed_at if service else None,
            "changed_by": service.changed_by if service else None,
            "shops": shops.get(code, 0),
            "products": products.get(code, 0),
            "sales": sales.get(code, 0),
            "purchases": purchases.get(code, 0),
            "customers": customers.get(code, 0),
            "suppliers": suppliers.get(code, 0),
            "features": feature_labels.get(code, []),
        })
    return rows


@login_required(login_url=LOGIN_URL)
def shop_type_services(request):
    if not _is_admin(request.user):
        messages.error(request, gettext("Only the admin can switch shop types on or off."))
        return redirect("dashboard")

    rows = _service_rows()
    return render(request, "shop_type_services.html", {
        "rows": rows,
        "active_count": sum(1 for row in rows if row["is_active"]),
        "paused_count": sum(1 for row in rows if not row["is_active"]),
    })


@require_POST
@login_required(login_url=LOGIN_URL)
def shop_type_service_toggle(request, shop_type):
    if not _is_admin(request.user):
        messages.error(request, gettext("Only the admin can switch shop types on or off."))
        return redirect("dashboard")

    if shop_type not in SHOP_TYPE_LABELS:
        messages.error(request, gettext("Please select a valid shop type."))
        return redirect("shop_type_services")

    action = request.POST.get("action", "")
    if action not in ("on", "off"):
        messages.error(request, gettext("Please choose to switch the service on or off."))
        return redirect("shop_type_services")

    turn_on = action == "on"

    with transaction.atomic():
        service, _ = ShopTypeService.all_objects.select_for_update().get_or_create(shop_type=shop_type)
        service.is_active = turn_on
        service.changed_by = request.user
        service.save()

    # The rest of this request must see the new setting.
    clear_request_cache()
    set_request_cache(inactive_shop_types())

    label = gettext(SHOP_TYPE_LABELS[shop_type])
    logger.info("Shop type %s switched %s by %s", shop_type, action, request.user.username)

    if turn_on:
        messages.success(request, gettext(
            "The %(label)s service is on again. Its shops and records are visible."
        ) % {"label": label})
    else:
        messages.success(request, gettext(
            "The %(label)s service is paused. Its shops and records are hidden and nothing was deleted."
        ) % {"label": label})

    return redirect("shop_type_services")
