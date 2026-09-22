
from django.urls import path
from . import views

urlpatterns = [
   
    path('', views.dashboard, name="dashboard"),
    
    #User Authentication URLs
    path('user-login/', views._login, name="user_login"),
    path('retailer-register/', views.retailer_register, name="retailer_register"),
    path('logout/', views.user_logout, name='user_logout'),

    #Products URLs
    path("product-list/", views.product_list, name="product_list"),
    path("add-product/", views.add_product, name="add_product"),
    # path("product-mapping/", views.product_mapping, name="product_mapping"),
    path("products/update/", views.update_product, name="update_product"),
    path("products/delete/<int:product_id>/", views.delete_product, name="delete_product"),
    path('low-stock/', views.low_stock_alert, name='low_stock_alert'),

    #Order URLs
    path('add-order/', views.add_order, name='add_new_order'),
    path('purchase-product-list/', views.purchase_list, name='purchase_product_list'),
    path("purchases-details/<int:purchase_id>/", views.purchase_detail, name="purchase_detail"),

    #Supplier URLs
    path('add-supplier/', views.add_supplier, name='add_new_supplier'),

    # Sales Module 
    path('sale-create/', views.sales_create, name='sale_create'),
    # path('sale-create1/', views.sales_create1, name='sale_create1'),
    path("sales-customer-create/", views.create_customer_ajax, name="create_customer_ajax"),
    path("sales-product/<int:product_id>/", views.sale_product_data, name="sale_product_data"),

]
