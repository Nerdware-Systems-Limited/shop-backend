from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, FileExtensionValidator
from decimal import Decimal


class VehicleMake(models.Model):
    """Vehicle manufacturers e.g. Toyota, Mitsubishi, Subaru"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to='installations/vehicle_makes/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class InstallationJob(models.Model):
    """
    Represents a single car installation job.
    E.g. "Toyota Prado J150 2018 - 9" Radio + 360 Cameras"
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    # Vehicle info
    vehicle_make = models.ForeignKey(
        VehicleMake, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='installation_jobs'
    )
    vehicle_model = models.CharField(max_length=100, help_text="e.g. Prado J150, RVR, Fielder")
    vehicle_year = models.PositiveSmallIntegerField(null=True, blank=True)
    vehicle_color = models.CharField(max_length=50, blank=True)
    license_plate = models.CharField(max_length=20, blank=True, help_text="Optional — for internal tracking")

    # Customer info (optional — not linked to auth user, to keep it simple)
    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)
    customer_email = models.EmailField(blank=True)

    # Job details
    title = models.CharField(
        max_length=255, blank=True,
        help_text="Auto-generated or custom title e.g. 'Toyota Prado - Full Audio Upgrade'"
    )
    description = models.TextField(blank=True, help_text="General notes about the job")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')
    technician = models.CharField(max_length=100, blank=True, help_text="Name of technician who did the job")

    # Costs
    labour_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    parts_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )

    # Visibility — for showcasing on frontend/portfolio
    is_featured = models.BooleanField(default=False, help_text="Show this job in the portfolio/showcase")
    is_public = models.BooleanField(default=True, help_text="Visible to customers on the website")

    #  SEO 
    slug = models.SlugField(
        max_length=255, unique=True, blank=True,
        help_text="Auto-generated URL slug e.g. toyota-prado-2018-audio-upgrade"
    )
    meta_title = models.CharField(
        max_length=70, blank=True,
        help_text="Google title tag (max 70 chars). Falls back to display_title if blank."
    )
    meta_description = models.CharField(
        max_length=160, blank=True,
        help_text="Google search snippet (max 160 chars)."
    )
    seo_keywords = models.CharField(
        max_length=255, blank=True,
        help_text="Comma-separated. e.g. 'Toyota Prado radio upgrade, 360 camera Nairobi'"
    )
    og_image = models.ImageField(
        upload_to='installations/og_images/', blank=True, null=True,
        help_text="Social sharing image (1200x630px). Falls back to primary after-image if blank."
    )

    # Timestamps
    job_date = models.DateField(default=timezone.now, help_text="Date the installation was done")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-job_date', '-created_at']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status']),
            models.Index(fields=['is_featured', 'is_public']),
            models.Index(fields=['job_date']),
            models.Index(fields=['vehicle_make', 'vehicle_model']),
        ]

    def __str__(self):
        return self.display_title

    @property
    def display_title(self):
        if self.title:
            return self.title
        parts = []
        if self.vehicle_make:
            parts.append(self.vehicle_make.name)
        if self.vehicle_model:
            parts.append(self.vehicle_model)
        if self.vehicle_year:
            parts.append(str(self.vehicle_year))
        return ' '.join(parts) if parts else f"Job #{self.pk}"

    @property
    def total_cost(self):
        return max(Decimal('0.00'), self.parts_cost + self.labour_cost - self.discount)

    @property
    def primary_before_image(self):
        return self.images.filter(image_type='before', is_primary=True).first() \
               or self.images.filter(image_type='before').first()

    @property
    def primary_after_image(self):
        return self.images.filter(image_type='after', is_primary=True).first() \
               or self.images.filter(image_type='after').first()

    @property
    def effective_meta_title(self):
        return self.meta_title or self.display_title[:70]

    @property
    def effective_og_image(self):
        if self.og_image:
            return self.og_image
        after = self.primary_after_image
        return after.image if after else None

    def _generate_slug(self):
        from django.utils.text import slugify
        import uuid
        parts = []
        if self.vehicle_make:
            parts.append(self.vehicle_make.name)
        if self.vehicle_model:
            parts.append(self.vehicle_model)
        if self.vehicle_year:
            parts.append(str(self.vehicle_year))
        base = slugify(' '.join(parts)) or 'installation'
        slug = base
        if InstallationJob.objects.exclude(pk=self.pk).filter(slug=slug).exists():
            slug = f"{base}-{uuid.uuid4().hex[:6]}"
        return slug

    def save(self, *args, **kwargs):
        if not self.title:
            self.title = self.display_title
        if not self.slug:          # ← add this line
            self.slug = self._generate_slug()
        super().save(*args, **kwargs)


