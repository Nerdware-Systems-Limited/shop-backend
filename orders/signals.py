from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Order, OrderStatusHistory
from .notifications import OrderNotifications
import logging

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Order)
def order_pre_save(sender, instance, **kwargs):
    """Handle order pre-save operations"""
    if instance.pk:
        old_instance = Order.objects.get(pk=instance.pk)
        
        # Check if status changed
        if old_instance.status != instance.status:
            # This will be handled in post_save to ensure instance is saved
            pass


@receiver(post_save, sender=Order)
def order_post_save(sender, instance, created, **kwargs):
    """Handle order post-save operations"""
    if created:
        # ✅ CHANGE THIS - use task instead
        from .tasks import send_order_confirmation_email
        send_order_confirmation_email.delay(instance.id)
        
        # Create initial status history
        OrderStatusHistory.objects.create(
            order=instance,
            old_status='',
            new_status='pending',
            changed_by=None,
            notes='Order created'
        )
        
        logger.info(f"New order created: {instance.order_number}")
    
    else:
        # Check for status changes
        try:
            old_instance = Order.objects.get(pk=instance.pk)
            
            if old_instance.status != instance.status:
                # ✅ ADD THIS - use centralized task
                from .tasks import update_order_status_task
                update_order_status_task.delay(
                    instance.id,
                    old_instance.status,
                    instance.status
                )
                
                # Create status history
                OrderStatusHistory.objects.create(
                    order=instance,
                    old_status=old_instance.status,
                    new_status=instance.status,
                    changed_by=None,
                    notes='Status updated'
                )
                
                logger.info(
                    f"Order {instance.order_number} status changed "
                    f"from {old_instance.status} to {instance.status}"
                )
        
        except Order.DoesNotExist:
            pass


@receiver(post_save, sender=OrderStatusHistory)
def status_history_post_save(sender, instance, created, **kwargs):
    """Handle status history post-save"""
    if created and instance.changed_by:
        # Log user-initiated status changes
        logger.info(
            f"User {instance.changed_by} changed order {instance.order.order_number} "
            f"from {instance.old_status} to {instance.new_status}"
        )