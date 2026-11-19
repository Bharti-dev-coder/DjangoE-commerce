from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.text import slugify

from core.models import (
    Address,
    CartItem,
    Category,
    Coupon,
    Employee,
    Favorite,
    Order,
    OrderItem,
    PaymentRecord,
    Product,
    StoreProfile,
)


admin.site.site_header = 'EuphoriaDJ store administration'
admin.site.site_title = 'EuphoriaDJ Admin'
admin.site.index_title = 'Store management'


class AutoSlugAdminForm(forms.ModelForm):
    """Let staff leave a slug blank and derive a unique one from the name."""

    slug = forms.SlugField(
        required=False,
        help_text='Leave blank to generate a unique slug from the name.',
    )

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name') or self.data.get('name') or ''
        slug = cleaned_data.get('slug') or slugify(name) or 'item'

        model = self._meta.model
        queryset = model.objects.exclude(pk=self.instance.pk) if self.instance.pk else model.objects.all()
        candidate = slug
        suffix = 2
        while queryset.filter(slug=candidate).exists():
            candidate = f'{slug}-{suffix}'
            suffix += 1

        cleaned_data['slug'] = candidate
        return cleaned_data

    class Meta:
        fields = '__all__'


class ProductAdminForm(AutoSlugAdminForm):
    class Meta(AutoSlugAdminForm.Meta):
        model = Product


class CategoryAdminForm(AutoSlugAdminForm):
    class Meta(AutoSlugAdminForm.Meta):
        model = Category


