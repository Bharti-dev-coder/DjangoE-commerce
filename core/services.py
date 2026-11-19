from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.models import CartItem, Coupon, Order, OrderItem


COUPON_SESSION_KEY = 'storefront_coupon_code'
COUPON_OWNER_SESSION_KEY = 'storefront_coupon_owner'


def money(value):
    """Normalize money to two decimal places using decimal arithmetic."""
    return Decimal(value or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_cart_items(user):
    return list(
        CartItem.objects.filter(user=user)
        .select_related('product__category')
        .order_by('added_at')
    )


@dataclass
class CartAddResult:
    """Outcome of a single cart add, used by both forms and the AI assistant."""

    item: CartItem
    created: bool
    requested_quantity: int
    previous_quantity: int

    @property
    def capped(self):
        return self.item.quantity < self.previous_quantity + self.requested_quantity


def add_product_to_cart(user, product, quantity=1, source=CartItem.SOURCE_PRODUCT_DETAIL):
    """Add a product using the storefront's 1-5 quantity rule.

    The product and quantity must already come from trusted server-side data.
    """
    if not product.available:
        raise ValidationError('Product not available.')

    try:
        quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError('Quantity must be a whole number between 1 and 5.') from exc
    if quantity < 1 or quantity > 5:
        raise ValidationError('Quantity must be a whole number between 1 and 5.')

    valid_sources = {choice[0] for choice in CartItem.SOURCE_CHOICES}
    if source not in valid_sources:
        source = CartItem.SOURCE_PRODUCT_DETAIL

    item, created = CartItem.objects.get_or_create(
        user=user,
        product=product,
        defaults={'quantity': quantity, 'source': source},
    )
    previous_quantity = 0 if created else item.quantity
    if not created:
        item.quantity = min(previous_quantity + quantity, 5)
        item.source = source
        item.save(update_fields=['quantity', 'source'])

    return CartAddResult(
        item=item,
        created=created,
        requested_quantity=quantity,
        previous_quantity=previous_quantity,
    )


def cart_subtotal(items):
    return money(sum((item.product.price * item.quantity for item in items), Decimal('0.00')))


@dataclass
class CartTotals:
    subtotal: Decimal
    discount: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal
    free_shipping_remaining: Decimal

    @property
    def discounted_subtotal(self):
        return money(max(self.subtotal - self.discount, Decimal('0.00')))


def calculate_totals(items, coupon=None):
    subtotal = cart_subtotal(items)
    discount = coupon.discount_for(subtotal) if coupon else Decimal('0.00')
    discounted_subtotal = money(max(subtotal - discount, Decimal('0.00')))

    tax_rate = Decimal(settings.STORE_TAX_RATE)
    tax = money(discounted_subtotal * tax_rate / Decimal('100')) if tax_rate else Decimal('0.00')

    free_shipping_threshold = Decimal(settings.STORE_FREE_SHIPPING_THRESHOLD)
    if not items or subtotal >= free_shipping_threshold:
        shipping = Decimal('0.00')
        free_shipping_remaining = Decimal('0.00')
    else:
        shipping = money(settings.STORE_SHIPPING_CHARGE)
        free_shipping_remaining = money(free_shipping_threshold - subtotal)

    total = money(discounted_subtotal + tax + shipping)
    return CartTotals(
        subtotal=subtotal,
        discount=money(discount),
        shipping=shipping,
        tax=tax,
        total=total,
        free_shipping_remaining=free_shipping_remaining,
    )


def coupon_validation_error(coupon, subtotal, now=None):
    now = now or timezone.now()
    if not coupon.is_active:
        return 'This coupon is not active.'
    if coupon.valid_from and now < coupon.valid_from:
        return 'This coupon is not valid yet.'
    if coupon.expiry_date and now > coupon.expiry_date:
        return 'This coupon has expired.'
    if coupon.usage_limit is not None and coupon.usage_count >= coupon.usage_limit:
        return 'This coupon has reached its usage limit.'
    if subtotal < coupon.minimum_order_amount:
        return (
            'This coupon requires a minimum order of '
            f'{settings.STORE_CURRENCY_SYMBOL}{coupon.minimum_order_amount:,.2f}.'
        )
    return None


def validate_coupon_code(code, subtotal, lock=False):
    """Find and validate a coupon. Raises ValidationError with a useful message."""
    code = (code or '').strip()
    if not code:
        raise ValidationError('Enter a coupon code.')

    queryset = Coupon.objects.all()
    if lock:
        queryset = queryset.select_for_update()
    coupon = queryset.filter(code__iexact=code).first()
    if coupon is None:
        raise ValidationError('This coupon code is not valid.')

    error = coupon_validation_error(coupon, subtotal)
    if error:
        raise ValidationError(error)
    return coupon


def set_session_coupon(request, coupon):
    request.session[COUPON_SESSION_KEY] = coupon.code
    request.session[COUPON_OWNER_SESSION_KEY] = request.user.pk


def clear_session_coupon(request):
    request.session.pop(COUPON_SESSION_KEY, None)
    request.session.pop(COUPON_OWNER_SESSION_KEY, None)


def get_session_coupon(request, subtotal):
    """Return (coupon, warning). Invalid/stale session coupons are cleared."""
    code = request.session.get(COUPON_SESSION_KEY)
    owner = request.session.get(COUPON_OWNER_SESSION_KEY)
    if not code or not request.user.is_authenticated or str(owner) != str(request.user.pk):
        return None, None

    try:
        coupon = validate_coupon_code(code, subtotal)
    except ValidationError as exc:
        clear_session_coupon(request)
        return None, exc.messages[0]
    return coupon, None


def checkout_pricing(request):
    """Load the current user's cart and coupon, returning authoritative totals."""
    items = get_cart_items(request.user)
    subtotal = cart_subtotal(items)
    coupon, coupon_warning = get_session_coupon(request, subtotal)
    totals = calculate_totals(items, coupon)
    return items, coupon, totals, coupon_warning


@transaction.atomic
def create_order(
    *,
    user,
    customer,
    shipping,
    address=None,
    coupon_code=None,
    payment_method=Order.PAYMENT_METHOD_COD,
    increment_coupon=False,
):
    """Create an order and its item snapshots from the authoritative cart."""
    items = list(
        CartItem.objects.select_for_update()
        .filter(user=user)
        .select_related('product')
        .order_by('added_at')
    )
    if not items:
        raise ValidationError('Your cart is empty.')

    unavailable = [item.product.name for item in items if not item.product.available]
    if unavailable:
        raise ValidationError(
            'These products are no longer available: ' + ', '.join(unavailable)
        )

    coupon = None
    if coupon_code:
        subtotal = cart_subtotal(items)
        coupon = validate_coupon_code(coupon_code, subtotal, lock=True)

    totals = calculate_totals(items, coupon)

    order = Order.objects.create(
        user=user,
        customer_name=customer['name'],
        customer_email=customer['email'],
        customer_phone=customer['phone'],
        address=address,
        shipping_full_name=shipping['full_name'],
        shipping_phone=shipping['phone'],
        shipping_house_number=shipping['house_number'],
        shipping_street=shipping['street'],
        shipping_landmark=shipping.get('landmark', ''),
        shipping_city=shipping['city'],
        shipping_state=shipping['state'],
        shipping_pin_code=shipping['pin_code'],
        shipping_country=shipping['country'],
        subtotal=totals.subtotal,
        coupon_discount=totals.discount,
        shipping_charge=totals.shipping,
        tax_amount=totals.tax,
        final_total=totals.total,
        coupon=coupon,
        coupon_code=coupon.code if coupon else '',
        payment_method=payment_method,
        payment_status=Order.PAYMENT_PENDING,
        order_status=Order.ORDER_PENDING,
    )

    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                product=item.product,
                product_name=item.product.name,
                product_image=item.product.image.name if item.product.image else None,
                unit_price=item.product.price,
                quantity=item.quantity,
                subtotal=money(item.product.price * item.quantity),
            )
            for item in items
        ]
    )

    if increment_coupon and coupon:
        Coupon.objects.filter(pk=coupon.pk).update(usage_count=F('usage_count') + 1)

    return order


