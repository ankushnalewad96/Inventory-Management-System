from django.db import models
from django.contrib.auth.models import AbstractUser


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
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    shop_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=150)

    mobile = models.CharField(max_length=15)
    email = models.EmailField()

    gst_number = models.CharField(max_length=20, blank=True, null=True)
    pan_number = models.CharField(max_length=10, blank=True, null=True)

    address = models.TextField()

    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.shop_name


class Supplier(models.Model):
    """
    Stores supplier/vendor details for a retailer.
    """

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

    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE
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
    barcode = models.CharField(max_length=100, blank=True, null=True, unique=True)
    hsn_code = models.CharField(max_length=20)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp = models.DecimalField(max_digits=10, decimal_places=2)
    minimum_stock = models.PositiveIntegerField(default=0)
    current_stock = models.PositiveIntegerField(default=0)
    gst = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["product_name"]

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


# Purchase Item Model 
class PurchaseItem(models.Model):
    """
    PurchaseItem Model - Stores individual product line items for a purchase.

    Each row represents one product bought within a Purchase bill,
    capturing quantity, pricing, batch, and expiry details. This model
    is what actually updates product stock when a purchase is recorded.
    """

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

    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    free_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mrp = models.DecimalField(max_digits=10,decimal_places=2, default=0)
    gst = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expiry_date = models.DateField(blank=True,null=True)
    batch_number = models.CharField(max_length=100, blank=True, null=True)
    remarks = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.purchase.bill_number} - {self.product.product_name}"




