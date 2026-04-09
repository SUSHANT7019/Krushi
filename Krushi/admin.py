from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django import forms
from .models import (
    User, Category, Product, Review, Feedback, Cart, CartItem, 
    Order, OrderItem, ContactMessage, FertilizerListing, 
    NewsletterSubscription, PasswordResetOTP, EmailOTPVerification,
    PaymentTransaction, Lab,
)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'phone', 'is_farmer', 'is_active', 'date_joined']
    list_filter = ['is_farmer', 'is_active', 'date_joined']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    ordering = ['-date_joined']
    
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {'fields': ('phone', 'address', 'is_farmer')}),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Additional Info', {'fields': ('phone', 'address', 'is_farmer')}),
    )

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'icon', 'created_at']
    search_fields = ['name']
    ordering = ['name']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'stock_quantity', 'rating', 'total_reviews', 'is_active', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    ordering = ['-created_at']
    list_editable = ['price', 'stock_quantity', 'is_active']

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'rating', 'is_active', 'created_at']
    list_filter = ['rating', 'is_active', 'created_at']
    search_fields = ['product__name', 'user__username']
    ordering = ['-created_at']

@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'rating', 'is_active', 'created_at']
    list_filter = ['rating', 'is_active', 'created_at']
    search_fields = ['name', 'comment']
    ordering = ['-created_at']

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'phone', 'subject', 'created_at']
    list_filter = ['subject', 'created_at']
    search_fields = ['name', 'email', 'phone', 'message']
    ordering = ['-created_at']

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['user', 'item_count', 'total_amount', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username']
    ordering = ['-created_at']

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ['cart', 'product', 'quantity', 'total_price', 'added_at']
    list_filter = ['added_at']
    search_fields = ['cart__user__username', 'product__name']
    ordering = ['-added_at']


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product', 'quantity', 'price', 'total_price']


class PaymentTransactionInline(admin.TabularInline):
    model = PaymentTransaction
    extra = 0
    readonly_fields = [
        'event', 'razorpay_order_id', 'razorpay_payment_id',
        'amount_paise', 'currency', 'status', 'created_at',
    ]
    can_delete = False


class OrderAdminForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        # Create a temporary instance to test clean() without saving
        instance = getattr(self, 'instance', None)
        if instance and instance.pk:
            # We want to use the cleaned data to test the transition
            # but keep the current DB state in the instance until save
            original_status = instance.status
            try:
                # Temporarily set the new status to run validation
                instance.status = cleaned_data.get('status', instance.status)
                instance.clean()
            except ValidationError as e:
                # Revert to original status to keep form consistent if it fails
                instance.status = original_status
                raise forms.ValidationError(e.messages)
            finally:
                instance.status = original_status
        return cleaned_data

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    list_display = [
        'order_number', 'user', 'payment_method', 'status', 'payment_status',
        'total_amount', 'razorpay_order_id', 'paid_at', 'created_at',
    ]
    list_filter = ['payment_method', 'status', 'payment_status', 'created_at']
    search_fields = ['order_number', 'user__username', 'razorpay_order_id', 'razorpay_payment_id']
    ordering = ['-created_at']
    list_editable = ['status', 'payment_status']
    readonly_fields = [
        'order_number', 'razorpay_order_id', 'razorpay_payment_id',
        'razorpay_signature', 'paid_at', 'payment_method',
    ]
    inlines = [OrderItemInline, PaymentTransactionInline]

    fieldsets = (
        ('Order Info', {
            'fields': ('order_number', 'user', 'status', 'total_amount', 'currency'),
        }),
        ('Payment', {
            'fields': (
                'payment_method', 'payment_status', 'paid_at',
            ),
        }),
        ('Razorpay Details', {
            'fields': (
                'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature',
            ),
            'classes': ('collapse',),
            'description': 'Only applicable for online (Razorpay) payments.',
        }),
        ('Shipping', {
            'fields': ('full_name', 'shipping_address', 'city', 'district', 'state', 'pincode', 'phone', 'notes'),
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Override save_model to catch and display status flow validation errors gracefully."""
        try:
            # At this point, form.clean() has already run and called obj.clean()
            # If it passed there, it's safe to save.
            super().save_model(request, obj, form, change)
        except ValidationError as e:
            from django.contrib import messages
            for error in e.messages:
                messages.error(request, f"Status Error: {error}")
        except Exception as e:
            raise e

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ['order', 'product', 'quantity', 'price', 'total_price']
    list_filter = ['order__status']
    search_fields = ['order__order_number', 'product__name']
    ordering = ['-order__created_at']

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'razorpay_payment_id', 'razorpay_order_id', 'event',
        'amount_paise', 'currency', 'status', 'created_at',
    ]
    list_filter = ['event', 'status', 'created_at']
    search_fields = ['razorpay_order_id', 'razorpay_payment_id', 'order__order_number']
    ordering = ['-created_at']
    readonly_fields = [
        'order', 'razorpay_order_id', 'razorpay_payment_id',
        'razorpay_signature', 'event', 'amount_paise', 'currency',
        'status', 'raw_response', 'created_at',
    ]

@admin.register(FertilizerListing)
class FertilizerListingAdmin(admin.ModelAdmin):
    list_display = ['fertilizer_name', 'seller', 'quantity', 'unit', 'price', 'is_active', 'created_at']
    list_filter = ['unit', 'is_active', 'created_at']
    search_fields = ['fertilizer_name', 'brand', 'seller__username']
    ordering = ['-created_at']
    list_editable = ['is_active', 'price', 'quantity']

@admin.register(NewsletterSubscription)
class NewsletterSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['email', 'created_at']
    search_fields = ['email']
    ordering = ['-created_at']

@admin.register(PasswordResetOTP)
class PasswordResetOTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'otp', 'expires_at', 'is_used', 'created_at']
    list_filter = ['is_used', 'created_at']
    search_fields = ['user__username', 'otp']

@admin.register(EmailOTPVerification)
class EmailOTPVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'otp_hash', 'attempts', 'expires_at', 'is_verified', 'created_at']
    list_filter = ['is_verified', 'created_at']
    search_fields = ['user__email']

@admin.register(Lab)
class LabAdmin(admin.ModelAdmin):
    list_display = ['name', 'latitude', 'longitude', 'source', 'created_at']
    list_filter = ['source', 'created_at']
    search_fields = ['name', 'address', 'phone']
    ordering = ['-created_at']

