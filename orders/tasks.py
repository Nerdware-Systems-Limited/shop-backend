"""
God-Level Celery Tasks for Orders App
Handles all asynchronous operations for order processing
"""
from celery import shared_task
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F
from datetime import timedelta
from decimal import Decimal
import logging

from .models import Order, OrderItem, OrderStatusHistory, OrderReturn
from .notifications import OrderNotifications
from customers.models import Customer

logger = logging.getLogger(__name__)


# ============================================================================
# EMAIL NOTIFICATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_order_confirmation_email(self, order_id):
    """
    Send order confirmation email asynchronously.
    Includes order details, items, and next steps.
    
    Args:
        order_id: ID of the order
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.select_related(
            'customer__user', 'billing_address', 'shipping_address'
        ).prefetch_related('items__product').get(id=order_id)
        
        # Send email using notifications system
        success = OrderNotifications.send_email_notification(
            order, 
            'order_confirmation'
        )
        
        if success:
            logger.info(f"✅ Order confirmation sent for {order.order_number}")
            return f"Confirmation email sent for order {order.order_number}"
        else:
            raise Exception("Failed to send email")
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send order confirmation: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_shipping_notification_email(self, order_id):
    """
    Send shipping notification with tracking information.
    
    Args:
        order_id: ID of the order
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.select_related(
            'customer__user', 'shipping_address'
        ).prefetch_related('items__product').get(id=order_id)
        
        if not order.tracking_number:
            logger.warning(f"No tracking number for order {order.order_number}")
            return "No tracking number available"
        
        # Send email
        success = OrderNotifications.send_email_notification(
            order, 
            'order_shipped'
        )
        
        if success:
            logger.info(f"✅ Shipping notification sent for {order.order_number}")
            
            # Send SMS if customer has phone
            if order.customer and order.customer.phone:
                sms_message = (
                    f"Your order {order.order_number} has shipped! "
                    f"Tracking: {order.tracking_number}"
                )
                OrderNotifications.send_sms_notification(order, sms_message)
            
            return f"Shipping notification sent for order {order.order_number}"
        else:
            raise Exception("Failed to send email")
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send shipping notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_delivery_notification_email(self, order_id):
    """
    Send delivery confirmation email.
    
    Args:
        order_id: ID of the order
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.select_related('customer__user').get(id=order_id)
        
        # Send email
        success = OrderNotifications.send_email_notification(
            order, 
            'order_delivered'
        )
        
        if success:
            logger.info(f"✅ Delivery notification sent for {order.order_number}")
            return f"Delivery notification sent for order {order.order_number}"
        else:
            raise Exception("Failed to send email")
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send delivery notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_cancellation_notification_email(self, order_id, reason=""):
    """
    Send order cancellation notification.
    
    Args:
        order_id: ID of the order
        reason: Cancellation reason
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.select_related('customer__user').get(id=order_id)
        
        # Add reason to context
        context = {'cancellation_reason': reason}
        
        # Send email
        success = OrderNotifications.send_email_notification(
            order, 
            'order_cancelled',
            context=context
        )
        
        if success:
            logger.info(f"✅ Cancellation notification sent for {order.order_number}")
            return f"Cancellation notification sent for order {order.order_number}"
        else:
            raise Exception("Failed to send email")
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send cancellation notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_failed_notification(self, order_id):
    """
    Send payment failed notification.
    
    Args:
        order_id: ID of the order
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.select_related('customer__user').get(id=order_id)
        
        # Send email
        success = OrderNotifications.send_email_notification(
            order, 
            'payment_failed'
        )
        
        if success:
            logger.info(f"✅ Payment failed notification sent for {order.order_number}")
            
            # Alert admin about failed payment
            OrderNotifications.send_admin_alert(
                order,
                'Payment Failed',
                f"Payment failed for order {order.order_number}. "
                f"Customer: {order.customer.user.email if order.customer else order.guest_email}"
            )
            
            return f"Payment failed notification sent for order {order.order_number}"
        else:
            raise Exception("Failed to send email")
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send payment notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_processing_notification(self, order_id):
    """
    Send order processing notification.
    
    Args:
        order_id: ID of the order
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.select_related('customer__user').get(id=order_id)
        
        # Send email
        success = OrderNotifications.send_email_notification(
            order, 
            'order_processing'
        )
        
        if success:
            logger.info(f"✅ Processing notification sent for {order.order_number}")
            return f"Processing notification sent for order {order.order_number}"
        else:
            raise Exception("Failed to send email")
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send processing notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ============================================================================
# ORDER STATUS & LIFECYCLE TASKS
# ============================================================================

