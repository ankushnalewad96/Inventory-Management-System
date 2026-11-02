from django.db import models, transaction
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError

from .shop_types import DEFAULT_SHOP_TYPE, SHOP_TYPE_CHOICES, get_features
from .shop_services import ShopScopedManager
from django.utils.translation import gettext







# Django User Authentication model
class CustomUser(AbstractUser):
    """
    Custom User Model - Extends Django's AbstractUser to add user type functionality.
    """
    USER_TYPE = (
        ("admin", "Admin"),
        ("retailer", "Retailer"),
    )

    user_type = models.CharField(max_length=20, choices=USER_TYPE, default="retailer")

    def __str__(self):
        return self.username

    def is_retailer(self):
        """
        Check if the user is a retailer.
        
        Returns:
            bool: True if user_type is 'retailer', False otherwise.
        """
        return self.user_type == "retailer"

    def is_admin_user(self):
        """
        Check if the user is an admin.
        
        Returns:
            bool: True if user_type is 'admin', False otherwise.
        """
        return self.user_type == "admin"


# Retailer Profile Details model
class Retailer(models.Model):
    """
    Retailer Profile Model - Stores detailed business information for retailer users.
    
    This model serves as the profile/extension for users who are retailers. 
    It contains all business-specific information that a retailer needs to 
    operate within the system, including shop details, contact information, 
    tax details, and address.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("shop_type")
    all_objects = models.Manager()
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    shop_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=150)

    # Kind of shop. Decides which features are on (see shop_types.py).
    shop_type = models.CharField(
        max_length=20,
        choices=SHOP_TYPE_CHOICES,
        default=DEFAULT_SHOP_TYPE,
        db_index=True,
    )

    mobile = models.CharField(max_length=15)
    email = models.EmailField()

    gst_number = models.CharField(max_length=20, blank=True, null=True)
    pan_number = models.CharField(max_length=10, blank=True, null=True)

    # Drug licence numbers (features.drug_licence), printed on invoices.
    drug_licence_number = models.CharField(max_length=50, blank=True, default="")
    drug_licence_number_2 = models.CharField(max_length=50, blank=True, default="")

    address = models.TextField()

    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.shop_name

    @property
    def features(self):
        """Feature switches for this shop (see shop_types.py)."""
        return get_features(self)


class ShopTypeService(models.Model):
    """
    On/off switch for a whole shop type, set by the admin.
    Off = its shops and all their records are hidden and its owners cannot
    sign in (see shop_services.py). Nothing is deleted.
    A shop type without a row counts as on.
    """

    shop_type = models.CharField(max_length=20, choices=SHOP_TYPE_CHOICES, unique=True)
    is_active = models.BooleanField(default=True)
    changed_at = models.DateTimeField(auto_now=True)
    changed_by = models.ForeignKey(
        "CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    objects = models.Manager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["shop_type"]

    def __str__(self):
        return f"{self.get_shop_type_display()}: {'on' if self.is_active else 'off'}"


class Supplier(models.Model):
    """
    Stores supplier/vendor details for a retailer.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="suppliers"
    )

    supplier_name = models.CharField(max_length=200) 
    contact_person = models.CharField(max_length=150, blank=True, null=True)
    mobile = models.CharField(max_length=15)
    alternate_mobile = models.CharField(max_length=15, blank=True, null=True)
    email = models.EmailField(blank=True,null=True)
    gst_number = models.CharField(max_length=20, blank=True, null=True)
    pan_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["supplier_name"]
        unique_together = ("retailer", "supplier_name")

    def __str__(self):
        return self.supplier_name


# Product Brand Model
class Brand(models.Model):
    """
    Brand Model - Stores product brands defined by each retailer.

    Each retailer can maintain their own list of brands to associate
    with their products (e.g., Nike, Samsung, Local Brand X). This helps
    in organizing and filtering products by brand.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()
    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE
    )

    brand_name = models.CharField(max_length=100)

    def __str__(self):
        return self.brand_name


# Product Category Model
class Category(models.Model):
    """
    Category Model - Stores product categories defined by each retailer.

    Each retailer can create their own set of categories to organize
    their products (e.g., Groceries, Electronics, Clothing). This allows
    products to be grouped and filtered by category on a per-retailer basis.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()
    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE
    )

    category_name = models.CharField(max_length=100)

    def __str__(self):
        return self.category_name


# Unit of Measurement Model
class Unit(models.Model):
    """
    Unit Model - Stores measurement units used for products.

    Defines common units (e.g., Kilogram, Piece, Litre) that can be
    assigned to products to specify how they are sold or measured.
    This is a shared/global list, not tied to a specific retailer.
    """
    name = models.CharField(max_length=50)
    short_name = models.CharField(max_length=10)

    def __str__(self):
        return self.short_name


