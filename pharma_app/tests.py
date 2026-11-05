from datetime import date, timedelta
from decimal import Decimal

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Payment,
    Brand,
    Category,
    CustomUser,
    Customer,
    Product,
    ProductBatch,
    Purchase,
    PurchaseItem,
    Retailer,
    Sale,
    SaleItem,
    Supplier,
    Unit,
)
from .views import calculate_due_date


class BaseTestData(TestCase):
    """
    Shared fixtures:

        admin (superuser)
        retailer A  -> supplier "Alpha Traders", "Acme Pharma", product "Paracetamol"
        retailer B  -> supplier "Beta Distributors", product "Ibuprofen"
    """

    password = "test-pass-123"

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=cls.password,
            user_type="admin",
        )

        cls.retailer_a = cls._create_retailer("shopa", "Shop A")
        cls.retailer_b = cls._create_retailer("shopb", "Shop B")

        cls.unit = Unit.objects.create(name="Piece", short_name="pc")

        cls.product_a = cls._create_product(cls.retailer_a, "Paracetamol")
        cls.product_b = cls._create_product(cls.retailer_b, "Ibuprofen")

        cls.supplier_a1 = cls._create_supplier(cls.retailer_a, "Alpha Traders")
        cls.supplier_a2 = cls._create_supplier(cls.retailer_a, "Acme Pharma")
        cls.supplier_b1 = cls._create_supplier(cls.retailer_b, "Beta Distributors")

    @classmethod
    def _create_retailer(cls, username, shop_name):
        user = CustomUser.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=cls.password,
            user_type="retailer",
        )

        return Retailer.objects.create(
            user=user,
            shop_name=shop_name,
            owner_name=f"{shop_name} Owner",
            mobile="9876543210",
            email=f"{username}@example.com",
            address="1 Main Road",
            city="Pune",
            state="Maharashtra",
            pincode="411001",
        )

    @classmethod
    def _create_product(cls, retailer, name, stock=10):
        return Product.objects.create(
            retailer=retailer,
            category=Category.objects.create(retailer=retailer, category_name="Medicine"),
            brand=Brand.objects.create(retailer=retailer, brand_name="Generic"),
            unit=cls.unit,
            product_name=name,
            hsn_code="3004",
            purchase_price=Decimal("10.00"),
            selling_price=Decimal("12.00"),
            mrp=Decimal("15.00"),
            current_stock=stock,
            gst=Decimal("5.00"),
        )

    @classmethod
    def _create_supplier(cls, retailer, name, **extra):
        data = {
            "retailer": retailer,
            "supplier_name": name,
            "mobile": "9123456780",
            "address": "Market Yard",
            "city": "Pune",
            "state": "Maharashtra",
            "pincode": "411002",
        }
        data.update(extra)
        return Supplier.objects.create(**data)

    @classmethod
    def _create_purchase(cls, retailer, supplier, product, price, bill_date, quantity=Decimal("5")):
        purchase = Purchase.objects.create(
            retailer=retailer,
            supplier=supplier,
            bill_number=f"BILL-{supplier.id}-{bill_date.isoformat()}-{price}",
            bill_date=bill_date,
            invoice_date=bill_date,
        )

        PurchaseItem.objects.create(
            purchase=purchase,
            product=product,
            unit=cls.unit,
            quantity=quantity,
            purchase_price=Decimal(price),
            amount=Decimal(price) * quantity,
        )

        return purchase

    def login_admin(self):
        self.client.force_login(self.admin)

    def login_retailer_a(self):
        self.client.force_login(self.retailer_a.user)

    def login_retailer_b(self):
        self.client.force_login(self.retailer_b.user)


# =====================================================================
# DUE DATE
# =====================================================================

class CalculateDueDateTests(TestCase):

    def test_net_terms_add_days(self):
        bill_date = date(2026, 10, 24)

        self.assertEqual(calculate_due_date(bill_date, "net15"), date(2026, 11, 8))
        self.assertEqual(calculate_due_date(bill_date, "net30"), date(2026, 11, 23))
        self.assertEqual(calculate_due_date(bill_date, "net45"), date(2026, 12, 8))
        self.assertEqual(calculate_due_date(bill_date, "net60"), date(2026, 12, 23))

    def test_immediate_and_cod_are_due_on_bill_date(self):
        bill_date = date(2026, 10, 24)

        self.assertEqual(calculate_due_date(bill_date, "immediate"), bill_date)
        self.assertEqual(calculate_due_date(bill_date, "cod"), bill_date)

    def test_crosses_year_boundary(self):
        self.assertEqual(
            calculate_due_date(date(2026, 12, 20), "net15"),
            date(2027, 1, 4),
        )

    def test_empty_or_unknown_terms_return_none(self):
        bill_date = date(2026, 10, 24)

        self.assertIsNone(calculate_due_date(bill_date, ""))
        self.assertIsNone(calculate_due_date(bill_date, None))
        self.assertIsNone(calculate_due_date(bill_date, "net90"))

    def test_terms_are_case_insensitive(self):
        self.assertEqual(
            calculate_due_date(date(2026, 1, 1), " NET30 "),
            date(2026, 1, 31),
        )


# =====================================================================
# SUPPLIER TABLE
# =====================================================================

class SupplierListTests(BaseTestData):

    url = reverse("supplier_list")

    def test_requires_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/user-login/", response.url)

    def test_admin_sees_all_suppliers_with_shop_names(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["suppliers"].paginator.count, 3)
        self.assertContains(response, "<th>Retailer Shop</th>")
        self.assertContains(response, "Shop A")
        self.assertContains(response, "Shop B")
        self.assertContains(response, "Beta Distributors")

    def test_retailer_sees_only_own_suppliers(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        names = {supplier.supplier_name for supplier in response.context["suppliers"]}
        self.assertEqual(names, {"Alpha Traders", "Acme Pharma"})
        self.assertNotContains(response, "Beta Distributors")
        self.assertNotContains(response, "<th>Retailer Shop</th>")

    def test_search_filters_by_supplier_name(self):
        self.login_admin()

        response = self.client.get(self.url, {"search": "alp"})

        names = [supplier.supplier_name for supplier in response.context["suppliers"]]
        self.assertEqual(names, ["Alpha Traders"])

    def test_admin_can_filter_by_retailer(self):
        self.login_admin()

        response = self.client.get(self.url, {"retailer": self.retailer_b.id})

        names = [supplier.supplier_name for supplier in response.context["suppliers"]]
        self.assertEqual(names, ["Beta Distributors"])

    def test_retailer_cannot_use_retailer_filter_to_see_others(self):
        self.login_retailer_a()

        response = self.client.get(self.url, {"retailer": self.retailer_b.id})

        names = {supplier.supplier_name for supplier in response.context["suppliers"]}
        self.assertEqual(names, {"Alpha Traders", "Acme Pharma"})

    def test_status_filter(self):
        self.supplier_a2.is_active = False
        self.supplier_a2.save()
        self.login_retailer_a()

        inactive = self.client.get(self.url, {"status": "inactive"})
        active = self.client.get(self.url, {"status": "active"})

        self.assertEqual([s.supplier_name for s in inactive.context["suppliers"]], ["Acme Pharma"])
        self.assertEqual([s.supplier_name for s in active.context["suppliers"]], ["Alpha Traders"])

    def test_purchase_count_is_annotated(self):
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "9.00", date(2026, 1, 1))
        self.login_retailer_a()

        response = self.client.get(self.url)

        counts = {s.supplier_name: s.purchase_count for s in response.context["suppliers"]}
        self.assertEqual(counts, {"Alpha Traders": 1, "Acme Pharma": 0})

    def test_user_without_retailer_profile_is_redirected(self):
        user = CustomUser.objects.create_user(username="orphan", password=self.password)
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)

    def test_add_supplier_link_is_shown(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, reverse("add_new_supplier"))


class SupplierUpdateTests(BaseTestData):

    def valid_payload(self, **overrides):
        payload = {
            "supplier_name": "Alpha Traders Pvt Ltd",
            "contact_person": "Ravi",
            "mobile": "98765-43210",
            "email": "alpha@example.com",
            "address": "New Market",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400001",
            "opening_balance": "100.50",
            "credit_limit": "5000",
            "credit_days": "30",
            "is_active": "on",
        }
        payload.update(overrides)
        return payload

    def url(self, supplier):
        return reverse("supplier_update", args=[supplier.id])

    def test_retailer_updates_own_supplier(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_a1), self.valid_payload())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        self.supplier_a1.refresh_from_db()
        self.assertEqual(self.supplier_a1.supplier_name, "Alpha Traders Pvt Ltd")
        self.assertEqual(self.supplier_a1.mobile, "9876543210")
        self.assertEqual(self.supplier_a1.city, "Mumbai")
        self.assertEqual(self.supplier_a1.credit_limit, Decimal("5000"))
        self.assertEqual(self.supplier_a1.credit_days, 30)
        self.assertTrue(self.supplier_a1.is_active)

    def test_unchecked_is_active_deactivates_supplier(self):
        self.login_retailer_a()
        payload = self.valid_payload()
        payload.pop("is_active")

        self.client.post(self.url(self.supplier_a1), payload)

        self.supplier_a1.refresh_from_db()
        self.assertFalse(self.supplier_a1.is_active)

    def test_retailer_cannot_update_other_retailers_supplier(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_b1), self.valid_payload())

        self.assertEqual(response.status_code, 404)
        self.supplier_b1.refresh_from_db()
        self.assertEqual(self.supplier_b1.supplier_name, "Beta Distributors")

    def test_admin_can_update_any_supplier(self):
        self.login_admin()

        response = self.client.post(
            self.url(self.supplier_b1),
            self.valid_payload(supplier_name="Beta Distributors Updated"),
        )

        self.assertEqual(response.status_code, 200)
        self.supplier_b1.refresh_from_db()
        self.assertEqual(self.supplier_b1.supplier_name, "Beta Distributors Updated")
        # Retailer ownership never changes on edit.
        self.assertEqual(self.supplier_b1.retailer, self.retailer_b)

    def test_missing_required_field_returns_400(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_a1), self.valid_payload(city=""))

        self.assertEqual(response.status_code, 400)
        self.assertIn("City", response.json()["message"])

    def test_invalid_mobile_returns_400(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_a1), self.valid_payload(mobile="12345"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("mobile", response.json()["message"].lower())

    def test_invalid_email_returns_400(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_a1), self.valid_payload(email="not-an-email"))

        self.assertEqual(response.status_code, 400)

    def test_negative_credit_limit_returns_400(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_a1), self.valid_payload(credit_limit="-1"))

        self.assertEqual(response.status_code, 400)

    def test_duplicate_name_for_same_retailer_returns_409(self):
        self.login_retailer_a()

        response = self.client.post(
            self.url(self.supplier_a1),
            self.valid_payload(supplier_name="acme pharma"),
        )

        self.assertEqual(response.status_code, 409)

    def test_same_name_as_other_retailers_supplier_is_allowed(self):
        self.login_retailer_a()

        response = self.client.post(
            self.url(self.supplier_a1),
            self.valid_payload(supplier_name="Beta Distributors"),
        )

        self.assertEqual(response.status_code, 200)

    def test_get_not_allowed(self):
        self.login_retailer_a()

        response = self.client.get(self.url(self.supplier_a1))

        self.assertEqual(response.status_code, 405)


class SupplierDeleteTests(BaseTestData):

    def url(self, supplier):
        return reverse("supplier_delete", args=[supplier.id])

    def test_retailer_deletes_own_supplier_without_purchases(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_a2))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Supplier.objects.filter(pk=self.supplier_a2.pk).exists())

    def test_supplier_with_purchases_cannot_be_deleted(self):
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "9.00", date(2026, 1, 1))
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_a1))

        self.assertEqual(response.status_code, 409)
        self.assertIn("inactive", response.json()["message"])
        self.assertTrue(Supplier.objects.filter(pk=self.supplier_a1.pk).exists())
        self.assertEqual(Purchase.objects.count(), 1)

    def test_retailer_cannot_delete_other_retailers_supplier(self):
        self.login_retailer_a()

        response = self.client.post(self.url(self.supplier_b1))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Supplier.objects.filter(pk=self.supplier_b1.pk).exists())

    def test_admin_can_delete_any_supplier(self):
        self.login_admin()

        response = self.client.post(self.url(self.supplier_b1))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Supplier.objects.filter(pk=self.supplier_b1.pk).exists())

    def test_get_not_allowed(self):
        self.login_admin()

        response = self.client.get(self.url(self.supplier_b1))

        self.assertEqual(response.status_code, 405)


class AddSupplierRedirectTests(BaseTestData):

    def test_normal_form_submit_redirects_to_supplier_table(self):
        self.login_retailer_a()

        response = self.client.post(
            reverse("add_new_supplier"),
            {
                "supplier_name": "Gamma Supplies",
                "mobile": "9000000001",
                "address": "Somewhere",
                "city": "Pune",
                "state": "Maharashtra",
                "pincode": "411003",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("supplier_list"), fetch_redirect_response=False)
        self.assertTrue(
            Supplier.objects.filter(retailer=self.retailer_a, supplier_name="Gamma Supplies").exists()
        )


# =====================================================================
# PURCHASE HISTORY
# =====================================================================

class PurchaseHistoryTests(BaseTestData):

    def url(self, product):
        return reverse("purchase_history", args=[product.id])

    def setUp(self):
        # Oldest -> newest
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "10.00", date(2026, 1, 10))
        self._create_purchase(self.retailer_a, self.supplier_a2, self.product_a, "8.50", date(2026, 2, 10))
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "12.00", date(2026, 3, 10))
        self._create_purchase(self.retailer_a, self.supplier_a2, self.product_a, "9.00", date(2026, 4, 10))

    def test_returns_low_high_last_prices_and_suppliers(self):
        self.login_retailer_a()

        data = self.client.get(self.url(self.product_a)).json()

        self.assertTrue(data["success"])
        summary = data["summary"]
        self.assertEqual(summary["purchases"], 4)
        self.assertEqual(Decimal(summary["min_price"]), Decimal("8.50"))
        self.assertEqual(summary["min_supplier"], "Acme Pharma")
        self.assertEqual(Decimal(summary["max_price"]), Decimal("12.00"))
        self.assertEqual(summary["max_supplier"], "Alpha Traders")
        self.assertEqual(Decimal(summary["last_price"]), Decimal("9.00"))
        self.assertEqual(summary["last_date"], "2026-04-10")
        # Same qty per purchase -> weighted avg = (10 + 8.5 + 12 + 9) / 4
        self.assertEqual(Decimal(summary["avg_price"]), Decimal("9.88"))

    def test_suppliers_are_sorted_cheapest_first_with_ranges(self):
        self.login_retailer_a()

        suppliers = self.client.get(self.url(self.product_a)).json()["suppliers"]

        self.assertEqual([s["supplier"] for s in suppliers], ["Acme Pharma", "Alpha Traders"])

        acme, alpha = suppliers
        self.assertEqual(acme["purchases"], 2)
        self.assertEqual(Decimal(acme["min_price"]), Decimal("8.50"))
        self.assertEqual(Decimal(acme["max_price"]), Decimal("9.00"))
        self.assertEqual(Decimal(acme["last_price"]), Decimal("9.00"))
        self.assertEqual(Decimal(alpha["min_price"]), Decimal("10.00"))
        self.assertEqual(Decimal(alpha["max_price"]), Decimal("12.00"))
        self.assertEqual(Decimal(alpha["last_price"]), Decimal("12.00"))

    def test_recent_purchases_are_newest_first(self):
        self.login_retailer_a()

        recent = self.client.get(self.url(self.product_a)).json()["recent"]

        self.assertEqual([row["date"] for row in recent], ["2026-04-10", "2026-03-10", "2026-02-10", "2026-01-10"])

    def test_product_without_purchases_has_no_summary(self):
        self.login_retailer_b()

        data = self.client.get(self.url(self.product_b)).json()

        self.assertTrue(data["success"])
        self.assertIsNone(data["summary"])
        self.assertEqual(data["suppliers"], [])

    def test_retailer_cannot_see_other_retailers_product_history(self):
        self.login_retailer_b()

        response = self.client.get(self.url(self.product_a))

        self.assertEqual(response.status_code, 404)

    def test_admin_can_see_any_product_history(self):
        self.login_admin()

        response = self.client.get(self.url(self.product_a))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["purchases"], 4)

    def test_requires_login(self):
        response = self.client.get(self.url(self.product_a))

        self.assertEqual(response.status_code, 302)


# =====================================================================
# ADD PURCHASE PAGE
# =====================================================================

