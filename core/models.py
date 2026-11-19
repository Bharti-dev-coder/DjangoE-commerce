import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


def _money(value):
    """Round a monetary value to two decimal places without using floats."""
    return Decimal(value or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# Existing
class Employee(models.Model):
    departments = (
        ('it', 'Information Technology'),
        ('sales', 'Sales Representative'),
        ('admin', 'Adminstrator'),
        ('marketing', 'Digital Marketing')
    )

    emp_name = models.CharField(max_length=150)
    emp_email = models.EmailField(max_length=250, unique=True)
    emp_mobile = models.CharField(max_length=10, null=True, blank=True)
    emp_dept = models.CharField(max_length=100, choices=departments, default='sales')
    emp_dob = models.DateField(null=True, blank=True)
    emp_address = models.TextField(null=True, blank=True)
    emp_joining_date = models.DateField(auto_now_add=True)

    def _str_(self):
        return self.emp_name


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.name


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='favorited_by')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ('user', 'product')
    def __str__(self):
        return f"{self.user.username} -> {self.product.name}"


class CartItem(models.Model):
    SOURCE_QUICK_ADD = 'quick_add'
    SOURCE_PRODUCT_DETAIL = 'product_detail'
    SOURCE_AI_CHAT = 'ai_chat'
    SOURCE_CHOICES = (
        (SOURCE_QUICK_ADD, 'Quick add from product card'),
        (SOURCE_PRODUCT_DETAIL, 'Product detail page'),
        (SOURCE_AI_CHAT, 'AI shopping assistant'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cart_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='cart_items')
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_PRODUCT_DETAIL)
    added_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ('user', 'product')
    def __str__(self):
        return f"{self.user.username}: {self.product.name} x{self.quantity}"
    def subtotal(self):
        return _money(self.product.price * Decimal(self.quantity))


class Coupon(models.Model):
    DISCOUNT_PERCENTAGE = 'percentage'
    DISCOUNT_FIXED = 'fixed'
    DISCOUNT_TYPE_CHOICES = (
        (DISCOUNT_PERCENTAGE, 'Percentage'),
        (DISCOUNT_FIXED, 'Fixed amount'),
    )

    code = models.CharField(max_length=50, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES, default=DISCOUNT_PERCENTAGE)
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='For percentage coupons enter a percentage (for example 10); for fixed coupons enter an amount.',
    )
    minimum_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    maximum_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Optional cap for the discount amount.',
    )
    valid_from = models.DateTimeField(default=timezone.now)
    expiry_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Optional total number of successful redemptions allowed.',
    )
    usage_count = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'coupon'
        verbose_name_plural = 'coupons'

    def __str__(self):
        return f'{self.code} ({self.get_discount_type_display()})'

    def clean(self):
        errors = {}
        if self.discount_type == self.DISCOUNT_PERCENTAGE and self.discount_value > 100:
            errors['discount_value'] = 'A percentage discount cannot be greater than 100%.'
        if self.discount_value is not None and self.discount_value <= 0:
            errors['discount_value'] = 'The discount value must be greater than zero.'
        if self.valid_from and self.expiry_date and self.expiry_date <= self.valid_from:
            errors['expiry_date'] = 'The expiry date must be after the valid-from date.'
        if errors:
            raise ValidationError(errors)

    def is_current(self, now=None):
        now = now or timezone.now()
        return (
            self.is_active
            and self.valid_from <= now <= self.expiry_date
            and (self.usage_limit is None or self.usage_count < self.usage_limit)
        )

    def discount_for(self, subtotal):
        """Return the coupon discount for a subtotal, capped when configured."""
        subtotal = _money(subtotal)
        if subtotal <= 0:
            return Decimal('0.00')
        if self.discount_type == self.DISCOUNT_PERCENTAGE:
            discount = subtotal * self.discount_value / Decimal('100')
        else:
            discount = self.discount_value
        if self.maximum_discount is not None:
            discount = min(discount, self.maximum_discount)
        return min(_money(discount), subtotal)


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    house_number = models.CharField(max_length=120)
    street = models.CharField(max_length=200)
    landmark = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=12)
    country = models.CharField(max_length=100, default='India')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-is_default', '-updated_at')
        indexes = [models.Index(fields=('user', '-updated_at'))]
        verbose_name = 'customer address'
        verbose_name_plural = 'customer addresses'

    def __str__(self):
        return f'{self.full_name}, {self.city} ({self.user.username})'

    def save(self, *args, **kwargs):
        if not self.is_default and not self.pk and not Address.objects.filter(user_id=self.user_id).exists():
            self.is_default = True
        if self.is_default and self.user_id:
            Address.objects.filter(user_id=self.user_id).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def full_address(self):
        parts = [
            self.house_number,
            self.street,
            self.landmark,
            self.city,
            self.state,
            self.pin_code,
            self.country,
        ]
        return ', '.join(part for part in parts if part)

    def snapshot(self):
        return {
            'full_name': self.full_name,
            'phone': self.phone,
            'house_number': self.house_number,
            'street': self.street,
            'landmark': self.landmark,
            'city': self.city,
            'state': self.state,
            'pin_code': self.pin_code,
            'country': self.country,
        }