@shared_task
def update_order_status_task(order_id, old_status, new_status):
    """
    Handle order status updates and trigger appropriate notifications.
    
    Args:
        order_id: ID of the order
        old_status: Previous status
        new_status: New status
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.get(id=order_id)
        
        # Send appropriate notification based on status
        if new_status == 'confirmed':
            send_order_confirmation_email.delay(order_id)
        
        elif new_status == 'processing':
            send_processing_notification.delay(order_id)
        
        elif new_status == 'shipped':
            send_shipping_notification_email.delay(order_id)
        
        elif new_status == 'delivered':
            send_delivery_notification_email.delay(order_id)
            # Award loyalty points for completed order
            award_order_loyalty_points.delay(order_id)
        
        elif new_status == 'cancelled':
            send_cancellation_notification_email.delay(order_id)
        
        logger.info(
            f"Status updated from {old_status} to {new_status} "
            f"for order {order.order_number}"
        )
        
        return f"Status updated for order {order.order_number}"
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise


@shared_task
def auto_confirm_paid_orders():
    """
    Automatically confirm orders that have been paid.
    Runs every 5 minutes via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find pending orders that are paid
        orders_to_confirm = Order.objects.filter(
            status='pending',
            payment_status='paid'
        )
        
        confirmed_count = 0
        
        for order in orders_to_confirm:
            old_status = order.status
            order.status = 'confirmed'
            order.save()
            
            # Create status history
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status='confirmed',
                changed_by=None,
                notes='Auto-confirmed after payment'
            )
            
            # Send confirmation email
            send_order_confirmation_email.delay(order.id)
            
            confirmed_count += 1
        
        logger.info(f"Auto-confirmed {confirmed_count} orders")
        return f"Auto-confirmed {confirmed_count} orders"
        
    except Exception as exc:
        logger.error(f"Failed to auto-confirm orders: {exc}", exc_info=True)
        raise


@shared_task
def auto_cancel_unpaid_orders():
    """
    Automatically cancel orders that haven't been paid after 24 hours.
    Runs daily via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find pending orders older than 24 hours
        cutoff_time = timezone.now() - timedelta(hours=24)
        
        orders_to_cancel = Order.objects.filter(
            status='pending',
            payment_status__in=['pending', 'failed'],
            created_at__lt=cutoff_time
        )
        
        cancelled_count = 0
        
        for order in orders_to_cancel:
            old_status = order.status
            order.status = 'cancelled'
            order.cancelled_at = timezone.now()
            order.save()
            
            # Restock items
            for item in order.items.all():
                item.product.stock_quantity += item.quantity
                item.product.save()
            
            # Create status history
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status='cancelled',
                changed_by=None,
                notes='Auto-cancelled - payment not received within 24 hours'
            )
            
            # Send cancellation email
            send_cancellation_notification_email.delay(
                order.id, 
                "Payment not received within 24 hours"
            )
            
            cancelled_count += 1
        
        logger.info(f"Auto-cancelled {cancelled_count} unpaid orders")
        return f"Auto-cancelled {cancelled_count} unpaid orders"
        
    except Exception as exc:
        logger.error(f"Failed to auto-cancel orders: {exc}", exc_info=True)
        raise


# ============================================================================
# LOYALTY POINTS TASKS
# ============================================================================

@shared_task
def award_order_loyalty_points(order_id):
    """
    Award loyalty points when order is delivered.
    Points = 1 point per 100 KSh spent (configurable).
    
    Args:
        order_id: ID of the order
    
    Returns:
        str: Success message
    """
    try:
        order = Order.objects.select_related('customer').get(id=order_id)
        
        # Only award points for non-guest orders
        if not order.customer:
            logger.info(f"Skipping loyalty points for guest order {order.order_number}")
            return "Guest order - no points awarded"
        
        # Calculate points (1 point per 100 KSh)
        points_to_award = int(order.total / 100)
        
        if points_to_award > 0:
            # Add points to customer
            customer = order.customer
            customer.loyalty_points += points_to_award
            customer.save(update_fields=['loyalty_points'])
            
            # Send notification
            from customers.tasks import send_loyalty_points_notification
            send_loyalty_points_notification.delay(
                customer.id,
                points_to_award,
                f"Points earned from order {order.order_number}"
            )
            
            logger.info(
                f"Awarded {points_to_award} loyalty points to customer "
                f"{customer.user.email} for order {order.order_number}"
            )
            
            return f"Awarded {points_to_award} points for order {order.order_number}"
        
        return "No points to award (order total too low)"
        
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to award loyalty points: {exc}", exc_info=True)
        raise


# ============================================================================
# ORDER MONITORING TASKS
# ============================================================================

@shared_task
def check_delayed_orders():
    """
    Check for orders that are delayed in shipping.
    Runs daily via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find shipped orders older than 7 days without delivery
        threshold_date = timezone.now() - timedelta(days=7)
        
        delayed_orders = Order.objects.filter(
            status='shipped',
            shipped_date__lt=threshold_date,
            delivered_date__isnull=True
        )
        
        for order in delayed_orders:
            # Send alert to admin
            OrderNotifications.send_admin_alert(
                order,
                'Delayed Order',
                f"Order {order.order_number} shipped on {order.shipped_date} "
                f"is still not delivered. Tracking: {order.tracking_number or 'N/A'}"
            )
        
        logger.info(f"Checked {delayed_orders.count()} delayed orders")
        return f"Found {delayed_orders.count()} delayed orders"
        
    except Exception as exc:
        logger.error(f"Failed to check delayed orders: {exc}", exc_info=True)
        raise


