"""
Quotations / estimates (features.quotations, e.g. hardware shops).

    quotation_list    -> list with filters
    quotation_create  -> new quotation (no stock or account changes)
    quotation_detail  -> view, cancel, print, convert to sale
    quotation_print   -> printable page
    quotation_cancel  -> POST, open quotations only

Converting uses the normal sales screen (sale_create?quotation=<id>), so
stock checks, payments and the customer ledger work exactly like any
other sale; the sale keeps the quoted prices and the quotation is marked
converted in the same transaction.

Access: a retailer sees only their own shop (and only when the feature
is on); the admin sees every shop that has the feature.
"""

import logging
import re
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Customer, Product, Quotation, QuotationItem
from .pharmacy_views import feature_not_available, shops_with_feature
from .quantities import QuantityError, format_quantity, parse_quantity
from .shop_types import get_features
from .views import (
    _is_admin,
    _querystring_without_page,
    calculate_sale_totals,
    decimal_value,
    product_rules_by_shop,
)
from django.utils.translation import gettext

logger = logging.getLogger("pharma_app")

LOGIN_URL = "/user-login/"
TWO_PLACES = Decimal("0.01")
DEFAULT_VALID_DAYS = 15


def _quotation_shops(request):
    """Shops whose quotations this user may see, or None (with a message)."""

    shops = shops_with_feature(request.user, "quotations")

    if not shops:
        feature_not_available(request, "quotations", "Quotations")
        return None

    return shops


def _get_quotation(request, quotation_id):
    shops = shops_with_feature(request.user, "quotations")

    if not shops:
        raise Http404("Quotation not found.")

    return get_object_or_404(
        Quotation.objects
        .select_related("retailer", "customer", "converted_sale")
        .prefetch_related("items__product", "items__unit"),
        pk=quotation_id,
        retailer__in=shops,
    )


# ================================================================ LIST

@login_required(login_url=LOGIN_URL)
def quotation_list(request):
    shops = _quotation_shops(request)
    if shops is None:
        return redirect("dashboard")

    search = (request.GET.get("search") or "").strip()
    status = (request.GET.get("status") or "").strip()

    quotations = (
        Quotation.objects
        .filter(retailer__in=shops)
        .select_related("retailer", "customer", "converted_sale")
    )

    if search:
        quotations = quotations.filter(
            Q(quotation_number__icontains=search)
            | Q(customer__customer_name__icontains=search)
            | Q(customer__mobile__icontains=search)
        )

    if status in dict(Quotation.STATUS_CHOICES):
        quotations = quotations.filter(status=status)

    page_obj = Paginator(quotations.order_by("-quotation_date", "-id"), 25).get_page(request.GET.get("page"))

    today = date.today()
    for quotation in page_obj:
        quotation.expired = quotation.is_expired(today)

    all_quotations = Quotation.objects.filter(retailer__in=shops)

    return render(request, "quotation_list.html", {
        "quotations": page_obj,
        "page_obj": page_obj,
        "search": search,
        "status": status,
        "status_choices": Quotation.STATUS_CHOICES,
        "is_admin": _is_admin(request.user),
        "querystring": _querystring_without_page(request),
        "open_count": all_quotations.filter(status=Quotation.STATUS_OPEN).count(),
        "converted_count": all_quotations.filter(status=Quotation.STATUS_CONVERTED).count(),
    })


# ================================================================ CREATE

def _read_rows(post):
    """Row numbers of items[N][product] fields, in order."""

    rows = set()
    for key in post.keys():
        match = re.match(r"^items\[(\d+)\]\[product\]$", key)
        if match:
            rows.add(match.group(1))
    return sorted(rows, key=int)


