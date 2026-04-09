from django.urls import path
from . import admin_views

urlpatterns = [
    path('login/', admin_views.admin_login, name='admin_login'),
    path('', admin_views.dashboard, name='admin_dashboard'),
    
    # User Management
    path('users/', admin_views.users_list, name='admin_users'),
    path('users/<int:user_id>/toggle/', admin_views.user_toggle_active, name='admin_user_toggle'),
    path('users/<int:user_id>/delete/', admin_views.user_delete, name='admin_user_delete'),
    
    # Category Management
    path('categories/', admin_views.categories_list, name='admin_categories'),
    path('categories/new/', admin_views.category_create, name='admin_category_create'),
    path('categories/<int:category_id>/edit/', admin_views.category_edit, name='admin_category_edit'),
    path('categories/<int:category_id>/delete/', admin_views.category_delete, name='admin_category_delete'),
    
    # Product Management
    path('products/', admin_views.products_list, name='admin_products'),
    path('products/new/', admin_views.product_create, name='admin_product_create'),
    path('products/<int:product_id>/edit/', admin_views.product_edit, name='admin_product_edit'),
    path('products/<int:product_id>/delete/', admin_views.product_delete, name='admin_product_delete'),
    path('products/<int:product_id>/approve/', admin_views.product_approve, name='admin_product_approve'),
    
    # Order Management
    path('orders/', admin_views.orders_list, name='admin_orders'),
    path('orders/<int:order_id>/update/', admin_views.order_update_status, name='admin_order_update'),
    path('orders/<int:order_id>/delete/', admin_views.order_delete, name='admin_order_delete'),
    
    # Fertilizer Listing Management
    path('fertilizers/', admin_views.fertilizers_list, name='admin_fertilizers'),
    path('fertilizers/<int:fertilizer_id>/toggle/', admin_views.fertilizer_toggle_active, name='admin_fertilizer_toggle'),
    path('fertilizers/<int:fertilizer_id>/delete/', admin_views.fertilizer_delete, name='admin_fertilizer_delete'),

    # Feedback & Reviews Management
    path('reviews/', admin_views.reviews_list, name='admin_reviews'),
    path('reviews/<int:review_id>/toggle/', admin_views.review_toggle_active, name='admin_review_toggle'),
    path('reviews/<int:review_id>/delete/', admin_views.review_delete, name='admin_review_delete'),
    
    path('feedbacks/', admin_views.feedbacks_list, name='admin_feedbacks'),
    path('feedbacks/<int:feedback_id>/toggle/', admin_views.feedback_toggle_active, name='admin_feedback_toggle'),
    path('feedbacks/<int:feedback_id>/delete/', admin_views.feedback_delete, name='admin_feedback_delete'),
    
    # Contact Messages & Newsletter
    path('contact-messages/', admin_views.contact_messages_list, name='admin_contact_messages'),
    path('contact-messages/<int:message_id>/delete/', admin_views.contact_message_delete, name='admin_contact_message_delete'),
    
    path('newsletter/', admin_views.newsletter_list, name='admin_newsletter'),
    path('newsletter/<int:subscriber_id>/delete/', admin_views.newsletter_delete, name='admin_newsletter_delete'),

    path('settings/', admin_views.general_settings, name='admin_settings'),
]
