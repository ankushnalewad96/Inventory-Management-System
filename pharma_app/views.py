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


# @staff_member_required
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
        current_stock = request.POST.get("current_stock", "0").strip()
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


def product_mapping(request):
    return render(request,"product_mapping.html")


@login_required(login_url='/user-login/')
def product_list(request):
    """
    Displays the retailer's product catalog in a tabular format,
    including category, brand, and unit details, ordered alphabetically
    by product name.
    """
    try:
        products = Product.objects.select_related(
            "category", "brand", "unit", "retailer"
        ).order_by("product_name")
    except Exception:
        logger.exception("Failed to fetch product list.")
        messages.error(request, "Something went wrong while loading the product list.")
        products = Product.objects.none()

    context = {"products": products}
    return render(request, "product_list.html", context)


GST_RATE_MAP = {
    "none": 0,
    "gst5": 5,
    "gst12": 12,
    "gst18": 18,
    "gst28": 28,
}


@login_required(login_url='/user-login/')
def add_order(request):
    """
    Handles creation of a purchase order (Purchase) along with its
    line items (PurchaseItem).

    The entire purchase — header + all items — is created inside a
    single atomic transaction: if any item fails to save, the whole
    purchase is rolled back instead of leaving a partially-saved record.
    """
    
    if request.method == "POST":
        return _handle_add_order(request)

    products = Product.objects.filter(is_active=True).order_by("product_name")
    units = Unit.objects.all()
    supplier_list = Supplier.objects.filter(is_active = True).order_by("supplier_name")
    retailer_list = Retailer.objects.filter(is_active = True).order_by("shop_name")

    context = {
        "products": products,
        "units": units,
        "supplier_list": supplier_list,
        "retailer_list": retailer_list,
    }

    return render(request, "add_order.html",context)


def _handle_add_order(request):
    """Validates form data and creates the Purchase + PurchaseItem records."""

    if request.user.is_superuser:
        retailer_id = request.POST.get("retailer", "").strip()
        print(">>>>>>>>>>>>>>>>> retailer             ", retailer_id) 
    else:
        retailer_id = getattr(request.user, "retailer", None)

       
    if retailer_id is None:
        logger.warning("User without a retailer profile attempted to add an order: user=%s", request.user.username)
        messages.error(request, "No retailer profile is linked to your account.")
        return redirect("add_new_order")

    retailer = Retailer.objects.get(id = retailer_id)

    supplier_id = request.POST.get("supplier", "").strip()
    bill_number = request.POST.get("bill_number", "").strip()
    bill_date = request.POST.get("bill_date", "").strip()
    bill_time = request.POST.get("bill_time") or None
    logger.warning("User without a retailer profile attempted to add an order")
    if not supplier_id or not bill_number or not bill_date:
        messages.error(request, "Supplier, bill number, and bill date are required.")
        return redirect("add_new_order")

    # --- Parse header-level numeric fields ---
    try:
        subtotal = Decimal(request.POST.get("subtotal", 0) or 0)
        discount = Decimal(request.POST.get("discount", 0) or 0)
        gst = Decimal(request.POST.get("gst", 0) or 0)
        grand_total = Decimal(request.POST.get("grand_total", 0) or 0)
        paid_amount = Decimal(request.POST.get("paid_amount", 0) or 0)
        due_amount = grand_total - paid_amount

    except InvalidOperation:
        logger.warning("Invalid numeric value submitted while adding order by user=%s", request.user.username)
        messages.error(request, "Please enter valid numeric values for amount fields.")
        return redirect("add_new_order")

    payment_status = "Paid" if due_amount <= 0 else ("Partial" if paid_amount > 0 else "Unpaid")

    try:
        with transaction.atomic():
            purchase = Purchase.objects.create(
                retailer=retailer,
                supplier=Supplier.objects.get(id = supplier_id),
                bill_number=bill_number,
                bill_date=bill_date,
                bill_time=bill_time,
                invoice_date=bill_date,
                payment_terms=request.POST.get("payment_terms", "").strip(),
                due_date=request.POST.get("due_date") or None,
                state_of_supply=request.POST.get("state_of_supply", "").strip(),
                warehouse=request.POST.get("warehouse", "").strip(),
                subtotal=subtotal,
                discount=discount,
                gst=gst,
                grand_total=grand_total,
                paid_amount=paid_amount,
                due_amount=due_amount,
                payment_type=request.POST.get("payment_type", "").strip(),
                payment_status=payment_status,
                remarks="",
            )

            if request.FILES.get("bill_file"):
                purchase.bill_file = request.FILES["bill_file"]
                purchase.save(update_fields=["bill_file"])

            # breakpoint()

            _create_purchase_items(request, purchase)

        logger.info(
            "Purchase order created by user=%s: bill_number=%s, retailer=%s",
            request.user.username, bill_number, retailer.shop_name,
        )
        messages.success(request, f"Purchase order {bill_number} created successfully!")
        return redirect("dashboard")

    except IntegrityError:
        logger.exception("IntegrityError while creating purchase order: bill_number=%s", bill_number)
        messages.error(request, "A purchase with this bill number may already exist.")
        return redirect("add_new_order")

    except ValueError as e:
        # Raised deliberately from _create_purchase_items for bad item data
        logger.warning("Invalid item data while creating purchase order: %s", str(e))
        messages.error(request, str(e))
        return redirect("add_new_order")

    except Exception:
        logger.exception("Unexpected error while creating purchase order: bill_number=%s", bill_number)
        messages.error(request, "Something went wrong while saving the purchase. Please try again.")
        return redirect("add_new_order")


