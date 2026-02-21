from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from rangefilter.filters import DateRangeFilter
from import_export.admin import ImportExportModelAdmin
from import_export import resources, fields

from .models import (
    Order, OrderItem, OrderStatusHistory, ShippingMethod,
    OrderReturn, ReturnItem, OrderNote
)


# ============================================================
#  Import/Export Resources
# ============================================================

class OrderResource(resources.ModelResource):
    customer_email = fields.Field(
        column_name='customer_email',
        attribute='customer__user__email'
    )

    customer_name = fields.Field(
        column_name='customer_name',
        attribute=lambda obj: (
            f"{obj.customer.user.first_name} {obj.customer.user.last_name}"
            if obj.customer and obj.customer.user else ""
        )
    )

    class Meta:
        model = Order
        fields = (
            'order_number', 'customer_email', 'customer_name', 'status',
            'payment_status', 'subtotal', 'tax_amount', 'shipping_cost',
            'discount_amount', 'total', 'created_at', 'tracking_number'
        )
        export_order = fields


class OrderItemResource(resources.ModelResource):
    product_name = fields.Field(
        column_name='product_name',
        attribute='product__name'
    )
    product_sku = fields.Field(
        column_name='product_sku',
        attribute='product__sku'
    )
    order_number = fields.Field(
        column_name='order_number',
        attribute='order__order_number'
    )

    class Meta:
        model = OrderItem
        fields = (
            'order_number', 'product_name', 'product_sku',
            'quantity', 'price', 'discount', 'total'
        )


# ============================================================
#  Inline Admins
# ============================================================

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product_link', 'price', 'total']
    fields = ['product_link', 'quantity', 'price', 'discount', 'total']

    def product_link(self, obj):
        if obj.product:
            try:
                url = reverse('admin:products_product_change', args=[obj.product.id])
                return format_html('<a href="{}">{}</a>', url, obj.product.name)
            except:
                return obj.product.name
        return "-"
    product_link.short_description = 'Product'

    def has_add_permission(self, request, obj=None):
        return False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ['old_status', 'new_status', 'changed_by', 'created_at']
    fields = ['old_status', 'new_status', 'changed_by', 'notes', 'created_at']

    def has_add_permission(self, request, obj=None):
        return False


class OrderNoteInline(admin.TabularInline):
    model = OrderNote
    extra = 1
    fields = ['user', 'note', 'is_customer_visible']


class ReturnItemInline(admin.TabularInline):
    model = ReturnItem
    extra = 0
    readonly_fields = ['order_item', 'refund_amount']
    fields = ['order_item', 'quantity', 'condition', 'refund_amount', 'notes']


# ============================================================
#  Order Admin
# ============================================================

@admin.register(Order)
class OrderAdmin(ImportExportModelAdmin):
    resource_class = OrderResource

    list_display = [
        'order_number', 'customer_info', 'status_badge',
        'payment_status_badge', 'total_display',
        'created_at', 'tracking_link', 'quick_actions'
    ]

    list_filter = [
        'status', 'payment_status', 'payment_method',
        ('created_at', DateRangeFilter),
        'is_guest', 'is_gift', 'is_digital'
    ]

    search_fields = [
        'order_number', 'customer__user__email',
        'customer__user__first_name', 'customer__user__last_name',
        'tracking_number', 'guest_email'
    ]

    readonly_fields = [
        'order_number', 'created_at', 'updated_at', 'paid_at',
        'cancelled_at', 'refunded_at', 'ip_address', 'status_history_display'
    ]

    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'status', 'payment_status', 'payment_method')
        }),
        ('Customer Information', {
            'fields': ('customer', 'is_guest', 'guest_email', 'guest_phone', 'guest_first_name', 'guest_last_name')
        }),
        ('Addresses', {
            'fields': ('billing_address', 'shipping_address')
        }),
        ('Financial', {
            'fields': (
                'subtotal', 'tax_amount', 'tax_rate',
                'shipping_cost', 'discount_amount', 'discount_code',
                'total', 'currency'
            )
        }),
        ('Shipping', {
            'fields': (
                'shipping_method', 'carrier',
                'tracking_number', 'tracking_url',
                'estimated_delivery', 'shipped_date', 'delivered_date',
                'requires_shipping'
            )
        }),
        ('Notes & Messages', {
            'fields': ('customer_notes', 'admin_notes', 'gift_message')
        }),
        ('Flags', {
            'fields': ('is_gift', 'is_digital', 'is_recurring')
        }),
        ('Audit', {
            'fields': (
                'created_at', 'updated_at', 'paid_at',
                'cancelled_at', 'refunded_at', 'ip_address', 'user_agent'
            )
        }),
        ('Status History', {
            'fields': ('status_history_display',)
        }),
    )

    inlines = [OrderItemInline, OrderStatusHistoryInline, OrderNoteInline]

    actions = [
        'mark_as_processing', 'mark_as_shipped',
        'mark_as_delivered', 'mark_as_cancelled',
        'export_selected_orders', 'send_tracking_email'
    ]

    list_per_page = 50

    # -----------------------
    #  DISPLAY FUNCTIONS
    # -----------------------

    def customer_info(self, obj):
        if obj.is_guest:
            return format_html('<span style="color:#888;">Guest: {}</span>', obj.guest_email)

        if not obj.customer:
            return "-"

        try:
            url = reverse('admin:customers_customer_change', args=[obj.customer.id])
            name = f"{obj.customer.user.first_name} {obj.customer.user.last_name}"
            return format_html(
                '<a href="{}">{}<br/><small>{}</small></a>',
                url, name, obj.customer.user.email
            )
        except:
            return obj.customer.user.email
    customer_info.short_description = 'Customer'

    def status_badge(self, obj):
        colors = {
            'pending': '#ffc107', 'processing': '#17a2b8', 'shipped': '#007bff',
            'delivered': '#28a745', 'cancelled': '#dc3545', 'refunded': '#6c757d'
        }
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;border-radius:12px;font-size:12px;">{}</span>',
            colors.get(obj.status, '#6c757d'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def payment_status_badge(self, obj):
        colors = {
            'pending': '#ffc107', 'paid': '#28a745',
            'failed': '#dc3545', 'refunded': '#6c757d'
        }
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;border-radius:12px;font-size:12px;">{}</span>',
            colors.get(obj.payment_status, '#6c757d'),
            obj.get_payment_status_display()
        )
    payment_status_badge.short_description = 'Payment'

    def total_display(self, obj):
        return format_html('<strong>${}</strong>', obj.total)
    total_display.short_description = 'Total'

    def tracking_link(self, obj):
        if not obj.tracking_number:
            return "-"
        if obj.tracking_url:
            return format_html('<a href="{}" target="_blank">{}</a>', obj.tracking_url, obj.tracking_number)
        return obj.tracking_number
    tracking_link.short_description = 'Tracking'

    def status_history_display(self, obj):
        c = obj.status_history.count()
        return format_html('{} change{} recorded', c, "" if c == 1 else "s")
    status_history_display.short_description = 'Status History'

    # -----------------------
    # QUICK ACTION BUTTONS
    # -----------------------
    def quick_actions(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.id])
        return format_html(
            '<a href="{}" style="padding:4px 8px;background:#007bff;color:white;border-radius:8px;font-size:12px;">Open</a>',
            url
        )
    quick_actions.short_description = 'Actions'

    # -----------------------
    #  ACTIONS
    # -----------------------

    def mark_as_processing(self, request, queryset):
        count = queryset.update(status='processing')
        self.message_user(request, f"{count} orders marked as processing.")
    mark_as_processing.short_description = "Mark selected as processing"

    def mark_as_shipped(self, request, queryset):
        for order in queryset:
            order.status = 'shipped'
            order.shipped_date = timezone.now()
            order.save()
        self.message_user(request, f"{queryset.count()} orders marked as shipped.")
    mark_as_shipped.short_description = "Mark selected as shipped"

    def mark_as_delivered(self, request, queryset):
        queryset.update(status='delivered', delivered_date=timezone.now())
        self.message_user(request, f"{queryset.count()} orders marked as delivered.")
    mark_as_delivered.short_description = "Mark selected as delivered"

    def mark_as_cancelled(self, request, queryset):
        queryset.update(status='cancelled', cancelled_at=timezone.now())
        self.message_user(request, f"{queryset.count()} orders marked as cancelled.")
    mark_as_cancelled.short_description = "Mark selected as cancelled"

    def export_selected_orders(self, request, queryset):
        pass

    def send_tracking_email(self, request, queryset):
        pass


