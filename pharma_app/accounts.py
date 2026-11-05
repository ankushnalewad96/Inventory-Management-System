"""
Money owed between a shop and its suppliers / customers.

Suppliers
    A purchase bill can be paid in parts (at purchase time, before or
    after its due date). Every part is a PurchasePayment row. When the
    balance due reaches zero the bill is closed (status "Paid").

Customers ("udhari" / khata)
    The customer's balance = opening balance + everything billed
    (ledger debits) - everything received (ledger credits).
    A customer can pay old dues without buying anything; the money is
    applied to the oldest unpaid invoices first.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    OuterRef,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    Customer,
    CustomerLedger,
    Payment,
    Purchase,
    PurchasePayment,
    PurchaseReturn,
    Sale,
)
from django.utils.translation import gettext

ZERO = Decimal("0.00")
TWO_PLACES = Decimal("0.01")

# Money to suppliers and from customers is cash only.
CASH = "Cash"
CUSTOMER_PAYMENT_TYPE = CASH
SUPPLIER_PAYMENT_TYPE = CASH

MONEY_FIELD = DecimalField(max_digits=14, decimal_places=2)


# ---------------------------------------------------------------- helpers

def parse_amount(value, label="Amount"):
    """A positive money amount with 2 decimals, or ValidationError."""

    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError((gettext('Enter a valid %(label)s.') % {'label': label.lower()}))

    if not amount.is_finite():
        raise ValidationError((gettext('Enter a valid %(label)s.') % {'label': label.lower()}))

    amount = amount.quantize(TWO_PLACES)

    if amount <= ZERO:
        raise ValidationError((gettext('%(label)s must be greater than zero.') % {'label': label}))

    return amount


def parse_payment_date(value, earliest=None):
    """
    Payment date from a YYYY-MM-DD string (empty = today).
    It cannot be in the future, or before `earliest` (e.g. the bill date).
    """

    today = timezone.localdate()

    if not value:
        payment_date = today
    else:
        try:
            payment_date = datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError(gettext('Enter a valid payment date.'))

    if payment_date > today:
        raise ValidationError(gettext('Payment date cannot be in the future.'))

    if earliest and payment_date < earliest:
        raise ValidationError(
            (gettext('Payment date cannot be before %(Y)s.') % {'Y': earliest.strftime('%d %b %Y')})
        )

    return payment_date


# ================================================================ SUPPLIERS

def set_purchase_payment_fields(purchase):
    """
    Recalculate due amount and status from grand total, paid amount and
    returned goods (debit notes applied to this bill).
    """

    settled = purchase.paid_amount + (purchase.returned_amount or ZERO)
    purchase.due_amount = max(purchase.grand_total - settled, ZERO)

    if purchase.due_amount <= ZERO:
        purchase.payment_status = "Paid"
    elif settled > ZERO:
        purchase.payment_status = "Partial"
    else:
        purchase.payment_status = "Unpaid"


@transaction.atomic
def record_purchase_payment(
    purchase,
    *,
    amount,
    payment_date=None,
    remarks="",
    user=None,
):
    """
    Pay (part of) the balance due on a purchase bill, in cash.

    Returns the new PurchasePayment. Raises ValidationError when the
    amount is invalid, more than the balance due, or the bill is closed.
    """

    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)

    amount = parse_amount(amount)

    if purchase.due_amount <= ZERO:
        raise ValidationError(gettext('This bill is already fully paid.'))

    if amount > purchase.due_amount:
        raise ValidationError(
            (gettext('Amount cannot be more than the balance due (₹%(due_amount)s).') % {'due_amount': purchase.due_amount})
        )

    payment = PurchasePayment.objects.create(
        retailer_id=purchase.retailer_id,
        supplier_id=purchase.supplier_id,
        purchase=purchase,
        payment_date=parse_payment_date(payment_date, earliest=purchase.bill_date),
        amount=amount,
        payment_type=SUPPLIER_PAYMENT_TYPE,
        remarks=(remarks or "").strip() or None,
        created_by=user,
    )

    purchase.paid_amount = (purchase.paid_amount + amount).quantize(TWO_PLACES)
    set_purchase_payment_fields(purchase)
    purchase.save(update_fields=["paid_amount", "due_amount", "payment_status", "updated_at"])

    return payment


def supplier_account(supplier):
    """
    What the shop owes a supplier: totals, open (unpaid) bills and
    overdue amount. Used on the supplier account page and when a new
    purchase order is started for that supplier.
    """

    today = timezone.localdate()
    bills = Purchase.objects.filter(supplier=supplier)

    totals = bills.aggregate(
        bills=Count("id"),
        billed=Coalesce(Sum("grand_total"), Value(ZERO), output_field=MONEY_FIELD),
        paid=Coalesce(Sum("paid_amount"), Value(ZERO), output_field=MONEY_FIELD),
        due=Coalesce(Sum("due_amount"), Value(ZERO), output_field=MONEY_FIELD),
        returned=Coalesce(Sum("returned_amount"), Value(ZERO), output_field=MONEY_FIELD),
    )

    open_bills = list(bills.filter(due_amount__gt=0).order_by("due_date", "bill_date", "id"))

    overdue_bills = [
        bill for bill in open_bills
        if bill.due_date and bill.due_date < today
    ]

    last_payment = (
        PurchasePayment.objects
        .filter(supplier=supplier)
        .order_by("-payment_date", "-id")
        .first()
    )

    return {
        "bills": totals["bills"],
        "billed": totals["billed"],
        "paid": totals["paid"],
        "due": totals["due"],
        # Debit notes (goods returned) that reduced bills' dues.
        "returned": totals["returned"],
        "open_bills": open_bills,
        "overdue_bills": overdue_bills,
        "overdue": sum((bill.due_amount for bill in overdue_bills), ZERO),
        "last_payment": last_payment,
        "today": today,
    }


def supplier_statement(supplier):
    """
    Supplier statement in date order: each bill increases the balance
    the shop owes, each payment reduces it.
    """

    events = []

    for bill in Purchase.objects.filter(supplier=supplier):
        events.append((bill.bill_date, 0, bill.created_at, {
            "date": bill.bill_date,
            "kind": "bill",
            "particulars": f"Purchase bill {bill.bill_number}",
            "reference": bill.bill_number,
            "purchase_id": bill.id,
            "debit": bill.grand_total,
            "credit": ZERO,
        }))

    for payment in PurchasePayment.objects.filter(supplier=supplier).select_related("purchase"):
        events.append((payment.payment_date, 1, payment.created_at, {
            "date": payment.payment_date,
            "kind": "payment",
            "particulars": f"Payment for bill {payment.purchase.bill_number}",
            "reference": payment.reference or "",
            "purchase_id": payment.purchase_id,
            "debit": ZERO,
            "credit": payment.amount,
        }))

    # Goods returned (debit notes): reduce what the shop owes; money the
    # supplier paid back for an already-paid bill cancels that out again.
    for note in PurchaseReturn.objects.filter(supplier=supplier).select_related("purchase"):
        events.append((note.return_date, 2, note.created_at, {
            "date": note.return_date,
            "kind": "debit_note",
            "particulars": f"Debit note {note.debit_note_number} (goods returned, bill {note.purchase.bill_number})",
            "reference": note.debit_note_number,
            "purchase_id": note.purchase_id,
            "debit": ZERO,
            "credit": note.total,
        }))

        if note.refund_amount > ZERO:
            events.append((note.return_date, 3, note.created_at, {
                "date": note.return_date,
                "kind": "refund",
                "particulars": f"Refund received from supplier for {note.debit_note_number}",
                "reference": note.debit_note_number,
                "purchase_id": note.purchase_id,
                "debit": note.refund_amount,
                "credit": ZERO,
            }))

    events.sort(key=lambda event: (event[0], event[1], event[2]))

    balance = ZERO
    rows = []

    for _, _, _, row in events:
        balance += row["debit"] - row["credit"]
        row["balance"] = balance
        rows.append(row)

    return rows


# ================================================================ CUSTOMERS

def customer_balance(customer):
    """What the customer owes now: opening balance + debits - credits."""

    totals = CustomerLedger.objects.filter(customer=customer).aggregate(
        debit=Coalesce(Sum("debit"), Value(ZERO), output_field=MONEY_FIELD),
        credit=Coalesce(Sum("credit"), Value(ZERO), output_field=MONEY_FIELD),
    )

    return (
        (customer.opening_balance or ZERO) + totals["debit"] - totals["credit"]
    ).quantize(TWO_PLACES)


def with_customer_totals(customers):
    """
    Annotate a Customer queryset with:
        outstanding, total_billed, total_paid, invoice_count, last_sale_date
    (subqueries, so the sums are not multiplied by joins).
    """

    def ledger_sum(field):
        return Coalesce(
            Subquery(
                CustomerLedger.objects
                .filter(customer=OuterRef("pk"))
                .values("customer")
                .annotate(total=Sum(field))
                .values("total")[:1],
                output_field=MONEY_FIELD,
            ),
            Value(ZERO),
            output_field=MONEY_FIELD,
        )

    def sale_value(expression):
        return Subquery(
            Sale.objects
            .filter(customer=OuterRef("pk"))
            .values("customer")
            .annotate(value=expression)
            .values("value")[:1]
        )

    return customers.annotate(
        total_billed=ledger_sum("debit"),
        total_paid=ledger_sum("credit"),
        invoice_count=Coalesce(sale_value(Count("id")), Value(0)),
        last_sale_date=sale_value(Max("invoice_date")),
    ).annotate(
        outstanding=ExpressionWrapper(
            F("opening_balance") + F("total_billed") - F("total_paid"),
            output_field=MONEY_FIELD,
        ),
    )


def customer_statement(customer):
    """
    Customer khata in date order with a running balance, starting from
    the opening balance.
    """

    rows = []
    balance = customer.opening_balance or ZERO

    if balance:
        rows.append({
            "date": customer.created_at.date() if customer.created_at else None,
            "kind": "opening",
            "particulars": "Opening balance",
            "sale_id": None,
            "debit": balance if balance > ZERO else ZERO,
            "credit": -balance if balance < ZERO else ZERO,
            "balance": balance,
        })

    entries = (
        CustomerLedger.objects
        .filter(customer=customer)
        .select_related("sale", "payment")
        .order_by("date", "id")
    )

    for entry in entries:
        balance += entry.debit - entry.credit

        if entry.sale_return_id:
            kind = "refund" if entry.debit > ZERO else "return"
        else:
            kind = "sale" if entry.debit > ZERO else "payment"

        rows.append({
            "date": entry.date,
            "kind": kind,
            "particulars": entry.remarks or ("Sale" if entry.debit > ZERO else "Payment received"),
            "sale_id": entry.sale_id,
            "receipt": entry.payment.receipt_number if entry.payment_id else "",
            "debit": entry.debit,
            "credit": entry.credit,
            "balance": balance,
        })

    return rows


def next_receipt_number(retailer, on_date):
    """RCPT-YYYY-000001, numbered per shop and year."""

    prefix = f"RCPT-{on_date.year}-"

    last = (
        Payment.objects
        .filter(retailer=retailer, receipt_number__startswith=prefix)
        .order_by("-receipt_number")
        .values_list("receipt_number", flat=True)
        .first()
    )

    try:
        number = int(last.rsplit("-", 1)[-1]) + 1 if last else 1
    except ValueError:
        number = 1

    return f"{prefix}{number:06d}"


@transaction.atomic
def receive_customer_payment(
    customer,
    *,
    amount,
    payment_date=None,
    remarks="",
):
    """
    Customer pays old dues (udhari), with or without buying anything.
    Customers always pay in cash.

    The money settles the oldest unpaid invoices first; anything left
    reduces the opening balance. Returns (receipt_number, settled) where
    settled is a list of (invoice_number, amount).
    """

    customer = Customer.objects.select_for_update().get(pk=customer.pk)

    amount = parse_amount(amount)
    payment_type = CUSTOMER_PAYMENT_TYPE
    payment_date = parse_payment_date(payment_date)

    outstanding = customer_balance(customer)

    if outstanding <= ZERO:
        raise ValidationError((gettext('%(customer_name)s has no amount due.') % {'customer_name': customer.customer_name}))

    if amount > outstanding:
        raise ValidationError(
            (gettext('Amount cannot be more than the amount due (₹%(outstanding)s).') % {'outstanding': outstanding})
        )

    receipt = next_receipt_number(customer.retailer, payment_date)
    note = (remarks or "").strip() or "Due payment received"

    remaining = amount
    payments = []
    settled = []

    open_sales = (
        Sale.objects
        .select_for_update()
        .filter(customer=customer, due_amount__gt=0)
        .order_by("invoice_date", "id")
    )

    for sale in open_sales:
        if remaining <= ZERO:
            break

        portion = min(remaining, sale.due_amount)

        payments.append(Payment.objects.create(
            retailer=customer.retailer,
            customer=customer,
            sale=sale,
            payment_date=payment_date,
            amount=portion,
            payment_type=payment_type,
            receipt_number=receipt,
            remarks=note,
        ))

        sale.paid_amount = (sale.paid_amount + portion).quantize(TWO_PLACES)
        sale.save()  # recalculates due amount and status

        settled.append((sale.invoice_number, portion))
        remaining -= portion

    if remaining > ZERO:
        # Rest of the money clears the opening balance.
        payments.append(Payment.objects.create(
            retailer=customer.retailer,
            customer=customer,
            sale=None,
            payment_date=payment_date,
            amount=remaining,
            payment_type=payment_type,
            receipt_number=receipt,
            remarks=note,
        ))
        settled.append(("Opening balance", remaining))

    details = ", ".join(f"{name} ₹{value}" for name, value in settled)

    entry = CustomerLedger(
        customer=customer,
        payment=payments[0],
        date=payment_date,
        debit=ZERO,
        credit=amount,
        balance=(outstanding - amount).quantize(TWO_PLACES),
        remarks=f"Payment received · {receipt} ({details})",
    )
    entry.full_clean()
    entry.save()

    return receipt, settled
