from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator
from .models import User, Product, Order, Category, Review, FertilizerListing, Feedback, ContactMessage, NewsletterSubscription
from .forms import AdminProductForm

# RBAC helper
def is_admin(user):
    return user.is_authenticated and (user.is_superuser or getattr(user, 'role', '') == 'Admin')

admin_required = user_passes_test(is_admin, login_url='/admin/login/')

def admin_login(request):
    if request.user.is_authenticated and is_admin(request.user):
        return redirect('admin_dashboard')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
            
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if is_admin(user):
                login(request, user)
                return redirect(request.GET.get('next', 'admin_dashboard'))
            else:
                messages.error(request, "You do not have permission to access the admin portal.")
        else:
            messages.error(request, "Invalid username or password.")
            
    return render(request, 'admin/login.html')

@admin_required
def dashboard(request):
    # Analytics data
    total_users = User.objects.count()
    total_products = Product.objects.count()
    total_orders = Order.objects.count()
    total_revenue = Order.objects.filter(status='delivered').aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_fertilizers = FertilizerListing.objects.count()
    total_feedbacks = Feedback.objects.count()
    total_subscribers = NewsletterSubscription.objects.count()

    recent_orders = Order.objects.order_by('-created_at')[:5]
    recent_users = User.objects.order_by('-created_at')[:5]

    context = {
        'total_users': total_users,
        'total_products': total_products,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'total_fertilizers': total_fertilizers,
        'total_feedbacks': total_feedbacks,
        'total_subscribers': total_subscribers,
        'recent_orders': recent_orders,
        'recent_users': recent_users,
        'now': timezone.now(),
    }
    return render(request, 'admin/dashboard.html', context)

@admin_required
def users_list(request):
    search_query = request.GET.get('search', '')
    if search_query:
        users = User.objects.filter(username__icontains=search_query) | User.objects.filter(email__icontains=search_query)
    else:
        users = User.objects.all().order_by('-date_joined')
    
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {'users': page_obj, 'search_query': search_query, 'page_obj': page_obj}
    return render(request, 'admin/users.html', context)

@admin_required
def user_toggle_active(request, user_id):
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        if user.is_superuser and user == request.user:
            messages.error(request, "You cannot block yourself.")
        else:
            user.is_active = not user.is_active
            user.save()
            status = 'unblocked' if user.is_active else 'blocked'
            messages.success(request, f"User {user.username} successfully {status}.")
    return redirect('admin_users')

@admin_required
def user_delete(request, user_id):
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        if user.is_superuser and user == request.user:
            messages.error(request, "You cannot delete yourself.")
        else:
            username = user.username
            user.delete()
            messages.success(request, f"User {username} deleted successfully.")
    return redirect('admin_users')