@shared_task
def check_pending_orders():
    """
    Monitor pending orders and alert for anomalies.
    Runs every hour via Celery Beat.
    
    Returns:
        str: Success message
    """
    try:
        # Check for high-value pending orders
        high_value_threshold = Decimal('50000.00')  # 50,000 KSh
        
        high_value_pending = Order.objects.filter(
            status='pending',
            payment_status='pending',
            total__gte=high_value_threshold
        )
        
        for order in high_value_pending:
            # Alert admin about high-value pending order
            OrderNotifications.send_admin_alert(
                order,
                'High-Value Pending Order',
                f"High-value order {order.order_number} (KSh {order.total}) "
                f"is pending payment. Customer: {order.customer.user.email if order.customer else order.guest_email}"
            )
        
        # Check for stuck orders (processing for more than 48 hours)
        stuck_threshold = timezone.now() - timedelta(hours=48)
        
        stuck_orders = Order.objects.filter(
            status='processing',
            updated_at__lt=stuck_threshold
        )
        
        for order in stuck_orders:
            OrderNotifications.send_admin_alert(
                order,
                'Stuck Order',
                f"Order {order.order_number} has been in processing status for over 48 hours"
            )
        
        logger.info(
            f"Monitoring: {high_value_pending.count()} high-value pending, "
            f"{stuck_orders.count()} stuck orders"
        )
        
        return f"Monitoring complete"
        
    except Exception as exc:
        logger.error(f"Failed to check pending orders: {exc}", exc_info=True)
        raise


# ============================================================================
# TRACKING & SHIPPING TASKS
# ============================================================================

@shared_task
def sync_tracking_updates():
    """
    Sync tracking updates from carriers.
    Runs every 6 hours via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        from .shipping import ShippingIntegration
        
        # Get orders with tracking that aren't delivered
        orders_with_tracking = Order.objects.exclude(
            tracking_number=''
        ).filter(
            status__in=['shipped', 'out_for_delivery']
        )
        
        updated_count = 0
        
        for order in orders_with_tracking:
            try:
                # Get tracking info from carrier
                tracking_info = ShippingIntegration.track_shipment(
                    order.tracking_number,
                    order.carrier
                )
                
                if tracking_info:
                    # Update order status based on tracking
                    # This is carrier-specific implementation
                    # Example for generic handling:
                    status = tracking_info.get('status', '').lower()
                    
                    if 'delivered' in status and order.status != 'delivered':
                        order.status = 'delivered'
                        order.delivered_date = timezone.now()
                        order.save()
                        
                        # Send delivery notification
                        send_delivery_notification_email.delay(order.id)
                        
                        updated_count += 1
                    
                    elif 'out for delivery' in status and order.status != 'out_for_delivery':
                        order.status = 'out_for_delivery'
                        order.save()
                        updated_count += 1
                
            except Exception as track_exc:
                logger.error(
                    f"Failed to track order {order.order_number}: {track_exc}"
                )
                continue
        
        logger.info(f"Updated tracking for {updated_count} orders")
        return f"Updated {updated_count} orders"
        
    except Exception as exc:
        logger.error(f"Failed to sync tracking: {exc}", exc_info=True)
        raise


# ============================================================================
# ANALYTICS & REPORTING TASKS
# ============================================================================

@shared_task
def generate_daily_order_report():
    """
    Generate daily order report and send to admins.
    Runs daily at 11 PM via Celery Beat.
    
    Returns:
        dict: Report data
    """
    try:
        today = timezone.now().date()
        
        # Get today's orders
        today_orders = Order.objects.filter(created_at__date=today)
        
        # Calculate metrics
        report_data = {
            'date': today.isoformat(),
            'total_orders': today_orders.count(),
            'total_revenue': today_orders.aggregate(Sum('total'))['total__sum'] or 0,
            'average_order_value': today_orders.aggregate(Avg('total'))['total__avg'] or 0,
            'by_status': dict(
                today_orders.values_list('status').annotate(Count('id'))
            ),
            'by_payment_method': dict(
                today_orders.exclude(payment_method='').values_list('payment_method').annotate(Count('id'))
            ),
            'top_products': list(
                OrderItem.objects.filter(
                    order__created_at__date=today
                ).values('product__name').annotate(
                    quantity=Sum('quantity'),
                    revenue=Sum(F('price') * F('quantity'))
                ).order_by('-revenue')[:5]
            ),
        }
        
        # Send report to admins
        from customers.utils import send_mail_to_admins
        
        subject = f"Daily Order Report - {today}"
        message = f"""
