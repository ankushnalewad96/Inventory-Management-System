import logging
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.core.validators import validate_email
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Count, F, Prefetch, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext
from django.views.decorators.http import require_GET, require_POST

from . import batches as batch_stock
from .gst import gst_choices, parse_rate as parse_gst_rate
from .models import (
    Brand,
    Category,
    Customer,
    CustomerLedger,
    CustomUser,
    Payment,
    Product,
    ProductBatch,
    Purchase,
    PurchaseItem,
    PurchasePayment,
    Quotation,
    Retailer,
    Sale,
    SaleItem,
    Supplier,
    SupplierProduct,
    Unit,
)
from .quantities import QuantityError, format_quantity, parse_quantity
from .sales import add_sale_item
from .shop_services import active_shop_type_choices, is_shop_type_active, service_paused_message
from .shop_types import SHOP_TYPE_LABELS, features_for_type, get_features, shop_type_feature_labels
from .states import STATE_CHOICES, rate_wise_summary, state_key, tax_fields
from .units import clean_purchase_unit, conversion_factor_for, to_base_quantity







logger = logging.getLogger("pharma_app")




# Create your views here.
# The dashboard lives in dashboard_views.py.


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
            gettext('You are not authorized to register a retailer.')
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
            "register.html",
            {
                # Only shop types the admin has switched on.
                "shop_type_choices": active_shop_type_choices(),
                "shop_type_feature_labels": shop_type_feature_labels(),
                # Shop types that print drug licence numbers on bills.
                "drug_licence_types": [
                    shop_type for shop_type in SHOP_TYPE_LABELS
                    if features_for_type(shop_type).drug_licence
                ],
            },
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

        # Kind of shop: decides which features the shop gets.
        shop_type = request.POST.get(
            "shop_type",
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
            "Shop Type": shop_type,
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
                (gettext('Please fill all required fields: %(missing_fields)s') % {'missing_fields': ", ".join(missing_fields)})
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
        # FORMAT VALIDATION (email, PIN code, password strength)
        # ========================================================

        format_error = None

        if shop_type not in SHOP_TYPE_LABELS:
            format_error = ("shop_type", gettext("Please select a valid shop type."))
        elif not is_shop_type_active(shop_type):
            format_error = ("shop_type", service_paused_message(shop_type))

        try:
            validate_email(email)
        except ValidationError:
            if format_error is None:
                format_error = ("email", "Please enter a valid email address.")

        if format_error is None and not (pincode.isdigit() and len(pincode) == 6):
            format_error = ("pincode", "Please enter a valid 6-digit PIN code.")

        if format_error is None:
            try:
                validate_password(
                    password,
                    user=CustomUser(username=username, email=email),
                )
            except ValidationError as exc:
                format_error = ("password", " ".join(exc.messages))

        if format_error is not None:

            field, error_message = format_error

            if is_ajax:
                return JsonResponse(
                    {
                        "success": False,
                        "message": error_message,
                        "field": field,
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

            error_message = gettext('Username already exists.')

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

            error_message = gettext('Email already exists.')

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
                gettext('Please enter a valid mobile number.')
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
                shop_type=shop_type,
                mobile=mobile_digits,
                email=email,
                gst_number=gst_number or None,
                pan_number=pan_number or None,
                address=address,
                city=city,
                state=state,
                pincode=pincode,
                # Drug licence numbers only for shops with that feature.
                **(
                    {
                        "drug_licence_number": (request.POST.get("drug_licence_number") or "").strip()[:50],
                        "drug_licence_number_2": (request.POST.get("drug_licence_number_2") or "").strip()[:50],
                    }
                    if features_for_type(shop_type).drug_licence
                    else {}
                ),
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
                    "message": gettext('Retailer registered successfully.')
                },
                status=201
            )

        # ========================================================
        # NORMAL FORM SUCCESS
        # ========================================================

        messages.success(
            request,
            (gettext('Retailer %(shop_name)s registered successfully.') % {'shop_name': shop_name})
        )

        return redirect("retailer_list")

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
            gettext('Registration failed because the username, email, or another value already exists.')
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
            gettext('Something went wrong while registering the retailer. Please try again later.')
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
            messages.error(request, gettext('Please enter your username and password.'))
            return render(request, "userlogin.html")

        try:
            user = authenticate(request, username=username, password=password)
        except Exception:
            logger.exception("Unexpected error during authentication for username=%s", username)
            messages.error(request, gettext('Something went wrong. Please try again later.'))
            return render(request, "userlogin.html")

        if user is not None:
            if not user.is_active:
                logger.warning("Login blocked for inactive user: username=%s", username)
                messages.error(request, gettext('Your account is turned off. Please contact the admin.'))
                return render(request, "userlogin.html")

            # Shop type switched off by the admin: no sign-in until it is on again.
            if not user.is_superuser:
                shop = Retailer.all_objects.filter(user=user).only("shop_type").first()
                if shop is not None and not is_shop_type_active(shop.shop_type):
                    logger.warning("Login blocked, shop type paused: username=%s type=%s", username, shop.shop_type)
                    messages.error(request, service_paused_message(shop.shop_type))
                    return render(request, "userlogin.html")

            login(request, user)
            logger.info("User logged in: username=%s", username)
            messages.success(request, (gettext('Welcome back, %(username)s!') % {'username': user.username}))

            # Go back to the page the user asked for, but only if it
            # is on this site (never to an outside URL).
            next_url = request.POST.get("next") or request.GET.get("next")
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)

            return redirect("dashboard")

        logger.warning("Failed login attempt for username=%s", username)
        messages.error(request, gettext('Wrong username or password. Please try again.'))

    return render(request, "userlogin.html")


def user_logout(request):
    """Logs out the current user and clears their session."""
    username = request.user.username if request.user.is_authenticated else "Anonymous"

    was_logged_in = request.user.is_authenticated

    try:
        logout(request)
        logger.info("User logged out: username=%s", username)
        if was_logged_in:
            messages.success(request, gettext('You have logged out safely. See you again soon.'))
    except Exception:
        logger.exception("Unexpected error during logout for username=%s", username)

    return redirect("user_login")


def product_rules_by_shop(retailers):
    """
    {shop id: {mrp_required, hsn_required, allow_below_cost_sale}} so the
    product forms can follow the right shop's rules. The server checks
    the same rules again on save.
    """

    rules = {}

    for retailer in retailers:
        features = get_features(retailer)
        rules[str(retailer.id)] = {
            "mrp_required": features.mrp_required,
            "hsn_required": features.hsn_required,
            "allow_below_cost_sale": features.allow_below_cost_sale,
            "decimal_quantity": features.decimal_quantity,
            "unit_conversion": features.unit_conversion,
            "batch_tracking": features.batch_tracking,
            "prescription_details": features.prescription_details,
            "price_levels": features.price_levels,
            "product_specification": features.product_specification,
        }

    return rules


def clean_hardware_details(data, features, *, purchase_price, selling_price, mrp):
    """
    Wholesale price (features.price_levels) and specification
    (features.product_specification) from a product form.

    Returns ({field: value}, warning). Fields of features that are off are
    left out, so posted values for them are ignored. Raises
    ValidationError for a bad wholesale price.
    """

    values = {}
    warning = ""

    if features.price_levels:
        raw = (data.get("wholesale_price") or "").strip()
        wholesale = None

        if raw:
            try:
                wholesale = Decimal(raw)
            except InvalidOperation:
                raise ValidationError(gettext('Enter a valid wholesale price.'))

            if not wholesale.is_finite() or wholesale <= 0:
                raise ValidationError(gettext('Wholesale price must be greater than 0.'))

            wholesale = wholesale.quantize(Decimal("0.01"))

            if mrp is not None and wholesale > mrp:
                raise ValidationError(gettext('Wholesale price cannot be greater than MRP.'))

            if wholesale > selling_price:
                raise ValidationError(gettext('Wholesale price cannot be more than the retail selling price.'))

            if wholesale < purchase_price:
                if not features.allow_below_cost_sale:
                    raise ValidationError(gettext('Wholesale price cannot be lower than the purchase price.'))
                warning = (
                    (gettext('Note: wholesale price ₹%(wholesale)s is below the purchase price ₹%(purchase_price)s.') % {'wholesale': wholesale, 'purchase_price': purchase_price})
                )

        values["wholesale_price"] = wholesale

    if features.product_specification:
        values["specification"] = (data.get("specification") or "").strip()[:255]

    return values, warning


ZERO_QTY = Decimal("0.000")


def link_supplier_product(supplier, product, *, price=None, bill_date=None):
    """
    Record that `supplier` sells `product` (same shop only). With a
    price/date from a bill, keeps the latest ones. Returns the link.
    """

    if supplier.retailer_id != product.retailer_id:
        raise ValidationError(gettext('The supplier and the product must belong to the same shop.'))

    link, created = SupplierProduct.objects.get_or_create(
        supplier=supplier,
        product=product,
        defaults={
            "retailer_id": supplier.retailer_id,
            "last_purchase_price": price,
            "last_purchase_date": bill_date,
        },
    )

    if not created and bill_date is not None and (
        link.last_purchase_date is None or bill_date >= link.last_purchase_date
    ):
        link.last_purchase_price = price
        link.last_purchase_date = bill_date
        link.save(update_fields=["last_purchase_price", "last_purchase_date"])

    return link


def supplier_product_map(suppliers):
    """{supplier id: [product ids]} for the purchase page filters."""

    mapping = {str(supplier.id): [] for supplier in suppliers}

    links = SupplierProduct.objects.filter(supplier__in=suppliers).values_list("supplier_id", "product_id")
    for supplier_id, product_id in links:
        mapping.setdefault(str(supplier_id), []).append(product_id)

    return mapping


def quotation_sale_prefill(request, quotation_id):
    """
    Data to fill the sale screen from an open quotation, or None.
    Only the user's own shop (admin: any shop) and only shops with
    features.quotations.
    """

    quotation_id = (quotation_id or "").strip()

    if not quotation_id.isdigit():
        return None

    quotations = Quotation.objects.filter(pk=quotation_id, status=Quotation.STATUS_OPEN)

    if not request.user.is_superuser:
        quotations = quotations.filter(retailer__user=request.user, retailer__is_active=True)

    quotation = quotations.select_related("retailer", "customer").first()

    if quotation is None or not get_features(quotation.retailer).quotations:
        return None

    return {
        "id": quotation.id,
        "number": quotation.quotation_number,
        "retailer_id": quotation.retailer_id,
        "customer_id": quotation.customer_id,
        "items": [
            {
                "product_id": item.product_id,
                "quantity": format_quantity(item.quantity),
                "discount": str(item.discount),
                "selling_price": str(item.selling_price),
                "gst": str(item.gst),
            }
            for item in quotation.items.all()
        ],
    }


