'''
Routing [URL Creation] + Parameterized Routing
Through Url -> 3 Types -> Str, slug, int
'''

from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name="home_page"),
    path('about/', views.about, name="about_page"),
    path('service/', views.service, name="service_page"),
    path('contact/', views.contact, name="contact_page"),
    path('create/employee/', views.create_employee, name="create_employee"),
    path('employees/', views.get_all_employees, name="get_all_employees"),
    path('delete/employee/<int:id>', views.delete_employee, name="delete_employee"),
    path('update/employee/<int:id>/', views.update_employee, name='update_employee'),
    # Authentication routes
    path('register', views.user_register, name='user_register'),
    path('login', views.user_login, name='user_login'),
    path('logout', views.user_logout, name='user_logout'),
    path("welcome/email", views.welcome_email, name='welcome_email'),
    # Storefront
    path('shop/', views.shop, name='shop_page'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('favorites/', views.favorites, name='favorites'),
    path('favorite/add/<int:product_id>/', views.add_favorite, name='add_favorite'),
    path('favorite/remove/<int:fav_id>/', views.remove_favorite, name='remove_favorite'),
    # Cart
    path('cart/', views.cart, name='cart'),
    path('cart/add/<int:product_id>/', views.add_cart, name='add_cart'),
    path('cart/update/<int:item_id>/', views.update_cart, name='update_cart'),
    path('cart/remove/<int:item_id>/', views.remove_cart, name='remove_cart'),
    path('cart/coupon/apply/', views.apply_coupon, name='apply_coupon'),
    path('cart/coupon/remove/', views.remove_coupon, name='remove_coupon'),
    # Local AI shopping assistant
    path('assistant/chat/', views.ai_chat, name='ai_chat'),
    path('assistant/cart/add/<int:product_id>/', views.ai_cart_add, name='ai_cart_add'),
    # Checkout and customer orders
    path('checkout/', views.checkout, name='checkout'),
    path('orders/', views.order_list, name='order_list'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path(
        'orders/<str:order_number>/success/',
        views.order_success,
        name='order_success',
    ),
    path('orders/<str:order_number>/pay/', views.order_payment, name='order_payment'),
    path(
        'orders/<str:order_number>/verify-payment/',
        views.verify_payment,
        name='verify_payment',
    ),
]
