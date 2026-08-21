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
    """
    Create a SaleItem and deduct the required quantity from stock.

    The Product row is locked using select_for_update() so that
    concurrent sales cannot consume the same stock simultaneously.
    """

    quantity = Decimal(str(quantity))

    if quantity <= Decimal("0.00"):
        raise ValidationError(
            "Sale quantity must be greater than zero."
        )

    # Lock the product row until the transaction finishes.
    product = (
        Product.objects
        .select_for_update()
        .get(
            pk=product_id,
            retailer=sale.retailer,
            is_active=True,
        )
    )

    # Validate stock while the product row is locked.
    if quantity > product.current_stock:
        raise ValidationError(
            f"Insufficient stock for '{product.product_name}'. "
            f"Available stock: {product.current_stock}, "
            f"requested quantity: {quantity}."
        )

    # Make sure the selected unit belongs to the retailer/product
    # structure expected by your application.
    unit = Unit.objects.get(pk=unit_id)

    # Create the sale item.
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

    # Run model-level validation.
    sale_item.full_clean()

    # Save SaleItem.
    sale_item.save()

    # Deduct stock.
    product.current_stock -= quantity

    product.save(
        update_fields=[
            "current_stock",
            "updated_at",
        ]
    )

    return sale_item