"""
Sale returns (credit notes) and purchase returns (debit notes).

Sale return
    Stock comes back (into the same batch for batch-tracked lines).
    The credit first reduces the bill's due; the rest is a cash refund
    or stays on the customer's account as advance. The customer ledger
    gets a credit entry for the note (and a debit for a cash refund).

Purchase return
    Stock goes out (from the same batch for batch-tracked lines).
    The debit note first reduces the bill's due; the rest is money the
    supplier pays back (refund_amount).

Amounts follow the original line: same price, line discount shared by
quantity, same GST rate, and the same GST split (CGST+SGST / IGST) as
the original bill. Returning the last units of a line uses whatever is
left of the line's amount, so paise never drift.

Everything runs in one transaction with the rows locked.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from . import accounts
from .models import (
    CustomerLedger,
    Product,
    ProductBatch,
    Purchase,
    PurchaseReturn,
    PurchaseReturnItem,
    Sale,
    SaleReturn,
    SaleReturnItem,
)
from .quantities import QuantityError, format_quantity, parse_quantity
from .shop_types import get_features
from .states import split_amount
from django.utils.translation import gettext

ZERO = Decimal("0.00")
PAISA = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(PAISA)


def _returned_totals(queryset, key):
    """{line id: {"quantity", "taxable", "gst", "amount", "discount"}} already returned."""

    rows = queryset.values(key).annotate(
        quantity=Sum("quantity"),
        taxable=Sum("taxable_amount"),
        gst=Sum("gst_amount"),
        amount=Sum("amount"),
        discount=Sum("discount"),
    )
    return {row[key]: row for row in rows}


# ================================================================ SALE RETURNS

def returnable_sale_lines(sale):
    """Each sale line with sold, already returned and still returnable quantity."""

    returned = _returned_totals(SaleReturnItem.objects.filter(sale_item__sale=sale), "sale_item")
    lines = []

    for item in sale.items.select_related("product", "unit", "batch").order_by("id"):
        done = returned.get(item.id, {}).get("quantity") or Decimal("0")
        lines.append({
            "item": item,
            "sold": item.quantity,
            "returned": done,
            "returnable": item.quantity - done,
        })

    return lines


def _read_quantities(data, prefix, lines, allow_fraction):
    """{line id: quantity} for lines with a quantity > 0 in the form."""

    quantities = {}

    for line in lines:
        item = line["item"]
        raw = (data.get(f"{prefix}{item.id}") or "").strip()

        if not raw or raw in ("0", "0.0", "0.00", "0.000"):
            continue

        try:
            quantity = parse_quantity(
                raw, (gettext("Return quantity for '%(product_name)s'") % {'product_name': item.product.product_name}),
                allow_fraction=allow_fraction,
            )
        except QuantityError as exc:
            raise ValidationError(str(exc))

        if quantity > line["returnable"]:
            raise ValidationError(
                (gettext("Only %(returnable)s of '%(product_name)s' can be returned.") % {'returnable': format_quantity(line['returnable']), 'product_name': item.product.product_name})
            )

        quantities[item.id] = quantity

    if not quantities:
        raise ValidationError(gettext('Enter the quantity to return for at least one item.'))

    return quantities


@transaction.atomic
def create_sale_return(sale, data, *, reason="", refund_mode=SaleReturn.REFUND_ACCOUNT):
    """
    Create a credit note for `sale` from form data (return_qty_<sale item id>).
    Returns the SaleReturn. Raises ValidationError for bad input.
    """

    sale = Sale.objects.select_for_update().select_related("customer", "retailer").get(pk=sale.pk)
    features = get_features(sale.retailer)

    if refund_mode not in dict(SaleReturn.REFUND_CHOICES):
        raise ValidationError(gettext('Please choose how to settle the return.'))

    lines = returnable_sale_lines(sale)
    quantities = _read_quantities(data, "return_qty_", lines, features.decimal_quantity)
    previous = _returned_totals(SaleReturnItem.objects.filter(sale_item__sale=sale), "sale_item")

    sale_return = SaleReturn.objects.create(
        retailer=sale.retailer,
        sale=sale,
        customer=sale.customer,
        return_date=timezone.localdate(),
        reason=(reason or "").strip(),
        tax_type=sale.tax_type,
        refund_mode=refund_mode,
    )

    subtotal = discount_total = gst_total = total = ZERO

    for line in lines:
        item = line["item"]
        quantity = quantities.get(item.id)
        if quantity is None:
            continue

        done = previous.get(item.id, {})
        is_last = quantity == line["returnable"]
        gross = _money(quantity * item.selling_price)

        if is_last:
            # Whatever is left of the line, so totals match the bill exactly.
            discount = item.discount - (done.get("discount") or ZERO)
            taxable = _money(item.quantity * item.selling_price - item.discount) - (done.get("taxable") or ZERO)
            amount = item.amount - (done.get("amount") or ZERO)
            gst_amount = amount - taxable
            gross = taxable + discount
        else:
            discount = _money(item.discount * quantity / item.quantity)
            taxable = gross - discount
            gst_amount = _money(taxable * item.gst / 100)
            amount = taxable + gst_amount

        SaleReturnItem.objects.create(
            sale_return=sale_return,
            sale_item=item,
            product=item.product,
            batch=item.batch,
            quantity=quantity,
            selling_price=item.selling_price,
            discount=discount,
            gst=item.gst,
            taxable_amount=taxable,
            gst_amount=gst_amount,
            amount=amount,
        )

        # Stock back (same batch for batch-tracked lines).
        product = Product.objects.select_for_update().get(pk=item.product_id)
        if item.batch_id:
            batch = ProductBatch.objects.select_for_update().get(pk=item.batch_id)
            batch.quantity += quantity
            batch.save(update_fields=["quantity"])
        product.current_stock += quantity
        product.save(update_fields=["current_stock", "updated_at"])

        subtotal += gross
        discount_total += discount
        gst_total += gst_amount
        total += amount

    # Money: reduce the bill's due first.
    applied = min(total, max(sale.due_amount, ZERO))
    refund = total - applied if refund_mode == SaleReturn.REFUND_CASH else ZERO

    sale_return.subtotal = subtotal
    sale_return.discount = discount_total
    sale_return.gst = gst_total
    sale_return.total = total
    sale_return.applied_to_bill = applied
    sale_return.refund_amount = refund
    sale_return.__dict__.update(split_amount(gst_total, sale.tax_type))
    sale_return.save()

    if applied > ZERO:
        sale.returned_amount = (sale.returned_amount + applied).quantize(PAISA)
        sale.save()   # recalculates due and status

    # Customer ledger: credit for the goods, debit for money paid back.
    customer = sale.customer
    balance = accounts.customer_balance(customer) - total
    CustomerLedger.objects.create(
        customer=customer, sale=sale, sale_return=sale_return,
        date=sale_return.return_date, debit=ZERO, credit=total, balance=balance,
        remarks=f"Credit note {sale_return.credit_note_number} (goods returned from {sale.invoice_number})",
    )

    if refund > ZERO:
        CustomerLedger.objects.create(
            customer=customer, sale=sale, sale_return=sale_return,
            date=sale_return.return_date, debit=refund, credit=ZERO, balance=balance + refund,
            remarks=f"Cash refund for credit note {sale_return.credit_note_number}",
        )

    return sale_return


# ================================================================ PURCHASE RETURNS

def returnable_purchase_lines(purchase):
    """
    Each purchase line with bought (paid quantity, in the unit it was
    bought in), already returned and still returnable quantity.
    Free quantity cannot be returned for money.
    """

    returned = _returned_totals(PurchaseReturnItem.objects.filter(purchase_item__purchase=purchase), "purchase_item")
    lines = []

    for item in purchase.items.select_related("product", "unit", "batch").order_by("id"):
        done = returned.get(item.id, {}).get("quantity") or Decimal("0")
        lines.append({
            "item": item,
            "sold": item.quantity,
            "returned": done,
            "returnable": item.quantity - done,
        })

    return lines


@transaction.atomic
def create_purchase_return(purchase, data, *, reason=""):
    """
    Create a debit note for `purchase` from form data
    (return_qty_<purchase item id>, in the unit the line was bought in).
    """

    purchase = Purchase.objects.select_for_update().select_related("supplier", "retailer").get(pk=purchase.pk)
    features = get_features(purchase.retailer)

    lines = returnable_purchase_lines(purchase)
    quantities = _read_quantities(data, "return_qty_", lines, features.decimal_quantity)

    purchase_return = PurchaseReturn.objects.create(
        retailer=purchase.retailer,
        purchase=purchase,
        supplier=purchase.supplier,
        return_date=timezone.localdate(),
        reason=(reason or "").strip(),
        tax_type=purchase.tax_type,
    )

    subtotal = discount_total = gst_total = total = ZERO

    for line in lines:
        item = line["item"]
        quantity = quantities.get(item.id)
        if quantity is None:
            continue

        factor = item.conversion_factor or Decimal("1")
        base_quantity = (quantity * factor).quantize(Decimal("0.001"))

        gross = _money(quantity * item.purchase_price)
        line_discount = _money((item.discount or ZERO) * quantity / item.quantity)
        before_bill_discount = gross - line_discount

        # Share of the bill-level discount (charges are not returned).
        bill_discount = (
            _money(before_bill_discount / purchase.subtotal * purchase.discount)
            if purchase.subtotal and purchase.discount else ZERO
        )
        # GST was charged before the bill discount (as on the purchase).
        gst_amount = _money(before_bill_discount * item.gst / 100)
        discount = line_discount + bill_discount
        taxable = gross - discount
        amount = taxable + gst_amount

        # Stock out (same batch for batch-tracked lines).
        product = Product.objects.select_for_update().get(pk=item.product_id)

        if item.batch_id:
            batch = ProductBatch.objects.select_for_update().get(pk=item.batch_id)
            if batch.quantity < base_quantity:
                raise ValidationError(
                    (gettext("Only %(quantity)s of '%(product_name)s' batch %(batch_number)s is left in stock.") % {'quantity': format_quantity(batch.quantity), 'product_name': product.product_name, 'batch_number': batch.batch_number})
                )
            batch.quantity -= base_quantity
            batch.save(update_fields=["quantity"])
        elif product.current_stock < base_quantity:
            raise ValidationError(
                (gettext("Only %(current_stock)s of '%(product_name)s' is left in stock.") % {'current_stock': format_quantity(product.current_stock), 'product_name': product.product_name})
            )

        product.current_stock -= base_quantity
        product.save(update_fields=["current_stock", "updated_at"])

        PurchaseReturnItem.objects.create(
            purchase_return=purchase_return,
            purchase_item=item,
            product=item.product,
            batch=item.batch,
            quantity=quantity,
            base_quantity=base_quantity,
            purchase_price=item.purchase_price,
            discount=discount,
            gst=item.gst,
            taxable_amount=taxable,
            gst_amount=gst_amount,
            amount=amount,
        )

        subtotal += gross
        discount_total += discount
        gst_total += gst_amount
        total += amount

    applied = min(total, max(purchase.due_amount, ZERO))
    refund = total - applied

    purchase_return.subtotal = subtotal
    purchase_return.discount = discount_total
    purchase_return.gst = gst_total
    purchase_return.total = total
    purchase_return.applied_to_bill = applied
    purchase_return.refund_amount = refund
    purchase_return.__dict__.update(split_amount(gst_total, purchase.tax_type))
    purchase_return.save()

    if applied > ZERO:
        purchase.returned_amount = (purchase.returned_amount + applied).quantize(PAISA)
        accounts.set_purchase_payment_fields(purchase)
        purchase.save(update_fields=["returned_amount", "due_amount", "payment_status", "updated_at"])

    return purchase_return
