from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Order
from .emails import send_order_status_email
import logging

logger = logging.getLogger(__name__)

@receiver(pre_save, sender=Order)
def capture_previous_status(sender, instance, **kwargs):
    """Capture the status before saving to detect changes."""
    if instance.pk:
        try:
            instance._previous_status = Order.objects.get(pk=instance.pk).status
        except Order.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None

@receiver(post_save, sender=Order)
def order_status_changed(sender, instance, created, **kwargs):
    """Send email when specific status transitions occur."""
    
    current_status = instance.status
    previous_status = getattr(instance, '_previous_status', None)
    
    # Target statuses for email notification
    target_statuses = ['placed', 'confirmed', 'shipped', 'delivered', 'cancelled']
    
    # 1. Newly created order with target status (especially COD 'placed')
    if created and current_status in target_statuses:
        send_order_status_email(instance, current_status)
    
    # 2. Status has changed to a target status
    elif not created and current_status != previous_status and current_status in target_statuses:
        # Note: We send 'confirmed' if it's the new status, even if it was 'pending' before
        send_order_status_email(instance, current_status)