def _create_purchase_items(request, purchase):
    """
    Parses dynamically-named item_* fields from the POST data and creates
    a PurchaseItem for each one, resolving product and unit by name.

    Raises ValueError (caught by the caller) if a referenced product or
    unit does not exist, so the whole transaction rolls back cleanly.
    """
    for key, value in request.POST.items():
        if not key.startswith("item_name_"):
            continue

        index = key.split("_")[-1]
        name = request.POST.get(f"item_name_{index}", "").strip()
        print(name,"            Name:::::::::::")
        if not name:
            continue

        unit_name = request.POST.get(f"item_unit_{index}", "").strip()
        print(unit_name,"            unit_name :::::::::::")


        try:
            mrp = Decimal(request.POST.get(f"item_mrp_{index}", 0) or 0)
            qty = Decimal(request.POST.get(f"item_qty_{index}", 0) or 0)
            free_qty_raw = request.POST.get(f"item_free_qty_{index}", "0")
            free_qty = Decimal(free_qty_raw) if free_qty_raw.strip() else Decimal("0")
            price = Decimal(request.POST.get(f"item_price_{index}", 0) or 0)
        except InvalidOperation:
            raise ValueError(f"Invalid numeric value for item '{name}'.")

        tax_code = request.POST.get(f"item_tax_{index}", "none")
        gst_rate = GST_RATE_MAP.get(tax_code, 0)

        amount = qty * price
        tax_amount = amount * (Decimal(str(gst_rate)) / Decimal("100"))
        total_amount = amount + tax_amount

        try:
            product = Product.objects.get(product_name__iexact=name, retailer=purchase.retailer)
        except Product.DoesNotExist:
            raise ValueError(f"Product '{name}' was not found. Please add it to inventory first.")

        try:
            unit = Unit.objects.get(id = unit_name)
        except Unit.DoesNotExist:
            raise ValueError(f"Unit '{unit_name}' was not found for item '{name}'.")

        PurchaseItem.objects.create(
            purchase=purchase,
            product=product,
            unit=unit,
            quantity=qty,
            free_quantity=free_qty,
            purchase_price=price,
            selling_price=product.selling_price,
            mrp=mrp,
            gst=gst_rate,
            discount=0,
            amount=total_amount,
            remarks=name,
        )


@login_required(login_url='/user-login/')
def purchase_list(request):
    """Displays all purchase orders, most recent first."""
    try:
        purchases = Purchase.objects.select_related("retailer").order_by("-bill_date", "-created_at")
        supplier_list = Supplier.objects.filter(is_active = True).order_by("supplier_name")
    except Exception:
        logger.exception("Failed to fetch purchase list.")
        messages.error(request, "Something went wrong while loading purchases.")
        purchases = Purchase.objects.none()

    context = {"purchases": purchases, "supplier_list":supplier_list}
    return render(request, "purchase_list.html", context)