def sale_pharmacy_data(products, today):
    """
    {product id: {stock, batches, rx, salt}} for products of shops with
    batch tracking / prescription details, for the sale screen.

    stock   -> sellable stock (unexpired batches only)
    batches -> unexpired batches with stock, earliest expiry first
    rx      -> Schedule H/H1/X: patient + doctor needed
    Products of other shops are left out (screen works as before).
    """

    shop_features = {}
    data = {}
    batch_products = []

    for product in products:
        features = shop_features.get(product.retailer_id)
        if features is None:
            features = shop_features[product.retailer_id] = get_features(product.retailer)

        if not (features.batch_tracking or features.prescription_details):
            continue

        data[str(product.id)] = {
            "stock": format_quantity(product.current_stock),
            "batches": [],
            "batch_tracking": features.batch_tracking,
            "rx": features.prescription_details and product.needs_prescription,
            "schedule": product.schedule if features.prescription_details else "",
            "salt": product.salt_composition,
        }

        if features.batch_tracking:
            data[str(product.id)]["stock"] = "0"
            batch_products.append(product.id)

    if batch_products:
        sellable = {}
        batches = (
            ProductBatch.objects
            .filter(product_id__in=batch_products, quantity__gt=0, expiry_date__gte=today)
            .order_by("expiry_date", "id")
        )

        for batch in batches:
            entry = data[str(batch.product_id)]
            entry["batches"].append({
                "id": batch.id,
                "batch_number": batch.batch_number,
                "expiry": batch.expiry_date.strftime("%m/%Y"),
                "quantity": format_quantity(batch.quantity),
            })
            sellable[batch.product_id] = sellable.get(batch.product_id, ZERO_QTY) + batch.quantity

        for product_id, quantity in sellable.items():
            data[str(product_id)]["stock"] = format_quantity(quantity)

    return data


