from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from . import batches as batch_stock
from .models import Product, SaleItem, Unit
from django.utils.translation import gettext



@transaction.atomic
def add_sale_item(
    *,
    sale,
    product_id,
    unit_id,
    quantity,
    selling_price,
    mrp=None,
    gst=Decimal("0.00"),
    discount=Decimal("0.00"),
    batch_tracking=False,
    batch_id=None,
    on_date=None,
):
    """
    Add one sale line and take its stock.

    batch_tracking (pharmacy): stock comes out of batches, earliest
    expiry first (or `batch_id` first); expired batches are never sold.
    A line needing several batches is saved as one SaleItem per batch,
    with the discount split by quantity. Returns the first SaleItem.
    """

    quantity = Decimal(str(quantity))

    if quantity <= Decimal("0.00"):
        raise ValidationError(
            gettext('Sale quantity must be greater than zero.')
        )

    product = (
        Product.objects
        .select_for_update()
        .get(
            pk=product_id,
            retailer=sale.retailer,
            is_active=True,
        )
    )

    if batch_tracking:
        return _add_batch_sale_items(
            sale=sale,
            product=product,
            unit_id=unit_id,
            quantity=quantity,
            selling_price=selling_price,
            mrp=mrp,
            gst=gst,
            discount=Decimal(str(discount)),
            batch_id=batch_id,
            on_date=on_date or sale.invoice_date,
        )

    available_stock = (
        product.current_stock or Decimal("0.00")
    )

    if quantity > available_stock:
        raise ValidationError(
            (gettext("Insufficient stock for '%(product_name)s'. Available stock: %(available_stock)s, requested: %(quantity)s.") % {'product_name': product.product_name, 'available_stock': available_stock, 'quantity': quantity})
        )

    unit = Unit.objects.get(pk=unit_id)

    sale_item = SaleItem(
        sale=sale,
        product=product,
        unit=unit,
        quantity=quantity,
        selling_price=selling_price,
        mrp=mrp,
        gst=gst,
        discount=discount,
    )

    sale_item.full_clean()
    sale_item.save()

    product.current_stock -= quantity

    product.save(
        update_fields=[
            "current_stock",
            "updated_at",
        ]
    )

    return sale_item


def _add_batch_sale_items(*, sale, product, unit_id, quantity, selling_price, mrp, gst, discount, batch_id, on_date):
    unit = Unit.objects.get(pk=unit_id)

    # Locks the batch rows (product row is already locked).
    allocations = batch_stock.allocate(
        product, quantity, on_date=on_date, batch_id=batch_id
    )
    discounts = batch_stock.split_amount(discount, allocations, quantity)

    items = []

    for (batch, batch_qty), batch_discount in zip(allocations, discounts):
        sale_item = SaleItem(
            sale=sale,
            product=product,
            unit=unit,
            batch=batch,
            quantity=batch_qty,
            selling_price=selling_price,
            # The pack's printed MRP when the batch has one.
            mrp=batch.mrp if batch.mrp is not None else mrp,
            gst=gst,
            discount=batch_discount,
        )
        sale_item.full_clean()
        sale_item.save()
        items.append(sale_item)

    batch_stock.take_from_batches(product, allocations)

    return items[0]