# Product Model
class Product(models.Model):
    """
    Product Model - Stores all product/inventory details for a retailer.

    Each retailer maintains their own product catalog, with each product
    linked to a category, brand, and unit. This model holds pricing,
    stock, and tax details used across purchase, sale, and inventory
    tracking features.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="products"
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="products"
    )

    brand = models.ForeignKey(
        Brand,
        on_delete=models.CASCADE,
        related_name="products"
    )

    # Base unit: the product is stocked and sold in this unit.
    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE
    )

    # Optional bigger unit it is bought in (features.unit_conversion):
    # 1 purchase_unit = conversion_factor x unit (e.g. 1 Box = 100 pc).
    purchase_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    conversion_factor = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("1"),
        help_text="How many base units are in one purchase unit.",
    )

    UNIT_CHOICES = (
        ("Kg", "Kg"),
        ("Gram", "Gram"),
        ("Litre", "Litre"),
        ("Piece", "Piece"),
        ("Packet", "Packet"),
        ("Box", "Box"),
        ("Bottle", "Bottle"),
    )

    product_name = models.CharField(max_length=200)

    # Drug details (pharmacy shops: features.prescription_details).
    SCHEDULE_NONE = "none"
    SCHEDULE_H = "H"
    SCHEDULE_H1 = "H1"
    SCHEDULE_X = "X"
    SCHEDULE_CHOICES = [
        (SCHEDULE_NONE, "Not scheduled"),
        (SCHEDULE_H, "Schedule H"),
        (SCHEDULE_H1, "Schedule H1"),
        (SCHEDULE_X, "Schedule X"),
    ]
    # Sales of these schedules need patient and doctor details.
    PRESCRIPTION_SCHEDULES = (SCHEDULE_H, SCHEDULE_H1, SCHEDULE_X)

    salt_composition = models.CharField(max_length=255, blank=True, default="")
    manufacturer = models.CharField(max_length=150, blank=True, default="")
    schedule = models.CharField(max_length=5, choices=SCHEDULE_CHOICES, default=SCHEDULE_NONE)

    # Unique within a shop only (see Meta.constraints): two shops can
    # sell the same barcoded product.
    barcode = models.CharField(max_length=100, blank=True, null=True)
    # Required or optional depending on the shop's features (hsn_required).
    hsn_code = models.CharField(max_length=20, blank=True, default="")
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    # Optional for shops where features.mrp_required is off (e.g. hardware).
    mrp = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    # Price for wholesale customers (features.price_levels). Empty = the
    # normal selling price is used for everyone.
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    # Size / gauge / grade, e.g. "1.5 sq mm, FR, 90 m" (features.product_specification).
    specification = models.CharField(max_length=255, blank=True, default="")
    # Stock in the product's unit; fractions (2.5 kg) only for shops with
    # features.decimal_quantity (checked in the views).
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    current_stock = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    gst = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["product_name"]

        constraints = [
            models.UniqueConstraint(
                fields=["retailer", "barcode"],
                condition=models.Q(barcode__isnull=False) & ~models.Q(barcode=""),
                name="unique_product_barcode_per_shop",
            ),
            # Stock can never go below zero (was guaranteed by PositiveIntegerField).
            models.CheckConstraint(
                condition=models.Q(current_stock__gte=0),
                name="product_current_stock_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_stock__gte=0),
                name="product_minimum_stock_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(conversion_factor__gt=0),
                name="product_conversion_factor_positive",
            ),
        ]

    @property
    def has_purchase_unit(self):
        """True when the product is bought in a bigger unit (box, strip...)."""
        return bool(self.purchase_unit_id) and self.purchase_unit_id != self.unit_id

    @property
    def needs_prescription(self):
        """Schedule H / H1 / X drug: sale needs patient and doctor details."""
        return self.schedule in self.PRESCRIPTION_SCHEDULES

    def price_for(self, customer, features):
        """
        Selling price for this customer: the wholesale price for a
        wholesale customer when the shop has price levels and the
        product has one; otherwise the normal selling price.
        """

        if (
            features.price_levels
            and customer is not None
            and customer.price_level == Customer.PRICE_LEVEL_WHOLESALE
            and self.wholesale_price is not None
        ):
            return self.wholesale_price

        return self.selling_price

    def __str__(self):
        return self.product_name


# Purchase Bill Model 
class Purchase(models.Model):
    """
    Purchase Model - Stores purchase bill/invoice details from suppliers.

    Represents a single purchase transaction made by a retailer, including
    supplier details, billing information, charges, and payment status.
    Acts as the parent record for individual purchased items (see
    PurchaseItem model).
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    PAYMENT_STATUS = (
        ("Paid", "Paid"),
        ("Partial", "Partial"),
        ("Unpaid", "Unpaid"),
    )

    PAYMENT_TYPE = (
        ("Cash", "Cash"),
        ("UPI", "UPI"),
        ("Bank Transfer", "Bank Transfer"),
        ("Cheque", "Cheque"),
        ("Credit", "Credit"),
    )

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="purchases"
    )

    supplier = models.ForeignKey(
            Supplier,
            on_delete=models.CASCADE,
            related_name="supplier"
        )
    
    bill_number = models.CharField(max_length=100)
    bill_date = models.DateField()
    bill_time = models.TimeField(blank=True, null=True)
    invoice_date = models.DateField()
    payment_terms = models.CharField(max_length=50, blank=True, null=True)
    due_date = models.DateField(blank=True, null=True)
    state_of_supply = models.CharField(max_length=100,blank=True, null=True)
    warehouse = models.CharField(max_length=100, blank=True, null=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_type = models.CharField(max_length=30, choices=PAYMENT_TYPE, blank=True, null=True)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default="Unpaid")
    remarks = models.TextField(blank=True, null=True)
    bill_file = models.FileField(upload_to="purchase_bills/", blank=True, null=True)

    # GST split decided when the bill is saved (features.b2b_tax_split):
    # supplier in the shop's state -> CGST + SGST, other state -> IGST.
    tax_type = models.CharField(max_length=5, blank=True, default="")
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Part of debit notes (purchase returns) used to reduce this bill's due.
    returned_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "-bill_date",
            "-created_at"
        ]

        indexes = [
            # Retailer's purchases sorted by latest bill date
            models.Index(
                fields=["retailer", "-bill_date"],
                name="purchase_retailer_date_idx"
            ),

            # Supplier-wise purchase filtering and date sorting
            models.Index(
                fields=["retailer", "supplier", "-bill_date"],
                name="purchase_supplier_date_idx"
            ),

            # Payment status filtering and date sorting
            models.Index(
                fields=["retailer", "payment_status", "-bill_date"],
                name="purchase_status_date_idx"
            ),
        ]

    def __str__(self):
        return self.bill_number


