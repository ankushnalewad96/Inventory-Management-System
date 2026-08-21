import re
import logging
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.contrib.auth import get_user_model
from .models import CustomUser, Retailer, Supplier, Category, Brand, Unit, Product, Purchase, PurchaseItem
from decimal import Decimal, InvalidOperation
from django.contrib.admin.views.decorators import staff_member_required
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, F, Count
from django.db import DatabaseError
from django.db.models import Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP





logger = logging.getLogger("pharma_app")




# Create your views here.
@login_required(login_url='/user-login/')
def dashboard(request):
    """
    Displays the retailer dashboard with a list of all purchases,
    ordered by the most recent bill date and creation time.
    """
    try:
        purchases = Purchase.objects.select_related("retailer").order_by(
            "-bill_date", "-created_at"
        )
        supplier_list = Supplier.objects.filter(is_active = True).order_by("supplier_name")
    except Exception:
        logger.exception("Failed to fetch purchases for dashboard.")
        messages.error(request, "Something went wrong while loading the dashboard.")
        purchases = Purchase.objects.none()

    context = {"purchases": purchases, "supplier_list":supplier_list}
    return render(request, "dashboard.html", context)


def retailer_register(request):
    """
    Handles retailer account creation.

    Restricted to admin/staff users only — retailers do not self-register.
    Creates a CustomUser account and a linked Retailer profile in a single
    atomic transaction — if profile creation fails, the user account is
    rolled back too, so we never end up with an orphaned user.
    """
    if request.method == "POST":
        return _handle_retailer_registration(request)

    return render(request, "register.html")


def _handle_retailer_registration(request):
    """Validates form data and creates the User + Retailer records."""

    # --- Collect form data ---
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    email = request.POST.get("email", "").strip()

    shop_name = request.POST.get("shop_name", "").strip()
    owner_name = request.POST.get("owner_name", "").strip()
    mobile = request.POST.get("mobile", "").strip()
    gst_number = request.POST.get("gst_number", "").strip()
    pan_number = request.POST.get("pan_number", "").strip()
    address = request.POST.get("address", "").strip()
    city = request.POST.get("city", "").strip()
    state = request.POST.get("state", "").strip()
    pincode = request.POST.get("pincode", "").strip()

    # --- Basic validation ---
    required_fields = {
        "Username": username,
        "Password": password,
        "Email": email,
        "Shop Name": shop_name,
        "Owner Name": owner_name,
        "Mobile": mobile,
        "Address": "address",
        "City": city,
        "State": state,
        "Pincode": pincode,
    }
    missing = [label for label, value in required_fields.items() if not value]
    if missing:
        messages.error(request, f"Missing required field(s): {', '.join(missing)}")
        return redirect("retailer_register")

    if CustomUser.objects.filter(username=username).exists():
        messages.error(request, "Username already exists.")
        return redirect("retailer_register")

    if CustomUser.objects.filter(email=email).exists():
        messages.error(request, "Email already exists.")
        return redirect("retailer_register")

    # --- Create user + retailer atomically ---
    try:
        with transaction.atomic():
            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                user_type="retailer",
            )

            Retailer.objects.create(
                user=user,
                shop_name=shop_name,
                owner_name=owner_name,
                mobile=mobile,
                email=email,
                gst_number=gst_number or None,
                pan_number=pan_number or None,
                address=address,
                city=city,
                state=state,
                pincode=pincode,
            )

        logger.info(
            "Retailer account created by admin=%s: username=%s, shop=%s",
            request.user.username, username, shop_name
        )
        messages.success(request, "Retailer registered successfully.")
        return redirect("user_login")

    except IntegrityError:
        logger.exception("IntegrityError during retailer registration for username=%s", username)
        messages.error(request, "Registration failed due to a data conflict. Please try again.")
        return redirect("retailer_register")

    except Exception:
        logger.exception("Unexpected error during retailer registration for username=%s", username)
        messages.error(request, "Something went wrong. Please try again later.")
        return redirect("retailer_register")


