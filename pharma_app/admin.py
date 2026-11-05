from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Retailer, Category, Brand, Unit, Product, Purchase, PurchaseItem, Supplier, ProductBatch, Quotation, QuotationItem, SaleReturn, PurchaseReturn


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
        "shop_type",
        "owner_name",
        "mobile",
        "city",
        "state",
        "is_active",
    )

    list_filter = (
        "shop_type",
        "is_active",
    )

    search_fields = (
        "shop_name",
        "owner_name",
        "mobile",
    )


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):

    list_display = (
        "retailer",
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


from django.contrib import admin

from .models import (
    Customer,
    Sale,
    SaleItem,
    Payment,
    CustomerLedger,
)


# ============================================================
# Customer Admin
# ============================================================

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """
    Admin configuration for Customer model.
    """

    list_display = (
        "customer_name",
        "mobile",
        "email",
        "retailer",
        "opening_balance",
        "credit_limit",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "retailer",
        "created_at",
    )

    search_fields = (
        "customer_name",
        "mobile",
        "email",
        "gst_number",
    )

    autocomplete_fields = (
        "retailer",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "customer_name",
    )

    list_per_page = 25


# ============================================================
# Sale Item Inline
# ============================================================

class SaleItemInline(admin.TabularInline):
    """
    Display SaleItem records directly inside Sale admin.
    """

    model = SaleItem

    extra = 0

    autocomplete_fields = (
        "product",
        "unit",
    )

    readonly_fields = (
        "amount",
        "created_at",
    )

    fields = (
        "product",
        "unit",
        "quantity",
        "selling_price",
        "mrp",
        "gst",
        "discount",
        "amount",
    )


# ============================================================
# Payment Inline
# ============================================================

class PaymentInline(admin.TabularInline):
    """
    Display payments associated with a sale.
    """

    model = Payment

    extra = 0

    autocomplete_fields = (
        "customer",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fields = (
        "customer",
        "payment_date",
        "amount",
        "receipt_number",
        "remarks",
    )


# ============================================================
# Customer Ledger Inline
# ============================================================

class CustomerLedgerInline(admin.TabularInline):
    """
    Display ledger entries associated with a sale.
    """

    model = CustomerLedger

    extra = 0

    readonly_fields = (
        "balance",
        "created_at",
    )

    fields = (
        "customer",
        "date",
        "debit",
        "credit",
        "balance",
        "remarks",
    )


# ============================================================
# Sale Admin
# ============================================================

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    """
    Admin configuration for Sale model.
    """

    list_display = (
        "invoice_number",
        "invoice_date",
        "retailer",
        "customer",
        "grand_total",
        "paid_amount",
        "due_amount",
        "payment_status",
        "created_at",
    )

    list_filter = (
        "payment_status",
        "invoice_date",
        "retailer",
    )

    search_fields = (
        "invoice_number",
        "customer__customer_name",
        "customer__mobile",
    )

    autocomplete_fields = (
        "retailer",
        "customer",
    )

    readonly_fields = (
        "invoice_number",
        "due_amount",
        "payment_status",
        "created_at",
        "updated_at",
    )

    date_hierarchy = "invoice_date"

    ordering = (
        "-invoice_date",
        "-created_at",
    )

    list_per_page = 25

    fieldsets = (
        (
            "Invoice Information",
            {
                "fields": (
                    "retailer",
                    "customer",
                    "invoice_number",
                    "invoice_date",
                )
            },
        ),
        (
            "Amount Details",
            {
                "fields": (
                    "subtotal",
                    "discount",
                    "gst",
                    "grand_total",
                )
            },
        ),
        (
            "Payment Details",
            {
                "fields": (
                    "paid_amount",
                    "due_amount",
                    "payment_status",
                )
            },
        ),
        (
            "Additional Information",
            {
                "fields": (
                    "remarks",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    inlines = (
        SaleItemInline,
        PaymentInline,
    )


# ============================================================
# Sale Item Admin
# ============================================================

@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    """
    Admin configuration for SaleItem model.
    """

    list_display = (
        "sale",
        "product",
        "unit",
        "quantity",
        "selling_price",
        "mrp",
        "gst",
        "discount",
        "amount",
        "created_at",
    )

    list_filter = (
        "unit",
        "created_at",
    )

    search_fields = (
        "sale__invoice_number",
        "product__product_name",
    )

    autocomplete_fields = (
        "sale",
        "product",
        "unit",
    )

    readonly_fields = (
        "amount",
        "created_at",
    )

    ordering = (
        "-created_at",
    )

    list_per_page = 25


# ============================================================
# Payment Admin
# ============================================================

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Admin configuration for Payment model.
    """

    list_display = (
        "payment_date",
        "receipt_number",
        "customer",
        "sale",
        "retailer",
        "amount",
        "created_at",
    )

    list_filter = (
        "payment_date",
        "retailer",
    )

    search_fields = (
        "receipt_number",
        "customer__customer_name",
        "customer__mobile",
        "sale__invoice_number",
    )

    autocomplete_fields = (
        "retailer",
        "customer", 
        "sale",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    date_hierarchy = "payment_date"

    ordering = (
        "-payment_date",
        "-created_at",
    )

    list_per_page = 25


# ============================================================
# Customer Ledger Admin
# ============================================================

@admin.register(CustomerLedger)
class CustomerLedgerAdmin(admin.ModelAdmin):
    """
    Admin configuration for CustomerLedger model.
    """

    list_display = (
        "date",
        "customer",
        "sale",
        "payment",
        "debit",
        "credit",
        "balance",
        "created_at",
    )

    list_filter = (
        "date",
        "created_at",
    )

    search_fields = (
        "customer__customer_name",
        "customer__mobile",
        "sale__invoice_number",
        "payment__receipt_number",
    )

    autocomplete_fields = (
        "customer",
        "sale",
        "payment",
    )

    readonly_fields = (
        "balance",
        "created_at",
    )

    date_hierarchy = "date"

    ordering = (
        "-date",
        "-id",
    )

    list_per_page = 25

@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    # Read-only view: batch stock changes only through purchases and
    # sales so that product stock stays equal to the sum of batches.
    list_display = ("product", "batch_number", "expiry_date", "quantity", "mrp", "retailer")
    list_filter = ("retailer",)
    search_fields = ("product__product_name", "batch_number")
    readonly_fields = ("retailer", "product", "batch_number", "expiry_date", "mrp", "purchase_price", "quantity", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 0
    readonly_fields = ("amount",)


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ("quotation_number", "retailer", "customer", "quotation_date", "status", "grand_total")
    list_filter = ("status", "retailer")
    search_fields = ("quotation_number", "customer__customer_name", "customer__mobile")
    readonly_fields = ("quotation_number", "converted_sale")
    inlines = [QuotationItemInline]

@admin.register(SaleReturn)
class SaleReturnAdmin(admin.ModelAdmin):
    # Read-only: returns change stock and accounts, so they are made
    # only from the app's return pages.
    list_display = ("credit_note_number", "retailer", "customer", "sale", "return_date", "total", "refund_amount")
    list_filter = ("retailer",)
    search_fields = ("credit_note_number", "sale__invoice_number", "customer__customer_name")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    list_display = ("debit_note_number", "retailer", "supplier", "purchase", "return_date", "total", "refund_amount")
    list_filter = ("retailer",)
    search_fields = ("debit_note_number", "purchase__bill_number", "supplier__supplier_name")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from .models import ShopTypeService


@admin.register(ShopTypeService)
class ShopTypeServiceAdmin(admin.ModelAdmin):
    # One row per shop type (made by migration 0011). The app's
    # "Shop types" page is the normal place to switch them.
    list_display = ("shop_type", "is_active", "changed_by", "changed_at")
    readonly_fields = ("shop_type", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.changed_by = request.user
        super().save_model(request, obj, form, change)
