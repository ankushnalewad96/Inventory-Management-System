# services/sales.py

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from .models import CustomUser, Retailer, Supplier, Category, Brand, Unit, Product, Purchase, PurchaseItem, Sale, SaleItem



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
):
    quantity = Decimal(str(quantity))

    if quantity <= Decimal("0.00"):
        raise ValidationError(
            "Sale quantity must be greater than zero."
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

    available_stock = (
        product.current_stock or Decimal("0.00")
    )

    if quantity > available_stock:
        raise ValidationError(
            f"Insufficient stock for "
            f"'{product.product_name}'. "
            f"Available stock: {available_stock}, "
            f"requested: {quantity}."
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