class ProductBatch(models.Model):
    """
    A batch of a product with its own expiry (features.batch_tracking).

    For batch-tracked shops Product.current_stock always equals the sum
    of its batches' quantity; both change together inside one
    transaction (see batches.py). Quantities are in the product's base
    unit (e.g. tablets).
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    OPENING_BATCH = "OPENING"

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="product_batches",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="batches",
    )

    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField()

    # Per base unit (e.g. per tablet).
    mrp = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Product Batch"
        verbose_name_plural = "Product Batches"
        ordering = ["expiry_date", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["product", "batch_number"],
                name="unique_batch_per_product",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name="batch_quantity_not_negative",
            ),
        ]

        indexes = [
            models.Index(fields=["retailer", "expiry_date"], name="batch_retailer_expiry_idx"),
        ]

    def __str__(self):
        return f"{self.product.product_name} - {self.batch_number} (exp {self.expiry_date:%m/%Y})"

    def is_expired(self, on_date):
        return self.expiry_date < on_date


# Purchase Item Model
class PurchaseItem(models.Model):
    """
    PurchaseItem Model - Stores individual product line items for a purchase.

    Each row represents one product bought within a Purchase bill,
    capturing quantity, pricing, batch, and expiry details. This model
    is what actually updates product stock when a purchase is recorded.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("purchase__retailer__shop_type")
    all_objects = models.Manager()

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="items"
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )

    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE
    )

    # quantity / free_quantity / purchase_price are as entered, in `unit`.
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    free_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    # Base units in one `unit` at the time of purchase (1 when bought in
    # the product's base unit). Stock added = (quantity + free) x factor.
    conversion_factor = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1"))
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mrp = models.DecimalField(max_digits=10,decimal_places=2, default=0)
    gst = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expiry_date = models.DateField(blank=True,null=True)
    batch_number = models.CharField(max_length=100, blank=True, null=True)
    # The batch this line went into (batch-tracked shops only).
    batch = models.ForeignKey(
        ProductBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_items",
    )
    remarks = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.purchase.bill_number} - {self.product.product_name}"

    @property
    def is_converted(self):
        """Bought in a purchase unit (box, strip...) rather than the base unit."""
        return self.conversion_factor != 1

    @property
    def base_quantity(self):
        """Stock added, in the product's base unit (quantity + free)."""
        return ((self.quantity + self.free_quantity) * self.conversion_factor).quantize(Decimal("0.001"))

    @property
    def base_unit_price(self):
        """Purchase price per base unit (e.g. per piece when bought per box)."""
        factor = self.conversion_factor or Decimal("1")
        return (self.purchase_price / factor).quantize(Decimal("0.01"))