def clean_drug_details(data, features):
    """
    Salt/composition, manufacturer and schedule from a product form.

    Drug details belong to shops with features.prescription_details
    (pharmacy); for other shops the posted values are ignored and the
    fields are left empty. Raises ValidationError for a bad schedule.
    """

    if not features.prescription_details:
        return {}

    schedule = (data.get("schedule") or Product.SCHEDULE_NONE).strip()

    if schedule not in dict(Product.SCHEDULE_CHOICES):
        raise ValidationError(gettext('Please select a valid drug schedule.'))

    return {
        "salt_composition": (data.get("salt_composition") or "").strip()[:255],
        "manufacturer": (data.get("manufacturer") or "").strip()[:150],
        "schedule": schedule,
    }


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
    is_admin = request.user.is_superuser or request.user.is_staff
    own_retailer = None

    if is_admin:
        retailers = Retailer.objects.filter(
            is_active=True
        )
        categories = Category.objects.all()
        brands = Brand.objects.all()
    else:
        # A retailer always adds products to their own shop,
        # so they never pick a retailer on the form.
        retailers = Retailer.objects.filter(
            user=request.user,
            is_active=True
        )
        own_retailer = retailers.first()

        if own_retailer is None:
            messages.error(
                request,
                gettext('No active retailer is associated with this user.')
            )
            return redirect("dashboard")

        brands = Brand.objects.filter(retailer=own_retailer)
        categories = Category.objects.filter(retailer=own_retailer)

    units = Unit.objects.all()

    context = {
        "retailers": retailers,
        "categories": categories,
        "brands": brands,
        "units": units,
        "is_admin": is_admin,
        "own_retailer": own_retailer,
        "gst_choices": gst_choices(),
        "schedule_choices": Product.SCHEDULE_CHOICES,
        # Form rules per shop (the admin can pick any shop).
        "shop_rules": product_rules_by_shop(retailers),
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
    if is_admin:
        retailer_id = request.POST.get(
            "retailer",
            ""
        ).strip()
    else:
        # Ignore any posted value; use the logged-in retailer's shop.
        retailer_id = str(own_retailer.id)

    # Features of the shop the product is for (MRP/HSN rules, price rules).
    if is_admin:
        target_shop = (
            Retailer.objects.filter(pk=retailer_id, is_active=True).first()
            if retailer_id.isdigit() else None
        )
    else:
        target_shop = own_retailer

    shop_features = get_features(target_shop)
    price_warning = ""

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
        "Purchase Price": purchase_price,
        "Selling Price": selling_price,
    }

    # HSN / MRP are required only when the shop's features say so.
    if shop_features.hsn_required:
        required_fields["HSN Code"] = hsn_code

    if shop_features.mrp_required:
        required_fields["MRP"] = mrp

    missing_fields = [
        field_name
        for field_name, value in required_fields.items()
        if not value
    ]

    if missing_fields:

        error_message = (
            (gettext('Please fill all required fields: %(missing_fields)s') % {'missing_fields': ", ".join(missing_fields)})
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

        # MRP may be left empty when the shop does not require it.
        mrp = (
            Decimal(mrp)
            if mrp
            else None
        )

        gst = (
            Decimal(gst)
            if gst
            else Decimal("0")
        )

        for value in (purchase_price, selling_price, mrp, gst):
            if value is not None and not value.is_finite():
                raise ValueError(gettext('Not a finite number.'))

        # Stock: Decimal; fractions only when the shop sells loose quantities.
        minimum_stock = parse_quantity(
            minimum_stock,
            gettext('Minimum stock'),
            allow_fraction=shop_features.decimal_quantity,
            allow_zero=True,
            default="0",
        )

        current_stock = parse_quantity(
            current_stock,
            gettext('Current stock'),
            allow_fraction=shop_features.decimal_quantity,
            allow_zero=True,
            default="0",
        )

    except (
        InvalidOperation,
        ValueError,
        TypeError
    ) as exc:

        logger.warning(
            "Invalid numeric values while adding product. "
            "User=%s, Product=%s",
            request.user.username,
            product_name
        )

        error_message = (
            str(exc)
            if isinstance(exc, QuantityError)
            else "Please enter valid numeric values for "
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
            gettext('Purchase price cannot be negative.')
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
            gettext('Selling price cannot be negative.')
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

    if mrp is not None and mrp < 0:

        error_message = (
            gettext('MRP cannot be negative.')
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
            gettext('Minimum stock cannot be negative.')
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
            gettext('Current stock cannot be negative.')
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
            gettext('GST cannot be negative.')
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
            gettext('GST percentage cannot be greater than 100.')
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
    if selling_price < purchase_price and shop_features.allow_below_cost_sale:

        # Allowed for this shop, but tell the user.
        price_warning = (
            (gettext('Note: selling price ₹%(selling_price)s is below the purchase price ₹%(purchase_price)s.') % {'selling_price': selling_price, 'purchase_price': purchase_price})
        )

    elif selling_price < purchase_price:

        error_message = (
            gettext('Selling price cannot be lower than the purchase price.')
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

    # No MRP entered (allowed for some shops): nothing to compare with.
    if mrp is not None and selling_price > mrp:

        error_message = (
            gettext('Selling price cannot be greater than MRP.')
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
            gettext('Selected retailer does not exist or you are not authorized to use it.')
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
                error_message = gettext('Category name is required.')

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
                    gettext('Selected category does not exist or does not belong to this retailer.')
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
                error_message = gettext('Brand name is required.')

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
                    gettext('Selected brand does not exist or does not belong to this retailer.')
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
                error_message = gettext('Unit name is required.')

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
                    gettext('Selected unit does not exist.')
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
            gettext('Something went wrong while processing brand, category, or unit.')
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
    # PURCHASE UNIT + CONVERSION (features.unit_conversion)
    # e.g. bought per Box, sold per pc, 1 Box = 100 pc.
    # Ignored for shops without unit conversion.
    # ============================================================
    try:

        purchase_unit, conversion_factor = clean_purchase_unit(
            unit.id,
            request.POST.get("purchase_unit"),
            request.POST.get("conversion_factor"),
            shop_features,
            Unit.objects.all(),
        )

    except QuantityError as exc:

        if is_ajax:
            return JsonResponse(
                {
                    "success": False,
                    "message": str(exc),
                    "field": "conversion_factor",
                },
                status=400
            )

        messages.error(
            request,
            str(exc)
        )

        return render(
            request,
            "add_product.html",
            context
        )

    # ============================================================
    # DRUG DETAILS + OPENING BATCH (pharmacy features only),
    # WHOLESALE PRICE + SPECIFICATION (hardware features only)
    # ============================================================
    try:

        drug_details = clean_drug_details(request.POST, shop_features)

        # Wholesale price + specification (hardware features).
        hardware_details, wholesale_warning = clean_hardware_details(
            request.POST, shop_features,
            purchase_price=purchase_price, selling_price=selling_price, mrp=mrp,
        )
        drug_details.update(hardware_details)
        if wholesale_warning:
            price_warning = f"{price_warning} {wholesale_warning}".strip()

        opening_expiry = None

        # Opening stock of a batch-tracked product goes into an
        # "OPENING" batch, so it needs an expiry date.
        if shop_features.batch_tracking and current_stock > 0:
            opening_expiry = batch_stock.parse_expiry(
                request.POST.get("opening_expiry"),
                gettext('Expiry date of opening stock'),
            )

    except ValidationError as exc:

        error_message = " ".join(exc.messages)

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
    # DUPLICATE BARCODE VALIDATION
    # ============================================================
    if barcode:

        # Unique within this shop only; other shops may use the same code.
        barcode_exists = Product.objects.filter(
            retailer=retailer,
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
                gettext('A product with this barcode already exists.')
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
                purchase_unit=purchase_unit,
                conversion_factor=conversion_factor,
                product_name=product_name,
                barcode=barcode or None,
                hsn_code=hsn_code,
                purchase_price=purchase_price,
                selling_price=selling_price,
                mrp=mrp,
                minimum_stock=minimum_stock,
                # Batch-tracked: stock is added through the opening batch.
                current_stock=ZERO_QTY if opening_expiry else current_stock,
                gst=gst,
                **drug_details,
            )

            if opening_expiry:
                product = Product.objects.select_for_update().get(pk=product.pk)
                batch_stock.receive_into_batch(
                    product,
                    batch_number=ProductBatch.OPENING_BATCH,
                    expiry_date=opening_expiry,
                    quantity=current_stock,
                    purchase_price=purchase_price,
                    mrp=mrp,
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
                    "retailer_id": product.retailer_id,
                    "unit_id": product.unit_id,
                    "purchase_unit_id": product.purchase_unit_id or "",
                    "conversion_factor": format_quantity(product.conversion_factor),
                    "mrp": str(product.mrp) if product.mrp is not None else "",
                    "purchase_price": str(product.purchase_price),
                    "gst": str(product.gst),
                    "message": gettext('Product added successfully.'),
                    "warning": price_warning,
                },
                status=201
            )

        # ========================================================
        # NORMAL FORM SUCCESS
        # ========================================================
        messages.success(
            request,
            gettext('Product added successfully.')
        )

        if price_warning:
            messages.warning(request, price_warning)

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
            gettext('A product with this barcode already exists or another database constraint was violated.')
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
            gettext('Something went wrong while adding the product. Please try again later.')
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
                    gettext('No retailer profile found for this account.')
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


        # SEARCH (name, barcode or HSN)
        search = request.GET.get("search", "").strip()

        if search:
            products_qs = products_qs.filter(
                Q(product_name__icontains=search)
                # Salt/composition (pharmacy; empty for other shops).
                | Q(salt_composition__icontains=search)
                | Q(barcode__icontains=search)
                | Q(hsn_code__icontains=search)
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
            "page_obj": products,
            "low_stock_count": low_stock_count,
            "is_admin": is_admin,
            "search": search,
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
            gettext('Something went wrong while loading low stock products.')
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
                    gettext('Your account is not associated with a retailer.'),
                )

                return redirect("dashboard")

            products = products.filter(
                retailer=retailer
            )

        # ---------------------------------------------------------
        # Shop-wide statistics for the stat cards. Worked out before
        # the search / status tab, so the cards always show the
        # shop's totals whichever tab is open.
        # ---------------------------------------------------------
        stats = products.aggregate(
            total_products=Count("id"),
            active_products=Count("id", filter=Q(is_active=True)),
            low_stock_count=Count(
                "id",
                filter=Q(current_stock__gt=0, current_stock__lte=F("minimum_stock")),
            ),
            out_of_stock_count=Count("id", filter=Q(current_stock=0)),
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
                # Salt/composition (pharmacy; empty for other shops).
                | Q(salt_composition__icontains=search)
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

            # Units for the "bought in" (purchase unit) field
            "units": Unit.objects.order_by("name"),

            # Drug schedule choices (pharmacy shops' edit popup)
            "schedule_choices": Product.SCHEDULE_CHOICES,

            # MRP / price rules of each shop for the edit popup
            "shop_rules": product_rules_by_shop(
                Retailer.objects.all()
                if request.user.is_superuser
                else Retailer.objects.filter(user=request.user)
            ),
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
            gettext('Unable to load products. Please try again.'),
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
            gettext('Something went wrong while loading the product list.'),
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


# GST rates live in gst.py (single source of truth).

# PAYMENT TERMS -> NUMBER OF DAYS UNTIL DUE
# Immediate / COD bills are due on the bill date itself.
PAYMENT_TERM_DAYS = {
    "net15": 15,
    "net30": 30,
    "net45": 45,
    "net60": 60,
    "immediate": 0,
    "cod": 0,
}

# COMMON DECIMAL VALUES
MONEY_ZERO = Decimal("0.00")


def calculate_due_date(bill_date, payment_terms):
    """
    Return the due date for a bill based on its payment terms.

    Returns None when no (or an unknown) payment term is selected.
    """

    days = PAYMENT_TERM_DAYS.get(
        (payment_terms or "").strip().lower()
    )

    if days is None:
        return None

    return bill_date + timedelta(days=days)

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
            (gettext('%(field_name)s must be a valid number.') % {'field_name': field_name})
        )

    if not amount.is_finite():
        raise ValueError(
            (gettext('%(field_name)s must be a valid number.') % {'field_name': field_name})
        )

    if amount < Decimal("0"):

        raise ValueError(
            (gettext('%(field_name)s cannot be negative.') % {'field_name': field_name})
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

        if retailers is None:
            messages.error(
                request,
                gettext('No active retailer profile is linked to your account.')
            )
            return redirect("dashboard")

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

    now = timezone.localtime()

    context = {
        "products": products,
        "categories": categories,
        "brands": brands,
        "units": units,
        "supplier_list": supplier_list,
        # Which supplier sells which products (supplier product list):
        # the page shows only the chosen supplier's products, and only
        # the suppliers of the chosen products.
        "supplier_products": supplier_product_map(supplier_list),
        "retailer_list": retailer_list,
        "today": now.date(),
        "now_time": now.strftime("%H:%M"),
        "payment_term_days": PAYMENT_TERM_DAYS,
        "shop_type_choices": active_shop_type_choices(),
        # GST slabs for the item rows (single source: gst.py)
        "gst_choices": gst_choices(),
        # MRP / HSN / price rules per shop for the "Add New Product" popup
        "shop_rules": product_rules_by_shop(
            retailer_list if request.user.is_superuser else [retailers]
        ),
    }


    return render(
        request,
        "add_order.html",
        context
    )


def _wants_json(request):
    """The New Sale / New Purchase pages save in the background and ask for JSON."""

    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _purchase_error(request, message, status=400):
    """
    A purchase could not be saved. The page (background save) gets the
    message as JSON and keeps everything the user typed; a plain form
    post goes back to an empty New Purchase page with the message.
    """

    if _wants_json(request):
        return JsonResponse({"success": False, "error": message}, status=status)

    messages.error(request, message)
    return redirect("add_new_order")


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
                    gettext('Please select a retailer.')
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
                    gettext('No retailer profile is linked to your account.')
                )


        # =====================================================
        # 2. GET RETAILER OBJECT
        # =====================================================

        try:
            

            retailer = Retailer.objects.get(
                id=retailer_id,
                is_active=True
            )


        except (Retailer.DoesNotExist, ValueError):

            raise ValueError(
                gettext('Selected retailer does not exist or is inactive.')
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
                gettext('Supplier is required.')
            )


        try:

            # The supplier must belong to the shop making the purchase.
            supplier = Supplier.objects.get(
                id=supplier_id,
                retailer=retailer,
                is_active=True
            )

        except (Supplier.DoesNotExist, ValueError):

            raise ValueError(
                gettext('Selected supplier does not exist or is inactive.')
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
                gettext('Bill number is required.')
            )


        if not bill_date:

            raise ValueError(
                gettext('Bill date is required.')
            )


        try:

            bill_date = datetime.strptime(
                bill_date,
                "%Y-%m-%d"
            ).date()

        except ValueError:

            raise ValueError(
                gettext('Please enter a valid bill date.')
            )


        # The same supplier bill must not be entered twice
        # (it would add the stock twice).
        if Purchase.objects.filter(
            retailer=retailer,
            supplier=supplier,
            bill_number__iexact=bill_number,
        ).exists():

            raise ValueError(
                (gettext('Bill %(bill_number)s from %(supplier_name)s has already been entered.') % {'bill_number': bill_number, 'supplier_name': supplier.supplier_name})
            )


        # =====================================================
        # DUE DATE
        #
        # The due date field is read-only in the form; it is
        # always derived from bill date + payment terms here.
        # =====================================================

        payment_terms = (
            request.POST
            .get(
                "payment_terms",
                ""
            )
            .strip()
        )

        due_date = calculate_due_date(
            bill_date,
            payment_terms
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
            gettext('Discount')
        )


        transport_charge = decimal_from_post(
            request.POST.get(
                "transport_charge",
                "0"
            ),
            gettext('Transport charge')
        )


        other_charge = decimal_from_post(
            request.POST.get(
                "other_charge",
                "0"
            ),
            gettext('Other charge')
        )


        paid_amount = decimal_from_post(
            request.POST.get(
                "paid_amount",
                "0"
            ),
            gettext('Paid amount')
        )


        # =====================================================
        # 6. PAYMENT (cash only)
        #
        # Suppliers are paid in cash. Any payment type sent by
        # the form is ignored; 0 paid keeps the whole bill due.
        # =====================================================

        payment_type = PurchasePayment.PAYMENT_TYPE_CASH


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
                gettext('Please add at least one product to the purchase.')
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
                gettext('Discount cannot be greater than subtotal.')
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
                gettext('Paid amount cannot be greater than the grand total.')
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

                payment_terms=payment_terms,

                due_date=due_date,

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

                # Supplier in the shop's state -> CGST+SGST, else IGST.
                **tax_fields(
                    get_features(retailer), retailer.state, supplier.state, gst
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


            # =================================================
            # FIRST PAYMENT (amount paid at purchase time)
            # Later payments are added from the bill's page.
            # =================================================

            if paid_amount > Decimal("0"):

                PurchasePayment.objects.create(
                    retailer=retailer,
                    supplier=supplier,
                    purchase=purchase,
                    payment_date=bill_date,
                    amount=money(paid_amount),
                    payment_type=payment_type,
                    remarks="Paid at the time of purchase",
                    created_by=request.user,
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
            (gettext('Purchase order %(bill_number)s created successfully!') % {'bill_number': bill_number})
        )


        # "Save & Print" opens the printable bill.
        if request.POST.get("action") == "save_print":
            next_url = reverse("purchase_invoice", args=[purchase.id]) + "?print=1"
        else:
            next_url = reverse("purchase_product_list")

        if _wants_json(request):
            return JsonResponse({"success": True, "redirect": next_url})

        return redirect(next_url)


    # =========================================================
    # VALIDATION ERRORS
    # =========================================================

    except (ValueError, ValidationError) as exc:

        # ValidationError: e.g. a batch number reused with a different expiry.
        error_message = (
            " ".join(exc.messages)
            if isinstance(exc, ValidationError)
            else str(exc)
        )

        logger.warning(
            "Purchase validation failed. "
            "user=%s error=%s",
            request.user.username,
            error_message
        )


        return _purchase_error(request, error_message)


    # =========================================================
    # INTEGRITY ERROR
    # =========================================================

    except IntegrityError:

        logger.exception(
            "IntegrityError while creating purchase. "
            "user=%s",
            request.user.username
        )


        return _purchase_error(
            request,
            gettext('A purchase with this bill number may already exist.'),
            status=409,
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


        return _purchase_error(
            request,
            gettext('Something went wrong while saving the purchase. Please try again.'),
            status=500,
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
                (gettext("Product '%(product_name)s' was not found for this retailer.") % {'product_name': product_name})
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
                (gettext("Please select a unit for '%(product_name)s'.") % {'product_name': product_name})
            )


        try:

            unit = Unit.objects.get(
                id=unit_id
            )

        except Unit.DoesNotExist:

            raise ValueError(
                (gettext("Selected unit was not found for '%(product_name)s'.") % {'product_name': product_name})
            )


        # =====================================================
        # MRP
        # =====================================================

        mrp = decimal_from_post(
            request.POST.get(
                f"item_mrp_{index}",
                "0"
            ),
            (gettext('MRP for %(product_name)s') % {'product_name': product_name})
        )


        # =====================================================
        # QUANTITY
        # =====================================================

        # Fractions (2.5 kg) only for shops that sell loose quantities.
        shop_features = get_features(retailer)
        allow_fraction = shop_features.decimal_quantity

        quantity = parse_quantity(
            request.POST.get(
                f"item_qty_{index}",
                ""
            ),
            (gettext("Quantity for '%(product_name)s'") % {'product_name': product_name}),
            allow_fraction=allow_fraction,
        )


        # =====================================================
        # FREE QUANTITY
        # =====================================================

        free_quantity = parse_quantity(
            request.POST.get(
                f"item_free_qty_{index}",
                ""
            ),
            (gettext("Free quantity for '%(product_name)s'") % {'product_name': product_name}),
            allow_fraction=allow_fraction,
            allow_zero=True,
            default="0",
        )


        # =====================================================
        # UNIT CONVERSION
        #
        # A line entered in the product's purchase unit (e.g. Box)
        # adds (quantity + free) x factor base units (e.g. pc).
        # Without unit conversion the factor is always 1.
        # =====================================================

        conversion_factor = conversion_factor_for(
            product,
            unit,
            shop_features
        )

        stock_to_add = to_base_quantity(
            quantity + free_quantity,
            conversion_factor,
            (gettext("Quantity for '%(product_name)s'") % {'product_name': product_name}),
            allow_fraction=allow_fraction,
        )


        # =====================================================
        # PURCHASE PRICE
        # =====================================================

        purchase_price = decimal_from_post(
            request.POST.get(
                f"item_price_{index}",
                "0"
            ),
            (gettext('Purchase price for %(product_name)s') % {'product_name': product_name})
        )


        if purchase_price <= Decimal("0"):

            raise ValueError(
                (gettext("Purchase price for '%(product_name)s' must be greater than zero.") % {'product_name': product_name})
            )


        # =====================================================
        # GST CODE
        # =====================================================

        # Rate from the current GST slabs (gst.py). Older forms may
        # still send "none" / "gstN"; parse_rate understands both.
        try:

            gst_rate = parse_gst_rate(
                request.POST.get(
                    f"item_tax_{index}",
                    "0"
                )
            )

        except ValueError as exc:

            raise ValueError(
                (gettext("Invalid GST selected for '%(product_name)s'. %(exc)s") % {'product_name': product_name, 'exc': exc})
            )


        # =====================================================
        # BATCH + EXPIRY (features.batch_tracking only)
        #
        # Required on every line; ignored for other shops.
        # =====================================================

        batch_number = None
        expiry_date = None

        if shop_features.batch_tracking:
            try:
                batch_number = batch_stock.clean_batch_number(
                    request.POST.get(f"item_batch_{index}"),
                    (gettext("Batch number for '%(product_name)s'") % {'product_name': product_name}),
                )
                expiry_date = batch_stock.parse_expiry(
                    request.POST.get(f"item_expiry_{index}"),
                    (gettext("Expiry date for '%(product_name)s'") % {'product_name': product_name}),
                )
            except ValidationError as exc:
                raise ValueError(" ".join(exc.messages))


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

            "conversion_factor": conversion_factor,

            "stock_to_add": stock_to_add,

            "purchase_price": purchase_price,

            "mrp": mrp,

            "gst_rate": gst_rate,

            "item_subtotal": item_subtotal,

            "item_gst": item_gst,

            "item_total": item_total,

            "product_name": product_name,

            "batch_number": batch_number,

            "expiry_date": expiry_date,

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

        purchase_item = PurchaseItem.objects.create(

            purchase=purchase,

            product=product,

            batch_number=item.get("batch_number"),

            expiry_date=item.get("expiry_date"),

            unit=item["unit"],

            quantity=item["quantity"],

            free_quantity=item[
                "free_quantity"
            ],

            # Factor at the time of purchase (1 = bought in base unit)
            conversion_factor=item[
                "conversion_factor"
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
        # STOCK TO ADD (in the product's base unit)
        #
        # Example:
        #
        # Quantity      = 10 Box
        # Free Quantity = 2 Box
        # 1 Box         = 100 pc
        #
        # Stock Added   = (10 + 2) x 100 = 1200 pc
        # =====================================================

        stock_to_add = item["stock_to_add"]


        # =====================================================
        # SUPPLIER SELLS THIS PRODUCT (supplier product list)
        # Keeps the latest price (per base unit) and bill date.
        # =====================================================

        link_supplier_product(
            purchase.supplier,
            product,
            price=money(item["purchase_price"] / (item["conversion_factor"] or Decimal("1"))),
            bill_date=purchase.bill_date,
        )


        if item.get("batch_number"):

            # =================================================
            # BATCH-TRACKED SHOP: stock goes into the batch and
            # the product total together (same transaction).
            # Prices on the batch are per base unit.
            # =================================================

            factor = item["conversion_factor"] or Decimal("1")
            batch_mrp = (
                money(item["mrp"] / factor)
                if item["mrp"] and item["mrp"] > 0
                else None
            )

            purchase_item.batch = batch_stock.receive_into_batch(
                product,
                batch_number=item["batch_number"],
                expiry_date=item["expiry_date"],
                quantity=stock_to_add,
                purchase_price=money(item["purchase_price"] / factor),
                mrp=batch_mrp,
            )
            purchase_item.save(update_fields=["batch"])

        else:

            # =================================================
            # UPDATE PRODUCT STOCK
            # =================================================

            product.current_stock = (
                product.current_stock
                + stock_to_add
            )


            # =================================================
            # SAVE PRODUCT STOCK
            # =================================================

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

        # GET FILTER PARAMETERS (invalid dates are ignored)
        from_date = _parse_date(request.GET.get("from_date"))
        to_date = _parse_date(request.GET.get("to_date"))
        status = request.GET.get("status", "").strip()
        supplier_id = request.GET.get("supplier", "").strip()

        # APPLY FILTERS
        if from_date:
            purchases = purchases.filter(bill_date__gte=from_date)
        if to_date:
            purchases = purchases.filter(bill_date__lte=to_date)
        if status:
            purchases = purchases.filter(payment_status=status)
        if supplier_id.isdigit():
            purchases = purchases.filter(supplier_id=supplier_id)

        # PAGINATION
        paginator = Paginator(purchases, 25)
        page_number = request.GET.get("page")
        page_obj = paginator.get_page(page_number)

    except Exception:
        logger.exception("Failed to fetch purchase list.")
        messages.error(
            request, gettext('Something went wrong while loading purchases.')
        )
        page_obj = Paginator(Purchase.objects.none(), 25).get_page(1)
        supplier_list = Supplier.objects.none()

    context = {
        "purchases": page_obj,
        "page_obj": page_obj,
        "supplier_list": supplier_list,
        "is_admin": request.user.is_superuser,
        "today": timezone.localdate(),
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
                    gettext('Your account is not associated with a retailer.'),
                )

                return redirect("purchase_product_list")

            purchase = get_object_or_404(
                purchase_queryset,
                pk=purchase_id,
                retailer=retailer,
            )

        # ---------------------------------------------------------
        # Prefetched purchase items
        # ---------------------------------------------------------
        items = purchase.items.all()

        today = timezone.localdate()

        # ---------------------------------------------------------
        # Context
        # ---------------------------------------------------------
        context = {
            "purchase": purchase,
            "items": items,
            "payments": purchase.payments.select_related("created_by").order_by("payment_date", "id"),
            "purchase_returns": purchase.returns.order_by("return_date", "id"),
            "today": today,
            "is_overdue": bool(
                purchase.due_amount > 0
                and purchase.due_date
                and purchase.due_date < today
            ),
            "days_overdue": (
                (today - purchase.due_date).days
                if purchase.due_date and purchase.due_date < today else 0
            ),
            "days_left": (
                (purchase.due_date - today).days
                if purchase.due_date and purchase.due_date >= today else None
            ),
        }

        return render(
            request,
            "purchase_detail.html",
            context,
        )

    except Http404:
        # Missing purchase, or another shop's purchase: plain "not found".
        raise

    except DatabaseError:
        logger.exception(
            "Database error while loading purchase details. "
            "purchase_id=%s, user_id=%s",
            purchase_id,
            request.user.id,
        )

        messages.error(
            request,
            gettext('Unable to load purchase details. Please try again.'),
        )

        return redirect("purchase_product_list")

    except Exception:
        logger.exception(
            "Unexpected error while loading purchase details. "
            "purchase_id=%s, user_id=%s",
            purchase_id,
            request.user.id,
        )

        messages.error(
            request,
            gettext('Something went wrong while loading purchase details.'),
        )

        return redirect("purchase_product_list")


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
                error_message = gettext('Please select a retailer.')

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
                    gettext('Retailer does not exist or you are not authorized to use this retailer.')
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
                    (gettext('Please fill all required fields: %(missing_fields)s') % {'missing_fields': ", ".join(missing_fields)})
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
                error_message = gettext('Please enter a valid mobile number.')

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
                    gettext('Supplier already exists for this retailer.')
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

            if email:
                try:
                    validate_email(email)
                except ValidationError:
                    error_message = gettext('Please enter a valid email address.')

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
                    gettext('Invalid numeric or decimal format provided.')
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
                error_message = gettext('Opening balance cannot be negative.')

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
                error_message = gettext('Credit limit cannot be negative.')

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
                error_message = gettext('Credit days cannot be negative.')

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
                        "message": gettext('Supplier added successfully.')
                    },
                    status=201
                )

            # ====================================================
            # NORMAL FORM RESPONSE
            # ====================================================
            messages.success(
                request,
                gettext('Supplier added successfully.')
            )

            return redirect("supplier_list")

    # ============================================================
    # DATABASE / UNEXPECTED ERRORS
    # ============================================================
    except IntegrityError:

        logger.exception(
            "Database integrity error while creating supplier. "
            "User ID: %s",
            request.user.id
        )

        error_message = gettext('Supplier already exists or violates a database constraint.')

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
            gettext('Something went wrong while adding the supplier. Please try again.')
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


def _product_queryset_for(user):
    """
    Products the user may change.

    Admin: every product. Retailer: only their own shop's products.
    Anyone else: nothing.
    """

    if user.is_superuser:
        return Product.objects.all()

    retailer = Retailer.objects.filter(user=user, is_active=True).first()

    if retailer is None:
        return Product.objects.none()

    return Product.objects.filter(retailer=retailer)


@require_POST
@login_required(login_url="/user-login/")
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
            message=gettext('Product ID is required.'),
            status=400,
        )

    # ---------------------------------------------------------
    # 2. Fetch Product
    # ---------------------------------------------------------
    try:
        # Retailers can only reach their own products.
        product = _product_queryset_for(request.user).get(pk=product_id)

    except Product.DoesNotExist:
        logger.warning(
            "Product update failed: product not found. product_id=%s user=%s",
            product_id,
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=False,
            message=gettext('Product not found.'),
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
            message=gettext('Invalid product ID.'),
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
        # MRP may be empty for shops that do not require it.
        mrp = Decimal(mrp_raw) if (mrp_raw or "").strip() else None
        gst = Decimal(gst_raw)

        for value in (purchase_price, selling_price, mrp, gst):
            if value is not None and not value.is_finite():
                raise ValueError(gettext('Not a finite number.'))

        # Stock: Decimal; fractions only for shops that sell loose quantities.
        allow_fraction = get_features(product.retailer).decimal_quantity

        current_stock = parse_quantity(
            current_stock_raw, gettext('Current stock'),
            allow_fraction=allow_fraction, allow_zero=True,
        )
        minimum_stock = parse_quantity(
            minimum_stock_raw, gettext('Minimum stock'),
            allow_fraction=allow_fraction, allow_zero=True,
        )

    except (InvalidOperation, TypeError, ValueError) as exc:
        logger.warning(
            "Product update failed: invalid numeric values. "
            "product_id=%s user=%s",
            product_id,
            request.user if request.user.is_authenticated else "Anonymous",
        )

        return _product_update_response(
            request,
            success=False,
            message=(
                str(exc)
                if isinstance(exc, QuantityError)
                else "One or more numeric values are invalid."
            ),
            status=400,
        )

    # ---------------------------------------------------------
    # 5. Validate values
    # ---------------------------------------------------------
    if purchase_price <= 0:
        return _product_update_response(
            request,
            success=False,
            message=gettext('Purchase price must be greater than 0.'),
            status=400,
        )

    if selling_price <= 0:
        return _product_update_response(
            request,
            success=False,
            message=gettext('Selling price must be greater than 0.'),
            status=400,
        )

    # Rules follow the features of the shop that owns the product.
    shop_features = get_features(product.retailer)
    price_warning = ""

    if selling_price < purchase_price:
        if shop_features.allow_below_cost_sale:
            price_warning = (
                (gettext(' Note: selling price ₹%(selling_price)s is below the purchase price ₹%(purchase_price)s.') % {'selling_price': selling_price, 'purchase_price': purchase_price})
            )
        else:
            return _product_update_response(
                request,
                success=False,
                message=gettext('Selling price must be greater than or equal to purchase price.'),
                status=400,
            )

    if mrp is None and shop_features.mrp_required:
        return _product_update_response(
            request,
            success=False,
            message=gettext('MRP is required.'),
            status=400,
        )

    if mrp is not None and mrp <= 0:
        return _product_update_response(
            request,
            success=False,
            message=gettext('MRP must be greater than 0.'),
            status=400,
        )

    if mrp is not None and mrp < selling_price:
        return _product_update_response(
            request,
            success=False,
            message=gettext('MRP must be greater than or equal to selling price.'),
            status=400,
        )

    if gst < 0 or gst > 100:
        return _product_update_response(
            request,
            success=False,
            message=gettext('GST must be between 0 and 100.'),
            status=400,
        )

    if current_stock < 0:
        return _product_update_response(
            request,
            success=False,
            message=gettext('Current stock cannot be negative.'),
            status=400,
        )

    if minimum_stock < 0:
        return _product_update_response(
            request,
            success=False,
            message=gettext('Minimum stock cannot be negative.'),
            status=400,
        )

    # Batch-tracked stock is the sum of the product's batches, so it
    # changes only through purchases (batches) and sales.
    if shop_features.batch_tracking and current_stock != product.current_stock:
        return _product_update_response(
            request,
            success=False,
            message=(
                gettext('Stock of this product is kept batch-wise. Add stock through a purchase with batch and expiry.')
            ),
            status=400,
        )

    # Drug details: changed only when the form sends them (pharmacy).
    drug_details = {}

    try:
        if "schedule" in request.POST:
            drug_details = clean_drug_details(request.POST, shop_features)

        # Wholesale price / specification: only when the form sends them.
        if "wholesale_price" in request.POST or "specification" in request.POST:
            hardware_details, wholesale_warning = clean_hardware_details(
                request.POST, shop_features,
                purchase_price=purchase_price, selling_price=selling_price, mrp=mrp,
            )
            if "wholesale_price" not in request.POST:
                hardware_details.pop("wholesale_price", None)
            if "specification" not in request.POST:
                hardware_details.pop("specification", None)
            drug_details.update(hardware_details)
            if wholesale_warning:
                price_warning += " " + wholesale_warning
    except ValidationError as exc:
        return _product_update_response(
            request,
            success=False,
            message=" ".join(exc.messages),
            status=400,
        )

    # ---------------------------------------------------------
    # 6. Convert active status
    # ---------------------------------------------------------
    is_active = str(is_active_raw).lower() == "true"

    # Purchase unit + conversion: changed only when the form sends them
    # (and only for shops with unit conversion).
    conversion_change = None

    if "purchase_unit" in request.POST:
        try:
            conversion_change = clean_purchase_unit(
                product.unit_id,
                request.POST.get("purchase_unit"),
                request.POST.get("conversion_factor"),
                get_features(product.retailer),
                Unit.objects.all(),
            )
        except QuantityError as exc:
            return _product_update_response(
                request,
                success=False,
                message=str(exc),
                status=400,
            )

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

            for field_name, value in drug_details.items():
                if getattr(product, field_name) != value:
                    setattr(product, field_name, value)
                    changed_fields.append(field_name)

            if conversion_change is not None:
                new_purchase_unit, new_factor = conversion_change

                if product.purchase_unit_id != (new_purchase_unit.id if new_purchase_unit else None):
                    product.purchase_unit = new_purchase_unit
                    changed_fields.append("purchase_unit")

                if product.conversion_factor != new_factor:
                    product.conversion_factor = new_factor
                    changed_fields.append("conversion_factor")

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
            message=(gettext('Product updated successfully.%(price_warning)s') % {'price_warning': price_warning}),
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
            message=gettext('An unexpected error occurred while updating the product.'),
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
@login_required(login_url="/user-login/")
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
                "message": gettext('Product ID is required.'),
            },
            status=400,
        )

    # ---------------------------------------------------------
    # 2. Get product
    # ---------------------------------------------------------
    try:
        # Retailers can only reach their own products.
        product = _product_queryset_for(request.user).get(pk=product_id)

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
                "message": gettext('Product not found.'),
            },
            status=404,
        )

    # ---------------------------------------------------------
    # 3. Store product information before deletion
    # ---------------------------------------------------------
    product_name = product.product_name

    # A product that appears on purchase bills or sale invoices must
    # stay, otherwise those bills lose their lines. Deactivate instead.
    used_on_bills = (
        PurchaseItem.objects.filter(product=product).exists()
        or product.sale_items.exists()
    )

    if used_on_bills:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    (gettext('"%(product_name)s" is used on purchase or sale bills and cannot be deleted. Mark it as inactive instead.') % {'product_name': product_name})
                ),
            },
            status=409,
        )

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
                    (gettext('Product "%(product_name)s" deleted successfully.') % {'product_name': product_name})
                ),
            },
            status=200,
        )

    except ProtectedError:

        return JsonResponse(
            {
                "success": False,
                "message": (
                    (gettext('"%(product_name)s" is used on other records and cannot be deleted. Mark it as inactive instead.') % {'product_name': product_name})
                ),
            },
            status=409,
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
                    gettext('An unexpected error occurred while deleting the product.')
                ),
            },
            status=500,
        )


