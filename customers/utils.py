import secrets
import string
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth.models import User
import six
import logging

logger = logging.getLogger(__name__)


class AccountActivationTokenGenerator(PasswordResetTokenGenerator):
    """Custom token generator for account activation and password reset"""
    
    def _make_hash_value(self, user, timestamp):
        return (
            six.text_type(user.pk) + six.text_type(timestamp) + 
            six.text_type(user.is_active)
        )


account_activation_token = AccountActivationTokenGenerator()


def generate_reset_code(length=6):
    """
    Generate a random alphanumeric reset code.
    
    Args:
        length (int): Length of the code (default 6)
    
    Returns:
        str: Random alphanumeric code in uppercase
    """
    characters = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))


def send_password_reset_email(user, reset_code):
    """
    Send password reset email with code using HTML template.
    
    Args:
        user: User object
        reset_code: Generated reset code
    """
    try:
        # Generate token for URL
        token = account_activation_token.make_token(user)
        uid = six.text_type(user.pk)
        
        # Build reset URL
        frontend_url = settings.CORS_ALLOWED_ORIGINS[0] if settings.CORS_ALLOWED_ORIGINS else settings.FRONTEND_URL
        reset_url = f"{frontend_url+'/reset-password'}?uid={uid}&token={token}&code={reset_code}"
        
        # Prepare context for template
        context = {
            'user': user,
            'reset_code': reset_code,
            'reset_url': reset_url,
            'support_email': settings.SUPPORT_EMAIL,
            'site_url': frontend_url,
        }
        
        # Render HTML email
        html_message = render_to_string('reset_email.html', context)
        
        # Plain text fallback
        plain_message = f"""
            Hello {user.first_name},

            We received a request to reset your password for your SoundWaveAudio account.

            Your password reset code is: {reset_code}

            Or use this link: {reset_url}

            This code will expire in 24 hours.

            If you didn't request a password reset, you can safely ignore this email.

            Best regards,
            The SoundWaveAudio Team
            """
        
        # Send email with both HTML and plain text
        email = EmailMultiAlternatives(
            subject='Password Reset Request - SoundWaveAudio',
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        logger.info(f"Password reset email sent to {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user.email}: {str(e)}")
        raise


def send_welcome_email_html(user):
    """
    Send welcome email to new user with HTML template.
    
    Args:
        user: User object
    """
    try:
        frontend_url = settings.CORS_ALLOWED_ORIGINS[0] if settings.CORS_ALLOWED_ORIGINS else settings.FRONTEND_URL
        
        context = {
            'user': user,
            'support_email': settings.SUPPORT_EMAIL,
            'site_url': frontend_url,
        }
        
        # Render HTML email
        html_message = render_to_string('welcome_email.html', context)
        
        # Plain text fallback
        plain_message = f"""
        Hello {user.first_name},

        Welcome to SoundWaveAudio! We're excited to have you as part of our community.

        Your account has been successfully created. You can now:
        - Browse our premium speaker collection
        - Save your favorite products
        - Track your orders
        - Earn loyalty points with every purchase

        We've added 100 loyalty points to get you started!

        If you have any questions, feel free to reach out to our support team at {settings.SUPPORT_EMAIL}.

        Happy shopping!

        Best regards,
        The SoundWaveAudio Team
        """
        
        email = EmailMultiAlternatives(
            subject='Welcome to SoundWaveAudio!',
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        logger.info(f"Welcome email sent to {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
        raise


def send_loyalty_points_email(user, points_added, total_points, reason):
    """
    Send loyalty points notification email with HTML template.
    
    Args:
        user: User object
        points_added: Number of points added
        total_points: Total points after addition
        reason: Reason for points addition
    """
    try:
        frontend_url = settings.CORS_ALLOWED_ORIGINS[0] if settings.CORS_ALLOWED_ORIGINS else settings.FRONTEND_URL
        
        context = {
            'user': user,
            'points_added': points_added,
            'total_points': total_points,
            'reason': reason,
            'support_email': settings.SUPPORT_EMAIL,
            'site_url': frontend_url,
        }
        
        # Render HTML email
        html_message = render_to_string('loyalty_points_notification.html', context)
        
        # Plain text fallback
        plain_message = f"""
Hello {user.first_name},

Great news! {points_added} loyalty points have been added to your account.

Reason: {reason}
Total Loyalty Points: {total_points}

Keep shopping to earn more points and unlock exclusive rewards!

Best regards,
The SoundWaveAudio Team
"""
        
        email = EmailMultiAlternatives(
            subject='Loyalty Points Added to Your Account!',
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        logger.info(f"Loyalty points notification sent to {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send loyalty points email to {user.email}: {str(e)}")
        raise


def send_reengagement_email(user, loyalty_points=0):
    """
    Send re-engagement email to inactive users with HTML template.
    
    Args:
        user: User object
        loyalty_points: Current loyalty points balance
    """
    try:
        frontend_url = settings.CORS_ALLOWED_ORIGINS[0] if settings.CORS_ALLOWED_ORIGINS else settings.FRONTEND_URL
        
        context = {
            'user': user,
            'loyalty_points': loyalty_points,
            'support_email': settings.SUPPORT_EMAIL,
            'site_url': frontend_url,
        }
        
        # Render HTML email
        html_message = render_to_string('reengagement_email.html', context)
        
        # Plain text fallback
        plain_message = f"""
Hello {user.first_name},

We noticed you haven't visited us in a while. We'd love to have you back!

Special Offer: Use code WELCOME15 for 15% off your next order!

You still have {loyalty_points} loyalty points waiting for you.

Check out our latest products and exclusive offers just for you.

Best regards,
The SoundWaveAudio Team
"""
        
        email = EmailMultiAlternatives(
            subject='We Miss You at SoundWaveAudio!',
            body=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        logger.info(f"Re-engagement email sent to {user.email}")
        
    except Exception as e:
        logger.error(f"Failed to send re-engagement email to {user.email}: {str(e)}")
        raise


def send_mail_to_admins(subject, message, html_message=None):
    """
    Send email to all admin users.
    
    Args:
        subject: Email subject
        message: Plain text message
        html_message: Optional HTML message
    """
    try:
        # Get all admin emails
        admin_emails = list(
            User.objects.filter(is_staff=True, is_active=True)
            .values_list('email', flat=True)
        )
        
        if not admin_emails:
            logger.warning("No admin users found to send email")
            return
        
        if html_message:
            email = EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=admin_emails,
            )
            email.attach_alternative(html_message, "text/html")
            email.send(fail_silently=False)
        else:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=admin_emails,
                fail_silently=False,
            )
        
        logger.info(f"Admin notification sent to {len(admin_emails)} admins")
        
    except Exception as e:
        logger.error(f"Failed to send email to admins: {str(e)}")
        raise


def send_customer_report_to_admins(report_data):
    """
    Send customer analytics report to admin users.
    
    Args:
        report_data: Dictionary containing report information
    """
    try:
        subject = f"Customer Analytics Report - {timezone.now().strftime('%B %d, %Y')}"
        
        # Create formatted message
        message = f"""
Customer Analytics Report
Generated: {report_data.get('generated_at', timezone.now().isoformat())}

Total Customers: {report_data.get('total_customers', 0)}
Average Loyalty Points: {report_data.get('average_loyalty_points', 0)}

Top 10 Customers by Loyalty Points:
"""
        
        for i, customer in enumerate(report_data.get('top_customers', [])[:10], 1):
            message += f"\n{i}. {customer.get('name', 'N/A')} ({customer.get('email', 'N/A')}) - {customer.get('loyalty_points', 0)} points"
        
        message += "\n\nBest regards,\nSoundWaveAudio Analytics System"
        
        send_mail_to_admins(subject, message)
        
        logger.info("Customer report sent to admins")
        
    except Exception as e:
        logger.error(f"Failed to send customer report to admins: {str(e)}")
        raise


def generate_unique_code(prefix='', length=8, model=None, field_name='code'):
    """
    Generate a unique code for a model.
    
    Args:
        prefix: Optional prefix for the code
        length: Length of the random part
        model: Model class to check uniqueness
        field_name: Field name to check for uniqueness
    
    Returns:
        str: Unique code
    """
    while True:
        random_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
        code = f"{prefix}{random_part}" if prefix else random_part
        
        if model is None:
            return code
        
        # Check if code exists in database
        filter_kwargs = {field_name: code}
        if not model.objects.filter(**filter_kwargs).exists():
            return code


def validate_kenyan_phone(phone):
    """
    Validate Kenyan phone number format.
    
    Args:
        phone: Phone number string
    
    Returns:
        tuple: (is_valid, formatted_phone)
    """
    import re
    
    # Remove any spaces, dashes, or parentheses
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Check various Kenyan formats
    patterns = [
        r'^(\+254|254|0)(7|1)\d{8}$',  # Standard Kenyan mobile
    ]
    
    for pattern in patterns:
        if re.match(pattern, cleaned):
            # Convert to international format
            if cleaned.startswith('0'):
                formatted = '+254' + cleaned[1:]
            elif cleaned.startswith('254'):
                formatted = '+' + cleaned
            else:
                formatted = cleaned
            
            return True, formatted
    
    return False, phone


def format_currency(amount, currency='KSh'):
    """
    Format amount as currency string.
    
    Args:
        amount: Numeric amount
        currency: Currency symbol/code
    
    Returns:
        str: Formatted currency string
    """
    try:
        return f"{currency} {amount:,.2f}"
    except (ValueError, TypeError):
        return f"{currency} 0.00"