"""
God-Level Celery Tasks for Inventory App
Handles stock monitoring, warehouse operations, transfers, and analytics
"""
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F, Q, Min, Max
from django.db.models.functions import TruncDate, TruncMonth
from datetime import timedelta
from decimal import Decimal
import logging

from .models import (
    Warehouse, WarehouseStock, StockMovement, InventoryTransfer,
    TransferItem, StockAlert, StockCount, StockCountItem
)
from products.models import Product
from orders.models import Order

logger = logging.getLogger(__name__)


# ============================================================================
# STOCK LEVEL MONITORING TASKS
# ============================================================================

@shared_task
def monitor_stock_levels():
    """
    Comprehensive stock monitoring across all warehouses.
    Creates alerts for low stock, out of stock, and overstock situations.
    Runs every 30 minutes via Celery Beat.
    
    Returns:
        dict: Summary of alerts created
    """
    try:
        alerts_created = {
            'low_stock': 0,
            'out_of_stock': 0,
            'reorder_point': 0,
            'overstock': 0
        }
        
        # Monitor all active warehouses
        active_warehouses = Warehouse.objects.filter(is_active=True)
        
        for warehouse in active_warehouses:
            warehouse_stocks = WarehouseStock.objects.filter(
                warehouse=warehouse
            ).select_related('product')
            
            for stock in warehouse_stocks:
                # Out of stock
                if stock.quantity == 0:
                    alert, created = StockAlert.objects.get_or_create(
                        alert_type='out_of_stock',
                        warehouse=warehouse,
                        product=stock.product,
                        is_resolved=False,
                        defaults={
                            'priority': 'critical',
                            'message': f'{stock.product.name} is out of stock at {warehouse.name}',
                            'current_quantity': 0,
                            'threshold_quantity': stock.reorder_point
                        }
                    )
                    if created:
                        alerts_created['out_of_stock'] += 1
                
                # Low stock (at or below reorder point)
                elif stock.quantity <= stock.reorder_point and stock.reorder_point > 0:
                    alert, created = StockAlert.objects.get_or_create(
                        alert_type='low_stock',
                        warehouse=warehouse,
                        product=stock.product,
                        is_resolved=False,
                        defaults={
                            'priority': 'high',
                            'message': f'{stock.product.name} is below reorder point at {warehouse.name}',
                            'current_quantity': stock.quantity,
                            'threshold_quantity': stock.reorder_point
                        }
                    )
                    if created:
                        alerts_created['low_stock'] += 1
                
                # Reorder point reached (needs ordering)
                elif stock.needs_reorder:
                    alert, created = StockAlert.objects.get_or_create(
                        alert_type='reorder_point',
                        warehouse=warehouse,
                        product=stock.product,
                        is_resolved=False,
                        defaults={
                            'priority': 'medium',
                            'message': f'{stock.product.name} needs reordering at {warehouse.name}',
                            'current_quantity': stock.quantity,
                            'threshold_quantity': stock.reorder_point
                        }
                    )
                    if created:
                        alerts_created['reorder_point'] += 1
                
                # Overstock detection (3x reorder quantity)
                elif stock.reorder_quantity > 0 and stock.quantity > (stock.reorder_quantity * 3):
                    alert, created = StockAlert.objects.get_or_create(
                        alert_type='overstock',
                        warehouse=warehouse,
                        product=stock.product,
                        is_resolved=False,
                        defaults={
                            'priority': 'low',
                            'message': f'{stock.product.name} may be overstocked at {warehouse.name}',
                            'current_quantity': stock.quantity,
                            'threshold_quantity': stock.reorder_quantity * 3
                        }
                    )
                    if created:
                        alerts_created['overstock'] += 1
                
                # Auto-resolve alerts if stock is replenished
                else:
                    StockAlert.objects.filter(
                        warehouse=warehouse,
                        product=stock.product,
                        alert_type__in=['low_stock', 'out_of_stock', 'reorder_point'],
                        is_resolved=False
                    ).update(
                        is_resolved=True,
                        resolution_notes='Stock replenished automatically'
                    )
        
        # Send consolidated alert if critical alerts exist
        total_alerts = sum(alerts_created.values())
        if total_alerts > 0:
            send_stock_alert_summary.delay(alerts_created)
        
        logger.info(f"Stock monitoring complete: {total_alerts} alerts created")
        return alerts_created
    
    except Exception as exc:
        logger.error(f"Failed to monitor stock levels: {exc}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_stock_alert_summary(self, alerts_created):
    """
    Send consolidated stock alert summary to admins.
    
    Args:
        alerts_created: Dictionary of alert counts by type
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        # Get critical alerts
        critical_alerts = StockAlert.objects.filter(
            priority='critical',
            is_resolved=False
        ).select_related('warehouse', 'product')[:20]
        
        # Get high priority alerts
        high_alerts = StockAlert.objects.filter(
            priority='high',
            is_resolved=False
        ).select_related('warehouse', 'product')[:20]
        
        subject = f"📦 Stock Alert Summary - {alerts_created['out_of_stock']} Critical"
        
        message = f"""
Stock Monitoring Alert Summary

New Alerts Created:
  • Out of Stock: {alerts_created['out_of_stock']}
  • Low Stock: {alerts_created['low_stock']}
  • Reorder Point: {alerts_created['reorder_point']}
  • Overstock: {alerts_created['overstock']}

CRITICAL - Out of Stock ({critical_alerts.count()}):
{chr(10).join(f"  • {a.product.name} ({a.product.sku}) at {a.warehouse.name}" for a in critical_alerts) if critical_alerts else "  None"}

HIGH PRIORITY - Low Stock ({high_alerts.count()}):
{chr(10).join(f"  • {a.product.name} ({a.product.sku}) at {a.warehouse.name} - {a.current_quantity} units" for a in high_alerts) if high_alerts else "  None"}

Please review and take action on these inventory alerts.

Best regards,
SoundWaveAudio Inventory System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Stock alert summary sent")
        return f"Stock alert summary sent"
    
    except Exception as exc:
        logger.error(f"Failed to send stock alert summary: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task
def check_damaged_stock():
    """
    Monitor and alert on damaged inventory.
    Runs daily via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find warehouses with damaged stock
        damaged_stock = WarehouseStock.objects.filter(
            damaged_quantity__gt=0
        ).select_related('warehouse', 'product')
        
        alerts_created = 0
        
        for stock in damaged_stock:
            # Calculate damage percentage
            if stock.quantity > 0:
                damage_percentage = (stock.damaged_quantity / stock.quantity) * 100
                priority = 'critical' if damage_percentage > 20 else 'high'
            else:
                priority = 'medium'
            
            alert, created = StockAlert.objects.get_or_create(
                alert_type='damaged',
                warehouse=stock.warehouse,
                product=stock.product,
                is_resolved=False,
                defaults={
                    'priority': priority,
                    'message': f'{stock.damaged_quantity} units of {stock.product.name} damaged at {stock.warehouse.name}',
                    'current_quantity': stock.damaged_quantity,
                    'threshold_quantity': 0
                }
            )
            
            if created:
                alerts_created += 1
        
        if alerts_created > 0:
            send_damaged_stock_alert.delay(list(damaged_stock.values_list('id', flat=True)))
        
        logger.info(f"Damaged stock check complete: {alerts_created} new alerts")
        return f"Damaged stock check complete: {alerts_created} new alerts"
    
    except Exception as exc:
        logger.error(f"Failed to check damaged stock: {exc}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_damaged_stock_alert(self, stock_ids):
    """
    Send damaged stock alert to admins.
    
    Args:
        stock_ids: List of WarehouseStock IDs with damage
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        damaged_items = WarehouseStock.objects.filter(
            id__in=stock_ids
        ).select_related('warehouse', 'product')
        
        total_damaged_value = sum(
            item.damaged_quantity * (item.product.cost_price or 0)
            for item in damaged_items
        )
        
        subject = f"⚠️ Damaged Inventory Alert - KSh {total_damaged_value:,.2f} Value"
        
        message = f"""
Damaged Inventory Report

Total Damaged Items: {damaged_items.count()}
Total Value: KSh {total_damaged_value:,.2f}

Damaged Stock:
{chr(10).join(f"  • {item.product.name} ({item.product.sku}) at {item.warehouse.name}: {item.damaged_quantity} units (KSh {item.damaged_quantity * (item.product.cost_price or 0):,.2f})" for item in damaged_items)}

Please investigate and take appropriate action (repair, dispose, insurance claim).

Best regards,
SoundWaveAudio Inventory System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Damaged stock alert sent for {len(stock_ids)} items")
        return f"Damaged stock alert sent"
    
    except Exception as exc:
        logger.error(f"Failed to send damaged stock alert: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ============================================================================
# WAREHOUSE CAPACITY MONITORING
# ============================================================================

@shared_task
def monitor_warehouse_capacity():
    """
    Monitor warehouse capacity usage and alert when approaching limits.
    Runs every 6 hours via Celery Beat.
    
    Returns:
        dict: Warehouse capacity summary
    """
    try:
        warehouses = Warehouse.objects.filter(is_active=True)
        
        capacity_alerts = []
        
        for warehouse in warehouses:
            if warehouse.max_capacity and warehouse.max_capacity > 0:
                usage_percentage = warehouse.capacity_percentage
                
                # Alert thresholds
                if usage_percentage >= 90:
                    priority = 'critical'
                    message = f'{warehouse.name} is at {usage_percentage:.1f}% capacity (CRITICAL)'
                    capacity_alerts.append({
                        'warehouse': warehouse.name,
                        'usage': usage_percentage,
                        'priority': priority
                    })
                elif usage_percentage >= 80:
                    priority = 'high'
                    message = f'{warehouse.name} is at {usage_percentage:.1f}% capacity (HIGH)'
                    capacity_alerts.append({
                        'warehouse': warehouse.name,
                        'usage': usage_percentage,
                        'priority': priority
                    })
                elif usage_percentage >= 70:
                    priority = 'medium'
                    message = f'{warehouse.name} is at {usage_percentage:.1f}% capacity'
                    capacity_alerts.append({
                        'warehouse': warehouse.name,
                        'usage': usage_percentage,
                        'priority': priority
                    })
        
        if capacity_alerts:
            send_capacity_alert.delay(capacity_alerts)
        
        logger.info(f"Capacity monitoring complete: {len(capacity_alerts)} alerts")
        return {'alerts': capacity_alerts}
    
    except Exception as exc:
        logger.error(f"Failed to monitor warehouse capacity: {exc}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_capacity_alert(self, capacity_alerts):
    """
    Send warehouse capacity alerts to admins.
    
    Args:
        capacity_alerts: List of warehouse capacity alert data
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        critical = [a for a in capacity_alerts if a['priority'] == 'critical']
        high = [a for a in capacity_alerts if a['priority'] == 'high']
        medium = [a for a in capacity_alerts if a['priority'] == 'medium']
        
        subject = f"📊 Warehouse Capacity Alert - {len(critical)} Critical"
        
        message = f"""
Warehouse Capacity Monitoring Alert

CRITICAL (≥90%):
{chr(10).join(f"  • {a['warehouse']}: {a['usage']:.1f}% full" for a in critical) if critical else "  None"}

HIGH (80-89%):
{chr(10).join(f"  • {a['warehouse']}: {a['usage']:.1f}% full" for a in high) if high else "  None"}

MEDIUM (70-79%):
{chr(10).join(f"  • {a['warehouse']}: {a['usage']:.1f}% full" for a in medium) if medium else "  None"}

Consider:
- Reviewing slow-moving inventory
- Planning warehouse transfers
- Expanding capacity
- Optimizing storage layout

Best regards,
SoundWaveAudio Warehouse Management
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Capacity alert sent")
        return "Capacity alert sent"
    
    except Exception as exc:
        logger.error(f"Failed to send capacity alert: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ============================================================================
# TRANSFER MANAGEMENT TASKS
# ============================================================================

@shared_task
def monitor_pending_transfers():
    """
    Monitor pending transfers and alert on delays.
    Runs every 2 hours via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find transfers pending for more than 24 hours
        threshold = timezone.now() - timedelta(hours=24)
        
        delayed_approvals = InventoryTransfer.objects.filter(
            status='draft',
            requested_at__lt=threshold
        ).select_related('from_warehouse', 'to_warehouse', 'requested_by')
        
        # Find transfers in transit for more than expected
        overdue_deliveries = InventoryTransfer.objects.filter(
            status='in_transit',
            expected_arrival__lt=timezone.now()
        ).select_related('from_warehouse', 'to_warehouse')
        
        if delayed_approvals.exists() or overdue_deliveries.exists():
            send_transfer_delay_alert.delay(
                list(delayed_approvals.values_list('id', flat=True)),
                list(overdue_deliveries.values_list('id', flat=True))
            )
        
        total = delayed_approvals.count() + overdue_deliveries.count()
        logger.info(f"Transfer monitoring: {total} delayed transfers found")
        return f"Found {total} delayed transfers"
    
    except Exception as exc:
        logger.error(f"Failed to monitor transfers: {exc}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_transfer_delay_alert(self, delayed_approval_ids, overdue_delivery_ids):
    """
    Send transfer delay alert to admins.
    
    Args:
        delayed_approval_ids: IDs of transfers waiting approval
        overdue_delivery_ids: IDs of overdue in-transit transfers
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        delayed_approvals = InventoryTransfer.objects.filter(
            id__in=delayed_approval_ids
        ).select_related('from_warehouse', 'to_warehouse', 'requested_by')
        
        overdue_deliveries = InventoryTransfer.objects.filter(
            id__in=overdue_delivery_ids
        ).select_related('from_warehouse', 'to_warehouse')
        
        subject = f"🚚 Transfer Delays - {len(delayed_approval_ids)} Pending Approval"
        
        message = f"""
Inventory Transfer Delay Alert

PENDING APPROVAL (>24 hours):
{chr(10).join(f"  • {t.transfer_number}: {t.from_warehouse.code} → {t.to_warehouse.code} (Requested: {t.requested_at.strftime('%Y-%m-%d %H:%M')})" for t in delayed_approvals) if delayed_approvals else "  None"}

OVERDUE DELIVERIES:
{chr(10).join(f"  • {t.transfer_number}: {t.from_warehouse.code} → {t.to_warehouse.code} (Expected: {t.expected_arrival.strftime('%Y-%m-%d')})" for t in overdue_deliveries) if overdue_deliveries else "  None"}

Please review and process these transfers immediately.

Best regards,
SoundWaveAudio Transfer Management
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Transfer delay alert sent")
        return "Transfer delay alert sent"
    
    except Exception as exc:
        logger.error(f"Failed to send transfer delay alert: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_transfer_notification(self, transfer_id, notification_type):
    """
    Send transfer status notification to warehouse managers.
    
    Args:
        transfer_id: ID of the transfer
        notification_type: Type of notification (approved, shipped, received)
    
    Returns:
        str: Success message
    """
    try:
        transfer = InventoryTransfer.objects.select_related(
            'from_warehouse', 'to_warehouse', 'requested_by'
        ).get(id=transfer_id)
        
        # Determine recipients
        recipients = []
        if transfer.from_warehouse.manager:
            recipients.append(transfer.from_warehouse.manager.email)
        if transfer.to_warehouse.manager:
            recipients.append(transfer.to_warehouse.manager.email)
        
        if not recipients:
            logger.warning(f"No recipients for transfer notification {transfer_id}")
            return "No recipients"
        
        # Build message based on type
        if notification_type == 'approved':
            subject = f"Transfer Approved: {transfer.transfer_number}"
            message = f"""
Your inventory transfer has been approved.

Transfer: {transfer.transfer_number}
From: {transfer.from_warehouse.name}
To: {transfer.to_warehouse.name}
Status: Approved - Ready for Shipment

Items:
{chr(10).join(f"  • {item.product.name}: {item.quantity} units" for item in transfer.items.all())}

Next Steps: Ship the items and update tracking information.

Best regards,
SoundWaveAudio Inventory System
"""
        
        elif notification_type == 'shipped':
            subject = f"Transfer Shipped: {transfer.transfer_number}"
            message = f"""
Inventory transfer has been shipped.

Transfer: {transfer.transfer_number}
From: {transfer.from_warehouse.name}
To: {transfer.to_warehouse.name}
Tracking: {transfer.tracking_number or 'N/A'}
Expected Arrival: {transfer.expected_arrival.strftime('%Y-%m-%d') if transfer.expected_arrival else 'TBD'}

Items:
{chr(10).join(f"  • {item.product.name}: {item.quantity} units" for item in transfer.items.all())}

Please prepare for receipt and inspection.

Best regards,
SoundWaveAudio Inventory System
"""
        
        elif notification_type == 'received':
            subject = f"Transfer Received: {transfer.transfer_number}"
            message = f"""
Inventory transfer has been received and processed.

Transfer: {transfer.transfer_number}
From: {transfer.from_warehouse.name}
To: {transfer.to_warehouse.name}
Received: {transfer.received_at.strftime('%Y-%m-%d %H:%M')}

Items Received:
{chr(10).join(f"  • {item.product.name}: {item.received_quantity}/{item.quantity} units" for item in transfer.items.all())}

Inventory has been updated accordingly.

Best regards,
SoundWaveAudio Inventory System
"""
        
        else:
            return f"Unknown notification type: {notification_type}"
        
        # Send email
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwaveaudio.com'),
            to=recipients,
        )
        email.send(fail_silently=False)
        
        logger.info(f"Transfer {notification_type} notification sent for {transfer.transfer_number}")
        return f"Transfer notification sent"
    
    except InventoryTransfer.DoesNotExist:
        logger.error(f"Transfer {transfer_id} not found")
        raise
    
    except Exception as exc:
        logger.error(f"Failed to send transfer notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ============================================================================
# STOCK COUNT TASKS
# ============================================================================

@shared_task
def schedule_automatic_stock_counts():
    """
    Automatically schedule stock counts based on warehouse settings.
    Runs weekly via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        from django.contrib.auth.models import User
        
        warehouses = Warehouse.objects.filter(is_active=True)
        counts_scheduled = 0
        
        for warehouse in warehouses:
            # Check if warehouse needs a cycle count (every 2 weeks)
            last_count = StockCount.objects.filter(
                warehouse=warehouse,
                count_type='cycle',
                status='completed'
            ).order_by('-completed_at').first()
            
            should_schedule = False
            
            if not last_count:
                should_schedule = True
            else:
                days_since_count = (timezone.now() - last_count.completed_at).days
                if days_since_count >= 14:
                    should_schedule = True
            
            if should_schedule:
                # Schedule cycle count for next week
                scheduled_date = timezone.now().date() + timedelta(days=7)
                
                # Assign to warehouse manager
                assigned_to = warehouse.manager if warehouse.manager else User.objects.filter(is_staff=True).first()
                
                if assigned_to:
                    stock_count = StockCount.objects.create(
                        warehouse=warehouse,
                        count_type='cycle',
                        scheduled_date=scheduled_date,
                        assigned_to=assigned_to,
                        notes='Automatically scheduled cycle count'
                    )
                    
                    # Add high-value or high-movement items to count
                    # Get top 50 products by movement in last 30 days
                    thirty_days_ago = timezone.now() - timedelta(days=30)
                    
                    high_activity_products = StockMovement.objects.filter(
                        warehouse=warehouse,
                        created_at__gte=thirty_days_ago
                    ).values('product').annotate(
                        movement_count=Count('id')
                    ).order_by('-movement_count')[:50]
                    
                    product_ids = [item['product'] for item in high_activity_products]
                    
                    warehouse_stocks = WarehouseStock.objects.filter(
                        warehouse=warehouse,
                        product_id__in=product_ids
                    )
                    
                    for stock in warehouse_stocks:
                        StockCountItem.objects.create(
                            stock_count=stock_count,
                            product=stock.product,
                            expected_quantity=stock.quantity
                        )
                    
                    counts_scheduled += 1
                    
                    # Send notification
                    send_stock_count_scheduled_notification.delay(stock_count.id)
        
        logger.info(f"Scheduled {counts_scheduled} automatic stock counts")
        return f"Scheduled {counts_scheduled} stock counts"
    
    except Exception as exc:
        logger.error(f"Failed to schedule stock counts: {exc}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_stock_count_scheduled_notification(self, count_id):
    """
    Send notification when stock count is scheduled.
    
    Args:
        count_id: ID of the stock count
    
    Returns:
        str: Success message
    """
    try:
        stock_count = StockCount.objects.select_related(
            'warehouse', 'assigned_to'
        ).get(id=count_id)
        
        recipient_email = stock_count.assigned_to.email
        recipient_name = stock_count.assigned_to.get_full_name() or stock_count.assigned_to.first_name
        
        subject = f"Stock Count Scheduled: {stock_count.count_number}"
        
        message = f"""
Dear {recipient_name},

A stock count has been scheduled for your attention.

Count Number: {stock_count.count_number}
Warehouse: {stock_count.warehouse.name}
Type: {stock_count.get_count_type_display()}
Scheduled Date: {stock_count.scheduled_date.strftime('%Y-%m-%d')}
Items to Count: {stock_count.total_items}

Please complete this count by the scheduled date.

Best regards,
SoundWaveAudio Inventory System
"""
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwaveaudio.com'),
            to=[recipient_email],
        )
        email.send(fail_silently=False)
        
        logger.info(f"Stock count scheduled notification sent to {recipient_email}")
        return "Stock count notification sent"
    
    except StockCount.DoesNotExist:
        logger.error(f"Stock count {count_id} not found")
        raise
    
    except Exception as exc:
        logger.error(f"Failed to send stock count notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task
def analyze_stock_count_discrepancies():
    """
    Analyze completed stock counts for patterns in discrepancies.
    Runs weekly via Celery Beat.
    
    Returns:
        dict: Analysis results
    """
    try:
        from customers.utils import send_mail_to_admins
        
        # Analyze counts from last 30 days
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        completed_counts = StockCount.objects.filter(
            status='completed',
            completed_at__gte=thirty_days_ago
        ).prefetch_related('items')
        
        total_counts = completed_counts.count()
        total_items_counted = 0
        total_discrepancies = 0
        discrepancy_value = Decimal('0.00')
        
        warehouse_discrepancies = {}
        product_discrepancies = {}
        
        for count in completed_counts:
            for item in count.items.all():
                total_items_counted += 1
                
                if item.has_discrepancy:
                    total_discrepancies += 1
                    
                    # Calculate value of discrepancy
                    if item.product.cost_price:
                        discrepancy_value += abs(item.discrepancy) * item.product.cost_price
                    
                    # Track by warehouse
                    warehouse_name = count.warehouse.name
                    if warehouse_name not in warehouse_discrepancies:
                        warehouse_discrepancies[warehouse_name] = 0
                    warehouse_discrepancies[warehouse_name] += 1
                    
                    # Track by product
                    product_key = f"{item.product.name} ({item.product.sku})"
                    if product_key not in product_discrepancies:
                        product_discrepancies[product_key] = 0
                    product_discrepancies[product_key] += 1
        
        # Calculate accuracy rate
        accuracy_rate = ((total_items_counted - total_discrepancies) / total_items_counted * 100) if total_items_counted > 0 else 100
        
        # Find top problem areas
        top_warehouses = sorted(warehouse_discrepancies.items(), key=lambda x: x[1], reverse=True)[:5]
        top_products = sorted(product_discrepancies.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Send report
        subject = f"📋 Stock Count Analysis - {accuracy_rate:.1f}% Accuracy"
        
        message = f"""
Stock Count Discrepancy Analysis (Last 30 Days)

Summary:
  • Total Counts Completed: {total_counts}
  • Total Items Counted: {total_items_counted}
  • Discrepancies Found: {total_discrepancies}
  • Accuracy Rate: {accuracy_rate:.1f}%
  • Discrepancy Value: KSh {discrepancy_value:,.2f}

Warehouses with Most Discrepancies:
{chr(10).join(f"  {i+1}. {wh}: {count} discrepancies" for i, (wh, count) in enumerate(top_warehouses)) if top_warehouses else "  None"}

Products with Most Discrepancies:
{chr(10).join(f"  {i+1}. {prod}: {count} times" for i, (prod, count) in enumerate(top_products)) if top_products else "  None"}

Recommendations:
  • Review counting procedures at problematic warehouses
  • Investigate frequently miscounted products
  • Consider additional training for count teams
  • Review security and theft prevention measures

Best regards,
SoundWaveAudio Inventory Analytics
"""
        
        send_mail_to_admins(subject, message)
        
        results = {
            'total_counts': total_counts,
            'total_items': total_items_counted,
            'discrepancies': total_discrepancies,
            'accuracy_rate': float(accuracy_rate),
            'discrepancy_value': float(discrepancy_value)
        }
        
        logger.info(f"Stock count analysis complete: {accuracy_rate:.1f}% accuracy")
        return results
    
    except Exception as exc:
        logger.error(f"Failed to analyze stock counts: {exc}", exc_info=True)
        raise


# ============================================================================
# INVENTORY ANALYTICS & REPORTING TASKS
# ============================================================================

@shared_task
def generate_inventory_valuation_report():
    """
    Generate daily inventory valuation report.
    Runs daily at 11 PM via Celery Beat.
    
    Returns:
        dict: Valuation report data
    """
    try:
        from customers.utils import send_mail_to_admins
        
        today = timezone.now().date()
        
        # Calculate inventory value by warehouse
        warehouses = Warehouse.objects.filter(is_active=True)
        warehouse_valuations = []
        total_inventory_value = Decimal('0.00')
        total_units = 0
        
        for warehouse in warehouses:
            stocks = WarehouseStock.objects.filter(
                warehouse=warehouse
            ).select_related('product')
            
            warehouse_value = Decimal('0.00')
            warehouse_units = 0
            
            for stock in stocks:
                if stock.product.cost_price:
                    warehouse_value += stock.quantity * stock.product.cost_price
                warehouse_units += stock.quantity
            
            warehouse_valuations.append({
                'warehouse': warehouse.name,
                'value': warehouse_value,
                'units': warehouse_units,
                'capacity_usage': warehouse.capacity_percentage
            })
            
            total_inventory_value += warehouse_value
            total_units += warehouse_units
        
        # Calculate by category
        category_valuations = []
        
        from products.models import Category
        categories = Category.objects.all()
        
        for category in categories:
            category_value = Decimal('0.00')
            category_units = 0
            
            stocks = WarehouseStock.objects.filter(
                product__category=category
            ).select_related('product')
            
            for stock in stocks:
                if stock.product.cost_price:
                    category_value += stock.quantity * stock.product.cost_price
                category_units += stock.quantity
            
            if category_value > 0:
                category_valuations.append({
                    'category': category.name,
                    'value': category_value,
                    'units': category_units
                })
        
        # Sort by value
        category_valuations.sort(key=lambda x: x['value'], reverse=True)
        
        # Calculate aging (slow-moving inventory)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        ninety_days_ago = timezone.now() - timedelta(days=90)
        
        slow_moving = WarehouseStock.objects.filter(
            product__orderitem__order__created_at__lt=ninety_days_ago
        ).distinct().count()
        
        # Send report
        subject = f"💰 Inventory Valuation Report - {today}"
        
        message = f"""
Daily Inventory Valuation Report for {today}

TOTAL INVENTORY VALUE: KSh {total_inventory_value:,.2f}
Total Units: {total_units:,}

By Warehouse:
{chr(10).join(f"  • {wh['warehouse']}: KSh {wh['value']:,.2f} ({wh['units']:,} units, {wh['capacity_usage']:.1f}% capacity)" for wh in warehouse_valuations)}

Top 5 Categories by Value:
{chr(10).join(f"  {i+1}. {cat['category']}: KSh {cat['value']:,.2f} ({cat['units']:,} units)" for i, cat in enumerate(category_valuations[:5]))}

Inventory Health:
  • Slow-Moving Items (>90 days): {slow_moving}
  
Best regards,
SoundWaveAudio Inventory Analytics
"""
        
        send_mail_to_admins(subject, message)
        
        report_data = {
            'date': today.isoformat(),
            'total_value': float(total_inventory_value),
            'total_units': total_units,
            'warehouses': warehouse_valuations,
            'categories': category_valuations[:5],
            'slow_moving_count': slow_moving
        }
        
        logger.info(f"Inventory valuation report generated: KSh {total_inventory_value:,.2f}")
        return report_data
    
    except Exception as exc:
        logger.error(f"Failed to generate valuation report: {exc}", exc_info=True)
        raise


@shared_task
def generate_reorder_recommendations():
    """
    Generate intelligent reorder recommendations.
    Analyzes stock levels, sales velocity, and lead times.
    Runs daily at 9 AM via Celery Beat.
    
    Returns:
        dict: Reorder recommendations
    """
    try:
        from customers.utils import send_mail_to_admins
        
        # Get products that need reordering
        reorder_needed = WarehouseStock.objects.filter(
            warehouse__is_active=True,
            quantity__lte=F('reorder_point'),
            reorder_quantity__gt=0
        ).select_related('warehouse', 'product', 'product__brand', 'product__category')
        
        recommendations = []
        total_reorder_cost = Decimal('0.00')
        
        for stock in reorder_needed:
            # Calculate daily sales rate (last 30 days)
            thirty_days_ago = timezone.now() - timedelta(days=30)
            
            recent_sales = StockMovement.objects.filter(
                warehouse=stock.warehouse,
                product=stock.product,
                movement_type='sale',
                created_at__gte=thirty_days_ago
            ).aggregate(total_sold=Sum('quantity'))['total_sold'] or 0
            
            daily_sales_rate = abs(recent_sales) / 30.0 if recent_sales else 0
            
            # Calculate days of stock remaining
            if daily_sales_rate > 0:
                days_remaining = stock.available_quantity / daily_sales_rate
            else:
                days_remaining = 999  # No recent sales
            
            # Calculate recommended order quantity
            # Order enough for 30 days + safety stock
            if daily_sales_rate > 0:
                recommended_qty = int((daily_sales_rate * 30) + stock.reorder_point)
            else:
                recommended_qty = stock.reorder_quantity
            
            # Ensure minimum reorder quantity
            recommended_qty = max(recommended_qty, stock.reorder_quantity)
            
            # Calculate cost
            if stock.product.cost_price:
                order_cost = recommended_qty * stock.product.cost_price
                total_reorder_cost += order_cost
            else:
                order_cost = Decimal('0.00')
            
            # Determine urgency
            if days_remaining < 7:
                urgency = 'CRITICAL'
                priority = 1
            elif days_remaining < 14:
                urgency = 'HIGH'
                priority = 2
            elif days_remaining < 30:
                urgency = 'MEDIUM'
                priority = 3
            else:
                urgency = 'LOW'
                priority = 4
            
            recommendations.append({
                'warehouse': stock.warehouse.name,
                'product': stock.product.name,
                'sku': stock.product.sku,
                'brand': stock.product.brand.name if stock.product.brand else 'N/A',
                'current_stock': stock.quantity,
                'available': stock.available_quantity,
                'daily_sales_rate': round(daily_sales_rate, 2),
                'days_remaining': round(days_remaining, 1),
                'recommended_qty': recommended_qty,
                'order_cost': float(order_cost),
                'urgency': urgency,
                'priority': priority
            })
        
        # Sort by priority
        recommendations.sort(key=lambda x: (x['priority'], x['days_remaining']))
        
        # Send report
        critical = [r for r in recommendations if r['urgency'] == 'CRITICAL']
        high = [r for r in recommendations if r['urgency'] == 'HIGH']
        
        subject = f"📦 Reorder Recommendations - {len(critical)} Critical"
        
        message = f"""
Inventory Reorder Recommendations

TOTAL REORDER COST: KSh {total_reorder_cost:,.2f}
Total Items Needing Reorder: {len(recommendations)}

CRITICAL (< 7 days stock):
{chr(10).join(f"  • {r['product']} ({r['sku']}) at {r['warehouse']}: {r['available']} units ({r['days_remaining']:.1f} days left) - Order {r['recommended_qty']} units (KSh {r['order_cost']:,.2f})" for r in critical[:10]) if critical else "  None"}

HIGH (7-14 days stock):
{chr(10).join(f"  • {r['product']} ({r['sku']}) at {r['warehouse']}: {r['available']} units ({r['days_remaining']:.1f} days left) - Order {r['recommended_qty']} units (KSh {r['order_cost']:,.2f})" for r in high[:10]) if high else "  None"}

MEDIUM Priority: {len([r for r in recommendations if r['urgency'] == 'MEDIUM'])}
LOW Priority: {len([r for r in recommendations if r['urgency'] == 'LOW'])}

Please review and place orders accordingly.

Best regards,
SoundWaveAudio Procurement System
"""
        
        send_mail_to_admins(subject, message)
        
        report_data = {
            'total_items': len(recommendations),
            'total_cost': float(total_reorder_cost),
            'critical_count': len(critical),
            'high_count': len(high),
            'recommendations': recommendations[:20]  # Top 20
        }
        
        logger.info(f"Reorder recommendations generated: {len(recommendations)} items")
        return report_data
    
    except Exception as exc:
        logger.error(f"Failed to generate reorder recommendations: {exc}", exc_info=True)
        raise


@shared_task
def analyze_stock_turnover():
    """
    Analyze inventory turnover rates and identify slow-moving items.
    Runs weekly via Celery Beat.
    
    Returns:
        dict: Turnover analysis
    """
    try:
        from customers.utils import send_mail_to_admins
        
        # Calculate turnover for last 90 days
        ninety_days_ago = timezone.now() - timedelta(days=90)
        
        products_with_stock = WarehouseStock.objects.filter(
            warehouse__is_active=True,
            quantity__gt=0
        ).values('product').distinct()
        
        slow_movers = []
        fast_movers = []
        no_movement = []
        
        for item in products_with_stock:
            product_id = item['product']
            
            try:
                product = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                continue
            
            # Calculate total sold in period
            total_sold = StockMovement.objects.filter(
                product=product,
                movement_type='sale',
                created_at__gte=ninety_days_ago
            ).aggregate(total=Sum('quantity'))['total'] or 0
            
            total_sold = abs(total_sold)
            
            # Get average inventory
            avg_inventory = WarehouseStock.objects.filter(
                product=product
            ).aggregate(total=Sum('quantity'))['total'] or 0
            
            # Calculate turnover rate
            if avg_inventory > 0 and total_sold > 0:
                turnover_rate = total_sold / avg_inventory
                days_to_sell = 90 / turnover_rate if turnover_rate > 0 else 999
                
                if days_to_sell > 180:  # Taking >6 months to sell
                    slow_movers.append({
                        'product': product.name,
                        'sku': product.sku,
                        'stock': avg_inventory,
                        'sold_90d': total_sold,
                        'turnover_rate': round(turnover_rate, 2),
                        'days_to_sell': round(days_to_sell, 1)
                    })
                elif days_to_sell < 30:  # Selling in <30 days
                    fast_movers.append({
                        'product': product.name,
                        'sku': product.sku,
                        'stock': avg_inventory,
                        'sold_90d': total_sold,
                        'turnover_rate': round(turnover_rate, 2),
                        'days_to_sell': round(days_to_sell, 1)
                    })
            elif avg_inventory > 0 and total_sold == 0:
                no_movement.append({
                    'product': product.name,
                    'sku': product.sku,
                    'stock': avg_inventory
                })
        
        # Sort
        slow_movers.sort(key=lambda x: x['days_to_sell'], reverse=True)
        fast_movers.sort(key=lambda x: x['turnover_rate'], reverse=True)
        
        # Send report
        subject = f"📊 Inventory Turnover Analysis - {len(slow_movers)} Slow Movers"
        
        message = f"""
Inventory Turnover Analysis (Last 90 Days)

SLOW MOVERS (>180 days to sell) - {len(slow_movers)} items:
{chr(10).join(f"  • {item['product']} ({item['sku']}): {item['stock']} units in stock, {item['sold_90d']} sold, {item['days_to_sell']:.0f} days to sell" for item in slow_movers[:15])}

NO MOVEMENT (0 sales) - {len(no_movement)} items:
{chr(10).join(f"  • {item['product']} ({item['sku']}): {item['stock']} units sitting idle" for item in no_movement[:10])}

FAST MOVERS (<30 days to sell) - {len(fast_movers)} items:
{chr(10).join(f"  • {item['product']} ({item['sku']}): Turnover {item['turnover_rate']}x, {item['days_to_sell']:.0f} days to sell" for item in fast_movers[:10])}

Recommendations:
  • Consider promotions/discounts for slow movers
  • Review pricing for items with no movement
  • Increase stock levels for fast movers
  • Discontinue products with consistent no movement

Best regards,
SoundWaveAudio Inventory Analytics
"""
        
        send_mail_to_admins(subject, message)
        
        analysis_data = {
            'slow_movers_count': len(slow_movers),
            'no_movement_count': len(no_movement),
            'fast_movers_count': len(fast_movers),
            'slow_movers': slow_movers[:20],
            'no_movement': no_movement[:20],
            'fast_movers': fast_movers[:10]
        }
        
        logger.info(f"Turnover analysis complete: {len(slow_movers)} slow movers found")
        return analysis_data
    
    except Exception as exc:
        logger.error(f"Failed to analyze stock turnover: {exc}", exc_info=True)
        raise


# ============================================================================
# MOVEMENT TRACKING & AUDIT TASKS
# ============================================================================

@shared_task
def detect_suspicious_movements():
    """
    Detect suspicious stock movements that may indicate theft or errors.
    Runs daily via Celery Beat.
    
    Returns:
        dict: Suspicious movements found
    """
    try:
        from customers.utils import send_mail_to_admins
        
        # Check movements from last 24 hours
        yesterday = timezone.now() - timedelta(hours=24)
        
        recent_movements = StockMovement.objects.filter(
            created_at__gte=yesterday
        ).select_related('warehouse', 'product', 'created_by')
        
        suspicious = []
        
        for movement in recent_movements:
            flags = []
            
            # Flag 1: Large quantity adjustments
            if movement.movement_type == 'adjustment' and abs(movement.quantity) > 50:
                flags.append(f"Large adjustment: {abs(movement.quantity)} units")
            
            # Flag 2: Multiple adjustments on same product
            same_product_adjustments = StockMovement.objects.filter(
                product=movement.product,
                warehouse=movement.warehouse,
                movement_type='adjustment',
                created_at__gte=yesterday
            ).count()
            
            if same_product_adjustments > 3:
                flags.append(f"Multiple adjustments: {same_product_adjustments} times")
            
            # Flag 3: Writeoff without approval
            if movement.movement_type == 'writeoff' and not movement.approved_by:
                flags.append("Writeoff without approval")
            
            # Flag 4: Lost/damaged with high value
            if movement.movement_type in ['lost', 'damaged']:
                if movement.product.cost_price:
                    value = abs(movement.quantity) * movement.product.cost_price
                    if value > 10000:  # >10,000 KSh
                        flags.append(f"High value loss: KSh {value:,.2f}")
            
            # Flag 5: After-hours movements
            movement_hour = movement.created_at.hour
            if movement_hour < 6 or movement_hour > 22:
                flags.append(f"After-hours activity: {movement.created_at.strftime('%H:%M')}")
            
            if flags:
                suspicious.append({
                    'movement_number': movement.movement_number,
                    'warehouse': movement.warehouse.name if movement.warehouse else 'N/A',
                    'product': movement.product.name,
                    'sku': movement.product.sku,
                    'type': movement.get_movement_type_display(),
                    'quantity': movement.quantity,
                    'created_by': movement.created_by.get_full_name() if movement.created_by else 'Unknown',
                    'created_at': movement.created_at.strftime('%Y-%m-%d %H:%M'),
                    'flags': flags
                })
        
        if suspicious:
            subject = f"🚨 Suspicious Inventory Movements - {len(suspicious)} Flagged"
            
            message = f"""
Suspicious Inventory Movement Alert

{len(suspicious)} movements have been flagged for review:

{chr(10).join(f'''
Movement: {item['movement_number']}
Product: {item['product']} ({item['sku']})
Warehouse: {item['warehouse']}
Type: {item['type']}
Quantity: {item['quantity']}
User: {item['created_by']}
Time: {item['created_at']}
Flags: {', '.join(item['flags'])}
---''' for item in suspicious[:20])}

Please investigate these movements immediately.

Best regards,
SoundWaveAudio Security System
"""
            
            send_mail_to_admins(subject, message)
        
        logger.info(f"Suspicious movement detection: {len(suspicious)} flagged")
        return {'suspicious_count': len(suspicious), 'movements': suspicious}
    
    except Exception as exc:
        logger.error(f"Failed to detect suspicious movements: {exc}", exc_info=True)
        raise


@shared_task
def generate_movement_audit_report():
    """
    Generate comprehensive movement audit report.
    Runs weekly via Celery Beat.
    
    Returns:
        dict: Audit report data
    """
    try:
        from customers.utils import send_mail_to_admins
        
        # Analyze movements from last 7 days
        seven_days_ago = timezone.now() - timedelta(days=7)
        
        movements = StockMovement.objects.filter(
            created_at__gte=seven_days_ago
        )
        
        # Summary by type
        by_type = movements.values('movement_type').annotate(
            count=Count('id'),
            total_quantity=Sum('quantity')
        ).order_by('-count')
        
        # Summary by warehouse
        by_warehouse = movements.values(
            'warehouse__name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Summary by user
        by_user = movements.values(
            'created_by__first_name',
            'created_by__last_name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        # Most active products
        active_products = movements.values(
            'product__name',
            'product__sku'
        ).annotate(
            movement_count=Count('id')
        ).order_by('-movement_count')[:10]
        
        # Cost tracking
        movements_with_cost = movements.exclude(total_cost__isnull=True)
        total_value_moved = movements_with_cost.aggregate(
            total=Sum('total_cost')
        )['total'] or Decimal('0.00')
        
        subject = f"📋 Weekly Movement Audit Report"
        
        message = f"""
Inventory Movement Audit Report (Last 7 Days)

SUMMARY:
  • Total Movements: {movements.count()}
  • Total Value Tracked: KSh {total_value_moved:,.2f}

By Movement Type:
{chr(10).join(f"  • {item['movement_type']}: {item['count']} movements" for item in by_type)}

By Warehouse:
{chr(10).join(f"  • {item['warehouse__name'] or 'N/A'}: {item['count']} movements" for item in by_warehouse)}

Top 10 Most Active Products:
{chr(10).join(f"  {i+1}. {item['product__name']} ({item['product__sku']}): {item['movement_count']} movements" for i, item in enumerate(active_products))}

Top 10 Users by Activity:
{chr(10).join(f"  {i+1}. {item['created_by__first_name']} {item['created_by__last_name']}: {item['count']} movements" for i, item in enumerate(by_user))}

Best regards,
SoundWaveAudio Audit System
"""
        
        send_mail_to_admins(subject, message)
        
        report_data = {
            'total_movements': movements.count(),
            'total_value': float(total_value_moved),
            'by_type': list(by_type),
            'by_warehouse': list(by_warehouse),
            'active_products': list(active_products)
        }
        
        logger.info(f"Movement audit report generated: {movements.count()} movements")
        return report_data
    
    except Exception as exc:
        logger.error(f"Failed to generate audit report: {exc}", exc_info=True)
        raise


# ============================================================================
# DATA CLEANUP & MAINTENANCE TASKS
# ============================================================================

@shared_task
def cleanup_old_resolved_alerts():
    """
    Clean up old resolved alerts (keep last 90 days).
    Runs monthly via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        ninety_days_ago = timezone.now() - timedelta(days=90)
        
        old_alerts = StockAlert.objects.filter(
            is_resolved=True,
            resolved_at__lt=ninety_days_ago
        )
        
        deleted_count = old_alerts.count()
        old_alerts.delete()
        
        logger.info(f"Cleaned up {deleted_count} old resolved alerts")
        return f"Cleaned up {deleted_count} old alerts"
    
    except Exception as exc:
        logger.error(f"Failed to cleanup old alerts: {exc}", exc_info=True)
        raise


@shared_task
def sync_product_stock_from_warehouses():
    """
    Sync product stock_quantity from warehouse stocks.
    Runs every 6 hours via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        products = Product.objects.all()
        updated_count = 0
        
        for product in products:
            # Calculate total across all warehouses
            total_stock = WarehouseStock.objects.filter(
                product=product
            ).aggregate(total=Sum('quantity'))['total'] or 0
            
            if product.stock_quantity != total_stock:
                product.stock_quantity = total_stock
                product.save(update_fields=['stock_quantity'])
                updated_count += 1
        
        logger.info(f"Synced stock for {updated_count} products")
        return f"Synced {updated_count} products"
    
    except Exception as exc:
        logger.error(f"Failed to sync product stock: {exc}", exc_info=True)
        raise


# ============================================================================
# SCHEDULED TASK CONFIGURATIONS
# ============================================================================

"""
Add these to your Celery Beat schedule in settings.py:

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Stock monitoring every 30 minutes
    'monitor-stock-levels': {
        'task': 'inventory.tasks.monitor_stock_levels',
        'schedule': crontab(minute='*/30'),
    },
    
    # Check damaged stock daily at 9 AM
    'check-damaged-stock': {
        'task': 'inventory.tasks.check_damaged_stock',
        'schedule': crontab(hour=9, minute=0),
    },
    
    # Monitor warehouse capacity every 6 hours
    'monitor-warehouse-capacity': {
        'task': 'inventory.tasks.monitor_warehouse_capacity',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    
    # Monitor pending transfers every 2 hours
    'monitor-pending-transfers': {
        'task': 'inventory.tasks.monitor_pending_transfers',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    
    # Schedule stock counts weekly on Monday
    'schedule-automatic-stock-counts': {
        'task': 'inventory.tasks.schedule_automatic_stock_counts',
        'schedule': crontab(day_of_week=1, hour=8, minute=0),
    },
    
    # Analyze stock count discrepancies weekly on Sunday
    'analyze-stock-count-discrepancies': {
        'task': 'inventory.tasks.analyze_stock_count_discrepancies',
        'schedule': crontab(day_of_week=0, hour=10, minute=0),
    },
    
    # Generate inventory valuation daily at 11 PM
    'generate-inventory-valuation-report': {
        'task': 'inventory.tasks.generate_inventory_valuation_report',
        'schedule': crontab(hour=23, minute=0),
    },
    
    # Generate reorder recommendations daily at 9 AM
    'generate-reorder-recommendations': {
        'task': 'inventory.tasks.generate_reorder_recommendations',
        'schedule': crontab(hour=9, minute=0),
    },
    
    # Analyze stock turnover weekly on Sunday at 11 AM
    'analyze-stock-turnover': {
        'task': 'inventory.tasks.analyze_stock_turnover',
        'schedule': crontab(day_of_week=0, hour=11, minute=0),
    },
    
    # Detect suspicious movements daily at 8 AM
    'detect-suspicious-movements': {
        'task': 'inventory.tasks.detect_suspicious_movements',
        'schedule': crontab(hour=8, minute=0),
    },
    
    # Generate movement audit report weekly on Monday at 10 AM
    'generate-movement-audit-report': {
        'task': 'inventory.tasks.generate_movement_audit_report',
        'schedule': crontab(day_of_week=1, hour=10, minute=0),
    },
    
    # Cleanup old alerts monthly on 1st at 3 AM
    'cleanup-old-resolved-alerts': {
        'task': 'inventory.tasks.cleanup_old_resolved_alerts',
        'schedule': crontab(day_of_month=1, hour=3, minute=0),
    },
    
    # Sync product stock every 6 hours
    'sync-product-stock-from-warehouses': {
        'task': 'inventory.tasks.sync_product_stock_from_warehouses',
        'schedule': crontab(minute=0, hour='*/6'),
    },
}
"""