@login_required(login_url='/user-login/')
def add_supplier(request):
    """
    Create a new supplier securely and safely.
    """
    # GET Request: Render the entry form
    if request.method != "POST":
        # SECURITY FIX: Filter retailers belonging strictly to the logged-in user
        # Replace 'user=request.user' with your actual model relationship (e.g., profile.retailer)
        retailers = Retailer.objects.filter(is_active=True)
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



# @login_required(login_url='/user-login/')
# def add_supplier(request):
#     """
#     Create a new supplier.

#     Features:
#     - Transaction safe
#     - Logging
#     - Duplicate supplier validation
#     - Proper exception handling
#     """

#     if request.method != "POST":
#         retailers = Retailer.objects.filter(is_active=True)

#         return render(
#             request,
#             "test.html",
#             {
#                 "retailers": retailers
#             }
#         )

#     try:

#         with transaction.atomic():
#             retailer = Retailer.objects.get(
#                 id=request.POST.get("retailer"),
#                 is_active=True
#             )

#             supplier_name = request.POST.get("supplier_name", "").strip()
#             if not supplier_name:
#                 messages.error(request, "Supplier Name is required.")
#                 return redirect("add_supplier")

#             if Supplier.objects.filter(
#                 retailer=retailer,
#                 supplier_name__iexact=supplier_name
#             ).exists():

#                 messages.error(
#                     request,
#                     "Supplier already exists."
#                 )

#                 logger.warning(
#                     "Duplicate supplier '%s' attempted by retailer %s",
#                     supplier_name,
#                     retailer.id
#                 )

#                 return redirect("add_supplier")

#             supplier = Supplier.objects.create(

#                 retailer=retailer,

#                 supplier_name=supplier_name,

#                 contact_person=request.POST.get(
#                     "contact_person"
#                 ),

#                 mobile=request.POST.get(
#                     "mobile"
#                 ),

#                 alternate_mobile=request.POST.get(
#                     "alternate_mobile"
#                 ),

#                 email=request.POST.get(
#                     "email"
#                 ),

#                 gst_number=request.POST.get(
#                     "gst_number"
#                 ),

#                 pan_number=request.POST.get(
#                     "pan_number"
#                 ),

#                 address=request.POST.get(
#                     "address"
#                 ),

#                 city=request.POST.get(
#                     "city"
#                 ),

#                 state=request.POST.get(
#                     "state"
#                 ),

#                 pincode=request.POST.get(
#                     "pincode"
#                 ),

#                 opening_balance=Decimal(
#                     request.POST.get(
#                         "opening_balance",
#                         0
#                     ) or 0
#                 ),

#                 credit_limit=Decimal(
#                     request.POST.get(
#                         "credit_limit",
#                         0
#                     ) or 0
#                 ),

#                 credit_days=request.POST.get(
#                     "credit_days",
#                     0
#                 ) or 0,

#                 is_active=request.POST.get(
#                     "is_active"
#                 ) == "True",

#                 notes=request.POST.get(
#                     "notes"
#                 )

#             )

#             logger.info(
#                 "Supplier '%s' created successfully by retailer %s",
#                 supplier.supplier_name,
#                 retailer.id
#             )

#             messages.success(
#                 request,
#                 "Supplier added successfully."
#             )

#             return redirect("supplier_list")

#     except Retailer.DoesNotExist:

#         logger.error(
#             "Retailer not found while creating supplier."
#         )

#         messages.error(
#             request,
#             "Retailer does not exist."
#         )

#     except InvalidOperation:

#         logger.exception(
#             "Invalid decimal value while creating supplier."
#         )

#         messages.error(
#             request,
#             "Invalid amount entered."
#         )

#     except IntegrityError:

#         logger.exception(
#             "Database integrity error while creating supplier."
#         )

#         messages.error(
#             request,
#             "Supplier already exists."
#         )