class InstalledItem(models.Model):
    """
    A product/part installed in this job.
    Can optionally link to a Product in the catalog, or be a free-text entry.

    Examples:
        - 9" Android Radio
        - Boschman Equaliser
        - Pioneer GM-A6704 Amplifier
        - 100Amps fuse block
        - Labour and wiring kit
    """

    CATEGORY_CHOICES = [
        ('head_unit', 'Head Unit / Radio'),
        ('speakers', 'Speakers'),
        ('amplifier', 'Amplifier'),
        ('subwoofer', 'Subwoofer'),
        ('camera', 'Camera'),
        ('equaliser', 'Equaliser'),
        ('wiring', 'Wiring & Accessories'),
        ('cabinet', 'Cabinet'),
        ('crossover', 'Crossover'),
        ('canbus', 'CANbus'),
        ('other', 'Other'),
    ]

    job = models.ForeignKey(
        InstallationJob, on_delete=models.CASCADE, related_name='installed_items'
    )
    # Link to catalog product (optional)
    product = models.ForeignKey(
        'products.Product', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='installation_uses'
    )
    # Free-text fallback (always filled — either from product.name or manually)
    name = models.CharField(max_length=255, help_text="e.g. Pioneer GM-A6704 Amplifier")
    category = models.CharField(
        max_length=30, choices=CATEGORY_CHOICES, default='other'
    )
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Price at time of installation (optional)"
    )
    notes = models.CharField(max_length=255, blank=True, help_text="e.g. Slot tuned cabinet, 5-way crossover")
    order = models.PositiveSmallIntegerField(default=0, help_text="Display order")

    class Meta:
        ordering = ['order', 'category', 'name']

    def __str__(self):
        return f"{self.name} (x{self.quantity}) — {self.job.display_title}"

    @property
    def line_total(self):
        if self.unit_price:
            return self.unit_price * self.quantity
        return None

    def save(self, *args, **kwargs):
        # Auto-populate name from linked product if not set
        if self.product and not self.name:
            self.name = self.product.name
        super().save(*args, **kwargs)


class InstallationImage(models.Model):
    """
    Before / After images for an installation job.
    Multiple images per job, tagged as before or after.
    """

    IMAGE_TYPE_CHOICES = [
        ('before', 'Before'),
        ('after', 'After'),
        ('in_progress', 'In Progress'),
        ('detail', 'Detail Shot'),
    ]

    job = models.ForeignKey(
        InstallationJob, on_delete=models.CASCADE, related_name='images'
    )
    image = models.ImageField(upload_to='installations/images/%Y/%m/')
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPE_CHOICES, default='after')
    caption = models.CharField(max_length=255, blank=True, help_text="e.g. Dashboard view after install")
    alt_text = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(
        default=False,
        help_text="Primary image shown as thumbnail for this type (before/after)"
    )
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['image_type', 'order', 'created_at']

    def __str__(self):
        return f"{self.get_image_type_display()} — {self.job.display_title}"

    def save(self, *args, **kwargs):
        # Auto-set alt text
        if not self.alt_text:
            self.alt_text = f"{self.get_image_type_display()} installation image for {self.job.display_title}"
        super().save(*args, **kwargs)

class InstallationVideo(models.Model):
    VIDEO_TYPE_CHOICES = [
        ('before', 'Before'),
        ('after', 'After'),
        ('in_progress', 'In Progress'),
        ('showcase', 'Showcase / Full Demo'),
    ]
    SOURCE_CHOICES = [
        ('upload', 'Direct Upload'),
        ('youtube', 'YouTube'),
        ('tiktok', 'TikTok'),
        ('instagram', 'Instagram'),
        ('other', 'Other'),
    ]

    job = models.ForeignKey(InstallationJob, on_delete=models.CASCADE, related_name='videos')

    # Option A: direct upload → S3
    video_file = models.FileField(
        upload_to='installations/videos/%Y/%m/',
        blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'webm', 'avi'])],
        help_text="Upload MP4/MOV/WebM. Stored on S3. Leave blank if using an embed URL."
    )

    # Option B: YouTube / TikTok / Instagram
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='upload')
    embed_url = models.URLField(
        blank=True,
        help_text="e.g. https://www.youtube.com/watch?v=abc123 or https://www.tiktok.com/@user/video/123"
    )
    embed_code = models.CharField(max_length=500, blank=True,
        help_text="Auto-generated iframe embed URL. Leave blank to auto-fill.")

    video_type = models.CharField(max_length=20, choices=VIDEO_TYPE_CHOICES, default='showcase')
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='installations/video_thumbnails/', blank=True, null=True,
        help_text="Custom thumbnail. YouTube thumbnail used automatically if blank.")
    is_primary = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'order', 'created_at']

    def __str__(self):
        return f"{self.get_video_type_display()} video — {self.job.display_title}"

    @property
    def youtube_id(self):
        import re
        if not self.embed_url:
            return None
        for pattern in [r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', r'embed/([a-zA-Z0-9_-]{11})']:
            match = re.search(pattern, self.embed_url)
            if match:
                return match.group(1)
        return None

    @property
    def auto_thumbnail_url(self):
        if self.thumbnail:
            return self.thumbnail.url
        vid_id = self.youtube_id
        if vid_id:
            return f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
        return None

    def save(self, *args, **kwargs):
        if self.embed_url and not self.embed_code:
            vid_id = self.youtube_id
            if vid_id:
                self.embed_code = f"https://www.youtube.com/embed/{vid_id}"
                self.source = 'youtube'
            elif 'tiktok.com' in self.embed_url:
                self.source = 'tiktok'
            elif 'instagram.com' in self.embed_url:
                self.source = 'instagram'
        if not self.title:
            self.title = f"{self.get_video_type_display()} — {self.job.display_title}"
        super().save(*args, **kwargs)