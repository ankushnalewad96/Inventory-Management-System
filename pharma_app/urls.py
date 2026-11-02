
from django.urls import path
from . import (
    account_views,
    dashboard_views,
    pharmacy_views,
    quotation_views,
    return_views,
    shop_service_views,
    supplier_product_views,
    views,
)

urlpatterns = [
   
    path('', dashboard_views.dashboard, name="dashboard"),
    
    #User Authentication URLs
    path('user-login/', views._login, name="user_login"),
    path('retailer-register/', views.retailer_register, name="retailer_register"),
    path('logout/', views.user_logout, name='user_logout'),

    #Products URLs
    path("product-list/", views.product_list, name="product_list"),
    path("add-product/", views.add_product, name="add_product"),
    path("products/update/", views.update_product, name="update_product"),
    path("products/delete/<int:product_id>/", views.delete_product, name="delete_product"),
    path('low-stock/', views.low_stock_alert, name='low_stock_alert'),

    #Order URLs
    path('add-order/', views.add_order, name='add_new_order'),
    path('purchase-product-list/', views.purchase_list, name='purchase_product_list'),
    path("purchases-details/<int:purchase_id>/", views.purchase_detail, name="purchase_detail"),
    path("purchase-history/<int:product_id>/", views.purchase_history, name="purchase_history"),

    #Supplier URLs
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('add-supplier/', views.add_supplier, name='add_new_supplier'),
    path('suppliers/<int:supplier_id>/update/', views.supplier_update, name='supplier_update'),
    path('suppliers/<int:supplier_id>/delete/', views.supplier_delete, name='supplier_delete'),

    # Supplier products (which products are bought from which supplier)
    path("supplier-products/", supplier_product_views.supplier_product_list, name="supplier_product_list"),
    path("supplier-products/add/", supplier_product_views.supplier_product_add, name="supplier_product_add"),
    path("supplier-products/<int:link_id>/remove/", supplier_product_views.supplier_product_remove, name="supplier_product_remove"),

    # Sales Module
    path('sales/', views.sales_list, name='sales_list'),
    path('sales/<int:sale_id>/', views.sale_detail, name='sale_detail'),
    path('sales/<int:sale_id>/invoice/', views.sale_invoice, name='sale_invoice'),
    path('sale-create/', views.sales_create, name='sale_create'),
    path("sales-customer-create/", views.create_customer_ajax, name="create_customer_ajax"),
    path("sales-product/<int:product_id>/", views.sale_product_data, name="sale_product_data"),

    # Retailers (admin only)
    path("retailers/", account_views.retailer_list, name="retailer_list"),

    # Shop types on / off (admin only)
    path("shop-types/", shop_service_views.shop_type_services, name="shop_type_services"),
    path("shop-types/<str:shop_type>/switch/", shop_service_views.shop_type_service_toggle, name="shop_type_service_toggle"),

    # Purchase bill payments & printable bill
    path("purchases-details/<int:purchase_id>/payments/add/", account_views.purchase_add_payment, name="purchase_add_payment"),
    path("purchases-details/<int:purchase_id>/invoice/", account_views.purchase_invoice, name="purchase_invoice"),

    # Supplier accounts
    path("suppliers/<int:supplier_id>/account/", account_views.supplier_account, name="supplier_account"),
    path("suppliers/<int:supplier_id>/statement/", account_views.supplier_statement_print, name="supplier_statement"),
    path("suppliers/<int:supplier_id>/summary/", account_views.supplier_summary, name="supplier_summary"),

    # Customer accounts (khata / udhari)
    path("customers/", account_views.customer_list, name="customer_list"),
    path("customers/<int:customer_id>/", account_views.customer_account, name="customer_account"),
    path("customers/<int:customer_id>/receive-payment/", account_views.customer_receive_payment, name="customer_receive_payment"),
    path("customers/<int:customer_id>/statement/", account_views.customer_statement_print, name="customer_statement"),
    path("customers/<int:customer_id>/summary/", account_views.customer_summary, name="customer_summary"),
    path("customers/<int:customer_id>/price-level/", account_views.customer_set_price_level, name="customer_set_price_level"),
    path("customers/<int:customer_id>/state/", account_views.customer_set_state, name="customer_set_state"),

    # Pharmacy (pages are switched on by shop features)
    path("near-expiry/", pharmacy_views.near_expiry, name="near_expiry"),
    path("h1-register/", pharmacy_views.h1_register, name="h1_register"),

    # Returns: credit notes (sales) and debit notes (purchases)
    path("returns/", return_views.returns_list, name="returns_list"),
    path("sales/<int:sale_id>/return/", return_views.sale_return_create, name="sale_return_create"),
    path("purchases-details/<int:purchase_id>/return/", return_views.purchase_return_create, name="purchase_return_create"),
    path("returns/credit-note/<int:return_id>/", return_views.credit_note, name="credit_note"),
    path("returns/debit-note/<int:return_id>/", return_views.debit_note, name="debit_note"),

    # Quotations (features.quotations)
    path("quotations/", quotation_views.quotation_list, name="quotation_list"),
    path("quotations/new/", quotation_views.quotation_create, name="quotation_create"),
    path("quotations/<int:quotation_id>/", quotation_views.quotation_detail, name="quotation_detail"),
    path("quotations/<int:quotation_id>/print/", quotation_views.quotation_print, name="quotation_print"),
    path("quotations/<int:quotation_id>/cancel/", quotation_views.quotation_cancel, name="quotation_cancel"),
]