# Sales Module
class SupplierProduct(models.Model):
    """
    A product the shop buys from a supplier ("what can I buy from whom").

    Added automatically when a purchase bill is saved (with the last
    price and date), and can also be added / removed by hand on the
    supplier products page. The purchase page uses it to show only the
    chosen supplier's products, or only the suppliers of a product.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    retailer = models.ForeignKey(Retailer, on_delete=models.CASCADE, related_name="supplier_products")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="supplier_products")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="supplier_links")
    last_purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    last_purchase_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["supplier__supplier_name", "product__product_name"]
        constraints = [
            models.UniqueConstraint(fields=["supplier", "product"], name="unique_supplier_product"),
        ]

    def __str__(self):
        return f"{self.supplier} - {self.product}"

    def clean(self):
        if self.supplier_id and self.product_id:
            if self.supplier.retailer_id != self.product.retailer_id:
                raise ValidationError(gettext('The supplier and the product must belong to the same shop.'))


class Customer(models.Model):
    """
    Represents a customer belonging to a specific retailer.

    Each retailer can maintain its own customer list, balances,
    credit limits, and customer information.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="customers",
        db_index=True,
    )

    customer_name = models.CharField(
        max_length=200,
        verbose_name="Customer Name",
    )

    mobile = models.CharField(
        max_length=15,
        verbose_name="Mobile Number",
    )

    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name="Email Address",
    )

    address = models.TextField(
        blank=True,
        null=True,
        verbose_name="Address",
    )

    gst_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="GST Number",
    )

    opening_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Opening Balance",
        help_text="Outstanding amount brought forward from previous records.",
    )

    credit_limit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Credit Limit",
    )

    # Which price the customer pays (features.price_levels). Shops without
    # price levels always charge the normal selling price.
    PRICE_LEVEL_RETAIL = "retail"
    PRICE_LEVEL_WHOLESALE = "wholesale"
    PRICE_LEVEL_CHOICES = [
        (PRICE_LEVEL_RETAIL, "Retail"),
        (PRICE_LEVEL_WHOLESALE, "Wholesale"),
    ]

    price_level = models.CharField(
        max_length=10,
        choices=PRICE_LEVEL_CHOICES,
        default=PRICE_LEVEL_RETAIL,
    )

    # Customer's state (states.py key). Another state than the shop's
    # means IGST on their bills; empty = same state as the shop.
    state = models.CharField(max_length=50, blank=True, default="")

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Active",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
        ordering = ["customer_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["retailer", "mobile"],
                name="unique_customer_mobile_per_retailer",
            ),
        ]

        indexes = [
            models.Index(
                fields=["retailer", "is_active"],
                name="customer_retailer_active_idx",
            ),
            models.Index(
                fields=["retailer", "mobile"],
                name="customer_retailer_mobile_idx",
            ),
            models.Index(
                fields=["retailer", "customer_name"],
                name="customer_retailer_name_idx",
            ),
        ]

    def __str__(self):
        return f"{self.customer_name} - {self.mobile}"

    @property
    def state_display(self):
        """State name for bills ("" when not set)."""
        from .states import state_name
        return state_name(self.state)


