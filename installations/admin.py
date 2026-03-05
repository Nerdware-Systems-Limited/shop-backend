from django.contrib import admin
from django.utils.html import format_html
from .models import VehicleMake, InstallationJob, InstalledItem, InstallationImage, InstallationVideo


@admin.register(VehicleMake)
class VehicleMakeAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'is_active']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['is_active']
    search_fields = ['name']


class InstalledItemInline(admin.TabularInline):
    model = InstalledItem
    extra = 3
    fields = ['category', 'name', 'product', 'quantity', 'unit_price', 'notes', 'order']
    autocomplete_fields = ['product']
    ordering = ['order', 'category']


class InstallationImageInline(admin.TabularInline):
    model = InstallationImage
    extra = 2
    fields = ['image', 'image_type', 'caption', 'alt_text', 'is_primary', 'order', 'image_preview']
    readonly_fields = ['image_preview']
    ordering = ['image_type', 'order']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:80px;max-width:120px;object-fit:cover;border-radius:4px;" />',
                obj.image.url
            )
        return '—'
    image_preview.short_description = 'Preview'


class InstallationVideoInline(admin.TabularInline):
    model = InstallationVideo
    extra = 1
    fields = ['video_type', 'source', 'video_file', 'embed_url', 'title', 'thumbnail', 'is_primary', 'order']
    readonly_fields = ['video_preview']

    def video_preview(self, obj):
        thumb = obj.auto_thumbnail_url
        if thumb:
            return format_html(
                '<img src="{}" style="height:50px;width:80px;object-fit:cover;border-radius:4px;" />',
                thumb
            )
        if obj.video_file:
            return format_html(
                '<video src="{}" style="height:50px;width:80px;object-fit:cover;border-radius:4px;" />',
                obj.video_file.url
            )
        return '—'
    video_preview.short_description = 'Preview'