class AddOrderPageTests(BaseTestData):

    url = reverse("add_new_order")

    def test_bill_date_defaults_to_today_and_due_date_is_readonly(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        today = timezone.localdate().isoformat()
        self.assertContains(response, f'name="bill_date" id="billDate" value="{today}"')
        self.assertContains(response, 'id="dueDate" readonly')
        self.assertContains(response, 'id="paymentTermDays"')

    def test_product_options_carry_product_id_for_history_lookup(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, f'data-id="{self.product_a.id}"')
        self.assertContains(response, reverse("purchase_history", args=[0]))
        self.assertContains(response, 'id="historyModal"')

    def test_item_totals_row_has_taxable_tax_and_amount(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        for element_id in ("totalTaxable", "totalTax", "totalAmount"):
            self.assertContains(response, f'id="{element_id}"')

    def test_retailer_add_product_modal_hides_retailer_select(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="productRetailerSelect"')
        self.assertContains(response, f'<input type="hidden" name="retailer" value="{self.retailer_a.id}">')

    def test_admin_add_product_modal_shows_retailer_select(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertContains(response, 'id="productRetailerSelect"')

    def test_payment_section_follows_totals_section(self):
        self.login_retailer_a()

        content = self.client.get(self.url).content.decode()

        self.assertLess(content.index('class="summary-box"'), content.index('class="payment-card"'))

    def test_retailer_without_profile_is_redirected(self):
        user = CustomUser.objects.create_user(username="orphan", password=self.password)
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)


class AddOrderSubmitTests(BaseTestData):

    url = reverse("add_new_order")

    def payload(self, **overrides):
        data = {
            "supplier": self.supplier_a1.id,
            "bill_number": "BILL-100",
            "bill_date": "2026-10-24",
            "payment_terms": "net30",
            # The client cannot dictate the due date.
            "due_date": "2030-01-01",
            "item_name_1": "Paracetamol",
            "item_unit_1": self.unit.id,
            "item_qty_1": "4",
            "item_free_qty_1": "1",
            "item_price_1": "9.50",
            "item_tax_1": "gst5",
            "item_mrp_1": "15",
            "paid_amount": "0",
        }
        data.update(overrides)
        return data

    def test_creates_purchase_and_redirects_to_purchase_table(self):
        self.login_retailer_a()

        response = self.client.post(self.url, self.payload())

        self.assertRedirects(response, reverse("purchase_product_list"), fetch_redirect_response=False)

        purchase = Purchase.objects.get(bill_number="BILL-100")
        self.assertEqual(purchase.retailer, self.retailer_a)
        self.assertEqual(purchase.subtotal, Decimal("38.00"))
        self.assertEqual(purchase.gst, Decimal("1.90"))
        self.assertEqual(purchase.grand_total, Decimal("39.90"))

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, 15)  # 10 + 4 + 1 free

    def test_due_date_is_calculated_from_payment_terms(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload())

        purchase = Purchase.objects.get(bill_number="BILL-100")
        self.assertEqual(purchase.due_date, date(2026, 11, 23))

    def test_immediate_terms_due_on_bill_date(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload(payment_terms="immediate"))

        purchase = Purchase.objects.get(bill_number="BILL-100")
        self.assertEqual(purchase.due_date, date(2026, 10, 24))

    def test_no_terms_means_no_due_date(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload(payment_terms=""))

        self.assertIsNone(Purchase.objects.get(bill_number="BILL-100").due_date)

    def test_invalid_bill_date_is_rejected(self):
        self.login_retailer_a()

        response = self.client.post(self.url, self.payload(bill_date="24/10/2026"))

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(Purchase.objects.exists())

    def test_retailer_cannot_buy_other_retailers_product(self):
        self.login_retailer_a()

        response = self.client.post(self.url, self.payload(item_name_1="Ibuprofen"))

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(Purchase.objects.exists())


class AddProductAjaxResponseTests(BaseTestData):

    def test_ajax_response_includes_option_data(self):
        self.login_retailer_a()
        category = Category.objects.filter(retailer=self.retailer_a).first()
        brand = Brand.objects.filter(retailer=self.retailer_a).first()

        response = self.client.post(
            reverse("add_product"),
            {
                "retailer": self.retailer_a.id,
                "category": category.id,
                "brand": brand.id,
                "unit": self.unit.id,
                "product_name": "Cetirizine",
                "hsn_code": "3004",
                "purchase_price": "4.00",
                "selling_price": "5.00",
                "mrp": "6.00",
                "gst": "12",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["retailer_id"], self.retailer_a.id)
        self.assertEqual(data["unit_id"], self.unit.id)
        self.assertEqual(Decimal(data["purchase_price"]), Decimal("4.00"))
        self.assertEqual(Decimal(data["gst"]), Decimal("12"))


class ReorderListTests(BaseTestData):

    def test_reorder_list_has_standard_back_button_to_product_list(self):
        self.login_retailer_a()

        response = self.client.get(reverse("low_stock_alert"))

        # Same round back arrow as the other pages, next to the title.
        self.assertContains(response, f'href="{reverse("product_list")}" class="page-back-btn"')
        self.assertContains(response, "<h1>Reorder List</h1>")
        self.assertNotContains(response, 'class="btn-back"')

    def test_reorder_list_has_no_dead_product_modal_script(self):
        # The old modal script crashed on this page (no #productModal).
        self.login_retailer_a()

        response = self.client.get(reverse("low_stock_alert"))

        self.assertNotContains(response, "getElementById('productModal')")
        self.assertContains(response, "function toggleTheme()")

    def test_product_list_css_does_not_override_theme_colours(self):
        # A :root block here loaded after base.css and blocked dark mode.
        css = finders.find("css/product_list.css")
        with open(css, encoding="utf-8") as handle:
            content = handle.read()

        self.assertNotRegex(content, r"(?m)^\s*:root\s*\{")


# =====================================================================
# SALES TABLE
# =====================================================================

class SalesTestData(BaseTestData):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.customer_a = Customer.objects.create(
            retailer=cls.retailer_a, customer_name="Rahul Sharma", mobile="9000000011"
        )
        cls.customer_a2 = Customer.objects.create(
            retailer=cls.retailer_a, customer_name="Priya Patel", mobile="9000000012"
        )
        cls.customer_b = Customer.objects.create(
            retailer=cls.retailer_b, customer_name="Amit Kumar", mobile="9000000013"
        )

        cls.sale_a1 = cls._create_sale(cls.retailer_a, cls.customer_a, date(2026, 10, 1), "120.00", "120.00")
        cls.sale_a2 = cls._create_sale(cls.retailer_a, cls.customer_a2, date(2026, 10, 15), "80.00", "0.00")
        cls.sale_b1 = cls._create_sale(cls.retailer_b, cls.customer_b, date(2026, 10, 20), "50.00", "20.00")

    @classmethod
    def _create_sale(cls, retailer, customer, invoice_date, total, paid):
        sale = Sale.objects.create(
            retailer=retailer,
            customer=customer,
            invoice_date=invoice_date,
            subtotal=Decimal(total),
            grand_total=Decimal(total),
            paid_amount=Decimal(paid),
            payment_type="Cash",
        )

        product = retailer.products.first()
        SaleItem.objects.create(
            sale=sale,
            product=product,
            unit=cls.unit,
            quantity=Decimal("1"),
            selling_price=Decimal(total),
        )

        return sale


class SalesListTests(SalesTestData):

    url = reverse("sales_list")

    def invoice_numbers(self, response):
        return {sale.invoice_number for sale in response.context["sales"]}

    def test_requires_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)

    def test_admin_sees_all_sales_with_shop_names(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertEqual(response.context["sales"].paginator.count, 3)
        self.assertContains(response, "<th>Retailer Shop</th>")
        self.assertContains(response, "Shop B")
        self.assertEqual(response.context["total_amount"], Decimal("250.00"))
        self.assertEqual(response.context["total_due"], Decimal("110.00"))

    def test_retailer_sees_only_own_sales(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertEqual(response.context["sales"].paginator.count, 2)
        self.assertNotContains(response, "Amit Kumar")
        self.assertNotContains(response, "<th>Retailer Shop</th>")

    def test_admin_filters_by_retailer(self):
        self.login_admin()

        response = self.client.get(self.url, {"retailer": self.retailer_b.id})

        self.assertEqual(self.invoice_numbers(response), {self.sale_b1.invoice_number})

    def test_retailer_cannot_use_retailer_filter_to_see_others(self):
        self.login_retailer_a()

        response = self.client.get(self.url, {"retailer": self.retailer_b.id})

        self.assertEqual(response.context["sales"].paginator.count, 2)

    def test_filter_by_customer_name(self):
        self.login_retailer_a()

        response = self.client.get(self.url, {"customer": "priya"})

        self.assertEqual([s.customer.customer_name for s in response.context["sales"]], ["Priya Patel"])

    def test_filter_by_customer_mobile(self):
        self.login_admin()

        response = self.client.get(self.url, {"customer": "0013"})

        self.assertEqual([s.customer.customer_name for s in response.context["sales"]], ["Amit Kumar"])

    def test_filter_by_date_range(self):
        self.login_admin()

        response = self.client.get(self.url, {"from_date": "2026-10-10", "to_date": "2026-10-16"})

        self.assertEqual(self.invoice_numbers(response), {self.sale_a2.invoice_number})

    def test_reversed_date_range_is_swapped(self):
        self.login_admin()

        response = self.client.get(self.url, {"from_date": "2026-10-16", "to_date": "2026-10-10"})

        self.assertEqual(self.invoice_numbers(response), {self.sale_a2.invoice_number})
        self.assertEqual(response.context["from_date"], "2026-10-10")

    def test_invalid_dates_are_ignored(self):
        self.login_admin()

        response = self.client.get(self.url, {"from_date": "not-a-date"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sales"].paginator.count, 3)

    def test_filter_by_status(self):
        self.login_retailer_a()

        response = self.client.get(self.url, {"status": "Unpaid"})

        self.assertEqual(self.invoice_numbers(response), {self.sale_a2.invoice_number})

    def test_add_sale_button_links_to_sale_create(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, f'href="{reverse("sale_create")}" class="action-btn primary"')

    def test_rows_link_to_view_and_invoice_download(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, reverse("sale_detail", args=[self.sale_a1.id]))
        self.assertContains(response, reverse("sale_invoice", args=[self.sale_a1.id]) + "?download=1")


class SaleDetailAndInvoiceTests(SalesTestData):

    def test_retailer_views_own_sale(self):
        self.login_retailer_a()

        response = self.client.get(reverse("sale_detail", args=[self.sale_a1.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sale_a1.invoice_number)
        self.assertContains(response, "Rahul Sharma")
        self.assertContains(response, "Paracetamol")

    def test_retailer_cannot_view_other_retailers_sale(self):
        self.login_retailer_a()

        self.assertEqual(self.client.get(reverse("sale_detail", args=[self.sale_b1.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("sale_invoice", args=[self.sale_b1.id])).status_code, 404)

    def test_admin_views_any_sale_and_invoice(self):
        self.login_admin()

        self.assertEqual(self.client.get(reverse("sale_detail", args=[self.sale_b1.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("sale_invoice", args=[self.sale_b1.id])).status_code, 200)

    def test_invoice_contains_shop_customer_and_totals(self):
        self.login_retailer_a()

        response = self.client.get(reverse("sale_invoice", args=[self.sale_a1.id]))

        self.assertContains(response, "TAX INVOICE")
        self.assertContains(response, "Shop A")
        self.assertContains(response, "Rahul Sharma")
        self.assertContains(response, "₹120.00")
        self.assertFalse(response.context["auto_download"])

    def test_download_flag_triggers_pdf_download(self):
        self.login_retailer_a()

        response = self.client.get(reverse("sale_invoice", args=[self.sale_a1.id]), {"download": "1"})

        self.assertTrue(response.context["auto_download"])
        self.assertContains(response, "window.addEventListener('load', downloadPdf)")

    def test_missing_sale_returns_404(self):
        self.login_admin()

        self.assertEqual(self.client.get(reverse("sale_detail", args=[99999])).status_code, 404)


class SaleCreateRedirectTests(BaseTestData):

    def setUp(self):
        self.customer = Customer.objects.create(
            retailer=self.retailer_a, customer_name="Walk-in", mobile="9000000099"
        )

    def payload(self, action):
        return {
            "customer": self.customer.id,
            "items[1][product]": self.product_a.id,
            "items[1][unit]": self.unit.id,
            "items[1][quantity]": "2",
            "items[1][discount]": "0",
            "payment_type": "Cash",
            "paid_amount": "24.00",
            "action": action,
        }

    def test_save_redirects_to_sales_table(self):
        self.login_retailer_a()

        response = self.client.post(reverse("sale_create"), self.payload("save"))

        self.assertRedirects(response, reverse("sales_list"), fetch_redirect_response=False)
        self.assertEqual(Sale.objects.count(), 1)

    def test_save_and_print_redirects_to_invoice(self):
        self.login_retailer_a()

        response = self.client.post(reverse("sale_create"), self.payload("save_print"))

        sale = Sale.objects.get()
        self.assertRedirects(
            response,
            reverse("sale_invoice", args=[sale.id]),
            fetch_redirect_response=False,
        )


class NavigationTests(BaseTestData):

    def test_sidebar_links_to_supplier_and_sales_tables(self):
        self.login_retailer_a()

        response = self.client.get(reverse("supplier_list"))

        self.assertContains(response, f'href="{reverse("supplier_list")}"')
        self.assertContains(response, f'href="{reverse("sales_list")}"')


# =====================================================================
# LIST PAGES: "ADD" BUTTON PLACEMENT
# =====================================================================

class ListHeaderButtonTests(BaseTestData):
    """
    Tablet / laptop / desktop: the "Add" button sits in the list's section
    header, in front of the title. Phones: it stays in the quick-actions bar.
    """

    def assert_button_in_header_and_mobile_bar(self, url, target):
        self.login_retailer_a()

        content = self.client.get(url).content.decode()
        href = f'href="{target}"'

        # Phone-only bar above the list keeps the button where it was.
        self.assertIn('class="quick-actions only-mobile"', content)
        bar = content[content.index('class="quick-actions only-mobile"'):content.index('class="purchases-section"')]
        self.assertIn(href, bar)

        # Larger screens: button inside the section header.
        header = content[content.index('class="section-header with-count"'):content.index('class="filters-bar"')]
        self.assertIn(href, header)
        self.assertIn('class="action-btn primary hide-mobile"', header)

    def test_supplier_list(self):
        self.assert_button_in_header_and_mobile_bar(reverse("supplier_list"), reverse("add_new_supplier"))

    def test_purchase_list(self):
        self.assert_button_in_header_and_mobile_bar(reverse("purchase_product_list"), reverse("add_new_order"))

    def test_sales_list(self):
        self.assert_button_in_header_and_mobile_bar(reverse("sales_list"), reverse("sale_create"))


# =====================================================================
# ADD PRODUCT: RETAILER IS NOT CHOSEN BY A RETAILER USER
# =====================================================================

class AddProductRetailerTests(BaseTestData):

    url = reverse("add_product")

    def payload(self, **extra):
        data = {
            "category": Category.objects.filter(retailer=self.retailer_a).first().id,
            "brand": Brand.objects.filter(retailer=self.retailer_a).first().id,
            "unit": self.unit.id,
            "product_name": "Cetirizine",
            "hsn_code": "3004",
            "purchase_price": "4.00",
            "selling_price": "5.00",
            "mrp": "6.00",
            "gst": "12",
            "current_stock": "5",
            "minimum_stock": "1",
        }
        data.update(extra)
        return data

    def post_ajax(self, data):
        return self.client.post(self.url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_retailer_form_has_no_retailer_dropdown(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertNotContains(response, '<select id="retailer"')
        self.assertContains(
            response,
            f'<input type="hidden" id="retailer" name="retailer" value="{self.retailer_a.id}">',
        )
        self.assertContains(response, "add a product to Shop A")

    def test_admin_form_shows_retailer_dropdown(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertContains(response, '<select id="retailer" name="retailer"')
        self.assertContains(response, "Shop B")

    def test_retailer_saves_product_without_choosing_retailer(self):
        self.login_retailer_a()

        response = self.post_ajax(self.payload())

        self.assertEqual(response.status_code, 201)
        product = Product.objects.get(product_name="Cetirizine")
        self.assertEqual(product.retailer, self.retailer_a)

    def test_retailer_cannot_add_product_to_another_shop(self):
        self.login_retailer_a()

        response = self.post_ajax(self.payload(retailer=self.retailer_b.id))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Product.objects.get(product_name="Cetirizine").retailer, self.retailer_a)

    def test_admin_must_choose_retailer(self):
        self.login_admin()

        response = self.post_ajax(self.payload())

        self.assertEqual(response.status_code, 400)
        self.assertIn("Retailer", response.json()["missing_fields"])
        self.assertFalse(Product.objects.filter(product_name="Cetirizine").exists())


# =====================================================================
# NEW PURCHASE ORDER: LAYOUT, TOTALS, PRICE INSIGHT
# =====================================================================

class AddOrderLayoutTests(BaseTestData):

    url = reverse("add_new_order")

    def test_page_title_has_back_button_to_purchases(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, f'href="{reverse("purchase_product_list")}" class="page-back-btn"')
        self.assertContains(response, "<h1>New Purchase Order</h1>")

    def test_retailer_supplier_field_is_not_a_full_width_row(self):
        self.login_retailer_a()

        content = self.client.get(self.url).content.decode()

        self.assertIn('class="form-grid po-grid"', content)
        self.assertIn('class="form-group span-2"', content)
        self.assertNotIn("full-width", content)

    def test_admin_supplier_field_uses_single_column(self):
        self.login_admin()

        content = self.client.get(self.url).content.decode()

        self.assertIn('id="retailerSelect"', content)
        self.assertNotIn('class="form-group span-2"', content)

    def test_item_totals_are_a_labelled_footer_with_add_row_below(self):
        self.login_retailer_a()

        content = self.client.get(self.url).content.decode()

        self.assertIn("<tfoot>", content)
        for element_id in ("totalItems", "totalQty", "totalFreeQty", "totalTaxable", "totalTax", "totalAmount", "itemsCountChip"):
            self.assertIn(f'id="{element_id}"', content)
        self.assertGreater(content.index('id="addRowBtn"'), content.index("</tfoot>"))

    def test_unused_bill_tax_dropdown_is_removed(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertNotContains(response, 'id="taxType"')
        self.assertContains(response, 'id="summaryPaymentStatus" data-status="Unpaid"')

    def test_price_insight_panel_is_wired_up(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, "insightRow.className = 'insight-row'")
        self.assertContains(response, 'data-action="full-history"')
        self.assertContains(response, "Cheapest suppliers")
        self.assertNotContains(response, "price-history-hint")


class PurchaseHistoryInsightDataTests(BaseTestData):
    """Data the price insight panel shows for a product."""

    def test_lowest_highest_last_and_cheapest_supplier_first(self):
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "12.00", date(2026, 9, 1))
        self._create_purchase(self.retailer_a, self.supplier_a2, self.product_a, "9.00", date(2026, 9, 15))
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "11.00", date(2026, 10, 1))
        self.login_retailer_a()

        data = self.client.get(reverse("purchase_history", args=[self.product_a.id])).json()

        summary = data["summary"]
        self.assertEqual(summary["purchases"], 3)
        self.assertEqual(Decimal(summary["min_price"]), Decimal("9.00"))
        self.assertEqual(summary["min_supplier"], "Acme Pharma")
        self.assertEqual(Decimal(summary["max_price"]), Decimal("12.00"))
        self.assertEqual(Decimal(summary["last_price"]), Decimal("11.00"))
        self.assertEqual(summary["last_supplier"], "Alpha Traders")
        self.assertEqual([row["supplier"] for row in data["suppliers"]], ["Acme Pharma", "Alpha Traders"])

    def test_first_purchase_has_no_summary(self):
        self.login_retailer_a()

        data = self.client.get(reverse("purchase_history", args=[self.product_a.id])).json()

        self.assertTrue(data["success"])
        self.assertIsNone(data["summary"])
        self.assertEqual(data["suppliers"], [])


# =====================================================================
# NEW SALE INVOICE
# =====================================================================

class SaleCreatePageTests(BaseTestData):

    url = reverse("sale_create")

    def setUp(self):
        self.customer_a = Customer.objects.create(
            retailer=self.retailer_a, customer_name="Walk-in A", mobile="9000000101"
        )
        self.customer_b = Customer.objects.create(
            retailer=self.retailer_b, customer_name="Walk-in B", mobile="9000000102"
        )

    def payload(self, customer, product, **extra):
        data = {
            "customer": customer.id,
            "items[1][product]": product.id,
            "items[1][unit]": self.unit.id,
            "items[1][quantity]": "2",
            "items[1][discount]": "0",
            "payment_type": "Cash",
            "paid_amount": "24.00",
            "action": "save",
        }
        data.update(extra)
        return data

    def test_admin_sees_retailer_dropdown_and_every_shops_products(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertTrue(response.context["is_admin"])
        self.assertContains(response, 'id="retailerSelect"')
        self.assertContains(response, "Paracetamol")
        self.assertContains(response, "Ibuprofen")

    def test_retailer_page_uses_own_shop_without_dropdown(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertFalse(response.context["is_admin"])
        self.assertNotContains(response, 'id="retailerSelect"')
        self.assertContains(response, f'<input type="hidden" name="retailer" value="{self.retailer_a.id}">')
        self.assertNotContains(response, "Ibuprofen")

    def test_page_has_progress_steps_cash_only_and_pay_full(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, 'id="saleSteps"')
        self.assertContains(response, 'class="cash-only-note"')
        self.assertNotContains(response, 'name="payment_type"')
        self.assertContains(response, 'id="btnPayFull"')
        self.assertContains(response, 'id="creditMeter"')
        self.assertContains(response, 'id="summaryItemsLine"')

    def test_page_links_its_stylesheet(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, "css/sale_create.css")

    def test_sale_create_css_styles_the_card_layout(self):
        css = finders.find("css/sale_create.css")
        with open(css, encoding="utf-8") as handle:
            content = handle.read()

        for selector in (".sale-layout", ".sale-card", ".customer-strip", ".sale-modal-overlay", ".sale-steps", ".cash-only-note"):
            self.assertIn(selector, content)

    def test_admin_sale_is_saved_for_selected_retailer(self):
        self.login_admin()

        self.client.post(
            self.url,
            self.payload(self.customer_b, self.product_b, retailer=self.retailer_b.id),
        )

        sale = Sale.objects.get()
        self.assertEqual(sale.retailer, self.retailer_b)
        self.assertEqual(sale.customer, self.customer_b)

    def test_admin_sale_without_retailer_is_rejected(self):
        self.login_admin()

        self.client.post(self.url, self.payload(self.customer_b, self.product_b))

        self.assertFalse(Sale.objects.exists())

    def test_retailer_cannot_sell_for_another_shop(self):
        self.login_retailer_a()

        self.client.post(
            self.url,
            self.payload(self.customer_b, self.product_b, retailer=self.retailer_b.id),
        )

        self.assertFalse(Sale.objects.exists())


class CreateCustomerAjaxTests(BaseTestData):

    url = reverse("create_customer_ajax")

    def payload(self, **extra):
        data = {
            "customer_name": "New Buyer",
            "mobile": "9000000555",
            "credit_limit": "0",
            "opening_balance": "0",
        }
        data.update(extra)
        return data

    def test_admin_creates_customer_for_selected_retailer(self):
        self.login_admin()

        response = self.client.post(self.url, self.payload(retailer=self.retailer_b.id))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["customer"]["retailer_id"], self.retailer_b.id)
        self.assertEqual(Customer.objects.get(mobile="9000000555").retailer, self.retailer_b)

    def test_retailer_always_creates_customer_for_own_shop(self):
        self.login_retailer_a()

        response = self.client.post(self.url, self.payload(retailer=self.retailer_b.id))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Customer.objects.get(mobile="9000000555").retailer, self.retailer_a)


# =====================================================================
# QA REGRESSION TESTS (bugs found in the QA pass of 2026-10-25)
# =====================================================================

class QASecurityRegressionTests(BaseTestData):

    def product_update_payload(self, product, **extra):
        data = {
            "product_id": product.id, "purchase_price": "1", "selling_price": "1", "mrp": "1",
            "gst": "0", "current_stock": "999", "minimum_stock": "0", "is_active": "true",
        }
        data.update(extra)
        return data

    def test_anonymous_cannot_update_product(self):
        response = self.client.post(reverse("update_product"), self.product_update_payload(self.product_b))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("user_login"), response.url)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, 10)

    def test_anonymous_cannot_delete_product(self):
        response = self.client.post(reverse("delete_product", args=[self.product_b.id]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(pk=self.product_b.id).exists())

    def test_retailer_cannot_update_other_shops_product(self):
        self.login_retailer_a()

        response = self.client.post(
            reverse("update_product"),
            self.product_update_payload(self.product_b),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 404)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, 10)

    def test_retailer_cannot_delete_other_shops_product(self):
        self.login_retailer_a()

        response = self.client.post(reverse("delete_product", args=[self.product_b.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Product.objects.filter(pk=self.product_b.id).exists())

    def test_admin_can_update_any_product(self):
        self.login_admin()

        response = self.client.post(
            reverse("update_product"),
            self.product_update_payload(
                self.product_b, purchase_price="10", selling_price="12", mrp="15", current_stock="40"
            ),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, 40)

    def test_product_on_a_purchase_bill_cannot_be_deleted(self):
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "9.00", date(2026, 10, 1))
        self.login_retailer_a()

        response = self.client.post(reverse("delete_product", args=[self.product_a.id]))

        self.assertEqual(response.status_code, 409)
        self.assertTrue(PurchaseItem.objects.filter(product=self.product_a).exists())

    def test_unused_product_can_still_be_deleted(self):
        self.login_retailer_a()

        response = self.client.post(reverse("delete_product", args=[self.product_a.id]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(pk=self.product_a.id).exists())

    def test_logged_out_user_is_sent_to_the_real_login_page(self):
        for name in ("sale_create", "sales_list", "dashboard"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("user_login")), (name, response.url))

    def test_login_returns_to_requested_page(self):
        response = self.client.post(
            reverse("user_login") + "?next=" + reverse("sales_list"),
            {"username": "shopa", "password": self.password},
        )

        self.assertRedirects(response, reverse("sales_list"), fetch_redirect_response=False)

    def test_login_ignores_external_next_url(self):
        response = self.client.post(
            reverse("user_login") + "?next=https://evil.example.com/",
            {"username": "shopa", "password": self.password},
        )

        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)


class QAProductAndDashboardRegressionTests(BaseTestData):

    def test_dashboard_shows_real_figures_for_own_shop(self):
        self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "10.00", date(2026, 10, 1))
        Purchase.objects.update(grand_total=Decimal("50.00"), due_amount=Decimal("50.00"))
        self._create_purchase(self.retailer_b, self.supplier_b1, self.product_b, "10.00", date(2026, 10, 1))
        self.login_retailer_a()

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "5,42,100")
        self.assertEqual(response.context["purchase_bills"], 1)
        self.assertEqual(response.context["purchase_total"], Decimal("50.00"))

    def test_product_stat_cards_ignore_status_tab(self):
        self.login_retailer_a()

        all_tab = self.client.get(reverse("product_list")).context["total_products"]
        inactive_tab = self.client.get(reverse("product_list"), {"status": "inactive"}).context["total_products"]

        self.assertEqual(all_tab, inactive_tab)

    def test_selling_price_below_purchase_price_is_rejected(self):
        self.login_retailer_a()

        response = self.client.post(
            reverse("add_product"),
            {
                "category": self.product_a.category_id, "brand": self.product_a.brand_id, "unit": self.unit.id,
                "product_name": "Loss Maker", "hsn_code": "1",
                "purchase_price": "50", "selling_price": "20", "mrp": "60",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Product.objects.filter(product_name="Loss Maker").exists())

    def test_reorder_search_and_pagination(self):
        Product.objects.filter(pk=self.product_a.pk).update(current_stock=1, minimum_stock=5)
        self.login_retailer_a()

        found = self.client.get(reverse("low_stock_alert"), {"search": "parac"})
        missing = self.client.get(reverse("low_stock_alert"), {"search": "zzz"})

        self.assertEqual(found.context["low_stock_count"], 1)
        # Now one translatable sentence (was split over several lines).
        self.assertContains(found, "Showing 1 - 1 of 1 products")
        self.assertEqual(missing.context["low_stock_count"], 0)

    def test_add_supplier_rejects_invalid_email(self):
        self.login_retailer_a()

        response = self.client.post(
            reverse("add_new_supplier"),
            {"supplier_name": "Bad Mail", "mobile": "9999999999", "email": "nope",
             "address": "x", "city": "x", "state": "x", "pincode": "411001"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Supplier.objects.filter(supplier_name="Bad Mail").exists())


class QAPurchaseRegressionTests(BaseTestData):

    url = reverse("add_new_order")

    def payload(self, **overrides):
        data = {
            "supplier": self.supplier_a1.id, "bill_number": "QA-1", "bill_date": "2026-10-24",
            "payment_terms": "net15", "item_name_1": "Paracetamol", "item_unit_1": self.unit.id,
            "item_qty_1": "4", "item_free_qty_1": "0", "item_price_1": "9.50",
            "item_tax_1": "none", "item_mrp_1": "15", "paid_amount": "0",
        }
        data.update(overrides)
        return data

    def test_retailer_cannot_use_other_shops_supplier(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload(supplier=self.supplier_b1.id))

        self.assertFalse(Purchase.objects.exists())

    def test_admin_cannot_mix_supplier_from_other_shop(self):
        self.login_admin()

        self.client.post(self.url, self.payload(retailer=self.retailer_a.id, supplier=self.supplier_b1.id))

        self.assertFalse(Purchase.objects.exists())

    def test_fractional_quantity_is_rejected(self):
        # Phase 3: fractions are allowed only for shops with decimal_quantity,
        # so this check runs on a shop type without it.
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        self.login_retailer_a()

        self.client.post(self.url, self.payload(item_qty_1="2.5"))

        self.assertFalse(Purchase.objects.exists())
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, 10)

    def test_same_bill_from_same_supplier_is_rejected(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload())
        self.client.post(self.url, self.payload())

        self.assertEqual(Purchase.objects.count(), 1)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, 14)

    def test_not_a_number_amount_is_rejected(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload(discount="NaN"))

        self.assertFalse(Purchase.objects.exists())

    def test_bill_number_is_not_prefilled(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertNotContains(response, 'value="BILL-2026-001"')

    def test_other_shops_purchase_detail_is_not_found(self):
        purchase = self._create_purchase(self.retailer_b, self.supplier_b1, self.product_b, "9.00", date(2026, 10, 1))
        self.login_retailer_a()

        response = self.client.get(reverse("purchase_detail", args=[purchase.id]))

        self.assertEqual(response.status_code, 404)

    def test_purchase_list_ignores_invalid_dates(self):
        self.login_retailer_a()

        response = self.client.get(reverse("purchase_product_list"), {"from_date": "nope", "supplier": "x"})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Something went wrong")


class QASalesRegressionTests(BaseTestData):

    url = reverse("sale_create")

    def setUp(self):
        self.customer = Customer.objects.create(retailer=self.retailer_a, customer_name="QA Buyer", mobile="9000000777")

    def payload(self, **overrides):
        data = {
            "customer": self.customer.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": "2", "items[1][discount]": "0",
            "payment_type": "Cash", "paid_amount": "25.20", "action": "save",
        }
        data.update(overrides)
        return data

    def test_product_gst_is_added_to_the_invoice(self):
        # 2 x 12.00 = 24.00 + 5% GST 1.20 = 25.20
        self.login_retailer_a()

        self.client.post(self.url, self.payload())

        sale = Sale.objects.get()
        self.assertEqual(sale.gst, Decimal("1.20"))
        self.assertEqual(sale.grand_total, Decimal("25.20"))
        self.assertEqual(sale.payment_status, "Paid")
        self.assertEqual(sale.items.get().gst, Decimal("5.00"))

    def test_fractional_sale_quantity_is_rejected(self):
        # Phase 3: fractions are allowed only for shops with decimal_quantity,
        # so this check runs on a shop type without it.
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        self.login_retailer_a()

        self.client.post(self.url, self.payload(**{"items[1][quantity]": "1.5", "paid_amount": "10"}))

        self.assertFalse(Sale.objects.exists())
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, 10)

    def test_admin_can_load_any_shops_product_on_sale_screen(self):
        self.login_admin()

        response = self.client.get(reverse("sale_product_data", args=[self.product_b.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["product"]["gst"], "5.00")

    def test_retailer_cannot_load_other_shops_product_on_sale_screen(self):
        self.login_retailer_a()

        response = self.client.get(reverse("sale_product_data", args=[self.product_b.id]))

        self.assertEqual(response.status_code, 404)


class QARetailerRegistrationRegressionTests(BaseTestData):

    url = reverse("retailer_register")

    def payload(self, **overrides):
        data = {
            "username": "newshop", "password": "Str0ng!Passw0rd", "email": "newshop@example.com",
            "shop_name": "New Shop", "owner_name": "Owner", "mobile": "9333333333",
            "address": "12 MG Road", "city": "Pune", "state": "Maharashtra", "pincode": "411001",
            "shop_type": "general",
        }
        data.update(overrides)
        return data

    def test_address_is_saved_as_entered(self):
        self.login_admin()

        self.client.post(self.url, self.payload())

        self.assertEqual(Retailer.objects.get(user__username="newshop").address, "12 MG Road")

    def test_invalid_input_is_rejected(self):
        self.login_admin()

        for field, value in (("address", ""), ("email", "not-an-email"), ("password", "123"), ("pincode", "12")):
            self.client.post(self.url, self.payload(**{field: value}))

        self.assertFalse(CustomUser.objects.filter(username="newshop").exists())

    def test_registration_form_has_address_field(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertContains(response, 'name="address"')


# =====================================================================
# RETAILERS LIST (admin only)
# =====================================================================

class RetailerListTests(BaseTestData):

    url = reverse("retailer_list")

    def test_admin_sees_every_retailer(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shop A")
        self.assertContains(response, "Shop B")
        self.assertEqual(response.context["total_count"], 2)

    def test_retailer_cannot_see_retailer_list(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)

    def test_search_filters_retailers(self):
        self.login_admin()

        response = self.client.get(self.url, {"search": "shop b"})

        shops = [retailer.shop_name for retailer in response.context["retailers"]]
        self.assertEqual(shops, ["Shop B"])

    def test_sidebar_shows_retailers_link_to_admin_only(self):
        self.login_admin()
        self.assertContains(self.client.get(reverse("dashboard")), f'href="{self.url}"')

        self.login_retailer_a()
        self.assertNotContains(self.client.get(reverse("dashboard")), f'href="{self.url}"')

    def test_add_retailer_page_has_back_button_to_list(self):
        self.login_admin()

        response = self.client.get(reverse("retailer_register"))

        self.assertContains(response, f'href="{self.url}" class="page-back-btn"')

    def test_registration_returns_to_retailer_list(self):
        self.login_admin()

        response = self.client.post(reverse("retailer_register"), {
            "username": "shopc", "password": "Str0ng!Passw0rd", "email": "shopc@example.com",
            "shop_name": "Shop C", "owner_name": "Owner", "mobile": "9333333333",
            "address": "1 Road", "city": "Pune", "state": "Maharashtra", "pincode": "411001",
            "shop_type": "stationery",
        })

        self.assertRedirects(response, self.url, fetch_redirect_response=False)


# =====================================================================
# PURCHASE BILL PAYMENTS
# =====================================================================

class PurchasePaymentTests(BaseTestData):

    def setUp(self):
        self.bill = self._create_purchase(
            self.retailer_a, self.supplier_a1, self.product_a, "10.00", date(2026, 10, 1)
        )
        Purchase.objects.filter(pk=self.bill.pk).update(
            grand_total=Decimal("100.00"), paid_amount=Decimal("0.00"),
            due_amount=Decimal("100.00"), payment_status="Unpaid",
            due_date=date(2026, 10, 10),
        )
        self.bill.refresh_from_db()
        self.url = reverse("purchase_add_payment", args=[self.bill.id])

    def pay(self, amount, **extra):
        data = {"amount": amount, "payment_type": "Cash", "payment_date": "2026-10-05"}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_partial_payment_updates_bill(self):
        self.login_retailer_a()

        response = self.pay("40.00")

        self.assertRedirects(response, reverse("purchase_detail", args=[self.bill.id]), fetch_redirect_response=False)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid_amount, Decimal("40.00"))
        self.assertEqual(self.bill.due_amount, Decimal("60.00"))
        self.assertEqual(self.bill.payment_status, "Partial")
        self.assertEqual(self.bill.payments.count(), 1)

    def test_payment_after_due_date_is_allowed_and_closes_bill(self):
        self.login_retailer_a()

        self.pay("40.00")
        self.pay("60.00", payment_date="2026-10-20")  # after the 10 Oct due date

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.due_amount, Decimal("0.00"))
        self.assertEqual(self.bill.payment_status, "Paid")
        self.assertEqual(self.bill.payments.count(), 2)

    def test_closed_bill_takes_no_more_payments(self):
        self.login_retailer_a()
        self.pay("100.00")

        self.pay("1.00")

        self.assertEqual(self.bill.payments.count(), 1)

    def test_overpayment_is_rejected(self):
        self.login_retailer_a()

        self.pay("100.01")

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid_amount, Decimal("0.00"))
        self.assertFalse(self.bill.payments.exists())

    def test_payment_date_before_bill_or_in_future_is_rejected(self):
        self.login_retailer_a()

        self.pay("10.00", payment_date="2026-09-30")
        self.pay("10.00", payment_date="2999-01-01")

        self.assertFalse(self.bill.payments.exists())

    def test_other_payment_modes_are_saved_as_cash(self):
        self.login_retailer_a()

        self.pay("10.00", payment_type="UPI", reference="UPI-123")

        payment = self.bill.payments.get()
        self.assertEqual(payment.payment_type, "Cash")
        self.assertIsNone(payment.reference)

    def test_retailer_cannot_pay_another_shops_bill(self):
        self.login_retailer_b()

        response = self.pay("10.00")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.bill.payments.exists())

    def test_admin_can_pay_any_bill(self):
        self.login_admin()

        self.pay("25.00")

        self.bill.refresh_from_db()
        self.assertEqual(self.bill.paid_amount, Decimal("25.00"))
        self.assertEqual(self.bill.payments.get().created_by, self.admin)

    def test_detail_page_shows_history_and_overdue_banner(self):
        self.login_retailer_a()
        self.pay("40.00")

        response = self.client.get(reverse("purchase_detail", args=[self.bill.id]))

        self.assertContains(response, "Payment History")
        self.assertContains(response, "₹40.00")
        self.assertTrue(response.context["is_overdue"])
        self.assertContains(response, "Payment overdue by")
        self.assertContains(response, 'id="payModal"')

    def test_detail_page_of_closed_bill_has_no_payment_form(self):
        self.login_retailer_a()
        self.pay("100.00")

        response = self.client.get(reverse("purchase_detail", args=[self.bill.id]))

        self.assertContains(response, "Bill fully paid and closed")
        self.assertNotContains(response, 'id="payModal"')

    def test_printable_bill_includes_payment_history(self):
        self.login_retailer_a()
        self.pay("40.00", remarks="Part payment by hand")

        response = self.client.get(reverse("purchase_invoice", args=[self.bill.id]), {"download": "1"})

        self.assertContains(response, "Purchase Bill")
        self.assertContains(response, "Part payment by hand")
        self.assertContains(response, "Paracetamol")
        self.assertTrue(response.context["auto_download"])

    def test_printable_bill_of_another_shop_is_not_found(self):
        self.login_retailer_b()

        response = self.client.get(reverse("purchase_invoice", args=[self.bill.id]))

        self.assertEqual(response.status_code, 404)

    def test_purchase_list_shows_shop_column_to_admin_only(self):
        self.login_admin()
        self.assertContains(self.client.get(reverse("purchase_product_list")), "<th>Retailer Shop</th>")

        self.login_retailer_a()
        self.assertNotContains(self.client.get(reverse("purchase_product_list")), "<th>Retailer Shop</th>")


class AddOrderSaveAndPrintTests(BaseTestData):

    url = reverse("add_new_order")

    def payload(self, **overrides):
        data = {
            "supplier": self.supplier_a1.id, "bill_number": "BILL-SP", "bill_date": "2026-10-24",
            "payment_terms": "net15", "item_name_1": "Paracetamol", "item_unit_1": self.unit.id,
            "item_qty_1": "4", "item_free_qty_1": "0", "item_price_1": "10",
            "item_tax_1": "none", "item_mrp_1": "15", "paid_amount": "0",
        }
        data.update(overrides)
        return data

    def test_page_has_save_and_save_print_buttons(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertContains(response, 'name="action" value="save"')
        self.assertContains(response, 'name="action" value="save_print"')
        self.assertContains(response, 'id="supplierAccount"')
        self.assertContains(response, f'data-summary-url="{reverse("supplier_summary", args=[self.supplier_a1.id])}"')

    def test_save_and_print_opens_printable_bill(self):
        self.login_retailer_a()

        response = self.client.post(self.url, self.payload(action="save_print"))

        purchase = Purchase.objects.get(bill_number="BILL-SP")
        self.assertRedirects(
            response,
            reverse("purchase_invoice", args=[purchase.id]) + "?print=1",
            fetch_redirect_response=False,
        )

    def test_amount_paid_at_purchase_is_the_first_payment(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload(paid_amount="15", payment_type="UPI"))

        purchase = Purchase.objects.get(bill_number="BILL-SP")
        payment = purchase.payments.get()
        self.assertEqual(payment.amount, Decimal("15.00"))
        self.assertEqual(payment.payment_type, "Cash")      # cash only; UPI is ignored
        self.assertEqual(purchase.payment_type, "Cash")
        self.assertEqual(payment.payment_date, date(2026, 10, 24))
        self.assertEqual(purchase.due_amount, Decimal("25.00"))

    def test_nothing_paid_keeps_the_whole_bill_due(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload(paid_amount="0"))

        purchase = Purchase.objects.get(bill_number="BILL-SP")
        self.assertEqual((purchase.paid_amount, purchase.payment_status), (Decimal("0.00"), "Unpaid"))
        self.assertFalse(purchase.payments.exists())


# =====================================================================
# SUPPLIER ACCOUNT
# =====================================================================

class SupplierAccountTests(BaseTestData):

    def setUp(self):
        self.old_bill = self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "10.00", date(2026, 9, 1))
        self.new_bill = self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "12.00", date(2026, 10, 1))
        Purchase.objects.filter(pk=self.old_bill.pk).update(
            grand_total=Decimal("50.00"), paid_amount=Decimal("20.00"), due_amount=Decimal("30.00"),
            payment_status="Partial", due_date=date(2026, 9, 15),
        )
        Purchase.objects.filter(pk=self.new_bill.pk).update(
            grand_total=Decimal("60.00"), paid_amount=Decimal("60.00"), due_amount=Decimal("0.00"),
            payment_status="Paid",
        )

    def test_summary_json_shows_what_is_owed(self):
        self.login_retailer_a()

        data = self.client.get(reverse("supplier_summary", args=[self.supplier_a1.id])).json()

        self.assertEqual(data["bills"], 2)
        self.assertEqual(Decimal(data["billed"]), Decimal("110.00"))
        self.assertEqual(Decimal(data["due"]), Decimal("30.00"))
        self.assertEqual(Decimal(data["overdue"]), Decimal("30.00"))
        self.assertEqual([bill["id"] for bill in data["open_bills"]], [self.old_bill.id])
        self.assertTrue(data["open_bills"][0]["overdue"])

    def test_summary_json_of_another_shops_supplier_is_not_found(self):
        self.login_retailer_b()

        response = self.client.get(reverse("supplier_summary", args=[self.supplier_a1.id]))

        self.assertEqual(response.status_code, 404)

    def test_account_page_statement_has_running_balance(self):
        self.login_retailer_a()
        self.client.post(
            reverse("purchase_add_payment", args=[self.old_bill.id]),
            {"amount": "10", "payment_type": "Cash", "payment_date": "2026-09-20"},
        )

        response = self.client.get(reverse("supplier_account", args=[self.supplier_a1.id]))

        self.assertEqual(response.status_code, 200)
        statement = response.context["statement"]
        self.assertEqual(statement[-1]["balance"], Decimal("110.00") - Decimal("10.00"))
        self.assertEqual(response.context["account"]["due"], Decimal("20.00"))

    def test_account_page_of_another_shops_supplier_is_not_found(self):
        self.login_retailer_b()

        response = self.client.get(reverse("supplier_account", args=[self.supplier_a1.id]))

        self.assertEqual(response.status_code, 404)

    def test_statement_can_be_printed_and_downloaded(self):
        self.login_admin()

        response = self.client.get(reverse("supplier_statement", args=[self.supplier_a1.id]), {"download": "1"})

        self.assertContains(response, "Supplier Statement")
        self.assertContains(response, "Alpha Traders")
        self.assertTrue(response.context["auto_download"])

    def test_supplier_list_links_to_account(self):
        self.login_retailer_a()

        response = self.client.get(reverse("supplier_list"))

        self.assertContains(response, reverse("supplier_account", args=[self.supplier_a1.id]))


# =====================================================================
# CUSTOMER ACCOUNTS (KHATA / UDHARI)
# =====================================================================

class CustomerAccountTests(BaseTestData):

    def setUp(self):
        self.customer = Customer.objects.create(
            retailer=self.retailer_a, customer_name="Ramesh", mobile="9000000201",
            opening_balance=Decimal("10.00"),
        )
        self.other_customer = Customer.objects.create(
            retailer=self.retailer_b, customer_name="Suresh", mobile="9000000202",
        )

    def sell(self, qty="2", paid="0", payment_type="Credit"):
        # 2 x 12.00 = 24.00 + 5% GST = 25.20
        self.login_retailer_a()
        self.client.post(reverse("sale_create"), {
            "customer": self.customer.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": qty, "items[1][discount]": "0",
            "payment_type": payment_type, "paid_amount": paid, "action": "save",
        })
        return Sale.objects.filter(customer=self.customer).order_by("-id").first()

    def receive(self, amount, **extra):
        data = {"amount": amount, "payment_type": "Cash"}
        data.update(extra)
        return self.client.post(reverse("customer_receive_payment", args=[self.customer.id]), data)

    def test_balance_includes_opening_balance_and_unpaid_bills(self):
        from .accounts import customer_balance

        self.sell()                       # 25.20 on credit
        self.sell(qty="1", paid="5", payment_type="Cash")   # 12.60, 5 paid -> 7.60 due

        self.assertEqual(customer_balance(self.customer), Decimal("42.80"))

    def test_payment_without_buying_settles_oldest_bill_first(self):
        first = self.sell()                                   # 25.20 due
        second = self.sell(qty="1", paid="5", payment_type="Cash")  # 7.60 due

        response = self.receive("30.00")

        self.assertRedirects(response, reverse("customer_account", args=[self.customer.id]), fetch_redirect_response=False)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.due_amount, Decimal("0.00"))
        self.assertEqual(first.payment_status, "Paid")
        self.assertEqual(second.due_amount, Decimal("2.80"))
        self.assertEqual(second.payment_status, "Partial")

        receipts = set(Payment.objects.filter(customer=self.customer, remarks="Due payment received")
                       .values_list("receipt_number", flat=True))
        self.assertEqual(len(receipts), 1)
        self.assertTrue(next(iter(receipts)).startswith("RCPT-"))

    def test_left_over_money_clears_opening_balance(self):
        from .accounts import customer_balance

        sale = self.sell()          # 25.20 due + 10.00 opening = 35.20

        self.receive("35.20")

        sale.refresh_from_db()
        self.assertEqual(sale.due_amount, Decimal("0.00"))
        self.assertEqual(customer_balance(self.customer), Decimal("0.00"))
        self.assertTrue(Payment.objects.filter(customer=self.customer, sale__isnull=True, amount=Decimal("10.00")).exists())

    def test_cannot_receive_more_than_due(self):
        self.sell()
        self.login_retailer_a()

        self.receive("999")

        self.assertFalse(Payment.objects.filter(customer=self.customer, remarks="Due payment received").exists())

    def test_customer_with_no_due_cannot_pay(self):
        self.customer.opening_balance = Decimal("0.00")
        self.customer.save()
        self.login_retailer_a()

        self.receive("5")

        self.assertFalse(Payment.objects.filter(customer=self.customer).exists())

    def test_retailer_cannot_receive_for_another_shops_customer(self):
        self.login_retailer_a()

        response = self.client.post(
            reverse("customer_receive_payment", args=[self.other_customer.id]),
            {"amount": "5", "payment_type": "Cash"},
        )

        self.assertEqual(response.status_code, 404)

    def test_account_page_shows_orders_and_statement(self):
        self.sell()

        response = self.client.get(reverse("customer_account", args=[self.customer.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["balance"], Decimal("35.20"))
        self.assertEqual(len(response.context["sales"]), 1)
        self.assertEqual(response.context["statement"][0]["particulars"], "Opening balance")
        self.assertEqual(response.context["statement"][-1]["balance"], Decimal("35.20"))
        self.assertContains(response, "Receive payment")

    def test_account_page_opens_payment_popup_from_link(self):
        self.login_retailer_a()

        response = self.client.get(reverse("customer_account", args=[self.customer.id]), {"pay": "1"})

        self.assertContains(response, 'data-auto-open="1"')

    def test_other_shops_customer_account_is_not_found(self):
        self.login_retailer_a()

        response = self.client.get(reverse("customer_account", args=[self.other_customer.id]))

        self.assertEqual(response.status_code, 404)

    def test_customer_list_is_scoped_and_shows_dues(self):
        self.sell()

        response = self.client.get(reverse("customer_list"))

        names = [customer.customer_name for customer in response.context["customers"]]
        self.assertEqual(names, ["Ramesh"])
        self.assertEqual(response.context["customers"][0].outstanding, Decimal("35.20"))

    def test_admin_customer_list_has_every_shop_and_dues_filter(self):
        self.sell()
        self.login_admin()

        everyone = self.client.get(reverse("customer_list"))
        with_dues = self.client.get(reverse("customer_list"), {"dues": "1"})

        self.assertEqual(everyone.context["summary"]["count"], 2)
        self.assertEqual([c.customer_name for c in with_dues.context["customers"]], ["Ramesh"])

    def test_summary_json_for_sale_screen(self):
        self.sell()

        data = self.client.get(reverse("customer_summary", args=[self.customer.id])).json()

        self.assertEqual(Decimal(data["balance"]), Decimal("35.20"))
        self.assertEqual(len(data["recent"]), 1)
        self.assertEqual(Decimal(data["recent"][0]["due"]), Decimal("25.20"))

    def test_sale_screen_shows_real_outstanding(self):
        self.sell()

        response = self.client.get(reverse("sale_create"))

        self.assertContains(response, 'data-outstanding="35.20"')
        self.assertContains(response, 'id="customerHistory"')
        self.assertContains(response, 'id="duePaymentModal"')

    def test_payment_from_sale_screen_returns_to_sale_screen(self):
        self.sell()

        response = self.receive("5", next="sale_create")

        self.assertRedirects(response, reverse("sale_create"), fetch_redirect_response=False)

    def test_statement_print_and_download(self):
        self.sell()

        response = self.client.get(reverse("customer_statement", args=[self.customer.id]), {"download": "1"})

        self.assertContains(response, "Customer Statement")
        self.assertContains(response, "Ramesh")
        self.assertTrue(response.context["auto_download"])

    def test_credit_limit_uses_current_balance(self):
        self.customer.credit_limit = Decimal("40.00")
        self.customer.save()
        self.sell()                     # 35.20 owed now

        blocked = self.sell(qty="1")    # +12.60 would exceed 40

        self.assertEqual(Sale.objects.filter(customer=self.customer).count(), 1)
        self.receive("35.20")
        self.sell(qty="1")
        self.assertEqual(Sale.objects.filter(customer=self.customer).count(), 2)


# =====================================================================
# DASHBOARD
# =====================================================================

class DashboardTests(BaseTestData):

    url = reverse("dashboard")

    def setUp(self):
        self.today = timezone.localdate()
        self.customer_a = Customer.objects.create(retailer=self.retailer_a, customer_name="Dash A", mobile="9000000301")
        self.customer_b = Customer.objects.create(retailer=self.retailer_b, customer_name="Dash B", mobile="9000000302")

    def make_sale(self, retailer, customer, total, paid, day=None):
        sale = Sale.objects.create(
            retailer=retailer, customer=customer, invoice_date=day or self.today,
            subtotal=Decimal(total), grand_total=Decimal(total), paid_amount=Decimal(paid),
            payment_type="Cash",
        )
        SaleItem.objects.create(
            sale=sale, product=retailer.products.first(), unit=self.unit,
            quantity=Decimal("2"), selling_price=Decimal(total) / 2,
        )
        return sale

    def credit_sale_a(self):
        # Goes through the real sale flow so the customer ledger is written.
        self.login_retailer_a()
        self.client.post(reverse("sale_create"), {
            "customer": self.customer_a.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": "2", "items[1][discount]": "0",
            "payment_type": "Credit", "paid_amount": "0", "action": "save",
        })

    def test_requires_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("user_login"), response.url)

    def test_retailer_sees_only_own_shop(self):
        self.make_sale(self.retailer_a, self.customer_a, "100.00", "100.00")
        self.make_sale(self.retailer_b, self.customer_b, "900.00", "900.00")
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sales_today_total"], Decimal("100.00"))
        self.assertEqual(response.context["sales_today_count"], 1)
        self.assertEqual(response.context["shop"], self.retailer_a)
        self.assertEqual(response.context["shop_rows"], [])
        self.assertNotContains(response, "Shops at a glance")
        self.assertNotContains(response, reverse("retailer_register"))

    def test_admin_sees_all_shops_and_shop_table(self):
        self.make_sale(self.retailer_a, self.customer_a, "100.00", "100.00")
        self.make_sale(self.retailer_b, self.customer_b, "900.00", "900.00")
        self.login_admin()

        response = self.client.get(self.url)

        self.assertEqual(response.context["sales_today_total"], Decimal("1000.00"))
        self.assertIsNone(response.context["shop"])
        self.assertEqual(len(response.context["shop_rows"]), 2)
        self.assertContains(response, "Shops at a glance")
        self.assertContains(response, reverse("retailer_list"))
        self.assertEqual(response.context["retailer_count"], 2)

    def test_admin_can_focus_on_one_shop(self):
        self.make_sale(self.retailer_a, self.customer_a, "100.00", "100.00")
        self.make_sale(self.retailer_b, self.customer_b, "900.00", "900.00")
        self.login_admin()

        response = self.client.get(self.url, {"retailer": self.retailer_b.id})

        self.assertEqual(response.context["shop"], self.retailer_b)
        self.assertEqual(response.context["sales_today_total"], Decimal("900.00"))
        self.assertNotContains(response, "Shops at a glance")

    def test_invalid_shop_filter_is_ignored(self):
        self.login_admin()

        for value in ("abc", "99999"):
            response = self.client.get(self.url, {"retailer": value})
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context["shop"])

    def test_retailer_cannot_use_shop_filter(self):
        self.make_sale(self.retailer_b, self.customer_b, "900.00", "900.00")
        self.login_retailer_a()

        response = self.client.get(self.url, {"retailer": self.retailer_b.id})

        self.assertEqual(response.context["shop"], self.retailer_a)
        self.assertEqual(response.context["sales_today_total"], Decimal("0.00"))

    def test_month_comparison_with_last_month(self):
        last_month = self.today.replace(day=1) - timedelta(days=1)
        same_day_last_month = last_month.replace(day=min(self.today.day, last_month.day))
        self.make_sale(self.retailer_a, self.customer_a, "100.00", "100.00", day=same_day_last_month)
        self.make_sale(self.retailer_a, self.customer_a, "150.00", "150.00")
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertEqual(response.context["sales_month_total"], Decimal("150.00"))
        self.assertEqual(response.context["sales_change"], 50.0)

    def test_customer_dues_are_shown(self):
        self.credit_sale_a()      # 25.20 on credit

        response = self.client.get(self.url)

        receivable = response.context["receivable"]
        self.assertEqual(receivable["total"], Decimal("25.20"))
        self.assertEqual(receivable["count"], 1)
        self.assertEqual(receivable["top"][0].customer_name, "Dash A")
        self.assertContains(response, "customer with dues")

    def test_overdue_supplier_bills_raise_an_alert(self):
        bill = self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "10.00", self.today - timedelta(days=40))
        Purchase.objects.filter(pk=bill.pk).update(
            grand_total=Decimal("80.00"), due_amount=Decimal("80.00"),
            due_date=self.today - timedelta(days=5),
        )
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertEqual(response.context["payable_total"], Decimal("80.00"))
        self.assertEqual(response.context["overdue_count"], 1)
        self.assertEqual(response.context["overdue_total"], Decimal("80.00"))
        self.assertContains(response, "supplier bill overdue")
        self.assertEqual(list(response.context["bills_to_pay"]), [Purchase.objects.get(pk=bill.pk)])

    def test_stock_alerts(self):
        Product.objects.filter(pk=self.product_a.pk).update(current_stock=0, minimum_stock=5)
        self._create_product(self.retailer_a, "Cough Syrup", stock=2)
        Product.objects.filter(product_name="Cough Syrup").update(minimum_stock=5)
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertEqual(response.context["out_of_stock_count"], 1)
        self.assertEqual(response.context["low_stock_count"], 1)
        self.assertContains(response, "product out of stock")
        self.assertContains(response, "product running low")
        names = [product.product_name for product in response.context["low_stock_products"]]
        self.assertEqual(names, ["Paracetamol", "Cough Syrup"])

    def test_all_clear_when_nothing_needs_attention(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertEqual(response.context["alerts"], [])
        self.assertContains(response, "All clear")

    def test_sales_chart_has_14_days_ending_today(self):
        self.make_sale(self.retailer_a, self.customer_a, "120.00", "120.00")
        self.make_sale(self.retailer_a, self.customer_a, "60.00", "60.00", day=self.today - timedelta(days=3))
        self.login_retailer_a()

        chart = self.client.get(self.url).context["chart"]

        self.assertEqual(len(chart["days"]), 14)
        self.assertEqual(chart["days"][-1]["date"], self.today)
        self.assertTrue(chart["days"][-1]["is_today"])
        self.assertEqual(chart["days"][-1]["total"], Decimal("120.00"))
        self.assertEqual(chart["total"], Decimal("180.00"))
        self.assertEqual(chart["best"]["date"], self.today)
        self.assertTrue(0 < chart["days"][-1]["height"] <= 100)
        self.assertEqual(chart["days"][-4]["height"] * 2, chart["days"][-1]["height"])

    def test_empty_chart_shows_message(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        self.assertFalse(response.context["chart"]["has_data"])
        self.assertContains(response, "No sales in the last 14 days")

    def test_top_selling_products(self):
        self.make_sale(self.retailer_a, self.customer_a, "100.00", "100.00")
        self.login_retailer_a()

        top = self.client.get(self.url).context["top_products"]

        self.assertEqual(top[0]["product__product_name"], "Paracetamol")
        self.assertEqual(top[0]["share"], 100.0)

    def test_quick_actions_and_module_links(self):
        self.login_retailer_a()

        response = self.client.get(self.url)

        for name in ("sale_create", "add_new_order", "add_product", "add_new_supplier",
                     "sales_list", "purchase_product_list", "customer_list", "supplier_list",
                     "product_list", "low_stock_alert"):
            self.assertContains(response, f'href="{reverse(name)}', msg_prefix=name)

    def test_retailer_without_shop_sees_message(self):
        user = CustomUser.objects.create_user(username="noshop", password=self.password)
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No shop linked to your account")

    def test_dashboard_stylesheet_and_script_are_linked(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertContains(response, "css/dashboard_home.css")
        self.assertContains(response, "jss/dashboard_home.js")


class DashboardHelperTests(TestCase):

    def test_nice_ceiling(self):
        from .dashboard_views import _nice_ceiling

        self.assertEqual(_nice_ceiling(Decimal("0")), Decimal("100"))
        self.assertEqual(_nice_ceiling(Decimal("87")), Decimal("100"))
        self.assertEqual(_nice_ceiling(Decimal("180")), Decimal("200"))
        self.assertEqual(_nice_ceiling(Decimal("2300")), Decimal("2500"))
        self.assertEqual(_nice_ceiling(Decimal("4100")), Decimal("5000"))

    def test_compact_uses_indian_units(self):
        from .dashboard_views import _compact

        self.assertEqual(_compact(950), "950")
        self.assertEqual(_compact(1500), "1.5K")
        self.assertEqual(_compact(250000), "2.5L")
        self.assertEqual(_compact(20000000), "2Cr")

    def test_percent_change(self):
        from .dashboard_views import _percent_change

        self.assertIsNone(_percent_change(Decimal("10"), Decimal("0")))
        self.assertEqual(_percent_change(Decimal("75"), Decimal("100")), -25.0)


# =====================================================================
# PHASE 1: SHOP TYPES + CENTRAL FEATURE MAP
# =====================================================================

from .shop_types import (  # noqa: E402
    FEATURE_NAMES,
    SHOP_TYPE_FEATURES,
    SHOP_TYPE_LABELS,
    Features,
    all_features,
    features_for_type,
    get_features,
    normalize_shop_type,
)


class FeatureMapTests(TestCase):

    EXPECTED = {
        #                     dec    conv   mrp    hsn    below  batch  expiry presc  drug   price  quote  b2b    spec
        "general":    dict(zip(FEATURE_NAMES, (True,  True,  True,  True,  False, False, False, False, False, False, False, True,  False))),
        "stationery": dict(zip(FEATURE_NAMES, (False, True,  True,  True,  False, False, False, False, False, False, False, True,  False))),
        "cosmetics":  dict(zip(FEATURE_NAMES, (False, False, True,  True,  False, False, False, False, False, False, False, True,  False))),
        "pharmacy":   dict(zip(FEATURE_NAMES, (False, True,  True,  True,  False, True,  True,  True,  True,  False, False, True,  False))),
        "hardware":   dict(zip(FEATURE_NAMES, (True,  True,  False, True,  True,  False, False, False, False, True,  True,  True,  True))),
    }

    def test_feature_names_are_in_the_expected_order(self):
        self.assertEqual(FEATURE_NAMES, (
            "decimal_quantity", "unit_conversion", "mrp_required", "hsn_required",
            "allow_below_cost_sale", "batch_tracking", "expiry_tracking", "prescription_details",
            "drug_licence", "price_levels", "quotations", "b2b_tax_split",
            "product_specification",  # added in Phase 6 (hardware only)
        ))

    def test_every_shop_type_matches_the_agreed_table(self):
        for shop_type, expected in self.EXPECTED.items():
            with self.subTest(shop_type=shop_type):
                self.assertEqual(features_for_type(shop_type).as_dict(), expected)
                self.assertEqual(SHOP_TYPE_FEATURES[shop_type], expected)

    def test_get_features_for_each_shop_type(self):
        for shop_type in SHOP_TYPE_LABELS:
            with self.subTest(shop_type=shop_type):
                retailer = Retailer(shop_type=shop_type)
                features = get_features(retailer)
                self.assertEqual(features.shop_type, shop_type)
                self.assertEqual(features.as_dict(), self.EXPECTED[shop_type])
                self.assertEqual(retailer.features.as_dict(), self.EXPECTED[shop_type])

    def test_attribute_item_and_template_style_access(self):
        features = features_for_type("pharmacy")

        self.assertTrue(features.expiry_tracking)
        self.assertTrue(features["batch_tracking"])
        self.assertIn("drug_licence", features)
        self.assertNotIn("quotations", features)
        self.assertIn("expiry_tracking", features.enabled)

    def test_unknown_feature_fails_loudly(self):
        with self.assertRaises(AttributeError):
            features_for_type("general").expiry_tracking_typo

    def test_features_are_read_only(self):
        features = features_for_type("general")

        with self.assertRaises(AttributeError):
            features.expiry_tracking = True

    def test_unknown_flag_name_is_rejected(self):
        with self.assertRaises(ValueError):
            Features({"not_a_feature": True})

    def test_no_shop_means_every_feature_off(self):
        features = get_features(None)

        self.assertIsNone(features.shop_type)
        self.assertEqual(features.enabled, [])

    def test_unknown_or_empty_shop_type_falls_back_to_general(self):
        self.assertEqual(normalize_shop_type("bakery"), "general")
        self.assertEqual(normalize_shop_type(""), "general")
        self.assertEqual(get_features(Retailer(shop_type="bakery")).shop_type, "general")

    def test_admin_view_is_the_union_of_all_shop_types(self):
        features = all_features()

        for name in FEATURE_NAMES:
            with self.subTest(feature=name):
                self.assertEqual(
                    getattr(features, name),
                    any(self.EXPECTED[shop_type][name] for shop_type in self.EXPECTED),
                )


class ShopTypeModelTests(BaseTestData):

    def test_shops_without_a_type_are_general(self):
        # BaseTestData creates shops without choosing a type.
        self.assertEqual(self.retailer_a.shop_type, "general")
        self.assertEqual(self.retailer_b.shop_type, "general")

    def test_migration_makes_existing_shops_general(self):
        from importlib import import_module

        from django.apps import apps as global_apps

        migration = import_module("pharma_app.migrations.0003_retailer_shop_type")
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="")
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="pharmacy")

        migration.existing_shops_are_general(global_apps, None)

        self.assertEqual(Retailer.objects.get(pk=self.retailer_a.pk).shop_type, "general")
        self.assertEqual(Retailer.objects.get(pk=self.retailer_b.pk).shop_type, "pharmacy")


class ShopTypeRegistrationTests(BaseTestData):

    url = reverse("retailer_register")

    def payload(self, shop_type, number):
        return {
            "username": f"shop{number}", "password": "Str0ng!Passw0rd", "email": f"shop{number}@example.com",
            "shop_name": f"Shop {number}", "owner_name": "Owner", "mobile": "9333333333",
            "address": "1 Road", "city": "Pune", "state": "Maharashtra", "pincode": "411001",
            "shop_type": shop_type,
        }

    def test_registration_with_each_shop_type(self):
        self.login_admin()

        for number, shop_type in enumerate(SHOP_TYPE_LABELS, start=1):
            with self.subTest(shop_type=shop_type):
                self.client.post(self.url, self.payload(shop_type, number))
                retailer = Retailer.objects.get(user__username=f"shop{number}")
                self.assertEqual(retailer.shop_type, shop_type)
                self.assertEqual(retailer.features.shop_type, shop_type)

    def test_missing_shop_type_is_rejected(self):
        self.login_admin()

        self.client.post(self.url, self.payload("", 1))

        self.assertFalse(CustomUser.objects.filter(username="shop1").exists())

    def test_invalid_shop_type_is_rejected(self):
        self.login_admin()

        response = self.client.post(self.url, self.payload("bakery", 1), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field"], "shop_type")
        self.assertFalse(CustomUser.objects.filter(username="shop1").exists())

    def test_form_lists_every_shop_type(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertContains(response, 'name="shop_type"')
        for value, label in SHOP_TYPE_LABELS.items():
            self.assertContains(response, f'<option value="{value}">{label}</option>', html=True)
        self.assertContains(response, 'id="shopTypeFeatures"')

    def test_purchase_page_retailer_popup_asks_for_shop_type(self):
        self.login_admin()

        response = self.client.get(reverse("add_new_order"))

        self.assertContains(response, '<select class="form-control" name="shop_type" required>')
        self.assertContains(response, "'shop_type','mobile'")


class FeatureContextTests(BaseTestData):

    def test_retailer_pages_get_their_shop_features(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="pharmacy")
        self.login_retailer_a()

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["shop_type"], "pharmacy")
        self.assertEqual(response.context["shop_type_label"], "Pharmacy")
        self.assertTrue(response.context["features"].expiry_tracking)
        self.assertFalse(response.context["features"].quotations)
        self.assertEqual(response.context["current_shop"], Retailer.objects.get(pk=self.retailer_a.pk))
        self.assertContains(response, '<span class="shop-card-meta">Pharmacy</span>', html=True)   # sidebar shop card

    def test_general_shop_has_no_pharmacy_features(self):
        self.login_retailer_b()

        features = self.client.get(reverse("dashboard")).context["features"]

        self.assertFalse(features.expiry_tracking)
        self.assertTrue(features.decimal_quantity)

    def test_admin_menus_use_the_features_of_existing_shops(self):
        # Changed later: the admin sees a feature menu only once a shop
        # that uses it exists (both fixture shops are general here).
        self.login_admin()

        response = self.client.get(reverse("dashboard"))
        self.assertIsNone(response.context["shop_type"])
        self.assertFalse(response.context["features"].expiry_tracking)
        self.assertFalse(response.context["features"].quotations)

        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="pharmacy")
        features = self.client.get(reverse("dashboard")).context["features"]
        self.assertTrue(features.expiry_tracking)
        self.assertFalse(features.quotations)

    def test_logged_out_pages_get_no_features(self):
        response = self.client.get(reverse("user_login"))

        self.assertNotIn("features", response.context)

    def test_dashboard_shows_shop_type_badge(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="hardware")
        self.login_retailer_a()

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, '<span class="type-badge type-hardware">Hardware</span>', html=True)


class RetailerShopTypeListTests(BaseTestData):

    url = reverse("retailer_list")

    def setUp(self):
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="pharmacy")

    def test_list_shows_shop_type(self):
        self.login_admin()

        response = self.client.get(self.url)

        self.assertContains(response, "<th>Shop type</th>", html=True)
        self.assertContains(response, '<span class="type-badge type-pharmacy">Pharmacy</span>', html=True)

    def test_filter_by_shop_type(self):
        self.login_admin()

        response = self.client.get(self.url, {"shop_type": "pharmacy"})

        self.assertEqual([r.shop_name for r in response.context["retailers"]], ["Shop B"])
        self.assertEqual(response.context["shop_type"], "pharmacy")

    def test_unknown_shop_type_filter_is_ignored(self):
        self.login_admin()

        response = self.client.get(self.url, {"shop_type": "bakery"})

        self.assertEqual(response.context["shop_type"], "")
        self.assertEqual(response.context["retailers"].paginator.count, 2)

    def test_counts_per_shop_type(self):
        self.login_admin()

        counts = {value: count for value, _, count in self.client.get(self.url).context["shop_type_counts"]}

        self.assertEqual(counts["general"], 1)
        self.assertEqual(counts["pharmacy"], 1)
        self.assertEqual(counts["hardware"], 0)

    def test_django_admin_lists_and_filters_shop_type(self):
        from django.contrib import admin as django_admin

        model_admin = django_admin.site._registry[Retailer]
        self.assertIn("shop_type", model_admin.list_display)
        self.assertIn("shop_type", model_admin.list_filter)

        self.login_admin()
        response = self.client.get("/admin/pharma_app/retailer/", {"shop_type__exact": "pharmacy"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shop B")
        self.assertNotContains(response, "Shop A")


# =====================================================================
# PHASE 2: BARCODE PER SHOP, GST LIST, MRP/HSN BY FEATURE, BRANDING
# =====================================================================

import re  # noqa: E402
from unittest import mock  # noqa: E402

from django.db import IntegrityError  # noqa: E402
from django.test import override_settings  # noqa: E402

from .gst import GST_RATES, LEGACY_GST_RATES, gst_choices, is_allowed_rate, parse_rate  # noqa: E402
from .shop_types import Features  # noqa: E402


def product_payload(shop, **extra):
    data = {
        "category": Category.objects.filter(retailer=shop).first().id,
        "brand": Brand.objects.filter(retailer=shop).first().id,
        "unit": Unit.objects.first().id,
        "product_name": "Test Item",
        "hsn_code": "3004",
        "purchase_price": "10.00",
        "selling_price": "12.00",
        "mrp": "15.00",
        "gst": "5",
        "current_stock": "5",
        "minimum_stock": "1",
    }
    data.update(extra)
    return data


class BarcodePerShopTests(BaseTestData):

    url = reverse("add_product")

    def post(self, data):
        return self.client.post(self.url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_two_shops_can_use_the_same_barcode(self):
        self.login_retailer_a()
        first = self.post(product_payload(self.retailer_a, barcode="8901234567890"))
        self.login_retailer_b()
        second = self.post(product_payload(self.retailer_b, barcode="8901234567890"))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Product.objects.filter(barcode="8901234567890").count(), 2)

    def test_same_barcode_twice_in_one_shop_is_rejected(self):
        self.login_retailer_a()
        self.post(product_payload(self.retailer_a, barcode="8901234567890"))

        response = self.post(product_payload(self.retailer_a, product_name="Other", barcode="8901234567890"))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["field"], "barcode")

    def test_database_enforces_barcode_per_shop(self):
        Product.objects.filter(pk=self.product_a.pk).update(barcode="ABC")
        Product.objects.filter(pk=self.product_b.pk).update(barcode="ABC")  # other shop: fine

        with self.assertRaises(IntegrityError):
            self._create_product(self.retailer_a, "Clash").__class__.objects.filter(
                product_name="Clash"
            ).update(barcode="ABC")

    def test_products_without_barcode_never_clash(self):
        Product.objects.filter(pk=self.product_a.pk).update(barcode=None)
        second = self._create_product(self.retailer_a, "No Code")
        Product.objects.filter(pk=second.pk).update(barcode="")
        third = self._create_product(self.retailer_a, "No Code Either")
        Product.objects.filter(pk=third.pk).update(barcode="")

        self.assertEqual(Product.objects.filter(retailer=self.retailer_a, barcode="").count(), 2)

    def test_migration_turns_blank_barcodes_into_null(self):
        from importlib import import_module

        from django.apps import apps as global_apps

        migration = import_module("pharma_app.migrations.0004_product_barcode_per_shop_optional_mrp")
        Product.objects.filter(pk=self.product_a.pk).update(barcode="")

        migration.blank_barcodes_to_null(global_apps, None)

        self.assertIsNone(Product.objects.get(pk=self.product_a.pk).barcode)


class GstRatesTests(BaseTestData):

    def test_one_list_of_current_rates(self):
        self.assertEqual([str(rate) for rate in GST_RATES], ["0", "0.25", "3", "5", "18", "40"])
        self.assertEqual(
            gst_choices(),
            [("0", "0%"), ("0.25", "0.25%"), ("3", "3%"), ("5", "5%"), ("18", "18%"), ("40", "40%")],
        )
        self.assertEqual([str(rate) for rate in LEGACY_GST_RATES], ["12", "28"])

    def test_parse_rate_accepts_numbers_and_old_codes(self):
        self.assertEqual(parse_rate("5"), Decimal("5"))
        self.assertEqual(parse_rate("18.00"), Decimal("18"))
        self.assertEqual(parse_rate("0.25"), Decimal("0.25"))
        self.assertEqual(parse_rate("gst5"), Decimal("5"))
        self.assertEqual(parse_rate("none"), Decimal("0"))
        self.assertEqual(parse_rate(""), Decimal("0"))

    def test_parse_rate_rejects_old_and_unknown_slabs(self):
        for value in ("12", "gst12", "28", "7", "abc", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_rate(value)
        self.assertFalse(is_allowed_rate("12"))
        self.assertTrue(is_allowed_rate("40"))

    def purchase(self, tax, bill="GST-1"):
        self.login_retailer_a()
        self.client.post(reverse("add_new_order"), {
            "supplier": self.supplier_a1.id, "bill_number": bill, "bill_date": "2026-10-24",
            "payment_terms": "net15", "item_name_1": "Paracetamol", "item_unit_1": self.unit.id,
            "item_qty_1": "10", "item_free_qty_1": "0", "item_price_1": "10",
            "item_tax_1": tax, "item_mrp_1": "15", "paid_amount": "0",
        })
        return Purchase.objects.filter(bill_number=bill).first()

    def test_purchase_with_new_slabs(self):
        purchase = self.purchase("18")

        self.assertEqual(purchase.gst, Decimal("18.00"))      # 100 x 18%
        self.assertEqual(purchase.items.get().gst, Decimal("18.00"))

        quarter = self.purchase("0.25", bill="GST-2")
        self.assertEqual(quarter.gst, Decimal("0.25"))

    def test_purchase_with_old_slab_is_rejected(self):
        self.assertIsNone(self.purchase("12"))
        self.assertIsNone(self.purchase("gst28", bill="GST-3"))

    def test_purchase_page_uses_the_list_from_the_server(self):
        self.login_retailer_a()

        response = self.client.get(reverse("add_new_order"))
        content = response.content.decode()

        self.assertEqual(response.context["gst_choices"], gst_choices())
        self.assertIn('<option value="0.25"', content)
        self.assertIn('<option value="40"', content)
        self.assertNotIn('value="gst12"', content)
        self.assertNotIn("taxRates", content)

    def test_product_forms_offer_the_current_slabs(self):
        self.login_retailer_a()

        response = self.client.get(reverse("add_product"))

        self.assertContains(response, '<select id="gst" name="gst" class="form-select">')
        self.assertContains(response, '<option value="40">40%</option>', html=True)
        self.assertNotContains(response, '<option value="12">')

    def test_old_purchase_bill_with_12_percent_still_prints(self):
        purchase = self._create_purchase(self.retailer_a, self.supplier_a1, self.product_a, "10.00", date(2025, 6, 1))
        PurchaseItem.objects.filter(purchase=purchase).update(gst=Decimal("12.00"))
        self.login_retailer_a()

        detail = self.client.get(reverse("purchase_detail", args=[purchase.id]))
        printed = self.client.get(reverse("purchase_invoice", args=[purchase.id]))

        self.assertContains(detail, "12%")
        self.assertContains(printed, "12%")

    def test_old_sale_with_28_percent_still_prints(self):
        customer = Customer.objects.create(retailer=self.retailer_a, customer_name="Old", mobile="9000000401")
        sale = Sale.objects.create(
            retailer=self.retailer_a, customer=customer, invoice_date=date(2025, 6, 1),
            subtotal=Decimal("100"), gst=Decimal("28"), grand_total=Decimal("128"),
            paid_amount=Decimal("128"), payment_type="Cash",
        )
        SaleItem.objects.create(
            sale=sale, product=self.product_a, unit=self.unit, quantity=Decimal("1"),
            selling_price=Decimal("100"), gst=Decimal("28"),
        )
        self.login_retailer_a()

        response = self.client.get(reverse("sale_invoice", args=[sale.id]))

        self.assertContains(response, "28%")
        self.assertContains(response, "₹128.00")


class MrpHsnByFeatureTests(BaseTestData):

    url = reverse("add_product")

    def setUp(self):
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="hardware")
        self.retailer_b.refresh_from_db()

    def post(self, data):
        return self.client.post(self.url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_hardware_shop_can_save_product_without_mrp(self):
        self.login_retailer_b()

        response = self.post(product_payload(self.retailer_b, product_name="Wire 1.5mm", mrp=""))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["mrp"], "")
        self.assertIsNone(Product.objects.get(product_name="Wire 1.5mm").mrp)

    def test_general_shop_still_needs_mrp(self):
        self.login_retailer_a()

        response = self.post(product_payload(self.retailer_a, mrp=""))

        self.assertEqual(response.status_code, 400)
        self.assertIn("MRP", response.json()["missing_fields"])

    def test_admin_follows_the_target_shops_rules(self):
        self.login_admin()

        hardware = self.post(product_payload(self.retailer_b, retailer=self.retailer_b.id, product_name="Pipe", mrp=""))
        general = self.post(product_payload(self.retailer_a, retailer=self.retailer_a.id, product_name="Soap", mrp=""))

        self.assertEqual(hardware.status_code, 201)
        self.assertEqual(general.status_code, 400)

    def test_hsn_is_required_while_the_feature_is_on(self):
        self.login_retailer_b()

        response = self.post(product_payload(self.retailer_b, hsn_code=""))

        self.assertEqual(response.status_code, 400)
        self.assertIn("HSN Code", response.json()["missing_fields"])

    def test_hsn_is_optional_when_the_feature_is_off(self):
        flags = Features({"mrp_required": True})  # hsn_required off
        self.login_retailer_a()

        with mock.patch("pharma_app.views.get_features", return_value=flags):
            response = self.post(product_payload(self.retailer_a, product_name="No HSN", hsn_code=""))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Product.objects.get(product_name="No HSN").hsn_code, "")

    def test_selling_above_mrp_is_checked_only_when_mrp_is_given(self):
        self.login_retailer_b()

        no_mrp = self.post(product_payload(self.retailer_b, product_name="Bolt", selling_price="50", mrp=""))
        above = self.post(product_payload(self.retailer_b, product_name="Nut", selling_price="50", mrp="40"))

        self.assertEqual(no_mrp.status_code, 201)
        self.assertEqual(above.status_code, 400)

    def test_hardware_may_sell_below_cost_with_a_warning(self):
        self.login_retailer_b()

        response = self.post(product_payload(self.retailer_b, product_name="Clearance", purchase_price="20", selling_price="15", mrp=""))

        self.assertEqual(response.status_code, 201)
        self.assertIn("below the purchase price", response.json()["warning"])

    def test_general_shop_cannot_sell_below_cost(self):
        self.login_retailer_a()

        response = self.post(product_payload(self.retailer_a, purchase_price="20", selling_price="15"))

        self.assertEqual(response.status_code, 400)

    def test_below_cost_warning_on_normal_form_submit(self):
        self.login_retailer_b()

        response = self.client.post(self.url, product_payload(self.retailer_b, product_name="Clearance", purchase_price="20", selling_price="15", mrp=""), follow=True)

        self.assertContains(response, "below the purchase price")

    def update(self, product, **extra):
        data = {
            "product_id": product.id, "purchase_price": "10", "selling_price": "12", "mrp": "15",
            "gst": "5", "current_stock": "10", "minimum_stock": "0", "is_active": "true",
        }
        data.update(extra)
        return self.client.post(reverse("update_product"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_update_without_mrp_follows_the_shop(self):
        self.login_retailer_b()
        self.assertEqual(self.update(self.product_b, mrp="").status_code, 200)
        self.product_b.refresh_from_db()
        self.assertIsNone(self.product_b.mrp)

        self.login_retailer_a()
        response = self.update(self.product_a, mrp="")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "MRP is required.")

    def test_update_below_cost_follows_the_shop(self):
        self.login_retailer_b()
        response = self.update(self.product_b, purchase_price="20", selling_price="15", mrp="")
        self.assertEqual(response.status_code, 200)
        self.assertIn("below the purchase price", response.json()["message"])

        self.login_retailer_a()
        self.assertEqual(self.update(self.product_a, purchase_price="20", selling_price="15").status_code, 400)

    def test_forms_get_each_shops_rules(self):
        self.login_admin()

        rules = self.client.get(self.url).context["shop_rules"]

        self.assertEqual(rules[str(self.retailer_b.id)], {
            "mrp_required": False, "hsn_required": True, "allow_below_cost_sale": True,
            "decimal_quantity": True, "unit_conversion": True,
            "batch_tracking": False, "prescription_details": False,
            "price_levels": True, "product_specification": True,
        })
        self.assertTrue(rules[str(self.retailer_a.id)]["mrp_required"])

    def test_product_without_mrp_shows_a_dash_and_can_be_sold(self):
        Product.objects.filter(pk=self.product_b.pk).update(mrp=None)
        customer = Customer.objects.create(retailer=self.retailer_b, customer_name="Mason", mobile="9000000402")
        self.login_retailer_b()

        listing = self.client.get(reverse("product_list"))
        self.assertContains(listing, '<div class="price-muted">—</div>', html=True)

        self.client.post(reverse("sale_create"), {
            "customer": customer.id,
            "items[1][product]": self.product_b.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": "1", "items[1][discount]": "0",
            "payment_type": "Cash", "paid_amount": "12.60", "action": "save",
        })
        sale = Sale.objects.get(customer=customer)
        self.assertIsNone(sale.items.get().mrp)
        self.assertContains(self.client.get(reverse("sale_invoice", args=[sale.id])), "—")


class BrandingTests(BaseTestData):

    def test_app_name_comes_from_one_setting(self):
        self.login_retailer_a()

        with override_settings(APP_DISPLAY_NAME="ShopEase"):
            dashboard = self.client.get(reverse("dashboard"))
            self.client.logout()
            login = self.client.get(reverse("user_login"))

        self.assertContains(dashboard, "<title>Dashboard - ShopEase</title>", html=True)
        self.assertContains(dashboard, '<span class="logo-text">ShopEase</span>', html=True)   # sidebar brand
        self.assertContains(login, "<title>Sign in - ShopEase</title>", html=True)
        self.assertContains(login, '<span class="logo-text">ShopEase</span>', html=True)

    def test_no_pharma_or_placeholder_names_in_templates(self):
        import re
        from pathlib import Path

        templates = Path(__file__).resolve().parent / "templates"
        for path in templates.glob("*.html"):
            text = path.read_text(encoding="utf-8")
            # Visible text only: drop template comments, HTML comments and {% url/static %} tags.
            visible = re.sub(r"\{#.*?#\}|<!--.*?-->|\{%.*?%\}", "", text, flags=re.S)
            with self.subTest(template=path.name):
                self.assertNotIn("My Django Site", visible)
                self.assertNotIn("StockWise", visible)
                self.assertIsNone(re.search(r"(?i)pharma(?!cy)", re.sub(r"pharma_app[/.]\w+", "", visible)))

    def test_general_shop_pages_do_not_mention_pharma(self):
        self.login_retailer_a()

        for name in ("dashboard", "product_list", "sales_list", "add_new_order"):
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                visible = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)
                # "Acme Pharma" is a supplier name in the test data, and "pharmacy" is a shop type option.
                self.assertNotRegex(visible.lower().replace("acme pharma", ""), r"pharma(?!cy)")


# =====================================================================
# PHASE 3: DECIMAL STOCK + LOOSE QUANTITIES
# =====================================================================

from .quantities import QuantityError, format_quantity, parse_quantity  # noqa: E402


class QuantityHelperTests(TestCase):

    def test_parse_allows_fractions_only_when_asked(self):
        self.assertEqual(parse_quantity("2.5", "Qty", allow_fraction=True), Decimal("2.500"))
        self.assertEqual(parse_quantity("0.125", "Qty", allow_fraction=True), Decimal("0.125"))
        self.assertEqual(parse_quantity("10", "Qty", allow_fraction=False), Decimal("10.000"))

        with self.assertRaisesMessage(QuantityError, "Qty must be a whole number for this shop."):
            parse_quantity("2.5", "Qty", allow_fraction=False)

    def test_parse_rejects_bad_values(self):
        for value, message in (
            ("", "Qty is required."),
            ("abc", "Qty must be a valid number."),
            ("NaN", "Qty must be a valid number."),
            ("-1", "Qty cannot be negative."),
            ("0", "Qty must be greater than zero."),
            ("1.2345", "Qty can have at most 3 decimal places."),
        ):
            with self.subTest(value=value):
                with self.assertRaisesMessage(QuantityError, message):
                    parse_quantity(value, "Qty", allow_fraction=True)

    def test_parse_zero_and_default(self):
        self.assertEqual(parse_quantity("0", "Qty", allow_fraction=False, allow_zero=True), Decimal("0.000"))
        self.assertEqual(parse_quantity("", "Qty", allow_fraction=False, allow_zero=True, default="0"), Decimal("0.000"))
        self.assertEqual(parse_quantity("1.500", "Qty", allow_fraction=True), Decimal("1.500"))  # trailing zeros fine

    def test_format_quantity(self):
        self.assertEqual(format_quantity(Decimal("10.000")), "10")
        self.assertEqual(format_quantity(Decimal("2.500")), "2.5")
        self.assertEqual(format_quantity(Decimal("0.125")), "0.125")
        self.assertEqual(format_quantity(Decimal("0")), "0")
        self.assertEqual(format_quantity(None), "0")

    def test_template_filters(self):
        from django.template import Context, Template

        rendered = Template("{% load qty %}{{ a|qty }}|{{ b|qty_unit:'kg' }}|{{ c|qty_unit:'' }}").render(
            Context({"a": Decimal("10.000"), "b": Decimal("2.500"), "c": Decimal("3")})
        )

        self.assertEqual(rendered, "10|2.5 kg|3")


class LooseQuantityTests(BaseTestData):

    def setUp(self):
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="hardware")
        self.customer_a = Customer.objects.create(retailer=self.retailer_a, customer_name="Loose A", mobile="9000000501")
        self.customer_b = Customer.objects.create(retailer=self.retailer_b, customer_name="Loose B", mobile="9000000502")

    def sell(self, customer, product, qty, paid):
        return self.client.post(reverse("sale_create"), {
            "customer": customer.id,
            "items[1][product]": product.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": qty, "items[1][discount]": "0",
            "payment_type": "Cash", "paid_amount": paid, "action": "save",
        })

    def buy(self, qty, free="0", bill="LOOSE-1"):
        return self.client.post(reverse("add_new_order"), {
            "supplier": self.supplier_a1.id, "bill_number": bill, "bill_date": "2026-10-24",
            "payment_terms": "net15", "item_name_1": "Paracetamol", "item_unit_1": self.unit.id,
            "item_qty_1": qty, "item_free_qty_1": free, "item_price_1": "10",
            "item_tax_1": "0", "item_mrp_1": "15", "paid_amount": "0",
        })

    def test_hardware_shop_sells_2_5_units(self):
        # 2.5 x 12.00 = 30.00 + 5% GST = 31.50
        self.login_retailer_b()

        self.sell(self.customer_b, self.product_b, "2.5", "31.50")

        sale = Sale.objects.get(customer=self.customer_b)
        self.assertEqual(sale.items.get().quantity, Decimal("2.500"))
        self.assertEqual(sale.grand_total, Decimal("31.50"))
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, Decimal("7.500"))

    def test_general_shop_sells_half_a_unit(self):
        # 0.5 x 12.00 = 6.00 + 5% GST = 6.30
        self.login_retailer_a()

        self.sell(self.customer_a, self.product_a, "0.5", "6.30")

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("9.500"))

    def test_stationery_shop_rejects_2_5(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        self.login_retailer_a()

        response = self.sell(self.customer_a, self.product_a, "2.5", "31.50")
        self.buy("2.5")

        self.assertFalse(Sale.objects.exists())
        self.assertFalse(Purchase.objects.exists())
        self.assertIn("whole number for this shop", " ".join(str(m) for m in response.wsgi_request._messages))
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("10"))

    def test_more_than_three_decimals_is_rejected(self):
        self.login_retailer_a()

        self.sell(self.customer_a, self.product_a, "0.1234", "1.30")

        self.assertFalse(Sale.objects.exists())

    def test_stock_math_after_purchase_and_sale(self):
        self.login_retailer_a()

        self.buy("2.25", free="0.5")                       # 10 + 2.25 + 0.5
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("12.750"))
        item = PurchaseItem.objects.get(purchase__bill_number="LOOSE-1")
        self.assertEqual((item.quantity, item.free_quantity), (Decimal("2.250"), Decimal("0.500")))

        # 0.125 x 12 = 1.50 + 5% = 1.575 -> 1.58 (kept 3 decimals, not rounded to 0.13)
        self.sell(self.customer_a, self.product_a, "0.125", "1.58")
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("12.625"))
        self.assertEqual(SaleItem.objects.get().quantity, Decimal("0.125"))

    def test_cannot_sell_more_than_fractional_stock(self):
        Product.objects.filter(pk=self.product_b.pk).update(current_stock=Decimal("2.5"))
        self.login_retailer_b()

        response = self.sell(self.customer_b, self.product_b, "2.6", "32.76")

        self.assertFalse(Sale.objects.exists())
        messages_text = " ".join(str(m) for m in response.wsgi_request._messages)
        self.assertIn("Available stock: 2.5.", messages_text)

    def add_product(self, shop, stock):
        return self.client.post(
            reverse("add_product"),
            product_payload(shop, product_name="Rope", current_stock=stock, minimum_stock="1.5", mrp=""),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_opening_stock_follows_the_shop(self):
        self.login_retailer_b()
        self.assertEqual(self.add_product(self.retailer_b, "2.5").status_code, 201)
        product = Product.objects.get(product_name="Rope")
        self.assertEqual((product.current_stock, product.minimum_stock), (Decimal("2.500"), Decimal("1.500")))

        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        self.login_retailer_a()
        response = self.client.post(
            reverse("add_product"),
            product_payload(self.retailer_a, product_name="Pen", current_stock="2.5"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Current stock must be a whole number for this shop.")

    def update_stock(self, product, stock):
        return self.client.post(reverse("update_product"), {
            "product_id": product.id, "purchase_price": "10", "selling_price": "12", "mrp": "15",
            "gst": "5", "current_stock": stock, "minimum_stock": "0", "is_active": "true",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_stock_edit_follows_the_shop(self):
        self.login_retailer_b()
        self.assertEqual(self.update_stock(self.product_b, "7.25").status_code, 200)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, Decimal("7.250"))

        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="cosmetics")
        self.login_retailer_a()
        response = self.update_stock(self.product_a, "7.25")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Current stock must be a whole number for this shop.")

    def test_stock_shows_clean_numbers(self):
        Product.objects.filter(pk=self.product_b.pk).update(current_stock=Decimal("2.5"), minimum_stock=Decimal("5"))
        self.login_retailer_b()

        product_list = self.client.get(reverse("product_list")).content.decode()
        reorder = self.client.get(reverse("low_stock_alert")).content.decode()
        dashboard = self.client.get(reverse("dashboard")).content.decode()
        data = self.client.get(reverse("sale_product_data", args=[self.product_b.id])).json()["product"]

        for html in (product_list, reorder, dashboard):
            self.assertIn("2.5 pc", html)
            self.assertNotIn("2.500", html)
            self.assertNotIn("5.000", html)
        self.assertEqual((data["stock"], data["unit"], data["decimal_quantity"]), ("2.5", "pc", True))

    def test_whole_stock_shows_without_decimals(self):
        self.login_retailer_a()

        html = self.client.get(reverse("product_list")).content.decode()

        self.assertIn("10 pc", html)
        self.assertNotIn("10.000", html)

    def test_invoice_shows_clean_quantity(self):
        self.login_retailer_b()
        self.sell(self.customer_b, self.product_b, "2.5", "31.50")
        sale = Sale.objects.get(customer=self.customer_b)

        invoice = self.client.get(reverse("sale_invoice", args=[sale.id])).content.decode()

        self.assertIn('<td class="num">2.5</td>', invoice)
        self.assertNotIn("2.500", invoice)

    def test_input_steps_follow_the_shop(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")

        self.login_retailer_a()
        stationery = self.client.get(reverse("add_product")).content.decode()
        sale_rules = self.client.get(reverse("sale_create")).context["shop_rules"]

        self.login_retailer_b()
        hardware = self.client.get(reverse("add_product")).content.decode()

        self.assertIn('step="1"\n                            data-quantity', stationery.replace("\r\n", "\n"))
        self.assertIn('step="0.001"\n                            data-quantity', hardware.replace("\r\n", "\n"))
        self.assertFalse(sale_rules[str(self.retailer_a.id)]["decimal_quantity"])

    def test_stock_can_never_go_negative_in_the_database(self):
        with self.assertRaises(IntegrityError):
            Product.objects.filter(pk=self.product_a.pk).update(current_stock=Decimal("-0.5"))


# =====================================================================
# PHASE 4: UNIT CONVERSION (BUY IN BOX, SELL IN PIECE)
# =====================================================================

from .units import clean_purchase_unit, conversion_factor_for, to_base_quantity  # noqa: E402


class UnitHelperTests(BaseTestData):

    def setUp(self):
        self.box = Unit.objects.create(name="Box", short_name="box")

    def test_factor_only_for_the_purchase_unit_with_the_feature_on(self):
        product = Product(unit=self.unit, purchase_unit=self.box, conversion_factor=Decimal("10"))

        self.assertEqual(conversion_factor_for(product, self.box, features_for_type("stationery")), Decimal("10"))
        self.assertEqual(conversion_factor_for(product, self.unit, features_for_type("stationery")), Decimal("1"))
        self.assertEqual(conversion_factor_for(product, self.box, features_for_type("cosmetics")), Decimal("1"))

    def test_to_base_quantity(self):
        self.assertEqual(to_base_quantity(Decimal("3"), Decimal("10"), "Qty", allow_fraction=False), Decimal("30.000"))
        self.assertEqual(to_base_quantity(Decimal("1.5"), Decimal("90"), "Qty", allow_fraction=True), Decimal("135.000"))

        with self.assertRaisesMessage(QuantityError, "more than 3 decimal places"):
            to_base_quantity(Decimal("0.001"), Decimal("1.333"), "Qty", allow_fraction=True)
        with self.assertRaisesMessage(QuantityError, "whole number of base units"):
            to_base_quantity(Decimal("1"), Decimal("2.5"), "Qty", allow_fraction=False)

    def test_clean_purchase_unit(self):
        units = Unit.objects.all()
        stationery = features_for_type("stationery")

        self.assertEqual(clean_purchase_unit(self.unit.id, self.box.id, "10", stationery, units), (self.box, Decimal("10.000")))
        self.assertEqual(clean_purchase_unit(self.unit.id, "", "10", stationery, units), (None, Decimal("1")))
        self.assertEqual(clean_purchase_unit(self.unit.id, self.box.id, "10", features_for_type("cosmetics"), units), (None, Decimal("1")))

        for unit_id, factor, message in (
            (self.unit.id, "10", "different from the selling unit"),
            (self.box.id, "1", "more than 1"),
            (self.box.id, "abc", "Enter how many"),
            (self.box.id, "2.5", "whole number for this shop"),
            ("999", "10", "valid purchase unit"),
        ):
            with self.subTest(unit=unit_id, factor=factor):
                with self.assertRaisesMessage(QuantityError, message):
                    clean_purchase_unit(self.unit.id, unit_id, factor, stationery, units)

        hardware = features_for_type("hardware")  # loose quantities: fractional factor ok
        self.assertEqual(clean_purchase_unit(self.unit.id, self.box.id, "2.5", hardware, units)[1], Decimal("2.500"))


class UnitConversionFlowTests(BaseTestData):
    """Buy in boxes / strips / bundles, stock and sell in base units."""

    def setUp(self):
        self.box = Unit.objects.create(name="Box", short_name="box")
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        # Pens: sold per pc at 6, bought per box of 10.
        Product.objects.filter(pk=self.product_a.pk).update(
            purchase_unit=self.box, conversion_factor=Decimal("10"),
            purchase_price=Decimal("5"), selling_price=Decimal("6"), mrp=Decimal("8"), gst=Decimal("0"),
        )
        self.product_a.refresh_from_db()
        self.customer = Customer.objects.create(retailer=self.retailer_a, customer_name="Student", mobile="9000000601")

    def buy(self, unit, qty, price, free="0", bill="BOX-1", product_name="Paracetamol", supplier=None, **extra):
        return self.client.post(reverse("add_new_order"), {
            "supplier": (supplier or self.supplier_a1).id, "bill_number": bill, "bill_date": "2026-10-24",
            "payment_terms": "net15", "item_name_1": product_name, "item_unit_1": unit.id,
            "item_qty_1": qty, "item_free_qty_1": free, "item_price_1": price,
            "item_tax_1": "0", "item_mrp_1": "8", "paid_amount": "0",
            **extra,
        })

    def sell(self, qty, unit=None, paid=None):
        return self.client.post(reverse("sale_create"), {
            "customer": self.customer.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": (unit or self.unit).id,
            "items[1][quantity]": qty, "items[1][discount]": "0",
            "payment_type": "Cash", "paid_amount": paid or str(Decimal(qty) * 6), "action": "save",
        })

    def test_buy_boxes_adds_pieces_to_stock(self):
        self.login_retailer_a()

        self.buy(self.box, "2", "50", free="1")            # 3 boxes x 10 = 30 pc

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("40"))   # 10 + 30
        item = PurchaseItem.objects.get(purchase__bill_number="BOX-1")
        self.assertEqual(item.unit, self.box)
        self.assertEqual(item.conversion_factor, Decimal("10"))
        self.assertEqual(item.base_quantity, Decimal("30"))
        self.assertEqual(item.base_unit_price, Decimal("5.00"))         # 50 per box / 10
        self.assertEqual(Purchase.objects.get(bill_number="BOX-1").subtotal, Decimal("100.00"))

    def test_buy_in_base_unit_still_works(self):
        self.login_retailer_a()

        self.buy(self.unit, "5", "5")

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("15"))
        self.assertEqual(PurchaseItem.objects.get().conversion_factor, Decimal("1"))

    def test_buy_boxes_then_sell_single_pieces(self):
        self.login_retailer_a()
        self.buy(self.box, "1", "50")                       # +10 pc -> 20

        self.sell("3")                                      # sold per pc

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("17"))
        self.assertEqual(SaleItem.objects.get().unit, self.unit)

    def test_sale_is_always_in_the_base_unit(self):
        self.login_retailer_a()

        self.sell("1", unit=self.box, paid="6")

        self.assertFalse(Sale.objects.exists())

    def test_fractional_boxes_rejected_without_loose_quantities(self):
        self.login_retailer_a()

        self.buy(self.box, "1.5", "50")

        self.assertFalse(Purchase.objects.exists())

    def test_shop_without_unit_conversion_ignores_the_purchase_unit(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="cosmetics")
        self.login_retailer_a()

        self.buy(self.box, "2", "50")

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("12"))   # factor 1
        self.assertEqual(PurchaseItem.objects.get().conversion_factor, Decimal("1"))

    def test_pharmacy_buys_strips_and_sells_loose_tablets(self):
        strip = Unit.objects.create(name="Strip", short_name="strip")
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="pharmacy")
        Product.objects.filter(pk=self.product_a.pk).update(
            purchase_unit=strip, conversion_factor=Decimal("10"), current_stock=Decimal("0"),
        )
        self.login_retailer_a()

        # Pharmacy purchases need batch + expiry on every line (Phase 5).
        self.buy(strip, "1", "50", item_batch_1="B1", item_expiry_1="2099-12")  # 1 strip = 10 tablets
        self.sell("3")

        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("7"))
        self.assertEqual(ProductBatch.objects.get(product=self.product_a).quantity, Decimal("7"))

    def test_hardware_buys_bundles_and_sells_metres(self):
        bundle = Unit.objects.create(name="Bundle", short_name="bundle")
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="hardware")
        Product.objects.filter(pk=self.product_b.pk).update(
            purchase_unit=bundle, conversion_factor=Decimal("90"), current_stock=Decimal("0"),
        )
        self.login_retailer_b()

        self.buy(bundle, "1.5", "900", supplier=self.supplier_b1, product_name="Ibuprofen", bill="WIRE-1")

        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, Decimal("135"))
        self.assertEqual(PurchaseItem.objects.get().base_unit_price, Decimal("10.00"))

    def test_price_history_is_compared_per_piece(self):
        self.login_retailer_a()
        self.buy(self.unit, "5", "5", bill="PC-1")          # 5.00 per pc
        self.buy(self.box, "1", "40", bill="BOX-2")         # 40 per box = 4.00 per pc

        data = self.client.get(reverse("purchase_history", args=[self.product_a.id])).json()

        self.assertEqual(Decimal(data["summary"]["min_price"]), Decimal("4.00"))
        self.assertEqual(Decimal(data["summary"]["max_price"]), Decimal("5.00"))
        self.assertEqual(Decimal(data["summary"]["total_qty"]), Decimal("15"))
        box_row = next(row for row in data["recent"] if row["bill_number"] == "BOX-2")
        self.assertEqual(box_row["entered"], "1 box @ 40.00")
        self.assertEqual(Decimal(box_row["quantity"]), Decimal("10"))

    def test_bill_shows_conversion(self):
        self.login_retailer_a()
        self.buy(self.box, "2", "50")
        purchase = Purchase.objects.get()

        detail = self.client.get(reverse("purchase_detail", args=[purchase.id])).content.decode()
        printed = self.client.get(reverse("purchase_invoice", args=[purchase.id])).content.decode()

        self.assertIn("2 box", detail)
        self.assertIn("= 20 pc in stock", detail)
        self.assertIn("₹5.00 / pc", detail)
        self.assertIn("= 20 pc", printed)

    def test_purchase_page_gets_conversion_data(self):
        self.login_retailer_a()

        response = self.client.get(reverse("add_new_order"))

        self.assertContains(response, f'data-purchase-unit="{self.box.id}"')
        self.assertContains(response, 'data-factor="10"')
        self.assertTrue(response.context["shop_rules"][str(self.retailer_a.id)]["unit_conversion"])


