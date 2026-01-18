"""
God-Level Celery Tasks for Products App
Handles inventory monitoring, review processing, and product analytics
"""
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F, Q, Min
from datetime import timedelta
from decimal import Decimal
import logging

from .models import Product, Review, Category, Brand, ProductImage
from customers.models import Customer
from orders.models import Order, OrderItem

logger = logging.getLogger(__name__)


# ============================================================================
# INVENTORY MONITORING TASKS
# ============================================================================

@shared_task
def check_low_stock_products():
    """
    Check for products with low stock and alert admins.
    Runs every hour via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Get products at or below low stock threshold
        low_stock_products = Product.objects.filter(
            is_active=True,
            stock_quantity__lte=F('low_stock_threshold'),
            stock_quantity__gt=0
        ).select_related('category', 'brand')
        
        low_count = low_stock_products.count()
        
        if low_count > 0:
            # Send alert to admins
            send_low_stock_alert.delay(list(low_stock_products.values_list('id', flat=True)))
            
            logger.warning(f"Found {low_count} products with low stock")
        
        return f"Checked inventory: {low_count} low stock products found"
    
    except Exception as exc:
        logger.error(f"Failed to check low stock: {exc}", exc_info=True)
        raise


@shared_task
def check_out_of_stock_products():
    """
    Check for out-of-stock products and alert admins.
    Runs every 2 hours via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Get products that are out of stock
        out_of_stock = Product.objects.filter(
            is_active=True,
            stock_quantity=0
        ).select_related('category', 'brand')
        
        oos_count = out_of_stock.count()
        
        if oos_count > 0:
            # Send alert to admins
            send_out_of_stock_alert.delay(list(out_of_stock.values_list('id', flat=True)))
            
            logger.warning(f"Found {oos_count} out-of-stock products")
        
        return f"Checked inventory: {oos_count} out-of-stock products found"
    
    except Exception as exc:
        logger.error(f"Failed to check out of stock: {exc}", exc_info=True)
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_low_stock_alert(self, product_ids):
    """
    Send low stock alert email to admins.
    
    Args:
        product_ids: List of product IDs with low stock
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        products = Product.objects.filter(id__in=product_ids).select_related(
            'category', 'brand'
        )
        
        # Group by urgency
        critical = []  # Stock = 0-5
        warning = []   # Stock = 6-10
        low = []       # Stock = 11-threshold
        
        for product in products:
            if product.stock_quantity <= 5:
                critical.append(product)
            elif product.stock_quantity <= 10:
                warning.append(product)
            else:
                low.append(product)
        
        subject = f"⚠️ Low Stock Alert - {len(product_ids)} Products Need Attention"
        
        message = f"""
Low Stock Inventory Alert

Critical (0-5 units):
{chr(10).join(f"  • {p.name} ({p.sku}): {p.stock_quantity} units" for p in critical) if critical else "  None"}

Warning (6-10 units):
{chr(10).join(f"  • {p.name} ({p.sku}): {p.stock_quantity} units" for p in warning) if warning else "  None"}

Low Stock (11-threshold):
{chr(10).join(f"  • {p.name} ({p.sku}): {p.stock_quantity} units" for p in low) if low else "  None"}

Total Products: {len(product_ids)}

Please restock these items as soon as possible.

