"""
Celery configuration for backend project.
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

app = Celery('backend')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


# ============================================================================
# CONSOLIDATED CELERY BEAT SCHEDULE FOR ALL APPS
# ============================================================================

app.conf.beat_schedule = {
    # ============================================================================
    # CUSTOMERS APP SCHEDULES
    # ============================================================================
    'cleanup-expired-reset-codes': {
        'task': 'customers.tasks.cleanup_expired_reset_codes',
        'schedule': crontab(hour=0, minute=0),  # Daily at midnight
    },
    'generate-customer-report': {
        'task': 'customers.tasks.generate_customer_report',
        'schedule': crontab(day_of_week=1, hour=9, minute=0),  # Every Monday at 9 AM
    },
    'check-inactive-customers': {
        'task': 'customers.tasks.check_inactive_customers',
        'schedule': crontab(day_of_week=0, hour=10, minute=0),  # Every Sunday at 10 AM
    },
    'analyze-customer-engagement': {
        'task': 'customers.tasks.analyze_customer_engagement',
        'schedule': crontab(day_of_month=1, hour=8, minute=0),  # First day of month at 8 AM
    },
    
    # ============================================================================
    # INVENTORY APP SCHEDULES
    # ============================================================================
    'monitor-stock-levels': {
        'task': 'inventory.tasks.monitor_stock_levels',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
    },
    'check-damaged-stock': {
        'task': 'inventory.tasks.check_damaged_stock',
        'schedule': crontab(hour=9, minute=0),  # Daily at 9 AM
    },
    'monitor-warehouse-capacity': {
        'task': 'inventory.tasks.monitor_warehouse_capacity',
        'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    },
    'monitor-pending-transfers': {
        'task': 'inventory.tasks.monitor_pending_transfers',
        'schedule': crontab(minute=0, hour='*/2'),  # Every 2 hours
    },
    'schedule-automatic-stock-counts': {
        'task': 'inventory.tasks.schedule_automatic_stock_counts',
        'schedule': crontab(day_of_week=1, hour=8, minute=0),  # Every Monday at 8 AM
    },
    'analyze-stock-count-discrepancies': {
        'task': 'inventory.tasks.analyze_stock_count_discrepancies',
        'schedule': crontab(day_of_week=0, hour=10, minute=0),  # Every Sunday at 10 AM
    },
    'generate-inventory-valuation-report': {
        'task': 'inventory.tasks.generate_inventory_valuation_report',
        'schedule': crontab(hour=23, minute=0),  # Daily at 11 PM
    },
    'generate-reorder-recommendations': {
        'task': 'inventory.tasks.generate_reorder_recommendations',
        'schedule': crontab(hour=9, minute=0),  # Daily at 9 AM
    },
    'analyze-stock-turnover': {
        'task': 'inventory.tasks.analyze_stock_turnover',
        'schedule': crontab(day_of_week=0, hour=11, minute=0),  # Every Sunday at 11 AM
    },
    'detect-suspicious-movements': {
        'task': 'inventory.tasks.detect_suspicious_movements',
        'schedule': crontab(hour=8, minute=0),  # Daily at 8 AM
    },
    'generate-movement-audit-report': {
        'task': 'inventory.tasks.generate_movement_audit_report',
        'schedule': crontab(day_of_week=1, hour=10, minute=0),  # Every Monday at 10 AM
    },
    'cleanup-old-resolved-alerts': {
        'task': 'inventory.tasks.cleanup_old_resolved_alerts',
        'schedule': crontab(day_of_month=1, hour=3, minute=0),  # Monthly on 1st at 3 AM
    },
    'sync-product-stock-from-warehouses': {
        'task': 'inventory.tasks.sync_product_stock_from_warehouses',
        'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    },
    
    # ============================================================================
    # ORDERS APP SCHEDULES
    # ============================================================================
    'auto-confirm-paid-orders': {
        'task': 'orders.tasks.auto_confirm_paid_orders',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'auto-cancel-unpaid-orders': {
        'task': 'orders.tasks.auto_cancel_unpaid_orders',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
    'check-delayed-orders': {
        'task': 'orders.tasks.check_delayed_orders',
        'schedule': crontab(hour=9, minute=0),  # Daily at 9 AM
    },
    'check-pending-orders': {
        'task': 'orders.tasks.check_pending_orders',
        'schedule': crontab(minute=0),  # Every hour
    },
    'sync-tracking-updates': {
        'task': 'orders.tasks.sync_tracking_updates',
        'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
    },
    'generate-daily-order-report': {
        'task': 'orders.tasks.generate_daily_order_report',
        'schedule': crontab(hour=23, minute=0),  # Daily at 11 PM
    },
    'cleanup-old-order-data': {
        'task': 'orders.tasks.cleanup_old_order_data',
        'schedule': crontab(day_of_week=0, hour=3, minute=0),  # Every Sunday at 3 AM
    },
    
    # ============================================================================
    # PAYMENTS APP SCHEDULES
    # ============================================================================
    'check-pending-mpesa-transactions': {
        'task': 'payments.tasks.check_pending_transactions',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'auto-timeout-stuck-transactions': {
        'task': 'payments.tasks.auto_timeout_stuck_transactions',
        'schedule': crontab(minute=0),  # Every hour
    },
    'monitor-failed-payments': {
        'task': 'payments.tasks.monitor_failed_payments',
        'schedule': crontab(minute=30),  # Every hour at minute 30
    },
    'reconcile-daily-mpesa-transactions': {
        'task': 'payments.tasks.reconcile_daily_transactions',
        'schedule': crontab(hour=23, minute=30),  # Daily at 11:30 PM
    },
    'cleanup-old-mpesa-callbacks': {
        'task': 'payments.tasks.cleanup_old_callbacks',
        'schedule': crontab(day_of_week=0, hour=2, minute=0),  # Every Sunday at 2 AM
    },
    'refresh-mpesa-access-tokens': {
        'task': 'payments.tasks.refresh_mpesa_access_tokens',
        'schedule': crontab(minute='*/50'),  # Every 50 minutes
    },
    
    # ============================================================================
    # PRODUCTS APP SCHEDULES
    # ============================================================================
    'check-low-stock-products': {
        'task': 'products.tasks.check_low_stock_products',
        'schedule': crontab(minute=0),  # Every hour
    },
    'check-out-of-stock-products': {
        'task': 'products.tasks.check_out_of_stock_products',
        'schedule': crontab(minute=0, hour='*/2'),  # Every 2 hours
    },
    'auto-deactivate-out-of-stock': {
        'task': 'products.tasks.auto_deactivate_out_of_stock_products',
        'schedule': crontab(day_of_week=1, hour=3, minute=0),  # Every Monday at 3 AM
    },
    'auto-approve-verified-reviews': {
        'task': 'products.tasks.auto_approve_verified_reviews',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
    'cleanup-spam-reviews': {
        'task': 'products.tasks.cleanup_spam_reviews',
        'schedule': crontab(day_of_week=0, hour=3, minute=0),  # Every Sunday at 3 AM
    },
    'generate-product-performance-report': {
        'task': 'products.tasks.generate_product_performance_report',
        'schedule': crontab(hour=23, minute=0),  # Daily at 11 PM
    },
    'update-product-popularity-scores': {
        'task': 'products.tasks.update_product_popularity_scores',
        'schedule': crontab(hour=4, minute=0),  # Daily at 4 AM
    },
    'check-pricing-anomalies': {
        'task': 'products.tasks.check_pricing_anomalies',
        'schedule': crontab(hour=9, minute=0),  # Daily at 9 AM
    },
    'cleanup-orphaned-product-images': {
        'task': 'products.tasks.cleanup_orphaned_product_images',
        'schedule': crontab(day_of_week=0, hour=4, minute=0),  # Every Sunday at 4 AM
    },
}

# Celery configuration
app.conf.update(
    # Task result backend
    result_backend='redis://127.0.0.1:6380/3',
    
    # Task serialization
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task execution settings
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes hard limit
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    
    # Worker settings
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    
    # Result expiration
    result_expires=3600,  # 1 hour
    
    # Task routing by app queues
    task_routes={
        'customers.tasks.*': {'queue': 'customers'},
        'orders.tasks.*': {'queue': 'orders'},
        'payments.tasks.*': {'queue': 'payments'},
        'inventory.tasks.*': {'queue': 'inventory'},
        'products.tasks.*': {'queue': 'products'},
    },
)


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery is working"""
    print(f'Request: {self.request!r}')