from django.contrib import admin
from django.db.models import Sum, F
from django.utils.html import format_html
from .models import Category, Brand, Product, ProductImage, Review


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'parent', 'display_order', 'is_active', 'created_at']
    list_filter = ['is_active', 'parent', 'created_at']
    search_fields = ['name', 'description', 'seo_keywords']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_active', 'display_order']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'parent', 'image', 'icon')
        }),
        ('Display', {
            'fields': ('display_order', 'is_active')
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description', 'seo_keywords'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'website', 'display_order', 'is_featured', 'is_active', 'created_at']
    list_filter = ['is_active', 'is_featured', 'created_at']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_active', 'is_featured', 'display_order']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'logo', 'description', 'website')
        }),
        ('Display', {
            'fields': ('display_order', 'is_active', 'is_featured')
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description'),
            'classes': ('collapse',)
        }),
    )


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'alt_text', 'is_primary', 'order']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'sku', 'category', 'brand', 'current_price_display', 
        'stock_status_display', 'stock_quantity', 'warehouse_total',
        'badge_display', 'is_featured', 'is_active', 'view_count'
    ]
    list_filter = [
        'category', 'brand', 'condition', 'is_featured', 'is_active',
        'is_new_arrival', 'is_bestseller', 'is_on_sale',
        'visibility', 'shipping_class', 'created_at'
    ]
    search_fields = ['name', 'sku', 'description', 'seo_keywords', 'manufacturer', 'model_number']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_featured', 'is_active']
    inlines = [ProductImageInline]
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'sku', 'description', 'short_description', 
                      'category', 'brand', 'manufacturer', 'model_number')
        }),
        ('Pricing', {
            'fields': ('price', 'cost_price', 'discount_percentage', 
                      'sale_price', 'sale_starts_at', 'sale_ends_at')
        }),
        ('Product Classification', {
            'fields': ('is_new_arrival', 'new_arrival_until', 'is_bestseller', 
                      'is_on_sale', 'badge_text', 'badge_color')
        }),
        ('Specifications', {
            'fields': ('specifications', 'weight', 'dimensions', 'condition')
        }),
        ('Warranty', {
            'fields': ('warranty_period', 'warranty_details'),
            'classes': ('collapse',)
        }),
        ('Inventory', {
            'fields': ('stock_quantity', 'low_stock_threshold', 
                      'preorder_available', 'preorder_release_date',
                      'backorder_allowed', 'restock_date'),
            'description': 'Note: Updating stock_quantity will automatically sync with warehouse stocks.'
        }),
        ('Shipping', {
            'fields': ('requires_shipping', 'is_fragile', 'shipping_class', 
                      'max_quantity_per_order'),
            'classes': ('collapse',)
        }),
        ('Display & Performance', {
            'fields': ('display_order', 'view_count', 'popularity_score')
        }),
        ('Variants', {
            'fields': ('has_variants', 'parent_product'),
            'classes': ('collapse',)
        }),
        ('Status & Visibility', {
            'fields': ('is_active', 'is_featured', 'visibility', 'publish_date')
        }),
        ('SEO', {
            'fields': ('meta_title', 'meta_description', 'seo_keywords', 
                      'canonical_url', 'og_image'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['warehouse_stock_info', 'view_count']

    def get_fieldsets(self, request, obj=None):
        """Add warehouse info for existing products"""
        fieldsets = list(super().get_fieldsets(request, obj))
        
        if obj and obj.pk:  # Only for existing products
            # Add warehouse info to Inventory section (index 5)
            inventory_fields = list(fieldsets[5][1]['fields'])
            if 'warehouse_stock_info' not in inventory_fields:
                inventory_fields.append('warehouse_stock_info')
                fieldsets[5] = (
                    fieldsets[5][0],
                    {**fieldsets[5][1], 'fields': tuple(inventory_fields)}
                )
        
        return fieldsets

    def current_price_display(self, obj):
        """Display current price with sale indicator"""
        price = obj.current_price
        if obj.sale_price and obj.is_sale_active:
            return format_html(
                '<span style="color: red; font-weight: bold;">KSh {:.2f}</span> '
                '<span style="text-decoration: line-through; color: gray;">KSh {:.2f}</span>',
                price, obj.price
            )
        elif obj.discount_percentage > 0:
            return format_html(
                '<span style="color: orange; font-weight: bold;">KSh {:.2f}</span> '
                '<span style="text-decoration: line-through; color: gray;">KSh {:.2f}</span> '
                '<span style="color: green;">(-{:.0f}%)</span>',
                price, obj.price, obj.discount_percentage
            )
        return f"KSh {price:.2f}"
    current_price_display.short_description = 'Current Price'

    def stock_status_display(self, obj):
        """Display stock status with color coding"""
        status = obj.stock_status
        colors = {
            'in_stock': 'green',
            'low_stock': 'orange',
            'out_of_stock': 'red',
            'preorder': 'blue',
            'backorder': 'purple',
            'out_of_stock_restock_scheduled': 'brown'
        }
        labels = {
            'in_stock': 'In Stock',
            'low_stock': 'Low Stock',
            'out_of_stock': 'Out of Stock',
            'preorder': 'Preorder',
            'backorder': 'Backorder',
            'out_of_stock_restock_scheduled': 'Restocking'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(status, 'gray'),
            labels.get(status, status)
        )
    stock_status_display.short_description = 'Stock Status'

    def badge_display(self, obj):
        """Display product badges"""
        badges = []
        
        if obj.is_new:
            badges.append('<span style="background: #4CAF50; color: white; padding: 2px 6px; border-radius: 3px; margin-right: 3px;">NEW</span>')
        
        if obj.is_bestseller:
            badges.append('<span style="background: #FF9800; color: white; padding: 2px 6px; border-radius: 3px; margin-right: 3px;">BESTSELLER</span>')
        
        if obj.is_on_sale:
            badges.append('<span style="background: #F44336; color: white; padding: 2px 6px; border-radius: 3px; margin-right: 3px;">SALE</span>')
        
        if obj.badge_text:
            badges.append(f'<span style="background: {obj.badge_color}; color: white; padding: 2px 6px; border-radius: 3px; margin-right: 3px;">{obj.badge_text}</span>')
        
        return format_html(''.join(badges)) if badges else '-'
    badge_display.short_description = 'Badges'

    def warehouse_total(self, obj):
        """Display total stock across all warehouses"""
        try:
            from inventory.models import WarehouseStock
            total = WarehouseStock.objects.filter(product=obj).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            return total
        except ImportError:
            return 'N/A'
    warehouse_total.short_description = 'Warehouse Total'

    def warehouse_stock_info(self, obj):
        """Display detailed warehouse stock information"""
        try:
            from inventory.models import WarehouseStock
            from django.utils.html import format_html
            
            stocks = WarehouseStock.objects.filter(product=obj).select_related('warehouse')
            
            if not stocks.exists():
                return format_html('<p style="color: orange;">No warehouse stocks found</p>')
            
            html = '<table style="width: 100%; border-collapse: collapse;">'
            html += '<tr style="background-color: #f0f0f0;"><th>Warehouse</th><th>Quantity</th><th>Reserved</th><th>Damaged</th><th>Available</th></tr>'
            
            for stock in stocks:
                available = stock.quantity - stock.reserved_quantity - stock.damaged_quantity
                html += f'''<tr style="border-bottom: 1px solid #ddd;">
                    <td>{stock.warehouse.name}</td>
                    <td>{stock.quantity}</td>
                    <td>{stock.reserved_quantity}</td>
                    <td>{stock.damaged_quantity}</td>
                    <td><strong>{available}</strong></td>
                </tr>'''
            
            html += '</table>'
            return format_html(html)
        except ImportError:
            return format_html('<p style="color: gray;">Inventory module not available</p>')
    
    warehouse_stock_info.short_description = 'Warehouse Stock Details'

    def save_model(self, request, obj, form, change):
        """Override save to handle warehouse sync"""
        super().save_model(request, obj, form, change)
        
        if change and 'stock_quantity' in form.changed_data:
            self.message_user(
                request, 
                f'Product stock updated. Warehouse stocks have been synchronized.',
                level='success'
            )


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ['product', 'alt_text', 'is_primary', 'order', 'created_at']
    list_filter = ['is_primary', 'created_at']
    search_fields = ['product__name', 'alt_text']
    list_editable = ['is_primary', 'order']


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'customer', 'rating', 'title', 'helpful_count',
                    'is_verified_purchase', 'is_approved', 'created_at']
    list_filter = ['rating', 'is_verified_purchase', 'is_approved', 'created_at']
    search_fields = ['product__name', 'customer__user__email', 'title', 'comment']
    list_editable = ['is_approved']
    date_hierarchy = 'created_at'
    readonly_fields = ['customer', 'product', 'helpful_count', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Review Information', {
            'fields': ('product', 'customer', 'rating', 'title', 'comment')
        }),
        ('Engagement', {
            'fields': ('helpful_count',)
        }),
        ('Status', {
            'fields': ('is_verified_purchase', 'is_approved')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        # Reviews should only be created through the API
        return False