def product_image_tag(image_field, alt_text=''):
    if image_field:
        return format_html(
            '<img src="{}" alt="{}" style="width:46px;height:46px;object-fit:contain;'
            'border:1px solid #ddd;border-radius:4px;background:#fff;padding:2px;">',
            image_field.url,
            alt_text,
        )
    return format_html(
        '<img src="{}" alt="" style="width:46px;height:46px;object-fit:contain;'
        'border:1px solid #ddd;border-radius:4px;background:#fff;padding:2px;">',
        static('theme/img/product-1.png'),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryAdminForm
    prepopulated_fields = {'slug': ('name',)}
    list_display = ('name', 'slug', 'product_count')
    search_fields = ('name', 'description')

    @admin.display(description='Products')
    def product_count(self, category):
        return category.products.count()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    prepopulated_fields = {'slug': ('name',)}
    list_display = ('name', 'category', 'price', 'available', 'created_at')
    list_filter = ('available', 'category', 'created_at')
    list_editable = ('available',)
    search_fields = ('name', 'description', 'slug')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'product', 'product_image', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'product__name')
    list_select_related = ('user', 'product')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    autocomplete_fields = ('user', 'product')

    @admin.display(description='Product image')
    def product_image(self, favorite):
        return product_image_tag(favorite.product.image, favorite.product.name)


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'product',
        'product_image',
        'unit_price_display',
        'quantity',
        'subtotal_display',
        'source',
        'added_at',
    )
    list_filter = ('source', 'added_at')
    search_fields = ('user__username', 'user__email', 'product__name')
    list_select_related = ('user', 'product')
    readonly_fields = ('added_at',)
    date_hierarchy = 'added_at'
    autocomplete_fields = ('user', 'product')
    ordering = ('-added_at',)

    @admin.display(description='Product image')
    def product_image(self, item):
        return product_image_tag(item.product.image, item.product.name)

    @admin.display(description='Unit price')
    def unit_price_display(self, item):
        return f'{settings.STORE_CURRENCY_SYMBOL}{item.product.price:,.2f}'

    @admin.display(description='Subtotal')
    def subtotal_display(self, item):
        return f'{settings.STORE_CURRENCY_SYMBOL}{item.subtotal():,.2f}'


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'discount_type',
        'discount_value',
        'minimum_order_amount',
        'maximum_discount',
        'valid_from',
        'expiry_date',
        'is_active',
        'usage_count',
        'usage_limit',
    )
    list_filter = ('is_active', 'discount_type', 'valid_from', 'expiry_date')
    search_fields = ('code',)
    readonly_fields = ('usage_count', 'created_at')
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Coupon code', {'fields': ('code', 'is_active')}),
        (
            'Discount rules',
            {
                'fields': (
                    'discount_type',
                    'discount_value',
                    'minimum_order_amount',
                    'maximum_discount',
                )
            },
        ),
        ('Validity and usage', {'fields': ('valid_from', 'expiry_date', 'usage_limit', 'usage_count', 'created_at')}),
    )


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'full_name',
        'phone',
        'city',
        'state',
        'pin_code',
        'country',
        'is_default',
        'updated_at',
    )
    list_filter = ('is_default', 'country', 'state', 'updated_at')
    search_fields = (
        'user__username',
        'user__email',
        'full_name',
        'phone',
        'city',
        'pin_code',
    )
    list_select_related = ('user',)
    autocomplete_fields = ('user',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-is_default', '-updated_at')


@admin.register(StoreProfile)
class StoreProfileAdmin(admin.ModelAdmin):
    list_display = (
        'business_name',
        'owner_name',
        'email',
        'contact_number',
        'city',
        'state',
        'gstin',
        'updated_at',
    )
    readonly_fields = ('updated_at',)
    fieldsets = (
        (
            'Business identity',
            {
                'fields': (
                    'business_name',
                    'owner_name',
                    'email',
                    'contact_number',
                    'gstin',
                )
            },
        ),
        (
            'Registered business address',
            {
                'fields': (
                    'house_number',
                    'street',
                    'city',
                    'state',
                    'pin_code',
                    'country',
                    'additional_info',
                    'updated_at',
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return not StoreProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = (
        'product',
        'product_name',
        'product_image_tag',
        'unit_price_display',
        'quantity',
        'subtotal_display',
    )
    readonly_fields = fields
    show_change_link = True

    @admin.display(description='Image')
    def product_image_tag(self, item):
        return product_image_tag(item.product_image, item.product_name)

    @admin.display(description='Unit price')
    def unit_price_display(self, item):
        if item.unit_price is None:
            return '-'
        return f'{settings.STORE_CURRENCY_SYMBOL}{item.unit_price:,.2f}'

    @admin.display(description='Subtotal')
    def subtotal_display(self, item):
        if item.subtotal is None:
            return '-'
        return f'{settings.STORE_CURRENCY_SYMBOL}{item.subtotal:,.2f}'

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentRecordInline(admin.TabularInline):
    model = PaymentRecord
    extra = 0
    can_delete = False
    fields = (
        'provider',
        'razorpay_order_id',
        'razorpay_payment_id',
        'amount_display',
        'currency',
        'status',
        'signature_verified',
        'created_at',
    )
    readonly_fields = fields
    show_change_link = True

    @admin.display(description='Amount')
    def amount_display(self, record):
        if record.amount is None:
            return '-'
        return f'{settings.STORE_CURRENCY_SYMBOL}{record.amount:,.2f}'

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_number',
        'user',
        'customer_name',
        'created_at',
        'final_total_display',
        'payment_method',
        'payment_status',
        'order_status',
        'item_count',
    )
    list_filter = (
        'payment_method',
        'payment_status',
        'order_status',
        'created_at',
    )
    search_fields = (
        'order_number',
        'customer_name',
        'customer_email',
        'customer_phone',
        'user__username',
        'user__email',
        'transaction_id',
        'razorpay_order_id',
    )
    list_select_related = ('user',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    inlines = (OrderItemInline, PaymentRecordInline)
    readonly_fields = (
        'order_number',
        'user',
        'customer_name',
        'customer_email',
        'customer_phone',
        'address',
        'shipping_full_name',
        'shipping_phone',
        'shipping_house_number',
        'shipping_street',
        'shipping_landmark',
        'shipping_city',
        'shipping_state',
        'shipping_pin_code',
        'shipping_country',
        'amount_subtotal',
        'amount_coupon_discount',
        'amount_shipping_charge',
        'amount_tax',
        'amount_final_total',
        'coupon',
        'coupon_code',
        'transaction_id',
        'razorpay_order_id',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        ('Order', {'fields': ('order_number', 'user', 'created_at', 'updated_at')}),
        ('Customer', {'fields': ('customer_name', 'customer_email', 'customer_phone')}),
        (
            'Delivery address snapshot',
            {
                'fields': (
                    'address',
                    'shipping_full_name',
                    'shipping_phone',
                    'shipping_house_number',
                    'shipping_street',
                    'shipping_landmark',
                    'shipping_city',
                    'shipping_state',
                    'shipping_pin_code',
                    'shipping_country',
                )
            },
        ),
        (
            'Amounts',
            {
                'fields': (
                    'amount_subtotal',
                    'coupon',
                    'coupon_code',
                    'amount_coupon_discount',
                    'amount_shipping_charge',
                    'amount_tax',
                    'amount_final_total',
                )
            },
        ),
        (
            'Payment and fulfilment',
            {
                'fields': (
                    'payment_method',
                    'payment_status',
                    'order_status',
                    'transaction_id',
                    'razorpay_order_id',
                    'notes',
                )
            },
        ),
    )

    @admin.display(description='Subtotal')
    def amount_subtotal(self, order):
        return f'{settings.STORE_CURRENCY_SYMBOL}{order.subtotal:,.2f}'

    @admin.display(description='Coupon discount')
    def amount_coupon_discount(self, order):
        return f'{settings.STORE_CURRENCY_SYMBOL}{order.coupon_discount:,.2f}'

    @admin.display(description='Shipping charge')
    def amount_shipping_charge(self, order):
        return f'{settings.STORE_CURRENCY_SYMBOL}{order.shipping_charge:,.2f}'

    @admin.display(description='Tax amount')
    def amount_tax(self, order):
        return f'{settings.STORE_CURRENCY_SYMBOL}{order.tax_amount:,.2f}'

    @admin.display(description='Final total', ordering='final_total')
    def amount_final_total(self, order):
        return f'{settings.STORE_CURRENCY_SYMBOL}{order.final_total:,.2f}'

    @admin.display(description='Final total', ordering='final_total')
    def final_total_display(self, order):
        return f'{settings.STORE_CURRENCY_SYMBOL}{order.final_total:,.2f}'

    @admin.display(description='Items')
    def item_count(self, order):
        return order.items.count()

    def has_add_permission(self, request):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'order',
        'product',
        'product_name',
        'product_image',
        'unit_price_display',
        'quantity',
        'subtotal_display',
        'created_at',
    )
    search_fields = (
        'order__order_number',
        'product_name',
        'product__name',
        'order__customer_name',
        'order__customer_email',
    )
    list_filter = ('created_at',)
    list_select_related = ('order', 'product')
    readonly_fields = ('created_at',)

    @admin.display(description='Product image')
    def product_image(self, item):
        return product_image_tag(item.product_image, item.product_name)

    @admin.display(description='Unit price')
    def unit_price_display(self, item):
        return f'{settings.STORE_CURRENCY_SYMBOL}{item.unit_price:,.2f}'

    @admin.display(description='Subtotal')
    def subtotal_display(self, item):
        return f'{settings.STORE_CURRENCY_SYMBOL}{item.subtotal:,.2f}'


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'order',
        'provider',
        'razorpay_order_id',
        'razorpay_payment_id',
        'amount_display',
        'currency',
        'status',
        'signature_verified',
        'created_at',
    )
    list_filter = ('provider', 'status', 'signature_verified', 'created_at')
    search_fields = (
        'order__order_number',
        'razorpay_order_id',
        'razorpay_payment_id',
        'order__customer_email',
    )
    list_select_related = ('order',)
    fields = (
        'order',
        'provider',
        'razorpay_order_id',
        'razorpay_payment_id',
        'amount_display',
        'currency',
        'status',
        'signature_verified',
        'raw_response',
        'error_message',
        'created_at',
        'updated_at',
    )
    readonly_fields = fields
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    @admin.display(description='Amount')
    def amount_display(self, record):
        return f'{settings.STORE_CURRENCY_SYMBOL}{record.amount:,.2f}'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Employee)
