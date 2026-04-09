from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

STATUS_CONFIG = {
    'placed': {
        'title': 'Order Placed',
        'message': 'Your order has been placed successfully! We have received your order and our team is now processing it.',
        'color': '#3b82f6',  # Blue
    },
    'confirmed': {
        'title': 'Order Confirmed',
        'message': 'Great news! Your order has been confirmed and we are preparing your items for shipment.',
        'color': '#8b5cf6',  # Purple
    },
    'shipped': {
        'title': 'Order Shipped',
        'message': 'Your order is on its way! We have handed over your package to our delivery partner.',
        'color': '#f59e0b',  # Amber
    },
    'delivered': {
        'title': 'Order Delivered',
        'message': 'Your order has been delivered successfully. We hope you are satisfied with your purchase!',
        'color': '#10b981',  # Green
    },
    'cancelled': {
        'title': 'Order Cancelled',
        'message': 'Your order has been cancelled. If you did not request this, please contact our support team immediately.',
        'color': '#ef4444',  # Red
    },
}

def send_order_status_email(order, status):
    """
    Send an email notification to the user about their order status change.
    
    Args:
        order: The Order model instance
        status: The target status string (e.g., 'placed', 'confirmed', etc.)
    """
    config = STATUS_CONFIG.get(status.lower())
    if not config:
        logger.warning(f"No email configuration found for status: {status}")
        return False

    # Basic setup
    subject = f"{config['title']} - Order #{order.order_number} - Krushi"
    from_email = settings.DEFAULT_FROM_EMAIL
    to_email = order.user.email
    
    # Context for template
    try:
        from django.contrib.sites.models import Site
        site_domain = Site.objects.get_current().domain
        site_url = f"http://{site_domain}" if '127.0.0.1' in site_domain or 'localhost' in site_domain else f"https://{site_domain}"
    except Exception:
        site_url = 'http://127.0.0.1:8000'
    
    context = {
        'user': order.user,
        'order': order,
        'status_title': config['title'],
        'status_message': config['message'],
        'status_color': config['color'],
        'site_url': site_url,
    }

    try:
        # Render HTML message
        html_message = render_to_string('emails/order_status_update.html', context)
        # Create plain text version for email clients that don't support HTML
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject,
            plain_message,
            from_email,
            [to_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Order status email ('{status}') sent to {to_email} for order #{order.order_number}")
        return True
    except Exception as e:
        logger.error(f"Failed to send order status email to {to_email}: {e}")
        return False