class Sale(models.Model):
    """
    Represents the master/header record of a sales invoice.

    Each sale belongs to a retailer and a customer.
    Invoice numbers are generated automatically per retailer.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    PAYMENT_TYPE_CASH = "Cash"
    PAYMENT_TYPE_UPI = "UPI"
    PAYMENT_TYPE_BANK = "Bank Transfer"
    PAYMENT_TYPE_CHEQUE = "Cheque"
    PAYMENT_TYPE_CREDIT = "Credit"

    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_TYPE_CASH, "Cash"),
        (PAYMENT_TYPE_UPI, "UPI"),
        (PAYMENT_TYPE_BANK, "Bank Transfer"),
        (PAYMENT_TYPE_CHEQUE, "Cheque"),
        (PAYMENT_TYPE_CREDIT, "Credit"),
    ]

    PAYMENT_STATUS_PAID = "Paid"
    PAYMENT_STATUS_PARTIAL = "Partial"
    PAYMENT_STATUS_UNPAID = "Unpaid"

    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_PAID, "Paid"),
        (PAYMENT_STATUS_PARTIAL, "Partial"),
        (PAYMENT_STATUS_UNPAID, "Unpaid"),
    ]

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="sales",
        db_index=True,
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="sales",
        db_index=True,
    )

    invoice_number = models.CharField(
        max_length=100,
        editable=False,
    )

    invoice_date = models.DateField()

    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    gst = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    grand_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    due_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
        blank=True,
        null=True,
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_STATUS_UNPAID,
    )

    remarks = models.TextField(
        blank=True,
        null=True,
    )

    # GST split decided when the sale is saved (features.b2b_tax_split):
    # "intra" = CGST + SGST, "inter" = IGST, "" = no split shown.
    tax_type = models.CharField(max_length=5, blank=True, default="")
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # Part of credit notes (sale returns) used to reduce this bill's due.
    returned_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # Prescription details (features.prescription_details). Required when
    # the sale has a Schedule H / H1 / X drug.
    patient_name = models.CharField(max_length=150, blank=True, default="")
    doctor_name = models.CharField(max_length=150, blank=True, default="")
    prescription_note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Sale"
        verbose_name_plural = "Sales"
        ordering = ["-invoice_date", "-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["retailer", "invoice_number"],
                name="unique_sale_invoice_per_retailer",
            ),
        ]

        indexes = [
            models.Index(
                fields=["retailer", "invoice_date"],
                name="sale_retailer_date_idx",
            ),
            models.Index(
                fields=["retailer", "customer"],
                name="sale_retailer_customer_idx",
            ),
            models.Index(
                fields=["retailer", "payment_status"],
                name="sale_retailer_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.customer.customer_name}"

    def clean(self):
        """
        Validate retailer/customer relationship and payment values.
        """

        if self.customer_id and self.retailer_id:
            if self.customer.retailer_id != self.retailer_id:
                raise ValidationError(
                    gettext('The selected customer does not belong to this retailer.')
                )

        if self.paid_amount < Decimal("0.00"):
            raise ValidationError(
                {"paid_amount": gettext('Paid amount cannot be negative.')}
            )

        if self.paid_amount > self.grand_total:
            raise ValidationError(
                {"paid_amount": gettext('Paid amount cannot exceed the grand total.')}
            )

        if self.discount < Decimal("0.00"):
            raise ValidationError(
                {"discount": gettext('Discount cannot be negative.')}
            )

        if self.gst < Decimal("0.00"):
            raise ValidationError(
                {"gst": gettext('GST cannot be negative.')}
            )

    def _generate_invoice_number(self):
        """
        Generate the next invoice number for the retailer.

        Format:
            INV-YYYY-000001
            INV-YYYY-000002
            INV-YYYY-000003
        """

        year = self.invoice_date.year

        prefix = f"INV-{year}-"

        last_sale = (
            Sale.objects
            .filter(
                retailer=self.retailer,
                invoice_number__startswith=prefix,
            )
            .order_by("-invoice_number")
            .first()
        )

        if last_sale:
            try:
                last_number = int(
                    last_sale.invoice_number.split("-")[-1]
                )
            except (ValueError, IndexError):
                last_number = 0
        else:
            last_number = 0

        next_number = last_number + 1

        return f"{prefix}{next_number:06d}"

    def save(self, *args, **kwargs):
        """
        Save sale and automatically generate invoice number,
        due amount and payment status.
        """

        is_new = self.pk is None

        if is_new and not self.invoice_number:
            with transaction.atomic():
                # Lock the retailer row to prevent two simultaneous
                # sales from generating the same invoice number.
                locked_retailer = (
                    Retailer.objects
                    .select_for_update()
                    .get(pk=self.retailer_id)
                )

                self.retailer = locked_retailer

                self.invoice_number = self._generate_invoice_number()

                self._calculate_payment_details()

                super().save(*args, **kwargs)

            return

        self._calculate_payment_details()

        super().save(*args, **kwargs)

    def _calculate_payment_details(self):
        """
        Calculate due amount and payment status automatically.
        """

        # Returned goods (credit notes) reduce what is still due.
        settled = self.paid_amount + (self.returned_amount or Decimal("0.00"))

        self.due_amount = (
            self.grand_total - settled
        ).quantize(Decimal("0.01"))

        if settled <= Decimal("0.00"):
            self.payment_status = self.PAYMENT_STATUS_UNPAID

        elif settled < self.grand_total:
            self.payment_status = self.PAYMENT_STATUS_PARTIAL

        else:
            self.payment_status = self.PAYMENT_STATUS_PAID
            self.due_amount = Decimal("0.00")


class SaleItem(models.Model):
    """
    Represents an individual product/item sold as part of a Sale.

    Stock deduction is handled transactionally by the sales service,
    rather than directly inside save(), to prevent accidental
    double deduction during updates/deletions.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("sale__retailer__shop_type")
    all_objects = models.Manager()

    sale = models.ForeignKey(
        Sale,
        on_delete=models.CASCADE,
        related_name="items",
        db_index=True,
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="sale_items",
        db_index=True,
    )

    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="sale_items",
    )

    # Batch the quantity came from (batch-tracked shops). A line that
    # needed more than one batch is saved as one SaleItem per batch.
    batch = models.ForeignKey(
        ProductBatch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_items",
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
    )

    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    mrp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )

    gst = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="GST percentage for this item.",
    )

    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Sale Item"
        verbose_name_plural = "Sale Items"
        ordering = ["id"]

        indexes = [
            models.Index(
                fields=["sale", "product"],
                name="saleitem_sale_product_idx",
            ),
            models.Index(
                fields=["product"],
                name="saleitem_product_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.sale.invoice_number} - "
            f"{self.product} - {self.quantity}"
        )

    def clean(self):
        """
        Validate the SaleItem values.

        Actual stock availability is checked inside the atomic
        stock-deduction service because the Product row must be
        locked while checking and updating stock.
        """

        if self.quantity <= Decimal("0.00"):
            raise ValidationError(
                {"quantity": gettext('Quantity must be greater than zero.')}
            )

        if self.selling_price < Decimal("0.00"):
            raise ValidationError(
                {"selling_price": gettext('Selling price cannot be negative.')}
            )

        if self.mrp is not None and self.mrp < Decimal("0.00"):
            raise ValidationError(
                {"mrp": gettext('MRP cannot be negative.')}
            )

        if self.gst < Decimal("0.00"):
            raise ValidationError(
                {"gst": gettext('GST cannot be negative.')}
            )

        if self.gst > Decimal("100.00"):
            raise ValidationError(
                {"gst": gettext('GST cannot exceed 100%.')}
            )

        if self.discount < Decimal("0.00"):
            raise ValidationError(
                {"discount": gettext('Discount cannot be negative.')}
            )

    def calculate_amount(self):
        """
        Calculate the final line amount.

        Formula:

            Gross Amount = quantity × selling_price
            Taxable Amount = Gross Amount - discount
            GST Amount = Taxable Amount × GST%
            Final Amount = Taxable Amount + GST Amount
        """

        gross_amount = self.quantity * self.selling_price

        taxable_amount = gross_amount - self.discount

        if taxable_amount < Decimal("0.00"):
            raise ValidationError(
                gettext('Discount cannot be greater than the gross amount.')
            )

        gst_amount = taxable_amount * (
            self.gst / Decimal("100.00")
        )

        final_amount = taxable_amount + gst_amount

        return final_amount.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    def save(self, *args, **kwargs):
        """
        Calculate the line amount before saving.

        NOTE:
        Stock is intentionally NOT modified here.
        Stock changes must happen through the transactional
        sales service.
        """

        self.amount = self.calculate_amount()

        super().save(*args, **kwargs)


class Quotation(models.Model):
    """
    A price quotation / estimate for a customer (features.quotations).

    It does not touch stock or the customer's account. Converting it
    creates a normal sale through the sales screen; the quotation is then
    marked converted and linked to that sale.
    Numbers: QT-YYYY-000001, per shop.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    STATUS_OPEN = "open"
    STATUS_CONVERTED = "converted"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_CONVERTED, "Converted to sale"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    retailer = models.ForeignKey(Retailer, on_delete=models.CASCADE, related_name="quotations")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="quotations")
    quotation_number = models.CharField(max_length=50, editable=False)
    quotation_date = models.DateField()
    valid_until = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    remarks = models.TextField(blank=True, default="")

    # The sale this quotation became (status = converted).
    converted_sale = models.OneToOneField(
        Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name="quotation",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-quotation_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["retailer", "quotation_number"],
                name="unique_quotation_number_per_shop",
            ),
        ]
        indexes = [
            models.Index(fields=["retailer", "status"], name="quotation_retailer_status_idx"),
        ]

    def __str__(self):
        return f"{self.quotation_number} - {self.customer.customer_name}"

    def is_expired(self, on_date):
        return (
            self.status == self.STATUS_OPEN
            and self.valid_until is not None
            and self.valid_until < on_date
        )

    def _generate_number(self):
        prefix = f"QT-{self.quotation_date.year}-"
        last = (
            Quotation.objects
            .filter(retailer=self.retailer, quotation_number__startswith=prefix)
            .order_by("-quotation_number")
            .values_list("quotation_number", flat=True)
            .first()
        )
        try:
            last_number = int(last.split("-")[-1]) if last else 0
        except (ValueError, IndexError):
            last_number = 0
        return f"{prefix}{last_number + 1:06d}"

    def save(self, *args, **kwargs):
        if self.pk is None and not self.quotation_number:
            with transaction.atomic():
                # Lock the shop row so two quotations never get one number.
                self.retailer = Retailer.objects.select_for_update().get(pk=self.retailer_id)
                self.quotation_number = self._generate_number()
                super().save(*args, **kwargs)
            return

        super().save(*args, **kwargs)


class QuotationItem(models.Model):
    """One line of a quotation. Prices are the quoted prices."""

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("quotation__retailer__shop_type")
    all_objects = models.Manager()

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="quotation_items")
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    gst = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), editable=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quotation.quotation_number} - {self.product}"

    def calculate_amount(self):
        taxable = self.quantity * self.selling_price - self.discount
        if taxable < 0:
            raise ValidationError(gettext('Discount cannot be greater than the gross amount.'))
        return (taxable + taxable * self.gst / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def save(self, *args, **kwargs):
        self.amount = self.calculate_amount()
        super().save(*args, **kwargs)


def next_document_number(model, retailer, field, prefix):
    """
    Next PREFIX-000001 style number for a shop. Call it inside a
    transaction with the shop row locked (see _NumberedDocument.save).
    """

    last = (
        model.objects
        .filter(retailer=retailer, **{f"{field}__startswith": prefix})
        .order_by(f"-{field}")
        .values_list(field, flat=True)
        .first()
    )

    try:
        number = int(last.rsplit("-", 1)[-1]) + 1 if last else 1
    except ValueError:
        number = 1

    return f"{prefix}{number:06d}"


class SaleReturn(models.Model):
    """
    Goods a customer returned: a credit note (CN-YYYY-000001 per shop).

    Money: the credit first reduces the original bill's due
    (applied_to_bill). The rest is either paid back now (refund_amount,
    cash refund) or kept on the customer's account as advance.
    Stock goes back (into the same batch for batch-tracked items).
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    REFUND_CASH = "cash"
    REFUND_ACCOUNT = "account"
    REFUND_CHOICES = [
        (REFUND_CASH, "Cash refund"),
        (REFUND_ACCOUNT, "Keep as credit on account"),
    ]

    retailer = models.ForeignKey(Retailer, on_delete=models.CASCADE, related_name="sale_returns")
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="returns")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="sale_returns")
    credit_note_number = models.CharField(max_length=50, editable=False)
    return_date = models.DateField()
    reason = models.TextField(blank=True, default="")

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    tax_type = models.CharField(max_length=5, blank=True, default="")
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    refund_mode = models.CharField(max_length=10, choices=REFUND_CHOICES, default=REFUND_ACCOUNT)
    applied_to_bill = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-return_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["retailer", "credit_note_number"],
                name="unique_credit_note_per_shop",
            ),
        ]

    def __str__(self):
        return f"{self.credit_note_number} ({self.sale.invoice_number})"

    @property
    def kept_on_account(self):
        return self.total - self.applied_to_bill - self.refund_amount

    def save(self, *args, **kwargs):
        if self.pk is None and not self.credit_note_number:
            with transaction.atomic():
                self.retailer = Retailer.objects.select_for_update().get(pk=self.retailer_id)
                self.credit_note_number = next_document_number(
                    SaleReturn, self.retailer, "credit_note_number", f"CN-{self.return_date.year}-"
                )
                super().save(*args, **kwargs)
            return

        super().save(*args, **kwargs)


