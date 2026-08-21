from django.db import models, transaction
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db.models import Max







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









# Sales Module
class Customer(models.Model):
    """
    Represents a customer belonging to a specific retailer.

    Each retailer can maintain its own customer list, balances,
    credit limits, and customer information.
    """

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
        blank=True,
        null=True,
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





class Sale(models.Model):
    """
    Represents the master/header record of a sales invoice.

    Each sale belongs to a retailer and a customer.
    Invoice numbers are generated automatically per retailer.
    """

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
                    "The selected customer does not belong to this retailer."
                )

        if self.paid_amount < Decimal("0.00"):
            raise ValidationError(
                {"paid_amount": "Paid amount cannot be negative."}
            )

        if self.paid_amount > self.grand_total:
            raise ValidationError(
                {"paid_amount": "Paid amount cannot exceed the grand total."}
            )

        if self.discount < Decimal("0.00"):
            raise ValidationError(
                {"discount": "Discount cannot be negative."}
            )

        if self.gst < Decimal("0.00"):
            raise ValidationError(
                {"gst": "GST cannot be negative."}
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

        self.due_amount = (
            self.grand_total - self.paid_amount
        ).quantize(Decimal("0.01"))

        if self.paid_amount <= Decimal("0.00"):
            self.payment_status = self.PAYMENT_STATUS_UNPAID

        elif self.paid_amount < self.grand_total:
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

    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
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
                {"quantity": "Quantity must be greater than zero."}
            )

        if self.selling_price < Decimal("0.00"):
            raise ValidationError(
                {"selling_price": "Selling price cannot be negative."}
            )

        if self.mrp is not None and self.mrp < Decimal("0.00"):
            raise ValidationError(
                {"mrp": "MRP cannot be negative."}
            )

        if self.gst < Decimal("0.00"):
            raise ValidationError(
                {"gst": "GST cannot be negative."}
            )

        if self.gst > Decimal("100.00"):
            raise ValidationError(
                {"gst": "GST cannot exceed 100%."}
            )

        if self.discount < Decimal("0.00"):
            raise ValidationError(
                {"discount": "Discount cannot be negative."}
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
                "Discount cannot be greater than the gross amount."
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





class Payment(models.Model):
    """
    Represents an actual payment received from a customer.

    A single Sale can have multiple Payment records.
    """

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
                {"amount": "Payment amount must be greater than zero."}
            )

        if self.customer_id and self.retailer_id:
            if self.customer.retailer_id != self.retailer_id:
                raise ValidationError(
                    "Customer does not belong to this retailer."
                )

        if self.sale_id:
            if self.sale.customer_id != self.customer_id:
                raise ValidationError(
                    "Payment customer does not match the sale customer."
                )

            if self.sale.retailer_id != self.retailer_id:
                raise ValidationError(
                    "Payment retailer does not match the sale retailer."
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
                {"debit": "Debit cannot be negative."}
            )

        if self.credit < Decimal("0.00"):
            raise ValidationError(
                {"credit": "Credit cannot be negative."}
            )

        if (
            self.debit > Decimal("0.00")
            and self.credit > Decimal("0.00")
        ):
            raise ValidationError(
                "A ledger entry cannot have both debit and credit."
            )

        if self.customer_id and self.sale_id:
            if self.sale.customer_id != self.customer_id:
                raise ValidationError(
                    "Sale customer does not match ledger customer."
                )

        if self.customer_id and self.payment_id:
            if self.payment.customer_id != self.customer_id:
                raise ValidationError(
                    "Payment customer does not match ledger customer."
                )