Daily Order Report for {today}

Total Orders: {report_data['total_orders']}
Total Revenue: KSh {report_data['total_revenue']:,.2f}
Average Order Value: KSh {report_data['average_order_value']:,.2f}

Orders by Status:
{chr(10).join(f"  {status}: {count}" for status, count in report_data['by_status'].items())}

Orders by Payment Method:
{chr(10).join(f"  {method}: {count}" for method, count in report_data['by_payment_method'].items())}

Top 5 Products:
{chr(10).join(f"  {i+1}. {item['product__name']}: {item['quantity']} units (KSh {item['revenue']:,.2f})" for i, item in enumerate(report_data['top_products']))}

Best regards,
SoundWaveAudio Analytics System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Daily order report generated for {today}")
        return report_data
        
    except Exception as exc:
        logger.error(f"Failed to generate daily report: {exc}", exc_info=True)
        raise


@shared_task
def cleanup_old_order_data():
    """
    Clean up old order-related data.
    Runs weekly via Celery Beat.
    
    Returns:
        str: Success message
    """
    try:
        # Delete old status history (keep last 6 months)
        six_months_ago = timezone.now() - timedelta(days=180)
        
        deleted_history = OrderStatusHistory.objects.filter(
            created_at__lt=six_months_ago
        ).delete()
        
        logger.info(
            f"Cleaned up {deleted_history[0]} old status history records"
        )
        
        return f"Cleaned up {deleted_history[0]} records"
        
    except Exception as exc:
        logger.error(f"Failed to cleanup old data: {exc}", exc_info=True)
        raise


# ============================================================================
# SCHEDULED TASK CONFIGURATIONS
# ============================================================================

"""
Add these to your Celery Beat schedule in settings.py:

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Auto-confirm paid orders every 5 minutes
    'auto-confirm-paid-orders': {
        'task': 'orders.tasks.auto_confirm_paid_orders',
        'schedule': crontab(minute='*/5'),
    },
    
    # Auto-cancel unpaid orders daily at 2 AM
    'auto-cancel-unpaid-orders': {
        'task': 'orders.tasks.auto_cancel_unpaid_orders',
        'schedule': crontab(hour=2, minute=0),
    },
    
    # Check delayed orders daily at 9 AM
    'check-delayed-orders': {
        'task': 'orders.tasks.check_delayed_orders',
        'schedule': crontab(hour=9, minute=0),
    },
    
    # Check pending orders every hour
    'check-pending-orders': {
        'task': 'orders.tasks.check_pending_orders',
        'schedule': crontab(minute=0),
    },
    
    # Sync tracking updates every 6 hours
    'sync-tracking-updates': {
        'task': 'orders.tasks.sync_tracking_updates',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    
    # Generate daily report at 11 PM
    'generate-daily-order-report': {
        'task': 'orders.tasks.generate_daily_order_report',
        'schedule': crontab(hour=23, minute=0),
    },
    
    # Cleanup old data weekly on Sunday at 3 AM
    'cleanup-old-order-data': {
        'task': 'orders.tasks.cleanup_old_order_data',
        'schedule': crontab(day_of_week=0, hour=3, minute=0),
    },
}
"""