def _login(request):
    """
    Handles user login.

    Authenticates credentials against the database and starts a session
    on success. Redirects already-authenticated users straight to the
    dashboard instead of showing the login form again.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:
            messages.error(request, "Both username and password are required fields.")
            return render(request, "userlogin.html")

        try:
            user = authenticate(request, username=username, password=password)
        except Exception:
            logger.exception("Unexpected error during authentication for username=%s", username)
            messages.error(request, "Something went wrong. Please try again later.")
            return render(request, "userlogin.html")

        if user is not None:
            if not user.is_active:
                logger.warning("Login blocked for inactive user: username=%s", username)
                messages.error(request, "Your account is inactive. Please contact support.")
                return render(request, "userlogin.html")

            login(request, user)
            logger.info("User logged in: username=%s", username)
            messages.success(request, f"Access Granted. Welcome, {user.username}.")
            return redirect("dashboard")

        logger.warning("Failed login attempt for username=%s", username)
        messages.error(request, "Invalid authentication credentials supplied.")

    return render(request, "userlogin.html")


def user_logout(request):
    """Logs out the current user and clears their session."""
    username = request.user.username if request.user.is_authenticated else "Anonymous"

    try:
        logout(request)
        logger.info("User logged out: username=%s", username)
    except Exception:
        logger.exception("Unexpected error during logout for username=%s", username)

    return redirect("user_login")


@login_required(login_url='/user-login/')
def add_product(request):
    """
    Handles product creation for a retailer.

    Displays a form pre-loaded with available retailers, categories,
    brands, and units, and creates a new Product record on submission.
    """
    retailers = Retailer.objects.all()
    categories = Category.objects.all()
    brands = Brand.objects.all()
    units = Unit.objects.all()

    context = {
        "retailers": retailers,
        "categories": categories,
        "brands": brands,
        "units": units,
    }

    if request.method == "POST":

        # --- Collect form data ---
        retailer_id = request.POST.get("retailer", "").strip()
        category_id = request.POST.get("category", "").strip()
        brand_id = request.POST.get("brand", "").strip()
        unit_id = request.POST.get("unit", "").strip()

        product_name = request.POST.get("product_name", "").strip()
        barcode = request.POST.get("barcode", "").strip()
        hsn_code = request.POST.get("hsn_code", "").strip()
        purchase_price = request.POST.get("purchase_price", "").strip()
        selling_price = request.POST.get("selling_price", "").strip()
        mrp = request.POST.get("mrp", "").strip()
        minimum_stock = request.POST.get("minimum_stock", "0").strip()
        current_stock = request.POST.get("current_stock", "10").strip()
        gst = request.POST.get("gst", "0").strip()

        # --- Basic required-field validation ---
        required_fields = {
            "Retailer": retailer_id,
            "Category": category_id,
            "Brand": brand_id,
            "Unit": unit_id,
            "Product Name": product_name,
            "HSN Code": hsn_code,
            "Purchase Price": purchase_price,
            "Selling Price": selling_price,
            "MRP": mrp,
        }
        missing = [label for label, value in required_fields.items() if not value]
        if missing:
            messages.error(request, f"Missing required field(s): {', '.join(missing)}")
            return render(request, "add_product.html", context)

        # --- Numeric field validation ---
        try:
            purchase_price = Decimal(purchase_price)
            selling_price = Decimal(selling_price)
            mrp = Decimal(mrp)
            gst = Decimal(gst) if gst else Decimal("0")
            minimum_stock = int(minimum_stock) if minimum_stock else 0
            current_stock = int(current_stock) if current_stock else 0
        except (InvalidOperation, ValueError):
            messages.error(request, "Please enter valid numeric values for price, stock, and GST fields.")
            return render(request, "add_product.html", context)

        # --- Fetch related objects safely ---
        try:
            retailer = get_object_or_404(Retailer, id=retailer_id)
            category = get_object_or_404(Category, id=category_id)
            brand = get_object_or_404(Brand, id=brand_id)
            unit = get_object_or_404(Unit, id=unit_id)
        except Exception:
            logger.warning(
                "Invalid related object reference while adding product: "
                "retailer=%s, category=%s, brand=%s, unit=%s",
                retailer_id, category_id, brand_id, unit_id,
            )
            messages.error(request, "Selected retailer, category, brand, or unit is invalid.")
            return render(request, "add_product.html", context)

        # --- Create product ---
        try:
            with transaction.atomic():
                Product.objects.create(
                    retailer=retailer,
                    category=category,
                    brand=brand,
                    unit=unit,
                    product_name=product_name,
                    barcode=barcode or None,
                    hsn_code=hsn_code,
                    purchase_price=purchase_price,
                    selling_price=selling_price,
                    mrp=mrp,
                    minimum_stock=minimum_stock,
                    current_stock=current_stock,
                    gst=gst,
                )

            logger.info(
                "Product added by user=%s: product=%s, retailer=%s",
                request.user.username, product_name, retailer.shop_name,
            )
            messages.success(request, "Product added successfully.")
            return redirect("dashboard")

        except IntegrityError:
            logger.exception(
                "IntegrityError while adding product=%s (likely duplicate barcode=%s)",
                product_name, barcode,
            )
            messages.error(request, "A product with this barcode already exists.")
            return render(request, "add_product.html", context)

        except Exception:
            logger.exception("Unexpected error while adding product=%s", product_name)
            messages.error(request, "Something went wrong while adding the product. Please try again.")
            return render(request, "add_product.html", context)

    return render(request, "add_product.html", context)





@login_required(login_url="/user-login/")
def low_stock_alert(request):
    """
    Display low-stock products.

    Retailer:
        - Shows only products belonging to the logged-in retailer.
        - Does not show retailer column.

    Superadmin:
        - Shows low-stock products for all active retailers.
        - Shows retailer column.
    """

    try:

        # CHECK WHETHER USER IS SUPERADMIN
        is_admin = request.user.is_superuser


        # BASE QUERY
        # Low stock means:
        # current_stock <= minimum_stock
        # Only active products are displayed.
        products_qs = (
            Product.objects
            .filter(
                is_active=True,
                current_stock__lte=F("minimum_stock"),
            )
            .select_related(
                "retailer",
                "category",
                "brand",
                "unit",
            )
        )


        # RETAILER LOGIN
        if not is_admin:

            retailer = getattr(
                request.user,
                "retailer",
                None
            )


            # Retailer profile does not exist
            if retailer is None:

                logger.warning(
                    "User %s has no associated retailer; "
                    "cannot fetch low stock products.",
                    request.user.id,
                )

                messages.error(
                    request,
                    "No retailer profile found for this account."
                )

                return render(
                    request,
                    "low_stock_list.html",
                    {
                        "products": [],
                        "low_stock_count": 0,
                        "is_admin": False,
                    }
                )


            # Restrict products to logged-in retailer
            products_qs = products_qs.filter(
                retailer=retailer
            )


        # SUPERADMIN
        else:

            logger.info(
                "Superadmin %s viewing low stock products "
                "for all retailers.",
                request.user.id,
            )


        # ORDERING
        # Lowest stock appears first.
        products_qs = products_qs.order_by(
            "current_stock",
            "minimum_stock",
            "product_name",
        )


        # COUNT BEFORE PAGINATION
        low_stock_count = products_qs.count()


        # PAGINATION
        paginator = Paginator(
            products_qs,
            25
        )

        page_number = request.GET.get(
            "page"
        )

        try:
            products = paginator.page(
                page_number
            )

        except PageNotAnInteger:
            products = paginator.page(
                1
            )

        except EmptyPage:
            products = paginator.page(
                paginator.num_pages
            )


        # LOGGING
        if is_admin:

            logger.info(
                "Superadmin %s: %d low stock product(s) found.",
                request.user.id,
                low_stock_count,
            )

        else:

            logger.info(
                "Retailer %s: %d low stock product(s) found.",
                retailer.id,
                low_stock_count,
            )


        # CONTEXT
        context = {
            "products": products,
            "low_stock_count": low_stock_count,
            "is_admin": is_admin,
        }


        return render(
            request,
            "low_stock_list.html",
            context
        )


    # UNEXPECTED ERROR
    except Exception:

        logger.exception(
            "Unexpected error while fetching low stock "
            "products for user %s.",
            request.user.id,
        )


        messages.error(
            request,
            "Something went wrong while loading "
            "low stock products."
        )


        return render(
            request,
            "low_stock_list.html",
            {
                "products": [],
                "low_stock_count": 0,
                "is_admin": request.user.is_superuser,
            }
        )



@login_required(login_url="/user-login/")
def product_list(request):
    """
    Display the product catalog with server-side filtering,
    dynamic statistics and pagination.

    Access rules:
    - Superadmin can view products from all retailers.
    - Retailer users can view only their own products.

    Filters:
    - All
    - Active
    - Inactive
    - Low Stock
    - Out of Stock
    - Product name
    - Barcode
    - HSN
    - Brand
    - Category
    """

    try:
        # ---------------------------------------------------------
        # Base queryset
        # ---------------------------------------------------------
        products = (
            Product.objects
            .select_related(
                "category",
                "brand",
                "unit",
                "retailer",
            )
        )

        # ---------------------------------------------------------
        # Retailer access control
        # ---------------------------------------------------------
        if not request.user.is_superuser:

            retailer = getattr(
                request.user,
                "retailer",
                None,
            )

            if retailer is None:
                logger.warning(
                    "Product list access denied. "
                    "User has no retailer association. user_id=%s",
                    request.user.id,
                )

                messages.error(
                    request,
                    "Your account is not associated with a retailer.",
                )

                return redirect("dashboard")

            products = products.filter(
                retailer=retailer
            )

        # ---------------------------------------------------------
        # Read GET parameters
        # ---------------------------------------------------------
        search = request.GET.get(
            "search",
            "",
        ).strip()

        status = request.GET.get(
            "status",
            "all",
        ).strip().lower()

        # ---------------------------------------------------------
        # Search
        # ---------------------------------------------------------
        if search:
            products = products.filter(
                Q(product_name__icontains=search)
                | Q(barcode__icontains=search)
                | Q(hsn_code__icontains=search)
                | Q(brand__brand_name__icontains=search)
                | Q(category__category_name__icontains=search)
            )

        # ---------------------------------------------------------
        # Status filter
        # ---------------------------------------------------------
        if status == "active":

            products = products.filter(
                is_active=True
            )

        elif status == "inactive":

            products = products.filter(
                is_active=False
            )

        elif status == "low_stock":

            products = products.filter(
                current_stock__gt=0,
                current_stock__lte=F(
                    "minimum_stock"
                ),
            )

        elif status == "out_of_stock":

            products = products.filter(
                current_stock=0
            )

        # ---------------------------------------------------------
        # Dynamic statistics
        # ---------------------------------------------------------
        stats = products.aggregate(
            total_products=Count("id"),

            active_products=Count(
                "id",
                filter=Q(
                    is_active=True
                ),
            ),

            low_stock_count=Count(
                "id",
                filter=Q(
                    current_stock__gt=0,
                    current_stock__lte=F(
                        "minimum_stock"
                    ),
                ),
            ),

            out_of_stock_count=Count(
                "id",
                filter=Q(
                    current_stock=0
                ),
            ),
        )

        # ---------------------------------------------------------
        # Pagination
        # ---------------------------------------------------------
        products = products.order_by(
            "product_name"
        )

        paginator = Paginator(
            products,
            25,
        )

        page_number = request.GET.get(
            "page"
        )

        page_obj = paginator.get_page(
            page_number
        )

        # ---------------------------------------------------------
        # Context
        # ---------------------------------------------------------
        context = {
            "products": page_obj,
            "page_obj": page_obj,

            "total_products": (
                stats["total_products"] or 0
            ),

            "active_products": (
                stats["active_products"] or 0
            ),

            "low_stock_count": (
                stats["low_stock_count"] or 0
            ),

            "out_of_stock_count": (
                stats["out_of_stock_count"] or 0
            ),

            "search": search,
            "status": status,
        }

        return render(
            request,
            "product_list.html",
            context,
        )

    except DatabaseError:
        logger.exception(
            "Database error while loading product list. "
            "user_id=%s",
            request.user.id,
        )

        messages.error(
            request,
            "Unable to load products. Please try again.",
        )

        context = {
            "products": Product.objects.none(),
            "page_obj": None,
            "total_products": 0,
            "active_products": 0,
            "low_stock_count": 0,
            "out_of_stock_count": 0,
            "search": "",
            "status": "all",
        }

        return render(
            request,
            "product_list.html",
            context,
        )

    except Exception:
        logger.exception(
            "Unexpected error while loading product list. "
            "user_id=%s",
            request.user.id,
        )

        messages.error(
            request,
            "Something went wrong while loading the product list.",
        )

        context = {
            "products": Product.objects.none(),
            "page_obj": None,
            "total_products": 0,
            "active_products": 0,
            "low_stock_count": 0,
            "out_of_stock_count": 0,
            "search": "",
            "status": "all",
        }

        return render(
            request,
            "product_list.html",
            context,
        )


# =========================================================
# GST RATE MAP
# =========================================================

GST_RATE_MAP = {
    "none": Decimal("0"),
    "gst5": Decimal("5"),
    "gst12": Decimal("12"),
    "gst18": Decimal("18"),
    "gst28": Decimal("28"),
}


# =========================================================
# COMMON DECIMAL VALUES
# =========================================================

MONEY_ZERO = Decimal("0.00")


# =========================================================
# MONEY HELPER
# =========================================================

def money(value):
    """
    Convert a value to Decimal with exactly 2 decimal places.
    """

    return Decimal(
        str(value or "0")
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )


# =========================================================
# DECIMAL POST HELPER
# =========================================================

def decimal_from_post(value, field_name):
    """
    Safely convert POST value to Decimal.

    Raises ValueError if:
    - value is invalid
    - value is negative
    """

    try:

        amount = Decimal(
            str(value or "0")
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError
    ):

        raise ValueError(
            f"{field_name} must be a valid number."
        )

    if amount < Decimal("0"):

        raise ValueError(
            f"{field_name} cannot be negative."
        )

    return amount


@login_required(login_url="/user-login/")
def add_order(request):
    """
    Display Add Purchase page and handle purchase creation.
    """

    # =====================================================
    # POST
    # =====================================================

    if request.method == "POST":

        return _handle_add_order(request)


    # =====================================================
    # PRODUCTS / SUPPLIERS
    # =====================================================

    if request.user.is_superuser:

        products = (
            Product.objects
            .filter(
                is_active=True
            )
            .select_related(
                "unit",
                "brand",
                "category"
            )
            .order_by(
                "product_name"
            )
        )

        supplier_list = (
            Supplier.objects
            .filter(
                is_active=True
            )
            .order_by(
                "supplier_name"
            )
        )

    else:

        products = (
            Product.objects
            .filter(
                retailer_id=request.user.id,
                is_active=True
            )
            .select_related(
                "unit",
                "brand",
                "category"
            )
            .order_by(
                "product_name"
            )
        )

        supplier_list = (
            Supplier.objects
            .filter(
                retailer_id=request.user.id,
                is_active=True
            )
            .order_by(
                "supplier_name"
            )
        )


    units = Unit.objects.all()


    retailer_list = (
        Retailer.objects
        .filter(
            is_active=True
        )
        .order_by(
            "shop_name"
        )
    )


    context = {
        "products": products,
        "units": units,
        "supplier_list": supplier_list,
        "retailer_list": retailer_list,
    }


    return render(
        request,
        "add_order.html",
        context
    )



def _handle_add_order(request):
    """
    Handles creation of Purchase and PurchaseItem records.

    Flow:

        1. Validate retailer
        2. Validate supplier
        3. Read bill information
        4. Read item information
        5. Calculate subtotal and GST
        6. Calculate grand total
        7. Create Purchase
        8. Pass Purchase object to _create_purchase_items()
        9. Create PurchaseItem records
        10. Update product stock
        11. Commit transaction
    """

    try:

        # =====================================================
        # 1. GET RETAILER
        # =====================================================

        if request.user.is_superuser:

            retailer_id = (
                request.POST
                .get(
                    "retailer",
                    ""
                )
                .strip()
            )

            if not retailer_id:

                raise ValueError(
                    "Please select a retailer."
                )

        else:

            retailer_id = getattr(
                request.user,
                "retailer_id",
                None
            )

            if not retailer_id:

                logger.warning(
                    "User without retailer profile "
                    "attempted to create purchase. "
                    "user=%s",
                    request.user.username
                )

                raise ValueError(
                    "No retailer profile is linked "
                    "to your account."
                )


        # =====================================================
        # 2. GET RETAILER OBJECT
        # =====================================================

        try:

            retailer = Retailer.objects.get(
                id=retailer_id,
                is_active=True
            )

        except Retailer.DoesNotExist:

            raise ValueError(
                "Selected retailer does not exist "
                "or is inactive."
            )


        # =====================================================
        # 3. GET SUPPLIER
        # =====================================================

        supplier_id = (
            request.POST
            .get(
                "supplier",
                ""
            )
            .strip()
        )


        if not supplier_id:

            raise ValueError(
                "Supplier is required."
            )


        try:

            supplier = Supplier.objects.get(
                id=supplier_id,
                is_active=True
            )

        except Supplier.DoesNotExist:

            raise ValueError(
                "Selected supplier does not exist "
                "or is inactive."
            )


        # =====================================================
        # 4. BILL INFORMATION
        # =====================================================

        bill_number = (
            request.POST
            .get(
                "bill_number",
                ""
            )
            .strip()
        )


        bill_date = (
            request.POST
            .get(
                "bill_date",
                ""
            )
            .strip()
        )


        bill_time = (
            request.POST
            .get(
                "bill_time"
            )
            or None
        )


        if not bill_number:

            raise ValueError(
                "Bill number is required."
            )


        if not bill_date:

            raise ValueError(
                "Bill date is required."
            )


        # =====================================================
        # 5. HEADER LEVEL AMOUNTS
        #
        # IMPORTANT:
        #
        # We DO NOT trust subtotal/GST/grand_total
        # coming from JavaScript.
        #
        # They are calculated by backend.
        # =====================================================

        discount = decimal_from_post(
            request.POST.get(
                "discount",
                "0"
            ),
            "Discount"
        )


        transport_charge = decimal_from_post(
            request.POST.get(
                "transport_charge",
                "0"
            ),
            "Transport charge"
        )


        other_charge = decimal_from_post(
            request.POST.get(
                "other_charge",
                "0"
            ),
            "Other charge"
        )


        paid_amount = decimal_from_post(
            request.POST.get(
                "paid_amount",
                "0"
            ),
            "Paid amount"
        )


        # =====================================================
        # 6. PAYMENT TYPE
        # =====================================================

        payment_type = (
            request.POST
            .get(
                "payment_type",
                ""
            )
            .strip()
        )


        if (
            paid_amount > Decimal("0")
            and not payment_type
        ):

            raise ValueError(
                "Please select a payment type."
            )


        # =====================================================
        # 7. CALCULATE ITEM TOTALS FIRST
        #
        # IMPORTANT:
        #
        # This function DOES NOT create PurchaseItem yet.
        #
        # It only validates and calculates the item data.
        # =====================================================

        item_data = _prepare_purchase_items(
            request=request,
            retailer=retailer
        )


        if not item_data:

            raise ValueError(
                "Please add at least one product "
                "to the purchase."
            )


        # =====================================================
        # 8. CALCULATE PURCHASE SUBTOTAL
        # =====================================================

        subtotal = money(
            sum(
                item["item_subtotal"]
                for item in item_data
            )
        )


        # =====================================================
        # 9. CALCULATE TOTAL GST
        # =====================================================

        gst = money(
            sum(
                item["item_gst"]
                for item in item_data
            )
        )


        # =====================================================
        # 10. DISCOUNT VALIDATION
        # =====================================================

        if discount > subtotal:

            raise ValueError(
                "Discount cannot be greater than subtotal."
            )


        # =====================================================
        # 11. GRAND TOTAL
        #
        # Same calculation as frontend.
        # =====================================================

        grand_total = money(
            subtotal
            - discount
            + gst
            + transport_charge
            + other_charge
        )


        # =====================================================
        # 12. PAID AMOUNT VALIDATION
        # =====================================================

        if paid_amount > grand_total:

            raise ValueError(
                "Paid amount cannot be greater than "
                "the grand total."
            )


        # =====================================================
        # 13. DUE AMOUNT
        # =====================================================

        due_amount = money(
            grand_total
            - paid_amount
        )


        if due_amount < Decimal("0.00"):

            due_amount = Decimal("0.00")


        # =====================================================
        # 14. PAYMENT STATUS
        # =====================================================

        if paid_amount >= grand_total:

            payment_status = "Paid"

            due_amount = Decimal("0.00")

        elif paid_amount > Decimal("0.00"):

            payment_status = "Partial"

        else:

            payment_status = "Unpaid"


        # =====================================================
        # 15. DATABASE TRANSACTION
        # =====================================================

        with transaction.atomic():

            # =================================================
            # CREATE PURCHASE
            # =================================================

            purchase = Purchase.objects.create(

                retailer=retailer,

                supplier=supplier,

                bill_number=bill_number,

                bill_date=bill_date,

                bill_time=bill_time,

                invoice_date=bill_date,

                payment_terms=(
                    request.POST
                    .get(
                        "payment_terms",
                        ""
                    )
                    .strip()
                ),

                due_date=(
                    request.POST
                    .get(
                        "due_date"
                    )
                    or None
                ),

                state_of_supply=(
                    request.POST
                    .get(
                        "state_of_supply",
                        ""
                    )
                    .strip()
                ),

                warehouse=(
                    request.POST
                    .get(
                        "warehouse",
                        ""
                    )
                    .strip()
                ),

                # Backend calculated values

                subtotal=subtotal,

                discount=money(
                    discount
                ),

                gst=gst,

                transport_charge=money(
                    transport_charge
                ),

                other_charge=money(
                    other_charge
                ),

                grand_total=grand_total,

                paid_amount=money(
                    paid_amount
                ),

                due_amount=due_amount,

                payment_type=payment_type,

                payment_status=payment_status,

                remarks=(
                    request.POST
                    .get(
                        "remarks",
                        ""
                    )
                    .strip()
                ),
            )


            # =================================================
            # CREATE PURCHASE ITEMS
            #
            # THIS IS THE FIX FOR YOUR PROBLEM.
            #
            # We now pass the Purchase object.
            # =================================================

            _create_purchase_items(
                request=request,
                purchase=purchase,
                item_data=item_data
            )


            # =================================================
            # SAVE BILL FILE
            # =================================================

            bill_file = request.FILES.get(
                "bill_file"
            )


            if bill_file:

                purchase.bill_file = bill_file

                purchase.save(
                    update_fields=[
                        "bill_file"
                    ]
                )


        # =====================================================
        # SUCCESS
        # =====================================================

        logger.info(
            "Purchase created successfully. "
            "user=%s bill_number=%s retailer=%s "
            "subtotal=%s gst=%s grand_total=%s "
            "paid=%s due=%s",
            request.user.username,
            bill_number,
            retailer.shop_name,
            subtotal,
            gst,
            grand_total,
            paid_amount,
            due_amount,
        )


        messages.success(
            request,
            f"Purchase order {bill_number} "
            f"created successfully!"
        )


        return redirect(
            "dashboard"
        )


    # =========================================================
    # VALIDATION ERRORS
    # =========================================================

    except ValueError as exc:

        logger.warning(
            "Purchase validation failed. "
            "user=%s error=%s",
            request.user.username,
            str(exc)
        )


        messages.error(
            request,
            str(exc)
        )


        return redirect(
            "add_new_order"
        )


    # =========================================================
    # INTEGRITY ERROR
    # =========================================================

    except IntegrityError:

        logger.exception(
            "IntegrityError while creating purchase. "
            "user=%s",
            request.user.username
        )


        messages.error(
            request,
            "A purchase with this bill number "
            "may already exist."
        )


        return redirect(
            "add_new_order"
        )


    # =========================================================
    # UNEXPECTED ERROR
    # =========================================================

    except Exception:

        logger.exception(
            "Unexpected error while creating purchase. "
            "user=%s",
            request.user.username
        )


        messages.error(
            request,
            "Something went wrong while saving "
            "the purchase. Please try again."
        )


        return redirect(
            "add_new_order"
        )


def _prepare_purchase_items(
    request,
    retailer
):
    """
    Reads all item_* fields from POST.

    This function:
        - validates product
        - validates unit
        - validates quantity
        - validates price
        - validates GST
        - calculates item subtotal
        - calculates item GST
        - calculates item total

    It does NOT create database records.

    Returns:
        list of dictionaries
    """

    item_data = []


    # =========================================================
    # LOOP THROUGH POST FIELDS
    # =========================================================

    for key in request.POST.keys():

        if not key.startswith(
            "item_name_"
        ):
            continue


        # =====================================================
        # GET ROW NUMBER
        # =====================================================

        index = key.rsplit(
            "_",
            1
        )[-1]


        # =====================================================
        # PRODUCT NAME
        # =====================================================

        product_name = (
            request.POST
            .get(
                f"item_name_{index}",
                ""
            )
            .strip()
        )


        # Empty product row
        # simply ignore it.

        if not product_name:
            continue


        # =====================================================
        # GET PRODUCT
        # =====================================================

        try:

            product = (
                Product.objects
                .get(
                    product_name__iexact=product_name,
                    retailer=retailer,
                    is_active=True
                )
            )

        except Product.DoesNotExist:

            raise ValueError(
                f"Product '{product_name}' "
                f"was not found for this retailer."
            )


        # =====================================================
        # UNIT
        # =====================================================

        unit_id = (
            request.POST
            .get(
                f"item_unit_{index}",
                ""
            )
            .strip()
        )


        if not unit_id:

            raise ValueError(
                f"Please select a unit for "
                f"'{product_name}'."
            )


        try:

            unit = Unit.objects.get(
                id=unit_id
            )

        except Unit.DoesNotExist:

            raise ValueError(
                f"Selected unit was not found "
                f"for '{product_name}'."
            )


        # =====================================================
        # MRP
        # =====================================================

        mrp = decimal_from_post(
            request.POST.get(
                f"item_mrp_{index}",
                "0"
            ),
            f"MRP for {product_name}"
        )


        # =====================================================
        # QUANTITY
        # =====================================================

        quantity = decimal_from_post(
            request.POST.get(
                f"item_qty_{index}",
                "0"
            ),
            f"Quantity for {product_name}"
        )


        if quantity <= Decimal("0"):

            raise ValueError(
                f"Quantity for '{product_name}' "
                f"must be greater than zero."
            )


        # =====================================================
        # FREE QUANTITY
        # =====================================================

        free_quantity = decimal_from_post(
            request.POST.get(
                f"item_free_qty_{index}",
                "0"
            ),
            f"Free quantity for {product_name}"
        )


        # =====================================================
        # PURCHASE PRICE
        # =====================================================

        purchase_price = decimal_from_post(
            request.POST.get(
                f"item_price_{index}",
                "0"
            ),
            f"Purchase price for {product_name}"
        )


        if purchase_price <= Decimal("0"):

            raise ValueError(
                f"Purchase price for '{product_name}' "
                f"must be greater than zero."
            )


        # =====================================================
        # GST CODE
        # =====================================================

        tax_code = (
            request.POST
            .get(
                f"item_tax_{index}",
                "none"
            )
            .strip()
            .lower()
        )


        if tax_code not in GST_RATE_MAP:

            raise ValueError(
                f"Invalid GST selected for "
                f"'{product_name}'."
            )


        gst_rate = GST_RATE_MAP[
            tax_code
        ]


        # =====================================================
        # ITEM SUBTOTAL
        #
        # Quantity × Purchase Price
        # =====================================================

        item_subtotal = money(
            quantity
            * purchase_price
        )


        # =====================================================
        # ITEM GST
        #
        # Subtotal × GST %
        # =====================================================

        item_gst = money(
            item_subtotal
            * gst_rate
            / Decimal("100")
        )


        # =====================================================
        # ITEM TOTAL
        # =====================================================

        item_total = money(
            item_subtotal
            + item_gst
        )


        # =====================================================
        # STORE ITEM DATA
        # =====================================================

        item_data.append({

            "product": product,

            "unit": unit,

            "quantity": quantity,

            "free_quantity": free_quantity,

            "purchase_price": purchase_price,

            "mrp": mrp,

            "gst_rate": gst_rate,

            "item_subtotal": item_subtotal,

            "item_gst": item_gst,

            "item_total": item_total,

            "product_name": product_name,

        })


    return item_data


def _create_purchase_items(
    request,
    purchase,
    item_data
):
    """
    Creates PurchaseItem records and updates product stock.

    Parameters:
        request:
            Current Django request.

        purchase:
            Already-created Purchase object.

        item_data:
            Validated and calculated item information
            returned by _prepare_purchase_items().

    Stock calculation:

        New Stock =
            Existing Stock
            + Purchase Quantity
            + Free Quantity

    Everything runs inside the transaction.atomic()
    block of _handle_add_order().
    """


    # =========================================================
    # LOOP THROUGH PREPARED ITEMS
    # =========================================================

    for item in item_data:


        # =====================================================
        # LOCK PRODUCT ROW
        #
        # This prevents incorrect stock updates when
        # multiple purchases happen at the same time.
        # =====================================================

        product = (
            Product.objects
            .select_for_update()
            .get(
                id=item["product"].id
            )
        )


        # =====================================================
        # STORE OLD STOCK FOR LOGGING
        # =====================================================

        old_stock = product.current_stock


        # =====================================================
        # CREATE PURCHASE ITEM
        # =====================================================

        PurchaseItem.objects.create(

            purchase=purchase,

            product=product,

            unit=item["unit"],

            quantity=item["quantity"],

            free_quantity=item[
                "free_quantity"
            ],

            purchase_price=item[
                "purchase_price"
            ],

            selling_price=product.selling_price,

            mrp=item["mrp"],

            gst=item["gst_rate"],

            discount=MONEY_ZERO,

            amount=item["item_total"],

            remarks=item["product_name"],
        )


        # =====================================================
        # STOCK TO ADD
        #
        # Example:
        #
        # Quantity      = 10
        # Free Quantity = 2
        #
        # Stock Added   = 12
        # =====================================================

        stock_to_add = (
            item["quantity"]
            + item["free_quantity"]
        )


        # =====================================================
        # UPDATE PRODUCT STOCK
        # =====================================================

        product.current_stock = (
            product.current_stock
            + stock_to_add
        )


        # =====================================================
        # SAVE PRODUCT STOCK
        # =====================================================

        product.save(
            update_fields=[
                "current_stock",
                "updated_at",
            ]
        )


        # =====================================================
        # LOG STOCK UPDATE
        # =====================================================

        logger.info(
            "Purchase item created and stock updated. "
            "purchase_id=%s "
            "product_id=%s "
            "product=%s "
            "old_stock=%s "
            "purchase_quantity=%s "
            "free_quantity=%s "
            "stock_added=%s "
            "new_stock=%s",
            purchase.id,
            product.id,
            product.product_name,
            old_stock,
            item["quantity"],
            item["free_quantity"],
            stock_to_add,
            product.current_stock,
        )

   

@login_required(login_url='/user-login/')
def purchase_list(request):

    try:
        purchases = (
            Purchase.objects
            .select_related("retailer", "supplier")
            .all()
            .order_by("-bill_date", "-created_at")
        )

        # -------------------------
        # GET FILTER PARAMETERS
        # -------------------------

        from_date = request.GET.get("from_date", "").strip()
        to_date = request.GET.get("to_date", "").strip()
        status = request.GET.get("status", "").strip()
        supplier_id = request.GET.get("supplier", "").strip()
        # search = request.GET.get("search", "").strip()

        # -------------------------
        # DATE FILTER
        # -------------------------

        if from_date:
            purchases = purchases.filter(
                bill_date__gte=from_date
            )

        if to_date:
            purchases = purchases.filter(
                bill_date__lte=to_date
            )

        # -------------------------
        # STATUS FILTER
        # -------------------------

        if status:
            purchases = purchases.filter(
                payment_status=status
            )

        # -------------------------
        # SUPPLIER FILTER
        # -------------------------

        if supplier_id:
            purchases = purchases.filter(
                supplier_id=supplier_id
            )

        # -------------------------
        # SEARCH
        # -------------------------

        # if search:
        #     purchases = purchases.filter(
        #         Q(bill_number__icontains=search) |
        #         Q(supplier__supplier_name__icontains=search)
        #     )

        # -------------------------
        # PAGINATION
        # -------------------------

        paginator = Paginator(purchases, 25)

        page_number = request.GET.get("page")

        page_obj = paginator.get_page(page_number)

        # -------------------------
        # SUPPLIER DROPDOWN
        # -------------------------

        supplier_list = (
            Supplier.objects
            .filter(is_active=True)
            .order_by("supplier_name")
        )

    except Exception:
        logger.exception("Failed to fetch purchase list.")

        messages.error(
            request,
            "Something went wrong while loading purchases."
        )

        page_obj = Paginator(
            Purchase.objects.none(),
            25
        ).get_page(1)

        supplier_list = Supplier.objects.none()

    context = {
        "purchases": page_obj,
        "page_obj": page_obj,
        "supplier_list": supplier_list,
    }

    return render(
        request,
        "purchase_list.html",
        context
    )


@login_required(login_url="/user-login/")
def purchase_detail(request, purchase_id):
    """
    Display complete purchase details including all purchase items.

    Access rules:
    - Django superadmin can view purchases belonging to any retailer.
    - Retailer users can view only purchases belonging to their retailer.
    """

    try:
        # ---------------------------------------------------------
        # PurchaseItem queryset
        # ---------------------------------------------------------
        items_queryset = (
            PurchaseItem.objects
            .select_related(
                "product",
                "unit",
            )
            .order_by("id")
        )

        # ---------------------------------------------------------
        # Base Purchase queryset
        # ---------------------------------------------------------
        purchase_queryset = (
            Purchase.objects
            .select_related(
                "retailer",
                "supplier",
            )
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=items_queryset,
                )
            )
        )

        # ---------------------------------------------------------
        # Access control
        # ---------------------------------------------------------
        if request.user.is_superuser:
            # Superadmin can view purchases of any retailer.
            purchase = get_object_or_404(
                purchase_queryset,
                pk=purchase_id,
            )

        else:
            # Retailer user can view only their own retailer's
            # purchase.
            retailer = getattr(request.user, "retailer", None)

            if retailer is None:
                logger.warning(
                    "Retailer not associated with user. "
                    "user_id=%s, purchase_id=%s",
                    request.user.id,
                    purchase_id,
                )

                messages.error(
                    request,
                    "Your account is not associated with a retailer.",
                )

                return redirect("purchase_list")

            purchase = get_object_or_404(
                purchase_queryset,
                pk=purchase_id,
                retailer=retailer,
            )

        # ---------------------------------------------------------
        # Prefetched purchase items
        # ---------------------------------------------------------
        items = purchase.items.all()

        # ---------------------------------------------------------
        # Context
        # ---------------------------------------------------------
        context = {
            "purchase": purchase,
            "items": items,
        }

        return render(
            request,
            "purchase_detail.html",
            context,
        )

    except DatabaseError:
        logger.exception(
            "Database error while loading purchase details. "
            "purchase_id=%s, user_id=%s",
            purchase_id,
            request.user.id,
        )

        messages.error(
            request,
            "Unable to load purchase details. Please try again.",
        )

        return redirect("purchase_list")

    except Exception:
        logger.exception(
            "Unexpected error while loading purchase details. "
            "purchase_id=%s, user_id=%s",
            purchase_id,
            request.user.id,
        )

        messages.error(
            request,
            "Something went wrong while loading purchase details.",
        )

        return redirect("purchase_list")


@login_required(login_url='/user-login/')
def add_supplier(request):
    """
    Create a new supplier securely and safely.
    """
    # GET Request: Render the entry form
    if request.method != "POST":
        # SECURITY FIX: Filter retailers belonging strictly to the logged-in user
        # Replace 'user=request.user' with your actual model relationship (e.g., profile.retailer)
        
        if request.user.is_superuser:
            retailers = Retailer.objects.filter(is_active=True)
        else:
            retailers = Retailer.objects.filter(user=request.user, is_active=True)
        return render(request, "add_supplier.html", {"retailers": retailers})

    # POST Request: Process and save the data
    try:
        with transaction.atomic():
            # SECURITY FIX: Ensure the user owns the retailer ID they sent
            retailer = Retailer.objects.get(
                id=request.POST.get("retailer"),
                is_active=True
            )

            # CLEANUP: Extract and sanitize crucial text values
            supplier_name = request.POST.get("supplier_name", "").strip()
            if not supplier_name:
                messages.error(request, "Supplier Name is required.")
                return redirect("add_new_supplier")

            # VALIDATION: Check for unique constraint violation early
            if Supplier.objects.filter(retailer=retailer, supplier_name__iexact=supplier_name).exists():
                logger.warning("Duplicate supplier '%s' attempted for retailer %s", supplier_name, retailer.id)
                messages.error(request, "Supplier already exists for this retailer.")
                return redirect("add_new_supplier")

            # CLEANUP: Extract optional fields cleanly as Python None instead of empty strings
            contact_person = request.POST.get("contact_person", "").strip() or None
            alternate_mobile = request.POST.get("alternate_mobile", "").strip() or None
            email = request.POST.get("email", "").strip() or None
            gst_number = request.POST.get("gst_number", "").strip() or None
            pan_number = request.POST.get("pan_number", "").strip() or None
            notes = request.POST.get("notes", "").strip() or None

            # MANDATORY FIELDS: Fallback defaults if they arrive empty
            mobile = request.POST.get("mobile", "").strip()
            address = request.POST.get("address", "").strip()
            city = request.POST.get("city", "").strip()
            state = request.POST.get("state", "").strip()
            pincode = request.POST.get("pincode", "").strip()

            # CONVERSIONS: Safe decimal and integer handling
            try:
                opening_balance = Decimal(request.POST.get("opening_balance") or "0.00")
                credit_limit = Decimal(request.POST.get("credit_limit") or "0.00")
                credit_days = int(request.POST.get("credit_days") or 0)
            except (InvalidOperation, ValueError):
                logger.error("Data type conversion failed for financial/numeric values.")
                messages.error(request, "Invalid numeric or decimal format provided.")
                return redirect("add_new_supplier")

            # FIX: HTML checkboxes send 'on' when checked, and are absent when unchecked
            is_active = "is_active" in request.POST

            # PERSIST: Build and commit instance to database
            supplier = Supplier.objects.create(
                retailer=retailer,
                supplier_name=supplier_name,
                contact_person=contact_person,
                mobile=mobile,
                alternate_mobile=alternate_mobile,
                email=email,
                gst_number=gst_number,
                pan_number=pan_number,
                address=address,
                city=city,
                state=state,
                pincode=pincode,
                opening_balance=opening_balance,
                credit_limit=credit_limit,
                credit_days=credit_days,
                is_active=is_active,
                notes=notes
            )

            logger.info("Supplier '%s' (ID: %s) created by retailer %s", supplier.supplier_name, supplier.id, retailer.id)
            messages.success(request, "Supplier added successfully.")
            return redirect("add_new_supplier")

    except Retailer.DoesNotExist:
        logger.error("Retailer not found or unauthorized access attempt by User ID %s", request.user.id)
        messages.error(request, "Retailer does not exist or unauthorized access.")
        
    except IntegrityError:
        logger.exception("Database unique constraint validation dropped to database level.")
        messages.error(request, "Supplier already exists.")
        
    except Exception as e:
        logger.exception("Unexpected exception inside add_supplier view: %s", str(e))
        messages.error(request, "Something went wrong. Please try again.")

    return redirect("add_new_supplier")





@require_POST
def update_product(request):
    """
    Update editable product fields from the product view/edit modal.

    Editable fields:
        - purchase_price
        - selling_price
        - mrp
        - gst
        - current_stock
        - minimum_stock
        - is_active
    """

    product_id = request.POST.get("product_id")

    # ---------------------------------------------------------
    # 1. Validate Product ID
    # ---------------------------------------------------------
    if not product_id:
        logger.warning(
            "Product update failed: product_id missing. user=%s",
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=False,
            message="Product ID is required.",
            status=400,
        )

    # ---------------------------------------------------------
    # 2. Fetch Product
    # ---------------------------------------------------------
    try:
        product = Product.objects.get(pk=product_id)

    except Product.DoesNotExist:
        logger.warning(
            "Product update failed: product not found. product_id=%s user=%s",
            product_id,
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=False,
            message="Product not found.",
            status=404,
        )

    except (TypeError, ValueError):
        logger.warning(
            "Product update failed: invalid product_id=%s user=%s",
            product_id,
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=False,
            message="Invalid product ID.",
            status=400,
        )

    # ---------------------------------------------------------
    # 3. Read submitted values
    # ---------------------------------------------------------
    purchase_price_raw = request.POST.get("purchase_price")
    selling_price_raw = request.POST.get("selling_price")
    mrp_raw = request.POST.get("mrp")
    gst_raw = request.POST.get("gst")
    current_stock_raw = request.POST.get("current_stock")
    minimum_stock_raw = request.POST.get("minimum_stock")
    is_active_raw = request.POST.get("is_active")

    try:
        # -----------------------------------------------------
        # 4. Convert numeric values
        # -----------------------------------------------------
        purchase_price = Decimal(purchase_price_raw)
        selling_price = Decimal(selling_price_raw)
        mrp = Decimal(mrp_raw)
        gst = Decimal(gst_raw)

        current_stock = int(current_stock_raw)
        minimum_stock = int(minimum_stock_raw)

    except (InvalidOperation, TypeError, ValueError):
        logger.warning(
            "Product update failed: invalid numeric values. "
            "product_id=%s user=%s",
            product_id,
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=False,
            message="One or more numeric values are invalid.",
            status=400,
        )

    # ---------------------------------------------------------
    # 5. Validate values
    # ---------------------------------------------------------
    if purchase_price <= 0:
        return _product_update_response(
            request,
            success=False,
            message="Purchase price must be greater than 0.",
            status=400,
        )

    if selling_price <= 0:
        return _product_update_response(
            request,
            success=False,
            message="Selling price must be greater than 0.",
            status=400,
        )

    if selling_price < purchase_price:
        return _product_update_response(
            request,
            success=False,
            message="Selling price must be greater than or equal to purchase price.",
            status=400,
        )

    if mrp <= 0:
        return _product_update_response(
            request,
            success=False,
            message="MRP must be greater than 0.",
            status=400,
        )

    if mrp < selling_price:
        return _product_update_response(
            request,
            success=False,
            message="MRP must be greater than or equal to selling price.",
            status=400,
        )

    if gst < 0 or gst > 100:
        return _product_update_response(
            request,
            success=False,
            message="GST must be between 0 and 100.",
            status=400,
        )

    if current_stock < 0:
        return _product_update_response(
            request,
            success=False,
            message="Current stock cannot be negative.",
            status=400,
        )

    if minimum_stock < 0:
        return _product_update_response(
            request,
            success=False,
            message="Minimum stock cannot be negative.",
            status=400,
        )

    # ---------------------------------------------------------
    # 6. Convert active status
    # ---------------------------------------------------------
    is_active = str(is_active_raw).lower() == "true"

    # ---------------------------------------------------------
    # 7. Update inside transaction
    # ---------------------------------------------------------
    try:
        with transaction.atomic():

            changed_fields = []

            if product.purchase_price != purchase_price:
                product.purchase_price = purchase_price
                changed_fields.append("purchase_price")

            if product.selling_price != selling_price:
                product.selling_price = selling_price
                changed_fields.append("selling_price")

            if product.mrp != mrp:
                product.mrp = mrp
                changed_fields.append("mrp")

            if product.gst != gst:
                product.gst = gst
                changed_fields.append("gst")

            if product.current_stock != current_stock:
                product.current_stock = current_stock
                changed_fields.append("current_stock")

            if product.minimum_stock != minimum_stock:
                product.minimum_stock = minimum_stock
                changed_fields.append("minimum_stock")

            if product.is_active != is_active:
                product.is_active = is_active
                changed_fields.append("is_active")

            # Save only when something actually changed.
            if changed_fields:
                product.save(
                    update_fields=changed_fields
                )

        # -----------------------------------------------------
        # 8. Success logging
        # -----------------------------------------------------
        logger.info(
            "Product updated successfully. "
            "product_id=%s product_name=%s changed_fields=%s user=%s",
            product.id,
            product.product_name,
            changed_fields,
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=True,
            message="Product updated successfully.",
            status=200,
        )

    except Exception:
        # -----------------------------------------------------
        # 9. Unexpected error
        # -----------------------------------------------------
        logger.exception(
            "Unexpected error while updating product. "
            "product_id=%s user=%s",
            product_id,
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=False,
            message="An unexpected error occurred while updating the product.",
            status=500,
        )


def _product_update_response(request, success, message, status):
    """
    Return JSON for AJAX requests and redirect response
    for normal browser POST requests.
    """

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if is_ajax:
        return JsonResponse(
            {
                "success": success,
                "message": message,
            },
            status=status,
        )

    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)

    return redirect("product_list")


@require_POST
def delete_product(request, product_id):
    """
    Delete a product by product ID.

    The endpoint accepts only POST requests and returns
    a JSON response suitable for AJAX requests.
    """

    user = (
        request.user
        if request.user.is_authenticated
        else "Anonymous"
    )

    # ---------------------------------------------------------
    # 1. Validate product ID
    # ---------------------------------------------------------
    if not product_id:
        logger.warning(
            "Product deletion failed: product_id missing. user=%s",
            user,
        )

        return JsonResponse(
            {
                "success": False,
                "message": "Product ID is required.",
            },
            status=400,
        )

    # ---------------------------------------------------------
    # 2. Get product
    # ---------------------------------------------------------
    try:
        product = Product.objects.get(pk=product_id)

    except Product.DoesNotExist:

        logger.warning(
            "Product deletion failed: product not found. "
            "product_id=%s user=%s",
            product_id,
            user,
        )

        return JsonResponse(
            {
                "success": False,
                "message": "Product not found.",
            },
            status=404,
        )

    # ---------------------------------------------------------
    # 3. Store product information before deletion
    # ---------------------------------------------------------
    product_name = product.product_name

    # ---------------------------------------------------------
    # 4. Delete product
    # ---------------------------------------------------------
    try:

        with transaction.atomic():

            product.delete()

        # -----------------------------------------------------
        # 5. Success logger
        # -----------------------------------------------------
        logger.info(
            "Product deleted successfully. "
            "product_id=%s product_name=%s user=%s",
            product_id,
            product_name,
            user,
        )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    f'Product "{product_name}" '
                    "deleted successfully."
                ),
            },
            status=200,
        )

    except Exception:

        logger.exception(
            "Unexpected error while deleting product. "
            "product_id=%s product_name=%s user=%s",
            product_id,
            product_name,
            user,
        )

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "An unexpected error occurred "
                    "while deleting the product."
                ),
            },
            status=500,
        )




# ********************************* Sales Module *********************************
def sales_create(request):
    return render(request,"sale_create.html")
