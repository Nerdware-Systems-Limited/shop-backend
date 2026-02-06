from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from django.utils import timezone
# from inventory.models import WarehouseStock


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    is_active = models.BooleanField(default=True)
    
    # SEO Fields
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(max_length=500, blank=True)
    seo_keywords = models.CharField(max_length=255, blank=True, help_text='Comma-separated keywords')
    
    # Display
    display_order = models.IntegerField(default=0, help_text='Lower numbers appear first')
    icon = models.CharField(max_length=50, blank=True, help_text='Icon class or emoji')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active', 'display_order']),
            models.Index(fields=['parent', 'is_active']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    logo = models.ImageField(upload_to='brands/', blank=True, null=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False, help_text='Show on featured brands section')
    
    # SEO Fields
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(max_length=500, blank=True)
    
    # Display
    display_order = models.IntegerField(default=0, help_text='Lower numbers appear first')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['display_order']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    CONDITION_CHOICES = [
        ('new', 'New'),
        ('refurbished', 'Refurbished'),
        ('used', 'Used'),
    ]
    
    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
        ('hidden', 'Hidden'),
        ('catalog', 'Catalog Only'),
    ]
    
    SHIPPING_CLASS_CHOICES = [
        ('standard', 'Standard'),
        ('express', 'Express'),
        ('heavy', 'Heavy Item'),
        ('fragile', 'Fragile'),
        ('oversized', 'Oversized'),
    ]

    # Basic Information
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    sku = models.CharField(max_length=50, unique=True)
    description = models.TextField()
    short_description = models.TextField(max_length=500, blank=True, help_text='Brief product description')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='products')
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], blank=True, null=True)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    
    # Sale/Promotion Pricing
    sale_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        blank=True, 
        null=True,
        validators=[MinValueValidator(0)],
        help_text='Special sale price (overrides discount_percentage)'
    )
    sale_starts_at = models.DateTimeField(blank=True, null=True, help_text='Sale start datetime')
    sale_ends_at = models.DateTimeField(blank=True, null=True, help_text='Sale end datetime')
    
    # Specifications
    specifications = models.JSONField(default=dict, blank=True)
    weight = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True, help_text='Weight in kg')
    dimensions = models.JSONField(default=dict, blank=True, help_text='{"length": 0, "width": 0, "height": 0} in cm')
    
    # Stock and Status
    stock_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    low_stock_threshold = models.IntegerField(default=10)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='new')
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    
    # Product Classification & Badges
    is_new_arrival = models.BooleanField(default=False, help_text='Mark as new arrival')
    new_arrival_until = models.DateTimeField(
        blank=True, 
        null=True, 
        help_text='Auto-remove new arrival badge after this date'
    )
    is_bestseller = models.BooleanField(default=False, help_text='Mark as bestseller')
    is_on_sale = models.BooleanField(default=False, help_text='Mark as on sale/promotion')
    badge_text = models.CharField(
        max_length=50, 
        blank=True, 
        help_text='Custom badge text (e.g., "Limited Edition", "Hot Deal")'
    )
    badge_color = models.CharField(
        max_length=7, 
        default='#FF0000', 
        blank=True, 
        help_text='Badge background color (hex code)'
    )
    
    # Inventory Management
    preorder_available = models.BooleanField(default=False, help_text='Allow preorders when out of stock')
    preorder_release_date = models.DateField(blank=True, null=True, help_text='Expected release date')
    backorder_allowed = models.BooleanField(default=False, help_text='Allow backorders when out of stock')
    restock_date = models.DateField(blank=True, null=True, help_text='Expected restock date')
    
    # Product Details
    manufacturer = models.CharField(max_length=100, blank=True, help_text='Product manufacturer')
    model_number = models.CharField(max_length=100, blank=True, help_text='Manufacturer model number')
    warranty_period = models.IntegerField(
        default=0, 
        validators=[MinValueValidator(0)], 
        help_text='Warranty period in months'
    )
    warranty_details = models.TextField(blank=True, help_text='Detailed warranty information')
    
    # Shipping & Logistics
    requires_shipping = models.BooleanField(default=True, help_text='Whether product requires physical shipping')
    is_fragile = models.BooleanField(default=False, help_text='Requires special handling')
    shipping_class = models.CharField(
        max_length=50, 
        choices=SHIPPING_CLASS_CHOICES,
        default='standard',
        help_text='Shipping class for rate calculation'
    )
    max_quantity_per_order = models.IntegerField(
        blank=True, 
        null=True, 
        validators=[MinValueValidator(1)],
        help_text='Maximum quantity allowed per order'
    )
    
    # Display & Performance
    display_order = models.IntegerField(default=0, help_text='Manual sort order (lower numbers first)')
    view_count = models.IntegerField(default=0, help_text='Number of page views')
    popularity_score = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0,
        help_text='Calculated popularity score for sorting'
    )
    
    # Variants (for future extensibility)
    has_variants = models.BooleanField(default=False, help_text='Product has variants (color, size, etc.)')
    parent_product = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='variants',
        help_text='Parent product if this is a variant'
    )
    
    # Visibility & Publishing
    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default='public',
        help_text='Product visibility settings'
    )
    publish_date = models.DateTimeField(blank=True, null=True, help_text='Schedule product publication')
    
    # SEO Fields
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(max_length=500, blank=True)
    seo_keywords = models.CharField(max_length=255, blank=True, help_text='Comma-separated keywords for SEO')
    canonical_url = models.URLField(blank=True, help_text='Canonical URL for SEO')
    og_image = models.ImageField(
        upload_to='products/og_images/', 
        blank=True, 
        null=True, 
        help_text='Open Graph image for social sharing'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Core indexes
            models.Index(fields=['slug']),
            models.Index(fields=['sku']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['brand', 'is_active']),
            
            # Pricing indexes
            models.Index(fields=['price']),
            models.Index(fields=['sale_price']),
            models.Index(fields=['discount_percentage']),
            
            # Stock indexes
            models.Index(fields=['stock_quantity']),
            models.Index(fields=['is_active', 'stock_quantity']),
            
            # Feature indexes
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['is_new_arrival', 'is_active']),
            models.Index(fields=['is_bestseller', 'is_active']),
            models.Index(fields=['is_on_sale', 'is_active']),
            
            # Time-based indexes
            models.Index(fields=['sale_starts_at', 'sale_ends_at']),
            models.Index(fields=['new_arrival_until']),
            models.Index(fields=['created_at']),
            models.Index(fields=['publish_date']),
            
            # Performance indexes
            models.Index(fields=['visibility', 'is_active']),
            models.Index(fields=['display_order']),
            models.Index(fields=['popularity_score']),
            models.Index(fields=['-view_count']),
            
            # Composite indexes for common queries
            models.Index(fields=['is_active', 'is_featured', '-created_at']),
            models.Index(fields=['category', 'is_active', '-popularity_score']),
            models.Index(fields=['brand', 'is_active', '-popularity_score']),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.name}-{self.sku}")
        
        # Auto-set is_on_sale based on sale_price and dates
        if self.sale_price and self.is_sale_active:
            self.is_on_sale = True
        elif not self.sale_price and self.discount_percentage == 0:
            self.is_on_sale = False
            
        super().save(*args, **kwargs)

    # ========================================================================
    # PRICING PROPERTIES
    # ========================================================================
    
    @property
    def is_sale_active(self):
        """Check if sale period is active"""
        if not self.sale_starts_at or not self.sale_ends_at:
            return True  # No time restriction
        
        now = timezone.now()
        return self.sale_starts_at <= now <= self.sale_ends_at
    
    @property
    def current_price(self):
        """Get the actual selling price considering sales"""
        # Priority: sale_price (if active) > discount_percentage > regular price
        if self.sale_price and self.is_sale_active:
            return self.sale_price
        return self.final_price
    
    @property
    def final_price(self):
        """Price after discount_percentage"""
        if self.discount_percentage > 0:
            return self.price - (self.price * self.discount_percentage / 100)
        return self.price
    
    @property
    def savings_amount(self):
        """Calculate savings amount"""
        return self.price - self.current_price
    
    @property
    def savings_percentage(self):
        """Calculate savings percentage"""
        if self.price > 0:
            return round(((self.price - self.current_price) / self.price) * 100, 2)
        return 0

    # ========================================================================
    # STATUS PROPERTIES
    # ========================================================================
    
    @property
    def is_new(self):
        """Check if product is still a new arrival"""
        if self.is_new_arrival:
            if self.new_arrival_until:
                return timezone.now() <= self.new_arrival_until
            return True
        return False
    
    @property
    def is_published(self):
        """Check if product is published"""
        if not self.is_active:
            return False
        
        if self.publish_date:
            return timezone.now() >= self.publish_date
        
        return True
    
    @property
    def is_low_stock(self):
        """Check if stock is low"""
        return 0 < self.stock_quantity <= self.low_stock_threshold

    @property
    def is_in_stock(self):
        """Check if product is in stock"""
        return self.stock_quantity > 0
    
    @property
    def can_purchase(self):
        """Check if product can be purchased"""
        if self.is_in_stock:
            return True
        return self.preorder_available or self.backorder_allowed
    
    @property
    def stock_status(self):
        """Get human-readable stock status"""
        if self.is_in_stock:
            if self.is_low_stock:
                return 'low_stock'
            return 'in_stock'
        
        if self.preorder_available:
            return 'preorder'
        
        if self.backorder_allowed:
            return 'backorder'
        
        if self.restock_date:
            return 'out_of_stock_restock_scheduled'
        
        return 'out_of_stock'

    # ========================================================================
    # WAREHOUSE INTEGRATION PROPERTIES
    # ========================================================================
    
    @property
    def warehouse_stock_summary(self):
        """Get stock across all warehouses"""
        try:
            from inventory.models import WarehouseStock
            from django.db.models import Sum, Count, F
            return WarehouseStock.objects.filter(product=self).aggregate(
                total_quantity=Sum('quantity'),
                total_reserved=Sum('reserved_quantity'),
                total_damaged=Sum('damaged_quantity'),
                total_available=Sum(F('quantity') - F('reserved_quantity') - F('damaged_quantity')),
                warehouse_count=Count('warehouse', distinct=True)
            )
        except ImportError:
            return None

    @property
    def available_quantity(self):
        """Total available across all warehouses"""
        try:
            from inventory.models import WarehouseStock
            from django.db.models import Sum, F
            result = WarehouseStock.objects.filter(product=self).aggregate(
                total=Sum(F('quantity') - F('reserved_quantity') - F('damaged_quantity'))
            )
            return result['total'] or 0
        except ImportError:
            return self.stock_quantity

    def update_from_warehouse_stock(self):
        """Sync product stock from warehouse totals"""
        try:
            from inventory.models import WarehouseStock
            from django.db.models import Sum
            total = WarehouseStock.objects.filter(product=self).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            self.stock_quantity = total
            self.save(update_fields=['stock_quantity'])
        except ImportError:
            pass

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def increment_view_count(self):
        """Increment view count atomically"""
        from django.db.models import F
        Product.objects.filter(pk=self.pk).update(view_count=F('view_count') + 1)
    
    def get_related_products(self, limit=4):
        """Get related products from same category"""
        return Product.objects.filter(
            category=self.category,
            is_active=True
        ).exclude(pk=self.pk).order_by('-popularity_score')[:limit]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/')
    alt_text = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-is_primary']
        indexes = [
            models.Index(fields=['product', 'is_primary']),
            models.Index(fields=['product', 'order']),
        ]

    def save(self, *args, **kwargs):
        if self.is_primary:
            # Ensure only one primary image per product
            ProductImage.objects.filter(product=self.product, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} - Image {self.order}"


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='reviews')
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=255)
    comment = models.TextField()
    is_verified_purchase = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False)
    
    # Additional review fields
    helpful_count = models.IntegerField(default=0, help_text='Number of users who found this helpful')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['product', 'customer']
        indexes = [
            models.Index(fields=['product', 'is_approved']),
            models.Index(fields=['customer', 'is_approved']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['rating', 'is_approved']),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.rating}★ by {self.customer.user.email}"