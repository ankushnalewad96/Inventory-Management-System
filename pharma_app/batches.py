"""
Batch-wise stock for shops with features.batch_tracking (pharmacy).

Rule: for a batch-tracked product, Product.current_stock always equals
the sum of its ProductBatch quantities. Every function here changes both
together, so call them inside transaction.atomic() with the product row
locked (select_for_update), like sales.add_sale_item does.

Selling picks the earliest expiry first (FEFO). Expired batches
(expiry date before today) can never be sold.
"""

import calendar
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError

from .models import ProductBatch
from .quantities import format_quantity
from django.utils.translation import gettext

ZERO = Decimal("0")
MONEY_STEP = Decimal("0.01")


# ---------------------------------------------------------------- input helpers

def parse_expiry(value, label="Expiry date"):
    """
    Expiry from a form: "YYYY-MM-DD", or "YYYY-MM" (month picker, the
    usual way expiry is printed on packs) meaning the month's last day.
    """

    text = (value or "").strip()

    if not text:
        raise ValidationError((gettext('%(label)s is required.') % {'label': label}))

    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue

        if fmt == "%Y-%m":
            last_day = calendar.monthrange(parsed.year, parsed.month)[1]
            parsed = parsed.replace(day=last_day)

        return parsed

    raise ValidationError((gettext('Enter a valid %(label)s.') % {'label': label.lower()}))


def clean_batch_number(value, label="Batch number"):
    text = (value or "").strip().upper()

    if not text:
        raise ValidationError((gettext('%(label)s is required.') % {'label': label}))

    if len(text) > 100:
        raise ValidationError((gettext('%(label)s is too long.') % {'label': label}))

    return text


# ---------------------------------------------------------------- stock in

def receive_into_batch(product, *, batch_number, expiry_date, quantity, purchase_price=None, mrp=None):
    """
    Add `quantity` (base units) to the product's batch, creating it when
    it does not exist yet, and add the same quantity to the product's
    stock. The caller holds the product row lock.
    """

    batch = (
        ProductBatch.objects
        .select_for_update()
        .filter(product=product, batch_number__iexact=batch_number)
        .first()
    )

    if batch is not None:
        if batch.expiry_date != expiry_date:
            raise ValidationError(
                (gettext("Batch %(batch_number)s of '%(product_name)s' already exists with expiry %(expiry_date)s. Check the batch number or expiry.") % {'batch_number': batch.batch_number, 'product_name': product.product_name, 'expiry_date': format(batch.expiry_date, '%d-%m-%Y')})
            )

        batch.quantity += quantity
        update_fields = ["quantity"]

        if purchase_price is not None:
            batch.purchase_price = purchase_price
            update_fields.append("purchase_price")

        if mrp is not None:
            batch.mrp = mrp
            update_fields.append("mrp")

        batch.save(update_fields=update_fields)
    else:
        batch = ProductBatch.objects.create(
            retailer_id=product.retailer_id,
            product=product,
            batch_number=batch_number,
            expiry_date=expiry_date,
            quantity=quantity,
            purchase_price=purchase_price if purchase_price is not None else ZERO,
            mrp=mrp,
        )

    product.current_stock = product.current_stock + quantity
    product.save(update_fields=["current_stock", "updated_at"])

    return batch


# ---------------------------------------------------------------- stock out

def sellable_quantity(product, on_date):
    """Stock that can be sold now: batches that have not expired."""

    total = ZERO
    for batch in product.batches.filter(quantity__gt=0, expiry_date__gte=on_date):
        total += batch.quantity
    return total


def allocate(product, quantity, *, on_date, batch_id=None):
    """
    Decide which batches a sale of `quantity` (base units) comes from.

    Earliest expiry first (FEFO). With `batch_id`, that batch is used
    first and any remainder comes from the other batches (FEFO).
    Expired batches are never used. Locks the batch rows.
    Returns [(batch, quantity), ...].
    """

    batches = list(
        ProductBatch.objects
        .select_for_update()
        .filter(product=product, quantity__gt=0)
        .order_by("expiry_date", "id")
    )

    usable = [batch for batch in batches if batch.expiry_date >= on_date]
    expired = [batch for batch in batches if batch.expiry_date < on_date]

    if batch_id:
        chosen = next((batch for batch in batches if str(batch.id) == str(batch_id)), None)

        if chosen is None:
            raise ValidationError(
                (gettext("Selected batch of '%(product_name)s' was not found or is empty.") % {'product_name': product.product_name})
            )

        if chosen.expiry_date < on_date:
            raise ValidationError(
                (gettext("Batch %(batch_number)s of '%(product_name)s' expired on %(expiry_date)s and cannot be sold.") % {'batch_number': chosen.batch_number, 'product_name': product.product_name, 'expiry_date': format(chosen.expiry_date, '%d-%m-%Y')})
            )

        usable = [chosen] + [batch for batch in usable if batch.id != chosen.id]

    available = sum((batch.quantity for batch in usable), ZERO)

    if quantity > available:
        expired_qty = sum((batch.quantity for batch in expired), ZERO)
        note = (
            " (" + (gettext("%(quantity)s more is expired and cannot be sold") % {"quantity": format_quantity(expired_qty)}) + ")"
            if expired_qty > 0 else ""
        )
        raise ValidationError(
            (gettext("Insufficient stock for '%(product_name)s'. Available: %(available)s%(note)s. Requested: %(quantity)s.") % {'product_name': product.product_name, 'available': format_quantity(available), 'note': note, 'quantity': format_quantity(quantity)})
        )

    allocations = []
    remaining = quantity

    for batch in usable:
        if remaining <= 0:
            break
        take = min(batch.quantity, remaining)
        allocations.append((batch, take))
        remaining -= take

    return allocations


def take_from_batches(product, allocations):
    """Remove allocated quantities from batches and from product stock."""

    total = ZERO

    for batch, quantity in allocations:
        batch.quantity -= quantity
        batch.save(update_fields=["quantity"])
        total += quantity

    product.current_stock = product.current_stock - total
    product.save(update_fields=["current_stock", "updated_at"])

    return total


def split_amount(amount, allocations, total_quantity):
    """
    Split a money amount (e.g. a line discount) over allocations in
    proportion to quantity; the last part takes the rounding remainder.
    """

    parts = []
    remaining = Decimal(amount)

    for index, (_, quantity) in enumerate(allocations):
        if index == len(allocations) - 1:
            parts.append(remaining)
        else:
            part = (Decimal(amount) * quantity / total_quantity).quantize(MONEY_STEP)
            parts.append(part)
            remaining -= part

    return parts


def batches_in_sync(product):
    """True when product stock equals the sum of its batches (for checks/tests)."""

    total = sum((batch.quantity for batch in product.batches.all()), ZERO)
    return total == product.current_stock
