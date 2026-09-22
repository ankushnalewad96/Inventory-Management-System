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


@login_required(login_url="/user-login/")
def retailer_register(request):
    """
    Handles retailer account creation.

    Only superusers and staff users are allowed to create
    retailer accounts.

    Supports:
    - Normal browser form submission.
    - AJAX form submission returning JSON.

    Creates the CustomUser and linked Retailer profile
    inside one atomic transaction.
    """

    # ------------------------------------------------------------
    # ACCESS CONTROL
    # ------------------------------------------------------------
    if not (request.user.is_superuser or request.user.is_staff):

        logger.warning(
            "Unauthorized retailer registration attempt. User ID=%s",
            request.user.id
        )

        error_message = (
            "You are not authorized to register a retailer."
        )

        is_ajax = (
            request.headers.get("X-Requested-With")
            == "XMLHttpRequest"
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message
                },
                status=403
            )

        messages.error(request, error_message)
        return redirect("user_login")

    # ------------------------------------------------------------
    # GET REQUEST
    # ------------------------------------------------------------
    if request.method != "POST":
        return render(
            request,
            "register.html"
        )

    # ------------------------------------------------------------
    # POST REQUEST
    # ------------------------------------------------------------
    return _handle_retailer_registration(request)


def _handle_retailer_registration(request):
    """
    Validates retailer registration data and creates:

        CustomUser
             |
             └── Retailer

    Both records are created atomically.
    """

    is_ajax = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    try:

        # ========================================================
        # COLLECT FORM DATA
        # ========================================================

        username = request.POST.get(
            "username",
            ""
        ).strip()

        password = request.POST.get(
            "password",
            ""
        )

        email = request.POST.get(
            "email",
            ""
        ).strip()

        shop_name = request.POST.get(
            "shop_name",
            ""
        ).strip()

        owner_name = request.POST.get(
            "owner_name",
            ""
        ).strip()

        mobile = request.POST.get(
            "mobile",
            ""
        ).strip()

        gst_number = request.POST.get(
            "gst_number",
            ""
        ).strip()

        pan_number = request.POST.get(
            "pan_number",
            ""
        ).strip()

        address = request.POST.get(
            "address",
            ""
        ).strip()

        city = request.POST.get(
            "city",
            ""
        ).strip()

        state = request.POST.get(
            "state",
            ""
        ).strip()

        pincode = request.POST.get(
            "pincode",
            ""
        ).strip()

        # ========================================================
        # REQUIRED FIELD VALIDATION
        # ========================================================

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

        missing_fields = [
            field_name
            for field_name, value in required_fields.items()
            if not value
        ]

        if missing_fields:

            error_message = (
                "Please fill all required fields: "
                + ", ".join(missing_fields)
            )

            if is_ajax:
                return JsonResponse(
                    {
                        "success": False,
                        "message": error_message,
                        "missing_fields": missing_fields
                    },
                    status=400
                )

            messages.error(
                request,
                error_message
            )

            return redirect("retailer_register")

        # ========================================================
        # USERNAME VALIDATION
        # ========================================================

        if CustomUser.objects.filter(
            username__iexact=username
        ).exists():

            logger.warning(
                "Duplicate username registration attempt. "
                "Username=%s, Created By=%s",
                username,
                request.user.username
            )

            error_message = "Username already exists."

            if is_ajax:
                return JsonResponse(
                    {
                        "success": False,
                        "message": error_message,
                        "field": "username"
                    },
                    status=409
                )

            messages.error(
                request,
                error_message
            )

            return redirect("retailer_register")

        # ========================================================
        # EMAIL VALIDATION
        # ========================================================

        if CustomUser.objects.filter(
            email__iexact=email
        ).exists():

            logger.warning(
                "Duplicate email registration attempt. "
                "Email=%s, Created By=%s",
                email,
                request.user.username
            )

            error_message = "Email already exists."

            if is_ajax:
                return JsonResponse(
                    {
                        "success": False,
                        "message": error_message,
                        "field": "email"
                    },
                    status=409
                )

            messages.error(
                request,
                error_message
            )

            return redirect("retailer_register")

        # ========================================================
        # MOBILE VALIDATION
        # ========================================================

        mobile_digits = "".join(
            character
            for character in mobile
            if character.isdigit()
        )

        if not 10 <= len(mobile_digits) <= 15:

            error_message = (
                "Please enter a valid mobile number."
            )

            if is_ajax:
                return JsonResponse(
                    {
                        "success": False,
                        "message": error_message,
                        "field": "mobile"
                    },
                    status=400
                )

            messages.error(
                request,
                error_message
            )

            return redirect("retailer_register")

        # ========================================================
        # CREATE USER + RETAILER ATOMICALLY
        # ========================================================

        with transaction.atomic():

            user = CustomUser.objects.create_user(
                username=username,
                email=email,
                password=password,
                user_type="retailer",
            )

            retailer = Retailer.objects.create(
                user=user,
                shop_name=shop_name,
                owner_name=owner_name,
                mobile=mobile_digits,
                email=email,
                gst_number=gst_number or None,
                pan_number=pan_number or None,
                address="address",
                city=city,
                state=state,
                pincode=pincode,
            )

        # ========================================================
        # LOG SUCCESS
        # ========================================================

        logger.info(
            "Retailer account created successfully. "
            "Retailer ID=%s, User ID=%s, Username=%s, "
            "Shop=%s, Created By=%s",
            retailer.id,
            user.id,
            username,
            shop_name,
            request.user.username
        )

        # ========================================================
        # AJAX SUCCESS RESPONSE
        # ========================================================

        if is_ajax:

            return JsonResponse(
                {
                    "success": True,
                    "id": retailer.id,
                    "user_id": user.id,
                    "username": user.username,
                    "shop_name": retailer.shop_name,
                    "message": "Retailer registered successfully."
                },
                status=201
            )

        # ========================================================
        # NORMAL FORM SUCCESS
        # ========================================================

        messages.success(
            request,
            "Retailer registered successfully."
        )

        return redirect("user_login")

    # ============================================================
    # DATABASE INTEGRITY ERROR
    # ============================================================

    except IntegrityError:

        logger.exception(
            "IntegrityError during retailer registration. "
            "Username=%s, Created By=%s",
            request.POST.get("username", "").strip(),
            request.user.username
        )

        error_message = (
            "Registration failed because the username, email, "
            "or another value already exists."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message
                },
                status=409
            )

        messages.error(
            request,
            error_message
        )

    # ============================================================
    # UNEXPECTED ERROR
    # ============================================================

    except Exception:

        logger.exception(
            "Unexpected error during retailer registration. "
            "Username=%s, Created By=%s",
            request.POST.get("username", "").strip(),
            request.user.username
        )

        error_message = (
            "Something went wrong while registering the retailer. "
            "Please try again later."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message
                },
                status=500
            )

        messages.error(
            request,
            error_message
        )

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


