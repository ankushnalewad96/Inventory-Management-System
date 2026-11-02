"""
Pharmacy pages, each switched on by a feature (never by shop type):

    near_expiry   -> features.expiry_tracking
    h1_register   -> features.prescription_details

Access: a retailer sees only their own shop (and only when the feature is
on for it); the admin sees every shop that has the feature.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from .models import Product, ProductBatch, Retailer, SaleItem
from .shop_types import get_features, shop_type_labels_with
from .views import _get_user_retailer, _is_admin, _parse_date, _querystring_without_page
from django.utils.translation import gettext

logger = logging.getLogger("pharma_app")

LOGIN_URL = "/user-login/"

EXPIRY_WINDOWS = (30, 60, 90)
DEFAULT_EXPIRY_WINDOW = 90


def shops_with_feature(user, feature):
    """
    Shops whose data this user may see for a feature page.
    Admin: every active shop with the feature. Retailer: own shop if
    the feature is on, else an empty list.
    """

    if _is_admin(user):
        shops = Retailer.objects.filter(is_active=True)
    else:
        shop = _get_user_retailer(user)
        shops = [shop] if shop is not None else []

    return [shop for shop in shops if getattr(get_features(shop), feature)]


def feature_not_available(request, feature, page_name):
    """
    Explain why a feature page has nothing to show, then go to the
    dashboard. The admin is told which shop types use it.
    """

    if _is_admin(request.user):
        types = " / ".join(shop_type_labels_with(feature))
        messages.info(
            request,
            (gettext('%(page_name)s is used by %(types)s shops. No such shop is registered yet; it will show here as soon as one is.') % {'page_name': page_name, 'types': types}),
        )
    else:
        messages.error(request, (gettext('%(page_name)s is not used in your shop type.') % {'page_name': page_name}))

    return redirect("dashboard")


def expiry_summary(shops, today=None):
    """Counts for the dashboard card: near expiry (90 days) and expired batches."""

    today = today or date.today()
    batches = ProductBatch.objects.filter(retailer__in=shops, quantity__gt=0)

    return {
        "near_expiry_count": batches.filter(
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=DEFAULT_EXPIRY_WINDOW),
        ).count(),
        "expired_count": batches.filter(expiry_date__lt=today).count(),
    }


# ================================================================ NEAR EXPIRY

@require_GET
@login_required(login_url=LOGIN_URL)
def near_expiry(request):
    """
    Batches in stock that expire within 30/60/90 days, or have expired.
    ?days=30|60|90 (default 90), ?days=expired for expired stock.
    """

    shops = shops_with_feature(request.user, "expiry_tracking")

    if not shops:
        return feature_not_available(request, "expiry_tracking", "Near Expiry")

    today = date.today()
    window = (request.GET.get("days") or "").strip().lower()
    search = (request.GET.get("search") or "").strip()

    batches = (
        ProductBatch.objects
        .filter(retailer__in=shops, quantity__gt=0)
        .select_related("product", "product__unit", "retailer")
    )

    if window == "expired":
        batches = batches.filter(expiry_date__lt=today)
        days = None
    else:
        days = int(window) if window.isdigit() and int(window) in EXPIRY_WINDOWS else DEFAULT_EXPIRY_WINDOW
        window = str(days)
        batches = batches.filter(
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=days),
        )

    if search:
        batches = batches.filter(
            Q(product__product_name__icontains=search)
            | Q(product__salt_composition__icontains=search)
            | Q(batch_number__icontains=search)
        )

    batches = batches.order_by("expiry_date", "product__product_name")

    # Stock value at purchase price (Decimal; quantities are base units).
    stock_value = sum(
        (batch.quantity * batch.purchase_price for batch in batches),
        Decimal("0"),
    ).quantize(Decimal("0.01"))

    page_obj = Paginator(batches, 25).get_page(request.GET.get("page"))

    for batch in page_obj:
        batch.days_left = (batch.expiry_date - today).days
        batch.cost_value = (batch.quantity * batch.purchase_price).quantize(Decimal("0.01"))

    counts = expiry_summary(shops, today)

    return render(
        request,
        "near_expiry.html",
        {
            "page_obj": page_obj,
            "batches": page_obj.object_list,
            "window": window,
            "windows": EXPIRY_WINDOWS,
            "search": search,
            "stock_value": stock_value,
            "total_count": page_obj.paginator.count,
            "is_admin": _is_admin(request.user),
            "querystring": _querystring_without_page(request),
            **counts,
        },
    )


# ================================================================ H1 REGISTER

@require_GET
@login_required(login_url=LOGIN_URL)
def h1_register(request):
    """
    Schedule H1 register: every sale of a Schedule H1 drug with date,
    invoice, patient, doctor, drug, batch and quantity. Printable.
    Filter by ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD (default: this month).
    """

    shops = shops_with_feature(request.user, "prescription_details")

    if not shops:
        return feature_not_available(request, "prescription_details", "The Schedule H1 register")

    today = date.today()
    date_from = _parse_date(request.GET.get("date_from")) or today.replace(day=1)
    date_to = _parse_date(request.GET.get("date_to")) or today

    if date_from > date_to:
        date_from, date_to = date_to, date_from

    entries = (
        SaleItem.objects
        .filter(
            sale__retailer__in=shops,
            product__schedule=Product.SCHEDULE_H1,
            sale__invoice_date__gte=date_from,
            sale__invoice_date__lte=date_to,
        )
        .select_related("sale", "sale__retailer", "product", "unit", "batch")
        .order_by("sale__invoice_date", "sale__invoice_number", "id")
    )

    total_quantity = entries.aggregate(total=Sum("quantity"))["total"] or Decimal("0")

    return render(
        request,
        "h1_register.html",
        {
            "entries": entries,
            "date_from": date_from,
            "date_to": date_to,
            "total_quantity": total_quantity,
            "is_admin": _is_admin(request.user),
            "shops": shops,
            "print_mode": request.GET.get("print") == "1",
        },
    )
