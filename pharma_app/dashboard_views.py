"""
Dashboard: one page to see and reach every module.

Admin    -> all shops (or one shop picked with ?retailer=<id>), plus a
            shop-by-shop performance table and the Retailers module.
Retailer -> only their own shop.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .models import (
    Customer,
    Payment,
    Product,
    Purchase,
    Retailer,
    Sale,
    SaleItem,
    Supplier,
)
from .pharmacy_views import expiry_summary, shops_with_feature
from .shop_types import get_features
from django.utils.translation import gettext, ngettext

logger = logging.getLogger("pharma_app")

ZERO = Decimal("0.00")
MONEY = DecimalField(max_digits=14, decimal_places=2)
CHART_DAYS = 14


def _sum(queryset, field):
    return queryset.aggregate(
        total=Coalesce(Sum(field), Value(ZERO), output_field=MONEY)
    )["total"]


def _percent_change(current, previous):
    """Signed % change vs the previous period, or None when there is no base."""

    if not previous:
        return None
    return round(float((current - previous) / previous * 100), 1)


def _nice_ceiling(value):
    """Round a chart maximum up to a clean number (1, 2, 2.5, 5 x 10^n)."""

    if value <= 0:
        return Decimal("100")

    value = float(value)
    magnitude = 10 ** (len(str(int(value))) - 1)

    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return Decimal(str(step * magnitude))

    return Decimal(str(10 * magnitude))


def _compact(value):
    """₹ axis labels: 950 / 1.2K / 3.4L / 1.1Cr (Indian units)."""

    value = float(value)

    if value >= 1_00_00_000:
        return f"{value / 1_00_00_000:.1f}Cr".replace(".0Cr", "Cr")
    if value >= 1_00_000:
        return f"{value / 1_00_000:.1f}L".replace(".0L", "L")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    return f"{value:.0f}"


def _sales_chart(sales, today):
    """Daily sales for the last CHART_DAYS days, with bar heights in %."""

    start = today - timedelta(days=CHART_DAYS - 1)

    per_day = {
        row["invoice_date"]: row
        for row in sales.filter(invoice_date__gte=start, invoice_date__lte=today)
        .values("invoice_date")
        .annotate(total=Sum("grand_total"), invoices=Count("id"))
    }

    days = []
    for offset in range(CHART_DAYS):
        day = start + timedelta(days=offset)
        row = per_day.get(day, {})
        days.append({
            "date": day,
            "total": row.get("total") or ZERO,
            "invoices": row.get("invoices", 0),
            "is_today": day == today,
        })

    peak = max((day["total"] for day in days), default=ZERO)
    ceiling = _nice_ceiling(peak)

    for day in days:
        day["height"] = round(float(day["total"] / ceiling * 100), 2) if ceiling else 0

    ticks = [
        {"label": _compact(ceiling * Decimal(step) / 4), "position": step * 25}
        for step in range(4, -1, -1)
    ]

    best = max(days, key=lambda day: day["total"]) if peak > 0 else None

    return {
        "days": days,
        "ticks": ticks,
        "total": sum((day["total"] for day in days), ZERO),
        "best": best,
        "has_data": peak > 0,
    }


def _receivable(customers):
    """What customers owe: opening balance + billed - received (dues only)."""

    rows = customers.annotate(
        billed=Coalesce(
            Sum("ledger_entries__debit"), Value(ZERO), output_field=MONEY
        ),
        received=Coalesce(
            Sum("ledger_entries__credit"), Value(ZERO), output_field=MONEY
        ),
    ).annotate(
        due=ExpressionWrapper(
            F("opening_balance") + F("billed") - F("received"),
            output_field=MONEY,
        )
    )

    # Round each due to paise in Python: SQLite returns these sums as
    # floats, and a leftover like 0.0000001 must not count as a due.
    owing = []
    for customer in rows.select_related("retailer"):
        customer.due = Decimal(str(customer.due or 0)).quantize(Decimal("0.01"))
        if customer.due > 0:
            owing.append(customer)

    owing.sort(key=lambda customer: customer.due, reverse=True)

    return {
        "total": sum((customer.due for customer in owing), ZERO),
        "count": len(owing),
        "top": owing[:5],
    }


@login_required(login_url="/user-login/")
def dashboard(request):
    is_admin = request.user.is_superuser
    today = timezone.localdate()
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    # Same number of days into last month, for a fair comparison.
    last_month_same_day = min(
        last_month_start + timedelta(days=(today - month_start).days),
        last_month_end,
    )

    # ---------------------------------------------------------- scope
    shop = None
    selected_retailer = ""

    if is_admin:
        selected_retailer = request.GET.get("retailer", "").strip()
        if selected_retailer.isdigit():
            shop = Retailer.objects.filter(pk=selected_retailer).first()
            if shop is None:
                selected_retailer = ""
        else:
            selected_retailer = ""
    else:
        shop = Retailer.objects.filter(user=request.user, is_active=True).first()

        if shop is None:
            messages.error(request, gettext('No active retailer profile is linked to your account.'))
            return render(request, "dashboard.html", {"no_shop": True, "is_admin": False})

    def scoped(queryset, field="retailer"):
        return queryset.filter(**{field: shop}) if shop is not None else queryset

    sales = scoped(Sale.objects.all())
    purchases = scoped(Purchase.objects.all())
    products = scoped(Product.objects.all())
    suppliers = scoped(Supplier.objects.all())
    customers = scoped(Customer.objects.all())
    payments_in = scoped(Payment.objects.all())

    # ---------------------------------------------------------- sales
    sales_today = sales.filter(invoice_date=today)
    sales_month = sales.filter(invoice_date__gte=month_start, invoice_date__lte=today)
    sales_last_month = sales.filter(
        invoice_date__gte=last_month_start, invoice_date__lte=last_month_same_day
    )

    sales_today_total = _sum(sales_today, "grand_total")
    sales_month_total = _sum(sales_month, "grand_total")
    sales_last_month_total = _sum(sales_last_month, "grand_total")

    collected_today = _sum(payments_in.filter(payment_date=today), "amount")

    # ---------------------------------------------------------- purchases / payable
    purchases_month = purchases.filter(bill_date__gte=month_start, bill_date__lte=today)
    open_bills = purchases.filter(due_amount__gt=0)
    overdue_bills = open_bills.filter(due_date__lt=today)
    due_soon_bills = open_bills.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7))

    payable_total = _sum(open_bills, "due_amount")
    overdue_total = _sum(overdue_bills, "due_amount")

    # ---------------------------------------------------------- stock
    active_products = products.filter(is_active=True)
    low_stock = active_products.filter(current_stock__gt=0, current_stock__lte=F("minimum_stock"))
    out_of_stock = active_products.filter(current_stock=0)
    stock_value = active_products.aggregate(
        value=Coalesce(
            Sum(ExpressionWrapper(F("current_stock") * F("purchase_price"), output_field=MONEY)),
            Value(ZERO),
            output_field=MONEY,
        )
    )["value"]

    # ---------------------------------------------------------- customers
    receivable = _receivable(customers)

    # ---------------------------------------------------------- top products this month
    top_products = list(
        scoped(SaleItem.objects.all(), "sale__retailer")
        .filter(sale__invoice_date__gte=month_start, sale__invoice_date__lte=today)
        .values("product__id", "product__product_name", "unit__short_name")
        .annotate(quantity=Sum("quantity"), amount=Sum("amount"))
        .order_by("-amount")[:5]
    )
    top_amount = max((row["amount"] for row in top_products), default=ZERO)
    for row in top_products:
        row["share"] = round(float(row["amount"] / top_amount * 100), 1) if top_amount else 0

    # ---------------------------------------------------------- expiry (features.expiry_tracking)
    if shop is not None:
        expiry_shops = [shop] if get_features(shop).expiry_tracking else []
    else:
        expiry_shops = shops_with_feature(request.user, "expiry_tracking")

    expiry = expiry_summary(expiry_shops, today) if expiry_shops else None

    # ---------------------------------------------------------- alerts
    alerts = []
    if expiry and expiry["expired_count"]:
        alerts.append({
            "tone": "critical", "icon": "fa-ban",
            "title": (ngettext('%(count)s expired batch in stock', '%(count)s expired batches in stock', expiry['expired_count']) % {'count': expiry['expired_count']}),
            "text": gettext('Expired stock cannot be sold; return or remove it'),
            "url": reverse("near_expiry") + "?days=expired",
        })
    if expiry and expiry["near_expiry_count"]:
        alerts.append({
            "tone": "warning", "icon": "fa-hourglass-half",
            "title": (ngettext('%(count)s batch expiring in 90 days', '%(count)s batches expiring in 90 days', expiry['near_expiry_count']) % {'count': expiry['near_expiry_count']}),
            "text": gettext('Sell these first or return them to the supplier'),
            "url": reverse("near_expiry"),
        })
    if overdue_bills.exists():
        alerts.append({
            "tone": "critical", "icon": "fa-triangle-exclamation",
            "title": (ngettext('%(count)s supplier bill overdue', '%(count)s supplier bills overdue', overdue_bills.count()) % {'count': overdue_bills.count()}),
            "text": (gettext('₹%(overdue_total)s past the due date') % {'overdue_total': overdue_total}),
            "url": reverse("purchase_product_list"),
        })
    if due_soon_bills.exists():
        alerts.append({
            "tone": "warning", "icon": "fa-hourglass-half",
            "title": (ngettext('%(count)s bill due this week', '%(count)s bills due this week', due_soon_bills.count()) % {'count': due_soon_bills.count()}),
            "text": (gettext('₹%(due_amount)s to pay in the next 7 days') % {'due_amount': _sum(due_soon_bills, 'due_amount')}),
            "url": reverse("purchase_product_list"),
        })
    if out_of_stock.exists():
        alerts.append({
            "tone": "critical", "icon": "fa-box-open",
            "title": (ngettext('%(count)s product out of stock', '%(count)s products out of stock', out_of_stock.count()) % {'count': out_of_stock.count()}),
            "text": gettext('Reorder now to avoid missed sales'),
            "url": reverse("low_stock_alert"),
        })
    if low_stock.exists():
        alerts.append({
            "tone": "warning", "icon": "fa-boxes-stacked",
            "title": (ngettext('%(count)s product running low', '%(count)s products running low', low_stock.count()) % {'count': low_stock.count()}),
            "text": gettext('At or below minimum stock'),
            "url": reverse("low_stock_alert"),
        })
    if receivable["count"]:
        alerts.append({
            "tone": "info", "icon": "fa-hand-holding-dollar",
            "title": (ngettext('%(count)s customer with dues', '%(count)s customers with dues', receivable['count']) % {'count': receivable['count']}),
            "text": (gettext('₹%(total)s to collect') % {'total': receivable['total']}),
            "url": reverse("customer_list") + "?dues=1",
        })

    # ---------------------------------------------------------- admin: shops table
    shop_rows = []
    if is_admin and shop is None:
        for retailer in Retailer.objects.order_by("shop_name"):
            shop_sales = Sale.objects.filter(retailer=retailer)
            shop_purchases = Purchase.objects.filter(retailer=retailer)
            shop_products = Product.objects.filter(retailer=retailer, is_active=True)
            shop_rows.append({
                "retailer": retailer,
                "sales_month": _sum(
                    shop_sales.filter(invoice_date__gte=month_start, invoice_date__lte=today), "grand_total"
                ),
                "purchases_month": _sum(
                    shop_purchases.filter(bill_date__gte=month_start, bill_date__lte=today), "grand_total"
                ),
                "receivable": _receivable(Customer.objects.filter(retailer=retailer))["total"],
                "payable": _sum(shop_purchases.filter(due_amount__gt=0), "due_amount"),
                "low_stock": shop_products.filter(current_stock__lte=F("minimum_stock")).count(),
            })

    # ---------------------------------------------------------- greeting
    hour = timezone.localtime().hour
    greeting = gettext("Good morning") if hour < 12 else gettext("Good afternoon") if hour < 17 else gettext("Good evening")

    context = {
        "is_admin": is_admin,
        "shop": shop,
        "selected_retailer": selected_retailer,
        "retailers": Retailer.objects.order_by("shop_name") if is_admin else Retailer.objects.none(),
        "greeting": greeting,
        "today": today,
        "month_start": month_start,

        # Sales
        "sales_today_total": sales_today_total,
        "sales_today_count": sales_today.count(),
        "collected_today": collected_today,
        "sales_month_total": sales_month_total,
        "sales_month_count": sales_month.count(),
        "sales_change": _percent_change(sales_month_total, sales_last_month_total),
        "chart": _sales_chart(sales, today),

        # Purchases / payable
        "purchases_month_total": _sum(purchases_month, "grand_total"),
        "purchases_month_count": purchases_month.count(),
        "payable_total": payable_total,
        "open_bill_count": open_bills.count(),
        "overdue_total": overdue_total,
        "overdue_count": overdue_bills.count(),

        # Backwards-compatible purchase totals
        "purchase_bills": purchases.count(),
        "purchase_total": _sum(purchases, "grand_total"),
        "purchase_paid": _sum(purchases, "paid_amount"),
        "purchase_due": payable_total,

        # Stock
        "product_count": active_products.count(),
        "low_stock_count": low_stock.count(),
        "out_of_stock_count": out_of_stock.count(),
        "stock_value": stock_value,
        # None when no shop in view tracks expiry (card hidden).
        "expiry": expiry,

        # Customers / suppliers / retailers
        "customer_count": customers.count(),
        "receivable": receivable,
        "supplier_count": suppliers.filter(is_active=True).count(),
        "retailer_count": Retailer.objects.filter(is_active=True).count() if is_admin else 0,

        # Lists
        "recent_sales": sales.select_related("customer", "retailer").order_by("-invoice_date", "-id")[:6],
        "recent_purchases": purchases.select_related("supplier", "retailer").order_by("-bill_date", "-id")[:6],
        "bills_to_pay": open_bills.select_related("supplier", "retailer").order_by(
            F("due_date").asc(nulls_last=True), "bill_date"
        )[:5],
        "low_stock_products": active_products.filter(current_stock__lte=F("minimum_stock"))
            .select_related("retailer", "unit").order_by("current_stock", "product_name")[:5],
        "top_products": top_products,
        "alerts": alerts,
        "shop_rows": shop_rows,
    }

    return render(request, "dashboard.html", context)