@admin.register(InstallationJob)
class InstallationJobAdmin(admin.ModelAdmin):
    list_display = [
        'display_title', 'vehicle_make', 'vehicle_year',
        'status_badge', 'technician', 'item_count',
        'before_after_preview', 'total_cost_display',
        'seo_score', 'is_featured', 'is_public', 'job_date'
    ]
    list_filter = [
        'status', 'is_featured', 'is_public',
        'vehicle_make', 'job_date', 'technician'
    ]
    search_fields = [
        'title', 'slug', 'vehicle_model', 'vehicle_make__name',
        'customer_name', 'customer_phone', 'description',
        'installed_items__name'
    ]
    list_editable = ['is_featured', 'is_public']
    date_hierarchy = 'job_date'
    inlines = [InstalledItemInline, InstallationImageInline, InstallationVideoInline]
    autocomplete_fields = ['vehicle_make']
    readonly_fields = [
        'slug_preview', 'meta_title_counter', 'meta_description_counter',
        'og_image_preview', 'seo_checklist',
    ]

    fieldsets = (
        ('Vehicle', {
            'fields': (
                ('vehicle_make', 'vehicle_model', 'vehicle_year'),
                ('vehicle_color', 'license_plate'),
            )
        }),
        ('Customer', {
            'fields': (
                ('customer_name', 'customer_phone', 'customer_email'),
            ),
            'classes': ('collapse',)
        }),
        ('Job Details', {
            'fields': (
                'title', 'description', 'status', 'technician', 'job_date'
            )
        }),
        ('Costs', {
            'fields': (
                ('labour_cost', 'parts_cost', 'discount'),
            )
        }),
        ('Visibility', {
            'fields': ('is_featured', 'is_public'),
        }),
        ('SEO', {
            'description': (
                'These fields control how this job appears in Google search results and '
                'when shared on WhatsApp / Facebook. Well-written SEO fields bring in more customers.'
            ),
            'fields': (
                'slug',
                'slug_preview',
                'meta_title',
                'meta_title_counter',
                'meta_description',
                'meta_description_counter',
                'seo_keywords',
                'og_image',
                'og_image_preview',
                'seo_checklist',
            ),
        }),
    )

    # ── List display helpers ──────────────────────────────────────────────────

    def status_badge(self, obj):
        colors = {
            'pending': '#FF9800',
            'in_progress': '#2196F3',
            'completed': '#4CAF50',
            'cancelled': '#F44336',
        }
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:3px;font-size:11px;">{}</span>',
            colors.get(obj.status, '#999'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def item_count(self, obj):
        return format_html('<strong>{}</strong> items', obj.installed_items.count())
    item_count.short_description = 'Items'

    def total_cost_display(self, obj):
        return f"KSh {obj.total_cost:,.2f}"
    total_cost_display.short_description = 'Total'

    def before_after_preview(self, obj):
        html = ''
        before = obj.primary_before_image
        after = obj.primary_after_image
        if before and before.image:
            html += format_html(
                '<img src="{}" title="Before" style="height:40px;width:60px;object-fit:cover;'
                'border-radius:3px;margin-right:4px;border:2px solid #F44336;" />',
                before.image.url
            )
        if after and after.image:
            html += format_html(
                '<img src="{}" title="After" style="height:40px;width:60px;object-fit:cover;'
                'border-radius:3px;border:2px solid #4CAF50;" />',
                after.image.url
            )
        return format_html(html) if html else '—'
    before_after_preview.short_description = 'Before / After'

    def seo_score(self, obj):
        """Quick green/amber/red dot in the list view showing SEO completeness"""
        score = 0
        if obj.meta_title:
            score += 1
        if obj.meta_description:
            score += 1
        if obj.seo_keywords:
            score += 1
        if obj.slug:
            score += 1
        if obj.primary_after_image or obj.og_image:
            score += 1

        if score == 5:
            color, label = '#4CAF50', '●●●●● Full'
        elif score >= 3:
            color, label = '#FF9800', f'{"●" * score}{"○" * (5 - score)} Partial'
        else:
            color, label = '#F44336', f'{"●" * score}{"○" * (5 - score)} Thin'

        return format_html(
            '<span style="color:{};font-size:12px;white-space:nowrap;" title="SEO score {}/5">{}</span>',
            color, score, label
        )
    seo_score.short_description = 'SEO'

    # ── SEO readonly field helpers ────────────────────────────────────────────

    def slug_preview(self, obj):
        if not obj.slug:
            return format_html('<span style="color:#999;">Slug will be auto-generated on save.</span>')
        return format_html(
            '<code style="background:#f5f5f5;padding:4px 8px;border-radius:3px;">'
            '/installations/<strong>{}</strong>/</code>',
            obj.slug
        )
    slug_preview.short_description = 'Page URL preview'

    def meta_title_counter(self, obj):
        length = len(obj.meta_title) if obj.meta_title else 0
        effective = obj.effective_meta_title
        color = '#4CAF50' if length <= 60 else '#FF9800' if length <= 70 else '#F44336'
        note = '' if obj.meta_title else f' <em style="color:#999;">(will use: "{effective[:60]}…")</em>'
        return format_html(
            '<span style="color:{};">{}/70 characters</span>{}'
            '<br><small style="color:#666;">Google typically shows 50–60 chars on mobile, up to 70 on desktop.</small>',
            color, length, format_html(note)
        )
    meta_title_counter.short_description = 'Title length'

    def meta_description_counter(self, obj):
        length = len(obj.meta_description) if obj.meta_description else 0
        color = '#4CAF50' if 120 <= length <= 160 else '#FF9800' if length > 0 else '#F44336'
        tip = 'Good length!' if 120 <= length <= 160 else \
              'Too long — Google will cut it off.' if length > 160 else \
              'Aim for 120–160 chars. Describe the job + mention Nairobi to attract local searches.'
        return format_html(
            '<span style="color:{};">{}/160 characters — {}</span>',
            color, length, tip
        )
    meta_description_counter.short_description = 'Description length'

    def og_image_preview(self, obj):
        img = obj.effective_og_image
        if img:
            try:
                return format_html(
                    '<img src="{}" style="max-width:300px;max-height:160px;object-fit:cover;'
                    'border-radius:6px;border:1px solid #ddd;" />'
                    '<br><small style="color:#666;">This is what appears when shared on WhatsApp / Facebook.</small>',
                    img.url
                )
            except Exception:
                pass
        return format_html(
            '<span style="color:#FF9800;">⚠ No OG image set. '
            'Upload one above or add an after-image to the job — it will be used automatically.</span>'
        )
    og_image_preview.short_description = 'Social share preview'

    def seo_checklist(self, obj):
        """Visual checklist of SEO completeness shown inside the form"""
        checks = [
            (bool(obj.slug),            'URL slug set'),
            (bool(obj.meta_title),      'Meta title filled in'),
            (bool(obj.meta_description),'Meta description filled in'),
            (bool(obj.seo_keywords),    'Keywords added'),
            (bool(obj.og_image or obj.primary_after_image),
                                        'Social share image available'),
            (bool(obj.description),     'Job description written'),
            (obj.images.filter(image_type='before').exists() if obj.pk else False,
                                        'Before image uploaded'),
            (obj.images.filter(image_type='after').exists() if obj.pk else False,
                                        'After image uploaded'),
        ]
        rows = ''
        for passed, label in checks:
            icon = '✅' if passed else '❌'
            style = 'color:#333;' if passed else 'color:#999;'
            rows += f'<li style="{style}margin:3px 0;">{icon} {label}</li>'

        score = sum(1 for passed, _ in checks if passed)
        total = len(checks)
        bar_color = '#4CAF50' if score == total else '#FF9800' if score >= 5 else '#F44336'

        return format_html(
            '<ul style="margin:0;padding-left:20px;list-style:none;">{}</ul>'
            '<p style="margin-top:8px;">'
            '<strong style="color:{};">{}/{} SEO fields complete</strong>'
            '</p>',
            format_html(rows), bar_color, score, total
        )
    seo_checklist.short_description = 'SEO checklist'


@admin.register(InstallationImage)
class InstallationImageAdmin(admin.ModelAdmin):
    list_display = ['job', 'image_type', 'image_preview', 'caption', 'alt_text', 'is_primary', 'order']
    list_filter = ['image_type', 'is_primary']
    search_fields = ['job__title', 'job__vehicle_model', 'caption', 'alt_text']
    list_editable = ['is_primary', 'order']

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:50px;width:75px;object-fit:cover;border-radius:4px;" />',
                obj.image.url
            )
        return '—'
    image_preview.short_description = 'Image'