class StoreProfile(models.Model):
    """Singleton store/business details used on receipts and order confirmations."""

    business_name = models.CharField(max_length=200, default='EuphoriaDJ')
    owner_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    contact_number = models.CharField(max_length=30, blank=True)
    house_number = models.CharField(max_length=120, blank=True)
    street = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pin_code = models.CharField(max_length=12, blank=True)
    country = models.CharField(max_length=100, default='India')
    gstin = models.CharField(max_length=30, blank=True, verbose_name='GSTIN')
    additional_info = models.TextField(blank=True, help_text='Optional business information for invoices and confirmations.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'store information'
        verbose_name_plural = 'store information'

    def __str__(self):
        return self.business_name or 'Store profile'

    def save(self, *args, **kwargs):
        # Keep one authoritative business profile in the database.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        profile = cls.objects.first()
        if profile:
            return profile
        return cls.objects.create()

    @property
    def full_address(self):
        parts = [
            self.house_number,
            self.street,
            self.city,
            self.state,
            self.pin_code,
            self.country,
        ]
        return ', '.join(part for part in parts if part)


class Order(models.Model):
    PAYMENT_METHOD_COD = 'cod'
    PAYMENT_METHOD_RAZORPAY = 'razorpay'
    PAYMENT_METHOD_CHOICES = (
        (PAYMENT_METHOD_COD, 'Cash on Delivery'),
        (PAYMENT_METHOD_RAZORPAY, 'Online payment (Razorpay)'),
    )

    PAYMENT_PENDING = 'pending'
    PAYMENT_PROCESSING = 'processing'
    PAYMENT_SUCCESS = 'success'
    PAYMENT_FAILED = 'failed'
    PAYMENT_REFUNDED = 'refunded'
    PAYMENT_STATUS_CHOICES = (
        (PAYMENT_PENDING, 'Pending'),
        (PAYMENT_PROCESSING, 'Processing'),
        (PAYMENT_SUCCESS, 'Success'),
        (PAYMENT_FAILED, 'Failed'),
        (PAYMENT_REFUNDED, 'Refunded'),
    )
    PAYMENT_STATUS_CSS = {
        PAYMENT_PENDING: 'warning',
        PAYMENT_PROCESSING: 'info',
        PAYMENT_SUCCESS: 'success',
        PAYMENT_FAILED: 'danger',
        PAYMENT_REFUNDED: 'secondary',
    }

    ORDER_PENDING = 'pending'
    ORDER_CONFIRMED = 'confirmed'
    ORDER_PROCESSING = 'processing'
    ORDER_SHIPPED = 'shipped'
    ORDER_OUT_FOR_DELIVERY = 'out_for_delivery'
    ORDER_DELIVERED = 'delivered'
    ORDER_CANCELLED = 'cancelled'
    ORDER_RETURNED = 'returned'
    ORDER_STATUS_CHOICES = (
        (ORDER_PENDING, 'Pending'),
        (ORDER_CONFIRMED, 'Confirmed'),
        (ORDER_PROCESSING, 'Processing'),
        (ORDER_SHIPPED, 'Shipped'),
        (ORDER_OUT_FOR_DELIVERY, 'Out for delivery'),
        (ORDER_DELIVERED, 'Delivered'),
        (ORDER_CANCELLED, 'Cancelled'),
        (ORDER_RETURNED, 'Returned'),
    )
    ORDER_STATUS_CSS = {
        ORDER_PENDING: 'warning',
        ORDER_CONFIRMED: 'info',
        ORDER_PROCESSING: 'info',
        ORDER_SHIPPED: 'primary',
        ORDER_OUT_FOR_DELIVERY: 'primary',
        ORDER_DELIVERED: 'success',
        ORDER_CANCELLED: 'danger',
        ORDER_RETURNED: 'secondary',
    }

    order_number = models.CharField(max_length=32, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)

    address = models.ForeignKey(
        Address,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    shipping_full_name = models.CharField(max_length=150)
    shipping_phone = models.CharField(max_length=20)
    shipping_house_number = models.CharField(max_length=120)
    shipping_street = models.CharField(max_length=200)
    shipping_landmark = models.CharField(max_length=200, blank=True)
    shipping_city = models.CharField(max_length=100)
    shipping_state = models.CharField(max_length=100)
    shipping_pin_code = models.CharField(max_length=12)
    shipping_country = models.CharField(max_length=100, default='India')

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    coupon_discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    shipping_charge = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    final_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
    )
    coupon_code = models.CharField(max_length=50, blank=True)

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default=PAYMENT_METHOD_COD,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_PENDING,
    )
    order_status = models.CharField(
        max_length=20,
        choices=ORDER_STATUS_CHOICES,
        default=ORDER_PENDING,
    )
    transaction_id = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text='Razorpay payment ID after a verified payment.',
    )
    razorpay_order_id = models.CharField(max_length=120, blank=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=('user', '-created_at'))]
        verbose_name = 'order'
        verbose_name_plural = 'orders'

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._new_order_number()
        super().save(*args, **kwargs)

    @staticmethod
    def _new_order_number():
        return f'EUP-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}'

    def get_absolute_url(self):
        return reverse('order_detail', args=[self.order_number])

    @property
    def payment_status_css(self):
        return self.PAYMENT_STATUS_CSS.get(self.payment_status, 'secondary')

    @property
    def order_status_css(self):
        return self.ORDER_STATUS_CSS.get(self.order_status, 'secondary')

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def full_shipping_address(self):
        parts = [
            self.shipping_house_number,
            self.shipping_street,
            self.shipping_landmark,
            self.shipping_city,
            self.shipping_state,
            self.shipping_pin_code,
            self.shipping_country,
        ]
        return ', '.join(part for part in parts if part)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='order_items',
    )
    product_name = models.CharField(max_length=200)
    product_image = models.ImageField(upload_to='order_items/', blank=True, null=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('id',)
        verbose_name = 'order item'
        verbose_name_plural = 'order items'

    def __str__(self):
        return f'{self.product_name} x{self.quantity} ({self.order.order_number})'

    def save(self, *args, **kwargs):
        self.subtotal = _money(self.unit_price * self.quantity)
        super().save(*args, **kwargs)


class PaymentRecord(models.Model):
    """Audit trail for Razorpay order creation and verification attempts."""

    STATUS_CREATED = 'created'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = (
        (STATUS_CREATED, 'Created'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
    )

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payment_records')
    provider = models.CharField(max_length=30, default='razorpay')
    razorpay_order_id = models.CharField(max_length=120, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=120, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)
    signature_verified = models.BooleanField(default=False)
    raw_response = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'payment record'
        verbose_name_plural = 'payment records'

    def __str__(self):
        return f'{self.order.order_number} - {self.get_status_display()}'