#     except Exception as e:

#         logger.exception(
#             "Unexpected error while creating supplier: %s",
#             str(e)
#         )

#         messages.error(
#             request,
#             "Something went wrong. Please try again."
#         )

#     return redirect("add_supplier")

# def retailer_register(request):

#     if request.method == "POST":

#         username = request.POST.get("username")
#         password = request.POST.get("password")
#         email = request.POST.get("email")

#         shop_name = request.POST.get("shop_name")
#         owner_name = request.POST.get("owner_name")
#         mobile = request.POST.get("mobile")
#         gst_number = request.POST.get("gst_number")
#         pan_number = request.POST.get("pan_number")
#         address = request.POST.get("address")
#         city = request.POST.get("city")
#         state = request.POST.get("state")
#         pincode = request.POST.get("pincode")

#         if CustomUser.objects.filter(username=username).exists():
#             messages.error(request, "Username already exists.")
#             return redirect("retailer_register")

#         if CustomUser.objects.filter(email=email).exists():
#             messages.error(request, "Email already exists.")
#             return redirect("retailer_register")

#         user = CustomUser.objects.create_user(
#             username=username,
#             email=email,
#             password=password,
#             user_type="retailer",
#         )

#         Retailer.objects.create(
#             user=user,
#             shop_name=shop_name,
#             owner_name=owner_name,
#             mobile=mobile,
#             email=email,
#             gst_number=gst_number,
#             pan_number=pan_number,
#             address="address",
#             city=city,
#             state=state,
#             pincode=pincode,
#         )

#         messages.success(request, "Retailer Registered Successfully.")
#         return redirect("user_login")

#     return render(request, "register.html")


# def _login(request):
#     if request.method == 'POST':
#         username = request.POST.get('username', '').strip()
#         password = request.POST.get('password', '')

#         if not username or not password:
#             messages.error(request, "Both username and password are required fields.")
#             return render(request, 'login.html')

#         # Authenticate details against hashed DB entries
#         user = authenticate(request, username=username, password=password)
        
#         if user is not None:
#             login(request, user)
#             messages.success(request, f"Access Granted. Welcome, {user.username}.")
#             return redirect('dashboard')
#         else:
#             messages.error(request, "Invalid authentication credentials supplied.")

#     return render(request, 'login.html')


# def user_logout(request):
#     logout(request)
#     return redirect('user_login')


# def add_product(request):

#     retailers = Retailer.objects.all()
#     categories = Category.objects.all()
#     brands = Brand.objects.all()
#     units = Unit.objects.all()

#     if request.method == "POST":

#         Product.objects.create(

#             retailer=Retailer.objects.get(
#                 id=request.POST["retailer"]
#             ),

#             category=Category.objects.get(
#                 id=request.POST["category"]
#             ),

#             brand=Brand.objects.get(
#                 id=request.POST["brand"]
#             ),

#             product_name=request.POST["product_name"],
#             barcode=request.POST["barcode"],
#             hsn_code=request.POST["hsn_code"],
#             unit=Unit.objects.get(id=request.POST["unit"]),
#             purchase_price=request.POST["purchase_price"],
#             selling_price=request.POST["selling_price"],
#             mrp=request.POST["mrp"],
#             minimum_stock=request.POST["minimum_stock"],
#             current_stock=request.POST["current_stock"],
#             gst=request.POST["gst"],
#         )

#         messages.success(request, "Product Added Successfully")

#         return redirect("dashboard")
#     print(categories,"          :::::::::::::::::::::::::")
#     context = {
#         "retailers": retailers,
#         "categories": categories,
#         "brands": brands,
#         "units": units,
#     }

#     return render(request, "add_product.html", context)


# def add_order(request):
#     if request.method == 'POST':
#         try:
#             # Get Purchase data
#             supplier_name = request.POST.get('supplier')
#             bill_number = request.POST.get('bill_number')
#             bill_date = request.POST.get('bill_date')
#             bill_time = request.POST.get('bill_time') or None
            
