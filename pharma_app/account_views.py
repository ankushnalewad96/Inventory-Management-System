"""
Pages for:
    - Retailers list (admin only)
    - Purchase bill payments, printable purchase bill and supplier accounts
    - Customer accounts (khata / udhari): history, receiving old dues

Access rules everywhere:
    Admin    -> every retailer shop.
    Retailer -> only their own shop's suppliers, bills and customers.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import accounts
from .models import Customer, Purchase, Retailer, Sale, Supplier
from .shop_services import active_shop_type_choices
from .shop_types import SHOP_TYPE_LABELS, get_features
from .states import STATE_CHOICES, is_inter_state, rate_wise_summary, state_key, state_name
from .views import _get_user_retailer, _is_admin, _querystring_without_page
from django.utils.translation import gettext

logger = logging.getLogger("pharma_app")

LOGIN_URL = "/user-login/"


# ---------------------------------------------------------------- scoping

def _scope(queryset, user, field="retailer"):
    """
    Limit a queryset to the user's shop. Admin sees everything.
    Returns None for a retailer user without an active shop profile.
    """

    if _is_admin(user):
        return queryset

    retailer = _get_user_retailer(user)

    if retailer is None:
        return None

    return queryset.filter(**{field: retailer})


def _get_scoped(queryset, user, pk):
    scoped = _scope(queryset, user)

    if scoped is None:
        raise Http404("Not found.")

    return get_object_or_404(scoped, pk=pk)


def _error_text(exc):
    return " ".join(str(message) for message in exc.messages)


def _payment_form_data(request):
    return {
        "amount": request.POST.get("amount", ""),
        "payment_type": request.POST.get("payment_type", ""),
        "payment_date": request.POST.get("payment_date", ""),
        "reference": request.POST.get("reference", ""),
        "remarks": request.POST.get("remarks", ""),
    }


# ================================================================ RETAILERS

@login_required(login_url=LOGIN_URL)
def retailer_list(request):
    """
    Registered retailer shops. Only the admin can see this page.
    """

    if not _is_admin(request.user):
        messages.error(request, gettext('Only the admin can view the retailers list.'))
        return redirect("dashboard")

    search = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip().lower()
    shop_type = request.GET.get("shop_type", "").strip().lower()

    if shop_type not in SHOP_TYPE_LABELS:
        shop_type = ""

    retailers = Retailer.objects.select_related("user").annotate(
        product_count=Count("products", distinct=True),
        customer_count=Count("customers", distinct=True),
    )

    if search:
        retailers = retailers.filter(
            Q(shop_name__icontains=search)
            | Q(owner_name__icontains=search)
            | Q(user__username__icontains=search)
            | Q(mobile__icontains=search)
            | Q(city__icontains=search)
        )

    if status == "active":
        retailers = retailers.filter(is_active=True)
    elif status == "inactive":
        retailers = retailers.filter(is_active=False)

    if shop_type:
        retailers = retailers.filter(shop_type=shop_type)

    retailers = retailers.order_by("shop_name")

    page_obj = Paginator(retailers, 25).get_page(request.GET.get("page"))

    total_count = Retailer.objects.count()
    active_count = Retailer.objects.filter(is_active=True).count()
    type_counts = dict(
        Retailer.objects.values_list("shop_type").annotate(total=Count("id"))
    )

    return render(request, "retailer_list.html", {
        "retailers": page_obj,
        "page_obj": page_obj,
        "search": search,
        "status": status,
        "querystring": _querystring_without_page(request),
        "total_count": total_count,
        "active_count": active_count,
        "inactive_count": total_count - active_count,
        "shop_type": shop_type,
        "shop_type_choices": active_shop_type_choices(),
        "shop_type_counts": [
            (value, label, type_counts.get(value, 0))
            for value, label in active_shop_type_choices()
        ],
    })


# ================================================================ PURCHASE BILLS

@require_POST
@login_required(login_url=LOGIN_URL)
def purchase_add_payment(request, purchase_id):
    """
    Pay (part of) the balance of a purchase bill - before or after its
    due date. When the balance reaches zero the bill is closed.
    """

    purchase = _get_scoped(Purchase.objects.all(), request.user, purchase_id)

    try:
        payment = accounts.record_purchase_payment(
            purchase,
            amount=request.POST.get("amount"),
            payment_type=request.POST.get("payment_type", ""),
            payment_date=request.POST.get("payment_date"),
            reference=request.POST.get("reference", ""),
            remarks=request.POST.get("remarks", ""),
            user=request.user,
        )

    except ValidationError as exc:
        messages.error(request, _error_text(exc))
        return redirect("purchase_detail", purchase_id=purchase.id)

    purchase.refresh_from_db()

    logger.info(
        "Purchase payment recorded. purchase_id=%s amount=%s user_id=%s",
        purchase.id, payment.amount, request.user.id,
    )

    if purchase.due_amount <= 0:
        messages.success(
            request,
            (gettext('Payment of ₹%(amount)s recorded. Bill %(bill_number)s is now fully paid and closed.') % {'amount': payment.amount, 'bill_number': purchase.bill_number}),
        )
    else:
        messages.success(
            request,
            (gettext('Payment of ₹%(amount)s recorded. Balance due: ₹%(due_amount)s.') % {'amount': payment.amount, 'due_amount': purchase.due_amount}),
        )

    return redirect("purchase_detail", purchase_id=purchase.id)


def purchase_gst_summary(purchase, items):
    """GST per rate on a purchase bill (CGST+SGST or IGST)."""

    return rate_wise_summary(
        [(item.gst, item.quantity * item.purchase_price - (item.discount or 0)) for item in items],
        purchase.tax_type,
    )


@login_required(login_url=LOGIN_URL)
def purchase_invoice(request, purchase_id):
    """
    Printable / downloadable purchase bill with its full payment history.
    ?download=1 downloads it as a PDF.
    """

    purchase = _get_scoped(
        Purchase.objects.select_related("retailer", "supplier"),
        request.user,
        purchase_id,
    )

    items = list(purchase.items.select_related("product", "unit").order_by("id"))

    return render(request, "purchase_invoice.html", {
        "purchase": purchase,
        "items": items,
        "payments": purchase.payments.order_by("payment_date", "id"),
        "purchase_returns": purchase.returns.order_by("return_date", "id"),
        "gst_summary": purchase_gst_summary(purchase, items),
        "today": timezone.localdate(),
        "auto_download": request.GET.get("download") == "1",
        "auto_print": request.GET.get("print") == "1",
    })


# ================================================================ SUPPLIER ACCOUNTS

@login_required(login_url=LOGIN_URL)
def supplier_account(request, supplier_id):
    """
    Supplier account: what the shop owes, open bills, every bill and
    payment (statement).
    """

    supplier = _get_scoped(Supplier.objects.select_related("retailer"), request.user, supplier_id)

    return render(request, "supplier_account.html", {
        "supplier": supplier,
        "account": accounts.supplier_account(supplier),
        "statement": accounts.supplier_statement(supplier),
        "bills": Purchase.objects.filter(supplier=supplier).order_by("-bill_date", "-id"),
        "is_admin": _is_admin(request.user),
    })


@login_required(login_url=LOGIN_URL)
def supplier_statement_print(request, supplier_id):
    supplier = _get_scoped(Supplier.objects.select_related("retailer"), request.user, supplier_id)
    account = accounts.supplier_account(supplier)

    return render(request, "account_statement.html", {
        "kind": "supplier",
        "title": gettext('Supplier Statement'),
        "shop": supplier.retailer,
        "party_label": "Supplier",
        "party_name": supplier.supplier_name,
        "party_lines": [
            f"Mobile: {supplier.mobile}",
            supplier.email or "",
            supplier.address,
            f"{supplier.city}, {supplier.state} - {supplier.pincode}",
            f"GSTIN: {supplier.gst_number}" if supplier.gst_number else "",
        ],
        "summary": [
            ("Total billed", account["billed"]),
            ("Total paid", account["paid"]),
            ("Balance payable", account["due"]),
        ],
        "debit_label": "Bill amount",
        "credit_label": "Paid",
        "balance_label": "Payable",
        "rows": accounts.supplier_statement(supplier),
        "back_url": reverse("supplier_account", args=[supplier.id]),
        "file_name": f"Statement-{supplier.supplier_name}",
        "auto_download": request.GET.get("download") == "1",
        "today": timezone.localdate(),
    })


@require_GET
@login_required(login_url=LOGIN_URL)
def supplier_summary(request, supplier_id):
    """
    JSON for the New Purchase Order page: what is still owed to the
    chosen supplier and its open bills.
    """

    scoped = _scope(Supplier.objects.all(), request.user)
    supplier = scoped.filter(pk=supplier_id).first() if scoped is not None else None

    if supplier is None:
        return JsonResponse({"success": False, "message": gettext('Supplier not found.')}, status=404)

    account = accounts.supplier_account(supplier)
    today = account["today"]

    return JsonResponse({
        "success": True,
        "supplier": supplier.supplier_name,
        "bills": account["bills"],
        "billed": str(account["billed"]),
        "paid": str(account["paid"]),
        "due": str(account["due"]),
        "overdue": str(account["overdue"]),
        "last_payment": (
            {
                "date": account["last_payment"].payment_date.isoformat(),
                "amount": str(account["last_payment"].amount),
            }
            if account["last_payment"] else None
        ),
        "open_bills": [
            {
                "id": bill.id,
                "bill_number": bill.bill_number,
                "bill_date": bill.bill_date.isoformat(),
                "due_date": bill.due_date.isoformat() if bill.due_date else "",
                "total": str(bill.grand_total),
                "due": str(bill.due_amount),
                "overdue": bool(bill.due_date and bill.due_date < today),
                "url": reverse("purchase_detail", args=[bill.id]),
            }
            for bill in account["open_bills"][:5]
        ],
        "open_count": len(account["open_bills"]),
        "account_url": reverse("supplier_account", args=[supplier.id]),
    })


# ================================================================ CUSTOMER ACCOUNTS

@login_required(login_url=LOGIN_URL)
def customer_list(request):
    """
    Customers with their outstanding (udhari) balance.
    """

    is_admin = _is_admin(request.user)
    customers = _scope(Customer.objects.select_related("retailer"), request.user)

    if customers is None:
        messages.error(request, gettext('No active retailer profile is linked to your account.'))
        return redirect("dashboard")

    search = request.GET.get("search", "").strip()
    retailer_id = request.GET.get("retailer", "").strip()
    dues_only = request.GET.get("dues") == "1"

    if search:
        customers = customers.filter(
            Q(customer_name__icontains=search) | Q(mobile__icontains=search)
        )

    if is_admin and retailer_id.isdigit():
        customers = customers.filter(retailer_id=retailer_id)

    customers = accounts.with_customer_totals(customers)

    if dues_only:
        customers = customers.filter(outstanding__gt=0)

    summary = {
        "count": customers.count(),
        "with_dues": customers.filter(outstanding__gt=0).count(),
        "outstanding": sum((c.outstanding for c in customers if c.outstanding > 0), accounts.ZERO),
    }

    customers = customers.order_by("-outstanding", "customer_name")

    page_obj = Paginator(customers, 25).get_page(request.GET.get("page"))

    return render(request, "customer_list.html", {
        "customers": page_obj,
        "page_obj": page_obj,
        "is_admin": is_admin,
        "retailers": Retailer.objects.filter(is_active=True).order_by("shop_name") if is_admin else Retailer.objects.none(),
        "search": search,
        "selected_retailer": retailer_id,
        "dues_only": dues_only,
        "summary": summary,
        "querystring": _querystring_without_page(request),
    })


def _customer_context(customer):
    sales = Sale.objects.filter(customer=customer).order_by("-invoice_date", "-id")
    balance = accounts.customer_balance(customer)
    totals = accounts.with_customer_totals(Customer.objects.filter(pk=customer.pk)).get()

    return {
        "customer": customer,
        "balance": balance,
        "total_billed": totals.total_billed,
        "total_paid": totals.total_paid,
        "invoice_count": totals.invoice_count,
        "open_sales": [sale for sale in sales if sale.due_amount > 0],
        "sales": sales,
        "statement": accounts.customer_statement(customer),
        "available_credit": (
            max(customer.credit_limit - balance, accounts.ZERO)
            if customer.credit_limit and customer.credit_limit > 0 else None
        ),
    }


@login_required(login_url=LOGIN_URL)
def customer_account(request, customer_id):
    """
    Customer khata: amount due, every purchase (what was bought, paid
    and left that day) and every payment, with a "Receive payment" form
    for paying old dues without buying.
    """

    customer = _get_scoped(Customer.objects.select_related("retailer"), request.user, customer_id)

    context = _customer_context(customer)
    context.update({
        "is_admin": _is_admin(request.user),
        "payment_types": accounts.PAYMENT_TYPES,
        "today": timezone.localdate(),
        "open_payment": request.GET.get("pay") == "1",
        # Features of the customer's own shop (price levels, ...).
        "customer_features": get_features(customer.retailer),
        "price_level_choices": Customer.PRICE_LEVEL_CHOICES,
        "state_choices": STATE_CHOICES,
        "customer_state_name": state_name(customer.state),
    })

    return render(request, "customer_account.html", context)


@require_POST
@login_required(login_url=LOGIN_URL)
def customer_set_state(request, customer_id):
    """Customer's state for the GST split (features.b2b_tax_split only)."""

    customer = _get_scoped(Customer.objects.select_related("retailer"), request.user, customer_id)

    if not get_features(customer.retailer).b2b_tax_split:
        messages.error(request, gettext('GST split is not used for this shop.'))
        return redirect("customer_account", customer_id=customer.id)

    raw = (request.POST.get("state") or "").strip()
    key = state_key(raw)

    if raw and not key:
        messages.error(request, gettext('Please select a valid state.'))
        return redirect("customer_account", customer_id=customer.id)

    customer.state = key
    customer.save(update_fields=["state", "updated_at"])
    logger.info("Customer state changed. customer_id=%s state=%s user_id=%s", customer.id, key, request.user.id)
    messages.success(
        request,
        (gettext('State saved. New bills for %(customer_name)s will use %(SGST)s') % {'customer_name': customer.customer_name, 'SGST': "IGST." if is_inter_state(customer.retailer.state, key) else "CGST + SGST."}),
    )
    return redirect("customer_account", customer_id=customer.id)