# ============================================================
# Other Admins
# ============================================================

@admin.register(OrderItem)
class OrderItemAdmin(ImportExportModelAdmin):
    resource_class = OrderItemResource
    list_display = ['order_link', 'product_link', 'quantity', 'price', 'total']
    list_filter = [('order__created_at', DateRangeFilter)]
    search_fields = ['order__order_number', 'product__name', 'product__sku']
    readonly_fields = ['order', 'product', 'price', 'total']

    def order_link(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.order.id])
        return format_html('<a href="{}">{}</a>', url, obj.order.order_number)
    order_link.short_description = 'Order'

    def product_link(self, obj):
        if obj.product:
            try:
                url = reverse('admin:products_product_change', args=[obj.product.id])
                return format_html('<a href="{}">{}</a>', url, obj.product.name)
            except:
                return obj.product.name
        return "-"
    product_link.short_description = 'Product'


@admin.register(ShippingMethod)
class ShippingMethodAdmin(admin.ModelAdmin):
    list_display = ['name', 'carrier', 'code', 'cost', 'is_active', 'estimated_delivery_text']
    list_filter = ['carrier', 'is_active']
    search_fields = ['name', 'carrier', 'code']
    list_editable = ['is_active', 'cost']

    def estimated_delivery_text(self, obj):
        return f"{obj.estimated_days_min}-{obj.estimated_days_max} days"
    estimated_delivery_text.short_description = 'Delivery Time'


@admin.register(OrderReturn)
class OrderReturnAdmin(admin.ModelAdmin):
    list_display = [
        'return_number', 'order_link', 'status_badge', 'reason',
        'refund_amount', 'requested_at'
    ]
    list_filter = ['status', 'reason', ('requested_at', DateRangeFilter)]
    search_fields = ['return_number', 'order__order_number']
    inlines = [ReturnItemInline]
    readonly_fields = ['return_number', 'requested_at']

    def order_link(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.order.id])
        return format_html('<a href="{}">{}</a>', url, obj.order.order_number)
    order_link.short_description = 'Order'

    def status_badge(self, obj):
        colors = {
            'requested': '#ffc107', 'approved': '#17a2b8', 'received': '#007bff',
            'refunded': '#28a745', 'rejected': '#dc3545'
        }
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;border-radius:12px;font-size:12px;">{}</span>',
            colors.get(obj.status, '#6c757d'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ['order_link', 'old_status', 'new_status', 'changed_by', 'created_at']
    list_filter = ['new_status', ('created_at', DateRangeFilter)]
    search_fields = ['order__order_number']
    readonly_fields = ['order', 'old_status', 'new_status', 'changed_by', 'created_at']

    def order_link(self, obj):
        url = reverse('admin:orders_order_change', args=[obj.order.id])
        return format_html('<a href="{}">{}</a>', url, obj.order.order_number)
    order_link.short_description = 'Order'