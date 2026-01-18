"""
God-Level Celery Tasks for M-Pesa Payments
Handles all asynchronous operations for payment processing
"""
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Count, Q
from datetime import timedelta
from decimal import Decimal
import logging

from .models import (
    MpesaTransaction, MpesaCallback, MpesaRefund,
    MpesaConfiguration, MpesaAccessToken
)
from .services import MpesaCallbackProcessor, MpesaAPIClient, MpesaPaymentService
from orders.models import Order

logger = logging.getLogger(__name__)


# ============================================================================
# CALLBACK PROCESSING TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_mpesa_callback_task(self, callback_data, ip_address=None):
    """
    Process M-Pesa callback asynchronously with retry logic.
    
    Args:
        callback_data: Callback payload from M-Pesa
        ip_address: IP address of callback request
    
    Returns:
        dict: Processing result
    """
    logger.info(f"🔵 Processing M-Pesa callback asynchronously")
    
    try:
        success = MpesaCallbackProcessor.process_stk_callback(
            callback_data,
            ip_address
        )
        
        if not success:
            logger.error(f"Callback processing failed: {callback_data}")
            # Retry with exponential backoff
            raise self.retry(countdown=30 * (2 ** self.request.retries))
        
        logger.info(f"✅ Callback processed successfully")
        return {'status': 'success', 'message': 'Callback processed'}
    
    except Exception as exc:
        logger.error(f"❌ Callback task error: {str(exc)}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ============================================================================
# EMAIL NOTIFICATION TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_confirmation_email(self, transaction_id):
    """
    Send payment confirmation email to customer.
    
    Args:
        transaction_id: ID of the transaction
    
    Returns:
        str: Success message
    """
    try:
        transaction = MpesaTransaction.objects.select_related(
            'order__customer__user', 'customer__user'
        ).get(id=transaction_id)
        
        # Determine recipient
        if transaction.order and transaction.order.customer:
            customer = transaction.order.customer
            recipient_email = customer.user.email
            recipient_name = customer.user.get_full_name() or customer.user.first_name
        elif transaction.customer:
            customer = transaction.customer
            recipient_email = customer.user.email
            recipient_name = customer.user.get_full_name() or customer.user.first_name
        else:
            logger.warning(f"No customer found for transaction {transaction_id}")
            return "No customer email available"
        
        # Prepare context
        context = {
            'transaction': transaction,
            'customer_name': recipient_name,
            'order': transaction.order,
            'site_name': 'SoundWaveAudio',
            'site_url': getattr(settings, 'FRONTEND_URL', 'https://soundwaveaudio.com'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@soundwaveaudio.com'),
        }
        
        # Render email templates
        subject = f'Payment Confirmation - {transaction.mpesa_receipt_number}'
        html_message = render_to_string('payments/payment_confirmation.html', context)
        plain_message = f"""
Dear {recipient_name},

Your payment has been received successfully!

Payment Details:
- M-Pesa Receipt: {transaction.mpesa_receipt_number}
- Amount: KSh {transaction.amount:,.2f}
- Phone: {transaction.phone_number}
- Date: {transaction.transaction_date.strftime('%B %d, %Y at %I:%M %p') if transaction.transaction_date else 'N/A'}

{f'Order Number: {transaction.order.order_number}' if transaction.order else ''}

Thank you for your payment!

Best regards,
SoundWaveAudio Team
"""
        
        # Send email
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwaveaudio.com'),
            to=[recipient_email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        logger.info(f"✅ Payment confirmation email sent to {recipient_email}")
        return f"Confirmation email sent to {recipient_email}"
    
    except MpesaTransaction.DoesNotExist:
        logger.error(f"Transaction {transaction_id} not found")
        raise
    
    except Exception as exc:
        logger.error(f"Failed to send payment confirmation: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_payment_failed_notification(self, transaction_id):
    """
    Send payment failure notification to customer.
    
    Args:
        transaction_id: ID of the failed transaction
    
    Returns:
        str: Success message
    """
    try:
        transaction = MpesaTransaction.objects.select_related(
            'order__customer__user', 'customer__user'
        ).get(id=transaction_id)
        
        # Determine recipient
        if transaction.order and transaction.order.customer:
            customer = transaction.order.customer
            recipient_email = customer.user.email
            recipient_name = customer.user.get_full_name() or customer.user.first_name
        elif transaction.customer:
            customer = transaction.customer
            recipient_email = customer.user.email
            recipient_name = customer.user.get_full_name() or customer.user.first_name
        else:
            return "No customer email available"
        
        # Prepare context
        context = {
            'transaction': transaction,
            'customer_name': recipient_name,
            'order': transaction.order,
            'site_name': 'SoundWaveAudio',
            'site_url': getattr(settings, 'FRONTEND_URL', 'https://soundwaveaudio.com'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@soundwaveaudio.com'),
        }
        
        subject = f'Payment Failed - {transaction.order.order_number if transaction.order else "Transaction"}'
        html_message = render_to_string('payments/payment_failed.html', context)
        plain_message = f"""
Dear {recipient_name},

We were unable to process your payment.

Payment Details:
- Amount: KSh {transaction.amount:,.2f}
- Phone: {transaction.phone_number}
- Status: {transaction.get_status_display()}
- Reason: {transaction.result_desc or 'Payment was not completed'}

{f'Order Number: {transaction.order.order_number}' if transaction.order else ''}

Please try again or contact support if the problem persists.

Best regards,
SoundWaveAudio Team
"""
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwaveaudio.com'),
            to=[recipient_email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        logger.info(f"✅ Payment failure notification sent to {recipient_email}")
        return f"Failure notification sent to {recipient_email}"
    
    except MpesaTransaction.DoesNotExist:
        logger.error(f"Transaction {transaction_id} not found")
        raise
    
    except Exception as exc:
        logger.error(f"Failed to send payment failure notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_refund_notification(self, refund_id):
    """
    Send refund notification to customer.
    
    Args:
        refund_id: ID of the refund
    
    Returns:
        str: Success message
    """
    try:
        refund = MpesaRefund.objects.select_related(
            'original_transaction__order__customer__user',
            'original_transaction__customer__user'
        ).get(id=refund_id)
        
        transaction = refund.original_transaction
        
        # Determine recipient
        if transaction.order and transaction.order.customer:
            customer = transaction.order.customer
            recipient_email = customer.user.email
            recipient_name = customer.user.get_full_name() or customer.user.first_name
        elif transaction.customer:
            customer = transaction.customer
            recipient_email = customer.user.email
            recipient_name = customer.user.get_full_name() or customer.user.first_name
        else:
            return "No customer email available"
        
        context = {
            'refund': refund,
            'transaction': transaction,
            'customer_name': recipient_name,
            'site_name': 'SoundWaveAudio',
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@soundwaveaudio.com'),
        }
        
        subject = f'Refund Processed - KSh {refund.amount:,.2f}'
        html_message = render_to_string('payments/refund_notification.html', context)
        plain_message = f"""
Dear {recipient_name},

Your refund has been processed successfully.

Refund Details:
- Amount: KSh {refund.amount:,.2f}
- Original Receipt: {transaction.mpesa_receipt_number}
- Reason: {refund.reason}
- Status: {refund.get_status_display()}

The refund should appear in your M-Pesa account within 24-48 hours.

Best regards,
SoundWaveAudio Team
"""
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwaveaudio.com'),
            to=[recipient_email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        logger.info(f"✅ Refund notification sent to {recipient_email}")
        return f"Refund notification sent to {recipient_email}"
    
    except MpesaRefund.DoesNotExist:
        logger.error(f"Refund {refund_id} not found")
        raise
    
    except Exception as exc:
        logger.error(f"Failed to send refund notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


# ============================================================================
# TRANSACTION MONITORING TASKS
# ============================================================================

@shared_task
def check_pending_transactions():
    """
    Check status of pending M-Pesa transactions.
    Runs every 5 minutes via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Get transactions pending for more than 5 minutes
        cutoff_time = timezone.now() - timedelta(minutes=5)
        
        pending_transactions = MpesaTransaction.objects.filter(
            status='processing',
            initiated_at__lte=cutoff_time
        ).exclude(
            checkout_request_id=''
        )
        
        checked_count = 0
        updated_count = 0
        
        service = MpesaPaymentService()
        
        for transaction in pending_transactions:
            try:
                checked_count += 1
                
                # Query M-Pesa for status
                updated_transaction = service.check_payment_status(
                    transaction.checkout_request_id
                )
                
                if updated_transaction and updated_transaction.status != 'processing':
                    updated_count += 1
                    
                    # Send appropriate notification
                    if updated_transaction.status == 'completed':
                        send_payment_confirmation_email.delay(updated_transaction.id)
                    elif updated_transaction.status in ['failed', 'cancelled', 'timeout']:
                        send_payment_failed_notification.delay(updated_transaction.id)
                
            except Exception as trans_exc:
                logger.error(
                    f"Error checking transaction {transaction.id}: {str(trans_exc)}"
                )
                continue
        
        logger.info(
            f"Checked {checked_count} pending transactions, "
            f"updated {updated_count}"
        )
        
        return f"Checked {checked_count} transactions, updated {updated_count}"
    
    except Exception as exc:
        logger.error(f"Failed to check pending transactions: {exc}", exc_info=True)
        raise


@shared_task
def auto_timeout_stuck_transactions():
    """
    Automatically timeout transactions stuck in processing for more than 2 hours.
    Runs hourly via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Get transactions stuck for more than 2 hours
        cutoff_time = timezone.now() - timedelta(hours=2)
        
        stuck_transactions = MpesaTransaction.objects.filter(
            status='processing',
            initiated_at__lte=cutoff_time
        )
        
        timeout_count = 0
        
        for transaction in stuck_transactions:
            transaction.status = 'timeout'
            transaction.result_desc = 'Transaction timed out - no response from M-Pesa'
            transaction.failed_at = timezone.now()
            transaction.save()
            
            # Send failure notification
            send_payment_failed_notification.delay(transaction.id)
            
            # Alert admin
            send_admin_payment_alert.delay(
                transaction.id,
                'Transaction Timeout',
                f"Transaction {transaction.checkout_request_id} timed out after 2 hours"
            )
            
            timeout_count += 1
        
        logger.info(f"Timed out {timeout_count} stuck transactions")
        return f"Timed out {timeout_count} transactions"
    
    except Exception as exc:
        logger.error(f"Failed to timeout stuck transactions: {exc}", exc_info=True)
        raise


@shared_task
def monitor_failed_payments():
    """
    Monitor failed payments and alert admins for high failure rates.
    Runs every hour via Celery Beat.
    
    Returns:
        str: Success message
    """
    try:
        # Get last hour's transactions
        one_hour_ago = timezone.now() - timedelta(hours=1)
        
        recent_transactions = MpesaTransaction.objects.filter(
            initiated_at__gte=one_hour_ago
        )
        
        total_count = recent_transactions.count()
        
        if total_count == 0:
            return "No transactions in the last hour"
        
        failed_count = recent_transactions.filter(
            status__in=['failed', 'cancelled', 'timeout']
        ).count()
        
        failure_rate = (failed_count / total_count) * 100
        
        # Alert if failure rate > 20%
        if failure_rate > 20:
            send_admin_payment_alert.delay(
                None,
                'High Payment Failure Rate',
                f"Payment failure rate is {failure_rate:.1f}% "
                f"({failed_count}/{total_count} transactions failed in the last hour)"
            )
            
            logger.warning(f"High failure rate detected: {failure_rate:.1f}%")
        
        logger.info(
            f"Payment monitoring: {total_count} transactions, "
            f"{failed_count} failed ({failure_rate:.1f}%)"
        )
        
        return f"Monitored {total_count} transactions, {failure_rate:.1f}% failure rate"
    
    except Exception as exc:
        logger.error(f"Failed to monitor payments: {exc}", exc_info=True)
        raise


# ============================================================================
# ADMIN NOTIFICATION TASKS
# ============================================================================

@shared_task
def send_admin_payment_alert(transaction_id, alert_type, message):
    """
    Send payment alert to admin users.
    
    Args:
        transaction_id: ID of the transaction (can be None)
        alert_type: Type of alert
        message: Alert message
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        transaction_info = ""
        if transaction_id:
            try:
                transaction = MpesaTransaction.objects.get(id=transaction_id)
                transaction_info = f"""
Transaction Details:
- ID: {transaction.transaction_id}
- Checkout Request: {transaction.checkout_request_id}
- Amount: KSh {transaction.amount:,.2f}
- Phone: {transaction.phone_number}
- Status: {transaction.get_status_display()}
- Order: {transaction.order.order_number if transaction.order else 'N/A'}
"""
            except MpesaTransaction.DoesNotExist:
                pass
        
        subject = f"🚨 M-Pesa Alert: {alert_type}"
        full_message = f"""
{message}

{transaction_info}

Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}

Best regards,
SoundWaveAudio Payment System
"""
        
        send_mail_to_admins(subject, full_message)
        
        logger.info(f"Admin alert sent: {alert_type}")
        return f"Admin alert sent: {alert_type}"
    
    except Exception as exc:
        logger.error(f"Failed to send admin alert: {exc}", exc_info=True)
        raise


# ============================================================================
# RECONCILIATION TASKS
# ============================================================================

@shared_task
def reconcile_daily_transactions():
    """
    Reconcile daily M-Pesa transactions.
    Generates report of all transactions for the day.
    Runs daily at 11:30 PM via Celery Beat.
    
    Returns:
        dict: Reconciliation report
    """
    try:
        today = timezone.now().date()
        
        # Get today's transactions
        transactions = MpesaTransaction.objects.filter(
            initiated_at__date=today
        )
        
        # Calculate metrics
        total_transactions = transactions.count()
        successful = transactions.filter(status='completed', result_code=0).count()
        failed = transactions.filter(status='failed').count()
        pending = transactions.filter(status__in=['pending', 'processing']).count()
        cancelled = transactions.filter(status__in=['cancelled', 'timeout']).count()
        
        total_amount = transactions.filter(
            status='completed', result_code=0
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        # Get refunds
        refunds = MpesaRefund.objects.filter(initiated_at__date=today)
        total_refunds = refunds.count()
        refund_amount = refunds.filter(
            status='completed'
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        report = {
            'date': today.isoformat(),
            'transactions': {
                'total': total_transactions,
                'successful': successful,
                'failed': failed,
                'pending': pending,
                'cancelled': cancelled,
            },
            'amounts': {
                'gross_revenue': float(total_amount),
                'refunds': float(refund_amount),
                'net_revenue': float(total_amount - refund_amount),
            },
            'success_rate': (successful / total_transactions * 100) if total_transactions > 0 else 0,
        }
        
        # Send report to admins
        from customers.utils import send_mail_to_admins
        
        subject = f"M-Pesa Daily Reconciliation - {today}"
        message = f"""
M-Pesa Reconciliation Report for {today}

Transactions Summary:
- Total: {total_transactions}
- Successful: {successful}
- Failed: {failed}
- Pending: {pending}
- Cancelled/Timeout: {cancelled}

Financial Summary:
- Gross Revenue: KSh {total_amount:,.2f}
- Refunds: KSh {refund_amount:,.2f}
- Net Revenue: KSh {(total_amount - refund_amount):,.2f}

Success Rate: {report['success_rate']:.1f}%

Best regards,
SoundWaveAudio Payment System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Daily reconciliation completed for {today}")
        return report
    
    except Exception as exc:
        logger.error(f"Failed to reconcile transactions: {exc}", exc_info=True)
        raise


@shared_task
def cleanup_old_callbacks():
    """
    Clean up old callback logs.
    Keeps last 90 days only.
    Runs weekly via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=90)
        
        deleted_callbacks = MpesaCallback.objects.filter(
            received_at__lt=cutoff_date,
            is_processed=True
        ).delete()
        
        logger.info(f"Cleaned up {deleted_callbacks[0]} old callbacks")
        return f"Cleaned up {deleted_callbacks[0]} callbacks"
    
    except Exception as exc:
        logger.error(f"Failed to cleanup callbacks: {exc}", exc_info=True)
        raise


# ============================================================================
# TOKEN MANAGEMENT TASKS
# ============================================================================

@shared_task
def refresh_mpesa_access_tokens():
    """
    Refresh M-Pesa access tokens for all active configurations.
    Runs every 50 minutes to ensure tokens don't expire.
    
    Returns:
        str: Success message
    """
    try:
        active_configs = MpesaConfiguration.objects.filter(is_active=True)
        
        refreshed_count = 0
        
        for config in active_configs:
            try:
                client = MpesaAPIClient(configuration=config)
                token = client.get_access_token()
                
                if token:
                    refreshed_count += 1
                    logger.info(f"Token refreshed for {config.name}")
            
            except Exception as config_exc:
                logger.error(f"Failed to refresh token for {config.name}: {str(config_exc)}")
                continue
        
        logger.info(f"Refreshed {refreshed_count} M-Pesa access tokens")
        return f"Refreshed {refreshed_count} tokens"
    
    except Exception as exc:
        logger.error(f"Failed to refresh access tokens: {exc}", exc_info=True)
        raise


# ============================================================================
# SCHEDULED TASK CONFIGURATIONS
# ============================================================================

"""
Add these to your Celery Beat schedule in settings.py:

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Check pending transactions every 5 minutes
    'check-pending-mpesa-transactions': {
        'task': 'payments.tasks.check_pending_transactions',
        'schedule': crontab(minute='*/5'),
    },
    
    # Auto-timeout stuck transactions every hour
    'auto-timeout-stuck-transactions': {
        'task': 'payments.tasks.auto_timeout_stuck_transactions',
        'schedule': crontab(minute=0),
    },
    
    # Monitor failed payments every hour
    'monitor-failed-payments': {
        'task': 'payments.tasks.monitor_failed_payments',
        'schedule': crontab(minute=30),
    },
    
    # Daily reconciliation at 11:30 PM
    'reconcile-daily-mpesa-transactions': {
        'task': 'payments.tasks.reconcile_daily_transactions',
        'schedule': crontab(hour=23, minute=30),
    },
    
    # Cleanup old callbacks weekly on Sunday at 2 AM
    'cleanup-old-mpesa-callbacks': {
        'task': 'payments.tasks.cleanup_old_callbacks',
        'schedule': crontab(day_of_week=0, hour=2, minute=0),
    },
    
    # Refresh access tokens every 50 minutes
    'refresh-mpesa-access-tokens': {
        'task': 'payments.tasks.refresh_mpesa_access_tokens',
        'schedule': crontab(minute='*/50'),
    },
}
"""