@require_POST
@login_required(login_url=LOGIN_URL)
def customer_set_price_level(request, customer_id):
    """Retail / wholesale price for a customer (features.price_levels only)."""

    customer = _get_scoped(Customer.objects.select_related("retailer"), request.user, customer_id)

    if not get_features(customer.retailer).price_levels:
        messages.error(request, gettext('Price levels are not available for this shop.'))
        return redirect("customer_account", customer_id=customer.id)

    level = (request.POST.get("price_level") or "").strip()

    if level not in dict(Customer.PRICE_LEVEL_CHOICES):
        messages.error(request, gettext('Please select a valid price level.'))
        return redirect("customer_account", customer_id=customer.id)

    if customer.price_level != level:
        customer.price_level = level
        customer.save(update_fields=["price_level", "updated_at"])
        logger.info(
            "Customer price level changed. customer_id=%s level=%s user_id=%s",
            customer.id, level, request.user.id,
        )

    messages.success(
        request,
        (gettext('%(customer_name)s now pays %(get_price_level_display)s prices.') % {'customer_name': customer.customer_name, 'get_price_level_display': gettext(customer.get_price_level_display())}),
    )
    return redirect("customer_account", customer_id=customer.id)


@require_POST
@login_required(login_url=LOGIN_URL)
def customer_receive_payment(request, customer_id):
    customer = _get_scoped(Customer.objects.select_related("retailer"), request.user, customer_id)

    try:
        receipt, settled = accounts.receive_customer_payment(
            customer,
            amount=request.POST.get("amount"),
            payment_type=request.POST.get("payment_type", ""),
            payment_date=request.POST.get("payment_date"),
            reference=request.POST.get("reference", ""),
            remarks=request.POST.get("remarks", ""),
        )

    except ValidationError as exc:
        messages.error(request, _error_text(exc))
        return redirect(reverse("customer_account", args=[customer.id]) + "?pay=1")

    logger.info(
        "Customer payment received. customer_id=%s receipt=%s user_id=%s",
        customer.id, receipt, request.user.id,
    )

    total = sum((amount for _, amount in settled), accounts.ZERO)
    balance = accounts.customer_balance(customer)

    messages.success(
        request,
        (gettext('₹%(total)s received from %(customer_name)s (receipt %(receipt)s). %(balance)s') % {'total': total, 'customer_name': customer.customer_name, 'receipt': receipt, 'balance': gettext("All dues are cleared.") if balance <= 0 else (gettext("Still due: ₹%(balance)s.") % {'balance': balance})}),
    )

    next_url = request.POST.get("next", "")
    if next_url == "sale_create":
        return redirect("sale_create")

    return redirect("customer_account", customer_id=customer.id)