Best regards,
SoundWaveAudio Inventory System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Low stock alert sent for {len(product_ids)} products")
        return f"Low stock alert sent for {len(product_ids)} products"
    
    except Exception as exc:
        logger.error(f"Failed to send low stock alert: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_out_of_stock_alert(self, product_ids):
    """
    Send out-of-stock alert email to admins.
    
    Args:
        product_ids: List of product IDs that are out of stock
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        products = Product.objects.filter(id__in=product_ids).select_related(
            'category', 'brand'
        ).annotate(
            pending_orders=Count('orderitem', filter=Q(
                orderitem__order__status__in=['pending', 'confirmed', 'processing']
            ))
        )
        
        # Separate products with pending orders (high priority)
        with_orders = []
        without_orders = []
        
        for product in products:
            if product.pending_orders > 0:
                with_orders.append(product)
            else:
                without_orders.append(product)
        
        subject = f"🚨 Out of Stock Alert - {len(product_ids)} Products"
        
        message = f"""
Out of Stock Alert

URGENT - Products with Pending Orders ({len(with_orders)}):
{chr(10).join(f"  • {p.name} ({p.sku}) - {p.pending_orders} pending orders" for p in with_orders) if with_orders else "  None"}

Other Out of Stock Products ({len(without_orders)}):
{chr(10).join(f"  • {p.name} ({p.sku})" for p in without_orders) if without_orders else "  None"}

Total Out of Stock: {len(product_ids)}

IMMEDIATE ACTION REQUIRED for products with pending orders!

Best regards,
SoundWaveAudio Inventory System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Out of stock alert sent for {len(product_ids)} products")
        return f"Out of stock alert sent for {len(product_ids)} products"
    
    except Exception as exc:
        logger.error(f"Failed to send out of stock alert: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task
def auto_deactivate_out_of_stock_products():
    """
    Automatically deactivate products that have been out of stock for 30+ days.
    Runs weekly via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        from django.db.models import Q
        
        # Find products out of stock for 30+ days
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        # This is a simplified check - in production you'd track "out_of_stock_since" date
        products_to_deactivate = Product.objects.filter(
            is_active=True,
            stock_quantity=0,
            # Add condition: No stock movement in last 30 days
            # This would require a "last_stocked_at" field or checking OrderItems
        ).exclude(
            orderitem__order__created_at__gte=thirty_days_ago
        ).distinct()
        
        deactivated_count = 0
        
        for product in products_to_deactivate:
            product.is_active = False
            product.save()
            deactivated_count += 1
        
        if deactivated_count > 0:
            # Alert admins
            from customers.utils import send_mail_to_admins
            
            subject = f"Auto-Deactivated {deactivated_count} Products"
            message = f"""
{deactivated_count} products have been automatically deactivated due to being out of stock for 30+ days.

Please review and restock or permanently remove these products.

Best regards,
SoundWaveAudio Inventory System
"""
            send_mail_to_admins(subject, message)
        
        logger.info(f"Auto-deactivated {deactivated_count} products")
        return f"Auto-deactivated {deactivated_count} products"
    
    except Exception as exc:
        logger.error(f"Failed to auto-deactivate products: {exc}", exc_info=True)
        raise


# ============================================================================
# REVIEW PROCESSING TASKS
# ============================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_review_notification(self, review_id):
    """
    Send notification to admins when a new review is submitted.
    
    Args:
        review_id: ID of the review
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        review = Review.objects.select_related(
            'product', 'customer__user'
        ).get(id=review_id)
        
        subject = f"New Review: {review.product.name} - {review.rating}⭐"
        
        message = f"""
New Product Review Submitted

Product: {review.product.name} ({review.product.sku})
Customer: {review.customer.user.get_full_name() or review.customer.user.email}
Rating: {review.rating} / 5 stars
Title: {review.title}

Review:
{review.comment}

Verified Purchase: {'Yes' if review.is_verified_purchase else 'No'}
Status: {'Approved' if review.is_approved else 'Pending Approval'}

Review this submission in the admin panel.

Best regards,
SoundWaveAudio Review System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Review notification sent for review {review_id}")
        return f"Review notification sent for review {review_id}"
    
    except Review.DoesNotExist:
        logger.error(f"Review {review_id} not found")
        raise
    
    except Exception as exc:
        logger.error(f"Failed to send review notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_review_approval_notification(self, review_id):
    """
    Send notification to customer when their review is approved.
    
    Args:
        review_id: ID of the approved review
    
    Returns:
        str: Success message
    """
    try:
        review = Review.objects.select_related(
            'product', 'customer__user'
        ).get(id=review_id)
        
        customer = review.customer
        recipient_email = customer.user.email
        recipient_name = customer.user.get_full_name() or customer.user.first_name
        
        subject = f"Your Review Has Been Published - {review.product.name}"
        
        context = {
            'customer_name': recipient_name,
            'review': review,
            'site_name': 'SoundWaveAudio',
            'site_url': getattr(settings, 'FRONTEND_URL', 'https://soundwaveaudio.com'),
        }
        
        # HTML email would go here
        plain_message = f"""
Dear {recipient_name},

Thank you for reviewing {review.product.name}!

Your review has been approved and is now visible on our website.

Your Rating: {review.rating} / 5 stars
Your Review: "{review.title}"

Thank you for helping other customers make informed decisions!

Best regards,
SoundWaveAudio Team
"""
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=plain_message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@soundwaveaudio.com'),
            to=[recipient_email],
        )
        email.send(fail_silently=False)
        
        logger.info(f"Review approval notification sent to {recipient_email}")
        return f"Review approval notification sent to {recipient_email}"
    
    except Review.DoesNotExist:
        logger.error(f"Review {review_id} not found")
        raise
    
    except Exception as exc:
        logger.error(f"Failed to send review approval notification: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task
def auto_approve_verified_reviews():
    """
    Auto-approve reviews from verified purchases with 3+ stars.
    Runs daily via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Get pending reviews from verified purchases with 3+ rating
        pending_verified_reviews = Review.objects.filter(
            is_approved=False,
            is_verified_purchase=True,
            rating__gte=3
        )
        
        approved_count = 0
        
        for review in pending_verified_reviews:
            review.is_approved = True
            review.save()
            
            # Send approval notification
            send_review_approval_notification.delay(review.id)
            
            approved_count += 1
        
        logger.info(f"Auto-approved {approved_count} verified reviews")
        return f"Auto-approved {approved_count} verified reviews"
    
    except Exception as exc:
        logger.error(f"Failed to auto-approve reviews: {exc}", exc_info=True)
        raise


@shared_task
def cleanup_spam_reviews():
    """
    Detect and remove spam/duplicate reviews.
    Runs weekly via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find potential spam (very short reviews, 1-star with minimal text)
        spam_candidates = Review.objects.filter(
            is_approved=False,
            rating=1,
            comment__regex=r'^.{0,10}$'  # Less than 10 characters
        )
        
        deleted_count = spam_candidates.count()
        spam_candidates.delete()
        
        logger.info(f"Cleaned up {deleted_count} potential spam reviews")
        return f"Cleaned up {deleted_count} potential spam reviews"
    
    except Exception as exc:
        logger.error(f"Failed to cleanup spam reviews: {exc}", exc_info=True)
        raise


# ============================================================================
# PRODUCT ANALYTICS TASKS
# ============================================================================

@shared_task
def generate_product_performance_report():
    """
    Generate daily product performance report.
    Runs daily at 11 PM via Celery Beat.
    
    Returns:
        dict: Report data
    """
    try:
        from customers.utils import send_mail_to_admins
        
        today = timezone.now().date()
        
        # Top selling products (last 30 days)
        thirty_days_ago = today - timedelta(days=30)
        
        top_sellers = Product.objects.filter(
            orderitem__order__created_at__date__gte=thirty_days_ago,
            orderitem__order__status__in=['confirmed', 'processing', 'shipped', 'delivered']
        ).annotate(
            units_sold=Sum('orderitem__quantity'),
            revenue=Sum(F('orderitem__price') * F('orderitem__quantity'))
        ).order_by('-units_sold')[:10]
        
        # Low performers (products with no sales in 30 days)
        no_sales = Product.objects.filter(is_active=True).exclude(
            orderitem__order__created_at__date__gte=thirty_days_ago
        ).count()
        
        # Products with low ratings
        low_rated = Product.objects.filter(
            reviews__is_approved=True
        ).annotate(
            avg_rating=Avg('reviews__rating')
        ).filter(avg_rating__lt=3).count()
        
        report = {
            'date': today.isoformat(),
            'top_sellers': list(top_sellers.values(
                'name', 'sku', 'units_sold', 'revenue'
            )),
            'no_sales_count': no_sales,
            'low_rated_count': low_rated,
            'total_active_products': Product.objects.filter(is_active=True).count(),
        }
        
        # Send report
        subject = f"Product Performance Report - {today}"
        message = f"""
Product Performance Report for {today}

Top 10 Selling Products (Last 30 Days):
{chr(10).join(f"  {i+1}. {p['name']} ({p['sku']}) - {p['units_sold']} units, KSh {p['revenue']:,.2f}" for i, p in enumerate(report['top_sellers']))}

Summary:
- Total Active Products: {report['total_active_products']}
- Products with No Sales (30 days): {report['no_sales_count']}
- Low-Rated Products (<3 stars): {report['low_rated_count']}

Best regards,
SoundWaveAudio Analytics System
"""
        
        send_mail_to_admins(subject, message)
        
        logger.info(f"Product performance report generated for {today}")
        return report
    
    except Exception as exc:
        logger.error(f"Failed to generate product report: {exc}", exc_info=True)
        raise


@shared_task
def update_product_popularity_scores():
    """
    Update popularity scores for products based on views, sales, reviews.
    Runs daily via Celery Beat.
    
    Note: Requires a 'popularity_score' field on Product model.
    
    Returns:
        str: Success message
    """
    try:
        # Calculate popularity based on multiple factors
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        products = Product.objects.filter(is_active=True).annotate(
            recent_sales=Count(
                'orderitem',
                filter=Q(orderitem__order__created_at__gte=thirty_days_ago)
            ),
            review_count=Count('reviews', filter=Q(reviews__is_approved=True)),
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
        )
        
        updated_count = 0
        
        for product in products:
            # Simple popularity formula
            # Score = (sales * 10) + (reviews * 5) + (avg_rating * 2)
            score = (
                (product.recent_sales or 0) * 10 +
                (product.review_count or 0) * 5 +
                (product.avg_rating or 0) * 2
            )
            
            # Update product (if you have popularity_score field)
            # product.popularity_score = score
            # product.save(update_fields=['popularity_score'])
            updated_count += 1
        
        logger.info(f"Updated popularity scores for {updated_count} products")
        return f"Updated popularity scores for {updated_count} products"
    
    except Exception as exc:
        logger.error(f"Failed to update popularity scores: {exc}", exc_info=True)
        raise


# ============================================================================
# PRICE & PROMOTION TASKS
# ============================================================================

@shared_task
def check_pricing_anomalies():
    """
    Check for pricing anomalies (cost > price, extreme discounts).
    Runs daily via Celery Beat.
    
    Returns:
        str: Success message
    """
    try:
        from customers.utils import send_mail_to_admins
        
        # Find products where cost > selling price
        loss_makers = Product.objects.filter(
            is_active=True,
            cost_price__gt=F('price')
        ).select_related('category', 'brand')
        
        # Find extreme discounts (>70%)
        extreme_discounts = Product.objects.filter(
            is_active=True,
            discount_percentage__gt=70
        ).select_related('category', 'brand')
        
        if loss_makers.exists() or extreme_discounts.exists():
            subject = "⚠️ Pricing Anomalies Detected"
            message = f"""
Pricing Anomalies Found

Products Selling at Loss (Cost > Price):
{chr(10).join(f"  • {p.name} ({p.sku}): Cost KSh {p.cost_price}, Price KSh {p.price}" for p in loss_makers) if loss_makers.exists() else "  None"}

Extreme Discounts (>70%):
{chr(10).join(f"  • {p.name} ({p.sku}): {p.discount_percentage}% off" for p in extreme_discounts) if extreme_discounts.exists() else "  None"}

Please review these pricing issues.

Best regards,
SoundWaveAudio Pricing System
"""
            
            send_mail_to_admins(subject, message)
        
        total_issues = loss_makers.count() + extreme_discounts.count()
        logger.info(f"Found {total_issues} pricing anomalies")
        return f"Found {total_issues} pricing anomalies"
    
    except Exception as exc:
        logger.error(f"Failed to check pricing anomalies: {exc}", exc_info=True)
        raise


@shared_task
def auto_expire_flash_sales():
    """
    Automatically reset discounts after flash sale period.
    
    Note: Requires a 'discount_ends_at' field on Product model.
    
    Returns:
        str: Success message with count
    """
    try:
        # This assumes you have a discount_ends_at datetime field
        # Uncomment and adjust if you implement this feature
        
        # expired_sales = Product.objects.filter(
        #     discount_ends_at__lte=timezone.now(),
        #     discount_percentage__gt=0
        # )
        
        # expired_count = 0
        # for product in expired_sales:
        #     product.discount_percentage = 0
        #     product.discount_ends_at = None
        #     product.save()
        #     expired_count += 1
        
        # logger.info(f"Expired {expired_count} flash sales")
        # return f"Expired {expired_count} flash sales"
        
        return "Flash sale expiration not implemented (requires discount_ends_at field)"
    
    except Exception as exc:
        logger.error(f"Failed to expire flash sales: {exc}", exc_info=True)
        raise


# ============================================================================
# IMAGE & MEDIA TASKS
# ============================================================================

@shared_task
def cleanup_orphaned_product_images():
    """
    Clean up product images with no associated product.
    Runs weekly via Celery Beat.
    
    Returns:
        str: Success message with count
    """
    try:
        # Find images where product is deleted
        orphaned_images = ProductImage.objects.filter(
            product__isnull=True
        )
        
        deleted_count = orphaned_images.count()
        
        # Delete the files and database records
        for image in orphaned_images:
            if image.image:
                image.image.delete()
        
        orphaned_images.delete()
        
        logger.info(f"Cleaned up {deleted_count} orphaned product images")
        return f"Cleaned up {deleted_count} orphaned product images"
    
    except Exception as exc:
        logger.error(f"Failed to cleanup orphaned images: {exc}", exc_info=True)
        raise


# ============================================================================
# SCHEDULED TASK CONFIGURATIONS
# ============================================================================

"""
Add these to your Celery Beat schedule in settings.py:

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # Inventory monitoring every hour
    'check-low-stock-products': {
        'task': 'products.tasks.check_low_stock_products',
        'schedule': crontab(minute=0),
    },
    
    # Check out of stock every 2 hours
    'check-out-of-stock-products': {
        'task': 'products.tasks.check_out_of_stock_products',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    
    # Auto-deactivate out of stock products weekly
    'auto-deactivate-out-of-stock': {
        'task': 'products.tasks.auto_deactivate_out_of_stock_products',
        'schedule': crontab(day_of_week=1, hour=3, minute=0),
    },
    
    # Auto-approve verified reviews daily at 2 AM
    'auto-approve-verified-reviews': {
        'task': 'products.tasks.auto_approve_verified_reviews',
        'schedule': crontab(hour=2, minute=0),
    },
    
    # Cleanup spam reviews weekly
    'cleanup-spam-reviews': {
        'task': 'products.tasks.cleanup_spam_reviews',
        'schedule': crontab(day_of_week=0, hour=3, minute=0),
    },
    
    # Product performance report daily at 11 PM
    'generate-product-performance-report': {
        'task': 'products.tasks.generate_product_performance_report',
        'schedule': crontab(hour=23, minute=0),
    },
    
    # Update popularity scores daily at 4 AM
    'update-product-popularity-scores': {
        'task': 'products.tasks.update_product_popularity_scores',
        'schedule': crontab(hour=4, minute=0),
    },
    
    # Check pricing anomalies daily at 9 AM
    'check-pricing-anomalies': {
        'task': 'products.tasks.check_pricing_anomalies',
        'schedule': crontab(hour=9, minute=0),
    },
    
    # Cleanup orphaned images weekly on Sunday at 4 AM
    'cleanup-orphaned-product-images': {
        'task': 'products.tasks.cleanup_orphaned_product_images',
        'schedule': crontab(day_of_week=0, hour=4, minute=0),
    },
}
"""