def _clean_quotation(request, shop):
    """Validate the posted quotation. Returns (customer, valid_until, remarks, lines)."""

    features = get_features(shop)

    customer_id = (request.POST.get("customer") or "").strip()
    customer = (
        Customer.objects.filter(pk=customer_id, retailer=shop, is_active=True).first()
        if customer_id.isdigit() else None
    )
    if customer is None:
        raise ValidationError(gettext('Please select a customer.'))

    valid_until = None
    raw_valid = (request.POST.get("valid_until") or "").strip()
    if raw_valid:
        try:
            valid_until = date.fromisoformat(raw_valid)
        except ValueError:
            raise ValidationError(gettext("Enter a valid 'valid until' date."))
        if valid_until < date.today():
            raise ValidationError(gettext("'Valid until' cannot be in the past."))

    remarks = (request.POST.get("remarks") or "").strip()

    rows = _read_rows(request.POST)
    if not rows:
        raise ValidationError(gettext('Please add at least one product.'))

    lines = []
    seen = set()

    for row in rows:
        product_id = (request.POST.get(f"items[{row}][product]") or "").strip()
        if not product_id:
            continue

        product = (
            Product.objects.filter(pk=product_id, retailer=shop, is_active=True)
            .select_related("unit").first()
            if product_id.isdigit() else None
        )
        if product is None:
            raise ValidationError((gettext('Product in row %(row)s does not exist.') % {'row': row}))

        if product.id in seen:
            raise ValidationError((gettext("'%(product_name)s' is added more than once.") % {'product_name': product.product_name}))
        seen.add(product.id)

        try:
            quantity = parse_quantity(
                request.POST.get(f"items[{row}][quantity]"),
                (gettext("Quantity for '%(product_name)s'") % {'product_name': product.product_name}),
                allow_fraction=features.decimal_quantity,
            )
        except QuantityError as exc:
            raise ValidationError(str(exc))

        # Quoted price: may be negotiated; empty = this customer's price.
        raw_price = (request.POST.get(f"items[{row}][selling_price]") or "").strip()
        if raw_price:
            price = decimal_value(raw_price, (gettext('Price for %(product_name)s') % {'product_name': product.product_name}))
        else:
            price = Decimal(str(product.price_for(customer, features))).quantize(TWO_PLACES)

        if price <= 0:
            raise ValidationError((gettext("Price for '%(product_name)s' must be greater than 0.") % {'product_name': product.product_name}))

        if product.mrp is not None and price > product.mrp:
            raise ValidationError((gettext("Price for '%(product_name)s' cannot be more than MRP ₹%(mrp)s.") % {'product_name': product.product_name, 'mrp': product.mrp}))

        if price < product.purchase_price and not features.allow_below_cost_sale:
            raise ValidationError(
                (gettext("Price for '%(product_name)s' cannot be below the purchase price.") % {'product_name': product.product_name})
            )

        discount = decimal_value(
            request.POST.get(f"items[{row}][discount]"), (gettext('Discount for %(product_name)s') % {'product_name': product.product_name})
        )

        if discount > (quantity * price).quantize(TWO_PLACES):
            raise ValidationError((gettext("Discount for '%(product_name)s' is more than the line amount.") % {'product_name': product.product_name}))

        lines.append({
            "product": product,
            "quantity": quantity,
            "selling_price": price,
            "mrp": product.mrp,
            "gst": Decimal(str(product.gst or 0)).quantize(TWO_PLACES),
            "discount": discount,
        })

    if not lines:
        raise ValidationError(gettext('Please add at least one product.'))

    return customer, valid_until, remarks, lines