def remove_ordered_products_from_cart(order):
    """Remove only the cart lines represented by this order."""
    product_ids = [
        product_id
        for product_id in order.items.values_list('product_id', flat=True)
        if product_id is not None
    ]
    if product_ids and order.user_id:
        CartItem.objects.filter(user_id=order.user_id, product_id__in=product_ids).delete()


def mark_order_paid(order, payment_id):
    """Idempotently mark an order paid and clear the ordered cart lines."""
    with transaction.atomic():
        locked_order = (
            Order.objects.select_for_update()
            .select_related('coupon')
            .get(pk=order.pk)
        )
        if locked_order.payment_status == Order.PAYMENT_SUCCESS:
            return locked_order, False

        locked_order.payment_status = Order.PAYMENT_SUCCESS
        locked_order.order_status = Order.ORDER_CONFIRMED
        locked_order.transaction_id = payment_id
        locked_order.save(
            update_fields=[
                'payment_status',
                'order_status',
                'transaction_id',
                'updated_at',
            ]
        )

        if locked_order.coupon_id:
            Coupon.objects.filter(pk=locked_order.coupon_id).update(
                usage_count=F('usage_count') + 1
            )

        remove_ordered_products_from_cart(locked_order)
        return locked_order, True


def mark_order_payment_failed(order):
    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        if locked_order.payment_status == Order.PAYMENT_SUCCESS:
            return locked_order
        locked_order.payment_status = Order.PAYMENT_FAILED
        locked_order.save(update_fields=['payment_status', 'updated_at'])
        return locked_order