@login_required(login_url="/user-login/")
def add_product(request):
    """
    Create a new product.

    Supports:
    - Normal browser form submission.
    - AJAX/fetch submission returning JSON.

    Security:
    - Superusers/staff can create products for any active retailer.
    - Normal users can create products only for their own retailer.

    All product creation is performed inside an atomic transaction.
    """

    # REQUEST TYPE
    is_ajax = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    # LOAD FORM DATA
    if request.user.is_superuser or request.user.is_staff:
        retailers = Retailer.objects.filter(
            is_active=True
        )
        categories = Category.objects.all()
        brands = Brand.objects.all()
        units = Unit.objects.all()
    else:
        retailers = Retailer.objects.filter(
            user=request.user,
            is_active=True
        )

        brands = Brand.objects.filter(retailer=retailers[0].id)
        categories = Category.objects.filter(retailer=retailers[0].id)
    units = Unit.objects.all()

    

    context = {
        "retailers": retailers,
        "categories": categories,
        "brands": brands,
        "units": units,
    }

    # ============================================================
    # GET REQUEST
    # ============================================================
    if request.method != "POST":
        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # COLLECT FORM DATA
    # ============================================================
    retailer_id = request.POST.get(
        "retailer",
        ""
    ).strip()

    category_id = request.POST.get(
        "category",
        ""
    ).strip()

    brand_id = request.POST.get(
        "brand",
        ""
    ).strip()

    unit_id = request.POST.get(
        "unit",
        ""
    ).strip()

    product_name = request.POST.get(
        "product_name",
        ""
    ).strip()

    barcode = request.POST.get(
        "barcode",
        ""
    ).strip()

    hsn_code = request.POST.get(
        "hsn_code",
        ""
    ).strip()

    purchase_price = request.POST.get(
        "purchase_price",
        ""
    ).strip()

    selling_price = request.POST.get(
        "selling_price",
        ""
    ).strip()

    mrp = request.POST.get(
        "mrp",
        ""
    ).strip()

    minimum_stock = request.POST.get(
        "minimum_stock",
        "0"
    ).strip()

    current_stock = request.POST.get(
        "current_stock",
        "0"
    ).strip()

    gst = request.POST.get(
        "gst",
        "0"
    ).strip()

    # ============================================================
    # REQUIRED FIELD VALIDATION
    # ============================================================
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

    missing_fields = [
        field_name
        for field_name, value in required_fields.items()
        if not value
    ]

    if missing_fields:

        error_message = (
            "Please fill all required fields: "
            + ", ".join(missing_fields)
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                    "missing_fields": missing_fields,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # NUMERIC VALIDATION
    # ============================================================
    try:

        purchase_price = Decimal(
            purchase_price
        )

        selling_price = Decimal(
            selling_price
        )

        mrp = Decimal(
            mrp
        )

        gst = (
            Decimal(gst)
            if gst
            else Decimal("0")
        )

        minimum_stock = (
            int(minimum_stock)
            if minimum_stock
            else 0
        )

        current_stock = (
            int(current_stock)
            if current_stock
            else 0
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError
    ):

        logger.warning(
            "Invalid numeric values while adding product. "
            "User=%s, Product=%s",
            request.user.username,
            product_name
        )

        error_message = (
            "Please enter valid numeric values for "
            "price, stock, and GST fields."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # BUSINESS VALIDATION
    # ============================================================
    if purchase_price < 0:

        error_message = (
            "Purchase price cannot be negative."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    if selling_price < 0:

        error_message = (
            "Selling price cannot be negative."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    if mrp < 0:

        error_message = (
            "MRP cannot be negative."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    if minimum_stock < 0:

        error_message = (
            "Minimum stock cannot be negative."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    if current_stock < 0:

        error_message = (
            "Current stock cannot be negative."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    if gst < 0:

        error_message = (
            "GST cannot be negative."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # GST RANGE VALIDATION
    # ============================================================
    if gst > Decimal("100"):

        error_message = (
            "GST percentage cannot be greater than 100."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # PRICE VALIDATION
    # ============================================================
    if selling_price > mrp:

        error_message = (
            "Selling price cannot be greater than MRP."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=400
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # FETCH RETAILER
    # ============================================================
    try:

        if request.user.is_superuser or request.user.is_staff:

            retailer = Retailer.objects.get(
                id=retailer_id,
                is_active=True
            )

        else:

            retailer = Retailer.objects.get(
                id=retailer_id,
                user=request.user,
                is_active=True
            )

    except Retailer.DoesNotExist:

        logger.warning(
            "Unauthorized or invalid retailer selected "
            "while adding product. User=%s, Retailer=%s",
            request.user.username,
            retailer_id
        )

        error_message = (
            "Selected retailer does not exist or "
            "you are not authorized to use it."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=403
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # FETCH CATEGORY
    # ============================================================
    try:

        # ========================================================
        # CATEGORY
        # ========================================================
        
        if category_id.startswith("other:"):

            category_name = category_id[
                len("other:"):
            ].strip()

            if not category_name:
                error_message = "Category name is required."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message,
                        },
                        status=400
                    )

                messages.error(
                    request,
                    error_message
                )

                return render(
                    request,
                    "add_product.html",
                    context
                )

            # ----------------------------------------------------
            # Check category for THIS retailer
            # ----------------------------------------------------
            category = Category.objects.filter(
                retailer=retailer,
                category_name__iexact=category_name
            ).first()

            # ----------------------------------------------------
            # Create category if it doesn't exist
            # ----------------------------------------------------
            if category is None:

                category = Category.objects.create(
                    retailer=retailer,
                    category_name=category_name
                )

                logger.info(
                    "New category created. "
                    "Category=%s, Retailer=%s, User=%s",
                    category_name,
                    retailer.id,
                    request.user.username
                )

        else:

            # ----------------------------------------------------
            # Existing category selected from dropdown
            # ----------------------------------------------------
            category = Category.objects.filter(
                id=category_id,
                retailer=retailer
            ).first()

            if category is None:

                error_message = (
                    "Selected category does not exist "
                    "or does not belong to this retailer."
                )

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message,
                        },
                        status=400
                    )

                messages.error(
                    request,
                    error_message
                )

                return render(
                    request,
                    "add_product.html",
                    context
                )

        # ========================================================
        # BRAND
        # ========================================================
        if brand_id.startswith("other:"):

            brand_name = brand_id[
                len("other:"):
            ].strip()

            if not brand_name:
                error_message = "Brand name is required."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message,
                        },
                        status=400
                    )

                messages.error(
                    request,
                    error_message
                )

                return render(
                    request,
                    "add_product.html",
                    context
                )

            # ----------------------------------------------------
            # Check brand for THIS retailer
            # ----------------------------------------------------
            brand = Brand.objects.filter(
                retailer=retailer,
                brand_name__iexact=brand_name
            ).first()

            # ----------------------------------------------------
            # Create brand if it doesn't exist
            # ----------------------------------------------------
            if brand is None:

                brand = Brand.objects.create(
                    retailer=retailer,
                    brand_name=brand_name
                )

                logger.info(
                    "New brand created. "
                    "Brand=%s, Retailer=%s, User=%s",
                    brand_name,
                    retailer.id,
                    request.user.username
                )

        else:

            # ----------------------------------------------------
            # Existing brand selected from dropdown
            # ----------------------------------------------------
            brand = Brand.objects.filter(
                id=brand_id,
                retailer=retailer
            ).first()

            if brand is None:

                error_message = (
                    "Selected brand does not exist "
                    "or does not belong to this retailer."
                )

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message,
                        },
                        status=400
                    )

                messages.error(
                    request,
                    error_message
                )

                return render(
                    request,
                    "add_product.html",
                    context
                )

        # ========================================================
        # UNIT
        # ========================================================
        if unit_id.startswith("other:"):

            unit_value = unit_id[
                len("other:"):
            ].strip()

            if not unit_value:
                error_message = "Unit name is required."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message,
                        },
                        status=400
                    )

                messages.error(
                    request,
                    error_message
                )

                return render(
                    request,
                    "add_product.html",
                    context
                )

            # ----------------------------------------------------
            # Unit is GLOBAL.
            #
            # User can enter either:
            #     Kilogram
            #     kg
            #
            # We check both name and short_name.
            # ----------------------------------------------------
            unit = Unit.objects.filter(
                Q(name__iexact=unit_value) |
                Q(short_name__iexact=unit_value)
            ).first()

            # ----------------------------------------------------
            # Create new global unit
            # ----------------------------------------------------
            if unit is None:

                unit = Unit.objects.create(
                    name=unit_value,
                    short_name=unit_value[:10]
                )

                logger.info(
                    "New unit created. "
                    "Unit=%s, User=%s",
                    unit_value,
                    request.user.username
                )

        else:

            # ----------------------------------------------------
            # Existing unit selected from dropdown
            # ----------------------------------------------------
            unit = Unit.objects.filter(
                id=unit_id
            ).first()

            if unit is None:

                error_message = (
                    "Selected unit does not exist."
                )

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message,
                        },
                        status=400
                    )

                messages.error(
                    request,
                    error_message
                )

                return render(
                    request,
                    "add_product.html",
                    context
                )

    except Exception:

        logger.exception(
            "Unexpected error while processing "
            "brand/category/unit. User=%s",
            request.user.username
        )

        error_message = (
            "Something went wrong while processing "
            "brand, category, or unit."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=500
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )
    
    # ============================================================
    # DUPLICATE BARCODE VALIDATION
    # ============================================================
    if barcode:

        barcode_exists = Product.objects.filter(
            barcode=barcode
        ).exists()

        if barcode_exists:

            logger.warning(
                "Duplicate barcode attempted while adding product. "
                "Barcode=%s, User=%s",
                barcode,
                request.user.username
            )

            error_message = (
                "A product with this barcode already exists."
            )

            if is_ajax:
                return JsonResponse(
                    {
                        "success": False,
                        "message": error_message,
                        "field": "barcode",
                    },
                    status=409
                )

            messages.error(
                request,
                error_message
            )

            return render(
                request,
                "add_product.html",
                context
            )

    # ============================================================
    # CREATE PRODUCT
    # ============================================================
    try:

        with transaction.atomic():

            product = Product.objects.create(
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

        # --------------------------------------------------------
        # SUCCESS LOG
        # --------------------------------------------------------
        logger.info(
            "Product added successfully. "
            "Product ID=%s, Product=%s, Retailer=%s, "
            "Created By=%s",
            product.id,
            product.product_name,
            retailer.shop_name,
            request.user.username,
        )

        # ========================================================
        # AJAX SUCCESS RESPONSE
        # ========================================================
        if is_ajax:

            return JsonResponse(
                {
                    "success": True,
                    "id": product.id,
                    "product_name": product.product_name,
                    "message": "Product added successfully.",
                },
                status=201
            )

        # ========================================================
        # NORMAL FORM SUCCESS
        # ========================================================
        messages.success(
            request,
            "Product added successfully."
        )

        return redirect("dashboard")

    # ============================================================
    # DATABASE INTEGRITY ERROR
    # ============================================================
    except IntegrityError:

        logger.exception(
            "IntegrityError while adding product. "
            "Product=%s, Barcode=%s, User=%s",
            product_name,
            barcode,
            request.user.username,
        )

        error_message = (
            "A product with this barcode already exists "
            "or another database constraint was violated."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=409
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # UNEXPECTED ERROR
    # ============================================================
    except Exception:

        logger.exception(
            "Unexpected error while adding product=%s",
            product_name
        )

        error_message = (
            "Something went wrong while adding the product. "
            "Please try again later."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message,
                },
                status=500
            )

        messages.error(
            request,
            error_message
        )

        return render(
            request,
            "add_product.html",
            context
        )


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


# GST RATE MAP
GST_RATE_MAP = {
    "none": Decimal("0"),
    "gst5": Decimal("5"),
    "gst12": Decimal("12"),
    "gst18": Decimal("18"),
    "gst28": Decimal("28"),
}

# COMMON DECIMAL VALUES
MONEY_ZERO = Decimal("0.00")

# MONEY HELPER
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

# DECIMAL POST HELPER
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
        retailers = Retailer.objects.filter(is_active=True)
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

        retailer_list = (
            Retailer.objects
            .filter(
                is_active=True
            )
            .order_by(
                "shop_name"
            )
        )
        categories = Category.objects.all()
        brands = Brand.objects.all()

    else:
        retailers = Retailer.objects.filter(user=request.user, is_active=True).first()
        products = (
            Product.objects
            .filter(
                retailer_id=retailers.id,
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
                retailer_id=retailers.id,
                is_active=True
            )
            .order_by(
                "supplier_name"
            )
        )
        brands = Brand.objects.filter(retailer=retailers.id)
        categories = Category.objects.filter(retailer=retailers.id)


        retailer_list = (
            Retailer.objects
            .filter(
                user=request.user,
                is_active=True
            )
            .order_by(
                "shop_name"
            )
        )
    
    units = Unit.objects.all()


    context = {
        "products": products,
        "categories": categories,
        "brands": brands,
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
            retailers = Retailer.objects.filter(user=request.user, is_active=True).first()
            retailer_id = retailers.id if retailers else None

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
            print(retailer,"            #######################")


        except Retailer.DoesNotExist:

            raise ValueError(
                "Selected retailer does not exist "
                "or is inactive."
            )

        print(retailer,"           ddd #######################")
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


        return redirect("add_new_order")


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
        # Base queryset with select_related optimization
        purchases = Purchase.objects.select_related("retailer", "supplier").all()
        supplier_list = Supplier.objects.filter(is_active=True)

        # ROLE-BASED ACCESS CONTROL
        # Admin / Superuser sees everything
        if not (request.user.is_superuser or request.user.is_staff):
            user_retailer = getattr(request.user, 'retailer', request.user)
            purchases = purchases.filter(retailer=user_retailer)
            supplier_list = supplier_list.filter(retailer=user_retailer)

        purchases = purchases.order_by("-bill_date", "-created_at")
        supplier_list = supplier_list.order_by("supplier_name")

        # GET FILTER PARAMETERS
        from_date = request.GET.get("from_date", "").strip()
        to_date = request.GET.get("to_date", "").strip()
        status = request.GET.get("status", "").strip()
        supplier_id = request.GET.get("supplier", "").strip()

        # APPLY FILTERS
        if from_date:
            purchases = purchases.filter(bill_date__gte=from_date)
        if to_date:
            purchases = purchases.filter(bill_date__lte=to_date)
        if status:
            purchases = purchases.filter(payment_status=status)
        if supplier_id:
            purchases = purchases.filter(supplier_id=supplier_id)

        # PAGINATION
        paginator = Paginator(purchases, 25)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

    except Exception:
        logger.exception("Failed to fetch purchase list.")
        messages.error(
            request, "Something went wrong while loading purchases."
        )
        page_obj = Paginator(Purchase.objects.none(), 25).get_page(1)
        supplier_list = Supplier.objects.none()

    context = {
        "purchases": page_obj,
        "page_obj": page_obj,
        "supplier_list": supplier_list,
    }
    return render(request, "purchase_list.html", context)


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

    Supports:
    - Normal GET request for rendering the supplier form.
    - AJAX POST request for creating a supplier and returning JSON.
    """

    # ============================================================
    # GET REQUEST
    # ============================================================
    if request.method != "POST":

        if request.user.is_superuser:
            retailers = Retailer.objects.filter(is_active=True)
        else:
            retailers = Retailer.objects.filter(
                user=request.user,
                is_active=True
            )

        return render(
            request,
            "add_supplier.html",
            {
                "retailers": retailers
            }
        )

    # ============================================================
    # POST REQUEST
    # ============================================================
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        with transaction.atomic():

            # ----------------------------------------------------
            # GET RETAILER
            # ----------------------------------------------------
            
            if request.user.is_superuser:
                retailer_id = request.POST.get("retailer")
            else:
                retailer = Retailer.objects.filter(user=request.user, is_active=True).first()
                retailer_id = retailer.id if retailer else None

            if not retailer_id:
                error_message = "Please select a retailer."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=400
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            # SECURITY:
            # Superuser can create supplier for any active retailer.
            # Normal user can only create supplier for their own retailer.
            if request.user.is_superuser:
                retailer = Retailer.objects.filter(
                    id=retailer_id,
                    is_active=True
                ).first()
            else:
                retailer = Retailer.objects.filter(
                    id=retailer_id,
                    user=request.user,
                    is_active=True
                ).first()

            if retailer is None:
                logger.warning(
                    "Unauthorized or invalid retailer access attempt. "
                    "User ID: %s, Retailer ID: %s",
                    request.user.id,
                    retailer_id
                )

                error_message = (
                    "Retailer does not exist or you are not authorized "
                    "to use this retailer."
                )

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=403
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            # ----------------------------------------------------
            # REQUIRED TEXT FIELDS
            # ----------------------------------------------------
            supplier_name = request.POST.get(
                "supplier_name",
                ""
            ).strip()

            mobile = request.POST.get(
                "mobile",
                ""
            ).strip()

            address = request.POST.get(
                "address",
                ""
            ).strip()

            city = request.POST.get(
                "city",
                ""
            ).strip()

            state = request.POST.get(
                "state",
                ""
            ).strip()

            pincode = request.POST.get(
                "pincode",
                ""
            ).strip()

            required_fields = {
                "Supplier Name": supplier_name,
                "Mobile": mobile,
                "Address": address,
                "City": city,
                "State": state,
                "Pincode": pincode,
            }

            missing_fields = [
                field_name
                for field_name, value in required_fields.items()
                if not value
            ]

            if missing_fields:
                error_message = (
                    "Please fill all required fields: "
                    + ", ".join(missing_fields)
                )

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=400
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            # ----------------------------------------------------
            # MOBILE VALIDATION
            # ----------------------------------------------------
            mobile_digits = "".join(
                character
                for character in mobile
                if character.isdigit()
            )

            if not 10 <= len(mobile_digits) <= 15:
                error_message = "Please enter a valid mobile number."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=400
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            # ----------------------------------------------------
            # DUPLICATE SUPPLIER CHECK
            # ----------------------------------------------------
            if Supplier.objects.filter(
                retailer=retailer,
                supplier_name__iexact=supplier_name
            ).exists():

                logger.warning(
                    "Duplicate supplier '%s' attempted for retailer %s",
                    supplier_name,
                    retailer.id
                )

                error_message = (
                    "Supplier already exists for this retailer."
                )

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=409
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            # ----------------------------------------------------
            # OPTIONAL FIELDS
            # ----------------------------------------------------
            contact_person = request.POST.get(
                "contact_person",
                ""
            ).strip() or None

            alternate_mobile = request.POST.get(
                "alternate_mobile",
                ""
            ).strip() or None

            email = request.POST.get(
                "email",
                ""
            ).strip() or None

            gst_number = request.POST.get(
                "gst_number",
                ""
            ).strip() or None

            pan_number = request.POST.get(
                "pan_number",
                ""
            ).strip() or None

            notes = request.POST.get(
                "notes",
                ""
            ).strip() or None

            # ----------------------------------------------------
            # NUMERIC FIELDS
            # ----------------------------------------------------
            try:
                opening_balance = Decimal(
                    request.POST.get("opening_balance") or "0.00"
                )

                credit_limit = Decimal(
                    request.POST.get("credit_limit") or "0.00"
                )

                credit_days = int(
                    request.POST.get("credit_days") or 0
                )

            except (InvalidOperation, ValueError, TypeError):

                logger.error(
                    "Invalid numeric data received while creating "
                    "supplier. User ID: %s",
                    request.user.id
                )

                error_message = (
                    "Invalid numeric or decimal format provided."
                )

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=400
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            # ----------------------------------------------------
            # ADDITIONAL NUMERIC VALIDATION
            # ----------------------------------------------------
            if opening_balance < 0:
                error_message = "Opening balance cannot be negative."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=400
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            if credit_limit < 0:
                error_message = "Credit limit cannot be negative."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=400
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            if credit_days < 0:
                error_message = "Credit days cannot be negative."

                if is_ajax:
                    return JsonResponse(
                        {
                            "success": False,
                            "message": error_message
                        },
                        status=400
                    )

                messages.error(request, error_message)
                return redirect("add_new_supplier")

            # ----------------------------------------------------
            # ACTIVE STATUS
            # ----------------------------------------------------
            is_active = "is_active" in request.POST

            # ----------------------------------------------------
            # CREATE SUPPLIER
            # ----------------------------------------------------
            supplier = Supplier.objects.create(
                retailer=retailer,
                supplier_name=supplier_name,
                contact_person=contact_person,
                mobile=mobile_digits,
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

            logger.info(
                "Supplier '%s' (ID: %s) created successfully "
                "by User ID %s for Retailer ID %s",
                supplier.supplier_name,
                supplier.id,
                request.user.id,
                retailer.id
            )

            # ====================================================
            # AJAX RESPONSE
            # ====================================================
            if is_ajax:
                return JsonResponse(
                    {
                        "success": True,
                        "id": supplier.id,
                        "supplier_name": supplier.supplier_name,
                        "message": "Supplier added successfully."
                    },
                    status=201
                )

            # ====================================================
            # NORMAL FORM RESPONSE
            # ====================================================
            messages.success(
                request,
                "Supplier added successfully."
            )

            return redirect("add_new_supplier")

    # ============================================================
    # DATABASE / UNEXPECTED ERRORS
    # ============================================================
    except IntegrityError:

        logger.exception(
            "Database integrity error while creating supplier. "
            "User ID: %s",
            request.user.id
        )

        error_message = "Supplier already exists or violates a database constraint."

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message
                },
                status=409
            )

        messages.error(request, error_message)

    except Exception as e:

        logger.exception(
            "Unexpected exception inside add_supplier view: %s",
            str(e)
        )

        error_message = (
            "Something went wrong while adding the supplier. "
            "Please try again."
        )

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": error_message
                },
                status=500
            )

        messages.error(request, error_message)

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

from decimal import Decimal, InvalidOperation
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET, require_POST

from .models import (
    Customer,
    Sale,
    SaleItem,
    Payment,
    CustomerLedger,
    Product,
    Unit,
    Retailer,
)

from .sales import add_sale_item


ZERO = Decimal("0.00")
ONE_HUNDRED = Decimal("100.00")
TWO_PLACES = Decimal("0.01")



def decimal_value(value, field_name, default=ZERO):
    """
    Convert a POST value safely into Decimal.
    """

    if value in (None, ""):
        return default

    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(
            f"Invalid value for {field_name}."
        )

    if value < ZERO:
        raise ValidationError(
            f"{field_name} cannot be negative."
        )

    return value.quantize(TWO_PLACES)


def get_logged_in_retailer(request):
    """
    Return the retailer belonging to the logged-in user.
    """

    if not request.user.is_authenticated:
        raise ValidationError(
            "You must be logged in."
        )

    if request.user.is_superuser:
        retailer = (
                    Retailer.objects
                    .filter(
                        user=2,
                        is_active=True,
                    )
                    .first()
                )
        print(retailer,"      LLLLLLLLLLLLLLLLLLLLLL")
    else:

        retailer = (
            Retailer.objects
            .filter(
                user=request.user,
                is_active=True,
            )
            .first()
        )

    if retailer is None:
        raise ValidationError(
            "No active retailer is associated with this user."
        )

    return retailer


def get_customer_ledger_balance(customer):
    """
    Return customer's current outstanding balance.
    """

    last_entry = (
        CustomerLedger.objects
        .filter(customer=customer)
        .order_by("-date", "-id")
        .first()
    )

    if last_entry:
        return last_entry.balance

    return customer.opening_balance or ZERO


def create_customer_ledger_entry(
    *,
    customer,
    sale=None,
    payment=None,
    debit=ZERO,
    credit=ZERO,
    entry_date,
    remarks="",
):
    """
    Create one customer ledger entry.

    Debit  = customer owes more.
    Credit = customer paid money.
    """

    debit = Decimal(debit).quantize(TWO_PLACES)
    credit = Decimal(credit).quantize(TWO_PLACES)

    if debit < ZERO:
        raise ValidationError(
            "Ledger debit cannot be negative."
        )

    if credit < ZERO:
        raise ValidationError(
            "Ledger credit cannot be negative."
        )

    if debit > ZERO and credit > ZERO:
        raise ValidationError(
            "Ledger entry cannot contain both debit and credit."
        )

    previous_balance = get_customer_ledger_balance(
        customer
    )

    balance = (
        previous_balance
        + debit
        - credit
    ).quantize(TWO_PLACES)

    ledger_entry = CustomerLedger(
        customer=customer,
        sale=sale,
        payment=payment,
        date=entry_date,
        debit=debit,
        credit=credit,
        balance=balance,
        remarks=remarks,
    )

    ledger_entry.full_clean()
    ledger_entry.save()

    return ledger_entry


def calculate_sale_totals(items):
    """
    Calculate invoice totals from trusted server-side values.
    """

    subtotal = ZERO
    total_discount = ZERO
    total_gst = ZERO

    for item in items:

        gross_amount = (
            item["quantity"]
            * item["selling_price"]
        )

        discount = item["discount"]

        taxable_amount = (
            gross_amount - discount
        )

        if taxable_amount < ZERO:
            raise ValidationError(
                f"Discount cannot be greater than "
                f"the amount for "
                f"'{item['product'].product_name}'."
            )

        gst_amount = (
            taxable_amount
            * item["gst"]
            / ONE_HUNDRED
        )

        subtotal += gross_amount
        total_discount += discount
        total_gst += gst_amount

    grand_total = (
        subtotal
        - total_discount
        + total_gst
    )

    return {
        "subtotal": subtotal.quantize(TWO_PLACES),
        "discount": total_discount.quantize(TWO_PLACES),
        "gst": total_gst.quantize(TWO_PLACES),
        "grand_total": grand_total.quantize(TWO_PLACES),
    }


@login_required
def sales_create(request):
    """
    Create a new sales invoice.

    GET:
        Display customers, products and units.

    POST:
        - Validate customer
        - Read dynamic product rows
        - Validate products
        - Validate units
        - Validate quantity
        - Validate stock
        - Get price/MRP/GST from database
        - Calculate totals server-side
        - Validate payment
        - Validate credit limit
        - Create Sale
        - Create SaleItems
        - Deduct stock
        - Create payment
        - Create customer ledger
        - Commit everything atomically
    """

    retailer = None

    # ==========================================================
    # GET RETAILER
    # ==========================================================

    try:
        retailer = get_logged_in_retailer(request)

    except ValidationError as exc:

        error_message = " ".join(
            str(message)
            for message in exc.messages
        )

        messages.error(
            request,
            error_message
        )

        logger.warning(
            "Retailer validation failed. "
            "user_id=%s error=%s",
            request.user.id,
            error_message,
        )

        return redirect("dashboard")

    # ==========================================================
    # GET
    # ==========================================================

    if request.method == "GET":

        try:

            customers = (
                Customer.objects
                .filter(
                    retailer=retailer,
                    is_active=True,
                )
                .order_by("customer_name")
            )

            products = (
                Product.objects
                .filter(
                    retailer=retailer,
                    is_active=True,
                )
                .select_related("unit")
                .order_by("product_name")
            )

            units = (
                Unit.objects
                .all()
                .order_by("name")
            )

            today = date.today()

            prefix = f"INV-{today.year}-"

            last_sale = (
                Sale.objects
                .filter(
                    retailer=retailer,
                    invoice_number__startswith=prefix,
                )
                .order_by("-invoice_number")
                .first()
            )

            last_number = 0

            if last_sale:
                try:
                    last_number = int(
                        last_sale.invoice_number
                        .split("-")[-1]
                    )
                except (ValueError, IndexError):
                    last_number = 0

            next_invoice_number = (
                f"{prefix}{last_number + 1:06d}"
            )
            if request.user.is_superuser:
                retailer = Retailer.objects.filter(is_active = True)
                customers = (
                                Customer.objects
                                .filter(
                                    is_active=True,
                                )
                                .order_by("customer_name")
                            )

            context = {
                "customers": customers,
                "products": products,
                "units": units,
                "today": today,
                "next_invoice_number": next_invoice_number,
                "retailers": retailer,
            }

            return render(
                request,
                "sale_create.html",
                context,
            )

        except Exception:

            logger.exception(
                "Unexpected error while loading "
                "sale create page. user_id=%s retailer_id=%s",
                request.user.id,
                getattr(retailer, "id", None),
            )

            messages.error(
                request,
                "Unable to load the sales page. "
                "Please try again.",
            )

            return redirect("dashboard")

    # ==========================================================
    # POST
    # ==========================================================

    try:

        # ======================================================
        # 1. CUSTOMER
        # ======================================================

        customer_id = (
            request.POST.get("customer") or ""
        ).strip()

        if not customer_id:
            raise ValidationError(
                "Please select a customer."
            )

        customer = (
            Customer.objects
            .filter(
                pk=customer_id,
                retailer=retailer,
                is_active=True,
            )
            .first()
        )

        if customer is None:
            raise ValidationError(
                "Selected customer does not exist."
            )

        # ======================================================
        # 2. INVOICE DATE
        # ======================================================

        invoice_date = date.today()

        # ======================================================
        # 3. READ DYNAMIC PRODUCT ROWS
        # ======================================================
        #
        # IMPORTANT:
        #
        # HTML sends:
        #
        # items[1][product]
        # items[1][unit]
        # items[1][selling_price]
        # items[1][mrp]
        # items[1][gst]
        # items[1][quantity]
        # items[1][discount]
        #
        # We therefore cannot use:
        #
        # request.POST.getlist("product[]")
        #
        # ======================================================

        processed_items = []

        item_indexes = set()

        for key in request.POST.keys():
            match = re.match(r"^items\[(\d+)\]\[product\]$", key)

            if match:
                row_number = match.group(1)
                item_indexes.add(row_number)

        if not item_indexes:
            raise ValidationError("Please add at least one product.")

        sorted_indexes = sorted(
            item_indexes,
            key=int
        )

        # Prevent duplicate products
        processed_product_ids = set()

        # ======================================================
        # 4. PROCESS EACH PRODUCT
        # ======================================================

        for row_number in sorted_indexes:

            product_key = (
                f"items[{row_number}][product]"
            )

            unit_key = (
                f"items[{row_number}][unit]"
            )

            selling_price_key = (
                f"items[{row_number}][selling_price]"
            )

            mrp_key = (
                f"items[{row_number}][mrp]"
            )

            gst_key = (
                f"items[{row_number}][gst]"
            )

            quantity_key = (
                f"items[{row_number}][quantity]"
            )

            discount_key = (
                f"items[{row_number}][discount]"
            )

            product_id = (
                request.POST.get(product_key) or ""
            ).strip()

            unit_id = (
                request.POST.get(unit_key) or ""
            ).strip()

            if not product_id:

                raise ValidationError(
                    f"Product is missing in row "
                    f"{row_number}."
                )

            # ==================================================
            # DUPLICATE PRODUCT
            # ==================================================

            if product_id in processed_product_ids:

                raise ValidationError(
                    "The same product cannot be added "
                    "multiple times to the same invoice."
                )

            processed_product_ids.add(
                product_id
            )

            # ==================================================
            # PRODUCT
            # ==================================================

            product = (
                Product.objects
                .select_for_update()
                .filter(
                    pk=product_id,
                    retailer=retailer,
                    is_active=True,
                )
                .first()
            )

            if product is None:

                raise ValidationError(
                    f"Product in row {row_number} "
                    f"does not exist."
                )

            # ==================================================
            # UNIT
            # ==================================================

            if not unit_id:

                raise ValidationError(
                    f"Unit is missing for "
                    f"'{product.product_name}'."
                )

            unit = (
                Unit.objects
                .filter(pk=unit_id)
                .first()
            )

            if unit is None:

                raise ValidationError(
                    f"Invalid unit for "
                    f"'{product.product_name}'."
                )

            # ==================================================
            # IMPORTANT UNIT CHECK
            # ==================================================

            if product.unit_id != unit.id:

                raise ValidationError(
                    f"Invalid unit selected for "
                    f"'{product.product_name}'."
                )

            # ==================================================
            # QUANTITY
            # ==================================================

            quantity = decimal_value(
                request.POST.get(quantity_key),
                f"Quantity for {product.product_name}",
            )

            if quantity <= ZERO:

                raise ValidationError(
                    f"Quantity for "
                    f"'{product.product_name}' "
                    f"must be greater than zero."
                )

            # ==================================================
            # STOCK
            # ==================================================

            available_stock = (
                product.current_stock or ZERO
            )

            if quantity > available_stock:

                raise ValidationError(
                    f"Insufficient stock for "
                    f"'{product.product_name}'. "
                    f"Available stock: "
                    f"{available_stock}. "
                    f"Requested quantity: "
                    f"{quantity}."
                )

            # ==================================================
            # PRICE
            # ==================================================
            #
            # NEVER TRUST PRICE FROM FRONTEND
            #
            # Frontend may display it.
            # Backend takes actual value from Product.
            #
            # ==================================================

            selling_price = Decimal(
                str(product.selling_price)
            ).quantize(TWO_PLACES)

            mrp = (
                Decimal(str(product.mrp))
                if product.mrp is not None
                else None
            )

            if mrp is not None:

                mrp = mrp.quantize(
                    TWO_PLACES
                )

            # ==================================================
            # GST
            # ==================================================

            gst = Decimal(
                str(
                    getattr(
                        product,
                        "gst_percentage",
                        ZERO
                    ) or ZERO
                )
            ).quantize(TWO_PLACES)

            # ==================================================
            # DISCOUNT
            # ==================================================

            discount = decimal_value(
                request.POST.get(discount_key),
                f"Discount for {product.product_name}",
            )

            # ==================================================
            # CALCULATE LINE
            # ==================================================

            gross_amount = (
                quantity * selling_price
            ).quantize(TWO_PLACES)

            if discount > gross_amount:

                raise ValidationError(
                    f"Discount for "
                    f"'{product.product_name}' "
                    f"cannot exceed "
                    f"₹{gross_amount}."
                )

            taxable_amount = (
                gross_amount - discount
            ).quantize(TWO_PLACES)

            gst_amount = (
                taxable_amount
                * gst
                / ONE_HUNDRED
            ).quantize(TWO_PLACES)

            line_amount = (
                taxable_amount
                + gst_amount
            ).quantize(TWO_PLACES)

            processed_items.append(
                {
                    "product": product,
                    "product_id": product.id,
                    "unit": unit,
                    "unit_id": unit.id,
                    "quantity": quantity,
                    "selling_price": selling_price,
                    "mrp": mrp,
                    "gst": gst,
                    "discount": discount,
                    "gst_amount": gst_amount,
                    "amount": line_amount,
                }
            )

        # ======================================================
        # 5. SERVER-SIDE TOTALS
        # ======================================================

        totals = calculate_sale_totals(
            processed_items
        )

        subtotal = totals["subtotal"]

        total_discount = totals["discount"]

        total_gst = totals["gst"]

        grand_total = totals["grand_total"]

        if grand_total <= ZERO:

            raise ValidationError(
                "Grand total must be greater than zero."
            )

        # ======================================================
        # 6. PAYMENT
        # ======================================================

        payment_type = (
            request.POST.get("payment_type") or ""
        ).strip()

        paid_amount = decimal_value(
            request.POST.get("paid_amount"),
            "Paid amount",
        )

        if paid_amount > grand_total:

            raise ValidationError(
                "Paid amount cannot exceed "
                f"grand total of ₹{grand_total}."
            )

        due_amount = (
            grand_total - paid_amount
        ).quantize(TWO_PLACES)

        # ======================================================
        # PAYMENT TYPE VALIDATION
        # ======================================================

        valid_payment_types = {
            Sale.PAYMENT_TYPE_CASH,
            Sale.PAYMENT_TYPE_UPI,
            Sale.PAYMENT_TYPE_BANK,
            Sale.PAYMENT_TYPE_CHEQUE,
            Sale.PAYMENT_TYPE_CREDIT,
        }

        if payment_type not in valid_payment_types:

            raise ValidationError(
                "Please select a valid payment type."
            )

        # ======================================================
        # CREDIT SALE
        # ======================================================

        if payment_type == Sale.PAYMENT_TYPE_CREDIT:

            if paid_amount != ZERO:

                raise ValidationError(
                    "Credit sales cannot have "
                    "a paid amount."
                )

        # ======================================================
        # NORMAL PAYMENT
        # ======================================================

        elif paid_amount == ZERO:

            raise ValidationError(
                "Please enter the paid amount."
            )

        # ======================================================
        # REMARKS
        # ======================================================

        remarks = (
            request.POST.get("remarks") or ""
        ).strip()

        # ======================================================
        # 7. ATOMIC TRANSACTION
        # ======================================================

        with transaction.atomic():

            # --------------------------------------------------
            # LOCK CUSTOMER
            # --------------------------------------------------

            customer = (
                Customer.objects
                .select_for_update()
                .get(
                    pk=customer.pk,
                    retailer=retailer,
                    is_active=True,
                )
            )

            # --------------------------------------------------
            # CURRENT CUSTOMER BALANCE
            # --------------------------------------------------

            current_balance = (
                get_customer_ledger_balance(
                    customer
                )
            )

            # --------------------------------------------------
            # CREDIT LIMIT
            # --------------------------------------------------

            credit_limit = (
                customer.credit_limit or ZERO
            )

            projected_balance = (
                current_balance
                + due_amount
            ).quantize(TWO_PLACES)

            if (
                due_amount > ZERO
                and credit_limit > ZERO
                and projected_balance > credit_limit
            ):

                raise ValidationError(
                    f"Credit limit exceeded for "
                    f"'{customer.customer_name}'. "
                    f"Current outstanding: "
                    f"₹{current_balance}. "
                    f"New due: ₹{due_amount}. "
                    f"Credit limit: "
                    f"₹{credit_limit}."
                )

            # --------------------------------------------------
            # CREATE SALE
            # --------------------------------------------------

            sale = Sale(
                retailer=retailer,
                customer=customer,
                invoice_date=invoice_date,
                subtotal=subtotal,
                discount=total_discount,
                gst=total_gst,
                grand_total=grand_total,
                paid_amount=paid_amount,
                payment_type=payment_type,
                remarks=remarks,
            )

            # Model validation
            sale.full_clean()

            # Sale.save() generates invoice number,
            # due amount and payment status.
            sale.save()

            logger.info(
                "Sale created. sale_id=%s "
                "invoice=%s user_id=%s retailer_id=%s",
                sale.id,
                sale.invoice_number,
                request.user.id,
                retailer.id,
            )

            # --------------------------------------------------
            # CREATE SALE ITEMS + DEDUCT STOCK
            # --------------------------------------------------

            for item in processed_items:

                add_sale_item(
                    sale=sale,
                    product_id=item["product_id"],
                    unit_id=item["unit_id"],
                    quantity=item["quantity"],
                    selling_price=item["selling_price"],
                    mrp=item["mrp"],
                    gst=item["gst"],
                    discount=item["discount"],
                )

            # --------------------------------------------------
            # CUSTOMER LEDGER - SALE DEBIT
            # --------------------------------------------------

            create_customer_ledger_entry(
                customer=customer,
                sale=sale,
                debit=grand_total,
                credit=ZERO,
                entry_date=invoice_date,
                remarks=(
                    f"Sale invoice "
                    f"{sale.invoice_number}"
                ),
            )

            # --------------------------------------------------
            # PAYMENT
            # --------------------------------------------------

            payment = None

            if paid_amount > ZERO:

                if payment_type == Sale.PAYMENT_TYPE_CREDIT:

                    raise ValidationError(
                        "Credit payment cannot be recorded."
                    )

                payment = Payment(
                    retailer=retailer,
                    customer=customer,
                    sale=sale,
                    payment_date=invoice_date,
                    amount=paid_amount,
                    payment_type=payment_type,
                    payment_reference=(
                        request.POST.get(
                            "payment_reference"
                        ) or None
                    ),
                    receipt_number=(
                        request.POST.get(
                            "receipt_number"
                        ) or None
                    ),
                    remarks=remarks,
                )

                payment.full_clean()
                payment.save()

                # --------------------------------------------------
                # CUSTOMER LEDGER - PAYMENT CREDIT
                # --------------------------------------------------

                create_customer_ledger_entry(
                    customer=customer,
                    payment=payment,
                    debit=ZERO,
                    credit=paid_amount,
                    entry_date=invoice_date,
                    remarks=(
                        f"Payment received for "
                        f"invoice "
                        f"{sale.invoice_number}"
                    ),
                )

            # --------------------------------------------------
            # FINAL SALE VALIDATION
            # --------------------------------------------------

            sale.refresh_from_db()

            if sale.due_amount != due_amount:

                raise ValidationError(
                    "Payment calculation mismatch."
                )

            logger.info(
                "Sale transaction completed successfully. "
                "sale_id=%s invoice=%s paid=%s due=%s "
                "user_id=%s retailer_id=%s",
                sale.id,
                sale.invoice_number,
                paid_amount,
                due_amount,
                request.user.id,
                retailer.id,
            )

        # ======================================================
        # SUCCESS
        # ======================================================

        action = (
            request.POST.get("action") or "save"
        ).strip()

        messages.success(
            request,
            f"Sale {sale.invoice_number} "
            f"created successfully."
        )

        if action == "save_print":

            return redirect(
                "sale_print",
                sale_id=sale.id,
            )

        return redirect(
            "sale_create"
        )

    # ==========================================================
    # VALIDATION ERROR
    # ==========================================================

    except ValidationError as exc:

        error_message = " ".join(
            str(message)
            for message in exc.messages
        )

        logger.warning(
            "Sale validation failed. "
            "user_id=%s retailer_id=%s error=%s",
            request.user.id,
            getattr(retailer, "id", None),
            error_message,
        )

        messages.error(
            request,
            error_message,
        )

        return redirect(
            "sale_create"
        )

    # ==========================================================
    # DATABASE ERROR
    # ==========================================================

    except IntegrityError:

        logger.exception(
            "Database integrity error while "
            "creating sale. "
            "user_id=%s retailer_id=%s",
            request.user.id,
            getattr(retailer, "id", None),
        )

        messages.error(
            request,
            "Unable to create the sale because "
            "of a database conflict. "
            "Please try again.",
        )

        return redirect(
            "sale_create"
        )

    # ==========================================================
    # UNEXPECTED ERROR
    # ==========================================================

    except Exception:

        logger.exception(
            "Unexpected error while creating sale. "
            "user_id=%s retailer_id=%s",
            request.user.id,
            getattr(retailer, "id", None),
        )

        messages.error(
            request,
            "An unexpected error occurred while "
            "creating the sale. Please try again.",
        )

        return redirect(
            "sale_create"
        )




@require_POST
@login_required
def create_customer_ajax(request):
    """
    Create customer from the Add Customer modal.

    Mobile number is unique per retailer.
    """
    try:

        retailer = get_logged_in_retailer(request)

        customer_name = (
            request.POST.get("customer_name") or ""
        ).strip()

        mobile = (
            request.POST.get("mobile") or ""
        ).strip()

        email = (
            request.POST.get("email") or ""
        ).strip()

        gst_number = (
            request.POST.get("gst_number") or ""
        ).strip()

        address = (
            request.POST.get("address") or ""
        ).strip()

        opening_balance = decimal_value(
            request.POST.get("opening_balance"),
            "Opening balance",
        )

        credit_limit = decimal_value(
            request.POST.get("credit_limit"),
            "Credit limit",
        )

        # ------------------------------------------------------
        # NAME
        # ------------------------------------------------------

        if not customer_name:
            raise ValidationError(
                "Customer name is required."
            )

        if len(customer_name) > 200:
            raise ValidationError(
                "Customer name cannot exceed 200 characters."
            )

        # ------------------------------------------------------
        # MOBILE
        # ------------------------------------------------------

        if not mobile:
            raise ValidationError(
                "Mobile number is required."
            )

        # Keep only digits for validation.
        normalized_mobile = "".join(
            character
            for character in mobile
            if character.isdigit()
        )

        if len(normalized_mobile) != 10:
            raise ValidationError(
                "Please enter a valid 10-digit mobile number."
            )

        # ------------------------------------------------------
        # DUPLICATE CHECK
        # ------------------------------------------------------

        existing_customer = (
            Customer.objects
            .filter(
                retailer=retailer,
                mobile=normalized_mobile,
            )
            .first()
        )

        if existing_customer:

            return JsonResponse(
                {
                    "success": False,
                    "exists": True,
                    "message": (
                        "A customer with this mobile number "
                        "already exists."
                    ),
                    "customer": {
                        "id": existing_customer.id,
                        "name": existing_customer.customer_name,
                        "mobile": existing_customer.mobile,
                    },
                },
                status=409,
            )

        # ------------------------------------------------------
        # CREATE CUSTOMER
        # ------------------------------------------------------

        with transaction.atomic():

            customer = Customer.objects.create(
                retailer=retailer,
                customer_name=customer_name,
                mobile=normalized_mobile,
                email=email or None,
                gst_number=gst_number or None,
                address=address or None,
                opening_balance=opening_balance,
                credit_limit=credit_limit,
                is_active=True,
            )

        logger.info(
            "Customer created successfully. "
            "customer_id=%s retailer_id=%s",
            customer.id,
            retailer.id,
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Customer created successfully.",
                "customer": {
                    "id": customer.id,
                    "name": customer.customer_name,
                    "mobile": customer.mobile,
                    "email": customer.email or "",
                    "address": customer.address or "",
                    "gst_number": customer.gst_number or "",
                    "credit_limit": str(
                        customer.credit_limit
                    ),
                    "opening_balance": str(
                        customer.opening_balance
                    ),
                },
            },
            status=201,
        )

    except ValidationError as exc:

        return JsonResponse(
            {
                "success": False,
                "message": " ".join(
                    str(message)
                    for message in exc.messages
                ),
            },
            status=400,
        )

    except IntegrityError:

        logger.exception(
            "Duplicate customer/mobile race condition."
        )

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "A customer with this mobile number "
                    "already exists."
                ),
            },
            status=409,
        )

    except Exception:

        logger.exception(
            "Unexpected error while creating customer."
        )

        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Unable to create customer. "
                    "Please try again."
                ),
            },
            status=500,
        )


@require_GET
@login_required
def sale_product_data(request, product_id):

    try:
        retailer = get_logged_in_retailer(request)
        product = (
            Product.objects
            .filter(
                pk=product_id,
                retailer=retailer,
                is_active=True,
            )
            .first()
        )

        if product is None:
            return JsonResponse(
                {
                    "success": False,
                    "message": "Product not found.",
                },
                status=404,
            )

        return JsonResponse(
            {
                "success": True,
                "product": {
                    "id": product.id,
                    "name": product.product_name,

                    "stock": str(
                        product.current_stock or ZERO
                    ),

                    "selling_price": str(
                        product.selling_price
                    ),

                    "mrp": (
                        str(product.mrp)
                        if product.mrp is not None
                        else ""
                    ),

                    "gst": str(
                        product.gst or ZERO
                    ),
                },
            }
        )

    except ValidationError as exc:

        return JsonResponse(
            {
                "success": False,
                "message": str(exc),
            },
            status=400,
        )

    except Exception:

        logger.exception(
            "Unable to fetch product data."
        )

        return JsonResponse(
            {
                "success": False,
                "message": "Unable to fetch product.",
            },
            status=500,
        )














































# from decimal import Decimal, InvalidOperation
# from datetime import date

# from django.contrib import messages
# from django.contrib.auth.decorators import login_required
# from django.core.exceptions import ValidationError
# from django.db import IntegrityError, transaction
# from django.http import JsonResponse
# from django.shortcuts import redirect, render
# from django.views.decorators.http import require_POST
# from django.views.decorators.http import require_GET, require_POST

# from .models import (
#     Customer,
#     Sale,
#     SaleItem,
#     Payment,
#     CustomerLedger,
#     Product,
#     Unit,
#     Retailer,
# )

# from .sales import add_sale_item


# ZERO = Decimal("0.00")
# ONE_HUNDRED = Decimal("100.00")
# TWO_PLACES = Decimal("0.01")



# def decimal_value(value, field_name, default=ZERO):
#     """
#     Convert a POST value safely into Decimal.
#     """

#     if value in (None, ""):
#         return default

#     try:
#         value = Decimal(str(value))
#     except (InvalidOperation, ValueError, TypeError):
#         raise ValidationError(
#             f"Invalid value for {field_name}."
#         )

#     if value < ZERO:
#         raise ValidationError(
#             f"{field_name} cannot be negative."
#         )

#     return value.quantize(TWO_PLACES)


# def get_logged_in_retailer(request):
#     """
#     Return the retailer belonging to the logged-in user.
#     """

#     if not request.user.is_authenticated:
#         raise ValidationError(
#             "You must be logged in."
#         )

#     if request.user.is_superuser:
#         redirect 

#     retailer = (
#         Retailer.objects
#         .filter(
#             user=request.user,
#             is_active=True,
#         )
#         .first()
#     )

#     if retailer is None:
#         raise ValidationError(
#             "No active retailer is associated with this user."
#         )

#     return retailer


# def get_customer_ledger_balance(customer):
#     """
#     Return customer's current outstanding balance.
#     """

#     last_entry = (
#         CustomerLedger.objects
#         .filter(customer=customer)
#         .order_by("-date", "-id")
#         .first()
#     )

#     if last_entry:
#         return last_entry.balance

#     return customer.opening_balance or ZERO


# def create_customer_ledger_entry(
#     *,
#     customer,
#     sale=None,
#     payment=None,
#     debit=ZERO,
#     credit=ZERO,
#     entry_date,
#     remarks="",
# ):
#     """
#     Create one customer ledger entry.

#     Debit  = customer owes more.
#     Credit = customer paid money.
#     """

#     debit = Decimal(debit).quantize(TWO_PLACES)
#     credit = Decimal(credit).quantize(TWO_PLACES)

#     if debit < ZERO:
#         raise ValidationError(
#             "Ledger debit cannot be negative."
#         )

#     if credit < ZERO:
#         raise ValidationError(
#             "Ledger credit cannot be negative."
#         )

#     if debit > ZERO and credit > ZERO:
#         raise ValidationError(
#             "Ledger entry cannot contain both debit and credit."
#         )

#     previous_balance = get_customer_ledger_balance(
#         customer
#     )

#     balance = (
#         previous_balance
#         + debit
#         - credit
#     ).quantize(TWO_PLACES)

#     ledger_entry = CustomerLedger(
#         customer=customer,
#         sale=sale,
#         payment=payment,
#         date=entry_date,
#         debit=debit,
#         credit=credit,
#         balance=balance,
#         remarks=remarks,
#     )

#     ledger_entry.full_clean()
#     ledger_entry.save()

#     return ledger_entry


# def calculate_sale_totals(items):
#     """
#     Calculate invoice totals from trusted server-side values.
#     """

#     subtotal = ZERO
#     total_discount = ZERO
#     total_gst = ZERO

#     for item in items:

#         gross_amount = (
#             item["quantity"]
#             * item["selling_price"]
#         )

#         discount = item["discount"]

#         taxable_amount = (
#             gross_amount - discount
#         )

#         if taxable_amount < ZERO:
#             raise ValidationError(
#                 f"Discount cannot be greater than "
#                 f"the amount for "
#                 f"'{item['product'].product_name}'."
#             )

#         gst_amount = (
#             taxable_amount
#             * item["gst"]
#             / ONE_HUNDRED
#         )

#         subtotal += gross_amount
#         total_discount += discount
#         total_gst += gst_amount

#     grand_total = (
#         subtotal
#         - total_discount
#         + total_gst
#     )

#     return {
#         "subtotal": subtotal.quantize(TWO_PLACES),
#         "discount": total_discount.quantize(TWO_PLACES),
#         "gst": total_gst.quantize(TWO_PLACES),
#         "grand_total": grand_total.quantize(TWO_PLACES),
#     }


# @login_required
# def sales_create(request):
#     """
#     Create a new sales invoice.

#     GET:
#         Display customers, products and units.

#     POST:
#         - Validate customer
#         - Read dynamic product rows
#         - Validate products
#         - Validate units
#         - Validate quantity
#         - Validate stock
#         - Get price/MRP/GST from database
#         - Calculate totals server-side
#         - Validate payment
#         - Validate credit limit
#         - Create Sale
#         - Create SaleItems
#         - Deduct stock
#         - Create payment
#         - Create customer ledger
#         - Commit everything atomically
#     """

#     retailer = None

#     # ==========================================================
#     # GET RETAILER
#     # ==========================================================

#     try:
#         retailer = get_logged_in_retailer(request)

#     except ValidationError as exc:

#         error_message = " ".join(
#             str(message)
#             for message in exc.messages
#         )

#         messages.error(
#             request,
#             error_message
#         )

#         logger.warning(
#             "Retailer validation failed. "
#             "user_id=%s error=%s",
#             request.user.id,
#             error_message,
#         )

#         return redirect("dashboard")

#     # ==========================================================
#     # GET
#     # ==========================================================

#     if request.method == "GET":

#         try:

#             customers = (
#                 Customer.objects
#                 .filter(
#                     retailer=retailer,
#                     is_active=True,
#                 )
#                 .order_by("customer_name")
#             )

#             products = (
#                 Product.objects
#                 .filter(
#                     retailer=retailer,
#                     is_active=True,
#                 )
#                 .select_related("unit")
#                 .order_by("product_name")
#             )

#             units = (
#                 Unit.objects
#                 .all()
#                 .order_by("name")
#             )

#             today = date.today()

#             prefix = f"INV-{today.year}-"

#             last_sale = (
#                 Sale.objects
#                 .filter(
#                     retailer=retailer,
#                     invoice_number__startswith=prefix,
#                 )
#                 .order_by("-invoice_number")
#                 .first()
#             )

#             last_number = 0

#             if last_sale:
#                 try:
#                     last_number = int(
#                         last_sale.invoice_number
#                         .split("-")[-1]
#                     )
#                 except (ValueError, IndexError):
#                     last_number = 0

#             next_invoice_number = (
#                 f"{prefix}{last_number + 1:06d}"
#             )

#             context = {
#                 "customers": customers,
#                 "products": products,
#                 "units": units,
#                 "today": today,
#                 "next_invoice_number": next_invoice_number,
#                 "retailers": retailer,
#             }

#             return render(
#                 request,
#                 "sale_create.html",
#                 context,
#             )

#         except Exception:

#             logger.exception(
#                 "Unexpected error while loading "
#                 "sale create page. user_id=%s retailer_id=%s",
#                 request.user.id,
#                 getattr(retailer, "id", None),
#             )

#             messages.error(
#                 request,
#                 "Unable to load the sales page. "
#                 "Please try again.",
#             )

#             return redirect("dashboard")

#     # ==========================================================
#     # POST
#     # ==========================================================

#     try:

#         # ======================================================
#         # 1. CUSTOMER
#         # ======================================================

#         customer_id = (
#             request.POST.get("customer") or ""
#         ).strip()

#         if not customer_id:
#             raise ValidationError(
#                 "Please select a customer."
#             )

#         customer = (
#             Customer.objects
#             .filter(
#                 pk=customer_id,
#                 retailer=retailer,
#                 is_active=True,
#             )
#             .first()
#         )

#         if customer is None:
#             raise ValidationError(
#                 "Selected customer does not exist."
#             )

#         # ======================================================
#         # 2. INVOICE DATE
#         # ======================================================

#         invoice_date = date.today()

#         # ======================================================
#         # 3. READ DYNAMIC PRODUCT ROWS
#         # ======================================================
#         #
#         # IMPORTANT:
#         #
#         # HTML sends:
#         #
#         # items[1][product]
#         # items[1][unit]
#         # items[1][selling_price]
#         # items[1][mrp]
#         # items[1][gst]
#         # items[1][quantity]
#         # items[1][discount]
#         #
#         # We therefore cannot use:
#         #
#         # request.POST.getlist("product[]")
#         #
#         # ======================================================

#         processed_items = []

#         item_indexes = set()

#         for key in request.POST.keys():
#             match = re.match(r"^items\[(\d+)\]\[product\]$", key)

#             if match:
#                 row_number = match.group(1)
#                 item_indexes.add(row_number)

#         if not item_indexes:
#             raise ValidationError("Please add at least one product.")

#         sorted_indexes = sorted(
#             item_indexes,
#             key=int
#         )

#         # Prevent duplicate products
#         processed_product_ids = set()

#         # ======================================================
#         # 4. PROCESS EACH PRODUCT
#         # ======================================================

#         for row_number in sorted_indexes:

#             product_key = (
#                 f"items[{row_number}][product]"
#             )

#             unit_key = (
#                 f"items[{row_number}][unit]"
#             )

#             selling_price_key = (
#                 f"items[{row_number}][selling_price]"
#             )

#             mrp_key = (
#                 f"items[{row_number}][mrp]"
#             )

#             gst_key = (
#                 f"items[{row_number}][gst]"
#             )

#             quantity_key = (
#                 f"items[{row_number}][quantity]"
#             )

#             discount_key = (
#                 f"items[{row_number}][discount]"
#             )

#             product_id = (
#                 request.POST.get(product_key) or ""
#             ).strip()

#             unit_id = (
#                 request.POST.get(unit_key) or ""
#             ).strip()

#             if not product_id:

#                 raise ValidationError(
#                     f"Product is missing in row "
#                     f"{row_number}."
#                 )

#             # ==================================================
#             # DUPLICATE PRODUCT
#             # ==================================================

#             if product_id in processed_product_ids:

#                 raise ValidationError(
#                     "The same product cannot be added "
#                     "multiple times to the same invoice."
#                 )

#             processed_product_ids.add(
#                 product_id
#             )

#             # ==================================================
#             # PRODUCT
#             # ==================================================

#             product = (
#                 Product.objects
#                 .select_for_update()
#                 .filter(
#                     pk=product_id,
#                     retailer=retailer,
#                     is_active=True,
#                 )
#                 .first()
#             )

#             if product is None:

#                 raise ValidationError(
#                     f"Product in row {row_number} "
#                     f"does not exist."
#                 )

#             # ==================================================
#             # UNIT
#             # ==================================================

#             if not unit_id:

#                 raise ValidationError(
#                     f"Unit is missing for "
#                     f"'{product.product_name}'."
#                 )

#             unit = (
#                 Unit.objects
#                 .filter(pk=unit_id)
#                 .first()
#             )

#             if unit is None:

#                 raise ValidationError(
#                     f"Invalid unit for "
#                     f"'{product.product_name}'."
#                 )

#             # ==================================================
#             # IMPORTANT UNIT CHECK
#             # ==================================================

#             if product.unit_id != unit.id:

#                 raise ValidationError(
#                     f"Invalid unit selected for "
#                     f"'{product.product_name}'."
#                 )

#             # ==================================================
#             # QUANTITY
#             # ==================================================

#             quantity = decimal_value(
#                 request.POST.get(quantity_key),
#                 f"Quantity for {product.product_name}",
#             )

#             if quantity <= ZERO:

#                 raise ValidationError(
#                     f"Quantity for "
#                     f"'{product.product_name}' "
#                     f"must be greater than zero."
#                 )

#             # ==================================================
#             # STOCK
#             # ==================================================

#             available_stock = (
#                 product.current_stock or ZERO
#             )

#             if quantity > available_stock:

#                 raise ValidationError(
#                     f"Insufficient stock for "
#                     f"'{product.product_name}'. "
#                     f"Available stock: "
#                     f"{available_stock}. "
#                     f"Requested quantity: "
#                     f"{quantity}."
#                 )

#             # ==================================================
#             # PRICE
#             # ==================================================
#             #
#             # NEVER TRUST PRICE FROM FRONTEND
#             #
#             # Frontend may display it.
#             # Backend takes actual value from Product.
#             #
#             # ==================================================

#             selling_price = Decimal(
#                 str(product.selling_price)
#             ).quantize(TWO_PLACES)

#             mrp = (
#                 Decimal(str(product.mrp))
#                 if product.mrp is not None
#                 else None
#             )

#             if mrp is not None:

#                 mrp = mrp.quantize(
#                     TWO_PLACES
#                 )

#             # ==================================================
#             # GST
#             # ==================================================

#             gst = Decimal(
#                 str(
#                     getattr(
#                         product,
#                         "gst_percentage",
#                         ZERO
#                     ) or ZERO
#                 )
#             ).quantize(TWO_PLACES)

#             # ==================================================
#             # DISCOUNT
#             # ==================================================

#             discount = decimal_value(
#                 request.POST.get(discount_key),
#                 f"Discount for {product.product_name}",
#             )

#             # ==================================================
#             # CALCULATE LINE
#             # ==================================================

#             gross_amount = (
#                 quantity * selling_price
#             ).quantize(TWO_PLACES)

#             if discount > gross_amount:

#                 raise ValidationError(
#                     f"Discount for "
#                     f"'{product.product_name}' "
#                     f"cannot exceed "
#                     f"₹{gross_amount}."
#                 )

#             taxable_amount = (
#                 gross_amount - discount
#             ).quantize(TWO_PLACES)

#             gst_amount = (
#                 taxable_amount
#                 * gst
#                 / ONE_HUNDRED
#             ).quantize(TWO_PLACES)

#             line_amount = (
#                 taxable_amount
#                 + gst_amount
#             ).quantize(TWO_PLACES)

#             processed_items.append(
#                 {
#                     "product": product,
#                     "product_id": product.id,
#                     "unit": unit,
#                     "unit_id": unit.id,
#                     "quantity": quantity,
#                     "selling_price": selling_price,
#                     "mrp": mrp,
#                     "gst": gst,
#                     "discount": discount,
#                     "gst_amount": gst_amount,
#                     "amount": line_amount,
#                 }
#             )

#         # ======================================================
#         # 5. SERVER-SIDE TOTALS
#         # ======================================================

#         totals = calculate_sale_totals(
#             processed_items
#         )

#         subtotal = totals["subtotal"]

#         total_discount = totals["discount"]

#         total_gst = totals["gst"]

#         grand_total = totals["grand_total"]

#         if grand_total <= ZERO:

#             raise ValidationError(
#                 "Grand total must be greater than zero."
#             )

#         # ======================================================
#         # 6. PAYMENT
#         # ======================================================

#         payment_type = (
#             request.POST.get("payment_type") or ""
#         ).strip()

#         paid_amount = decimal_value(
#             request.POST.get("paid_amount"),
#             "Paid amount",
#         )

#         if paid_amount > grand_total:

#             raise ValidationError(
#                 "Paid amount cannot exceed "
#                 f"grand total of ₹{grand_total}."
#             )

#         due_amount = (
#             grand_total - paid_amount
#         ).quantize(TWO_PLACES)

#         # ======================================================
#         # PAYMENT TYPE VALIDATION
#         # ======================================================

#         valid_payment_types = {
#             Sale.PAYMENT_TYPE_CASH,
#             Sale.PAYMENT_TYPE_UPI,
#             Sale.PAYMENT_TYPE_BANK,
#             Sale.PAYMENT_TYPE_CHEQUE,
#             Sale.PAYMENT_TYPE_CREDIT,
#         }

#         if payment_type not in valid_payment_types:

#             raise ValidationError(
#                 "Please select a valid payment type."
#             )

#         # ======================================================
#         # CREDIT SALE
#         # ======================================================

#         if payment_type == Sale.PAYMENT_TYPE_CREDIT:

#             if paid_amount != ZERO:

#                 raise ValidationError(
#                     "Credit sales cannot have "
#                     "a paid amount."
#                 )

#         # ======================================================
#         # NORMAL PAYMENT
#         # ======================================================

#         elif paid_amount == ZERO:

#             raise ValidationError(
#                 "Please enter the paid amount."
#             )

#         # ======================================================
#         # REMARKS
#         # ======================================================

#         remarks = (
#             request.POST.get("remarks") or ""
#         ).strip()

#         # ======================================================
#         # 7. ATOMIC TRANSACTION
#         # ======================================================

#         with transaction.atomic():

#             # --------------------------------------------------
#             # LOCK CUSTOMER
#             # --------------------------------------------------

#             customer = (
#                 Customer.objects
#                 .select_for_update()
#                 .get(
#                     pk=customer.pk,
#                     retailer=retailer,
#                     is_active=True,
#                 )
#             )

#             # --------------------------------------------------
#             # CURRENT CUSTOMER BALANCE
#             # --------------------------------------------------

#             current_balance = (
#                 get_customer_ledger_balance(
#                     customer
#                 )
#             )

#             # --------------------------------------------------
#             # CREDIT LIMIT
#             # --------------------------------------------------

#             credit_limit = (
#                 customer.credit_limit or ZERO
#             )

#             projected_balance = (
#                 current_balance
#                 + due_amount
#             ).quantize(TWO_PLACES)

#             if (
#                 due_amount > ZERO
#                 and credit_limit > ZERO
#                 and projected_balance > credit_limit
#             ):

#                 raise ValidationError(
#                     f"Credit limit exceeded for "
#                     f"'{customer.customer_name}'. "
#                     f"Current outstanding: "
#                     f"₹{current_balance}. "
#                     f"New due: ₹{due_amount}. "
#                     f"Credit limit: "
#                     f"₹{credit_limit}."
#                 )

#             # --------------------------------------------------
#             # CREATE SALE
#             # --------------------------------------------------

#             sale = Sale(
#                 retailer=retailer,
#                 customer=customer,
#                 invoice_date=invoice_date,
#                 subtotal=subtotal,
#                 discount=total_discount,
#                 gst=total_gst,
#                 grand_total=grand_total,
#                 paid_amount=paid_amount,
#                 payment_type=payment_type,
#                 remarks=remarks,
#             )

#             # Model validation
#             sale.full_clean()

#             # Sale.save() generates invoice number,
#             # due amount and payment status.
#             sale.save()

#             logger.info(
#                 "Sale created. sale_id=%s "
#                 "invoice=%s user_id=%s retailer_id=%s",
#                 sale.id,
#                 sale.invoice_number,
#                 request.user.id,
#                 retailer.id,
#             )

#             # --------------------------------------------------
#             # CREATE SALE ITEMS + DEDUCT STOCK
#             # --------------------------------------------------

#             for item in processed_items:

#                 add_sale_item(
#                     sale=sale,
#                     product_id=item["product_id"],
#                     unit_id=item["unit_id"],
#                     quantity=item["quantity"],
#                     selling_price=item["selling_price"],
#                     mrp=item["mrp"],
#                     gst=item["gst"],
#                     discount=item["discount"],
#                 )

#             # --------------------------------------------------
#             # CUSTOMER LEDGER - SALE DEBIT
#             # --------------------------------------------------

#             create_customer_ledger_entry(
#                 customer=customer,
#                 sale=sale,
#                 debit=grand_total,
#                 credit=ZERO,
#                 entry_date=invoice_date,
#                 remarks=(
#                     f"Sale invoice "
#                     f"{sale.invoice_number}"
#                 ),
#             )

#             # --------------------------------------------------
#             # PAYMENT
#             # --------------------------------------------------

#             payment = None

#             if paid_amount > ZERO:

#                 if payment_type == Sale.PAYMENT_TYPE_CREDIT:

#                     raise ValidationError(
#                         "Credit payment cannot be recorded."
#                     )

#                 payment = Payment(
#                     retailer=retailer,
#                     customer=customer,
#                     sale=sale,
#                     payment_date=invoice_date,
#                     amount=paid_amount,
#                     payment_type=payment_type,
#                     payment_reference=(
#                         request.POST.get(
#                             "payment_reference"
#                         ) or None
#                     ),
#                     receipt_number=(
#                         request.POST.get(
#                             "receipt_number"
#                         ) or None
#                     ),
#                     remarks=remarks,
#                 )

#                 payment.full_clean()
#                 payment.save()

#                 # --------------------------------------------------
#                 # CUSTOMER LEDGER - PAYMENT CREDIT
#                 # --------------------------------------------------

#                 create_customer_ledger_entry(
#                     customer=customer,
#                     payment=payment,
#                     debit=ZERO,
#                     credit=paid_amount,
#                     entry_date=invoice_date,
#                     remarks=(
#                         f"Payment received for "
#                         f"invoice "
#                         f"{sale.invoice_number}"
#                     ),
#                 )

#             # --------------------------------------------------
#             # FINAL SALE VALIDATION
#             # --------------------------------------------------

#             sale.refresh_from_db()

#             if sale.due_amount != due_amount:

#                 raise ValidationError(
#                     "Payment calculation mismatch."
#                 )

#             logger.info(
#                 "Sale transaction completed successfully. "
#                 "sale_id=%s invoice=%s paid=%s due=%s "
#                 "user_id=%s retailer_id=%s",
#                 sale.id,
#                 sale.invoice_number,
#                 paid_amount,
#                 due_amount,
#                 request.user.id,
#                 retailer.id,
#             )

#         # ======================================================
#         # SUCCESS
#         # ======================================================

#         action = (
#             request.POST.get("action") or "save"
#         ).strip()

#         messages.success(
#             request,
#             f"Sale {sale.invoice_number} "
#             f"created successfully."
#         )

#         if action == "save_print":

#             return redirect(
#                 "sale_print",
#                 sale_id=sale.id,
#             )

#         return redirect(
#             "sale_create"
#         )

#     # ==========================================================
#     # VALIDATION ERROR
#     # ==========================================================

#     except ValidationError as exc:

#         error_message = " ".join(
#             str(message)
#             for message in exc.messages
#         )

#         logger.warning(
#             "Sale validation failed. "
#             "user_id=%s retailer_id=%s error=%s",
#             request.user.id,
#             getattr(retailer, "id", None),
#             error_message,
#         )

#         messages.error(
#             request,
#             error_message,
#         )

#         return redirect(
#             "sale_create"
#         )

#     # ==========================================================
#     # DATABASE ERROR
#     # ==========================================================

#     except IntegrityError:

#         logger.exception(
#             "Database integrity error while "
#             "creating sale. "
#             "user_id=%s retailer_id=%s",
#             request.user.id,
#             getattr(retailer, "id", None),
#         )

#         messages.error(
#             request,
#             "Unable to create the sale because "
#             "of a database conflict. "
#             "Please try again.",
#         )

#         return redirect(
#             "sale_create"
#         )

#     # ==========================================================
#     # UNEXPECTED ERROR
#     # ==========================================================

#     except Exception:

#         logger.exception(
#             "Unexpected error while creating sale. "
#             "user_id=%s retailer_id=%s",
#             request.user.id,
#             getattr(retailer, "id", None),
#         )

#         messages.error(
#             request,
#             "An unexpected error occurred while "
#             "creating the sale. Please try again.",
#         )

#         return redirect(
#             "sale_create"
#         )




# @require_POST
# @login_required
# def create_customer_ajax(request):
#     """
#     Create customer from the Add Customer modal.

#     Mobile number is unique per retailer.
#     """
#     try:

#         retailer = get_logged_in_retailer(request)

#         customer_name = (
#             request.POST.get("customer_name") or ""
#         ).strip()

#         mobile = (
#             request.POST.get("mobile") or ""
#         ).strip()

#         email = (
#             request.POST.get("email") or ""
#         ).strip()

#         gst_number = (
#             request.POST.get("gst_number") or ""
#         ).strip()

#         address = (
#             request.POST.get("address") or ""
#         ).strip()

#         opening_balance = decimal_value(
#             request.POST.get("opening_balance"),
#             "Opening balance",
#         )

#         credit_limit = decimal_value(
#             request.POST.get("credit_limit"),
#             "Credit limit",
#         )

#         # ------------------------------------------------------
#         # NAME
#         # ------------------------------------------------------

#         if not customer_name:
#             raise ValidationError(
#                 "Customer name is required."
#             )

#         if len(customer_name) > 200:
#             raise ValidationError(
#                 "Customer name cannot exceed 200 characters."
#             )

#         # ------------------------------------------------------
#         # MOBILE
#         # ------------------------------------------------------

#         if not mobile:
#             raise ValidationError(
#                 "Mobile number is required."
#             )

#         # Keep only digits for validation.
#         normalized_mobile = "".join(
#             character
#             for character in mobile
#             if character.isdigit()
#         )

#         if len(normalized_mobile) != 10:
#             raise ValidationError(
#                 "Please enter a valid 10-digit mobile number."
#             )

#         # ------------------------------------------------------
#         # DUPLICATE CHECK
#         # ------------------------------------------------------

#         existing_customer = (
#             Customer.objects
#             .filter(
#                 retailer=retailer,
#                 mobile=normalized_mobile,
#             )
#             .first()
#         )

#         if existing_customer:

#             return JsonResponse(
#                 {
#                     "success": False,
#                     "exists": True,
#                     "message": (
#                         "A customer with this mobile number "
#                         "already exists."
#                     ),
#                     "customer": {
#                         "id": existing_customer.id,
#                         "name": existing_customer.customer_name,
#                         "mobile": existing_customer.mobile,
#                     },
#                 },
#                 status=409,
#             )

#         # ------------------------------------------------------
#         # CREATE CUSTOMER
#         # ------------------------------------------------------

#         with transaction.atomic():

#             customer = Customer.objects.create(
#                 retailer=retailer,
#                 customer_name=customer_name,
#                 mobile=normalized_mobile,
#                 email=email or None,
#                 gst_number=gst_number or None,
#                 address=address or None,
#                 opening_balance=opening_balance,
#                 credit_limit=credit_limit,
#                 is_active=True,
#             )

#         logger.info(
#             "Customer created successfully. "
#             "customer_id=%s retailer_id=%s",
#             customer.id,
#             retailer.id,
#         )

#         return JsonResponse(
#             {
#                 "success": True,
#                 "message": "Customer created successfully.",
#                 "customer": {
#                     "id": customer.id,
#                     "name": customer.customer_name,
#                     "mobile": customer.mobile,
#                     "email": customer.email or "",
#                     "address": customer.address or "",
#                     "gst_number": customer.gst_number or "",
#                     "credit_limit": str(
#                         customer.credit_limit
#                     ),
#                     "opening_balance": str(
#                         customer.opening_balance
#                     ),
#                 },
#             },
#             status=201,
#         )

#     except ValidationError as exc:

#         return JsonResponse(
#             {
#                 "success": False,
#                 "message": " ".join(
#                     str(message)
#                     for message in exc.messages
#                 ),
#             },
#             status=400,
#         )

#     except IntegrityError:

#         logger.exception(
#             "Duplicate customer/mobile race condition."
#         )

#         return JsonResponse(
#             {
#                 "success": False,
#                 "message": (
#                     "A customer with this mobile number "
#                     "already exists."
#                 ),
#             },
#             status=409,
#         )

#     except Exception:

#         logger.exception(
#             "Unexpected error while creating customer."
#         )

#         return JsonResponse(
#             {
#                 "success": False,
#                 "message": (
#                     "Unable to create customer. "
#                     "Please try again."
#                 ),
#             },
#             status=500,
#         )


# @require_GET
# @login_required
# def sale_product_data(request, product_id):

#     try:
#         retailer = get_logged_in_retailer(request)
#         product = (
#             Product.objects
#             .filter(
#                 pk=product_id,
#                 retailer=retailer,
#                 is_active=True,
#             )
#             .first()
#         )

#         if product is None:
#             return JsonResponse(
#                 {
#                     "success": False,
#                     "message": "Product not found.",
#                 },
#                 status=404,
#             )

#         return JsonResponse(
#             {
#                 "success": True,
#                 "product": {
#                     "id": product.id,
#                     "name": product.product_name,

#                     "stock": str(
#                         product.current_stock or ZERO
#                     ),

#                     "selling_price": str(
#                         product.selling_price
#                     ),

#                     "mrp": (
#                         str(product.mrp)
#                         if product.mrp is not None
#                         else ""
#                     ),

#                     "gst": str(
#                         product.gst or ZERO
#                     ),
#                 },
#             }
#         )

#     except ValidationError as exc:

#         return JsonResponse(
#             {
#                 "success": False,
#                 "message": str(exc),
#             },
#             status=400,
#         )

#     except Exception:

#         logger.exception(
#             "Unable to fetch product data."
#         )

#         return JsonResponse(
#             {
#                 "success": False,
#                 "message": "Unable to fetch product.",
#             },
#             status=500,
#         )