@login_required(login_url=LOGIN_URL)
def customer_statement_print(request, customer_id):
    customer = _get_scoped(Customer.objects.select_related("retailer"), request.user, customer_id)
    context = _customer_context(customer)

    return render(request, "account_statement.html", {
        "kind": "customer",
        "title": gettext('Customer Statement'),
        "shop": customer.retailer,
        "party_label": "Customer",
        "party_name": customer.customer_name,
        "party_lines": [
            f"Mobile: {customer.mobile}",
            customer.email or "",
            customer.address or "",
            f"GSTIN: {customer.gst_number}" if customer.gst_number else "",
        ],
        "summary": [
            ("Total billed", context["total_billed"]),
            ("Total received", context["total_paid"]),
            ("Balance due", context["balance"]),
        ],
        "debit_label": "Billed",
        "credit_label": "Received",
        "balance_label": "Due",
        "rows": context["statement"],
        "back_url": reverse("customer_account", args=[customer.id]),
        "file_name": f"Statement-{customer.customer_name}",
        "auto_download": request.GET.get("download") == "1",
        "today": timezone.localdate(),
    })


@require_GET
@login_required(login_url=LOGIN_URL)
def customer_summary(request, customer_id):
    """
    JSON for the New Sale page: the customer's old balance and recent
    purchases (what was bought, paid and left each day).
    """

    scoped = _scope(Customer.objects.all(), request.user)
    customer = scoped.filter(pk=customer_id).first() if scoped is not None else None

    if customer is None:
        return JsonResponse({"success": False, "message": gettext('Customer not found.')}, status=404)

    sales = Sale.objects.filter(customer=customer).order_by("-invoice_date", "-id")

    return JsonResponse({
        "success": True,
        "customer": customer.customer_name,
        "balance": str(accounts.customer_balance(customer)),
        "credit_limit": str(customer.credit_limit or 0),
        "invoice_count": sales.count(),
        "recent": [
            {
                "invoice": sale.invoice_number,
                "date": sale.invoice_date.isoformat(),
                "total": str(sale.grand_total),
                "paid": str(sale.paid_amount),
                "due": str(sale.due_amount),
                "status": sale.payment_status,
                "url": reverse("sale_detail", args=[sale.id]),
            }
            for sale in sales[:5]
        ],
        "account_url": reverse("customer_account", args=[customer.id]),
        "pay_url": reverse("customer_account", args=[customer.id]) + "?pay=1",
    })