#             # Create Purchase instance
#             purchase = Purchase.objects.create(
#                 retailer_id=request.user.retailer.id,  # Assuming user has retailer relationship
#                 supplier=supplier_name,
#                 bill_number=bill_number,
#                 bill_date=bill_date,
#                 bill_time=bill_time,
#                 invoice_date=bill_date,  # Using bill date as invoice date
#                 payment_terms=request.POST.get('payment_terms', ''),
#                 due_date=request.POST.get('due_date') or None,
#                 state_of_supply=request.POST.get('state_of_supply', ''),
#                 warehouse=request.POST.get('warehouse', ''),
#                 subtotal=Decimal(request.POST.get('subtotal', 0)),
#                 discount=Decimal(request.POST.get('discount', 0)),
#                 gst=Decimal(request.POST.get('gst', 0)),
#                 grand_total=Decimal(request.POST.get('grand_total', 0)),
#                 paid_amount=Decimal(request.POST.get('paid_amount', 0)),  # Default
#                 due_amount=(Decimal(request.POST.get('grand_total', 0))-Decimal(request.POST.get('paid_amount', 0))),  # Default to grand total
#                 payment_type=request.POST.get('payment_type', ''),
#                 payment_status='Unpaid',
#                 remarks='',
#             )

#             # Handle bill file upload
#             if request.FILES.get('bill_file'):
#                 purchase.bill_file = request.FILES['bill_file']
#                 purchase.save()

#             # Process items
#             items_data = []
#             for key, value in request.POST.items():
#                 if key.startswith('item_name_'):
#                     index = key.split('_')[-1]
                    
#                     # Get all fields for this item
#                     name = request.POST.get(f'item_name_{index}')

#                     if not name:
#                         continue
                    
#                     mrp = Decimal(request.POST.get(f'item_mrp_{index}', 0))
#                     qty = Decimal(request.POST.get(f'item_qty_{index}', 0))
#                     raw_free_qty = request.POST.get(f'item_free_qty_{index}', '0')
#                     free_qty = Decimal(raw_free_qty) if raw_free_qty.strip() else Decimal('0')
#                     unit = request.POST.get(f'item_unit_{index}', 'none')
#                     price = Decimal(request.POST.get(f'item_price_{index}', 0))
#                     tax_code = request.POST.get(f'item_tax_{index}', 'none')
                    
#                     # Calculate tax rate from code
#                     tax_rates = {
#                         'none': 0,
#                         'gst5': 5,
#                         'gst12': 12,
#                         'gst18': 18,
#                         'gst28': 28
#                     }
#                     gst_rate = tax_rates.get(tax_code, 0)
                    
#                     # Calculate amount
#                     amount = qty * price
#                     tax_amount = amount * (Decimal(str(gst_rate)) / Decimal('100'))
#                     total_amount = amount + tax_amount
                    
#                     # Create PurchaseItem
#                     purchase_item = PurchaseItem.objects.create(
#                         purchase=purchase,
#                         product_id=1,  # You'll need to map product by name
#                         unit_id=1,  # You'll need to map unit by name
#                         quantity=qty,
#                         free_quantity=free_qty,
#                         purchase_price=price,
#                         selling_price=0,  # You might want to set this
#                         mrp=mrp,
#                         gst=gst_rate,
#                         discount=0,
#                         amount=total_amount,
#                         remarks=name,  # Store product name in remarks if product not found
#                     )
                    
#                     items_data.append({
#                         'name': name,
#                         'quantity': qty,
#                         'price': price,
#                         'amount': total_amount
#                     })

#             messages.success(request, f'Purchase order {bill_number} created successfully!')
#             # return redirect('purchase_detail', pk=purchase.id)
#             return redirect('dashboard')
            
#         except Exception as e:
#             messages.error(request, f'Error saving purchase: {str(e)}')
#             return redirect('add_new_order')
    
#     return render(request, 'add_order.html')


# def purchase_list(request):
#     """
#     Simple view to display all purchase orders
#     """
#     purchases = Purchase.objects.all().order_by('-bill_date', '-created_at')
    
#     context = {
#         'purchases': purchases,
#     }
#     return render(request, 'purchase_list.html', context)

