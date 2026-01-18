from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.utils.timezone import now

from .models import Customer, Address, PasswordResetCode


# =========================
# Address Inline
# =========================
class AddressInline(admin.TabularInline):
    model = Address
    extra = 0
    fields = (
        'address_type',
        'street_address',
        'city',
        'county',
        'subcounty',
        'ward',
        'postal_code',
        'country',
        'is_default',
    )
    readonly_fields = ('created_at',)
    show_change_link = True


# =========================
# Customer Inline (User Admin)
# =========================
class CustomerInline(admin.StackedInline):
    model = Customer
    can_delete = False
    verbose_name_plural = "Customer Profile"
    fields = ('phone', 'date_of_birth', 'profile_image', 'loyalty_points')
    readonly_fields = ('loyalty_points', 'created_at', 'updated_at')


# =========================
# Custom User Admin
# =========================
class UserAdmin(BaseUserAdmin):
    inlines = [CustomerInline]

    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'is_active',
        'loyalty_points',
    )
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'date_joined')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'customer__phone')
    ordering = ('-date_joined',)

    def loyalty_points(self, obj):
        return obj.customer.loyalty_points if hasattr(obj, 'customer') else 0

    loyalty_points.short_description = "Loyalty Points"
    loyalty_points.admin_order_field = "customer__loyalty_points"


# =========================
# Customer Admin
# =========================
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        'username',
        'email',
        'phone',
        'loyalty_points',
        'created_at',
    )
    list_filter = ('created_at', 'updated_at')
    search_fields = (
        'user__username',
        'user__email',
        'user__first_name',
        'user__last_name',
        'phone',
    )
    readonly_fields = ('created_at', 'updated_at', 'loyalty_points')
    inlines = [AddressInline]
    autocomplete_fields = ('user',)

    fieldsets = (
        ("User", {'fields': ('user',)}),
        ("Customer Profile", {
            'fields': ('phone', 'date_of_birth', 'profile_image', 'loyalty_points')
        }),
        ("Timestamps", {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def username(self, obj):
        return obj.user.username

    def email(self, obj):
        return obj.user.email

    username.admin_order_field = 'user__username'
    email.admin_order_field = 'user__email'

    # ---- Admin Actions ----
    actions = ('add_100_points', 'add_500_points', 'reset_points')

    def add_100_points(self, request, queryset):
        queryset.update(loyalty_points=models.F('loyalty_points') + 100)
        self.message_user(request, f"Added 100 points to {queryset.count()} customers.")

    def add_500_points(self, request, queryset):
        queryset.update(loyalty_points=models.F('loyalty_points') + 500)
        self.message_user(request, f"Added 500 points to {queryset.count()} customers.")

    def reset_points(self, request, queryset):
        queryset.update(loyalty_points=0)
        self.message_user(request, f"Loyalty points reset for {queryset.count()} customers.")

    add_100_points.short_description = "➕ Add 100 loyalty points"
    add_500_points.short_description = "➕ Add 500 loyalty points"
    reset_points.short_description = "♻ Reset loyalty points"


# =========================
# Address Admin
# =========================
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        'customer_name',
        'address_type',
        'county',
        'city',
        'is_default',
        'created_at',
    )
    list_filter = ('address_type', 'county', 'is_default', 'country')
    search_fields = (
        'customer__user__username',
        'customer__user__email',
        'street_address',
        'county',
        'subcounty',
        'ward',
        'city',
    )
    readonly_fields = ('created_at',)
    autocomplete_fields = ('customer',)

    fieldsets = (
        ("Customer", {'fields': ('customer',)}),
        ("Address Type", {'fields': ('address_type', 'is_default')}),
        ("Location", {
            'fields': (
                'street_address',
                'apartment',
                'city',
                'county',
                'subcounty',
                'ward',
            )
        }),
        ("Postal", {'fields': ('postal_code', 'state', 'country')}),
        ("Metadata", {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    def customer_name(self, obj):
        return obj.customer.user.get_full_name() or obj.customer.user.username

    customer_name.short_description = "Customer"
    customer_name.admin_order_field = 'customer__user__username'

    def save_model(self, request, obj, form, change):
        if obj.is_default:
            Address.objects.filter(
                customer=obj.customer,
                address_type=obj.address_type
            ).exclude(pk=obj.pk).update(is_default=False)
        super().save_model(request, obj, form, change)


# =========================
# Password Reset Code Admin
# =========================
@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'code',
        'is_used',
        'is_expired',
        'created_at',
        'expires_at',
    )
    list_filter = ('is_used', 'created_at', 'expires_at')
    search_fields = ('user__email', 'code')
    readonly_fields = (
        'id',
        'user',
        'code',
        'token',
        'created_at',
        'expires_at',
    )
    ordering = ('-created_at',)

    def is_expired(self, obj):
        return obj.expires_at < now()

    is_expired.boolean = True
    is_expired.short_description = "Expired"

    actions = ('mark_used',)

    def mark_used(self, request, queryset):
        updated = queryset.filter(is_used=False).update(is_used=True)
        self.message_user(request, f"{updated} reset codes marked as used.")

    mark_used.short_description = "✔ Mark selected codes as used"


# =========================
# Register Custom User Admin
# =========================
admin.site.unregister(User)
admin.site.register(User, UserAdmin)