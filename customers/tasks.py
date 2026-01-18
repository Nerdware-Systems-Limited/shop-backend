"""
Celery tasks for the customers app.
Handles asynchronous email sending and background jobs.
"""
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Avg, Count, Sum
from datetime import timedelta
from .models import Customer, PasswordResetCode
from .utils import (
    send_password_reset_email,
    send_welcome_email_html,
    send_loyalty_points_email,
    send_reengagement_email,
    send_customer_report_to_admins,
)
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# EMAIL TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_welcome_email(self, user_id):
    """
    Send welcome email to newly registered user.
    Uses retry mechanism for reliability with exponential backoff.
    
    Args:
        user_id: ID of the user to send welcome email to
    
    Returns:
        str: Success message
    """
    try:
        user = User.objects.get(id=user_id)
        
        # Add welcome bonus loyalty points
        if hasattr(user, 'customer'):
            customer = user.customer
            customer.loyalty_points += 100
            customer.save(update_fields=['loyalty_points'])
            logger.info(f"Added 100 welcome points to user {user.email}")
        
        # Send welcome email using HTML template
        send_welcome_email_html(user)
        
        logger.info(f"Welcome email sent to {user.email}")
        return f"Welcome email sent to {user.email}"
        
    except User.DoesNotExist:
        logger.error(f"User with id {user_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send welcome email: {exc}", exc_info=True)
        # Retry with exponential backoff (60s, 120s, 240s)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email_async(self, user_id, reset_code):
    """
    Send password reset email asynchronously.
    
    Args:
        user_id: ID of the user requesting password reset
        reset_code: Generated reset code
    
    Returns:
        str: Success message
    """
    logger.info(f"🔵 TASK STARTED: Sending password reset for user {user_id}")
    
    try:
        user = User.objects.get(id=user_id)
        
        logger.info(f"📧 User found: {user.email}")
        logger.info(f"📧 Calling send_password_reset_email...")
        
        # Send email using utility function
        send_password_reset_email(user, reset_code)
        
        logger.info(f"✅ Password reset email sent successfully to {user.email}")
        return f"Password reset email sent to {user.email}"
        
    except User.DoesNotExist:
        logger.error(f"❌ User with id {user_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"❌ Failed to send password reset email: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_loyalty_points_notification(self, customer_id, points_added, reason):
    """
    Send email notification when loyalty points are added to customer account.
    
    Args:
        customer_id: ID of the customer
        points_added: Number of points added
        reason: Reason for adding points
    
    Returns:
        str: Success message
    """
    try:
        customer = Customer.objects.select_related('user').get(id=customer_id)
        user = customer.user
        
        # Send email using HTML template
        send_loyalty_points_email(
            user=user,
            points_added=points_added,
            total_points=customer.loyalty_points,
            reason=reason
        )
        
        logger.info(f"Loyalty points notification sent to {user.email}")
        return f"Notification sent to {user.email}"
        
    except Customer.DoesNotExist:
        logger.error(f"Customer with id {customer_id} not found")
        raise
        
    except Exception as exc:
        logger.error(f"Failed to send loyalty notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=2)
def send_bulk_promotional_email(self, subject, message, html_message=None, customer_ids=None):
    """
    Send promotional emails to customers in bulk.
    Uses batching to avoid overwhelming the mail server.
    
    Args:
        subject: Email subject
        message: Plain text message
        html_message: Optional HTML message
        customer_ids: List of customer IDs (None = all active customers)
    
    Returns:
        str: Success message with count
    """
    try:
        # Get target customers
        if customer_ids:
            customers = Customer.objects.filter(
                id__in=customer_ids
            ).select_related('user').filter(user__is_active=True)
        else:
            customers = Customer.objects.filter(
                user__is_active=True
            ).select_related('user')
        
        email_list = [customer.user.email for customer in customers]
        
        if not email_list:
            logger.warning("No customers found for bulk email")
            return "No customers to email"
        
        # Send emails in batches to avoid rate limits
        batch_size = 50
        sent_count = 0
        
        for i in range(0, len(email_list), batch_size):
            batch = email_list[i:i + batch_size]
            
            try:
                if html_message:
                    from django.core.mail import EmailMultiAlternatives
                    email = EmailMultiAlternatives(
                        subject=subject,
                        body=message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        bcc=batch,  # Use BCC for privacy
                    )
                    email.attach_alternative(html_message, "text/html")
                    email.send(fail_silently=False)
                else:
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=batch,
                        fail_silently=False,
                    )
                
                sent_count += len(batch)
                logger.info(f"Sent batch {i//batch_size + 1}: {len(batch)} emails")
                
            except Exception as batch_exc:
                logger.error(f"Failed to send batch {i//batch_size + 1}: {batch_exc}")
                continue
        
        logger.info(f"Bulk email campaign completed: {sent_count}/{len(email_list)} sent")
        return f"Sent bulk email to {sent_count} customers"
        
    except Exception as exc:
        logger.error(f"Failed to send bulk email: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=300)  # Retry after 5 minutes


# ============================================================================
# CUSTOMER MANAGEMENT TASKS
# ============================================================================

@shared_task
def update_customer_loyalty_points(customer_id, points_to_add, reason="Loyalty program update"):
    """
    Update customer loyalty points and send notification.
    Useful for bulk operations or scheduled point awards.
    
    Args:
        customer_id: ID of the customer
        points_to_add: Number of points to add
        reason: Reason for adding points
    
    Returns:
        str: Success message
    """
    try:
        customer = Customer.objects.get(id=customer_id)
        customer.loyalty_points += points_to_add
        customer.save(update_fields=['loyalty_points'])
        
        logger.info(f"Added {points_to_add} points to customer {customer.id}")
        
        # Send notification asynchronously
        send_loyalty_points_notification.delay(
            customer_id, 
            points_to_add, 
            reason
        )
        
        return f"Updated loyalty points for customer {customer_id}"
        
    except Customer.DoesNotExist:
        logger.error(f"Customer with id {customer_id} not found")
        raise


@shared_task
def check_inactive_customers():
    """
    Check for customers who haven't logged in for 90 days.
    Send re-engagement emails with special offers.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find users inactive for 90 days
        threshold_date = timezone.now() - timedelta(days=90)
        inactive_users = User.objects.filter(
            last_login__lt=threshold_date,
            is_active=True
        ).select_related('customer')
        
        sent_count = 0
        
        for user in inactive_users:
            try:
                # Get loyalty points if customer exists
                loyalty_points = 0
                if hasattr(user, 'customer'):
                    loyalty_points = user.customer.loyalty_points
                
                # Send re-engagement email
                send_reengagement_email(user, loyalty_points)
                sent_count += 1
                
            except Exception as user_exc:
                logger.error(f"Failed to send re-engagement email to {user.email}: {user_exc}")
                continue
        
        logger.info(f"Sent re-engagement emails to {sent_count} inactive customers")
        return f"Sent re-engagement emails to {sent_count} customers"
        
    except Exception as exc:
        logger.error(f"Failed to check inactive customers: {exc}", exc_info=True)
        raise


# ============================================================================
# CLEANUP & MAINTENANCE TASKS
# ============================================================================

@shared_task
def cleanup_expired_reset_codes():
    """
    Clean up expired and used password reset codes.
    Scheduled to run daily via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Delete expired codes
        expired_codes = PasswordResetCode.objects.filter(
            expires_at__lt=timezone.now()
        )
        expired_count = expired_codes.count()
        expired_codes.delete()
        
        # Delete used codes older than 7 days
        old_used_codes = PasswordResetCode.objects.filter(
            is_used=True,
            created_at__lt=timezone.now() - timedelta(days=7)
        )
        used_count = old_used_codes.count()
        old_used_codes.delete()
        
        total_cleaned = expired_count + used_count
        logger.info(f"Cleaned up {total_cleaned} password reset codes ({expired_count} expired, {used_count} old used)")
        
        return f"Cleaned up {total_cleaned} reset codes"
        
    except Exception as exc:
        logger.error(f"Failed to cleanup expired reset codes: {exc}", exc_info=True)
        raise


# ============================================================================
# ANALYTICS & REPORTING TASKS
# ============================================================================

@shared_task
def generate_customer_report():
    """
    Generate comprehensive customer analytics report.
    Scheduled to run weekly/monthly via Celery Beat.
    Sends report to admin users.
    
    Returns:
        dict: Report data
    """
    try:
        # Calculate statistics
        total_customers = Customer.objects.count()
        
        # Average loyalty points
        avg_loyalty_points = Customer.objects.aggregate(
            avg_points=Avg('loyalty_points')
        )['avg_points'] or 0
        
        # Total loyalty points awarded
        total_loyalty_points = Customer.objects.aggregate(
            total_points=Sum('loyalty_points')
        )['total_points'] or 0
        
        # New customers this month
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        new_customers_month = Customer.objects.filter(
            created_at__gte=month_start
        ).count()
        
        # Top customers by loyalty points
        top_customers = Customer.objects.select_related('user').order_by(
            '-loyalty_points'
        )[:10]
        
        # Prepare report data
        report = {
            'total_customers': total_customers,
            'average_loyalty_points': round(avg_loyalty_points, 2),
            'total_loyalty_points': total_loyalty_points,
            'new_customers_this_month': new_customers_month,
            'top_customers': [
                {
                    'email': c.user.email,
                    'name': c.user.get_full_name() or c.user.username,
                    'loyalty_points': c.loyalty_points,
                    'phone': c.phone,
                }
                for c in top_customers
            ],
            'generated_at': timezone.now().isoformat(),
            'report_period': 'Monthly',
        }
        
        logger.info(f"Customer report generated: {total_customers} total customers")
        
        # Send report to admins
        send_customer_report_to_admins(report)
        
        return report
        
    except Exception as exc:
        logger.error(f"Failed to generate customer report: {exc}", exc_info=True)
        raise


@shared_task
def analyze_customer_engagement():
    """
    Analyze customer engagement metrics.
    Identifies highly engaged vs at-risk customers.
    
    Returns:
        dict: Engagement analysis
    """
    try:
        # Active customers (logged in within 30 days)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        active_customers = User.objects.filter(
            last_login__gte=thirty_days_ago,
            is_active=True
        ).count()
        
        # At-risk customers (no login in 60-90 days)
        sixty_days_ago = timezone.now() - timedelta(days=60)
        ninety_days_ago = timezone.now() - timedelta(days=90)
        at_risk_customers = User.objects.filter(
            last_login__lt=sixty_days_ago,
            last_login__gte=ninety_days_ago,
            is_active=True
        ).count()
        
        # Dormant customers (no login in 90+ days)
        dormant_customers = User.objects.filter(
            last_login__lt=ninety_days_ago,
            is_active=True
        ).count()
        
        # Customers with high loyalty points (top 10%)
        high_value_threshold = Customer.objects.order_by('-loyalty_points')[
            int(Customer.objects.count() * 0.1)
        ].loyalty_points if Customer.objects.count() > 0 else 0
        
        high_value_customers = Customer.objects.filter(
            loyalty_points__gte=high_value_threshold
        ).count()
        
        engagement_data = {
            'active_customers': active_customers,
            'at_risk_customers': at_risk_customers,
            'dormant_customers': dormant_customers,
            'high_value_customers': high_value_customers,
            'high_value_threshold': high_value_threshold,
            'analyzed_at': timezone.now().isoformat(),
        }
        
        logger.info(f"Engagement analysis: {active_customers} active, {at_risk_customers} at-risk, {dormant_customers} dormant")
        
        return engagement_data
        
    except Exception as exc:
        logger.error(f"Failed to analyze customer engagement: {exc}", exc_info=True)
        raise


# ============================================================================
# SCHEDULED TASK CONFIGURATIONS
# ============================================================================

"""
Add these to your Celery Beat schedule in settings.py:

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
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
}
"""