class ProductPurchaseUnitFormTests(BaseTestData):

    def setUp(self):
        self.box = Unit.objects.create(name="Box", short_name="box")

    def add(self, shop, **extra):
        return self.client.post(
            reverse("add_product"),
            product_payload(shop, product_name="Pen", **extra),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_stationery_saves_box_of_ten(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        self.login_retailer_a()

        response = self.add(self.retailer_a, purchase_unit=self.box.id, conversion_factor="10")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["purchase_unit_id"], self.box.id)
        product = Product.objects.get(product_name="Pen")
        self.assertEqual((product.purchase_unit, product.conversion_factor), (self.box, Decimal("10.000")))
        self.assertTrue(product.has_purchase_unit)

    def test_invalid_conversion_is_rejected(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        self.login_retailer_a()

        for extra in (
            {"purchase_unit": self.box.id, "conversion_factor": "2.5"},
            {"purchase_unit": self.box.id, "conversion_factor": "1"},
            {"purchase_unit": self.unit.id, "conversion_factor": "10"},
        ):
            with self.subTest(extra=extra):
                response = self.add(self.retailer_a, **extra)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["field"], "conversion_factor")

        self.assertFalse(Product.objects.filter(product_name="Pen").exists())

    def test_shop_without_conversion_ignores_it(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="cosmetics")
        self.login_retailer_a()

        response = self.add(self.retailer_a, purchase_unit=self.box.id, conversion_factor="10")

        self.assertEqual(response.status_code, 201)
        product = Product.objects.get(product_name="Pen")
        self.assertIsNone(product.purchase_unit)
        self.assertEqual(product.conversion_factor, Decimal("1"))

    def test_add_product_page_shows_conversion_only_for_shops_with_it(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="cosmetics")
        self.login_retailer_a()
        cosmetics = self.client.get(reverse("add_product")).content.decode()

        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="pharmacy")
        pharmacy = self.client.get(reverse("add_product")).content.decode()

        self.assertIn('data-feature="unit_conversion" hidden', cosmetics)
        self.assertIn('data-feature="unit_conversion">', pharmacy)
        self.assertIn('name="purchase_unit"', pharmacy)

    def update(self, product, **extra):
        data = {
            "product_id": product.id, "purchase_price": "10", "selling_price": "12", "mrp": "15",
            "gst": "5", "current_stock": "10", "minimum_stock": "0", "is_active": "true",
        }
        data.update(extra)
        return self.client.post(reverse("update_product"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_edit_sets_keeps_and_clears_conversion(self):
        self.login_retailer_a()  # general shop: unit conversion on

        self.assertEqual(self.update(self.product_a, purchase_unit=self.box.id, conversion_factor="12").status_code, 200)
        self.product_a.refresh_from_db()
        self.assertEqual((self.product_a.purchase_unit, self.product_a.conversion_factor), (self.box, Decimal("12")))

        self.update(self.product_a)  # fields not sent: unchanged
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.purchase_unit, self.box)

        self.update(self.product_a, purchase_unit="", conversion_factor="")  # cleared
        self.product_a.refresh_from_db()
        self.assertIsNone(self.product_a.purchase_unit)
        self.assertEqual(self.product_a.conversion_factor, Decimal("1"))

    def test_edit_rejects_bad_conversion(self):
        self.login_retailer_a()

        response = self.update(self.product_a, purchase_unit=self.box.id, conversion_factor="0.5")

        self.assertEqual(response.status_code, 400)
        self.assertIn("more than 1", response.json()["message"])

    def test_product_list_edit_popup_has_conversion_fields(self):
        self.login_retailer_a()

        response = self.client.get(reverse("product_list"))

        self.assertContains(response, 'id="modalPurchaseUnit" name="purchase_unit"')
        self.assertContains(response, 'id="modalConversionFactor" name="conversion_factor"')


# =====================================================================
# PHASE 5: PHARMACY (batches, expiry, FEFO, prescriptions, H1 register)
# Everything here is switched on by pharmacy features, not shop type.
# =====================================================================

from django.db import transaction as _transaction

from . import batches as batch_stock


class PharmacyBase(BaseTestData):
    """Shop A is a pharmacy; Shop B stays a general store."""

    def setUp(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(
            shop_type="pharmacy", drug_licence_number="20B-MH-111", drug_licence_number_2="21B-MH-222",
        )
        self.retailer_a.refresh_from_db()
        Product.objects.filter(pk=self.product_a.pk).update(
            current_stock=Decimal("0"), purchase_price=Decimal("5"), selling_price=Decimal("10"),
            mrp=Decimal("12"), gst=Decimal("0"), salt_composition="Paracetamol 500mg",
        )
        self.product_a.refresh_from_db()
        self.customer = Customer.objects.create(retailer=self.retailer_a, customer_name="Ravi", mobile="9000000701")
        self.customer_b = Customer.objects.create(retailer=self.retailer_b, customer_name="Sita", mobile="9000000702")
        self.today = date.today()

    def add_batch(self, number, expiry, qty, product=None):
        product = product or self.product_a
        with _transaction.atomic():
            locked = Product.objects.select_for_update().get(pk=product.pk)
            batch = batch_stock.receive_into_batch(
                locked, batch_number=number, expiry_date=expiry, quantity=Decimal(qty),
                purchase_price=Decimal("5"), mrp=Decimal("12"),
            )
        product.refresh_from_db()
        return batch

    def sell(self, qty, batch=None, discount="0", customer=None, product=None, **extra):
        product = product or self.product_a
        data = {
            "customer": (customer or self.customer).id,
            "items[1][product]": product.id, "items[1][unit]": product.unit_id,
            "items[1][quantity]": qty, "items[1][discount]": discount,
            "payment_type": "Cash", "action": "save",
        }
        price = product.selling_price
        data["paid_amount"] = str((Decimal(qty) * price - Decimal(discount)) * (1 + product.gst / 100))
        if batch is not None:
            data["items[1][batch]"] = batch.id
        data.update(extra)
        return self.client.post(reverse("sale_create"), data)

    def buy(self, qty, bill="PH-1", **extra):
        data = {
            "supplier": self.supplier_a1.id, "bill_number": bill, "bill_date": self.today.isoformat(),
            "payment_terms": "net15", "item_name_1": self.product_a.product_name, "item_unit_1": self.unit.id,
            "item_qty_1": qty, "item_free_qty_1": "0", "item_price_1": "5",
            "item_tax_1": "0", "item_mrp_1": "12", "paid_amount": "0",
        }
        data.update(extra)
        return self.client.post(reverse("add_new_order"), data)

    def batch_qty(self, batch):
        batch.refresh_from_db()
        return batch.quantity

    def assert_stock_matches_batches(self, product=None):
        product = product or self.product_a
        product.refresh_from_db()
        self.assertTrue(batch_stock.batches_in_sync(product), "stock must equal sum of batches")


class PharmacyPurchaseTests(PharmacyBase):

    def test_purchase_line_needs_batch_and_expiry(self):
        self.login_retailer_a()

        self.buy("10")                                           # no batch
        self.buy("10", bill="PH-2", item_batch_1="B1")           # no expiry

        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(ProductBatch.objects.exists())

    def test_purchase_creates_batch_and_stock_equals_sum(self):
        self.login_retailer_a()

        self.buy("10", item_batch_1="b1", item_expiry_1="2099-06")

        batch = ProductBatch.objects.get()
        self.assertEqual(batch.batch_number, "B1")                # stored upper-case
        self.assertEqual(batch.expiry_date, date(2099, 6, 30))    # month -> last day
        self.assertEqual(batch.quantity, Decimal("10"))
        self.assertEqual(batch.retailer, self.retailer_a)
        item = PurchaseItem.objects.get()
        self.assertEqual((item.batch, item.batch_number), (batch, "B1"))
        self.assert_stock_matches_batches()

    def test_same_batch_again_increases_it(self):
        self.login_retailer_a()

        self.buy("10", item_batch_1="B1", item_expiry_1="2099-06")
        self.buy("5", bill="PH-2", item_batch_1="B1", item_expiry_1="2099-06")

        self.assertEqual(ProductBatch.objects.get().quantity, Decimal("15"))
        self.assertEqual(self.product_a.__class__.objects.get(pk=self.product_a.pk).current_stock, Decimal("15"))

    def test_same_batch_with_other_expiry_is_rejected(self):
        self.login_retailer_a()
        self.buy("10", item_batch_1="B1", item_expiry_1="2099-06")

        self.buy("5", bill="PH-2", item_batch_1="B1", item_expiry_1="2098-01")

        self.assertFalse(Purchase.objects.filter(bill_number="PH-2").exists())   # whole bill rolled back
        self.assertEqual(ProductBatch.objects.get().quantity, Decimal("10"))
        self.assert_stock_matches_batches()

    def test_strips_go_into_the_batch_as_tablets(self):
        strip = Unit.objects.create(name="Strip", short_name="strip")
        Product.objects.filter(pk=self.product_a.pk).update(purchase_unit=strip, conversion_factor=Decimal("10"))
        self.login_retailer_a()

        self.buy("2", item_unit_1=strip.id, item_price_1="50", item_mrp_1="120",
                 item_batch_1="S1", item_expiry_1="2099-01")

        batch = ProductBatch.objects.get()
        self.assertEqual(batch.quantity, Decimal("20"))
        self.assertEqual(batch.purchase_price, Decimal("5.00"))   # per tablet
        self.assertEqual(batch.mrp, Decimal("12.00"))
        self.assert_stock_matches_batches()


class PharmacySaleTests(PharmacyBase):

    def test_fefo_sells_earliest_expiry_first(self):
        late = self.add_batch("LATE", self.today + timedelta(days=300), "10")
        early = self.add_batch("EARLY", self.today + timedelta(days=30), "10")
        self.login_retailer_a()

        self.sell("4")

        self.assertEqual(self.batch_qty(early), Decimal("6"))
        self.assertEqual(self.batch_qty(late), Decimal("10"))
        self.assertEqual(SaleItem.objects.get().batch, early)
        self.assert_stock_matches_batches()

    def test_line_splits_across_batches(self):
        first = self.add_batch("A1", self.today + timedelta(days=30), "3")
        second = self.add_batch("A2", self.today + timedelta(days=60), "10")
        self.login_retailer_a()

        self.sell("5", discount="1.00")

        items = list(SaleItem.objects.order_by("id"))
        self.assertEqual([(i.batch, i.quantity) for i in items], [(first, Decimal("3")), (second, Decimal("2"))])
        self.assertEqual(sum(i.discount for i in items), Decimal("1.00"))   # discount split, nothing lost
        self.assertEqual(self.batch_qty(first), Decimal("0"))
        self.assertEqual(self.batch_qty(second), Decimal("8"))
        sale = Sale.objects.get()
        self.assertEqual(sum(i.amount for i in items), sale.grand_total)
        self.assert_stock_matches_batches()

    def test_expired_batch_is_never_sold(self):
        expired = self.add_batch("OLD", self.today - timedelta(days=1), "10")
        self.login_retailer_a()

        self.sell("1")

        self.assertFalse(Sale.objects.exists())
        self.assertEqual(self.batch_qty(expired), Decimal("10"))

    def test_fefo_skips_expired_batch(self):
        expired = self.add_batch("OLD", self.today - timedelta(days=1), "10")
        good = self.add_batch("NEW", self.today + timedelta(days=90), "10")
        self.login_retailer_a()

        self.sell("2")

        self.assertEqual(self.batch_qty(expired), Decimal("10"))
        self.assertEqual(self.batch_qty(good), Decimal("8"))

    def test_choosing_an_expired_batch_is_rejected(self):
        expired = self.add_batch("OLD", self.today - timedelta(days=1), "10")
        self.add_batch("NEW", self.today + timedelta(days=90), "10")
        self.login_retailer_a()

        self.sell("1", batch=expired)

        self.assertFalse(Sale.objects.exists())

    def test_chosen_batch_is_used_first(self):
        early = self.add_batch("EARLY", self.today + timedelta(days=30), "10")
        late = self.add_batch("LATE", self.today + timedelta(days=300), "10")
        self.login_retailer_a()

        self.sell("3", batch=late)

        self.assertEqual(self.batch_qty(late), Decimal("7"))
        self.assertEqual(self.batch_qty(early), Decimal("10"))

    def test_batch_of_other_shop_cannot_be_chosen(self):
        self.add_batch("A1", self.today + timedelta(days=30), "10")
        other = ProductBatch.objects.create(
            retailer=self.retailer_b, product=self.product_b, batch_number="X",
            expiry_date=self.today + timedelta(days=30), quantity=Decimal("0"),
        )
        self.login_retailer_a()

        self.sell("1", batch=other)

        self.assertFalse(Sale.objects.exists())

    def test_more_than_unexpired_stock_is_rejected(self):
        self.add_batch("OLD", self.today - timedelta(days=1), "10")
        self.add_batch("NEW", self.today + timedelta(days=90), "2")
        self.login_retailer_a()

        self.sell("5")

        self.assertFalse(Sale.objects.exists())
        self.assert_stock_matches_batches()

    def test_stock_always_equals_sum_of_batches(self):
        self.login_retailer_a()
        self.buy("10", item_batch_1="P1", item_expiry_1="2099-01")
        self.buy("6", bill="PH-2", item_batch_1="P2", item_expiry_1="2098-01")
        self.assert_stock_matches_batches()

        self.sell("9")
        self.assert_stock_matches_batches()
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("7"))

    def test_sale_product_data_lists_sellable_batches(self):
        self.add_batch("OLD", self.today - timedelta(days=1), "10")
        self.add_batch("NEW", self.today + timedelta(days=90), "4")
        self.login_retailer_a()

        data = self.client.get(reverse("sale_product_data", args=[self.product_a.id])).json()["product"]

        self.assertTrue(data["batch_tracking"])
        self.assertEqual(data["stock"], "4")
        self.assertEqual([b["batch_number"] for b in data["batches"]], ["NEW"])

    def test_sale_page_gets_batch_data(self):
        self.add_batch("NEW", self.today + timedelta(days=90), "4")
        self.login_retailer_a()

        data = self.client.get(reverse("sale_create")).context["pharmacy_data"][str(self.product_a.id)]

        self.assertEqual(data["stock"], "4")
        self.assertEqual(data["salt"], "Paracetamol 500mg")


class PrescriptionTests(PharmacyBase):

    def setUp(self):
        super().setUp()
        Product.objects.filter(pk=self.product_a.pk).update(schedule=Product.SCHEDULE_H1)
        self.product_a.refresh_from_db()
        self.batch = self.add_batch("H1B", self.today + timedelta(days=200), "20")

    def test_h1_drug_needs_patient_and_doctor(self):
        self.login_retailer_a()

        self.sell("1")
        self.sell("1", patient_name="Ravi")
        self.sell("1", doctor_name="Dr. Rao")

        self.assertFalse(Sale.objects.exists())
        self.assertEqual(self.batch_qty(self.batch), Decimal("20"))

    def test_h1_sale_with_details_is_saved_and_in_register(self):
        self.login_retailer_a()

        self.sell("2", patient_name="Ravi Kumar", doctor_name="Dr. Rao", prescription_note="Rx 42")

        sale = Sale.objects.get()
        self.assertEqual((sale.patient_name, sale.doctor_name, sale.prescription_note), ("Ravi Kumar", "Dr. Rao", "Rx 42"))

        response = self.client.get(reverse("h1_register"))
        self.assertContains(response, "Ravi Kumar")
        self.assertContains(response, "Dr. Rao")
        self.assertContains(response, "H1B")
        self.assertContains(response, sale.invoice_number)

    def test_schedule_h_and_x_also_need_details(self):
        for schedule in (Product.SCHEDULE_H, Product.SCHEDULE_X):
            with self.subTest(schedule=schedule):
                Product.objects.filter(pk=self.product_a.pk).update(schedule=schedule)
                self.login_retailer_a()
                self.sell("1")
                self.assertFalse(Sale.objects.exists())

    def test_unscheduled_drug_needs_no_details(self):
        Product.objects.filter(pk=self.product_a.pk).update(schedule=Product.SCHEDULE_NONE)
        self.login_retailer_a()

        self.sell("1")

        self.assertEqual(Sale.objects.count(), 1)

    def test_invoice_shows_batch_expiry_licence_and_prescription(self):
        self.login_retailer_a()
        self.sell("1", patient_name="Ravi Kumar", doctor_name="Dr. Rao")
        sale = Sale.objects.get()

        response = self.client.get(reverse("sale_invoice", args=[sale.id]))

        self.assertContains(response, "H1B")
        self.assertContains(response, self.batch.expiry_date.strftime("%m/%Y"))
        self.assertContains(response, "20B-MH-111")
        self.assertContains(response, "21B-MH-222")
        self.assertContains(response, "Dr. Rao")

    def test_h1_register_is_scoped_and_feature_gated(self):
        self.login_retailer_a()
        self.sell("1", patient_name="Ravi Kumar", doctor_name="Dr. Rao")

        self.login_retailer_b()                                   # general store: no register
        self.assertRedirects(self.client.get(reverse("h1_register")), reverse("dashboard"), fetch_redirect_response=False)

        self.login_admin()
        self.assertContains(self.client.get(reverse("h1_register")), "Ravi Kumar")


class NonPharmacyUnaffectedTests(PharmacyBase):
    """Shop B (general) must work exactly as before."""

    def test_general_sale_uses_plain_stock_and_ignores_pharmacy_fields(self):
        self.login_retailer_b()

        response = self.sell("2", customer=self.customer_b, product=self.product_b,
                             patient_name="X", doctor_name="Y", **{"items[1][batch]": "999"})

        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual((sale.patient_name, sale.doctor_name), ("", ""))
        self.assertIsNone(SaleItem.objects.get().batch)
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, Decimal("8"))
        self.assertFalse(ProductBatch.objects.exists())

    def test_general_purchase_ignores_batch_fields(self):
        self.login_retailer_b()

        self.client.post(reverse("add_new_order"), {
            "supplier": self.supplier_b1.id, "bill_number": "G-1", "bill_date": self.today.isoformat(),
            "payment_terms": "net15", "item_name_1": "Ibuprofen", "item_unit_1": self.unit.id,
            "item_qty_1": "5", "item_free_qty_1": "0", "item_price_1": "10",
            "item_tax_1": "0", "item_mrp_1": "15", "paid_amount": "0",
            "item_batch_1": "ZZ", "item_expiry_1": "2099-01",
        })

        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, Decimal("15"))
        self.assertFalse(ProductBatch.objects.exists())
        self.assertIsNone(PurchaseItem.objects.get().batch_number)

    def test_general_invoice_has_no_batch_columns(self):
        self.login_retailer_b()
        self.sell("1", customer=self.customer_b, product=self.product_b)

        response = self.client.get(reverse("sale_invoice", args=[Sale.objects.get().id]))

        self.assertNotContains(response, "<th>Batch</th>")
        self.assertNotContains(response, "D.L. No")

    def test_pharmacy_pages_hidden_for_general_shop(self):
        self.login_retailer_b()

        self.assertRedirects(self.client.get(reverse("near_expiry")), reverse("dashboard"), fetch_redirect_response=False)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertNotContains(dashboard, reverse("near_expiry"))
        self.assertNotContains(dashboard, reverse("h1_register"))

    def test_drug_details_ignored_for_general_product(self):
        self.login_retailer_b()

        self.client.post(reverse("add_product"), product_payload(
            self.retailer_b, product_name="Soap", salt_composition="X", schedule="H1",
        ), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        soap = Product.objects.get(product_name="Soap")
        self.assertEqual((soap.salt_composition, soap.schedule), ("", Product.SCHEDULE_NONE))
        self.assertEqual(soap.current_stock, Decimal("5"))
        self.assertFalse(soap.batches.exists())


class PharmacyProductTests(PharmacyBase):

    def post_product(self, **extra):
        return self.client.post(reverse("add_product"), product_payload(self.retailer_a, **extra),
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_opening_stock_goes_into_opening_batch(self):
        self.login_retailer_a()

        response = self.post_product(product_name="Crocin", current_stock="20", opening_expiry="2099-03",
                                     salt_composition="Paracetamol 650mg", manufacturer="GSK", schedule="H")

        self.assertEqual(response.status_code, 201)
        crocin = Product.objects.get(product_name="Crocin")
        batch = crocin.batches.get()
        self.assertEqual((batch.batch_number, batch.quantity, batch.expiry_date),
                         (ProductBatch.OPENING_BATCH, Decimal("20"), date(2099, 3, 31)))
        self.assertEqual(crocin.current_stock, Decimal("20"))
        self.assertEqual((crocin.salt_composition, crocin.manufacturer, crocin.schedule),
                         ("Paracetamol 650mg", "GSK", "H"))

    def test_opening_stock_without_expiry_is_rejected(self):
        self.login_retailer_a()

        response = self.post_product(product_name="Crocin", current_stock="20")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Product.objects.filter(product_name="Crocin").exists())

    def test_zero_opening_stock_needs_no_expiry(self):
        self.login_retailer_a()

        self.assertEqual(self.post_product(product_name="Crocin", current_stock="0").status_code, 201)
        self.assertFalse(Product.objects.get(product_name="Crocin").batches.exists())

    def test_invalid_schedule_is_rejected(self):
        self.login_retailer_a()

        self.assertEqual(self.post_product(product_name="Crocin", current_stock="0", schedule="Z").status_code, 400)

    def test_stock_cannot_be_edited_directly(self):
        self.add_batch("A1", self.today + timedelta(days=30), "10")
        self.login_retailer_a()
        data = {
            "product_id": self.product_a.id, "purchase_price": "5", "selling_price": "10", "mrp": "12",
            "gst": "0", "current_stock": "50", "minimum_stock": "0", "is_active": "true",
        }

        response = self.client.post(reverse("update_product"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 400)

        data.update(current_stock="10", schedule="H1", salt_composition="Paracetamol 500mg")
        self.assertEqual(self.client.post(reverse("update_product"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 200)
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.schedule, "H1")
        self.assert_stock_matches_batches()

    def test_product_search_matches_salt(self):
        self.login_retailer_a()

        response = self.client.get(reverse("product_list"), {"search": "500mg"})

        self.assertContains(response, "Paracetamol")


class NearExpiryTests(PharmacyBase):

    def test_windows_and_expired_filter(self):
        self.add_batch("D20", self.today + timedelta(days=20), "1")
        self.add_batch("D50", self.today + timedelta(days=50), "1")
        self.add_batch("D200", self.today + timedelta(days=200), "1")
        self.add_batch("GONE", self.today - timedelta(days=5), "1")
        self.login_retailer_a()

        def numbers(params):
            response = self.client.get(reverse("near_expiry"), params)
            return {batch.batch_number for batch in response.context["batches"]}

        self.assertEqual(numbers({"days": "30"}), {"D20"})
        self.assertEqual(numbers({"days": "60"}), {"D20", "D50"})
        self.assertEqual(numbers({}), {"D20", "D50"})               # default 90
        self.assertEqual(numbers({"days": "expired"}), {"GONE"})

    def test_empty_batches_are_not_listed(self):
        batch = self.add_batch("D20", self.today + timedelta(days=20), "1")
        ProductBatch.objects.filter(pk=batch.pk).update(quantity=0)
        self.login_retailer_a()

        self.assertEqual(self.client.get(reverse("near_expiry")).context["total_count"], 0)

    def test_dashboard_card_and_menu_for_pharmacy(self):
        self.add_batch("D20", self.today + timedelta(days=20), "1")
        self.add_batch("GONE", self.today - timedelta(days=5), "1")
        self.login_retailer_a()

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["expiry"], {"near_expiry_count": 1, "expired_count": 1})
        self.assertContains(response, reverse("near_expiry"))
        self.assertContains(response, reverse("h1_register"))

    def test_admin_sees_pharmacy_batches(self):
        self.add_batch("D20", self.today + timedelta(days=20), "1")
        self.login_admin()

        response = self.client.get(reverse("near_expiry"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shop A")


class PharmacyRegistrationTests(BaseTestData):

    def payload(self, **overrides):
        data = {
            "username": "medshop", "password": "Str0ng!Passw0rd", "email": "med@example.com",
            "shop_name": "Med Shop", "owner_name": "Owner", "mobile": "9444444444",
            "address": "1 Road", "city": "Pune", "state": "Maharashtra", "pincode": "411001",
            "shop_type": "pharmacy", "drug_licence_number": "20B-1", "drug_licence_number_2": "21B-2",
        }
        data.update(overrides)
        return data

    def test_pharmacy_licence_numbers_are_saved(self):
        self.login_admin()

        self.client.post(reverse("retailer_register"), self.payload())

        shop = Retailer.objects.get(shop_name="Med Shop")
        self.assertEqual((shop.drug_licence_number, shop.drug_licence_number_2), ("20B-1", "21B-2"))

    def test_licence_numbers_ignored_for_other_shop_types(self):
        self.login_admin()

        self.client.post(reverse("retailer_register"), self.payload(shop_type="general"))

        shop = Retailer.objects.get(shop_name="Med Shop")
        self.assertEqual((shop.drug_licence_number, shop.drug_licence_number_2), ("", ""))


class BatchServiceTests(TestCase):

    def test_parse_expiry_formats(self):
        self.assertEqual(batch_stock.parse_expiry("2026-02"), date(2026, 2, 28))
        self.assertEqual(batch_stock.parse_expiry("2028-02"), date(2028, 2, 29))
        self.assertEqual(batch_stock.parse_expiry("2026-05-10"), date(2026, 5, 10))
        for bad in ("", "02/2026", "2026-13"):
            with self.subTest(value=bad):
                with self.assertRaises(Exception):
                    batch_stock.parse_expiry(bad)

    def test_split_amount_keeps_the_total(self):
        allocations = [(None, Decimal("1")), (None, Decimal("1")), (None, Decimal("1"))]

        parts = batch_stock.split_amount(Decimal("1.00"), allocations, Decimal("3"))

        self.assertEqual(sum(parts), Decimal("1.00"))
        self.assertEqual(parts, [Decimal("0.33"), Decimal("0.33"), Decimal("0.34")])


# =====================================================================
# PHASE 6: HARDWARE (price levels, specification, quotations)
# Switched on by features (price_levels, product_specification,
# quotations), never by shop type.
# =====================================================================

from .models import CustomerLedger, Quotation, QuotationItem


class HardwareBase(BaseTestData):
    """Shop B is a hardware shop; Shop A stays a general store."""

    def setUp(self):
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="hardware")
        self.retailer_b.refresh_from_db()
        Product.objects.filter(pk=self.product_b.pk).update(
            wholesale_price=Decimal("11.00"), specification="1.5 sq mm, 90 m",
        )
        self.product_b.refresh_from_db()
        self.retail_b = Customer.objects.create(retailer=self.retailer_b, customer_name="Walk-in", mobile="9000000801")
        self.wholesale_b = Customer.objects.create(
            retailer=self.retailer_b, customer_name="Builder Co", mobile="9000000802",
            price_level=Customer.PRICE_LEVEL_WHOLESALE,
        )
        self.customer_a = Customer.objects.create(retailer=self.retailer_a, customer_name="Asha", mobile="9000000803")

    def sell(self, customer, product, qty="2", **extra):
        data = {
            "customer": customer.id,
            "items[1][product]": product.id, "items[1][unit]": product.unit_id,
            "items[1][quantity]": qty, "items[1][discount]": "0",
            "payment_type": "Credit", "paid_amount": "0", "action": "save",
        }
        data.update(extra)
        return self.client.post(reverse("sale_create"), data)

    def quote(self, customer, product=None, qty="3", price="", discount="0", **extra):
        product = product or self.product_b
        data = {
            "customer": customer.id, "valid_until": "",
            "items[1][product]": product.id, "items[1][quantity]": qty,
            "items[1][selling_price]": price, "items[1][discount]": discount,
            "action": "save",
        }
        data.update(extra)
        return self.client.post(reverse("quotation_create"), data)


class PriceLevelTests(HardwareBase):

    def test_wholesale_customer_pays_wholesale_price(self):
        self.login_retailer_b()

        self.sell(self.wholesale_b, self.product_b)

        self.assertEqual(SaleItem.objects.get().selling_price, Decimal("11.00"))

    def test_retail_customer_pays_selling_price(self):
        self.login_retailer_b()

        self.sell(self.retail_b, self.product_b)

        self.assertEqual(SaleItem.objects.get().selling_price, Decimal("12.00"))

    def test_product_without_wholesale_price_uses_selling_price(self):
        Product.objects.filter(pk=self.product_b.pk).update(wholesale_price=None)
        self.login_retailer_b()

        self.sell(self.wholesale_b, self.product_b)

        self.assertEqual(SaleItem.objects.get().selling_price, Decimal("12.00"))

    def test_price_levels_off_for_general_shop(self):
        Customer.objects.filter(pk=self.customer_a.pk).update(price_level=Customer.PRICE_LEVEL_WHOLESALE)
        Product.objects.filter(pk=self.product_a.pk).update(wholesale_price=Decimal("11.00"))
        self.customer_a.refresh_from_db()
        self.login_retailer_a()

        self.sell(self.customer_a, self.product_a)

        self.assertEqual(SaleItem.objects.get().selling_price, Decimal("12.00"))

    def test_price_for_helper(self):
        hardware = get_features(self.retailer_b)
        general = get_features(self.retailer_a)
        self.assertEqual(self.product_b.price_for(self.wholesale_b, hardware), Decimal("11.00"))
        self.assertEqual(self.product_b.price_for(self.retail_b, hardware), Decimal("12.00"))
        self.assertEqual(self.product_b.price_for(self.wholesale_b, general), Decimal("12.00"))
        self.assertEqual(self.product_b.price_for(None, hardware), Decimal("12.00"))

    def test_new_customer_price_level(self):
        self.login_retailer_b()
        url = reverse("create_customer_ajax")

        response = self.client.post(url, {"customer_name": "Dealer", "mobile": "9000000810", "price_level": "wholesale"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Customer.objects.get(mobile="9000000810").price_level, "wholesale")

        self.assertEqual(self.client.post(url, {"customer_name": "X", "mobile": "9000000811", "price_level": "vip"}).status_code, 400)

        self.login_retailer_a()                                # general: ignored
        self.client.post(url, {"customer_name": "Y", "mobile": "9000000812", "price_level": "wholesale"})
        self.assertEqual(Customer.objects.get(mobile="9000000812").price_level, "retail")

    def test_change_price_level_on_account_page(self):
        self.login_retailer_b()
        url = reverse("customer_set_price_level", args=[self.retail_b.id])

        self.client.post(url, {"price_level": "wholesale"})
        self.retail_b.refresh_from_db()
        self.assertEqual(self.retail_b.price_level, "wholesale")

        page = self.client.get(reverse("customer_account", args=[self.retail_b.id]))
        self.assertContains(page, 'name="price_level"')

    def test_price_level_not_available_for_general_shop(self):
        self.login_retailer_a()

        self.client.post(reverse("customer_set_price_level", args=[self.customer_a.id]), {"price_level": "wholesale"})

        self.customer_a.refresh_from_db()
        self.assertEqual(self.customer_a.price_level, "retail")
        self.assertNotContains(self.client.get(reverse("customer_account", args=[self.customer_a.id])), 'name="price_level"')

    def test_other_shop_customer_cannot_be_changed(self):
        self.login_retailer_a()

        response = self.client.post(reverse("customer_set_price_level", args=[self.retail_b.id]), {"price_level": "wholesale"})

        self.assertEqual(response.status_code, 404)


class HardwareProductTests(HardwareBase):

    def post_product(self, shop, **extra):
        return self.client.post(reverse("add_product"), product_payload(shop, **extra),
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_hardware_product_saves_wholesale_and_specification(self):
        self.login_retailer_b()

        response = self.post_product(self.retailer_b, product_name="Wire", wholesale_price="11.50",
                                     specification="2.5 sq mm")

        self.assertEqual(response.status_code, 201)
        wire = Product.objects.get(product_name="Wire")
        self.assertEqual((wire.wholesale_price, wire.specification), (Decimal("11.50"), "2.5 sq mm"))

    def test_general_product_ignores_hardware_fields(self):
        self.login_retailer_a()

        self.post_product(self.retailer_a, product_name="Rice", wholesale_price="11", specification="5 kg")

        rice = Product.objects.get(product_name="Rice")
        self.assertEqual((rice.wholesale_price, rice.specification), (None, ""))

    def test_wholesale_price_rules(self):
        self.login_retailer_b()

        self.assertEqual(self.post_product(self.retailer_b, product_name="W1", wholesale_price="13").status_code, 400)   # > selling 12
        self.assertEqual(self.post_product(self.retailer_b, product_name="W2", wholesale_price="0").status_code, 400)
        self.assertEqual(self.post_product(self.retailer_b, product_name="W3", wholesale_price="abc").status_code, 400)
        response = self.post_product(self.retailer_b, product_name="W4", wholesale_price="9")                            # below cost 10
        self.assertEqual(response.status_code, 201)
        self.assertIn("below the purchase price", response.json()["warning"])

    def test_update_product_hardware_fields(self):
        self.login_retailer_b()
        data = {
            "product_id": self.product_b.id, "purchase_price": "10", "selling_price": "12", "mrp": "15",
            "gst": "5", "current_stock": "10", "minimum_stock": "0", "is_active": "true",
            "wholesale_price": "10.50", "specification": "4 sq mm",
        }

        self.assertEqual(self.client.post(reverse("update_product"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 200)
        self.product_b.refresh_from_db()
        self.assertEqual((self.product_b.wholesale_price, self.product_b.specification), (Decimal("10.50"), "4 sq mm"))

        data["wholesale_price"] = ""                                       # cleared
        self.client.post(reverse("update_product"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.product_b.refresh_from_db()
        self.assertIsNone(self.product_b.wholesale_price)

    def test_specification_shown_on_sale_invoice(self):
        self.login_retailer_b()
        self.sell(self.retail_b, self.product_b)

        response = self.client.get(reverse("sale_invoice", args=[Sale.objects.get().id]))

        self.assertContains(response, "1.5 sq mm, 90 m")

    def test_forms_get_hardware_rules(self):
        self.login_retailer_b()

        rules = self.client.get(reverse("add_product")).context["shop_rules"][str(self.retailer_b.id)]

        self.assertTrue(rules["price_levels"])
        self.assertTrue(rules["product_specification"])


class QuotationTests(HardwareBase):

    def test_create_quotation_numbers_and_totals(self):
        self.login_retailer_b()

        self.quote(self.retail_b, qty="3", price="12", discount="1")
        self.quote(self.retail_b, qty="1")

        first, second = Quotation.objects.order_by("id")
        year = date.today().year
        self.assertEqual(first.quotation_number, f"QT-{year}-000001")
        self.assertEqual(second.quotation_number, f"QT-{year}-000002")
        self.assertEqual(first.status, Quotation.STATUS_OPEN)
        item = first.items.get()
        self.assertEqual((item.quantity, item.selling_price, item.discount, item.gst), (Decimal("3"), Decimal("12"), Decimal("1"), Decimal("5")))
        self.assertEqual(item.amount, Decimal("36.75"))               # (36 - 1) * 1.05
        self.assertEqual((first.subtotal, first.discount, first.grand_total), (Decimal("36"), Decimal("1"), Decimal("36.75")))

    def test_quotation_does_not_touch_stock_or_account(self):
        self.login_retailer_b()

        self.quote(self.retail_b, qty="5")

        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, Decimal("10"))
        self.assertFalse(Sale.objects.exists())
        self.assertFalse(CustomerLedger.objects.filter(customer=self.retail_b).exists())

    def test_numbers_are_per_shop(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="hardware")
        self.login_retailer_b()
        self.quote(self.retail_b)
        self.login_retailer_a()
        self.quote(self.customer_a, product=self.product_a)

        numbers = set(Quotation.objects.values_list("quotation_number", flat=True))
        self.assertEqual(numbers, {f"QT-{date.today().year}-000001"})

    def test_blank_price_uses_customer_level(self):
        self.login_retailer_b()

        self.quote(self.wholesale_b, price="")

        self.assertEqual(QuotationItem.objects.get().selling_price, Decimal("11.00"))

    def test_invalid_quotations_are_rejected(self):
        self.login_retailer_b()

        self.quote(self.retail_b, price="16")                         # above MRP 15
        self.quote(self.customer_a)                                   # other shop's customer
        self.quote(self.retail_b, product=self.product_a)             # other shop's product
        self.quote(self.retail_b, qty="0")
        self.quote(self.retail_b, discount="100")
        self.quote(self.retail_b, valid_until="2000-01-01")

        self.assertFalse(Quotation.objects.exists())

    def test_hardware_allows_quote_below_cost(self):
        self.login_retailer_b()

        self.quote(self.retail_b, price="9")                          # cost 10

        self.assertEqual(Quotation.objects.count(), 1)

    def test_general_shop_has_no_quotations(self):
        self.login_retailer_a()

        self.assertRedirects(self.client.get(reverse("quotation_list")), reverse("dashboard"), fetch_redirect_response=False)
        self.quote(self.customer_a, product=self.product_a)
        self.assertFalse(Quotation.objects.exists())
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("quotation_list"))

    def test_menu_shows_quotations_for_hardware(self):
        self.login_retailer_b()

        self.assertContains(self.client.get(reverse("dashboard")), reverse("quotation_list"))

    def test_quotations_are_scoped_to_the_shop(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="hardware")
        self.login_retailer_b()
        self.quote(self.retail_b)
        quotation = Quotation.objects.get()
        self.client.get(reverse("quotation_list"))   # show (and clear) the "created" message

        self.login_retailer_a()
        self.assertEqual(self.client.get(reverse("quotation_detail", args=[quotation.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("quotation_print", args=[quotation.id])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("quotation_list")), quotation.quotation_number)

        self.login_admin()
        self.assertContains(self.client.get(reverse("quotation_list")), quotation.quotation_number)

    def test_admin_creates_for_chosen_shop(self):
        self.login_admin()

        self.quote(self.retail_b, retailer=self.retailer_b.id)
        self.quote(self.customer_a, product=self.product_a, retailer=self.retailer_a.id)   # general shop: refused

        self.assertEqual(list(Quotation.objects.values_list("retailer_id", flat=True)), [self.retailer_b.id])

    def test_detail_and_print_pages(self):
        self.login_retailer_b()
        self.quote(self.retail_b)
        quotation = Quotation.objects.get()

        detail = self.client.get(reverse("quotation_detail", args=[quotation.id]))
        printed = self.client.get(reverse("quotation_print", args=[quotation.id]))

        self.assertContains(detail, quotation.quotation_number)
        self.assertContains(detail, f"?quotation={quotation.id}")
        self.assertContains(printed, "QUOTATION")
        self.assertContains(printed, "1.5 sq mm, 90 m")

    def test_cancel(self):
        self.login_retailer_b()
        self.quote(self.retail_b)
        quotation = Quotation.objects.get()

        self.client.post(reverse("quotation_cancel", args=[quotation.id]))

        quotation.refresh_from_db()
        self.assertEqual(quotation.status, Quotation.STATUS_CANCELLED)


class QuotationConversionTests(HardwareBase):

    def setUp(self):
        super().setUp()
        self.login_retailer_b()
        self.quote(self.retail_b, qty="4", price="11.50", discount="2")
        self.quotation = Quotation.objects.get()

    def convert(self, customer=None, qty="4", **extra):
        return self.sell(customer or self.retail_b, self.product_b, qty=qty,
                         quotation=self.quotation.id, **{"items[1][discount]": "2"}, **extra)

    def test_sale_page_is_prefilled(self):
        prefill = self.client.get(reverse("sale_create"), {"quotation": self.quotation.id}).context["quotation_prefill"]

        self.assertEqual(prefill["customer_id"], self.retail_b.id)
        self.assertEqual(prefill["items"][0]["product_id"], self.product_b.id)
        self.assertEqual(prefill["items"][0]["quantity"], "4")

    def test_conversion_uses_quoted_price_and_links_sale(self):
        self.convert()

        sale = Sale.objects.get()
        item = SaleItem.objects.get()
        self.assertEqual(item.selling_price, Decimal("11.50"))        # quoted, not 12
        self.assertEqual(item.discount, Decimal("2.00"))
        self.quotation.refresh_from_db()
        self.assertEqual((self.quotation.status, self.quotation.converted_sale), (Quotation.STATUS_CONVERTED, sale))
        self.product_b.refresh_from_db()
        self.assertEqual(self.product_b.current_stock, Decimal("6"))  # normal sale: stock taken
        self.assertContains(self.client.get(reverse("sale_detail", args=[sale.id])), self.quotation.quotation_number)

    def test_cannot_convert_twice(self):
        self.convert()
        self.convert()

        self.assertEqual(Sale.objects.count(), 1)

    def test_customer_must_match(self):
        self.convert(customer=self.wholesale_b)

        self.assertFalse(Sale.objects.exists())
        self.quotation.refresh_from_db()
        self.assertEqual(self.quotation.status, Quotation.STATUS_OPEN)

    def test_cancelled_quotation_cannot_be_converted(self):
        self.client.post(reverse("quotation_cancel", args=[self.quotation.id]))

        self.convert()

        self.assertFalse(Sale.objects.exists())

    def test_failed_sale_leaves_quotation_open(self):
        self.convert(qty="50")                                         # more than stock

        self.assertFalse(Sale.objects.exists())
        self.quotation.refresh_from_db()
        self.assertEqual(self.quotation.status, Quotation.STATUS_OPEN)

    def test_other_shop_cannot_convert(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="hardware")
        self.login_retailer_a()

        self.sell(self.customer_a, self.product_a, quotation=self.quotation.id)
        self.assertIsNone(self.client.get(reverse("sale_create"), {"quotation": self.quotation.id}).context["quotation_prefill"])

        self.assertFalse(Sale.objects.exists())

    def test_other_products_on_the_sale_use_normal_prices(self):
        other = Product.objects.create(
            retailer=self.retailer_b, category=self.product_b.category, brand=self.product_b.brand,
            unit=self.unit, product_name="Switch", hsn_code="8536", purchase_price=Decimal("10"),
            selling_price=Decimal("12"), wholesale_price=Decimal("11"), current_stock=Decimal("5"), gst=Decimal("5"),
        )
        self.sell(self.retail_b, self.product_b, qty="4", quotation=self.quotation.id, **{
            "items[1][discount]": "2",
            "items[2][product]": other.id, "items[2][unit]": other.unit_id,
            "items[2][quantity]": "1", "items[2][discount]": "0",
        })

        prices = dict(SaleItem.objects.values_list("product__product_name", "selling_price"))
        self.assertEqual(prices, {"Ibuprofen": Decimal("11.50"), "Switch": Decimal("12.00")})


# =====================================================================
# PHASE 7: RETURNS (credit / debit notes) + GST SPLIT (CGST+SGST / IGST)
# =====================================================================

from .models import PurchaseReturn, SaleReturn
from .states import is_inter_state, rate_wise_summary, split_amount, state_key, tax_fields
from . import accounts as accounts_module


class StateAndSplitTests(TestCase):

    def test_state_spellings(self):
        for value in ("maharashtra", "Maharashtra", " MAHA RASHTRA ", "maharashtra."):
            with self.subTest(value=value):
                self.assertEqual(state_key(value), "maharashtra")
        self.assertEqual(state_key("Uttar Pradesh"), "up")
        self.assertEqual(state_key("up"), "up")
        self.assertEqual(state_key("Orissa"), "odisha")
        self.assertEqual(state_key("Atlantis"), "")

    def test_inter_state(self):
        self.assertFalse(is_inter_state("maharashtra", "Maharashtra"))
        self.assertTrue(is_inter_state("maharashtra", "Gujarat"))
        self.assertFalse(is_inter_state("maharashtra", ""))           # unknown -> same state
        self.assertFalse(is_inter_state("", "Gujarat"))

    def test_split_always_adds_up(self):
        for amount in ("1.25", "0.01", "100.00", "7.77"):
            with self.subTest(amount=amount):
                parts = split_amount(Decimal(amount), "intra")
                self.assertEqual(parts["cgst"] + parts["sgst"], Decimal(amount))
                self.assertEqual(parts["igst"], Decimal("0.00"))
        self.assertEqual(split_amount(Decimal("5"), "inter")["igst"], Decimal("5.00"))
        self.assertEqual(split_amount(Decimal("5"), ""), {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("0.00")})

    def test_split_off_when_feature_off(self):
        from .shop_types import Features
        off = Features({})
        self.assertEqual(tax_fields(off, "maharashtra", "gujarat", Decimal("10"))["tax_type"], "")

    def test_rate_wise_summary(self):
        rows = rate_wise_summary([(Decimal("5"), Decimal("100")), (Decimal("18"), Decimal("50")), (Decimal("5"), Decimal("20"))], "intra")
        self.assertEqual([(r["rate"], r["taxable"], r["tax"]) for r in rows],
                         [(Decimal("5"), Decimal("120.00"), Decimal("6.00")), (Decimal("18"), Decimal("50.00"), Decimal("9.00"))])
        self.assertEqual(rows[1]["cgst"] + rows[1]["sgst"], Decimal("9.00"))


class TaxSplitFlowTests(BaseTestData):

    def setUp(self):
        self.local = Customer.objects.create(retailer=self.retailer_a, customer_name="Local", mobile="9000000901")
        self.outside = Customer.objects.create(retailer=self.retailer_a, customer_name="Outside", mobile="9000000902", state="gujarat")

    def sell(self, customer, qty="2"):
        return self.client.post(reverse("sale_create"), {
            "customer": customer.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": qty, "items[1][discount]": "0",
            "payment_type": "Credit", "paid_amount": "0", "action": "save",
        })

    def test_same_state_customer_gets_cgst_sgst(self):
        self.login_retailer_a()
        self.sell(self.local)

        sale = Sale.objects.get()
        self.assertEqual((sale.tax_type, sale.cgst, sale.sgst, sale.igst),
                         ("intra", Decimal("0.60"), Decimal("0.60"), Decimal("0.00")))
        invoice = self.client.get(reverse("sale_invoice", args=[sale.id]))
        self.assertContains(invoice, "CGST")
        self.assertNotContains(invoice, "IGST")

    def test_other_state_customer_gets_igst(self):
        self.login_retailer_a()
        self.sell(self.outside)

        sale = Sale.objects.get()
        self.assertEqual((sale.tax_type, sale.igst, sale.cgst), ("inter", Decimal("1.20"), Decimal("0.00")))
        invoice = self.client.get(reverse("sale_invoice", args=[sale.id]))
        self.assertContains(invoice, "IGST")
        self.assertContains(invoice, "Gujarat")

    def test_purchase_split_follows_supplier_state(self):
        far = self._create_supplier(self.retailer_a, "Far Traders", state="Karnataka")
        self.login_retailer_a()

        for supplier, bill in ((self.supplier_a1, "LOC-1"), (far, "FAR-1")):
            self.client.post(reverse("add_new_order"), {
                "supplier": supplier.id, "bill_number": bill, "bill_date": date.today().isoformat(),
                "payment_terms": "net15", "item_name_1": "Paracetamol", "item_unit_1": self.unit.id,
                "item_qty_1": "10", "item_free_qty_1": "0", "item_price_1": "10",
                "item_tax_1": "5", "item_mrp_1": "15", "paid_amount": "0",
            })

        local = Purchase.objects.get(bill_number="LOC-1")
        far_bill = Purchase.objects.get(bill_number="FAR-1")
        self.assertEqual((local.tax_type, local.cgst, local.sgst), ("intra", Decimal("2.50"), Decimal("2.50")))
        self.assertEqual((far_bill.tax_type, far_bill.igst), ("inter", Decimal("5.00")))
        self.assertContains(self.client.get(reverse("purchase_invoice", args=[far_bill.id])), "IGST")

    def test_new_customer_state(self):
        self.login_retailer_a()
        url = reverse("create_customer_ajax")

        self.assertEqual(self.client.post(url, {"customer_name": "G", "mobile": "9000000910", "state": "Gujarat"}).status_code, 201)
        self.assertEqual(Customer.objects.get(mobile="9000000910").state, "gujarat")
        self.assertEqual(self.client.post(url, {"customer_name": "X", "mobile": "9000000911", "state": "Atlantis"}).status_code, 400)

    def test_change_customer_state(self):
        self.login_retailer_a()

        self.client.post(reverse("customer_set_state", args=[self.local.id]), {"state": "karnataka"})
        self.local.refresh_from_db()
        self.assertEqual(self.local.state, "karnataka")

        self.client.post(reverse("customer_set_state", args=[self.local.id]), {"state": ""})
        self.local.refresh_from_db()
        self.assertEqual(self.local.state, "")

        self.login_retailer_b()
        self.assertEqual(self.client.post(reverse("customer_set_state", args=[self.local.id]), {"state": "goa"}).status_code, 404)


class SaleReturnTests(BaseTestData):

    def setUp(self):
        self.customer = Customer.objects.create(retailer=self.retailer_a, customer_name="Ravi", mobile="9000000920")
        self.login_retailer_a()

    def sell(self, qty="4", paid="0", payment_type="Credit", discount="0"):
        self.client.post(reverse("sale_create"), {
            "customer": self.customer.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": qty, "items[1][discount]": discount,
            "payment_type": payment_type, "paid_amount": paid, "action": "save",
        })
        return Sale.objects.latest("id")

    def give_back(self, sale, qty, refund_mode="account", reason="Damaged"):
        item = sale.items.get()
        return self.client.post(reverse("sale_return_create", args=[sale.id]), {
            f"return_qty_{item.id}": qty, "reason": reason, "refund_mode": refund_mode,
        })

    def balance(self):
        return accounts_module.customer_balance(self.customer)

    def test_return_on_unpaid_bill_reduces_due_and_restores_stock(self):
        sale = self.sell("4")                                         # 4 x 12 + 5% = 50.40
        response = self.give_back(sale, "1")

        note = SaleReturn.objects.get()
        self.assertRedirects(response, reverse("credit_note", args=[note.id]), fetch_redirect_response=False)
        self.assertEqual(note.credit_note_number, f"CN-{date.today().year}-000001")
        self.assertEqual((note.total, note.applied_to_bill, note.refund_amount), (Decimal("12.60"), Decimal("12.60"), Decimal("0.00")))
        self.assertEqual((note.tax_type, note.cgst + note.sgst), ("intra", Decimal("0.60")))
        sale.refresh_from_db()
        self.assertEqual((sale.returned_amount, sale.due_amount), (Decimal("12.60"), Decimal("37.80")))
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("7"))   # 10 - 4 + 1
        self.assertEqual(self.balance(), Decimal("37.80"))
        self.assertTrue(CustomerLedger.objects.filter(sale_return=note, credit=Decimal("12.60")).exists())

    def test_paid_bill_cash_refund(self):
        sale = self.sell("2", paid="25.20", payment_type="Cash")
        self.give_back(sale, "1", refund_mode="cash")

        note = SaleReturn.objects.get()
        self.assertEqual((note.applied_to_bill, note.refund_amount, note.kept_on_account), (Decimal("0.00"), Decimal("12.60"), Decimal("0.00")))
        self.assertEqual(self.balance(), Decimal("0.00"))
        sale.refresh_from_db()
        self.assertEqual(sale.due_amount, Decimal("0.00"))

    def test_paid_bill_credit_kept_as_advance(self):
        sale = self.sell("2", paid="25.20", payment_type="Cash")
        self.give_back(sale, "1", refund_mode="account")

        note = SaleReturn.objects.get()
        self.assertEqual(note.kept_on_account, Decimal("12.60"))
        self.assertEqual(self.balance(), Decimal("-12.60"))          # advance for the next bill

    def test_partly_paid_bill_reduces_due_then_refunds(self):
        sale = self.sell("2", paid="20.00", payment_type="Cash")       # due 5.20
        self.give_back(sale, "1", refund_mode="cash")

        note = SaleReturn.objects.get()
        self.assertEqual((note.applied_to_bill, note.refund_amount), (Decimal("5.20"), Decimal("7.40")))
        sale.refresh_from_db()
        self.assertEqual((sale.due_amount, sale.payment_status), (Decimal("0.00"), "Paid"))
        self.assertEqual(self.balance(), Decimal("0.00"))

    def test_cannot_return_more_than_sold(self):
        sale = self.sell("2")

        self.give_back(sale, "3")
        self.assertFalse(SaleReturn.objects.exists())

        self.give_back(sale, "2")
        self.give_back(sale, "1")                                      # nothing left
        self.assertEqual(SaleReturn.objects.count(), 1)

    def test_nothing_entered_is_rejected(self):
        sale = self.sell("2")

        self.give_back(sale, "0")

        self.assertFalse(SaleReturn.objects.exists())
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("8"))

    def test_returning_everything_matches_the_line_exactly(self):
        sale = self.sell("3", discount="1.00")                         # (36 - 1) x 1.05 = 36.75
        item = sale.items.get()

        self.give_back(sale, "1")
        self.give_back(sale, "2")

        returned = SaleReturn.objects.all()
        self.assertEqual(sum(note.total for note in returned), item.amount)
        self.assertEqual(sum(note.discount for note in returned), item.discount)
        sale.refresh_from_db()
        self.assertEqual(sale.due_amount, Decimal("0.00"))
        self.assertEqual(self.balance(), Decimal("0.00"))

    def test_fractional_return_follows_the_shop(self):
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="stationery")
        sale = self.sell("2")

        self.give_back(sale, "0.5")

        self.assertFalse(SaleReturn.objects.exists())

    def test_other_shop_cannot_return(self):
        sale = self.sell("2")
        self.login_retailer_b()

        self.assertEqual(self.client.get(reverse("sale_return_create", args=[sale.id])).status_code, 404)
        self.give_back(sale, "1")
        self.assertFalse(SaleReturn.objects.exists())

    def test_pages_show_the_return(self):
        sale = self.sell("2")
        self.give_back(sale, "1")
        note = SaleReturn.objects.get()

        self.assertContains(self.client.get(reverse("credit_note", args=[note.id])), "CREDIT NOTE")
        self.assertContains(self.client.get(reverse("sale_detail", args=[sale.id])), note.credit_note_number)
        self.assertContains(self.client.get(reverse("returns_list")), note.credit_note_number)
        self.assertContains(self.client.get(reverse("customer_account", args=[self.customer.id])), note.credit_note_number)

    def test_batch_line_goes_back_into_its_batch(self):
        from . import batches as batch_stock
        from django.db import transaction as tx
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="pharmacy")
        Product.objects.filter(pk=self.product_a.pk).update(current_stock=0)
        with tx.atomic():
            locked = Product.objects.select_for_update().get(pk=self.product_a.pk)
            batch = batch_stock.receive_into_batch(locked, batch_number="B1", expiry_date=date.today() + timedelta(days=90), quantity=Decimal("5"))
        sale = self.sell("3")

        self.give_back(sale, "2")

        batch.refresh_from_db()
        self.assertEqual(batch.quantity, Decimal("4"))
        self.assertEqual(SaleReturn.objects.get().items.get().batch, batch)
        self.product_a.refresh_from_db()
        self.assertTrue(batch_stock.batches_in_sync(self.product_a))


class PurchaseReturnTests(BaseTestData):

    def setUp(self):
        self.login_retailer_a()

    def buy(self, bill="PR-1", qty="10", price="10", paid="0", discount="0", supplier=None, **extra):
        data = {
            "supplier": (supplier or self.supplier_a1).id, "bill_number": bill, "bill_date": timezone.localdate().isoformat(),
            "payment_terms": "net15", "item_name_1": "Paracetamol", "item_unit_1": self.unit.id,
            "item_qty_1": qty, "item_free_qty_1": "0", "item_price_1": price,
            "item_tax_1": "5", "item_mrp_1": "15", "paid_amount": paid, "discount": discount,
        }
        if Decimal(paid) > 0:
            data["payment_type"] = "Cash"
        data.update(extra)
        self.client.post(reverse("add_new_order"), data)
        return Purchase.objects.get(bill_number=bill)

    def send_back(self, purchase, qty, reason="Damaged"):
        item = purchase.items.get()
        return self.client.post(reverse("purchase_return_create", args=[purchase.id]), {
            f"return_qty_{item.id}": qty, "reason": reason,
        })

    def test_return_on_unpaid_bill_reduces_due_and_stock(self):
        purchase = self.buy()                                          # 100 + 5 = 105
        response = self.send_back(purchase, "4")

        note = PurchaseReturn.objects.get()
        self.assertRedirects(response, reverse("debit_note", args=[note.id]), fetch_redirect_response=False)
        self.assertEqual(note.debit_note_number, f"DN-{date.today().year}-000001")
        self.assertEqual((note.total, note.applied_to_bill, note.refund_amount), (Decimal("42.00"), Decimal("42.00"), Decimal("0.00")))
        purchase.refresh_from_db()
        self.assertEqual((purchase.returned_amount, purchase.due_amount), (Decimal("42.00"), Decimal("63.00")))
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("16"))  # 10 + 10 - 4
        account = accounts_module.supplier_account(self.supplier_a1)
        self.assertEqual(account["due"], Decimal("63.00"))
        statement = accounts_module.supplier_statement(self.supplier_a1)
        self.assertEqual(statement[-1]["balance"], Decimal("63.00"))
        self.assertEqual(statement[-1]["kind"], "debit_note")

    def test_paid_bill_return_is_a_refund_from_supplier(self):
        purchase = self.buy(paid="105")
        self.send_back(purchase, "2")

        note = PurchaseReturn.objects.get()
        self.assertEqual((note.applied_to_bill, note.refund_amount), (Decimal("0.00"), Decimal("21.00")))
        statement = accounts_module.supplier_statement(self.supplier_a1)
        self.assertEqual(statement[-1]["balance"], Decimal("0.00"))    # note and refund cancel out

    def test_bill_discount_is_shared(self):
        purchase = self.buy(discount="10")                             # 100 - 10 + 5 = 95
        self.send_back(purchase, "5")

        note = PurchaseReturn.objects.get()
        self.assertEqual((note.subtotal, note.discount, note.gst, note.total),
                         (Decimal("50.00"), Decimal("5.00"), Decimal("2.50"), Decimal("47.50")))

    def test_cannot_return_more_than_bought_or_in_stock(self):
        purchase = self.buy()

        self.send_back(purchase, "11")
        self.assertFalse(PurchaseReturn.objects.exists())

        Product.objects.filter(pk=self.product_a.pk).update(current_stock=Decimal("3"))   # sold most of it
        self.send_back(purchase, "5")
        self.assertFalse(PurchaseReturn.objects.exists())

    def test_boxes_return_in_boxes(self):
        box = Unit.objects.create(name="Box", short_name="box")
        Product.objects.filter(pk=self.product_a.pk).update(purchase_unit=box, conversion_factor=Decimal("10"), selling_price=Decimal("12"))
        purchase = self.buy(qty="2", price="50", item_unit_1=box.id)    # +20 pc

        self.send_back(purchase, "1")                                  # 1 box = 10 pc

        item = PurchaseReturn.objects.get().items.get()
        self.assertEqual((item.quantity, item.base_quantity), (Decimal("1"), Decimal("10")))
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("20"))  # 10 + 20 - 10

    def test_batch_purchase_return_takes_from_its_batch(self):
        from . import batches as batch_stock
        Retailer.objects.filter(pk=self.retailer_a.pk).update(shop_type="pharmacy")
        Product.objects.filter(pk=self.product_a.pk).update(current_stock=0)
        purchase = self.buy(item_batch_1="B7", item_expiry_1="2099-01")

        self.send_back(purchase, "3")

        batch = ProductBatch.objects.get(batch_number="B7")
        self.assertEqual(batch.quantity, Decimal("7"))
        self.product_a.refresh_from_db()
        self.assertTrue(batch_stock.batches_in_sync(self.product_a))

    def test_inter_state_debit_note_uses_igst(self):
        far = self._create_supplier(self.retailer_a, "Far Traders", state="Karnataka")
        purchase = self.buy(supplier=far)

        self.send_back(purchase, "2")

        note = PurchaseReturn.objects.get()
        self.assertEqual((note.tax_type, note.igst), ("inter", Decimal("1.00")))
        self.assertContains(self.client.get(reverse("debit_note", args=[note.id])), "IGST")

    def test_other_shop_cannot_return(self):
        purchase = self.buy()
        self.login_retailer_b()

        self.assertEqual(self.client.get(reverse("purchase_return_create", args=[purchase.id])).status_code, 404)

    def test_pages_show_the_return(self):
        purchase = self.buy()
        self.send_back(purchase, "1")
        note = PurchaseReturn.objects.get()

        self.assertContains(self.client.get(reverse("purchase_detail", args=[purchase.id])), note.debit_note_number)
        self.assertContains(self.client.get(reverse("purchase_invoice", args=[purchase.id])), note.debit_note_number)
        self.assertContains(self.client.get(reverse("returns_list"), {"type": "purchase"}), note.debit_note_number)
        self.assertContains(self.client.get(reverse("supplier_account", args=[self.supplier_a1.id])), note.debit_note_number)


# =====================================================================
# FINAL CHECKLIST: demo shops + rules that must hold everywhere
# =====================================================================

import re as _re
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command

from .pharmacy_views import expiry_summary


class SeedDemoShopsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo_shops", stdout=StringIO())

    def demo(self, shop_type):
        return Retailer.objects.get(user__username=f"demo_{shop_type}")

    def test_one_demo_shop_per_type(self):
        types = set(Retailer.objects.filter(user__username__startswith="demo_").values_list("shop_type", flat=True))
        self.assertEqual(types, set(SHOP_TYPE_LABELS))

    def test_running_again_changes_nothing(self):
        before = (Retailer.objects.count(), Product.objects.count(), Customer.objects.count(),
                  ProductBatch.objects.count(), Quotation.objects.count())
        out = StringIO()

        call_command("seed_demo_shops", stdout=out)

        after = (Retailer.objects.count(), Product.objects.count(), Customer.objects.count(),
                 ProductBatch.objects.count(), Quotation.objects.count())
        self.assertEqual(before, after)
        self.assertIn("Skipped demo_pharmacy", out.getvalue())

    def test_short_password_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_shops", "--password", "short", stdout=StringIO())

    def test_demo_data_uses_each_shops_features(self):
        pharmacy, hardware, general = self.demo("pharmacy"), self.demo("hardware"), self.demo("general")

        # Pharmacy: stock = sum of batches, one near expiry, one expired, H1 drug, licence.
        from . import batches as batch_stock
        for product in pharmacy.products.all():
            self.assertTrue(batch_stock.batches_in_sync(product), product.product_name)
        # Expiring in 20 and 60 days (both inside 90), and one already expired.
        self.assertEqual(expiry_summary([pharmacy]), {"near_expiry_count": 2, "expired_count": 1})
        self.assertTrue(pharmacy.products.filter(schedule="H1").exists())
        self.assertTrue(pharmacy.drug_licence_number)

        # Hardware: wholesale prices, specification, wholesale customer, a quotation.
        self.assertTrue(hardware.products.exclude(wholesale_price=None).exists())
        self.assertTrue(hardware.products.exclude(specification="").exists())
        self.assertTrue(hardware.customers.filter(price_level="wholesale").exists())
        self.assertEqual(hardware.quotations.count(), 1)

        # Other shops: none of that.
        self.assertFalse(general.product_batches.exists())
        self.assertFalse(general.products.exclude(wholesale_price=None).exists())
        self.assertFalse(general.quotations.exists())
        self.assertTrue(general.products.filter(current_stock=Decimal("48.5")).exists())   # loose rice

    def test_every_demo_login_opens_the_main_pages(self):
        pages = ["dashboard", "product_list", "add_product", "low_stock_alert", "sale_create", "sales_list",
                 "add_new_order", "purchase_product_list", "supplier_list", "customer_list", "returns_list"]

        for shop_type in SHOP_TYPE_LABELS:
            self.client.force_login(self.demo(shop_type).user)
            for page in pages:
                with self.subTest(shop=shop_type, page=page):
                    self.assertEqual(self.client.get(reverse(page)).status_code, 200)

    def test_feature_pages_follow_the_features(self):
        pages = {"near_expiry": "expiry_tracking", "h1_register": "prescription_details", "quotation_list": "quotations"}

        for shop_type in SHOP_TYPE_LABELS:
            shop = self.demo(shop_type)
            features = get_features(shop)
            self.client.force_login(shop.user)
            dashboard = self.client.get(reverse("dashboard")).content.decode()

            for page, feature in pages.items():
                with self.subTest(shop=shop_type, page=page):
                    status = self.client.get(reverse(page)).status_code
                    self.assertEqual(status, 200 if getattr(features, feature) else 302)
                    self.assertEqual(reverse(page) in dashboard, getattr(features, feature))

    def test_sell_return_and_igst_in_every_shop(self):
        for shop_type in SHOP_TYPE_LABELS:
            shop = self.demo(shop_type)
            product = shop.products.order_by("id").first()
            customer = shop.customers.get(state="gujarat")
            stock_before = product.current_stock
            self.client.force_login(shop.user)

            with self.subTest(shop=shop_type):
                self.client.post(reverse("sale_create"), {
                    "customer": customer.id,
                    "items[1][product]": product.id, "items[1][unit]": product.unit_id,
                    "items[1][quantity]": "1", "items[1][discount]": "0",
                    "payment_type": "Credit", "paid_amount": "0", "action": "save",
                })
                sale = Sale.objects.get(retailer=shop)
                self.assertEqual(sale.tax_type, "inter")              # other state -> IGST
                self.assertEqual(sale.igst, sale.gst)

                item = sale.items.first()
                self.client.post(reverse("sale_return_create", args=[sale.id]), {
                    f"return_qty_{line.id}": line.quantity for line in sale.items.all()
                })
                product.refresh_from_db()
                self.assertEqual(product.current_stock, stock_before)  # stock back after full return
                sale.refresh_from_db()
                self.assertEqual(sale.due_amount, Decimal("0.00"))
                self.assertIsNotNone(item)

    def test_demo_quotation_converts_to_a_sale(self):
        hardware = self.demo("hardware")
        quotation = hardware.quotations.get()
        self.client.force_login(hardware.user)
        data = {
            "customer": quotation.customer_id, "quotation": quotation.id,
            "payment_type": "Credit", "paid_amount": "0", "action": "save",
        }
        for number, item in enumerate(quotation.items.all(), start=1):
            data.update({
                f"items[{number}][product]": item.product_id, f"items[{number}][unit]": item.unit_id,
                f"items[{number}][quantity]": str(item.quantity), f"items[{number}][discount]": "0",
            })

        self.client.post(reverse("sale_create"), data)

        quotation.refresh_from_db()
        self.assertEqual(quotation.status, Quotation.STATUS_CONVERTED)
        self.assertEqual(
            sorted(quotation.converted_sale.items.values_list("selling_price", flat=True)),
            sorted(quotation.items.values_list("selling_price", flat=True)),
        )

    def test_shops_cannot_see_each_other(self):
        pharmacy, hardware = self.demo("pharmacy"), self.demo("hardware")
        self.client.force_login(pharmacy.user)

        other_product = hardware.products.first()
        other_customer = hardware.customers.first()
        self.assertEqual(self.client.get(reverse("sale_product_data", args=[other_product.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("customer_account", args=[other_customer.id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("quotation_detail", args=[hardware.quotations.get().id])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("product_list")), other_product.product_name)


class CodeRulesTests(TestCase):
    """Rules from the brief that are easy to break later."""

    APP_DIR = Path(__file__).resolve().parent

    # Comparing a shop type to a literal ("pharmacy", ...) outside the
    # central feature map means code is asking for a shop type instead
    # of a feature.
    SHOP_TYPE_CHECK = _re.compile(
        r"""shop_type\s*(==|!=)\s*['"]|shop_type\s+(not\s+)?in\s*[\[\(]['"]|['"](general|stationery|cosmetics|pharmacy|hardware)['"]\s*(==|!=)\s*\w*shop_type"""
    )
    ALLOWED = {"shop_types.py", "tests.py"}

    def source_files(self):
        for path in self.APP_DIR.rglob("*"):
            if path.suffix not in (".py", ".html") or "migrations" in path.parts:
                continue
            if path.name in self.ALLOWED or "management" in path.parts:
                continue
            yield path

    def test_code_asks_for_features_not_shop_types(self):
        offenders = []

        for path in self.source_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.lstrip().startswith("#"):
                    continue          # old commented-out code
                if self.SHOP_TYPE_CHECK.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")

        self.assertEqual(offenders, [], "Use features (get_features / {{ features.x }}) instead:\n" + "\n".join(offenders))

    def test_app_label_and_models_kept(self):
        from django.apps import apps
        self.assertTrue(apps.is_installed("pharma_app"))
        for name in ("CustomUser", "Retailer", "Product", "Purchase", "PurchaseItem", "Sale", "SaleItem", "Customer"):
            with self.subTest(model=name):
                self.assertIsNotNone(apps.get_model("pharma_app", name))


# =====================================================================
# FIXES: supplier products, purchase page filters, customer form,
# payment-type link, admin feature pages
# =====================================================================

from .models import SupplierProduct


class SupplierProductTests(BaseTestData):

    def buy(self, supplier, product_name="Paracetamol", bill="SP-1", price="10"):
        return self.client.post(reverse("add_new_order"), {
            "supplier": supplier.id, "bill_number": bill, "bill_date": date.today().isoformat(),
            "payment_terms": "net15", "item_name_1": product_name, "item_unit_1": self.unit.id,
            "item_qty_1": "2", "item_free_qty_1": "0", "item_price_1": price,
            "item_tax_1": "5", "item_mrp_1": "15", "paid_amount": "0",
        })

    def test_saving_a_purchase_links_the_supplier_and_product(self):
        self.login_retailer_a()

        self.buy(self.supplier_a1, price="10")
        self.buy(self.supplier_a1, bill="SP-2", price="11")

        link = SupplierProduct.objects.get()
        self.assertEqual((link.supplier, link.product, link.retailer), (self.supplier_a1, self.product_a, self.retailer_a))
        self.assertEqual(link.last_purchase_price, Decimal("11.00"))

    def test_retailer_sees_only_own_links(self):
        SupplierProduct.objects.create(retailer=self.retailer_a, supplier=self.supplier_a1, product=self.product_a)
        SupplierProduct.objects.create(retailer=self.retailer_b, supplier=self.supplier_b1, product=self.product_b)
        self.login_retailer_a()

        response = self.client.get(reverse("supplier_product_list"))

        self.assertContains(response, "Alpha Traders")
        self.assertNotContains(response, "Beta Distributors")
        self.assertNotContains(response, "Ibuprofen")

    def test_admin_filters_by_shop_type_shop_and_supplier(self):
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="hardware")
        SupplierProduct.objects.create(retailer=self.retailer_a, supplier=self.supplier_a1, product=self.product_a)
        SupplierProduct.objects.create(retailer=self.retailer_b, supplier=self.supplier_b1, product=self.product_b)
        self.login_admin()
        url = reverse("supplier_product_list")

        def names(params):
            return {link.product.product_name for link in self.client.get(url, params).context["links"]}

        self.assertEqual(names({}), {"Paracetamol", "Ibuprofen"})
        self.assertEqual(names({"shop_type": "hardware"}), {"Ibuprofen"})
        self.assertEqual(names({"retailer": self.retailer_a.id}), {"Paracetamol"})
        self.assertEqual(names({"supplier": self.supplier_b1.id}), {"Ibuprofen"})

    def test_add_and_remove_by_hand(self):
        self.login_retailer_a()

        self.client.post(reverse("supplier_product_add"), {"supplier": self.supplier_a2.id, "product": [self.product_a.id]})
        link = SupplierProduct.objects.get(supplier=self.supplier_a2)

        self.client.post(reverse("supplier_product_remove", args=[link.id]))
        self.assertFalse(SupplierProduct.objects.exists())

    def test_cannot_link_other_shops_supplier_or_product(self):
        self.login_retailer_a()

        self.client.post(reverse("supplier_product_add"), {"supplier": self.supplier_b1.id, "product": [self.product_b.id]})
        self.client.post(reverse("supplier_product_add"), {"supplier": self.supplier_a1.id, "product": [self.product_b.id]})

        self.assertFalse(SupplierProduct.objects.exists())
        other = SupplierProduct.objects.create(retailer=self.retailer_b, supplier=self.supplier_b1, product=self.product_b)
        self.assertEqual(self.client.post(reverse("supplier_product_remove", args=[other.id])).status_code, 404)

    def test_purchase_page_gets_the_supplier_product_map(self):
        SupplierProduct.objects.create(retailer=self.retailer_a, supplier=self.supplier_a1, product=self.product_a)
        self.login_retailer_a()

        response = self.client.get(reverse("add_new_order"))

        self.assertEqual(response.context["supplier_products"][str(self.supplier_a1.id)], [self.product_a.id])
        self.assertEqual(response.context["supplier_products"][str(self.supplier_a2.id)], [])
        self.assertContains(response, 'id="supplierProducts"')

    def test_supplier_list_links_to_its_products(self):
        self.login_retailer_a()

        response = self.client.get(reverse("supplier_list"))

        self.assertContains(response, f"{reverse('supplier_product_list')}?supplier={self.supplier_a1.id}")


class SmallFixTests(BaseTestData):

    def test_add_customer_form_has_no_gst_number(self):
        self.login_retailer_a()

        page = self.client.get(reverse("sale_create"))
        self.assertNotContains(page, 'name="gst_number"')
        self.assertNotContains(page, 'id="custGST"')

        self.client.post(reverse("create_customer_ajax"), {
            "customer_name": "New", "mobile": "9000000990", "gst_number": "27AAAAA0000A1Z5",
        })
        self.assertIsNone(Customer.objects.get(mobile="9000000990").gst_number)   # ignored by the server

    def test_purchase_page_has_no_add_payment_type_link(self):
        self.login_retailer_a()

        self.assertNotContains(self.client.get(reverse("add_new_order")), "Add Payment Type")

    def test_admin_feature_pages_explain_when_no_shop_uses_them(self):
        self.login_admin()

        response = self.client.get(reverse("quotation_list"), follow=True)

        self.assertContains(response, "Quotations is used by Hardware shops")
        self.assertNotContains(response, "not available for your shop")
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("quotation_list"))

    def test_admin_sees_feature_pages_once_such_a_shop_exists(self):
        Retailer.objects.filter(pk=self.retailer_b.pk).update(shop_type="hardware")
        self.login_admin()

        self.assertEqual(self.client.get(reverse("quotation_list")).status_code, 200)
        self.assertContains(self.client.get(reverse("dashboard")), reverse("quotation_list"))


# =====================================================================
# LANGUAGES: English, Hindi, Marathi
# =====================================================================

from django.utils import translation as _translation


class LanguageTests(BaseTestData):

    PAGES = ["dashboard", "product_list", "add_product", "low_stock_alert", "sale_create", "sales_list",
             "add_new_order", "purchase_product_list", "supplier_list", "customer_list", "returns_list",
             "supplier_product_list"]

    def tearDown(self):
        _translation.activate("en")

    def choose(self, language):
        return self.client.post(reverse("set_language"), {"language": language, "next": reverse("dashboard")})

    def test_english_is_the_default(self):
        self.login_retailer_a()

        page = self.client.get(reverse("dashboard"))

        self.assertContains(page, "Sales")
        self.assertContains(page, 'name="language"')

    def test_hindi_and_marathi_menus(self):
        self.login_retailer_a()

        self.choose("hi")
        hindi = self.client.get(reverse("dashboard"))
        self.assertContains(hindi, "बिक्री")
        self.assertContains(hindi, "ग्राहक")
        self.assertContains(hindi, 'lang="hi"')

        self.choose("mr")
        marathi = self.client.get(reverse("dashboard"))
        self.assertContains(marathi, "विक्री")
        self.assertContains(marathi, "खरेदी")

    def test_every_main_page_opens_in_every_language(self):
        for user in (self.retailer_a.user, self.admin):
            self.client.force_login(user)
            for language in ("en", "hi", "mr"):
                self.choose(language)
                for page in self.PAGES:
                    with self.subTest(user=user.username, language=language, page=page):
                        self.assertEqual(self.client.get(reverse(page)).status_code, 200)

    def test_login_page_has_a_language_menu(self):
        self.choose("mr")

        page = self.client.get(reverse("user_login"))

        self.assertContains(page, 'name="language"')
        self.assertContains(page, "मराठी")

    def test_server_messages_are_translated(self):
        self.login_retailer_a()
        self.choose("hi")

        response = self.client.post(reverse("sale_create"), {"payment_type": "Cash"}, follow=True)

        self.assertContains(response, "ग्राहक चुनें।")   # "Please select a customer."

    def test_javascript_messages_are_translated(self):
        self.choose("hi")

        catalog = self.client.get(reverse("javascript-catalog"))

        self.assertEqual(catalog.status_code, 200)
        # The catalog writes non-English letters as \uXXXX codes.
        import json as _json
        self.assertContains(catalog, '"Customer name is required"')
        self.assertContains(catalog, _json.dumps("ग्राहक का नाम ज़रूरी है")[1:-1])

    def test_stored_values_show_translated(self):
        customer = Customer.objects.create(retailer=self.retailer_a, customer_name="Ram", mobile="9000000981")
        self.login_retailer_a()
        self.client.post(reverse("sale_create"), {
            "customer": customer.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": "1", "items[1][discount]": "0",
            "payment_type": "Cash", "paid_amount": "12.60", "action": "save",
        })
        self.choose("hi")

        page = self.client.get(reverse("sale_detail", args=[Sale.objects.get().id]))

        self.assertContains(page, "पूरा भुगतान")     # Paid
        self.assertEqual(Sale.objects.get().payment_status, "Paid")   # stored value unchanged

    def test_every_marked_text_has_hindi_and_marathi(self):
        from .management.commands.build_translations import LOCALE_DIR, collect, read_po

        found = collect()
        for language in ("hi", "mr"):
            for domain in ("django", "djangojs"):
                entries, _ = read_po(LOCALE_DIR / language / "LC_MESSAGES" / f"{domain}.po")
                missing = [key[0] for key in found[domain] if not any(entries.get(key, [""]))]
                with self.subTest(language=language, domain=domain):
                    self.assertEqual(missing, [], "Run: python manage.py build_translations --update, then translate")


# =====================================================================
# SAMPLE DATA (load_sample_data): every shop type, every scenario
# =====================================================================

class SampleDataTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        from io import StringIO
        call_command("load_sample_data", stdout=StringIO())

    def shop(self, shop_type):
        return Retailer.objects.get(shop_type=shop_type)

    def test_one_shop_per_type_and_logins_work(self):
        from .management.commands.load_sample_data import ADMIN, SHOPS
        self.assertEqual(set(Retailer.objects.values_list("shop_type", flat=True)), set(SHOPS))
        self.assertTrue(self.client.login(username=ADMIN["username"], password=ADMIN["password"]))
        for spec in SHOPS.values():
            username, password = spec["login"]
            with self.subTest(user=username):
                self.assertTrue(self.client.login(username=username, password=password))

    def test_every_shop_has_every_scenario(self):
        from django.db.models import F
        for shop in Retailer.objects.all():
            sales = Sale.objects.filter(retailer=shop)
            with self.subTest(shop=shop.shop_type):
                self.assertGreaterEqual(sales.count(), 10)
                # udhari: no cash taken at billing time (paid later by receipts or still due)
                self.assertTrue(sales.exclude(payments__receipt_number__isnull=True).exists())
                self.assertFalse(sales.exclude(payment_type="Cash").exists())          # cash only
                self.assertTrue(sales.filter(payment_status="Partial").exists())       # part paid
                self.assertTrue(sales.filter(tax_type="inter").exists())               # IGST customer
                self.assertTrue(sales.filter(tax_type="intra").exists())               # CGST+SGST
                self.assertTrue(Purchase.objects.filter(retailer=shop, due_amount__gt=0).exists())
                self.assertTrue(Payment.objects.filter(retailer=shop, receipt_number__isnull=False).exists())
                self.assertTrue(SaleReturn.objects.filter(retailer=shop).exists())
                self.assertTrue(PurchaseReturn.objects.filter(retailer=shop).exists())
                self.assertTrue(SupplierProduct.objects.filter(retailer=shop).exists())
                self.assertTrue(Product.objects.filter(retailer=shop, current_stock__lte=F("minimum_stock")).exists())

    def test_pharmacy_and_hardware_specials(self):
        from . import batches as batch_stock
        from .pharmacy_views import expiry_summary
        pharmacy = self.shop("pharmacy")
        self.assertTrue(all(batch_stock.batches_in_sync(p) for p in pharmacy.products.all()))
        summary = expiry_summary([pharmacy])
        self.assertGreaterEqual(summary["near_expiry_count"], 1)
        self.assertGreaterEqual(summary["expired_count"], 1)
        self.assertTrue(SaleItem.objects.filter(sale__retailer=pharmacy, product__schedule="H1").exists())

        hardware = self.shop("hardware")
        self.assertEqual(set(hardware.quotations.values_list("status", flat=True)), {"open", "converted", "cancelled"})
        self.assertTrue(hardware.customers.filter(price_level="wholesale").exists())

    def test_every_login_opens_every_page(self):
        pages = ["dashboard", "product_list", "add_product", "low_stock_alert", "sale_create", "sales_list",
                 "add_new_order", "purchase_product_list", "supplier_list", "customer_list", "returns_list",
                 "supplier_product_list"]
        users = [CustomUser.objects.get(is_superuser=True)] + [r.user for r in Retailer.objects.all()]
        for user in users:
            self.client.force_login(user)
            for page in pages:
                with self.subTest(user=user.username, page=page):
                    self.assertEqual(self.client.get(reverse(page)).status_code, 200)
            shop = Retailer.objects.filter(user=user).first()
            sales = Sale.objects.filter(retailer=shop) if shop else Sale.objects.all()
            for sale in sales[:3]:
                with self.subTest(user=user.username, sale=sale.invoice_number):
                    self.assertEqual(self.client.get(reverse("sale_invoice", args=[sale.id])).status_code, 200)


# =====================================================================
# SHOP TYPE SERVICES (admin switches a whole shop type on / off)
# =====================================================================

from .models import ShopTypeService  # noqa: E402


class ShopTypeServiceTests(BaseTestData):
    """Shop B is a stationery shop; Shop A stays general."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Retailer.all_objects.filter(pk=cls.retailer_b.pk).update(shop_type="stationery")
        cls.retailer_b.refresh_from_db()
        cls.purchase_b = cls._create_purchase(
            cls.retailer_b, cls.supplier_b1, cls.product_b, "8.00", date(2026, 10, 1)
        )

    def switch(self, shop_type, action):
        return self.client.post(
            reverse("shop_type_service_toggle", args=[shop_type]), {"action": action}
        )

    def test_migration_made_one_row_per_shop_type_all_on(self):
        self.assertEqual(
            sorted(ShopTypeService.all_objects.values_list("shop_type", flat=True)),
            sorted(SHOP_TYPE_LABELS),
        )
        self.assertFalse(ShopTypeService.all_objects.filter(is_active=False).exists())

    def test_admin_page_lists_every_type_with_counts(self):
        self.login_admin()

        response = self.client.get(reverse("shop_type_services"))

        self.assertEqual(response.status_code, 200)
        rows = {row["code"]: row for row in response.context["rows"]}
        self.assertEqual(set(rows), set(SHOP_TYPE_LABELS))
        self.assertEqual(rows["stationery"]["shops"], 1)
        self.assertEqual(rows["stationery"]["products"], 1)
        self.assertEqual(rows["stationery"]["purchases"], 1)
        self.assertContains(response, 'href="/shop-types/"')

    def test_switching_off_hides_every_record_of_that_type(self):
        self.login_admin()

        response = self.switch("stationery", "off")

        self.assertRedirects(response, reverse("shop_type_services"))
        service = ShopTypeService.all_objects.get(shop_type="stationery")
        self.assertFalse(service.is_active)
        self.assertEqual(service.changed_by, self.admin)

        # Hidden through the normal managers...
        self.assertFalse(Retailer.objects.filter(pk=self.retailer_b.pk).exists())
        self.assertFalse(Product.objects.filter(pk=self.product_b.pk).exists())
        self.assertFalse(Supplier.objects.filter(pk=self.supplier_b1.pk).exists())
        self.assertFalse(Purchase.objects.filter(pk=self.purchase_b.pk).exists())
        self.assertFalse(PurchaseItem.objects.filter(purchase=self.purchase_b).exists())
        # ...the other shop is untouched...
        self.assertTrue(Product.objects.filter(pk=self.product_a.pk).exists())
        # ...and nothing was deleted.
        self.assertTrue(Retailer.all_objects.filter(pk=self.retailer_b.pk).exists())
        self.assertTrue(Product.all_objects.filter(pk=self.product_b.pk).exists())
        self.assertTrue(PurchaseItem.all_objects.filter(purchase=self.purchase_b).exists())

    def test_admin_pages_hide_switched_off_shops(self):
        self.login_admin()
        self.switch("stationery", "off")

        retailers = self.client.get(reverse("retailer_list"))
        self.assertNotContains(retailers, "Shop B")
        self.assertContains(retailers, "Shop A")
        self.assertNotIn("stationery", [code for code, _ in retailers.context["shop_type_choices"]])

        products = self.client.get(reverse("product_list"))
        self.assertNotContains(products, "Ibuprofen")
        self.assertContains(products, "Paracetamol")

        suppliers = self.client.get(reverse("supplier_list"))
        self.assertNotContains(suppliers, "Beta Distributors")

        purchases = self.client.get(reverse("purchase_product_list"))
        self.assertNotContains(purchases, self.purchase_b.bill_number)

        # Opening a hidden record directly does not work either.
        detail = self.client.get(reverse("purchase_detail", args=[self.purchase_b.pk]))
        self.assertIn(detail.status_code, (302, 404))

        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_switching_on_again_shows_everything(self):
        self.login_admin()
        self.switch("stationery", "off")
        self.switch("stationery", "on")

        self.assertTrue(ShopTypeService.all_objects.get(shop_type="stationery").is_active)
        self.assertContains(self.client.get(reverse("retailer_list")), "Shop B")
        self.assertContains(self.client.get(reverse("product_list")), "Ibuprofen")
        self.assertTrue(PurchaseItem.objects.filter(purchase=self.purchase_b).exists())

    def test_owner_of_switched_off_type_cannot_log_in(self):
        ShopTypeService.all_objects.filter(shop_type="stationery").update(is_active=False)

        response = self.client.post(
            reverse("user_login"), {"username": "shopb", "password": self.password}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "service is paused by the admin")
        self.assertNotIn("_auth_user_id", self.client.session)

        # Other shop types still log in.
        response = self.client.post(
            reverse("user_login"), {"username": "shopa", "password": self.password}
        )
        self.assertEqual(response.status_code, 302)

    def test_owner_already_logged_in_is_signed_out(self):
        self.login_retailer_b()
        self.assertEqual(self.client.get(reverse("product_list")).status_code, 200)

        ShopTypeService.all_objects.filter(shop_type="stationery").update(is_active=False)
        response = self.client.get(reverse("product_list"))

        self.assertRedirects(response, reverse("user_login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_owner_can_log_in_again_after_switch_on(self):
        ShopTypeService.all_objects.filter(shop_type="stationery").update(is_active=False)
        ShopTypeService.all_objects.filter(shop_type="stationery").update(is_active=True)

        response = self.client.post(
            reverse("user_login"), {"username": "shopb", "password": self.password}
        )

        self.assertEqual(response.status_code, 302)

    def test_new_shop_of_switched_off_type_cannot_register(self):
        ShopTypeService.all_objects.filter(shop_type="stationery").update(is_active=False)
        self.login_admin()

        form = self.client.get(reverse("retailer_register"))
        self.assertNotContains(form, '<option value="stationery">')

        response = self.client.post(
            reverse("retailer_register"),
            {
                "username": "newshop", "password": "Str0ng!Passw0rd", "email": "newshop@example.com",
                "shop_name": "New Shop", "owner_name": "Owner", "mobile": "9333333333",
                "address": "1 Road", "city": "Pune", "state": "Maharashtra", "pincode": "411001",
                "shop_type": "stationery",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field"], "shop_type")
        self.assertFalse(CustomUser.objects.filter(username="newshop").exists())

    def test_retailer_cannot_open_or_switch(self):
        self.login_retailer_a()

        self.assertRedirects(
            self.client.get(reverse("shop_type_services")), reverse("dashboard"),
            fetch_redirect_response=False,
        )
        self.switch("stationery", "off")

        self.assertTrue(ShopTypeService.all_objects.get(shop_type="stationery").is_active)
        self.assertNotContains(self.client.get(reverse("dashboard")), 'href="/shop-types/"')

    def test_switch_needs_post_and_valid_values(self):
        self.login_admin()

        self.assertEqual(
            self.client.get(reverse("shop_type_service_toggle", args=["stationery"])).status_code, 405
        )
        self.switch("bakery", "off")
        self.switch("stationery", "maybe")

        self.assertFalse(ShopTypeService.all_objects.filter(is_active=False).exists())


class LoginPageMessageTests(BaseTestData):
    """Sign-in page shows server messages as styled alerts."""

    url = reverse("user_login")

    def test_wrong_password_shows_error_alert_and_keeps_username(self):
        response = self.client.post(self.url, {"username": "shopa", "password": "wrong-pass"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="alert alert-error"')
        self.assertContains(response, "Could not sign in")
        self.assertContains(response, "Wrong username or password. Please try again.")
        self.assertContains(response, 'value="shopa"')

    def test_empty_form_asks_for_both_fields(self):
        response = self.client.post(self.url, {"username": "", "password": ""})

        self.assertContains(response, "Please enter your username and password.")

    def test_inactive_account_message(self):
        CustomUser.objects.filter(username="shopa").update(is_active=False)

        response = self.client.post(self.url, {"username": "shopa", "password": self.password})

        # Django's default backend refuses inactive users, so the
        # message is the normal wrong-login one; either way no session.
        self.assertContains(response, 'class="alert alert-error"')
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_shows_success_alert_on_login_page(self):
        self.login_retailer_a()

        response = self.client.get(reverse("user_logout"), follow=True)

        self.assertContains(response, 'class="alert alert-success"')
        self.assertContains(response, "You have logged out safely.")

    def test_success_message_after_login_goes_to_dashboard(self):
        response = self.client.post(
            self.url, {"username": "shopa", "password": self.password}, follow=True
        )

        self.assertContains(response, "Welcome back, shopa!")

    def test_protected_page_shows_please_sign_in(self):
        response = self.client.get(reverse("sales_list"), follow=True)

        self.assertContains(response, "Please sign in")
        self.assertContains(response, 'name="next"')

    def test_plain_login_page_has_no_alert(self):
        response = self.client.get(self.url)

        self.assertNotContains(response, 'class="alert ')
        self.assertContains(response, 'id="loginForm"')


# =====================================================================
# SALES: CASH ONLY + SAVING WITHOUT LOSING THE BILL
# =====================================================================

class SaleCashOnlyTests(BaseTestData):
    """Sales and money from customers are cash only."""

    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def setUp(self):
        self.customer = Customer.objects.create(
            retailer=self.retailer_a, customer_name="Ramesh", mobile="9000000301",
        )

    def sale_data(self, qty="2", paid="25.20", **extra):
        # 2 x 12.00 = 24.00 + 5% GST = 25.20
        data = {
            "customer": self.customer.id,
            "items[1][product]": self.product_a.id, "items[1][unit]": self.unit.id,
            "items[1][quantity]": qty, "items[1][discount]": "0",
            "paid_amount": paid, "action": "save",
        }
        data.update(extra)
        return data

    def test_sale_without_payment_type_is_saved_as_cash(self):
        self.login_retailer_a()

        self.client.post(reverse("sale_create"), self.sale_data())

        sale = Sale.objects.get()
        self.assertEqual(sale.payment_type, "Cash")
        self.assertEqual(sale.payments.get().payment_type, "Cash")

    def test_other_payment_types_sent_by_a_form_are_ignored(self):
        self.login_retailer_a()

        for mode in ("UPI", "Cheque", "Bank Transfer", "Credit"):
            self.client.post(reverse("sale_create"), self.sale_data(qty="1", paid="12.60", payment_type=mode))

        self.assertEqual(Sale.objects.count(), 4)
        self.assertFalse(Sale.objects.exclude(payment_type="Cash").exists())
        self.assertFalse(Payment.objects.exclude(payment_type="Cash").exists())

    def test_nothing_paid_keeps_the_whole_bill_due(self):
        self.login_retailer_a()

        self.client.post(reverse("sale_create"), self.sale_data(paid="0"))

        sale = Sale.objects.get()
        self.assertEqual((sale.due_amount, sale.payment_status), (Decimal("25.20"), "Unpaid"))
        self.assertFalse(sale.payments.exists())

    def test_part_paid_sale(self):
        self.login_retailer_a()

        self.client.post(reverse("sale_create"), self.sale_data(paid="10"))

        sale = Sale.objects.get()
        self.assertEqual((sale.due_amount, sale.payment_status), (Decimal("15.20"), "Partial"))

    def test_sale_pages_do_not_show_a_payment_type(self):
        self.login_retailer_a()
        self.client.post(reverse("sale_create"), self.sale_data())
        sale = Sale.objects.get()

        for url in (reverse("sales_list"), reverse("sale_detail", args=[sale.id]), reverse("sale_invoice", args=[sale.id])):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertNotContains(page, "Payment Type")
                self.assertNotContains(page, "Type:")

    def test_customer_due_is_received_in_cash_only(self):
        self.login_retailer_a()
        self.client.post(reverse("sale_create"), self.sale_data(paid="0"))

        self.client.post(reverse("customer_receive_payment", args=[self.customer.id]), {
            "amount": "5", "payment_type": "UPI", "reference": "UPI 123",
        })

        payment = Payment.objects.get(receipt_number__isnull=False)
        self.assertEqual(payment.payment_type, "Cash")
        self.assertIsNone(payment.payment_reference)

    def test_customer_account_has_no_payment_mode_field(self):
        self.login_retailer_a()

        page = self.client.get(reverse("customer_account", args=[self.customer.id]))

        self.assertNotContains(page, 'name="payment_type"')
        self.assertNotContains(page, 'name="reference"')

    # ---------------------------------------------------- background save

    def test_page_save_success_answers_with_the_next_page(self):
        self.login_retailer_a()

        response = self.client.post(reverse("sale_create"), self.sale_data(action="save_print"), **self.AJAX)

        sale = Sale.objects.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True, "redirect": reverse("sale_invoice", args=[sale.id])})

    def test_page_save_error_answers_with_the_message_and_saves_nothing(self):
        self.login_retailer_a()

        # More than in stock (10): the page gets the message as JSON and
        # keeps the bill on screen instead of reloading an empty form.
        response = self.client.post(reverse("sale_create"), self.sale_data(qty="50", paid="0"), **self.AJAX)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertTrue(response.json()["error"])
        self.assertFalse(Sale.objects.exists())
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("10"))

    def test_paid_more_than_total_is_an_error_message(self):
        self.login_retailer_a()

        response = self.client.post(reverse("sale_create"), self.sale_data(paid="100"), **self.AJAX)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Paid amount cannot exceed grand total", response.json()["error"])

    def test_plain_form_post_still_redirects(self):
        self.login_retailer_a()

        response = self.client.post(reverse("sale_create"), self.sale_data(qty="50"))

        self.assertRedirects(response, reverse("sale_create"), fetch_redirect_response=False)

    def test_page_saves_in_the_background(self):
        self.login_retailer_a()

        page = self.client.get(reverse("sale_create"))

        self.assertContains(page, "function submitSale(")
        self.assertContains(page, "'X-Requested-With': 'XMLHttpRequest'")
        # The Save buttons are named "action", so saleForm.action is not the URL.
        self.assertContains(page, "fetch(saleForm.getAttribute('action')")
        self.assertNotContains(page, "fetch(saleForm.action")

    def test_old_due_from_the_sale_page_answers_with_json(self):
        self.login_retailer_a()
        self.client.post(reverse("sale_create"), self.sale_data(paid="0"))

        response = self.client.post(
            reverse("customer_receive_payment", args=[self.customer.id]),
            {"amount": "5.20", "next": "sale_create"}, **self.AJAX,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(Decimal(response.json()["balance"]), Decimal("20.00"))

        bad = self.client.post(
            reverse("customer_receive_payment", args=[self.customer.id]),
            {"amount": "999"}, **self.AJAX,
        )
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(bad.json()["success"])


# =====================================================================
# PURCHASES: CASH ONLY + SAVING WITHOUT LOSING THE BILL
# =====================================================================

from .models import PurchasePayment  # noqa: E402


class PurchaseCashOnlyTests(BaseTestData):
    """Purchases and payments to suppliers are cash only."""

    url = reverse("add_new_order")
    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def payload(self, **overrides):
        # 4 x 10.00, no tax = 40.00
        data = {
            "supplier": self.supplier_a1.id, "bill_number": "BILL-CASH", "bill_date": "2026-10-24",
            "payment_terms": "net15", "item_name_1": "Paracetamol", "item_unit_1": self.unit.id,
            "item_qty_1": "4", "item_free_qty_1": "0", "item_price_1": "10",
            "item_tax_1": "none", "item_mrp_1": "15", "paid_amount": "40", "action": "save",
        }
        data.update(overrides)
        return data

    def test_purchase_without_payment_type_is_saved_as_cash(self):
        self.login_retailer_a()

        self.client.post(self.url, self.payload())

        purchase = Purchase.objects.get(bill_number="BILL-CASH")
        self.assertEqual(purchase.payment_type, "Cash")
        self.assertEqual(purchase.payment_status, "Paid")
        self.assertEqual(purchase.payments.get().payment_type, "Cash")

    def test_other_payment_types_sent_by_a_form_are_ignored(self):
        self.login_retailer_a()

        for n, mode in enumerate(("UPI", "Cheque", "Bank Transfer", "Credit"), start=1):
            self.client.post(self.url, self.payload(bill_number=f"BILL-{n}", paid_amount="15", payment_type=mode))

        self.assertEqual(Purchase.objects.count(), 4)
        self.assertFalse(Purchase.objects.exclude(payment_type="Cash").exists())
        self.assertFalse(PurchasePayment.objects.exclude(payment_type="Cash").exists())

    def test_purchase_page_has_no_payment_type_field(self):
        self.login_retailer_a()

        page = self.client.get(self.url)

        self.assertNotContains(page, 'name="payment_type"')
        self.assertContains(page, 'class="cash-only-note"')

    def test_purchase_pages_do_not_show_a_payment_mode(self):
        self.login_retailer_a()
        self.client.post(self.url, self.payload(paid_amount="15"))
        purchase = Purchase.objects.get(bill_number="BILL-CASH")

        for url in (reverse("purchase_product_list"), reverse("purchase_detail", args=[purchase.id]),
                    reverse("purchase_invoice", args=[purchase.id])):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertNotContains(page, "Payment Type")
                self.assertNotContains(page, "Payment mode")
                self.assertNotContains(page, "<th>Mode</th>")
                self.assertNotContains(page, 'name="payment_type"')
                self.assertNotContains(page, 'name="reference"')

    def test_supplier_statement_does_not_name_a_payment_mode(self):
        self.login_retailer_a()
        self.client.post(self.url, self.payload(paid_amount="15"))

        statement = accounts_module.supplier_statement(self.supplier_a1)

        payment_rows = [row for row in statement if row["kind"] == "payment"]
        self.assertEqual(payment_rows[0]["particulars"], "Payment for bill BILL-CASH")

    # ---------------------------------------------------- background save

    def test_page_save_success_answers_with_the_next_page(self):
        self.login_retailer_a()

        response = self.client.post(self.url, self.payload(action="save_print"), **self.AJAX)

        purchase = Purchase.objects.get(bill_number="BILL-CASH")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "success": True,
            "redirect": reverse("purchase_invoice", args=[purchase.id]) + "?print=1",
        })

    def test_page_save_error_answers_with_the_message_and_saves_nothing(self):
        self.login_retailer_a()

        # Paid more than the bill: the page gets the message as JSON and
        # keeps everything on screen instead of reloading an empty form.
        response = self.client.post(self.url, self.payload(paid_amount="500"), **self.AJAX)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertTrue(response.json()["error"])
        self.assertFalse(Purchase.objects.exists())
        self.product_a.refresh_from_db()
        self.assertEqual(self.product_a.current_stock, Decimal("10"))

    def test_same_bill_number_twice_is_an_error_message(self):
        self.login_retailer_a()
        self.client.post(self.url, self.payload())

        response = self.client.post(self.url, self.payload(), **self.AJAX)

        self.assertIn(response.status_code, (400, 409))
        self.assertFalse(response.json()["success"])
        self.assertEqual(Purchase.objects.filter(bill_number="BILL-CASH").count(), 1)

    def test_plain_form_post_still_redirects(self):
        self.login_retailer_a()

        response = self.client.post(self.url, self.payload(paid_amount="500"))

        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_page_saves_in_the_background(self):
        self.login_retailer_a()

        page = self.client.get(self.url)

        self.assertContains(page, "function submitPurchase(")
        self.assertContains(page, "'X-Requested-With': 'XMLHttpRequest'")
        # The Save buttons are named "action", so form.action is not the URL.
        self.assertContains(page, "fetch(form.getAttribute('action')")

    def test_bill_payment_is_cash_only(self):
        self.login_retailer_a()
        self.client.post(self.url, self.payload(paid_amount="0"))
        purchase = Purchase.objects.get(bill_number="BILL-CASH")

        self.client.post(reverse("purchase_add_payment", args=[purchase.id]), {
            "amount": "10", "payment_type": "Cheque", "reference": "CHQ 1", "payment_date": "2026-10-25",
        })

        payment = purchase.payments.get()
        self.assertEqual((payment.amount, payment.payment_type, payment.reference), (Decimal("10.00"), "Cash", None))