@login_required(login_url=LOGIN_URL)
def quotation_create(request):
    shops = _quotation_shops(request)
    if shops is None:
        return redirect("dashboard")

    is_admin = _is_admin(request.user)

    if request.method == "POST":
        try:
            if is_admin:
                shop_id = (request.POST.get("retailer") or "").strip()
                shop = next((s for s in shops if str(s.id) == shop_id), None)
                if shop is None:
                    raise ValidationError(gettext('Please select a shop that uses quotations.'))
            else:
                shop = shops[0]

            customer, valid_until, remarks, lines = _clean_quotation(request, shop)
            totals = calculate_sale_totals(lines)

            with transaction.atomic():
                quotation = Quotation.objects.create(
                    retailer=shop,
                    customer=customer,
                    quotation_date=date.today(),
                    valid_until=valid_until,
                    remarks=remarks,
                    subtotal=totals["subtotal"],
                    discount=totals["discount"],
                    gst=totals["gst"],
                    grand_total=totals["grand_total"],
                )

                for line in lines:
                    QuotationItem.objects.create(
                        quotation=quotation,
                        product=line["product"],
                        unit=line["product"].unit,
                        quantity=line["quantity"],
                        selling_price=line["selling_price"],
                        mrp=line["mrp"],
                        gst=line["gst"],
                        discount=line["discount"],
                    )

            logger.info(
                "Quotation created. quotation_id=%s number=%s user_id=%s retailer_id=%s",
                quotation.id, quotation.quotation_number, request.user.id, shop.id,
            )
            messages.success(request, (gettext('Quotation %(quotation_number)s created.') % {'quotation_number': quotation.quotation_number}))

            if request.POST.get("action") == "save_print":
                return redirect("quotation_print", quotation_id=quotation.id)

            return redirect("quotation_detail", quotation_id=quotation.id)

        except ValidationError as exc:
            error = " ".join(str(message) for message in exc.messages)
            logger.warning("Quotation validation failed. user_id=%s error=%s", request.user.id, error)
            messages.error(request, error)

        except IntegrityError:
            logger.exception("Quotation could not be saved. user_id=%s", request.user.id)
            messages.error(request, gettext('Could not save the quotation. Please try again.'))

        return redirect("quotation_create")

    customers = (
        Customer.objects.filter(retailer__in=shops, is_active=True)
        .order_by("customer_name")
    )
    products = (
        Product.objects.filter(retailer__in=shops, is_active=True)
        .select_related("unit")
        .order_by("product_name")
    )

    products_data = [
        {
            "id": product.id,
            "shop": product.retailer_id,
            "name": product.product_name,
            "specification": product.specification,
            "unit": product.unit.short_name if product.unit_id else "",
            "price": str(product.selling_price),
            "wholesale_price": str(product.wholesale_price) if product.wholesale_price is not None else "",
            "mrp": str(product.mrp) if product.mrp is not None else "",
            "gst": str(product.gst or 0),
            "stock": format_quantity(product.current_stock),
        }
        for product in products
    ]

    return render(request, "quotation_create.html", {
        "shops": shops,
        "is_admin": is_admin,
        "customers": customers,
        "products_data": products_data,
        "shop_rules": product_rules_by_shop(shops),
        "default_valid_until": date.today() + timedelta(days=DEFAULT_VALID_DAYS),
        "today": date.today(),
    })


# ================================================================ DETAIL / PRINT / CANCEL

@login_required(login_url=LOGIN_URL)
def quotation_detail(request, quotation_id):
    quotation = _get_quotation(request, quotation_id)

    return render(request, "quotation_detail.html", {
        "quotation": quotation,
        "items": quotation.items.all(),
        "expired": quotation.is_expired(date.today()),
        "shop_features": get_features(quotation.retailer),
        "convert_url": reverse("sale_create") + f"?quotation={quotation.id}",
    })


@login_required(login_url=LOGIN_URL)
def quotation_print(request, quotation_id):
    quotation = _get_quotation(request, quotation_id)

    return render(request, "quotation_print.html", {
        "quotation": quotation,
        "items": quotation.items.all(),
        "shop_features": get_features(quotation.retailer),
    })


@require_POST
@login_required(login_url=LOGIN_URL)
def quotation_cancel(request, quotation_id):
    quotation = _get_quotation(request, quotation_id)

    with transaction.atomic():
        locked = Quotation.objects.select_for_update().get(pk=quotation.pk)

        if locked.status != Quotation.STATUS_OPEN:
            messages.error(request, gettext('Only open quotations can be cancelled.'))
        else:
            locked.status = Quotation.STATUS_CANCELLED
            locked.save(update_fields=["status", "updated_at"])
            logger.info("Quotation cancelled. quotation_id=%s user_id=%s", locked.id, request.user.id)
            messages.success(request, (gettext('Quotation %(quotation_number)s cancelled.') % {'quotation_number': locked.quotation_number}))

    return redirect("quotation_detail", quotation_id=quotation.id)
