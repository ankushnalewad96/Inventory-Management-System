from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Retailer, Category, Brand, Unit, Product, Purchase, PurchaseItem, Supplier


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "user_type",
        "is_active",
    )


@admin.register(Retailer)
class RetailerAdmin(admin.ModelAdmin):
    list_display = (
        "shop_name",
        "owner_name",
        "mobile",
        "city",
        "state",
    )

    search_fields = (
        "shop_name",
        "owner_name",
        "mobile",
    )


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):

    list_display = (
        "supplier_name",
        "mobile",
        "city",
        "state",
        "credit_days",
        "opening_balance",
        "is_active",
    )

    search_fields = (
        "supplier_name",
        "mobile",
        "gst_number",
    )

    list_filter = (
        "state",
        "is_active",
    )

    ordering = (
        "supplier_name",
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "product_name",
        "category",
        "brand",
        "unit",
        "purchase_price",
        "selling_price",
        "mrp",
        "current_stock",
        "minimum_stock",
        "gst",
        "is_active",
    )

    search_fields = (
        "product_name",
        "barcode",
        "hsn_code",
    )

    list_filter = (
        "category",
        "brand",
        "unit",
        "is_active",
    )

    ordering = (
        "product_name",
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "category_name",
        "retailer",
    )

    search_fields = (
        "category_name",
        "retailer__shop_name",
    )

    list_filter = (
        "retailer",
    )

    ordering = (
        "category_name",
    )


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "brand_name",
        "retailer",
    )

    search_fields = (
        "brand_name",
        "retailer__shop_name",
    )

    list_filter = (
        "retailer",
    )

    ordering = (
        "brand_name",
    )


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "short_name",
    )

    search_fields = (
        "name",
        "short_name",
    )

    ordering = (
        "name",
    )


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):

    list_display = (
        "bill_number",
        "supplier",
        "retailer",
        "bill_date",
        "grand_total",
        "paid_amount",
        "due_amount",
        "payment_status",
    )

    search_fields = (
        "bill_number",
        "supplier",
        "retailer__shop_name",
    )

    list_filter = (
        "payment_status",
        "bill_date",
        "payment_type",
    )

    ordering = (
        "-bill_date",
    )


@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):

    list_display = (
        "purchase",
        "product",
        "quantity",
        "free_quantity",
        "purchase_price",
        "selling_price",
        "mrp",
        "amount",
    )

    search_fields = (
        "purchase__bill_number",
        "product__product_name",
        "batch_number",
    )

    list_filter = (
        "unit",
        "gst",
    )

    ordering = (
        "purchase",
    )

    