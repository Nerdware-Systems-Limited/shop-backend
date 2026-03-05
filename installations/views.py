from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Prefetch

from .models import VehicleMake, InstallationJob, InstalledItem, InstallationImage
from .serializers import (
    VehicleMakeSerializer,
    InstallationJobListSerializer,
    InstallationJobDetailSerializer,
    InstallationJobWriteSerializer,
    InstallationImageSerializer,
    InstalledItemSerializer,
    BulkImageUploadSerializer,
)
from .permissions import IsAdminOrReadOnly
from .filters import InstallationJobFilter
from backend.pagination import StandardResultsSetPagination, SmallResultsSetPagination


class VehicleMakeViewSet(viewsets.ModelViewSet):
    queryset = VehicleMake.objects.filter(is_active=True)
    serializer_class = VehicleMakeSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name']
    ordering = ['name']


class InstallationJobViewSet(viewsets.ModelViewSet):
    """
    Main viewset for installation jobs.

    list   → lightweight cards (for portfolio grid)
    detail → full job with all images and items
    """
    lookup_field = 'slug'
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = InstallationJobFilter
    search_fields = [
        'title', 'vehicle_model', 'vehicle_make__name',
        'customer_name', 'description', 'installed_items__name'
    ]
    ordering_fields = ['job_date', 'created_at', 'vehicle_model']
    ordering = ['-job_date']
    pagination_class = StandardResultsSetPagination

    # print("hey i work here")

    def get_queryset(self):
        qs = InstallationJob.objects.select_related('vehicle_make').prefetch_related(
            Prefetch(
                'images',
                queryset=InstallationImage.objects.order_by('image_type', 'order')
            ),
            Prefetch(
                'installed_items',
                queryset=InstalledItem.objects.select_related('product').order_by('order', 'category')
            ),
        )

        # Public-facing endpoints only show public jobs
        if not (self.request.user and self.request.user.is_staff):
            qs = qs.filter(is_public=True)

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return InstallationJobListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return InstallationJobWriteSerializer
        return InstallationJobDetailSerializer

    @action(detail=False, methods=['get'], url_path='featured')
    def featured(self, request):
        """Return featured jobs for homepage/portfolio showcase"""
        jobs = self.get_queryset().filter(is_featured=True, is_public=True)
        page = self.paginate_queryset(jobs)
        if page is not None:
            serializer = InstallationJobListSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = InstallationJobListSerializer(jobs, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='by-vehicle')
    def by_vehicle(self, request):
        """Group jobs by vehicle make — useful for a 'Browse by Car' page"""
        makes = VehicleMake.objects.filter(
            installation_jobs__is_public=True
        ).annotate(
            job_count=Count('installation_jobs')
        ).filter(job_count__gt=0)

        data = []
        for make in makes:
            jobs = self.get_queryset().filter(vehicle_make=make)
            data.append({
                'make': VehicleMakeSerializer(make).data,
                'job_count': make.job_count,
                'recent_jobs': InstallationJobListSerializer(
                    jobs[:4], many=True, context={'request': request}
                ).data
            })

        return Response(data)

    @action(detail=True, methods=['post'], url_path='upload-images',
            parser_classes=[MultiPartParser, FormParser])
    def upload_images(self, request, pk=None):
        """
        Upload one or more images to a job.
        Accepts: image_type (before/after/in_progress/detail), images[]
        """
        job = self.get_object()
        serializer = BulkImageUploadSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        image_type = serializer.validated_data['image_type']
        uploaded_images = serializer.validated_data['images']
        created = []

        for i, image_file in enumerate(uploaded_images):
            # First image of each type becomes primary if none exists
            is_primary = (
                i == 0 and
                not job.images.filter(image_type=image_type, is_primary=True).exists()
            )
            img = InstallationImage.objects.create(
                job=job,
                image=image_file,
                image_type=image_type,
                is_primary=is_primary,
                order=job.images.filter(image_type=image_type).count(),
            )
            created.append(img)

        return Response(
            InstallationImageSerializer(created, many=True, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['get'], url_path='items')
    def items(self, request, pk=None):
        """List all installed items for a job"""
        job = self.get_object()
        items = job.installed_items.select_related('product').order_by('order', 'category')
        serializer = InstalledItemSerializer(items, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='add-item')
    def add_item(self, request, pk=None):
        """Add a single item to an existing job"""
        job = self.get_object()
        serializer = InstalledItemSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(job=job)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class InstallationImageViewSet(viewsets.ModelViewSet):
    """Manage individual images — delete, reorder, set primary"""
    queryset = InstallationImage.objects.select_related('job')
    serializer_class = InstallationImageSerializer
    permission_classes = [IsAdminOrReadOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @action(detail=True, methods=['post'], url_path='set-primary')
    def set_primary(self, request, pk=None):
        """Set this image as primary for its type within its job"""
        image = self.get_object()
        # Unset other primaries of same type in this job
        InstallationImage.objects.filter(
            job=image.job, image_type=image.image_type
        ).update(is_primary=False)
        image.is_primary = True
        image.save(update_fields=['is_primary'])
        return Response({'status': 'primary image updated'})


class InstalledItemViewSet(viewsets.ModelViewSet):
    """Manage individual installed items"""
    queryset = InstalledItem.objects.select_related('job', 'product')
    serializer_class = InstalledItemSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'notes']
    filterset_fields = ['job', 'category', 'product']