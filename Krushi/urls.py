from django.urls import path
from django.views.generic.base import RedirectView
from . import views, views_chat
from .views_chat import chat_api

urlpatterns = [
    path('', views.home, name='home'),
    path('health/', views.health_check, name='health_check'),
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.ico')),
    path('shop/', views.shop, name='shop'),
    
    # Sell Products
    path('sell-product/', views.sell_product, name='sell_product'),
    path('my-products/', views.my_products, name='my_products'),
    path('edit-product/<int:product_id>/', views.edit_product, name='edit_product'),
    path('delete-product/<int:product_id>/', views.delete_product, name='delete_product'),
    path('shop/sell-fertilizer/', views.create_fertilizer_listing, name='create_fertilizer_listing'),
    path('disease/', views.disease, name='disease'),
    path('soil-analysis/', views.soil_analysis, name='soil_analysis'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('rating/', views.rating, name='rating'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.user_profile, name='user_profile'),
    
    # Registration Email Verification
    path('verify-registration-otp/', views.verify_registration_otp, name='verify_registration_otp'),
    path('resend-registration-otp/', views.resend_registration_otp, name='resend_registration_otp'),
    
    # Password Reset
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('reset-password/', views.reset_password, name='reset_password'),
    path('resend-otp/', views.resend_otp, name='resend_otp'),
    path('govsites/', views.govsites, name ='govsites'),
    path('api/weather/', views.weather_api, name='weather_api'),
    
    # Cart and Shopping
    path('cart/', views.view_cart, name='view_cart'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('update-cart/<int:item_id>/', views.update_cart, name='update_cart'),
    path('remove-from-cart/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('payment/verify/', views.payment_verify, name='payment_verify'),
    path('payment/cancelled/', views.payment_cancelled, name='payment_cancelled'),
    path('payment/webhook/', views.razorpay_webhook, name='razorpay_webhook'),
    
    # Orders
    path('order-confirmation/<int:order_id>/', views.order_confirmation, name='order_confirmation'),
    path('my-orders/', views.my_orders, name='my_orders'),
    path('cancel-order/<int:order_id>/', views.cancel_order, name='cancel_order'),
    
    # Reviews
    path('add-review/<int:product_id>/', views.add_review, name='add_review'),
    
    # API endpoints
    path('api/analyze-disease/', views.analyze_disease, name='analyze_disease'),
    path('api/analyze-soil/', views.analyze_soil, name='analyze_soil'),
    path('api/newsletter/subscribe/', views.newsletter_subscribe, name='newsletter_subscribe'),
    path('api/chat/', chat_api, name='chat_api'),
    
    # Crop Planning API
    path('api/planning/generate/', views.generate_crop_plan_api, name='generate_crop_plan_api'),
    path('api/planning/crops/', views.get_available_crops_api, name='get_available_crops_api'),
    path('crop-planning/', views.crop_planning_page, name='crop_planning'),

    # Legal Pages
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms-conditions/', views.terms_conditions, name='terms_conditions'),
    path('disclaimer/', views.disclaimer, name='disclaimer'),
]