class SaleReturnItem(models.Model):
    """One returned line, tied to the sale line it came from."""

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("sale_return__retailer__shop_type")
    all_objects = models.Manager()

    sale_return = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name="items")
    sale_item = models.ForeignKey(SaleItem, on_delete=models.PROTECT, related_name="return_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    gst = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_return_qty_positive"),
        ]


class PurchaseReturn(models.Model):
    """
    Goods sent back to a supplier: a debit note (DN-YYYY-000001 per shop).

    Money: the debit note first reduces the original bill's due
    (applied_to_bill); anything more (the bill was already paid) is a
    refund the supplier gives back (refund_amount).
    Stock goes out (from the same batch for batch-tracked items).
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    retailer = models.ForeignKey(Retailer, on_delete=models.CASCADE, related_name="purchase_returns")
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="returns")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_returns")
    debit_note_number = models.CharField(max_length=50, editable=False)
    return_date = models.DateField()
    reason = models.TextField(blank=True, default="")

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    tax_type = models.CharField(max_length=5, blank=True, default="")
    cgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    applied_to_bill = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-return_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["retailer", "debit_note_number"],
                name="unique_debit_note_per_shop",
            ),
        ]

    def __str__(self):
        return f"{self.debit_note_number} ({self.purchase.bill_number})"

    def save(self, *args, **kwargs):
        if self.pk is None and not self.debit_note_number:
            with transaction.atomic():
                self.retailer = Retailer.objects.select_for_update().get(pk=self.retailer_id)
                self.debit_note_number = next_document_number(
                    PurchaseReturn, self.retailer, "debit_note_number", f"DN-{self.return_date.year}-"
                )
                super().save(*args, **kwargs)
            return

        super().save(*args, **kwargs)


class PurchaseReturnItem(models.Model):
    """One returned purchase line, in the unit it was bought in."""

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("purchase_return__retailer__shop_type")
    all_objects = models.Manager()

    purchase_return = models.ForeignKey(PurchaseReturn, on_delete=models.CASCADE, related_name="items")
    purchase_item = models.ForeignKey(PurchaseItem, on_delete=models.PROTECT, related_name="return_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    # Base units taken out of stock (quantity x the line's conversion factor).
    base_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    gst = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchase_return_qty_positive"),
        ]


class Payment(models.Model):
    """
    Represents an actual payment received from a customer.

    A single Sale can have multiple Payment records.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    PAYMENT_TYPE_CASH = "Cash"
    PAYMENT_TYPE_UPI = "UPI"
    PAYMENT_TYPE_BANK = "Bank Transfer"
    PAYMENT_TYPE_CHEQUE = "Cheque"

    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_TYPE_CASH, "Cash"),
        (PAYMENT_TYPE_UPI, "UPI"),
        (PAYMENT_TYPE_BANK, "Bank Transfer"),
        (PAYMENT_TYPE_CHEQUE, "Cheque"),
    ]

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="customer_payments",
        db_index=True,
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="payments",
        db_index=True,
    )

    sale = models.ForeignKey(
        Sale,
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
        db_index=True,
    )

    payment_date = models.DateField()

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[],
    )

    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="UPI transaction ID, cheque number, bank reference, etc.",
    )

    receipt_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
    )

    remarks = models.TextField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ["-payment_date", "-created_at"]

        indexes = [
            models.Index(
                fields=["retailer", "customer", "payment_date"],
                name="payment_customer_date_idx",
            ),
            models.Index(
                fields=["retailer", "sale"],
                name="payment_retailer_sale_idx",
            ),
            models.Index(
                fields=["payment_reference"],
                name="payment_reference_idx",
            ),
        ]

    def __str__(self):
        if self.sale:
            return (
                f"{self.customer.customer_name} - "
                f"{self.sale.invoice_number} - "
                f"{self.amount}"
            )

        return (
            f"{self.customer.customer_name} - "
            f"Payment {self.amount}"
        )

    def clean(self):
        if self.amount <= Decimal("0.00"):
            raise ValidationError(
                {"amount": gettext('Payment amount must be greater than zero.')}
            )

        if self.customer_id and self.retailer_id:
            if self.customer.retailer_id != self.retailer_id:
                raise ValidationError(
                    gettext('Customer does not belong to this retailer.')
                )

        if self.sale_id:
            if self.sale.customer_id != self.customer_id:
                raise ValidationError(
                    gettext('Payment customer does not match the sale customer.')
                )

            if self.sale.retailer_id != self.retailer_id:
                raise ValidationError(
                    gettext('Payment retailer does not match the sale retailer.')
                )


