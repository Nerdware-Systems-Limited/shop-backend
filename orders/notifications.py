from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
import logging

# Optional: Twilio for SMS (install with: pip install twilio)
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

logger = logging.getLogger(__name__)


class OrderNotifications:
    """
    God-Level Notification System for Orders
    
    Features:
    - Email notifications with beautiful HTML templates
    - SMS notifications (optional)
    - Admin alerts
    - Automatic template selection
    - Error handling and logging
    """
    
    # Email template configuration
    EMAIL_TEMPLATES = {
        'order_confirmation': {
            'subject': '✅ Order Confirmation - {order_number}',
            'template_html': 'emails/order_confirmation.html',
            'template_txt': 'emails/order_confirmation.txt'
        },
        'order_shipped': {
            'subject': '📦 Your Order Has Shipped! - {order_number}',
            'template_html': 'emails/order_shipped.html',
            'template_txt': 'emails/order_shipped.txt'
        },
        'order_delivered': {
            'subject': '🎉 Order Delivered - {order_number}',
            'template_html': 'emails/order_delivered.html',
            'template_txt': 'emails/order_delivered.txt'
        },
        'order_cancelled': {
            'subject': '❌ Order Cancelled - {order_number}',
            'template_html': 'emails/order_cancelled.html',
            'template_txt': 'emails/order_cancelled.txt'
        },
        'payment_failed': {
            'subject': '⚠️ Payment Failed - {order_number}',
            'template_html': 'emails/payment_failed.html',
            'template_txt': 'emails/payment_failed.txt'
        },
        'payment_received': {
            'subject': '💰 Payment Received - {order_number}',
            'template_html': 'emails/payment_received.html',
            'template_txt': 'emails/payment_received.txt'
        },
        'order_processing': {
            'subject': '⚙️ Order Processing - {order_number}',
            'template_html': 'emails/order_processing.html',
            'template_txt': 'emails/order_processing.txt'
        },
    }
    
    @classmethod
    def send_email_notification(cls, order, notification_type, context=None, recipient_email=None):
        """
        Send email notification
        
        Args:
            order: Order instance
            notification_type: Type of notification (key from EMAIL_TEMPLATES)
            context: Additional context data (dict)
            recipient_email: Override recipient email
        
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        if notification_type not in cls.EMAIL_TEMPLATES:
            logger.error(f"Unknown notification type: {notification_type}")
            return False
        
        template = cls.EMAIL_TEMPLATES[notification_type]
        
        # Prepare context
        email_context = {
            'order': order,
            'site_name': getattr(settings, 'SITE_NAME', 'SoundWaveAudio'),
            'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@soundwave.com'),
            'current_year': timezone.now().year,
        }

        # Add custom context
        if context:
            email_context.update(context)
        
        # Render templates
        try:
            subject = template['subject'].format(order_number=order.order_number)
            html_content = render_to_string(template['template_html'], email_context)
            text_content = render_to_string(template['template_txt'], email_context)
        except Exception as e:
            print(f"Failed to render email template: {str(e)}")
            logger.error(f"Failed to render email template: {str(e)}")
            return False
        
        # Determine recipient
        if recipient_email:
            recipient = recipient_email
        elif order.is_guest:
            recipient = order.guest_email
        elif order.customer:
            recipient = order.customer.user.email
        else:
            logger.error(f"No recipient email found for order {order.order_number}")
            return False
        
        if not recipient:
            logger.error(f"Empty recipient email for order {order.order_number}")
            return False
            
        # Send email
        try:
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwave.com'),
                to=[recipient],
                reply_to=[getattr(settings, 'SUPPORT_EMAIL', 'support@soundwave.com')]
            )
            email.attach_alternative(html_content, "text/html")
            print(email)
            email.send(fail_silently=False)
            
            logger.info(f"✅ Email sent: {notification_type} for order {order.order_number} to {recipient}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to send email notification: {str(e)}")
            print(f"❌ Failed to send email notification: {str(e)}")
            logger.exception(e)  # Log full stack trace
            return False
    
    @classmethod
    def send_sms_notification(cls, order, message, phone_number=None):
        """
        Send SMS notification (requires Twilio)
        
        Args:
            order: Order instance
            message: SMS message text
            phone_number: Override phone number
        
        Returns:
            bool: True if SMS sent successfully, False otherwise
        """
        if not TWILIO_AVAILABLE:
            logger.warning("Twilio not installed. Install with: pip install twilio")
            return False
        
        if not hasattr(settings, 'TWILIO_ACCOUNT_SID'):
            logger.warning("Twilio not configured in settings")
            return False
        
        try:
            # Determine phone number
            if phone_number:
                recipient_phone = phone_number
            elif order.is_guest and order.guest_phone:
                recipient_phone = order.guest_phone
            elif order.customer and hasattr(order.customer, 'phone') and order.customer.phone:
                recipient_phone = order.customer.phone
            else:
                logger.warning(f"No phone number found for order {order.order_number}")
                return False
            
            # Initialize Twilio client
            client = Client(
                settings.TWILIO_ACCOUNT_SID,
                settings.TWILIO_AUTH_TOKEN
            )
            
            # Send SMS
            sms = client.messages.create(
                body=message,
                from_=settings.TWILIO_PHONE_NUMBER,
                to=recipient_phone
            )
            
            logger.info(f"✅ SMS sent to {recipient_phone}: {sms.sid}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to send SMS: {str(e)}")
            return False
    
    @classmethod
    def send_admin_alert(cls, order, alert_type, message):
        """
        Send alert to admin
        
        Args:
            order: Order instance
            alert_type: Type of alert (string)
            message: Alert message
        
        Returns:
            bool: True if alert sent successfully, False otherwise
        """
        if not hasattr(settings, 'ADMIN_EMAILS'):
            logger.warning("ADMIN_EMAILS not configured in settings")
            return False
        
        admin_emails = settings.ADMIN_EMAILS
        if isinstance(admin_emails, str):
            admin_emails = [admin_emails]
        
        if not admin_emails:
            logger.warning("No admin emails configured")
            return False
        
        try:
            subject = f"🚨 Admin Alert: {alert_type} - Order {order.order_number}"
            
            context = {
                'order': order,
                'alert_type': alert_type,
                'message': message,
                'timestamp': timezone.now(),
                'site_name': getattr(settings, 'SITE_NAME', 'SoundWaveAudio'),
                'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
            }
            
            html_content = render_to_string('emails/admin_alert.html', context)
            text_content = render_to_string('emails/admin_alert.txt', context)
            
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwave.com'),
                to=admin_emails
            )
            email.attach_alternative(html_content, "text/html")
            email.send(fail_silently=False)
            
            logger.info(f"✅ Admin alert sent: {alert_type} for order {order.order_number}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to send admin alert: {str(e)}")
            return False
    
    @classmethod
    def notify_order_status_change(cls, order, old_status, new_status):
        """
        Automatically send appropriate notification based on status change
        
        Args:
            order: Order instance
            old_status: Previous status
            new_status: New status
        """
        notification_mapping = {
            'confirmed': 'order_confirmation',
            'processing': 'order_processing',
            'shipped': 'order_shipped',
            'delivered': 'order_delivered',
            'cancelled': 'order_cancelled',
        }
        
        if new_status in notification_mapping:
            notification_type = notification_mapping[new_status]
            cls.send_email_notification(order, notification_type)
            
            # Send SMS for critical status changes
            if new_status in ['shipped', 'delivered']:
                sms_messages = {
                    'shipped': f"Your order {order.order_number} has been shipped! Track it here: {getattr(settings, 'SITE_URL', '')}/orders/{order.order_number}",
                    'delivered': f"Your order {order.order_number} has been delivered! We hope you enjoy your purchase. 🎉"
                }
                cls.send_sms_notification(order, sms_messages[new_status])
    
    @classmethod
    def notify_payment_status_change(cls, order, old_payment_status, new_payment_status):
        """
        Send notification for payment status changes
        
        Args:
            order: Order instance
            old_payment_status: Previous payment status
            new_payment_status: New payment status
        """
        if new_payment_status == 'paid':
            cls.send_email_notification(order, 'payment_received')
        elif new_payment_status == 'failed':
            cls.send_email_notification(order, 'payment_failed')
            # Alert admin about failed payment
            cls.send_admin_alert(
                order, 
                'Payment Failed',
                f"Payment failed for order {order.order_number}. Customer: {order.customer.user.email if order.customer else order.guest_email}"
            )


# Convenience functions for common notifications
def send_order_confirmation(order):
    """Send order confirmation email"""
    return OrderNotifications.send_email_notification(order, 'order_confirmation')


def send_shipping_notification(order):
    """Send shipping notification email"""
    return OrderNotifications.send_email_notification(order, 'order_shipped')


def send_delivery_notification(order):
    """Send delivery notification email"""
    return OrderNotifications.send_email_notification(order, 'order_delivered')


def send_cancellation_notification(order):
    """Send cancellation notification email"""
    return OrderNotifications.send_email_notification(order, 'order_cancelled')


def send_payment_failed_notification(order):
    """Send payment failed notification email"""
    return OrderNotifications.send_email_notification(order, 'payment_failed')


def notify_admins(order, alert_type, message):
    """Send alert to admins"""
    return OrderNotifications.send_admin_alert(order, alert_type, message)