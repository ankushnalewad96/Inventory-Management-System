"""
Create one demo shop of every shop type, with products, stock,
suppliers and customers that show off that type's features:

    general     loose quantities (rice by the kg), bought in boxes
    stationery  pens bought in boxes of 10, sold per piece
    cosmetics   simple products, MRP required
    pharmacy    batches with expiry (one near expiry, one expired),
                Schedule H / H1 drugs, drug licence numbers
    hardware    wholesale price + wholesale customer, specification,
                wire bought per coil and sold per metre, a quotation

Every shop also gets a customer in another state, to show IGST.

Safe to run more than once: a shop whose demo login already exists is
skipped, and nothing existing is changed or deleted.

    python manage.py seed_demo_shops
    python manage.py seed_demo_shops --password "MyPass@123" --types pharmacy hardware
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from pharma_app import batches as batch_stock
from pharma_app.models import (
    Brand,
    Category,
    CustomUser,
    Customer,
    Product,
    Quotation,
    QuotationItem,
    Retailer,
    Supplier,
    Unit,
)
from pharma_app.shop_types import SHOP_TYPE_LABELS, get_features

DEFAULT_PASSWORD = "DemoShop@2026"

D = Decimal

# Units are shared by all shops: (short name, full name).
UNITS = {
    "pc": "Piece", "box": "Box", "kg": "Kilogram", "ream": "Ream",
    "tab": "Tablet", "strip": "Strip", "btl": "Bottle",
    "m": "Metre", "coil": "Coil", "ltr": "Litre",
}

# product: name, unit, purchase unit/factor, prices, gst, stock, extras
DEMO_SHOPS = {
    "general": {
        "shop_name": "Demo Kirana Store",
        "category": "Grocery", "brand": "Local",
        "products": [
            {"name": "Basmati Rice", "unit": "kg", "price": ("80", "95", "110"), "gst": "5", "stock": "48.5", "min": "10", "hsn": "1006"},
            {"name": "Toor Dal", "unit": "kg", "price": ("120", "140", "160"), "gst": "5", "stock": "25", "min": "5", "hsn": "0713"},
            {"name": "Bath Soap", "unit": "pc", "buy_in": ("box", "12"), "price": ("28", "35", "40"), "gst": "18", "stock": "60", "min": "12", "hsn": "3401"},
        ],
    },
    "stationery": {
        "shop_name": "Demo Stationery Mart",
        "category": "Stationery", "brand": "Classmate",
        "products": [
            {"name": "Blue Ball Pen", "unit": "pc", "buy_in": ("box", "10"), "price": ("6", "10", "10"), "gst": "18", "stock": "200", "min": "50", "hsn": "9608"},
            {"name": "Notebook 200 Pages", "unit": "pc", "price": ("45", "60", "65"), "gst": "0", "stock": "80", "min": "20", "hsn": "4820"},
            {"name": "A4 Copier Paper", "unit": "ream", "price": ("230", "280", "300"), "gst": "18", "stock": "15", "min": "5", "hsn": "4802"},
        ],
    },
    "cosmetics": {
        "shop_name": "Demo Beauty & Gifts",
        "category": "Beauty", "brand": "Glow",
        "products": [
            {"name": "Face Cream 50g", "unit": "pc", "price": ("150", "199", "225"), "gst": "18", "stock": "30", "min": "6", "hsn": "3304"},
            {"name": "Matte Lipstick", "unit": "pc", "price": ("220", "299", "349"), "gst": "18", "stock": "24", "min": "6", "hsn": "3304"},
            {"name": "Phone Back Cover", "unit": "pc", "price": ("80", "149", "199"), "gst": "18", "stock": "40", "min": "10", "hsn": "3926"},
        ],
    },
    "pharmacy": {
        "shop_name": "Demo Medical Store",
        "category": "Medicine", "brand": "Generic",
        "drug_licence": ("20B-MH-DEMO-001", "21B-MH-DEMO-001"),
        "products": [
            {
                "name": "Paracetamol 500mg", "unit": "tab", "buy_in": ("strip", "10"),
                "price": ("1.50", "2.00", "2.50"), "gst": "5", "min": "50", "hsn": "3004",
                "salt": "Paracetamol 500mg", "manufacturer": "Demo Pharma Ltd", "schedule": "none",
                # (batch, days until expiry, quantity): near expiry, good, expired
                "batches": [("PCM-A1", 20, "40"), ("PCM-B2", 400, "200"), ("PCM-OLD", -5, "10")],
            },
            {
                "name": "Azithromycin 500mg", "unit": "tab", "buy_in": ("strip", "3"),
                "price": ("20", "28", "35"), "gst": "5", "min": "9", "hsn": "3004",
                "salt": "Azithromycin 500mg", "manufacturer": "Demo Pharma Ltd", "schedule": "H1",
                "batches": [("AZI-01", 300, "30")],
            },
            {
                "name": "Cough Syrup 100ml", "unit": "btl",
                "price": ("60", "85", "95"), "gst": "5", "min": "5", "hsn": "3004",
                "salt": "Dextromethorphan + Chlorpheniramine", "manufacturer": "Demo Pharma Ltd", "schedule": "H",
                "batches": [("CS-11", 60, "12")],
            },
        ],
    },
    "hardware": {
        "shop_name": "Demo Hardware & Electricals",
        "category": "Electrical", "brand": "Finolex",
        "products": [
            {
                "name": "Copper Wire 1.5 sq mm", "unit": "m", "buy_in": ("coil", "90"),
                "price": ("16", "22", None), "wholesale": "19", "gst": "18", "stock": "270", "min": "90",
                "hsn": "8544", "spec": "1.5 sq mm, FR PVC, 90 m coil, red",
            },
            {
                "name": "PVC Pipe 1 inch", "unit": "m",
                "price": ("35", "48", None), "wholesale": "42", "gst": "18", "stock": "120.5", "min": "20",
                "hsn": "3917", "spec": "25 mm, 4 kg/cm2",
            },
            {
                "name": "Exterior Paint", "unit": "ltr",
                "price": ("260", "330", "360"), "wholesale": "300", "gst": "18", "stock": "40", "min": "10",
                "hsn": "3209", "spec": "Weather-proof emulsion, white",
            },
        ],
    },
}


class Command(BaseCommand):
    help = "Create one demo shop per shop type (skips shops that already exist; never deletes data)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password for the demo logins.")
        parser.add_argument(
            "--types", nargs="+", choices=sorted(SHOP_TYPE_LABELS), default=list(DEMO_SHOPS),
            help="Only these shop types.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        if len(password) < 8:
            raise CommandError("Use a password of at least 8 characters.")

        created, skipped = [], []

        for shop_type in options["types"]:
            username = f"demo_{shop_type}"

            if CustomUser.objects.filter(username=username).exists():
                skipped.append(username)
                continue

            with transaction.atomic():
                shop = self._create_shop(shop_type, username, password)

            created.append((username, shop))

        for username, shop in created:
            self.stdout.write(self.style.SUCCESS(
                f"Created {shop.shop_name} ({SHOP_TYPE_LABELS[shop.shop_type]}) - login: {username}"
            ))
        for username in skipped:
            self.stdout.write(f"Skipped {username}: already exists (left unchanged).")

        if created:
            self.stdout.write(f"Password for the new demo logins: {password}")

    # ------------------------------------------------------------ helpers

    def _unit(self, short_name):
        unit = Unit.objects.filter(short_name__iexact=short_name).first()
        if unit is None:
            unit = Unit.objects.create(name=UNITS[short_name], short_name=short_name)
        return unit

    def _create_shop(self, shop_type, username, password):
        spec = DEMO_SHOPS[shop_type]

        user = CustomUser.objects.create_user(
            username=username, email=f"{username}@example.com", password=password, user_type="retailer",
        )
        shop = Retailer.objects.create(
            user=user,
            shop_name=spec["shop_name"],
            owner_name="Demo Owner",
            shop_type=shop_type,
            mobile="9000000000",
            email=f"{username}@example.com",
            address="1 Demo Market Road",
            city="Pune",
            state="maharashtra",
            pincode="411001",
            gst_number="27AAAAA0000A1Z5",
        )
        features = get_features(shop)

        if features.drug_licence and spec.get("drug_licence"):
            shop.drug_licence_number, shop.drug_licence_number_2 = spec["drug_licence"]
            shop.save(update_fields=["drug_licence_number", "drug_licence_number_2"])

        category = Category.objects.create(retailer=shop, category_name=spec["category"])
        brand = Brand.objects.create(retailer=shop, brand_name=spec["brand"])

        Supplier.objects.create(
            retailer=shop, supplier_name=f"{spec['shop_name']} Supplier", mobile="9000000001",
            address="Wholesale Market", city="Pune", state="Maharashtra", pincode="411002",
        )
        Supplier.objects.create(
            retailer=shop, supplier_name="Out of State Distributor", mobile="9000000002",
            address="GIDC", city="Ahmedabad", state="Gujarat", pincode="380001",
        )

        local = Customer.objects.create(retailer=shop, customer_name="Ravi Kumar", mobile="9000000011")
        Customer.objects.create(
            retailer=shop, customer_name="Gujarat Traders (IGST)", mobile="9000000012",
            state="gujarat", gst_number="24BBBBB1111B1Z5",
        )
        contractor = None
        if features.price_levels:
            contractor = Customer.objects.create(
                retailer=shop, customer_name="Sharma Contractors", mobile="9000000013",
                price_level=Customer.PRICE_LEVEL_WHOLESALE,
            )

        products = [
            self._create_product(shop, features, category, brand, item)
            for item in spec["products"]
        ]

        if features.quotations and contractor is not None:
            self._create_quotation(shop, contractor, products[:2])

        return shop

    def _create_product(self, shop, features, category, brand, item):
        purchase, selling, mrp = item["price"]
        unit = self._unit(item["unit"])

        purchase_unit, factor = None, D("1")
        if features.unit_conversion and item.get("buy_in"):
            purchase_unit = self._unit(item["buy_in"][0])
            factor = D(item["buy_in"][1])

        extra = {}
        if features.prescription_details:
            extra.update(
                salt_composition=item.get("salt", ""),
                manufacturer=item.get("manufacturer", ""),
                schedule=item.get("schedule", Product.SCHEDULE_NONE),
            )
        if features.price_levels and item.get("wholesale"):
            extra["wholesale_price"] = D(item["wholesale"])
        if features.product_specification:
            extra["specification"] = item.get("spec", "")

        batch_tracked = features.batch_tracking and item.get("batches")

        product = Product.objects.create(
            retailer=shop, category=category, brand=brand, unit=unit,
            purchase_unit=purchase_unit, conversion_factor=factor,
            product_name=item["name"], hsn_code=item.get("hsn", ""),
            purchase_price=D(purchase), selling_price=D(selling),
            mrp=D(mrp) if mrp else None,
            gst=D(item["gst"]), minimum_stock=D(item.get("min", "0")),
            # Batch-tracked stock is added through its batches below.
            current_stock=D("0") if batch_tracked else D(item.get("stock", "0")),
            **extra,
        )

        if batch_tracked:
            today = timezone.localdate()
            locked = Product.objects.select_for_update().get(pk=product.pk)
            for number, days, quantity in item["batches"]:
                batch_stock.receive_into_batch(
                    locked, batch_number=number, expiry_date=today + timedelta(days=days),
                    quantity=D(quantity), purchase_price=D(purchase), mrp=D(mrp) if mrp else None,
                )
            product.refresh_from_db()

        return product

    def _create_quotation(self, shop, customer, products):
        today = timezone.localdate()
        features = get_features(shop)
        lines = []
        subtotal = gst = D("0")

        for product, quantity in zip(products, (D("180"), D("30"))):
            price = product.price_for(customer, features)
            taxable = quantity * price
            subtotal += taxable
            gst += (taxable * product.gst / 100).quantize(D("0.01"))
            lines.append((product, quantity, price))

        quotation = Quotation.objects.create(
            retailer=shop, customer=customer, quotation_date=today,
            valid_until=today + timedelta(days=15),
            remarks="Demo quotation. Delivery in 3 days.",
            subtotal=subtotal, discount=D("0"), gst=gst, grand_total=subtotal + gst,
        )
        for product, quantity, price in lines:
            QuotationItem.objects.create(
                quotation=quotation, product=product, unit=product.unit, quantity=quantity,
                selling_price=price, mrp=product.mrp, gst=product.gst, discount=D("0"),
            )
