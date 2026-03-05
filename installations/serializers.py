from rest_framework import serializers
from .models import VehicleMake, InstallationJob, InstalledItem, InstallationImage, InstallationVideo


class VehicleMakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleMake
        fields = ['id', 'name', 'slug', 'logo']


class InstallationImageSerializer(serializers.ModelSerializer):
    image_type_display = serializers.CharField(source='get_image_type_display', read_only=True)

    class Meta:
        model = InstallationImage
        fields = [
            'id', 'image', 'image_type', 'image_type_display',
            'caption', 'alt_text', 'is_primary', 'order', 'created_at'
        ]
        read_only_fields = ['created_at']


class InstallationVideoSerializer(serializers.ModelSerializer):
    video_type_display = serializers.CharField(source='get_video_type_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    auto_thumbnail_url = serializers.CharField(read_only=True)

    class Meta:
        model = InstallationVideo
        fields = [
            'id', 'video_file', 'source', 'source_display', 'embed_url', 'embed_code',
            'video_type', 'video_type_display', 'title', 'description',
            'thumbnail', 'auto_thumbnail_url', 'is_primary', 'order', 'created_at'
        ]
        read_only_fields = ['embed_code', 'created_at']


class InstalledItemSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    line_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = InstalledItem
        fields = [
            'id', 'product', 'product_name', 'name', 'category', 'category_display',
            'quantity', 'unit_price', 'line_total', 'notes', 'order'
        ]


class InstallationJobListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views / portfolio grid"""
    vehicle_make_name = serializers.CharField(source='vehicle_make.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    primary_after_image = serializers.SerializerMethodField()

    class Meta:
        model = InstallationJob
        fields = [
            'id', 'slug', 'display_title', 'description', 'vehicle_make_name', 'vehicle_model',
            'vehicle_year', 'vehicle_color', 'status', 'status_display',
            'job_date', 'is_featured',
            'primary_after_image',
        ]

    def get_primary_after_image(self, obj):
        img = obj.primary_after_image
        if img:
            return InstallationImageSerializer(img, context=self.context).data
        return None


class InstallationJobDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail view"""
    vehicle_make = VehicleMakeSerializer(read_only=True)
    vehicle_make_id = serializers.PrimaryKeyRelatedField(
        queryset=VehicleMake.objects.all(), source='vehicle_make', write_only=True, required=False
    )
    installed_items = InstalledItemSerializer(many=True, read_only=True)
    images = InstallationImageSerializer(many=True, read_only=True)
    videos = InstallationVideoSerializer(many=True, read_only=True)
    total_cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    display_title = serializers.CharField(read_only=True)
    effective_meta_title = serializers.CharField(read_only=True)
    effective_og_image = serializers.SerializerMethodField()

    # Grouped images for convenience
    before_images = serializers.SerializerMethodField()
    after_images = serializers.SerializerMethodField()
    in_progress_images = serializers.SerializerMethodField()
    primary_before_image = serializers.SerializerMethodField()
    primary_after_image = serializers.SerializerMethodField()

    class Meta:
        model = InstallationJob
        fields = [
            'id', 'slug',
            'vehicle_make', 'vehicle_make_id', 'vehicle_model',
            'vehicle_year', 'vehicle_color', 'license_plate',
            'customer_name', 'customer_phone', 'customer_email',
            'title', 'display_title', 'description', 'status', 'status_display',
            'technician', 'labour_cost', 'parts_cost', 'discount', 'total_cost',
            'is_featured', 'is_public', 'job_date',
            # SEO
            'meta_title', 'meta_description', 'seo_keywords', 'og_image',
            'effective_meta_title', 'effective_og_image',
            # Media
            'installed_items', 'images', 'videos',
            'before_images', 'after_images', 'in_progress_images',
            'primary_before_image', 'primary_after_image',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['slug', 'created_at', 'updated_at']

    def get_effective_og_image(self, obj):
        image = obj.effective_og_image
        if image:
            request = self.context.get('request')
            return request.build_absolute_uri(image.url) if request else image.url
        return None

    def get_before_images(self, obj):
        imgs = obj.images.filter(image_type='before')
        return InstallationImageSerializer(imgs, many=True, context=self.context).data

    def get_after_images(self, obj):
        imgs = obj.images.filter(image_type='after')
        return InstallationImageSerializer(imgs, many=True, context=self.context).data

    def get_in_progress_images(self, obj):
        imgs = obj.images.filter(image_type='in_progress')
        return InstallationImageSerializer(imgs, many=True, context=self.context).data

    def get_primary_before_image(self, obj):
        img = obj.primary_before_image
        return InstallationImageSerializer(img, context=self.context).data if img else None

    def get_primary_after_image(self, obj):
        img = obj.primary_after_image
        return InstallationImageSerializer(img, context=self.context).data if img else None


class InstallationJobWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer — supports nested creation of installed_items.
    Images are uploaded separately via InstallationImageViewSet.
    """
    installed_items = InstalledItemSerializer(many=True, required=False)

    class Meta:
        model = InstallationJob
        fields = [
            'vehicle_make', 'vehicle_model', 'vehicle_year', 'vehicle_color',
            'license_plate', 'customer_name', 'customer_phone', 'customer_email',
            'title', 'description', 'status', 'technician',
            'labour_cost', 'parts_cost', 'discount',
            'is_featured', 'is_public', 'job_date',
            'installed_items',
        ]

    def create(self, validated_data):
        items_data = validated_data.pop('installed_items', [])
        job = InstallationJob.objects.create(**validated_data)
        for item_data in items_data:
            InstalledItem.objects.create(job=job, **item_data)
        return job

    def update(self, instance, validated_data):
        items_data = validated_data.pop('installed_items', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            # Replace all items on update
            instance.installed_items.all().delete()
            for item_data in items_data:
                InstalledItem.objects.create(job=instance, **item_data)

        return instance


class BulkImageUploadSerializer(serializers.Serializer):
    """For uploading multiple images to a job at once"""
    images = serializers.ListField(
        child=serializers.ImageField(),
        max_length=20,
        help_text="Upload up to 20 images at once"
    )
    image_type = serializers.ChoiceField(
        choices=InstallationImage.IMAGE_TYPE_CHOICES,
        default='after'
    )