class CustomerLedger(models.Model):
    """
    Maintains the financial ledger of a customer.

    Debit:
        Amount added to customer's outstanding balance.

    Credit:
        Amount received from customer.

    Balance:
        Running outstanding balance after the ledger entry.
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("customer__retailer__shop_type")
    all_objects = models.Manager()

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        db_index=True,
    )

    sale = models.ForeignKey(
        Sale,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
        db_index=True,
    )

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
        db_index=True,
    )

    # Credit note (goods returned) this entry belongs to, if any.
    sale_return = models.ForeignKey(
        "SaleReturn",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )

    date = models.DateField()

    debit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    credit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )

    remarks = models.TextField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Customer Ledger"
        verbose_name_plural = "Customer Ledgers"

        ordering = ["date", "id"]

        indexes = [
            models.Index(
                fields=["customer", "date"],
                name="ledger_customer_date_idx",
            ),
            models.Index(
                fields=["customer", "sale"],
                name="ledger_customer_sale_idx",
            ),
            models.Index(
                fields=["customer", "payment"],
                name="ledger_customer_payment_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.customer.customer_name} - "
            f"{self.date} - Balance: {self.balance}"
        )

    def clean(self):
        """
        Validate debit/credit values.

        A ledger entry should normally contain either a debit
        or a credit, not both.
        """

        if self.debit < Decimal("0.00"):
            raise ValidationError(
                {"debit": gettext('Debit cannot be negative.')}
            )

        if self.credit < Decimal("0.00"):
            raise ValidationError(
                {"credit": gettext('Credit cannot be negative.')}
            )

        if (
            self.debit > Decimal("0.00")
            and self.credit > Decimal("0.00")
        ):
            raise ValidationError(
                gettext('A ledger entry cannot have both debit and credit.')
            )

        if self.customer_id and self.sale_id:
            if self.sale.customer_id != self.customer_id:
                raise ValidationError(
                    gettext('Sale customer does not match ledger customer.')
                )

        if self.customer_id and self.payment_id:
            if self.payment.customer_id != self.customer_id:
                raise ValidationError(
                    gettext('Payment customer does not match ledger customer.')
                )






class PurchasePayment(models.Model):
    """
    A payment made to a supplier against a purchase bill.

    A bill can be paid in parts (at purchase time, before or after the
    due date). Purchase.paid_amount / due_amount / payment_status are
    kept in step with the sum of these rows. When the due amount reaches
    zero the bill is fully paid ("closed").
    """

    # Hides rows of switched-off shop types (shop_services.py);
    # all_objects sees everything.
    objects = ShopScopedManager("retailer__shop_type")
    all_objects = models.Manager()

    PAYMENT_TYPE_CHOICES = [
        ("Cash", "Cash"),
        ("UPI", "UPI"),
        ("Bank Transfer", "Bank Transfer"),
        ("Cheque", "Cheque"),
    ]

    retailer = models.ForeignKey(
        Retailer,
        on_delete=models.CASCADE,
        related_name="supplier_payments",
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="payments",
    )

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="payments",
    )

    payment_date = models.DateField()

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    payment_type = models.CharField(
        max_length=20,
        choices=PAYMENT_TYPE_CHOICES,
    )

    reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="UPI transaction ID, cheque number, bank reference, etc.",
    )

    remarks = models.TextField(
        blank=True,
        null=True,
    )

    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Purchase Payment"
        verbose_name_plural = "Purchase Payments"
        ordering = ["payment_date", "id"]

        indexes = [
            models.Index(
                fields=["retailer", "supplier", "payment_date"],
                name="ppay_supplier_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.purchase.bill_number} - {self.amount}"