# ********************************* Sales Module *********************************


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
            (gettext('Invalid value for %(field_name)s.') % {'field_name': field_name})
        )

    if not value.is_finite():
        raise ValidationError(
            (gettext('Invalid value for %(field_name)s.') % {'field_name': field_name})
        )

    if value < ZERO:
        raise ValidationError(
            (gettext('%(field_name)s cannot be negative.') % {'field_name': field_name})
        )

    return value.quantize(TWO_PLACES)


def get_logged_in_retailer(request):
    """
    Return the retailer belonging to the logged-in user.
    """

    if not request.user.is_authenticated:
        raise ValidationError(
            gettext('You must be logged in.')
        )

    if request.user.is_superuser:
        # Admin works across shops and picks the shop on each form;
        # this is only a starting default (the first active shop).
        retailer = (
            Retailer.objects
            .filter(is_active=True)
            .order_by("id")
            .first()
        )
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
            gettext('No active retailer is associated with this user.')
        )

    return retailer


def get_posted_retailer_for_admin(request, default_retailer):
    """
    For a superuser, return the active retailer sent in POST["retailer"].
    Everyone else always uses their own retailer (default_retailer).
    """

    if not request.user.is_superuser:
        return default_retailer

    retailer_id = (request.POST.get("retailer") or "").strip()

    if not retailer_id.isdigit():
        raise ValidationError(gettext('Please select a retailer.'))

    retailer = (
        Retailer.objects
        .filter(pk=retailer_id, is_active=True)
        .first()
    )

    if retailer is None:
        raise ValidationError(gettext('Selected retailer does not exist.'))

    return retailer


