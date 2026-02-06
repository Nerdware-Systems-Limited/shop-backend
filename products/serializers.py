from rest_framework import serializers
from django.db import models
from django.utils import timezone
from .models import Category, Brand, Product, ProductImage, Review


# ============================================================================
# CATEGORY SERIALIZERS
# ============================================================================

class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'slug', 'description', 'image', 'icon', 'parent', 
            'children', 'is_active', 'display_order', 'product_count', 
            'meta_title', 'meta_description', 'seo_keywords',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']

    def get_children(self, obj):
        if obj.children.exists():
            return CategorySerializer(
                obj.children.filter(is_active=True).order_by('display_order', 'name'), 
                many=True
            ).data
        return []

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class CategoryCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating categories"""
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'description', 'image', 'icon', 'parent', 
            'is_active', 'display_order',
            'meta_title', 'meta_description', 'seo_keywords'
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']

    def validate_name(self, value):
        """Ensure category name is unique"""
        instance = self.instance
        if instance and instance.name == value:
            return value
        
        if Category.objects.filter(name=value).exists():
            raise serializers.ValidationError("Category with this name already exists")
        return value


# ============================================================================
# BRAND SERIALIZERS
# ============================================================================

class BrandSerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Brand
        fields = [
            'id', 'name', 'slug', 'logo', 'description', 'website', 
            'is_active', 'is_featured', 'display_order', 'product_count',
            'meta_title', 'meta_description', 'created_at'
        ]
        read_only_fields = ['slug', 'created_at']

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class BrandCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating brands"""
    
    class Meta:
        model = Brand
        fields = [
            'id', 'name', 'logo', 'description', 'website', 
            'is_active', 'is_featured', 'display_order',
            'meta_title', 'meta_description'
        ]
        read_only_fields = ['slug', 'created_at']

    def validate_name(self, value):
        """Ensure brand name is unique"""
        instance = self.instance
        if instance and instance.name == value:
            return value
        
        if Brand.objects.filter(name=value).exists():
            raise serializers.ValidationError("Brand with this name already exists")
        return value


# ============================================================================
# PRODUCT IMAGE SERIALIZER
# ============================================================================

class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['id', 'image', 'alt_text', 'is_primary', 'order', 'created_at']
        read_only_fields = ['created_at']


# ============================================================================
# REVIEW SERIALIZERS
# ============================================================================

class ReviewSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.user.get_full_name', read_only=True)
    customer_email = serializers.EmailField(source='customer.user.email', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_slug = serializers.CharField(source='product.slug', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'product', 'product_name', 'product_slug',
            'customer', 'customer_name', 'customer_email', 
            'rating', 'title', 'comment', 
            'helpful_count',
            'is_verified_purchase', 'is_approved', 
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'customer', 'customer_name', 'customer_email', 
            'product_name', 'product_slug',
            'is_verified_purchase', 'is_approved', 'helpful_count',
            'created_at', 'updated_at'
        ]

    def validate_rating(self, value):
        """Ensure rating is between 1 and 5"""
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return value

    def validate(self, data):
        """Check if user has already reviewed this product"""
        request = self.context.get('request')
        if request and request.method == 'POST':
            product = data.get('product')
            if Review.objects.filter(product=product, customer=request.user.customer).exists():
                raise serializers.ValidationError("You have already reviewed this product")
        return data


# ============================================================================
# PRODUCT SERIALIZERS
# ============================================================================

class ProductListSerializer(serializers.ModelSerializer):
    """Optimized serializer for product list views"""
    
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    brand_name = serializers.CharField(source='brand.name', read_only=True)
    brand_slug = serializers.CharField(source='brand.slug', read_only=True)
    primary_image = serializers.SerializerMethodField()
    
    # Use annotated fields for performance
    average_rating = serializers.DecimalField(
        max_digits=3, 
        decimal_places=1, 
        read_only=True, 
        source='annotated_avg_rating',
        coerce_to_string=False,
        allow_null=True
    )
    review_count = serializers.IntegerField(
        read_only=True, 
        source='annotated_review_count',
        default=0
    )
    
    # Computed/property fields from model
    current_price = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        read_only=True
    )
    savings_amount = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        read_only=True
    )
    savings_percentage = serializers.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        read_only=True
    )
    stock_status = serializers.CharField(read_only=True)
    can_purchase = serializers.BooleanField(read_only=True)
    is_new = serializers.BooleanField(read_only=True)
    is_sale_active = serializers.BooleanField(read_only=True)
    
    # Badge information
    badges = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'short_description',
            'category_name', 'category_slug', 'brand_name', 'brand_slug',
            
            # Pricing
            'price', 'discount_percentage', 'sale_price', 
            'current_price', 'final_price', 'savings_amount', 'savings_percentage',
            
            # Stock & Availability
            'stock_quantity', 'stock_status', 'is_in_stock', 'is_low_stock', 
            'can_purchase', 'preorder_available', 'backorder_allowed',
            
            # Classification
            'is_featured', 'is_new', 'is_bestseller', 'is_on_sale', 'is_sale_active',
            'badges', 'condition',
            
            # Media & Reviews
            'primary_image', 'average_rating', 'review_count',
            
            # Metadata
            'view_count', 'popularity_score', 'created_at'
        ]

    def get_primary_image(self, obj):
        """Get primary image URL from prefetched images"""
        images = obj.images.all()
        
        for image in images:
            if image.is_primary:
                return image.image.url
        
        if images:
            return images[0].image.url
        
        return None
    
    def get_badges(self, obj):
        """Return list of active badges for product"""
        badges = []
        
        if obj.is_new:
            badges.append({
                'type': 'new_arrival',
                'text': 'NEW',
                'color': '#4CAF50'
            })
        
        if obj.is_bestseller:
            badges.append({
                'type': 'bestseller',
                'text': 'BESTSELLER',
                'color': '#FF9800'
            })
        
        if obj.is_on_sale and obj.is_sale_active:
            badges.append({
                'type': 'sale',
                'text': f'SAVE {int(obj.discount_percentage)}%',
                'color': '#F44336'
            })
        
        if obj.badge_text:
            badges.append({
                'type': 'custom',
                'text': obj.badge_text,
                'color': obj.badge_color or '#9C27B0'
            })
        
        return badges


class ProductDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for single product view"""
    
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    reviews = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    
    # Computed fields from model properties
    current_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    savings_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    savings_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    stock_status = serializers.CharField(read_only=True)
    can_purchase = serializers.BooleanField(read_only=True)
    is_new = serializers.BooleanField(read_only=True)
    is_sale_active = serializers.BooleanField(read_only=True)
    is_published = serializers.BooleanField(read_only=True)
    badges = serializers.SerializerMethodField()
    related_products = serializers.SerializerMethodField()
    is_in_stock = serializers.BooleanField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    
    # Warehouse info (if you have inventory app integrated)
    warehouse_stock_summary = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = ['slug', 'view_count', 'popularity_score', 'created_at', 'updated_at']

    def get_average_rating(self, obj):
        """Calculate average rating from approved reviews"""
        # Use prefetched reviews if available
        if hasattr(obj, 'approved_reviews'):
            reviews = obj.approved_reviews
        else:
            reviews = obj.reviews.filter(is_approved=True)
        
        if reviews:
            ratings = [review.rating for review in reviews]
            return round(sum(ratings) / len(ratings), 1) if ratings else None
        return None

    def get_review_count(self, obj):
        """Get count of approved reviews"""
        if hasattr(obj, 'approved_reviews'):
            return len(obj.approved_reviews)
        return obj.reviews.filter(is_approved=True).count()
    
    def get_reviews(self, obj):
        """Get approved reviews"""
        if hasattr(obj, 'approved_reviews'):
            reviews = obj.approved_reviews
        else:
            reviews = obj.reviews.filter(is_approved=True)
        
        return ReviewSerializer(reviews, many=True).data
    
    def get_badges(self, obj):
        """Return list of active badges"""
        badges = []
        
        if obj.is_new:
            badges.append({'type': 'new_arrival', 'text': 'NEW', 'color': '#4CAF50'})
        
        if obj.is_bestseller:
            badges.append({'type': 'bestseller', 'text': 'BESTSELLER', 'color': '#FF9800'})
        
        if obj.is_on_sale and obj.is_sale_active:
            badges.append({
                'type': 'sale', 
                'text': f'SAVE {int(obj.discount_percentage)}%', 
                'color': '#F44336'
            })
        
        if obj.badge_text:
            badges.append({
                'type': 'custom', 
                'text': obj.badge_text, 
                'color': obj.badge_color or '#9C27B0'
            })
        
        return badges
    
    def get_related_products(self, obj):
        """Get related products (same category, excluding current)"""
        related = obj.get_related_products(limit=4)
        return ProductListSerializer(related, many=True).data
    
    def get_warehouse_stock_summary(self, obj):
        """Get warehouse stock summary if available"""
        summary = obj.warehouse_stock_summary
        if summary:
            return {
                'total_quantity': summary.get('total_quantity', 0),
                'total_reserved': summary.get('total_reserved', 0),
                'total_damaged': summary.get('total_damaged', 0),
                'total_available': summary.get('total_available', 0),
                'warehouse_count': summary.get('warehouse_count', 0)
            }
        return None


class ProductCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating products"""
    
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'slug', 'sku', 'description', 'short_description',
            'category', 'brand', 'manufacturer', 'model_number',
            
            # Pricing
            'price', 'cost_price', 'discount_percentage',
            'sale_price', 'sale_starts_at', 'sale_ends_at',
            
            # Classification
            'is_new_arrival', 'new_arrival_until', 'is_bestseller', 'is_on_sale',
            'badge_text', 'badge_color',
            
            # Specifications
            'specifications', 'weight', 'dimensions', 'condition',
            
            # Warranty
            'warranty_period', 'warranty_details',
            
            # Inventory
            'stock_quantity', 'low_stock_threshold',
            'preorder_available', 'preorder_release_date',
            'backorder_allowed', 'restock_date',
            
            # Shipping
            'requires_shipping', 'is_fragile', 'shipping_class',
            'max_quantity_per_order',
            
            # Display
            'display_order',
            
            # Variants
            'has_variants', 'parent_product',
            
            # Status
            'is_active', 'is_featured', 'visibility', 'publish_date',
            
            # SEO
            'meta_title', 'meta_description', 'seo_keywords',
            'canonical_url', 'og_image',
            
            # Timestamps
            'created_at', 'updated_at'
        ]
        read_only_fields = ['slug', 'view_count', 'popularity_score', 'created_at', 'updated_at']

    def validate_sku(self, value):
        """Ensure SKU is unique"""
        instance = self.instance
        if instance and instance.sku == value:
            return value
        
        if Product.objects.filter(sku=value).exists():
            raise serializers.ValidationError("Product with this SKU already exists")
        return value

    def validate_price(self, value):
        """Ensure price is positive"""
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value

    def validate_stock_quantity(self, value):
        """Ensure stock quantity is non-negative"""
        if value < 0:
            raise serializers.ValidationError("Stock quantity cannot be negative")
        return value

    def validate(self, data):
        """Additional cross-field validation"""
        
        # Cost price validation
        cost_price = data.get('cost_price')
        price = data.get('price')
        
        if cost_price and price and cost_price > price:
            raise serializers.ValidationError({
                'cost_price': 'Cost price cannot be greater than selling price'
            })
        
        # Sale price validation
        sale_price = data.get('sale_price')
        if sale_price and price and sale_price >= price:
            raise serializers.ValidationError({
                'sale_price': 'Sale price must be less than regular price'
            })
        
        # Sale dates validation
        sale_starts_at = data.get('sale_starts_at')
        sale_ends_at = data.get('sale_ends_at')
        
        if sale_starts_at and sale_ends_at and sale_starts_at >= sale_ends_at:
            raise serializers.ValidationError({
                'sale_ends_at': 'Sale end date must be after start date'
            })
        
        # Discount percentage validation
        discount_percentage = data.get('discount_percentage', 0)
        if discount_percentage < 0 or discount_percentage > 100:
            raise serializers.ValidationError({
                'discount_percentage': 'Discount percentage must be between 0 and 100'
            })
        
        # Preorder validation
        preorder_available = data.get('preorder_available')
        preorder_release_date = data.get('preorder_release_date')
        
        if preorder_available and not preorder_release_date:
            raise serializers.ValidationError({
                'preorder_release_date': 'Preorder release date is required when preorder is available'
            })
        
        # Warranty validation
        warranty_period = data.get('warranty_period', 0)
        if warranty_period < 0:
            raise serializers.ValidationError({
                'warranty_period': 'Warranty period cannot be negative'
            })
        
        # Publish date validation
        publish_date = data.get('publish_date')
        if publish_date and publish_date < timezone.now():
            raise serializers.ValidationError({
                'publish_date': 'Publish date cannot be in the past'
            })
        
        return data