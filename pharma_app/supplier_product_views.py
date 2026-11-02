"""
Supplier products: which products the shop buys from which supplier.

    supplier_product_list    -> list with filters, and a small "link" form
    supplier_product_add     -> POST, link a product to a supplier
    supplier_product_remove  -> POST, remove a link

Access: a retailer sees and changes only their own shop's links.
The admin sees every shop and can filter by shop type, shop and supplier.

Links are also added automatically whenever a purchase bill is saved.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .account_views import _scope
from .models import Product, Retailer, Supplier, SupplierProduct
from .shop_services import active_shop_type_choices
from .shop_types import SHOP_TYPE_LABELS
from .views import _is_admin, _querystring_without_page, link_supplier_product
from django.utils.translation import gettext

logger = logging.getLogger("pharma_app")

LOGIN_URL = "/user-login/"


def _back_to_list(request):
    """Return to the list with the filters the user had."""

    next_query = (request.POST.get("next") or "").strip()
    url = reverse("supplier_product_list")
    return redirect(f"{url}?{next_query}" if next_query and "//" not in next_query else url)


@login_required(login_url=LOGIN_URL)
def supplier_product_list(request):
    is_admin = _is_admin(request.user)

    links = _scope(
        SupplierProduct.objects.select_related(
            "retailer", "supplier", "product", "product__unit", "product__category"
        ),
        request.user,
    )
    suppliers = _scope(Supplier.objects.filter(is_active=True), request.user)
    products = _scope(Product.objects.filter(is_active=True).select_related("unit"), request.user)

    if links is None:
        messages.error(request, gettext('No active retailer profile is linked to your account.'))
        return redirect("dashboard")

    search = (request.GET.get("search") or "").strip()
    supplier_id = (request.GET.get("supplier") or "").strip()
    retailer_id = (request.GET.get("retailer") or "").strip()
    shop_type = (request.GET.get("shop_type") or "").strip()

    if is_admin and shop_type in SHOP_TYPE_LABELS:
        links = links.filter(retailer__shop_type=shop_type)
        suppliers = suppliers.filter(retailer__shop_type=shop_type)
    else:
        shop_type = ""

    if is_admin and retailer_id.isdigit():
        links = links.filter(retailer_id=retailer_id)
        suppliers = suppliers.filter(retailer_id=retailer_id)
    else:
        retailer_id = ""

    selected_supplier = None
    if supplier_id.isdigit():
        selected_supplier = suppliers.filter(pk=supplier_id).first()
    if selected_supplier is not None:
        links = links.filter(supplier=selected_supplier)
    else:
        supplier_id = ""

    if search:
        links = links.filter(
            Q(product__product_name__icontains=search)
            | Q(product__barcode__icontains=search)
            | Q(supplier__supplier_name__icontains=search)
        )

    page_obj = Paginator(
        links.order_by("supplier__supplier_name", "product__product_name"), 25
    ).get_page(request.GET.get("page"))

    # Products that can still be linked to the chosen supplier.
    linkable_products = []
    if selected_supplier is not None:
        linked_ids = selected_supplier.supplier_products.values_list("product_id", flat=True)
        linkable_products = (
            products.filter(retailer_id=selected_supplier.retailer_id)
            .exclude(pk__in=linked_ids)
            .order_by("product_name")
        )

    return render(request, "supplier_product_list.html", {
        "links": page_obj,
        "page_obj": page_obj,
        "is_admin": is_admin,
        "search": search,
        "suppliers": suppliers.select_related("retailer").order_by("supplier_name"),
        "selected_supplier": selected_supplier,
        "supplier_id": supplier_id,
        "retailers": Retailer.objects.filter(is_active=True).order_by("shop_name") if is_admin else [],
        "retailer_id": retailer_id,
        "shop_type": shop_type,
        "shop_type_choices": active_shop_type_choices(),
        "linkable_products": linkable_products,
        "querystring": _querystring_without_page(request),
        "current_query": request.GET.urlencode(),
    })


@require_POST
@login_required(login_url=LOGIN_URL)
def supplier_product_add(request):
    suppliers = _scope(Supplier.objects.filter(is_active=True), request.user)
    products = _scope(Product.objects.filter(is_active=True), request.user)

    if suppliers is None:
        raise Http404("Not found.")

    supplier_id = (request.POST.get("supplier") or "").strip()
    product_ids = [value for value in request.POST.getlist("product") if value.isdigit()]

    supplier = suppliers.filter(pk=supplier_id).first() if supplier_id.isdigit() else None

    if supplier is None:
        messages.error(request, gettext('Please select a supplier.'))
        return _back_to_list(request)

    chosen = list(products.filter(pk__in=product_ids, retailer_id=supplier.retailer_id))

    if not chosen:
        messages.error(request, gettext("Please select at least one product of this supplier's shop."))
        return _back_to_list(request)

    try:
        for product in chosen:
            link_supplier_product(supplier, product)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return _back_to_list(request)

    logger.info(
        "Supplier products linked. supplier_id=%s products=%s user_id=%s",
        supplier.id, [product.id for product in chosen], request.user.id,
    )
    messages.success(request, (gettext('%(chosen)s product(s) added to %(supplier_name)s.') % {'chosen': len(chosen), 'supplier_name': supplier.supplier_name}))
    return _back_to_list(request)


@require_POST
@login_required(login_url=LOGIN_URL)
def supplier_product_remove(request, link_id):
    links = _scope(SupplierProduct.objects.select_related("supplier", "product"), request.user)

    if links is None:
        raise Http404("Not found.")

    link = get_object_or_404(links, pk=link_id)
    name = f"{link.product.product_name} from {link.supplier.supplier_name}"
    link.delete()

    logger.info("Supplier product removed. link_id=%s user_id=%s", link_id, request.user.id)
    messages.success(request, (gettext('Removed %(name)s. Past bills are not changed.') % {'name': name}))
    return _back_to_list(request)
