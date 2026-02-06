import django_filters
from django.db.models import Q, F
from django.utils import timezone
from .models import Product


class ProductFilter(django_filters.FilterSet):
    # Price filters
    min_price = django_filters.NumberFilter(field_name='price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='price', lookup_expr='lte')
    min_current_price = django_filters.NumberFilter(method='filter_min_current_price')
    max_current_price = django_filters.NumberFilter(method='filter_max_current_price')
    
    # Category and Brand filters
    category = django_filters.CharFilter(field_name='category__slug')
    brand = django_filters.CharFilter(field_name='brand__slug')
    
    # Stock filters
    in_stock = django_filters.BooleanFilter(method='filter_in_stock')
    low_stock = django_filters.BooleanFilter(method='filter_low_stock')
    
    # Sale and promotion filters
    on_sale = django_filters.BooleanFilter(method='filter_on_sale')
    is_featured = django_filters.BooleanFilter(field_name='is_featured')
    is_new = django_filters.BooleanFilter(method='filter_new_arrivals')
    is_bestseller = django_filters.BooleanFilter(field_name='is_bestseller')
    
    # Product characteristics
    condition = django_filters.ChoiceFilter(
        field_name='condition',
        choices=Product.CONDITION_CHOICES
    )
    visibility = django_filters.ChoiceFilter(
        field_name='visibility',
        choices=Product.VISIBILITY_CHOICES
    )
    shipping_class = django_filters.ChoiceFilter(
        field_name='shipping_class',
        choices=Product.SHIPPING_CLASS_CHOICES
    )
    
    # Availability filters
    preorder_available = django_filters.BooleanFilter(field_name='preorder_available')
    backorder_allowed = django_filters.BooleanFilter(field_name='backorder_allowed')
    
    # Warranty filter
    has_warranty = django_filters.BooleanFilter(method='filter_has_warranty')
    min_warranty = django_filters.NumberFilter(field_name='warranty_period', lookup_expr='gte')
    
    # Rating filter
    min_rating = django_filters.NumberFilter(method='filter_min_rating')
    
    # Discount filter
    min_discount = django_filters.NumberFilter(field_name='discount_percentage', lookup_expr='gte')

    class Meta:
        model = Product
        fields = [
            'category', 'brand', 'condition', 'is_featured', 
            'is_bestseller', 'visibility', 'shipping_class',
            'preorder_available', 'backorder_allowed'
        ]

    def filter_in_stock(self, queryset, name, value):
        """Filter products that are in stock"""
        if value:
            return queryset.filter(stock_quantity__gt=0)
        return queryset.filter(stock_quantity=0)
    
    def filter_low_stock(self, queryset, name, value):
        """Filter products with low stock"""
        if value:
            return queryset.filter(
                stock_quantity__lte=F('low_stock_threshold'),
                stock_quantity__gt=0
            )
        return queryset
    
    def filter_on_sale(self, queryset, name, value):
        """Filter products currently on sale"""
        if value:
            now = timezone.now()
            return queryset.filter(
                is_on_sale=True
            ).filter(
                Q(sale_ends_at__isnull=True) | Q(sale_ends_at__gte=now)
            )
        return queryset.filter(is_on_sale=False)
    
    def filter_new_arrivals(self, queryset, name, value):
        """Filter new arrival products that haven't expired"""
        if value:
            now = timezone.now()
            return queryset.filter(
                is_new_arrival=True
            ).filter(
                Q(new_arrival_until__isnull=True) | Q(new_arrival_until__gte=now)
            )
        return queryset.filter(is_new_arrival=False)
    
    def filter_has_warranty(self, queryset, name, value):
        """Filter products with/without warranty"""
        if value:
            return queryset.filter(warranty_period__gt=0)
        return queryset.filter(warranty_period=0)
    
    def filter_min_current_price(self, queryset, name, value):
        """Filter by minimum current/sale price"""
        # This filters based on actual selling price (considering sales)
        from django.db.models import Case, When, F
        
        return queryset.annotate(
            current_price=Case(
                When(is_on_sale=True, sale_price__isnull=False, then=F('sale_price')),
                default=F('price')
            )
        ).filter(current_price__gte=value)
    
    def filter_max_current_price(self, queryset, name, value):
        """Filter by maximum current/sale price"""
        from django.db.models import Case, When, F
        
        return queryset.annotate(
            current_price=Case(
                When(is_on_sale=True, sale_price__isnull=False, then=F('sale_price')),
                default=F('price')
            )
        ).filter(current_price__lte=value)
    
    def filter_min_rating(self, queryset, name, value):
        """Filter products by minimum average rating"""
        from django.db.models import Avg
        
        return queryset.annotate(
            avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True))
        ).filter(avg_rating__gte=value)