@admin_required
def products_list(request):
    search_query = request.GET.get('search', '')
    if search_query:
        products = Product.objects.filter(name__icontains=search_query) | Product.objects.filter(category__name__icontains=search_query)
    else:
        products = Product.objects.all().order_by('-created_at')
        
    paginator = Paginator(products, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
        
    context = {'products': page_obj, 'search_query': search_query, 'page_obj': page_obj}
    return render(request, 'admin/products.html', context)

@admin_required
def product_delete(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        product.delete()
        messages.success(request, f"Product {product.name} deleted successfully.")
    return redirect('admin_products')

@admin_required
def product_approve(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        product.is_approved = True
        product.save()
        
        # Send approval email to farmer if they exist
        if product.seller and product.seller.email:
            try:
                from django.core.mail import send_mail
                from django.template.loader import render_to_string
                from django.utils.html import strip_tags
                from django.contrib.sites.shortcuts import get_current_site
                from django.conf import settings
                
                current_site = get_current_site(request)
                subject = 'Your Product is Approved and Live! - Krushi'
                html_message = render_to_string('emails/product_approved.html', {
                    'user': product.seller,
                    'product': product,
                    'site_url': f"http://{current_site.domain}"
                })
                plain_message = strip_tags(html_message)
                
                send_mail(
                    subject,
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [product.seller.email],
                    html_message=html_message,
                    fail_silently=True,
                )
            except Exception as e:
                # We log this but don't stop the approval flow
                import logging
                logging.getLogger(__name__).error(f"Error sending product approval email: {str(e)}")

        messages.success(request, f"Product {product.name} approved and is now live on the shop. Approval email sent to {product.seller.username if product.seller else 'N/A'}.")
    return redirect('admin_products')

@admin_required
def product_create(request):
    if request.method == 'POST':
        form = AdminProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            messages.success(request, f"Product {product.name} created successfully.")
            return redirect('admin_products')
        else:
            messages.error(request, "Failed to create product. Please check the form for validation errors.")
    else:
        form = AdminProductForm()
    return render(request, 'admin/product_form.html', {'form': form, 'title': 'Add New Product'})

@admin_required
def product_edit(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        form = AdminProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            product = form.save()
            messages.success(request, f"Product {product.name} updated successfully.")
            return redirect('admin_products')
        else:
            messages.error(request, "Failed to update product. Please check the form for validation errors.")
    else:
        form = AdminProductForm(instance=product)
    return render(request, 'admin/product_form.html', {'form': form, 'product': product, 'title': 'Edit Product'})

@admin_required
def orders_list(request):
    search_query = request.GET.get('search', '')
    if search_query:
        orders = Order.objects.filter(order_number__icontains=search_query)
    else:
        orders = Order.objects.all().order_by('-created_at')
        
    paginator = Paginator(orders, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
        
    context = {'orders': page_obj, 'search_query': search_query, 'page_obj': page_obj}
    return render(request, 'admin/orders.html', context)

from django.core.exceptions import ValidationError

@admin_required
def order_update_status(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        new_status = request.POST.get('status')
        if new_status in dict(Order.STATUS_CHOICES):
            try:
                order.status = new_status
                # Model save() calls clean(), which checks the forward-only flow
                order.save()
                messages.success(request, f"Order {order.order_number} status updated to {new_status.capitalize()}.")
            except ValidationError as e:
                for error in e.messages:
                    messages.error(request, f"Cannot update status: {error}")
            except Exception as e:
                messages.error(request, f"System Error: {str(e)}")
        else:
            messages.error(request, "Invalid status selected.")
    return redirect('admin_orders')

@admin_required
def order_delete(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        order_num = order.order_number
        order.delete()
        messages.success(request, f"Order {order_num} deleted successfully.")
    return redirect('admin_orders')

@admin_required
def fertilizers_list(request):
    search_query = request.GET.get('search', '')
    if search_query:
        fertilizers = FertilizerListing.objects.filter(fertilizer_name__icontains=search_query) | FertilizerListing.objects.filter(brand__icontains=search_query)
    else:
        fertilizers = FertilizerListing.objects.all().order_by('-created_at')
        
    paginator = Paginator(fertilizers, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
        
    context = {'fertilizers': page_obj, 'search_query': search_query, 'page_obj': page_obj}
    return render(request, 'admin/fertilizers.html', context)

@admin_required
def fertilizer_toggle_active(request, fertilizer_id):
    if request.method == 'POST':
        fertilizer = get_object_or_404(FertilizerListing, id=fertilizer_id)
        fertilizer.is_active = not fertilizer.is_active
        fertilizer.save()
        status = 'activated' if fertilizer.is_active else 'deactivated'
        messages.success(request, f"Fertilizer listing {fertilizer.fertilizer_name} {status}.")
    return redirect('admin_fertilizers')

@admin_required
def fertilizer_delete(request, fertilizer_id):
    if request.method == 'POST':
        fertilizer = get_object_or_404(FertilizerListing, id=fertilizer_id)
        name = fertilizer.fertilizer_name
        fertilizer.delete()
        messages.success(request, f"Fertilizer listing {name} deleted successfully.")
    return redirect('admin_fertilizers')

@admin_required
def reviews_list(request):
    search_query = request.GET.get('search', '')
    if search_query:
        reviews = Review.objects.filter(product__name__icontains=search_query) | Review.objects.filter(user__username__icontains=search_query)
    else:
        reviews = Review.objects.all().order_by('-created_at')
        
    paginator = Paginator(reviews, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
        
    context = {'reviews': page_obj, 'search_query': search_query, 'page_obj': page_obj}
    return render(request, 'admin/reviews.html', context)

@admin_required
def review_toggle_active(request, review_id):
    if request.method == 'POST':
        review = get_object_or_404(Review, id=review_id)
        review.is_active = not review.is_active
        review.save()
        status = 'activated' if review.is_active else 'deactivated'
        messages.success(request, f"Review for {review.product.name} {status}.")
    return redirect('admin_reviews')

@admin_required
def review_delete(request, review_id):
    if request.method == 'POST':
        review = get_object_or_404(Review, id=review_id)
        review.delete()
        messages.success(request, f"Review deleted successfully.")
    return redirect('admin_reviews')

@admin_required
def feedbacks_list(request):
    feedbacks = Feedback.objects.all().order_by('-created_at')
    paginator = Paginator(feedbacks, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {'feedbacks': page_obj, 'page_obj': page_obj}
    return render(request, 'admin/feedbacks.html', context)

@admin_required
def feedback_toggle_active(request, feedback_id):
    if request.method == 'POST':
        feedback = get_object_or_404(Feedback, id=feedback_id)
        feedback.is_active = not feedback.is_active
        feedback.save()
        status = 'activated' if feedback.is_active else 'deactivated'
        messages.success(request, f"Feedback {status}.")
    return redirect('admin_feedbacks')

@admin_required
def feedback_delete(request, feedback_id):
    if request.method == 'POST':
        feedback = get_object_or_404(Feedback, id=feedback_id)
        feedback.delete()
        messages.success(request, f"Feedback deleted successfully.")
    return redirect('admin_feedbacks')

@admin_required
def contact_messages_list(request):
    messages_list = ContactMessage.objects.all().order_by('-created_at')
    paginator = Paginator(messages_list, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {'contact_messages': page_obj, 'page_obj': page_obj}
    return render(request, 'admin/contact_messages.html', context)

@admin_required
def contact_message_delete(request, message_id):
    if request.method == 'POST':
        msg = get_object_or_404(ContactMessage, id=message_id)
        msg.delete()
        messages.success(request, f"Contact message deleted successfully.")
    return redirect('admin_contact_messages')

@admin_required
def newsletter_list(request):
    subscribers = NewsletterSubscription.objects.all().order_by('-created_at')
    paginator = Paginator(subscribers, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {'subscribers': page_obj, 'page_obj': page_obj}
    return render(request, 'admin/newsletter.html', context)

@admin_required
def newsletter_delete(request, subscriber_id):
    if request.method == 'POST':
        sub = get_object_or_404(NewsletterSubscription, id=subscriber_id)
        email = sub.email
        sub.delete()
        messages.success(request, f"Subscriber {email} removed successfully.")
    return redirect('admin_newsletter')

@admin_required
def categories_list(request):
    categories = Category.objects.all().order_by('name')
    paginator = Paginator(categories, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {'categories': page_obj, 'page_obj': page_obj}
    return render(request, 'admin/categories.html', context)

@admin_required
def category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        icon = request.POST.get('icon', 'fas fa-tag')
        if name:
            Category.objects.create(name=name, description=description, icon=icon)
            messages.success(request, f"Category {name} created successfully.")
        else:
            messages.error(request, "Name is required.")
    return redirect('admin_categories')

@admin_required
def category_edit(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'POST':
        category.name = request.POST.get('name')
        category.description = request.POST.get('description', '')
        category.icon = request.POST.get('icon', 'fas fa-tag')
        if category.name:
            category.save()
            messages.success(request, f"Category {category.name} updated successfully.")
            return redirect('admin_categories')
        else:
            messages.error(request, "Name is required.")
    return render(request, 'admin/category_form.html', {'category': category})

@admin_required
def category_delete(request, category_id):
    if request.method == 'POST':
        category = get_object_or_404(Category, id=category_id)
        category.delete()
        messages.success(request, f"Category {category.name} deleted successfully.")
    return redirect('admin_categories')

@admin_required
def general_settings(request):
    # Placeholder for settings until models are added
    return render(request, 'admin/settings.html')