@admin.register(InstallationVideo)
class InstallationVideoAdmin(admin.ModelAdmin):
    list_display = ['job', 'video_type', 'source', 'title', 'video_preview', 'is_primary', 'order', 'created_at']
    list_filter = ['video_type', 'source', 'is_primary']
    search_fields = ['job__title', 'job__vehicle_model', 'title', 'description']
    list_editable = ['is_primary', 'order']
    readonly_fields = ['video_preview', 'embed_code']

    fieldsets = (
        ('Job', {
            'fields': ('job', 'video_type', 'title', 'description')
        }),
        ('Upload (Option A — direct file)', {
            'fields': ('video_file',),
            'description': 'Upload MP4, MOV, or WebM. File goes to S3.',
        }),
        ('Embed link (Option B — YouTube / TikTok / Instagram)', {
            'fields': ('embed_url', 'embed_code', 'source'),
            'description': 'Paste a full URL. embed_code is auto-generated on save.',
        }),
        ('Thumbnail & Display', {
            'fields': ('thumbnail', 'video_preview', 'is_primary', 'order'),
        }),
    )

    def video_preview(self, obj):
        thumb = obj.auto_thumbnail_url
        if thumb:
            label = 'YouTube thumbnail' if obj.youtube_id else 'Custom thumbnail'
            return format_html(
                '<img src="{}" style="height:80px;width:120px;object-fit:cover;border-radius:6px;" />'
                '<br><small style="color:#666;">{}</small>',
                thumb, label
            )
        if obj.video_file:
            return format_html(
                '<video controls style="height:80px;width:140px;border-radius:6px;">'
                '<source src="{}"></video>',
                obj.video_file.url
            )
        return format_html('<span style="color:#999;">No preview yet</span>')
    video_preview.short_description = 'Preview'


@admin.register(InstalledItem)
class InstalledItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'job', 'category', 'quantity', 'unit_price', 'notes']
    list_filter = ['category']
    search_fields = ['name', 'job__title', 'job__vehicle_model', 'notes']
    autocomplete_fields = ['product']