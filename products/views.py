from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Avg, Count, F, Prefetch, Sum, Case, When, DecimalField
from django.db import models
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from .models import Category, Brand, Product, ProductImage, Review
from .serializers import (CategorySerializer, BrandSerializer, ProductListSerializer, 
                          ProductDetailSerializer, ProductImageSerializer, ReviewSerializer,
                          ProductCreateUpdateSerializer, CategoryCreateUpdateSerializer,
                          BrandCreateUpdateSerializer)
from .filters import ProductFilter
from .permissions import IsAdminOrReadOnly
from backend.pagination import (
    StandardResultsSetPagination, 
    ProductCursorPagination,
    SmallResultsSetPagination,
    LargeResultsSetPagination
)
from django.utils import timezone
from rest_framework.exceptions import NotFound


class CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for Category CRUD operations."""
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    
    # Use standard pagination
    pagination_class = StandardResultsSetPagination

    @method_decorator(cache_page(60 * 15))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CategoryCreateUpdateSerializer
        return CategorySerializer

    def perform_destroy(self, instance):
        """Soft delete by setting is_active to False"""
        instance.is_active = False
        instance.save()

    @action(detail=True, methods=['get'])
    def products(self, request, slug=None):
        """Get all products for a specific category"""
        category = self.get_object()
        products = Product.objects.filter(
            category=category, 
            is_active=True
        ).select_related('category', 'brand').prefetch_related(
            'images',
            Prefetch('reviews', queryset=Review.objects.filter(is_approved=True))
        ).annotate(
            annotated_avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
            annotated_review_count=Count('reviews', filter=Q(reviews__is_approved=True))
        )
        
        # Use pagination for category products
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class BrandViewSet(viewsets.ModelViewSet):
    """ViewSet for Brand CRUD operations."""
    queryset = Brand.objects.filter(is_active=True)
    serializer_class = BrandSerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    
    # Use standard pagination
    pagination_class = StandardResultsSetPagination

    @method_decorator(cache_page(60 * 15))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return BrandCreateUpdateSerializer
        return BrandSerializer

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()

    @action(detail=True, methods=['get'])
    def products(self, request, slug=None):
        """Get all products for a specific brand"""
        brand = self.get_object()
        products = Product.objects.filter(
            brand=brand, 
            is_active=True
        ).select_related('category', 'brand').prefetch_related(
            'images',
            Prefetch('reviews', queryset=Review.objects.filter(is_approved=True))
        ).annotate(
            annotated_avg_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
            annotated_review_count=Count('reviews', filter=Q(reviews__is_approved=True))
        )
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Product CRUD operations with optimized queries.
    Uses cursor pagination for better performance with large datasets.
    """
    queryset = Product.objects.filter(is_active=True)
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'slug'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'description', 'sku', 'brand__name']
    ordering_fields = ['price', 'created_at', 'name', 'stock_quantity']
    ordering = ['-created_at']
    
    # CRITICAL: Use cursor pagination for products (handles large datasets better)
    pagination_class = ProductCursorPagination

    def get_object(self):
        """
        Override to support both exact slug match and prefix-based fallback.
        Handles cases where external links use a shorter version of the slug.
        """
        queryset = self.get_queryset()
        slug = self.kwargs.get(self.lookup_field, '')

        # Strip any accidental query string bleed (e.g. slug?utm_source=...)
        slug = slug.split('?')[0]

        # 1. Try exact match first (fast path)
        try:
            obj = queryset.get(slug=slug)
            self.check_object_permissions(self.request, obj)
            return obj
        except Product.DoesNotExist:
            pass

        # 2. Fallback: slug starts with the given value (handles truncated slugs)
        matches = queryset.filter(slug__startswith=slug)
        if matches.count() >= 1:
            obj = matches.first()
            self.check_object_permissions(self.request, obj)
            return obj

        # 3. Fallback: recursive slug truncation
        parts = slug.split('-')
        print(parts)
        while len(parts) > 1:
            parts = parts[:-1]
            truncated = '-'.join(parts)
            
            # startswith truncated slug
            matches = queryset.filter(slug__startswith=truncated)
            if matches.count() >= 1:
                obj = matches.first()
                self.check_object_permissions(self.request, obj)
                return obj

        # 4. Last resort: slug contains any part of the original slug
        matches = queryset.filter(slug__icontains=slug)
        if matches.exists():
            obj = matches.first()
            self.check_object_permissions(self.request, obj)
            return obj

        # 5. Nothing found
        raise NotFound(detail="PRODUCT NOT FOUND")

    def get_queryset(self):
        """
        Optimized queryset with all necessary prefetching.
        Eliminates N+1 queries completely.
        """
        queryset = super().get_queryset()
        
        # Select related for foreign keys
        queryset = queryset.select_related('category', 'brand')
        
        # Prefetch images efficiently
        queryset = queryset.prefetch_related(
            Prefetch(
                'images',
                queryset=ProductImage.objects.order_by('-is_primary', 'order')
            )
        )
        
        # Prefetch approved reviews
        queryset = queryset.prefetch_related(
            Prefetch(
                'reviews',
                queryset=Review.objects.filter(is_approved=True).select_related('customer__user'),
                to_attr='approved_reviews'
            )
        )
        
        # Annotate with aggregated data (eliminates N+1 for ratings/counts)
        queryset = queryset.annotate(
            annotated_avg_rating=Avg(
                'reviews__rating', 
                filter=Q(reviews__is_approved=True)
            ),
            annotated_review_count=Count(
                'reviews', 
                filter=Q(reviews__is_approved=True),
                distinct=True
            )
        )
        
        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProductCreateUpdateSerializer
        return ProductDetailSerializer

    @method_decorator(cache_page(60 * 5))
    def list(self, request, *args, **kwargs):
        """Cached list view with smart cache key"""
        # Create cache key from query params
        cache_key = f"products_list_{hash(frozenset(request.GET.items()))}"
        
        # Try to get from cache
        cached_response = cache.get(cache_key, version='pagination')
        if cached_response:
            return Response(cached_response)
        
        # Get fresh data
        response = super().list(request, *args, **kwargs)
        
        # Cache the response data
        cache.set(cache_key, response.data, timeout=60 * 5, version='pagination')
        
        return response

    def perform_create(self, serializer):
        """Clear cache when creating products"""
        serializer.save()
        cache.delete_pattern('products_list_*', version='pagination')

    def perform_update(self, serializer):
        """Clear cache when updating products"""
        serializer.save()
        cache.delete_pattern('products_list_*', version='pagination')

    def perform_destroy(self, instance):
        """Soft delete and clear cache"""
        instance.is_active = False
        instance.save()
        cache.delete_pattern('products_list_*', version='pagination')

    @action(detail=False, methods=['get'])
    def featured(self, request):
        """Get featured products with small pagination"""
        products = self.get_queryset().filter(is_featured=True)
        
        # Use smaller pagination for featured items
        paginator = SmallResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Get products with low stock"""
        products = self.get_queryset().filter(
            stock_quantity__lte=F('low_stock_threshold')
        )
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=False, methods=['get'])
    def on_sale(self, request):
        """Get products that are on sale"""
        products = self.get_queryset().filter(discount_percentage__gt=0)
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def add_image(self, request, slug=None):
        """Add an image to a product"""
        product = self.get_object()
        serializer = ProductImageSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(product=product)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_stock(self, request, slug=None):
        """Update product stock quantity"""
        product = self.get_object()
        quantity = request.data.get('stock_quantity')
        
        if quantity is None:
            return Response(
                {'error': 'stock_quantity is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            quantity = int(quantity)
            if quantity < 0:
                return Response(
                    {'error': 'stock_quantity must be non-negative'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            product.stock_quantity = quantity
            product.save()
            
            # Clear cache
            cache.delete_pattern('products_list_*', version='pagination')
            
            return Response({
                'message': 'Stock updated successfully',
                'stock_quantity': product.stock_quantity,
                'is_in_stock': product.is_in_stock,
                'is_low_stock': product.is_low_stock
            })
        except ValueError:
            return Response(
                {'error': 'Invalid stock_quantity value'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    # ============================================================================
    # NEW PRODUCT DISCOVERY ENDPOINTS
    # ============================================================================

    @action(detail=False, methods=['get'])
    def new_arrivals(self, request):
        """Get new arrival products that haven't expired"""
        now = timezone.now()
        products = self.get_queryset().filter(
            is_new_arrival=True
        ).filter(
            Q(new_arrival_until__isnull=True) | Q(new_arrival_until__gte=now)
        ).order_by('-created_at')
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


    @action(detail=False, methods=['get'])
    def bestsellers(self, request):
        """Get bestseller products"""
        products = self.get_queryset().filter(
            is_bestseller=True
        ).order_by('-popularity_score')
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


    @action(detail=False, methods=['get'])
    def trending(self, request):
        """Get trending products based on popularity score"""
        products = self.get_queryset().filter(
            popularity_score__gt=0
        ).order_by('-popularity_score', '-view_count')[:50]
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


    @action(detail=False, methods=['get'])
    def deals_of_the_day(self, request):
        """Get products with highest discounts currently on sale"""
        now = timezone.now()
        
        products = self.get_queryset().filter(
            is_on_sale=True
        ).filter(
            Q(sale_ends_at__isnull=True) | Q(sale_ends_at__gte=now)
        ).order_by('-discount_percentage', '-popularity_score')[:20]
        
        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data)


    @action(detail=False, methods=['get'])
    def preorder(self, request):
        """Get products available for preorder"""
        products = self.get_queryset().filter(
            preorder_available=True,
            stock_quantity=0
        ).order_by('preorder_release_date')
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


    @action(detail=False, methods=['get'])
    def coming_soon(self, request):
        """Get products scheduled to be published"""
        now = timezone.now()
        
        # Note: This shows inactive products, so you may want to restrict to admins
        products = Product.objects.filter(
            is_active=False,
            publish_date__isnull=False,
            publish_date__gte=now
        ).select_related('category', 'brand').prefetch_related('images').order_by('publish_date')
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


    # ============================================================================
    # UPDATED on_sale ACTION (replace the existing one)
    # ============================================================================

    @action(detail=False, methods=['get'])
    def on_sale(self, request):
        """Get products that are currently on sale"""
        now = timezone.now()
        
        products = self.get_queryset().filter(
            is_on_sale=True
        ).filter(
            Q(sale_ends_at__isnull=True) | Q(sale_ends_at__gte=now)
        ).order_by('-discount_percentage')
        
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(products, request)
        serializer = ProductListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


    # ============================================================================
    # PRODUCT INTERACTION ENDPOINTS
    # ============================================================================

    @action(detail=True, methods=['post'], permission_classes=[AllowAny])
    def increment_view(self, request, slug=None):
        """Increment product view count (public endpoint)"""
        product = self.get_object()
        product.increment_view_count()
        
        return Response({
            'message': 'View count updated',
            'view_count': product.view_count
        })


    @action(detail=True, methods=['get'])
    def related(self, request, slug=None):
        """Get related products based on category and brand"""
        product = self.get_object()
        related_products = product.get_related_products(limit=8)
        
        serializer = ProductListSerializer(related_products, many=True)
        return Response(serializer.data)


    @action(detail=True, methods=['get'])
    def check_availability(self, request, slug=None):
        """Check detailed product availability and stock status"""
        product = self.get_object()
        
        return Response({
            'sku': product.sku,
            'name': product.name,
            'stock_quantity': product.stock_quantity,
            'stock_status': product.stock_status,
            'can_purchase': product.can_purchase,
            'is_in_stock': product.is_in_stock,
            'is_low_stock': product.is_low_stock,
            'low_stock_threshold': product.low_stock_threshold,
            'preorder_available': product.preorder_available,
            'preorder_release_date': product.preorder_release_date,
            'backorder_allowed': product.backorder_allowed,
            'restock_date': product.restock_date,
            'max_quantity_per_order': product.max_quantity_per_order,
        })


    # ============================================================================
    # ADMIN-FOCUSED ENDPOINTS
    # ============================================================================

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def toggle_featured(self, request, slug=None):
        """Toggle featured status of a product"""
        product = self.get_object()
        product.is_featured = not product.is_featured
        product.save(update_fields=['is_featured'])
        
        # Clear cache
        cache.delete_pattern('products_list_*', version='pagination')
        
        return Response({
            'message': 'Featured status updated',
            'is_featured': product.is_featured
        })


    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def toggle_bestseller(self, request, slug=None):
        """Manually toggle bestseller status"""
        product = self.get_object()
        product.is_bestseller = not product.is_bestseller
        product.save(update_fields=['is_bestseller'])
        
        # Clear cache
        cache.delete_pattern('products_list_*', version='pagination')
        
        return Response({
            'message': 'Bestseller status updated',
            'is_bestseller': product.is_bestseller
        })


    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated])
    def update_visibility(self, request, slug=None):
        """Update product visibility"""
        product = self.get_object()
        visibility = request.data.get('visibility')
        
        if visibility not in dict(Product.VISIBILITY_CHOICES):
            return Response(
                {'error': 'Invalid visibility choice'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        product.visibility = visibility
        product.save(update_fields=['visibility'])
        
        return Response({
            'message': 'Visibility updated',
            'visibility': product.visibility
        })


    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def schedule_publish(self, request, slug=None):
        """Schedule a product to be published at a specific date"""
        product = self.get_object()
        publish_date = request.data.get('publish_date')
        
        if not publish_date:
            return Response(
                {'error': 'publish_date is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from django.utils.dateparse import parse_datetime
            publish_datetime = parse_datetime(publish_date)
            
            if not publish_datetime:
                raise ValueError("Invalid datetime format")
            
            product.publish_date = publish_datetime
            product.is_active = False  # Deactivate until publish date
            product.save(update_fields=['publish_date', 'is_active'])
            
            return Response({
                'message': 'Product scheduled for publishing',
                'publish_date': product.publish_date,
                'is_active': product.is_active
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class ReviewViewSet(viewsets.ModelViewSet):
    """ViewSet for Review CRUD operations with optimized queries."""
    queryset = Review.objects.filter(is_approved=True)
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['product', 'rating']
    ordering_fields = ['created_at', 'rating']
    ordering = ['-created_at']
    
    # Use small pagination for reviews
    pagination_class = SmallResultsSetPagination

    def get_queryset(self):
        """Optimized queryset with prefetching"""
        queryset = super().get_queryset()  # Gets the base queryset
        return queryset.select_related(
            'customer__user',
            'product'
        )

    def perform_create(self, serializer):
        """Create a new review for authenticated user"""
        serializer.save(customer=self.request.user.customer)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_reviews(self, request):
        """Get all reviews by the current user"""
        reviews = Review.objects.filter(
            customer=request.user.customer
        ).select_related('customer__user', 'product')
        
        # Paginate user's reviews
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(reviews, request)
        serializer = self.get_serializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def mark_helpful(self, request, pk=None):
        """Mark a review as helpful"""
        review = self.get_object()
        
        # Increment helpful count
        from django.db.models import F
        Review.objects.filter(pk=review.pk).update(helpful_count=F('helpful_count') + 1)
        
        # Refresh from database to get updated count
        review.refresh_from_db()
        
        return Response({
            'message': 'Review marked as helpful',
            'helpful_count': review.helpful_count
        })


    @action(detail=False, methods=['get'])
    def pending(self, request):
        """Get pending reviews (admin only)"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Admin access required'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        reviews = Review.objects.filter(
            is_approved=False
        ).select_related('customer__user', 'product').order_by('-created_at')
        
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(reviews, request)
        serializer = self.get_serializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def approve(self, request, pk=None):
        """Approve a review (admin only)"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Admin access required'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        review = self.get_object()
        review.is_approved = True
        review.save(update_fields=['is_approved'])
        
        # Send approval notification
        from .tasks import send_review_approval_notification
        send_review_approval_notification.delay(review.id)
        
        return Response({
            'message': 'Review approved',
            'is_approved': review.is_approved
        })