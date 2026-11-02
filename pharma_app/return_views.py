"""
Returns pages.

    sale_return_create      -> return items of a sale (credit note)
    purchase_return_create  -> return items to the supplier (debit note)
    credit_note / debit_note -> printable notes
    returns_list            -> all credit and debit notes

Access: a retailer only reaches their own shop's bills; the admin all.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from . import returns
from .account_views import _scope
from .models import Purchase, PurchaseReturn, Sale, SaleReturn
from .shop_types import get_features
from .states import rate_wise_summary
from .views import _is_admin, _querystring_without_page
from django.utils.translation import gettext

logger = logging.getLogger("pharma_app")

LOGIN_URL = "/user-login/"


def _scoped_get(queryset, request, pk):
    scoped = _scope(queryset, request.user)
    if scoped is None:
        raise Http404("Not found.")
    return get_object_or_404(scoped, pk=pk)


def _error_text(exc):
    return " ".join(str(message) for message in exc.messages)


# ================================================================ SALE RETURN

@login_required(login_url=LOGIN_URL)
def sale_return_create(request, sale_id):
    sale = _scoped_get(Sale.objects.select_related("customer", "retailer"), request, sale_id)

    if request.method == "POST":
        try:
            note = returns.create_sale_return(
                sale,
                request.POST,
                reason=request.POST.get("reason", ""),
                refund_mode=request.POST.get("refund_mode", SaleReturn.REFUND_ACCOUNT),
            )
        except ValidationError as exc:
            error = _error_text(exc)
            logger.warning("Sale return failed. sale_id=%s user_id=%s error=%s", sale.id, request.user.id, error)
            messages.error(request, error)
            return redirect("sale_return_create", sale_id=sale.id)

        logger.info(
            "Sale return saved. credit_note=%s sale_id=%s total=%s user_id=%s",
            note.credit_note_number, sale.id, note.total, request.user.id,
        )
        messages.success(request, (gettext('Credit note %(credit_note_number)s saved for ₹%(total)s.') % {'credit_note_number': note.credit_note_number, 'total': note.total}))
        return redirect("credit_note", return_id=note.id)

    lines = returns.returnable_sale_lines(sale)

    return render(request, "return_form.html", {
        "kind": "sale",
        "bill": sale,
        "bill_number": sale.invoice_number,
        "party_name": sale.customer.customer_name,
        "lines": lines,
        "nothing_left": all(line["returnable"] <= 0 for line in lines),
        "refund_choices": SaleReturn.REFUND_CHOICES,
        "features": get_features(sale.retailer),
        "back_url_name": "sale_detail",
    })


# ================================================================ PURCHASE RETURN

@login_required(login_url=LOGIN_URL)
def purchase_return_create(request, purchase_id):
    purchase = _scoped_get(Purchase.objects.select_related("supplier", "retailer"), request, purchase_id)

    if request.method == "POST":
        try:
            note = returns.create_purchase_return(purchase, request.POST, reason=request.POST.get("reason", ""))
        except ValidationError as exc:
            error = _error_text(exc)
            logger.warning("Purchase return failed. purchase_id=%s user_id=%s error=%s", purchase.id, request.user.id, error)
            messages.error(request, error)
            return redirect("purchase_return_create", purchase_id=purchase.id)

        logger.info(
            "Purchase return saved. debit_note=%s purchase_id=%s total=%s user_id=%s",
            note.debit_note_number, purchase.id, note.total, request.user.id,
        )
        messages.success(request, (gettext('Debit note %(debit_note_number)s saved for ₹%(total)s.') % {'debit_note_number': note.debit_note_number, 'total': note.total}))
        return redirect("debit_note", return_id=note.id)

    lines = returns.returnable_purchase_lines(purchase)

    return render(request, "return_form.html", {
        "kind": "purchase",
        "bill": purchase,
        "bill_number": purchase.bill_number,
        "party_name": purchase.supplier.supplier_name,
        "lines": lines,
        "nothing_left": all(line["returnable"] <= 0 for line in lines),
        "features": get_features(purchase.retailer),
        "back_url_name": "purchase_detail",
    })


# ================================================================ NOTES (printable)

def _note_context(note, items, kind):
    return {
        "kind": kind,
        "note": note,
        "items": items,
        "features": get_features(note.retailer),
        "gst_summary": rate_wise_summary(
            [(item.gst, item.taxable_amount) for item in items], note.tax_type
        ),
    }


@login_required(login_url=LOGIN_URL)
def credit_note(request, return_id):
    note = _scoped_get(
        SaleReturn.objects.select_related("retailer", "customer", "sale"), request, return_id
    )
    items = list(note.items.select_related("product", "batch", "sale_item__unit"))
    return render(request, "return_note.html", _note_context(note, items, "sale"))


@login_required(login_url=LOGIN_URL)
def debit_note(request, return_id):
    note = _scoped_get(
        PurchaseReturn.objects.select_related("retailer", "supplier", "purchase"), request, return_id
    )
    items = list(note.items.select_related("product", "batch", "purchase_item__unit"))
    return render(request, "return_note.html", _note_context(note, items, "purchase"))


# ================================================================ LIST

@login_required(login_url=LOGIN_URL)
def returns_list(request):
    kind = "purchase" if request.GET.get("type") == "purchase" else "sale"
    search = (request.GET.get("search") or "").strip()

    if kind == "sale":
        notes = _scope(SaleReturn.objects.select_related("retailer", "customer", "sale"), request.user)
        if notes is not None and search:
            notes = notes.filter(
                Q(credit_note_number__icontains=search)
                | Q(sale__invoice_number__icontains=search)
                | Q(customer__customer_name__icontains=search)
            )
    else:
        notes = _scope(PurchaseReturn.objects.select_related("retailer", "supplier", "purchase"), request.user)
        if notes is not None and search:
            notes = notes.filter(
                Q(debit_note_number__icontains=search)
                | Q(purchase__bill_number__icontains=search)
                | Q(supplier__supplier_name__icontains=search)
            )

    if notes is None:
        messages.error(request, gettext('No active retailer profile is linked to your account.'))
        return redirect("dashboard")

    page_obj = Paginator(notes.order_by("-return_date", "-id"), 25).get_page(request.GET.get("page"))

    return render(request, "returns_list.html", {
        "kind": kind,
        "notes": page_obj,
        "page_obj": page_obj,
        "search": search,
        "is_admin": _is_admin(request.user),
        "querystring": _querystring_without_page(request),
    })