def get_customer_ledger_balance(customer):
    """
    Return customer's current outstanding balance.
    """

    # Opening balance + all debits - all credits (correct even when an
    # entry is back-dated).
    from .accounts import customer_balance

    return customer_balance(customer)


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
            gettext('Ledger debit cannot be negative.')
        )

    if credit < ZERO:
        raise ValidationError(
            gettext('Ledger credit cannot be negative.')
        )

    if debit > ZERO and credit > ZERO:
        raise ValidationError(
            gettext('Ledger entry cannot contain both debit and credit.')
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
                (gettext("Discount cannot be greater than the amount for '%(product_name)s'.") % {'product_name': item['product'].product_name})
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


def _sale_error(request, message, status=400):
    """
    A sale could not be saved. The page (background save) gets the
    message as JSON and keeps everything the user typed; a plain form
    post goes back to an empty New Sale page with the message.
    """

    if _wants_json(request):
        return JsonResponse({"success": False, "error": message}, status=status)

    messages.error(request, message)
    return redirect("sale_create")


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
        - Validate the cash paid (0 .. grand total)
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
            is_admin = request.user.is_superuser

            if is_admin:
                # Admin picks the retailer on the page, so send every
                # active retailer's customers and products; the page
                # filters them by the chosen retailer.
                retailer = Retailer.objects.filter(is_active=True)
                customers = (
                    Customer.objects
                    .filter(is_active=True)
                    .order_by("customer_name")
                )
                products = (
                    Product.objects
                    .filter(is_active=True, retailer__in=retailer)
                    .select_related("unit")
                    .order_by("product_name")
                )

            # Each customer's current due (old udhari) for the sale screen.
            from .accounts import with_customer_totals

            # "Convert to sale": rows filled from an open quotation.
            quotation_prefill = quotation_sale_prefill(
                request, request.GET.get("quotation")
            )

            context = {
                "quotation_prefill": quotation_prefill,
                "state_choices": STATE_CHOICES,
                "customers": with_customer_totals(customers),
                "products": products,
                # Batches / prescription flags for pharmacy products only.
                "pharmacy_data": sale_pharmacy_data(products, today),
                "units": units,
                "today": today,
                "next_invoice_number": next_invoice_number,
                "retailers": retailer,
                "is_admin": is_admin,
                # Per-shop rules (loose quantities) for the sale form
                "shop_rules": product_rules_by_shop(
                    retailer if is_admin else [retailer]
                ),
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
                gettext('Unable to load the sales page. Please try again.'),
            )

            return redirect("dashboard")

    # ==========================================================
    # POST
    # ==========================================================

    try:

        # Admin sells on behalf of the retailer chosen on the page.
        retailer = get_posted_retailer_for_admin(request, retailer)

        # Features of the shop this sale is for (loose quantities, ...).
        sale_features = get_features(retailer)

        # ======================================================
        # 1. CUSTOMER
        # ======================================================

        customer_id = (
            request.POST.get("customer") or ""
        ).strip()

        if not customer_id:
            raise ValidationError(
                gettext('Please select a customer.')
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
                gettext('Selected customer does not exist.')
            )

        # ======================================================
        # 1b. QUOTATION BEING CONVERTED (features.quotations)
        # ======================================================

        quotation = None
        quoted_items = {}
        quotation_id = (request.POST.get("quotation") or "").strip()

        if quotation_id and sale_features.quotations:
            quotation = (
                Quotation.objects
                .filter(pk=quotation_id, retailer=retailer)
                .first()
                if quotation_id.isdigit()
                else None
            )

            if quotation is None:
                raise ValidationError(gettext('Selected quotation does not exist.'))

            if quotation.status == Quotation.STATUS_CONVERTED:
                raise ValidationError(
                    (gettext('Quotation %(quotation_number)s has already been converted to a sale.') % {'quotation_number': quotation.quotation_number})
                )

            if quotation.status != Quotation.STATUS_OPEN:
                raise ValidationError(
                    (gettext('Quotation %(quotation_number)s was cancelled and cannot be converted.') % {'quotation_number': quotation.quotation_number})
                )

            if quotation.customer_id != customer.id:
                raise ValidationError(
                    gettext('The customer must be the same as on the quotation.')
                )

            quoted_items = {
                item.product_id: item
                for item in quotation.items.all()
            }

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
            raise ValidationError(gettext('Please add at least one product.'))

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
                    (gettext('Product is missing in row %(row_number)s.') % {'row_number': row_number})
                )

            # ==================================================
            # DUPLICATE PRODUCT
            # ==================================================

            if product_id in processed_product_ids:

                raise ValidationError(
                    gettext('The same product cannot be added multiple times to the same invoice.')
                )

            processed_product_ids.add(
                product_id
            )

            # ==================================================
            # PRODUCT
            # ==================================================

            # Read-only check here; add_sale_item() locks the row and
            # re-checks stock inside the transaction.
            product = (
                Product.objects
                .filter(
                    pk=product_id,
                    retailer=retailer,
                    is_active=True,
                )
                .first()
                if product_id.isdigit()
                else None
            )

            if product is None:

                raise ValidationError(
                    (gettext('Product in row %(row_number)s does not exist.') % {'row_number': row_number})
                )

            # ==================================================
            # UNIT
            # ==================================================

            if not unit_id:

                raise ValidationError(
                    (gettext("Unit is missing for '%(product_name)s'.") % {'product_name': product.product_name})
                )

            unit = (
                Unit.objects
                .filter(pk=unit_id)
                .first()
            )

            if unit is None:

                raise ValidationError(
                    (gettext("Invalid unit for '%(product_name)s'.") % {'product_name': product.product_name})
                )

            # ==================================================
            # IMPORTANT UNIT CHECK
            # ==================================================

            if product.unit_id != unit.id:

                raise ValidationError(
                    (gettext("Invalid unit selected for '%(product_name)s'.") % {'product_name': product.product_name})
                )

            # ==================================================
            # QUANTITY
            # ==================================================

            # Up to 3 decimals (0.125 kg); fractions only for shops that
            # sell loose quantities (features.decimal_quantity).
            try:
                quantity = parse_quantity(
                    request.POST.get(quantity_key),
                    (gettext("Quantity for '%(product_name)s'") % {'product_name': product.product_name}),
                    allow_fraction=sale_features.decimal_quantity,
                )
            except QuantityError as exc:
                raise ValidationError(str(exc))

            # ==================================================
            # STOCK
            # ==================================================

            batch_id = None

            if sale_features.batch_tracking:
                # Only unexpired batches can be sold. Optional chosen
                # batch; otherwise earliest expiry first (FEFO).
                available_stock = batch_stock.sellable_quantity(
                    product, invoice_date
                )

                batch_id = (
                    request.POST.get(f"items[{row_number}][batch]") or ""
                ).strip() or None

                if batch_id is not None:
                    chosen_batch = (
                        ProductBatch.objects
                        .filter(pk=batch_id, product=product, retailer=retailer)
                        .first()
                        if batch_id.isdigit()
                        else None
                    )

                    if chosen_batch is None:
                        raise ValidationError(
                            (gettext("Selected batch for '%(product_name)s' does not exist.") % {'product_name': product.product_name})
                        )

                    if chosen_batch.is_expired(invoice_date):
                        raise ValidationError(
                            (gettext("Batch %(batch_number)s of '%(product_name)s' has expired and cannot be sold.") % {'batch_number': chosen_batch.batch_number, 'product_name': product.product_name})
                        )
            else:
                available_stock = (
                    product.current_stock or ZERO
                )

            if quantity > available_stock:

                raise ValidationError(
                    (gettext("Insufficient stock for '%(product_name)s'. Available stock: %(available_stock)s. Requested quantity: %(quantity)s.") % {'product_name': product.product_name, 'available_stock': format_quantity(available_stock), 'quantity': format_quantity(quantity)})
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

            # Wholesale customers pay the wholesale price in shops with
            # price levels (Product.price_for); everyone else the
            # normal selling price. A converted quotation keeps its
            # quoted price (read from the database, never the form).
            quoted_item = quoted_items.get(product.id)

            if quoted_item is not None:
                selling_price = quoted_item.selling_price
            else:
                selling_price = Decimal(
                    str(product.price_for(customer, sale_features))
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

            # GST % comes from the product (the field is Product.gst),
            # or from the quotation line being converted.
            gst = Decimal(
                str(quoted_item.gst if quoted_item is not None else (product.gst or ZERO))
            ).quantize(TWO_PLACES)

            # ==================================================
            # DISCOUNT
            # ==================================================

            discount = decimal_value(
                request.POST.get(discount_key),
                (gettext('Discount for %(product_name)s') % {'product_name': product.product_name}),
            )

            # ==================================================
            # CALCULATE LINE
            # ==================================================

            gross_amount = (
                quantity * selling_price
            ).quantize(TWO_PLACES)

            if discount > gross_amount:

                raise ValidationError(
                    (gettext("Discount for '%(product_name)s' cannot exceed ₹%(gross_amount)s.") % {'product_name': product.product_name, 'gross_amount': gross_amount})
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
                    "batch_id": batch_id,
                }
            )

        # ======================================================
        # 4b. PRESCRIPTION DETAILS (features.prescription_details)
        # ======================================================

        patient_name = doctor_name = prescription_note = ""

        if sale_features.prescription_details:
            patient_name = (request.POST.get("patient_name") or "").strip()[:150]
            doctor_name = (request.POST.get("doctor_name") or "").strip()[:150]
            prescription_note = (request.POST.get("prescription_note") or "").strip()

            scheduled = [
                item["product"].product_name
                for item in processed_items
                if item["product"].needs_prescription
            ]

            if scheduled and (not patient_name or not doctor_name):
                raise ValidationError(
                    (gettext('Patient name and doctor name are required for prescription drugs: %(scheduled)s.') % {'scheduled': ", ".join(scheduled)})
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
                gettext('Grand total must be greater than zero.')
            )

        # ======================================================
        # 6. PAYMENT (cash only)
        # ======================================================
        #
        # Sales are paid in cash. The paid amount can be anything
        # from 0 (whole bill on udhari) up to the grand total; the
        # rest stays due on the customer's account. Any payment type
        # sent by the form is ignored.

        payment_type = Sale.PAYMENT_TYPE_CASH

        paid_amount = decimal_value(
            request.POST.get("paid_amount"),
            gettext('Paid amount'),
        )

        if paid_amount > grand_total:

            raise ValidationError(
                (gettext('Paid amount cannot exceed grand total of ₹%(grand_total)s.') % {'grand_total': grand_total})
            )

        due_amount = (
            grand_total - paid_amount
        ).quantize(TWO_PLACES)

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
                    (gettext("Credit limit exceeded for '%(customer_name)s'. Current outstanding: ₹%(current_balance)s. New due: ₹%(due_amount)s. Credit limit: ₹%(credit_limit)s.") % {'customer_name': customer.customer_name, 'current_balance': current_balance, 'due_amount': due_amount, 'credit_limit': credit_limit})
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
                patient_name=patient_name,
                doctor_name=doctor_name,
                prescription_note=prescription_note,
                # CGST+SGST (customer in the shop's state or state not
                # known) or IGST (another state); features.b2b_tax_split.
                **tax_fields(sale_features, retailer.state, customer.state, total_gst),
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
                    batch_tracking=sale_features.batch_tracking,
                    batch_id=item["batch_id"],
                    on_date=invoice_date,
                )

            # --------------------------------------------------
            # QUOTATION -> CONVERTED (locked so it converts once)
            # --------------------------------------------------

            if quotation is not None:
                locked_quotation = (
                    Quotation.objects
                    .select_for_update()
                    .get(pk=quotation.pk)
                )

                if locked_quotation.status != Quotation.STATUS_OPEN:
                    raise ValidationError(
                        (gettext('Quotation %(quotation_number)s was already converted or cancelled.') % {'quotation_number': locked_quotation.quotation_number})
                    )

                locked_quotation.status = Quotation.STATUS_CONVERTED
                locked_quotation.converted_sale = sale
                locked_quotation.save(
                    update_fields=["status", "converted_sale", "updated_at"]
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

                payment = Payment(
                    retailer=retailer,
                    customer=customer,
                    sale=sale,
                    payment_date=invoice_date,
                    amount=paid_amount,
                    payment_type=payment_type,
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
                    gettext('Payment calculation mismatch.')
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
            (gettext('Sale %(invoice_number)s created successfully.') % {'invoice_number': sale.invoice_number})
        )

        if action == "save_print":
            next_url = reverse("sale_invoice", args=[sale.id])
        else:
            next_url = reverse("sales_list")

        if _wants_json(request):
            return JsonResponse({"success": True, "redirect": next_url})

        return redirect(next_url)

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

        return _sale_error(request, error_message)

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

        return _sale_error(
            request,
            gettext('Unable to create the sale because of a database conflict. Please try again.'),
            status=409,
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

        return _sale_error(
            request,
            gettext('An unexpected error occurred while creating the sale. Please try again.'),
            status=500,
        )




@require_POST
@login_required
def create_customer_ajax(request):
    """
    Create customer from the Add Customer modal.

    Mobile number is unique per retailer.
    """
    try:

        retailer = get_posted_retailer_for_admin(
            request,
            get_logged_in_retailer(request),
        )

        customer_name = (
            request.POST.get("customer_name") or ""
        ).strip()

        mobile = (
            request.POST.get("mobile") or ""
        ).strip()

        email = (
            request.POST.get("email") or ""
        ).strip()

        address = (
            request.POST.get("address") or ""
        ).strip()

        opening_balance = decimal_value(
            request.POST.get("opening_balance"),
            gettext('Opening balance'),
        )

        credit_limit = decimal_value(
            request.POST.get("credit_limit"),
            gettext('Credit limit'),
        )

        # ------------------------------------------------------
        # NAME
        # ------------------------------------------------------

        if not customer_name:
            raise ValidationError(
                gettext('Customer name is required.')
            )

        if len(customer_name) > 200:
            raise ValidationError(
                gettext('Customer name cannot exceed 200 characters.')
            )

        # ------------------------------------------------------
        # MOBILE
        # ------------------------------------------------------

        if not mobile:
            raise ValidationError(
                gettext('Mobile number is required.')
            )

        # Keep only digits for validation.
        normalized_mobile = "".join(
            character
            for character in mobile
            if character.isdigit()
        )

        if len(normalized_mobile) != 10:
            raise ValidationError(
                gettext('Please enter a valid 10-digit mobile number.')
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
                        gettext('A customer with this mobile number already exists.')
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
        # PRICE LEVEL (features.price_levels; others: retail)
        # ------------------------------------------------------

        price_level = Customer.PRICE_LEVEL_RETAIL

        if get_features(retailer).price_levels:
            price_level = (
                request.POST.get("price_level") or Customer.PRICE_LEVEL_RETAIL
            ).strip()

            if price_level not in dict(Customer.PRICE_LEVEL_CHOICES):
                raise ValidationError(gettext('Please select a valid price level.'))

        # ------------------------------------------------------
        # STATE (features.b2b_tax_split: another state -> IGST)
        # ------------------------------------------------------

        customer_state = ""

        if get_features(retailer).b2b_tax_split:
            raw_state = (request.POST.get("state") or "").strip()
            customer_state = state_key(raw_state)

            if raw_state and not customer_state:
                raise ValidationError(gettext('Please select a valid state.'))

        # ------------------------------------------------------
        # CREATE CUSTOMER
        # ------------------------------------------------------

        with transaction.atomic():

            customer = Customer.objects.create(
                retailer=retailer,
                customer_name=customer_name,
                mobile=normalized_mobile,
                email=email or None,
                address=address or None,
                opening_balance=opening_balance,
                credit_limit=credit_limit,
                price_level=price_level,
                state=customer_state,
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
                "message": gettext('Customer created successfully.'),
                "customer": {
                    "id": customer.id,
                    "retailer_id": retailer.id,
                    "name": customer.customer_name,
                    "mobile": customer.mobile,
                    "email": customer.email or "",
                    "address": customer.address or "",
                    "credit_limit": str(
                        customer.credit_limit
                    ),
                    "opening_balance": str(
                        customer.opening_balance
                    ),
                    "price_level": customer.price_level,
                    "state": customer.state,
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
                    gettext('A customer with this mobile number already exists.')
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
                    gettext('Unable to create customer. Please try again.')
                ),
            },
            status=500,
        )


@require_GET
@login_required
def sale_product_data(request, product_id):

    try:
        products = Product.objects.filter(is_active=True)

        # Admin can sell for any shop; a retailer only sees own products.
        if not request.user.is_superuser:
            products = products.filter(
                retailer=get_logged_in_retailer(request)
            )

        product = products.filter(pk=product_id).first()

        if product is None:
            return JsonResponse(
                {
                    "success": False,
                    "message": gettext('Product not found.'),
                },
                status=404,
            )

        product_features = get_features(product.retailer)
        stock = product.current_stock
        batches = []

        if product_features.batch_tracking:
            # Unexpired batches, earliest expiry first (FEFO order).
            today = date.today()
            stock = batch_stock.sellable_quantity(product, today)
            batches = [
                {
                    "id": batch.id,
                    "batch_number": batch.batch_number,
                    "expiry": batch.expiry_date.strftime("%m/%Y"),
                    "quantity": format_quantity(batch.quantity),
                    "mrp": str(batch.mrp) if batch.mrp is not None else "",
                }
                for batch in product.batches.filter(
                    quantity__gt=0, expiry_date__gte=today
                ).order_by("expiry_date", "id")
            ]

        return JsonResponse(
            {
                "success": True,
                "product": {
                    "id": product.id,
                    "name": product.product_name,

                    # Clean number: "10", "2.5" (not "10.000")
                    "stock": format_quantity(stock),
                    "unit": product.unit.short_name if product.unit_id else "",
                    "decimal_quantity": product_features.decimal_quantity,
                    "batch_tracking": product_features.batch_tracking,
                    "batches": batches,
                    "schedule": product.schedule if product_features.prescription_details else "",
                    "needs_prescription": (
                        product_features.prescription_details and product.needs_prescription
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
                "message": gettext('Unable to fetch product.'),
            },
            status=500,
        )


# ********************************* Shared Access Helpers *********************************

def _is_admin(user):
    """
    Admin users (Django superusers) can see data of every retailer.
    """

    return user.is_superuser


def _get_user_retailer(user):
    """
    Return the active retailer profile of a retailer user, or None.
    """

    return (
        Retailer.objects
        .filter(
            user=user,
            is_active=True,
        )
        .first()
    )


def _parse_date(value):
    """
    Parse a YYYY-MM-DD string. Returns None for empty/invalid input.
    """

    try:
        return datetime.strptime(
            (value or "").strip(),
            "%Y-%m-%d"
        ).date()
    except ValueError:
        return None


def _querystring_without_page(request):
    """
    Current GET filters as a querystring, without the page number,
    so pagination links keep the active filters.
    """

    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


# ********************************* Purchase History *********************************

@require_GET
@login_required(login_url="/user-login/")
def purchase_history(request, product_id):
    """
    Return the purchase history of a product as JSON.

    Used by the Add Purchase page: when the user selects a product,
    it shows from which suppliers the product was bought before and
    the lowest / highest / last purchase price.

    Access rules:
    - Admin can see the history of any product.
    - Retailer can see the history of their own products only.
    """

    products = Product.objects.select_related("unit")

    if not _is_admin(request.user):

        retailer = _get_user_retailer(request.user)

        if retailer is None:
            return JsonResponse(
                {
                    "success": False,
                    "message": gettext('No active retailer profile is linked to your account.'),
                },
                status=403,
            )

        products = products.filter(
            retailer=retailer
        )

    product = products.filter(pk=product_id).first()

    if product is None:
        return JsonResponse(
            {
                "success": False,
                "message": gettext('Product not found.'),
            },
            status=404,
        )

    try:

        # Newest purchase first.
        items = list(
            PurchaseItem.objects
            .filter(product=product)
            .select_related("purchase__supplier", "unit")
            .order_by(
                "-purchase__bill_date",
                "-purchase__created_at",
                "-id",
            )
        )

        product_data = {
            "id": product.id,
            "name": product.product_name,
            "unit": product.unit.short_name if product.unit_id else "",
        }

        if not items:
            return JsonResponse(
                {
                    "success": True,
                    "product": product_data,
                    "summary": None,
                    "suppliers": [],
                    "recent": [],
                }
            )

        # -------------------------------------------------------
        # Overall summary
        # Prices are compared per BASE unit (e.g. per pc), so a bill
        # bought per Box (1 Box = 100 pc) is comparable with one bought
        # per piece. Quantities are in base units too.
        # -------------------------------------------------------
        lowest = min(items, key=lambda item: item.base_unit_price)
        highest = max(items, key=lambda item: item.base_unit_price)
        latest = items[0]

        total_qty = sum(
            (item.quantity * item.conversion_factor for item in items),
            ZERO,
        )

        total_value = sum(
            (item.quantity * item.purchase_price for item in items),  # = base qty x base price
            ZERO,
        )

        average_price = (
            total_value / total_qty
            if total_qty > ZERO
            else ZERO
        )

        summary = {
            "purchases": len(items),
            "total_qty": str(total_qty),
            "min_price": str(lowest.base_unit_price),
            "min_supplier": lowest.purchase.supplier.supplier_name,
            "min_date": lowest.purchase.bill_date.isoformat(),
            "max_price": str(highest.base_unit_price),
            "max_supplier": highest.purchase.supplier.supplier_name,
            "max_date": highest.purchase.bill_date.isoformat(),
            "avg_price": str(average_price.quantize(TWO_PLACES)),
            "last_price": str(latest.base_unit_price),
            "last_supplier": latest.purchase.supplier.supplier_name,
            "last_date": latest.purchase.bill_date.isoformat(),
        }

        # -------------------------------------------------------
        # Supplier-wise breakdown
        # Items are newest first, so the first item seen for a
        # supplier is that supplier's last purchase.
        # -------------------------------------------------------
        suppliers = {}

        for item in items:

            supplier = item.purchase.supplier
            price = item.base_unit_price

            entry = suppliers.get(supplier.id)

            if entry is None:
                entry = suppliers[supplier.id] = {
                    "supplier": supplier.supplier_name,
                    "purchases": 0,
                    "total_qty": ZERO,
                    "min_price": price,
                    "max_price": price,
                    "last_price": price,
                    "last_date": item.purchase.bill_date.isoformat(),
                }

            entry["purchases"] += 1
            entry["total_qty"] += item.quantity * item.conversion_factor
            entry["min_price"] = min(entry["min_price"], price)
            entry["max_price"] = max(entry["max_price"], price)

        # Cheapest supplier first.
        supplier_rows = sorted(
            suppliers.values(),
            key=lambda entry: entry["min_price"],
        )

        for entry in supplier_rows:
            for key in ("total_qty", "min_price", "max_price", "last_price"):
                entry[key] = str(entry[key])

        # -------------------------------------------------------
        # Recent purchases (latest 10)
        # -------------------------------------------------------
        recent = [
            {
                "date": item.purchase.bill_date.isoformat(),
                "bill_number": item.purchase.bill_number,
                "supplier": item.purchase.supplier.supplier_name,
                # Base units (e.g. pc) so every row is comparable
                "quantity": str(item.quantity * item.conversion_factor),
                "free_quantity": str(item.free_quantity * item.conversion_factor),
                "price": str(item.base_unit_price),
                # What was entered on the bill (e.g. 2 Box @ 500)
                "entered": (
                    f"{format_quantity(item.quantity)} {item.unit.short_name} @ {item.purchase_price}"
                    if item.is_converted else ""
                ),
                "gst": str(item.gst),
            }
            for item in items[:10]
        ]

        return JsonResponse(
            {
                "success": True,
                "product": product_data,
                "summary": summary,
                "suppliers": supplier_rows,
                "recent": recent,
            }
        )

    except Exception:

        logger.exception(
            "Unable to load purchase history. product_id=%s user_id=%s",
            product_id,
            request.user.id,
        )

        return JsonResponse(
            {
                "success": False,
                "message": gettext('Unable to load purchase history.'),
            },
            status=500,
        )


# ********************************* Supplier Table *********************************

SUPPLIER_TEXT_FIELDS = (
    "supplier_name",
    "contact_person",
    "mobile",
    "alternate_mobile",
    "email",
    "gst_number",
    "pan_number",
    "address",
    "city",
    "state",
    "pincode",
    "notes",
)


def _supplier_queryset_for(user):
    """
    Suppliers visible to the user.

    Returns None for a retailer user without an active retailer profile.
    """

    suppliers = Supplier.objects.select_related("retailer")

    if _is_admin(user):
        return suppliers

    retailer = _get_user_retailer(user)

    if retailer is None:
        return None

    return suppliers.filter(retailer=retailer)


def _clean_supplier_data(data):
    """
    Validate supplier form data.

    Returns a dict of cleaned model field values.
    Raises ValueError with a user-friendly message when invalid.
    """

    cleaned = {
        field: (data.get(field) or "").strip()
        for field in SUPPLIER_TEXT_FIELDS
    }

    required_fields = {
        "Supplier Name": cleaned["supplier_name"],
        "Mobile": cleaned["mobile"],
        "Address": cleaned["address"],
        "City": cleaned["city"],
        "State": cleaned["state"],
        "Pincode": cleaned["pincode"],
    }

    missing_fields = [
        field_name
        for field_name, value in required_fields.items()
        if not value
    ]

    if missing_fields:
        raise ValueError(
            (gettext('Please fill all required fields: %(missing_fields)s') % {'missing_fields': ", ".join(missing_fields)})
        )

    mobile_digits = "".join(
        character
        for character in cleaned["mobile"]
        if character.isdigit()
    )

    if not 10 <= len(mobile_digits) <= 15:
        raise ValueError(gettext('Please enter a valid mobile number.'))

    cleaned["mobile"] = mobile_digits

    if cleaned["email"]:
        try:
            validate_email(cleaned["email"])
        except ValidationError:
            raise ValueError(gettext('Please enter a valid email address.'))

    try:
        opening_balance = Decimal(data.get("opening_balance") or "0.00")
        credit_limit = Decimal(data.get("credit_limit") or "0.00")
        credit_days = int(data.get("credit_days") or 0)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(gettext('Invalid numeric or decimal format provided.'))

    if opening_balance < 0:
        raise ValueError(gettext('Opening balance cannot be negative.'))

    if credit_limit < 0:
        raise ValueError(gettext('Credit limit cannot be negative.'))

    if credit_days < 0:
        raise ValueError(gettext('Credit days cannot be negative.'))

    # Optional text fields are stored as NULL when empty.
    for field in (
        "contact_person",
        "alternate_mobile",
        "email",
        "gst_number",
        "pan_number",
        "notes",
    ):
        cleaned[field] = cleaned[field] or None

    cleaned["opening_balance"] = opening_balance
    cleaned["credit_limit"] = credit_limit
    cleaned["credit_days"] = credit_days
    cleaned["is_active"] = "is_active" in data

    return cleaned


def _serialize_supplier(supplier):
    """
    Supplier fields used by the view / edit modals.
    """

    return {
        "id": supplier.id,
        "retailer": supplier.retailer.shop_name,
        "supplier_name": supplier.supplier_name,
        "contact_person": supplier.contact_person or "",
        "mobile": supplier.mobile,
        "alternate_mobile": supplier.alternate_mobile or "",
        "email": supplier.email or "",
        "gst_number": supplier.gst_number or "",
        "pan_number": supplier.pan_number or "",
        "address": supplier.address,
        "city": supplier.city,
        "state": supplier.state,
        "pincode": supplier.pincode,
        "opening_balance": str(supplier.opening_balance),
        "credit_limit": str(supplier.credit_limit),
        "credit_days": supplier.credit_days,
        "is_active": supplier.is_active,
        "notes": supplier.notes or "",
    }


@login_required(login_url="/user-login/")
def supplier_list(request):
    """
    Supplier table.

    Admin:
        - Sees suppliers of all retailer shops (with shop name).
        - Can filter by supplier name, retailer and status.
        - Can view / edit / delete any supplier.

    Retailer:
        - Sees only their own suppliers.
        - Can filter by supplier name and status.
        - Can view / edit / delete only their own suppliers.
    """

    is_admin = _is_admin(request.user)

    suppliers = _supplier_queryset_for(request.user)

    if suppliers is None:
        messages.error(
            request,
            gettext('No active retailer profile is linked to your account.')
        )
        return redirect("dashboard")

    search = request.GET.get("search", "").strip()
    retailer_id = request.GET.get("retailer", "").strip()
    status = request.GET.get("status", "").strip().lower()

    if search:
        suppliers = suppliers.filter(
            supplier_name__icontains=search
        )

    if is_admin and retailer_id.isdigit():
        suppliers = suppliers.filter(
            retailer_id=retailer_id
        )

    if status == "active":
        suppliers = suppliers.filter(is_active=True)
    elif status == "inactive":
        suppliers = suppliers.filter(is_active=False)

    # Purchase.supplier uses related_name="supplier", so this
    # counts the purchases made from each supplier.
    suppliers = (
        suppliers
        .annotate(purchase_count=Count("supplier"))
        .order_by("supplier_name", "retailer__shop_name")
    )

    page_obj = Paginator(suppliers, 25).get_page(
        request.GET.get("page")
    )

    context = {
        "suppliers": page_obj,
        "page_obj": page_obj,
        "supplier_data": {
            supplier.id: _serialize_supplier(supplier)
            for supplier in page_obj
        },
        "is_admin": is_admin,
        "retailers": (
            Retailer.objects.filter(is_active=True).order_by("shop_name")
            if is_admin
            else Retailer.objects.none()
        ),
        "search": search,
        "selected_retailer": retailer_id,
        "status": status,
        "querystring": _querystring_without_page(request),
    }

    return render(
        request,
        "supplier_list.html",
        context,
    )


@require_POST
@login_required(login_url="/user-login/")
def supplier_update(request, supplier_id):
    """
    Update a supplier from the edit modal (AJAX, returns JSON).

    Retailers can update only their own suppliers.
    """

    suppliers = _supplier_queryset_for(request.user)

    supplier = (
        suppliers.filter(pk=supplier_id).first()
        if suppliers is not None
        else None
    )

    if supplier is None:
        logger.warning(
            "Supplier update denied or not found. "
            "supplier_id=%s user_id=%s",
            supplier_id,
            request.user.id,
        )

        return JsonResponse(
            {
                "success": False,
                "message": gettext('Supplier not found.'),
            },
            status=404,
        )

    try:
        cleaned = _clean_supplier_data(request.POST)
    except ValueError as exc:
        return JsonResponse(
            {
                "success": False,
                "message": str(exc),
            },
            status=400,
        )

    duplicate = (
        Supplier.objects
        .filter(
            retailer=supplier.retailer,
            supplier_name__iexact=cleaned["supplier_name"],
        )
        .exclude(pk=supplier.pk)
        .exists()
    )

    if duplicate:
        return JsonResponse(
            {
                "success": False,
                "message": gettext('Another supplier with this name already exists for this retailer.'),
            },
            status=409,
        )

    try:
        with transaction.atomic():
            for field, value in cleaned.items():
                setattr(supplier, field, value)

            supplier.save()

    except IntegrityError:
        logger.exception(
            "IntegrityError while updating supplier. supplier_id=%s",
            supplier_id,
        )

        return JsonResponse(
            {
                "success": False,
                "message": gettext('Supplier violates a database constraint.'),
            },
            status=409,
        )

    except Exception:
        logger.exception(
            "Unexpected error while updating supplier. supplier_id=%s",
            supplier_id,
        )

        return JsonResponse(
            {
                "success": False,
                "message": gettext('Something went wrong while updating the supplier.'),
            },
            status=500,
        )

    logger.info(
        "Supplier updated. supplier_id=%s user_id=%s",
        supplier.id,
        request.user.id,
    )

    return JsonResponse(
        {
            "success": True,
            "message": gettext('Supplier updated successfully.'),
            "supplier": _serialize_supplier(supplier),
        }
    )


@require_POST
@login_required(login_url="/user-login/")
def supplier_delete(request, supplier_id):
    """
    Delete a supplier (AJAX, returns JSON).

    Deleting a supplier would cascade-delete its purchase bills,
    so suppliers that have purchases cannot be deleted; they should
    be marked inactive instead.
    """

    suppliers = _supplier_queryset_for(request.user)

    supplier = (
        suppliers.filter(pk=supplier_id).first()
        if suppliers is not None
        else None
    )

    if supplier is None:
        logger.warning(
            "Supplier delete denied or not found. "
            "supplier_id=%s user_id=%s",
            supplier_id,
            request.user.id,
        )

        return JsonResponse(
            {
                "success": False,
                "message": gettext('Supplier not found.'),
            },
            status=404,
        )

    purchase_count = Purchase.objects.filter(supplier=supplier).count()

    if purchase_count:
        return JsonResponse(
            {
                "success": False,
                "message": (
                    (gettext('"%(supplier_name)s" has %(purchase_count)s purchase bill(s) and cannot be deleted. Mark the supplier as inactive instead.') % {'supplier_name': supplier.supplier_name, 'purchase_count': purchase_count})
                ),
            },
            status=409,
        )

    supplier_name = supplier.supplier_name

    try:
        supplier.delete()

    except Exception:
        logger.exception(
            "Unexpected error while deleting supplier. supplier_id=%s",
            supplier_id,
        )

        return JsonResponse(
            {
                "success": False,
                "message": gettext('Something went wrong while deleting the supplier.'),
            },
            status=500,
        )

    logger.info(
        "Supplier deleted. supplier_id=%s name=%s user_id=%s",
        supplier_id,
        supplier_name,
        request.user.id,
    )

    return JsonResponse(
        {
            "success": True,
            "message": (gettext('Supplier "%(supplier_name)s" deleted successfully.') % {'supplier_name': supplier_name}),
        }
    )


# ********************************* Sales Table *********************************

def _sales_queryset_for(user):
    """
    Sales visible to the user.

    Returns None for a retailer user without an active retailer profile.
    """

    sales = Sale.objects.select_related("retailer", "customer")

    if _is_admin(user):
        return sales

    retailer = _get_user_retailer(user)

    if retailer is None:
        return None

    return sales.filter(retailer=retailer)


@login_required(login_url="/user-login/")
def sales_list(request):
    """
    Sales table.

    Admin:
        - Sees sales of all retailer shops (with shop name).
        - Filters: retailer, customer name, date range, status.

    Retailer:
        - Sees only their own shop's sales.
        - Filters: customer name, date range, status.

    Both roles can open a sale and download its invoice.
    """

    is_admin = _is_admin(request.user)

    sales = _sales_queryset_for(request.user)

    if sales is None:
        messages.error(
            request,
            gettext('No active retailer profile is linked to your account.')
        )
        return redirect("dashboard")

    customer = request.GET.get("customer", "").strip()
    retailer_id = request.GET.get("retailer", "").strip()
    status = request.GET.get("status", "").strip()
    from_date = _parse_date(request.GET.get("from_date"))
    to_date = _parse_date(request.GET.get("to_date"))

    if customer:
        sales = sales.filter(
            Q(customer__customer_name__icontains=customer)
            | Q(customer__mobile__icontains=customer)
        )

    if is_admin and retailer_id.isdigit():
        sales = sales.filter(retailer_id=retailer_id)

    if status in dict(Sale.PAYMENT_STATUS_CHOICES):
        sales = sales.filter(payment_status=status)

    if from_date and to_date and from_date > to_date:
        messages.warning(
            request,
            gettext("'From' date was after 'To' date, so the dates were swapped.")
        )
        from_date, to_date = to_date, from_date

    if from_date:
        sales = sales.filter(invoice_date__gte=from_date)

    if to_date:
        sales = sales.filter(invoice_date__lte=to_date)

    totals = sales.aggregate(
        total_amount=Sum("grand_total"),
        total_paid=Sum("paid_amount"),
        total_due=Sum("due_amount"),
    )

    sales = sales.order_by("-invoice_date", "-created_at")

    page_obj = Paginator(sales, 25).get_page(
        request.GET.get("page")
    )

    context = {
        "sales": page_obj,
        "page_obj": page_obj,
        "is_admin": is_admin,
        "retailers": (
            Retailer.objects.filter(is_active=True).order_by("shop_name")
            if is_admin
            else Retailer.objects.none()
        ),
        "customer": customer,
        "selected_retailer": retailer_id,
        "status": status,
        "from_date": from_date.isoformat() if from_date else "",
        "to_date": to_date.isoformat() if to_date else "",
        "total_amount": totals["total_amount"] or ZERO,
        "total_paid": totals["total_paid"] or ZERO,
        "total_due": totals["total_due"] or ZERO,
        "querystring": _querystring_without_page(request),
    }

    return render(
        request,
        "sales_list.html",
        context,
    )


def sale_gst_summary(sale):
    """GST per rate for the invoice (CGST+SGST or IGST, per sale.tax_type)."""

    return rate_wise_summary(
        [
            (item.gst, item.quantity * item.selling_price - item.discount)
            for item in sale.items.all()
        ],
        sale.tax_type,
    )


def _get_sale_for_user(request, sale_id):
    """
    Fetch a sale with its items and payments, enforcing access rules.

    Raises Http404 when the sale does not exist or belongs to
    another retailer.
    """

    sales = _sales_queryset_for(request.user)

    if sales is None:
        raise Http404("Sale not found.")

    return get_object_or_404(
        sales.prefetch_related(
            Prefetch(
                "items",
                queryset=SaleItem.objects.select_related("product", "unit", "batch"),
            ),
            "payments",
        ),
        pk=sale_id,
    )


@login_required(login_url="/user-login/")
def sale_detail(request, sale_id):
    """
    View a single sale with its items, totals and payments.
    """

    sale = _get_sale_for_user(request, sale_id)

    return render(
        request,
        "sale_detail.html",
        {
            "sale": sale,
            "items": sale.items.all(),
            "payments": sale.payments.all(),
            # Features of the sale's own shop (the admin's menu features
            # are a union of all shops).
            "sale_features": get_features(sale.retailer),
            "gst_summary": sale_gst_summary(sale),
            "sale_returns": sale.returns.order_by("return_date", "id"),
        },
    )


@login_required(login_url="/user-login/")
def sale_invoice(request, sale_id):
    """
    Printable / downloadable tax invoice for a sale.

    Opening the page with ?download=1 downloads the invoice as a PDF.
    """

    sale = _get_sale_for_user(request, sale_id)

    return render(
        request,
        "sale_invoice.html",
        {
            "sale": sale,
            "items": sale.items.all(),
            "sale_features": get_features(sale.retailer),
            "gst_summary": sale_gst_summary(sale),
            "auto_download": request.GET.get("download") == "1",
        },
    )
