import json
import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from core import ai as ai_service
from core.forms import CheckoutForm, RegistrationForm
from core.helper import custom_mail
from core.models import Address, CartItem, Category, Employee, Favorite, Order, Product, StoreProfile
from core.payments import (
    RazorpayError,
    create_razorpay_order,
    fetch_payment,
    razorpay_configured,
    record_payment_result,
    validate_payment,
    verify_signature,
)
from core.services import (
    add_product_to_cart,
    calculate_totals,
    cart_subtotal,
    checkout_pricing,
    clear_session_coupon,
    create_order,
    get_cart_items,
    mark_order_paid,
    mark_order_payment_failed,
    remove_ordered_products_from_cart,
    set_session_coupon,
    validate_coupon_code,
)

# Create your views here.
''' Views.py -> Each and every function inside
file must have a parameter called request '''

logger = logging.getLogger(__name__)
CHECKOUT_TOKEN_SESSION_KEY = 'checkout_token'


def _safe_next_url(request, target):
    """Return target only when it is a safe same-host redirect."""
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return None


def _redirect_back(request, fallback):
    return redirect(_safe_next_url(request, request.POST.get('next') or request.GET.get('next')) or fallback)


def _parse_quantity(raw_value):
    try:
        quantity = int(raw_value)
    except (TypeError, ValueError):
        return None
    if quantity < 1 or quantity > 5:
        return None
    return quantity


def _request_payload(request):
    """Read a small JSON object or normal form fields from a POST request."""
    if request.content_type == 'application/json':
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except (TypeError, ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
    return request.POST


def _parse_decimal(raw_value):
    if raw_value in (None, ''):
        return None
    try:
        value = Decimal(raw_value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _with_favorites(queryset, user):
    """Attach the signed-in user's favorite row id to each product, when present."""
    if not user.is_authenticated:
        return queryset
    favorite = Favorite.objects.filter(user=user, product=OuterRef('pk')).values('id')[:1]
    return queryset.annotate(user_favorite_id=Subquery(favorite))


def home(request):
    products = _with_favorites(
        Product.objects.filter(available=True).select_related('category'), request.user
    ).order_by('-created_at')
    recent_products = list(products[:8])
    categories = (
        Category.objects.annotate(
            available_count=Count('products', filter=Q(products__available=True))
        )
        .order_by('name')
    )
    ai_recommendations = ai_service.get_recommendations(
        request.user,
        request.session,
        limit=int(getattr(settings, 'AI_RECOMMENDATION_LIMIT', 4)),
        exclude_ids=[product.pk for product in recent_products],
    )
    payload = {
        'site_title': 'EuphoriaDJ',
        'site_description': 'A curated electronics storefront for everyday technology.',
        'recent_products': recent_products,
        'featured_products': recent_products[:4],
        'categories': categories,
        'ai_recommendations': ai_recommendations,
    }
    return render(request, 'home.html', payload)


def about(request):
    age = 25
    fruits = ['apple', 'banana', 'guava', 'mango']
    payload = {
        'age': age,
        'fruits': fruits,
    }
    return render(request, 'about.html', payload)


def service(request):
    return render(request, 'service.html')


def contact(request):
    return render(request, 'contact.html')


def create_employee(request):
    if request.method == "POST":
        emp_name = request.POST['emp_name']
        emp_email = request.POST['emp_email']
        emp_mobile = request.POST['emp_mobile']
        emp_dept = request.POST['emp_dept']
        emp_dob = request.POST['emp_dob']
        emp_address = request.POST['emp_address']

        try:
            emp_obj = Employee.objects.create(
                emp_name=emp_name,
                emp_email=emp_email,
                emp_mobile=emp_mobile,
                emp_dept=emp_dept,
                emp_dob=emp_dob,
                emp_address=emp_address,
            )

            if emp_obj:
                messages.success(request, f"New employee created ! {emp_name}")
                return redirect('create_employee')
            messages.error(request, f"Could not create employee {emp_name}.")
            return redirect('create_employee')

        except Exception as e:
            messages.error(request, f"Error : {e}")
            return redirect('create_employee')
    return render(request, 'create_employee.html')


@login_required(login_url='user_login')
def get_all_employees(request):
    emps = Employee.objects.all()
    payload = {'emps': emps}
    return render(request, "all_employees.html", payload)


@login_required(login_url='user_login')
def update_employee(request, id):
    emp = None
    try:
        emp = Employee.objects.filter(id=id).first()

    except Exception as e:
        messages.error(request, f"Error : {e}")
        return redirect('get_all_employees')

    # Update Form Handling
    if request.method == "POST":
        emp_name = request.POST['emp_name']
        emp_mobile = request.POST['emp_mobile']
        emp_dept = request.POST['emp_dept']
        emp_dob = request.POST['emp_dob']
        emp_address = request.POST['emp_address']

        emp.emp_name = emp_name
        emp.emp_mobile = emp_mobile
        emp.emp_dept = emp_dept
        emp.emp_dob = emp_dob
        emp.emp_address = emp_address
        emp.save()
        messages.success(request, "Employee Updated Successfully !")
        return redirect('get_all_employees')

    payload = {
        'id': id,
        'emp': emp,
    }

    return render(request, "update_employee.html", payload)


@login_required(login_url='user_login')
def delete_employee(request, id):
    try:
        emp = Employee.objects.filter(id=id).first()
        emp.delete()
        messages.success(request, "Employee Deleted Successfully !")
        return redirect('get_all_employees')

    except Exception as e:
        messages.error(request, f"Error : {e}")
        return redirect('get_all_employees')


'''
Authentication Functions --
'''


def user_register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except IntegrityError:
                form.add_error('email', 'An account with this email already exists.')
            except Exception:
                form.add_error(None, 'Registration could not be completed. Please try again.')
            else:
                email_sent = custom_mail(
                    title="Registration Successful",
                    message=(
                        f"Hi {user.first_name},\n\n"
                        "Your registration was successful. Welcome to EuphoriaDJ!\n\n"
                        "You can now sign in to save favorites and keep a cart."
                    ),
                    reply_to="support@euphoriasj.com",
                    recipients=[user.email],
                )
                if email_sent:
                    messages.success(
                        request,
                        "Registration successful! A welcome email has been sent. Please sign in.",
                    )
                else:
                    messages.warning(
                        request,
                        "Registration successful, but the welcome email could not be sent. "
                        "You can still sign in.",
                    )
                return redirect('user_login')
    else:
        form = RegistrationForm()

    return render(request, 'Auth/user_register.html', {'form': form})


def user_login(request):
    next_url = request.POST.get('next') or request.GET.get('next') or ''

    if request.user.is_authenticated:
        return redirect(_safe_next_url(request, next_url) or 'home_page')

    if request.method == "POST":
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not username or not password:
            messages.error(request, "Please enter your username and password.")
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f"Welcome back, {user.first_name or user.username}.")
                return redirect(_safe_next_url(request, next_url) or 'home_page')
            messages.error(request, "Raised issues during login ! Please check your credentials.")

    return render(
        request,
        'Auth/user_login.html',
        {'next': next_url, 'username': request.POST.get('username', '')},
    )


def user_logout(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('home_page')


def welcome_email(request):
    return render(request, 'welcome_email.html') if False else render(request, 'home.html')


# --- Shop / Product ---


def shop(request):
    products = _with_favorites(
        Product.objects.filter(available=True).select_related('category'), request.user
    )
    categories = (
        Category.objects.annotate(
            product_count=Count('products', filter=Q(products__available=True))
        )
        .order_by('name')
    )

    q = request.GET.get('q', '').strip()
    if q:
        products = products.filter(Q(name__icontains=q) | Q(description__icontains=q))

    category_id = request.GET.get('category', '').strip()
    if category_id:
        try:
            products = products.filter(category_id=int(category_id))
        except (TypeError, ValueError):
            category_id = ''

    min_price_raw = request.GET.get('min_price', '').strip()
    max_price_raw = request.GET.get('max_price', '').strip()
    min_price = _parse_decimal(min_price_raw)
    max_price = _parse_decimal(max_price_raw)

    if min_price is not None:
        products = products.filter(price__gte=min_price)
    if max_price is not None:
        products = products.filter(price__lte=max_price)
    if min_price is not None and max_price is not None and min_price > max_price:
        messages.warning(request, "The minimum price is greater than the maximum price.")

    sort = request.GET.get('sort', 'newest')
    sort_options = {
        'newest': ('-created_at', '-id'),
        'name_asc': ('name', 'id'),
        'name_desc': ('-name', '-id'),
        'price_asc': ('price', 'name'),
        'price_desc': ('-price', 'name'),
    }
    if sort not in sort_options:
        sort = 'newest'
    products = products.order_by(*sort_options[sort])

    paginator = Paginator(products, 8)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)
    querystring = query_params.urlencode()
    active_category = categories.filter(pk=category_id).first() if category_id else None
    total_product_count = Product.objects.filter(available=True).count()

    payload = {
        'products': page_obj,
        'page_obj': page_obj,
        'categories': categories,
        'q': q,
        'selected_category': category_id,
        'active_category': active_category,
        'min_price': min_price_raw,
        'max_price': max_price_raw,
        'sort': sort,
        'querystring': querystring,
        'total_product_count': total_product_count,
    }
    return render(request, 'shop.html', payload)


def product_detail(request, slug):
    try:
        product = Product.objects.select_related('category').get(slug=slug, available=True)
    except Product.DoesNotExist:
        messages.error(request, "Product not found.")
        return redirect('shop_page')

    ai_service.record_product_view(request, product)
    favorite = None
    if request.user.is_authenticated:
        favorite = Favorite.objects.filter(user=request.user, product=product).first()

    related = Product.objects.filter(available=True).exclude(pk=product.pk).select_related('category')
    if product.category_id:
        related = related.filter(category_id=product.category_id)
    else:
        related = related.none()
    related_products = list(_with_favorites(related, request.user).order_by('-created_at')[:4])

    payload = {
        'product': product,
        'favorite': favorite,
        'is_fav': favorite is not None,
        'related_products': related_products,
    }
    return render(request, 'product_detail.html', payload)


# --- Favorites ---


@login_required
def favorites(request):
    favs = (
        Favorite.objects.filter(user=request.user)
        .select_related('product__category')
        .order_by('-created_at')
    )
    payload = {'favorites': favs}
    return render(request, 'favorites.html', payload)


@login_required
def add_favorite(request, product_id):
    if request.method != 'POST':
        messages.error(request, "Use the favorite button to save a product.")
        return _redirect_back(request, 'shop_page')

    product = Product.objects.filter(id=product_id, available=True).first()
    if product is None:
        messages.error(request, "Product not found.")
    else:
        _, created = Favorite.objects.get_or_create(user=request.user, product=product)
        if created:
            messages.success(request, "Added to favorites.")
        else:
            messages.info(request, "This product is already in your favorites.")
    return _redirect_back(request, 'favorites')


@login_required
def remove_favorite(request, fav_id):
    if request.method != 'POST':
        messages.error(request, "Use the remove button to change your favorites.")
        return _redirect_back(request, 'favorites')

    favorite = Favorite.objects.filter(id=fav_id, user=request.user).first()
    if favorite is None:
        messages.error(request, "Favorite not found.")
    else:
        favorite.delete()
        messages.success(request, "Removed from favorites.")
    return _redirect_back(request, 'favorites')


# --- Cart ---


@login_required
def cart(request):
    items, coupon, totals, coupon_warning = checkout_pricing(request)
    if coupon_warning:
        messages.warning(request, coupon_warning)

    payload = {
        'items': items,
        'coupon': coupon,
        'subtotal': totals.subtotal,
        'coupon_discount': totals.discount,
        'shipping_charge': totals.shipping,
        'tax_amount': totals.tax,
        'cart_total': totals.total,
        'free_shipping_remaining': totals.free_shipping_remaining,
        'free_shipping_threshold': settings.STORE_FREE_SHIPPING_THRESHOLD,
        'total_quantity': sum(item.quantity for item in items),
    }
    return render(request, 'cart.html', payload)


@login_required
def add_cart(request, product_id):
    if request.method != 'POST':
        messages.error(request, "Use the Add to Cart button to change your cart.")
        return _redirect_back(request, 'shop_page')

    product = Product.objects.filter(id=product_id, available=True).first()
    if product is None:
        messages.error(request, "Product not available.")
        return _redirect_back(request, 'shop_page')

    quantity = _parse_quantity(request.POST.get('quantity', 1))
    if quantity is None:
        messages.error(request, "Quantity must be a whole number between 1 and 5.")
        return _redirect_back(request, reverse('product_detail', args=[product.slug]))

    valid_sources = {choice[0] for choice in CartItem.SOURCE_CHOICES}
    source = request.POST.get('source')
    if source not in valid_sources:
        source = CartItem.SOURCE_PRODUCT_DETAIL

    result = add_product_to_cart(request.user, product, quantity=quantity, source=source)
    if result.created:
        messages.success(request, f"Added {product.name} to your cart.")
    elif result.item.quantity == result.previous_quantity:
        messages.info(
            request,
            f"{product.name} is already at the maximum quantity of 5.",
        )
    elif result.capped:
        messages.info(
            request,
            f"Updated {product.name} to the maximum quantity of 5.",
        )
    else:
        messages.success(request, f"Updated {product.name} quantity to {result.item.quantity}.")
    return _redirect_back(request, 'cart')


@require_POST
def ai_chat(request):
    """JSON endpoint for the local shopping assistant."""
    payload = _request_payload(request)
    if payload is None:
        return JsonResponse({'error': 'Send a JSON object or form data.'}, status=400)

    raw_message = payload.get('message')
    if not isinstance(raw_message, str) or not raw_message.strip():
        return JsonResponse({'error': 'Please enter a message.'}, status=400)

    message = raw_message.strip()
    max_length = int(getattr(settings, 'AI_CHAT_MAX_MESSAGE_LENGTH', 800))
    if len(message) > max_length:
        return JsonResponse(
            {'error': f'Please keep messages under {max_length} characters.'},
            status=400,
        )

    try:
        result = ai_service.handle_chat(request, message)
    except Exception:
        logger.exception('Local AI chat failed')
        result = ai_service.fallback_error_response()
    return JsonResponse(result)


@require_POST
def ai_cart_add(request, product_id):
    """Add one DB-resolved product from an assistant product card."""
    if not request.user.is_authenticated:
        signin = f"{reverse('user_login')}?{urlencode({'next': reverse('cart')})}"
        return JsonResponse(
            {
                'ok': False,
                'error': 'signin_required',
                'message': 'Sign in to add products to your cart.',
                'signin_url': signin,
            },
            status=401,
        )

    payload = _request_payload(request)
    if payload is None:
        return JsonResponse({'ok': False, 'error': 'Send a JSON object or form data.'}, status=400)

    quantity = _parse_quantity(payload.get('quantity', 1))
    if quantity is None:
        return JsonResponse(
            {'ok': False, 'error': 'Quantity must be a whole number between 1 and 5.'},
            status=400,
        )

    product = Product.objects.filter(id=product_id, available=True).first()
    if product is None:
        return JsonResponse({'ok': False, 'error': 'Product not available.'}, status=404)

    try:
        result = add_product_to_cart(
            request.user,
            product,
            quantity=quantity,
            source=CartItem.SOURCE_AI_CHAT,
        )
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': exc.messages[0]}, status=400)

    if result.created:
        message = f'Added {product.name} to your cart.'
    elif result.item.quantity == result.previous_quantity:
        message = f'{product.name} is already at the maximum quantity of 5.'
    elif result.capped:
        message = f'Added {product.name}. Your cart now has the maximum quantity of 5.'
    else:
        message = f'Added {product.name}. Your cart now has {result.item.quantity}.'

    cart_count = (
        CartItem.objects.filter(user=request.user).aggregate(total=Sum('quantity'))['total'] or 0
    )
    quantities = {
        item['product_id']: item['quantity']
        for item in CartItem.objects.filter(user=request.user).values('product_id', 'quantity')
    }
    return JsonResponse(
        {
            'ok': True,
            'message': message,
            'product': ai_service.product_payload(
                product,
                request,
                cart_quantities=quantities,
            ),
            'cart_count': cart_count,
            'cart_url': reverse('cart'),
            'capped': result.capped,
        }
    )


@login_required
def update_cart(request, item_id):
    if request.method != 'POST':
        messages.error(request, "Use the update button to change your cart.")
        return _redirect_back(request, 'cart')

    item = CartItem.objects.filter(id=item_id, user=request.user).first()
    if item is None:
        messages.error(request, "Cart item not found.")
        return _redirect_back(request, 'cart')

    if not item.product.available:
        messages.error(request, "This product is no longer available. Remove it from your cart.")
        return _redirect_back(request, 'cart')

    quantity = _parse_quantity(request.POST.get('quantity'))
    if quantity is None:
        messages.error(request, "Quantity must be a whole number between 1 and 5.")
        return _redirect_back(request, 'cart')

    item.quantity = quantity
    item.save(update_fields=['quantity'])
    messages.success(request, "Cart updated.")
    return _redirect_back(request, 'cart')


@login_required
def remove_cart(request, item_id):
    if request.method != 'POST':
        messages.error(request, "Use the remove button to change your cart.")
        return _redirect_back(request, 'cart')

    item = CartItem.objects.filter(id=item_id, user=request.user).first()
    if item is None:
        messages.error(request, "Cart item not found.")
    else:
        item.delete()
        messages.success(request, "Removed from cart.")
        if not CartItem.objects.filter(user=request.user).exists():
            clear_session_coupon(request)
    return _redirect_back(request, 'cart')


@login_required
def apply_coupon(request):
    if request.method != 'POST':
        messages.error(request, "Use the coupon form to apply a code.")
        return redirect('cart')

    items = get_cart_items(request.user)
    if not items:
        messages.error(request, "Add a product to your cart before applying a coupon.")
        return redirect('cart')

    code = request.POST.get('coupon_code', '')
    try:
        coupon = validate_coupon_code(code, cart_subtotal(items))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('cart')

    set_session_coupon(request, coupon)
    discount = coupon.discount_for(cart_subtotal(items))
    messages.success(
        request,
        f"Coupon {coupon.code} applied. You saved "
        f"{settings.STORE_CURRENCY_SYMBOL}{discount:,.2f}.",
    )
    return redirect('cart')


@login_required
def remove_coupon(request):
    if request.method != 'POST':
        messages.error(request, "Use the coupon form to remove a code.")
        return redirect('cart')
    clear_session_coupon(request)
    messages.success(request, "Coupon removed.")
    return redirect('cart')


# --- Checkout and orders ---


def _checkout_initial(user):
    saved_address = user.addresses.filter(is_default=True).first() or user.addresses.first()
    name = f'{user.first_name} {user.last_name}'.strip() or user.username
    initial = {
        'full_name': name,
        'email': user.email,
        'phone': saved_address.phone if saved_address else '',
        'delivery_full_name': name,
        'country': 'India',
        'save_address': True,
    }
    if saved_address:
        initial.update(
            {
                'saved_address': saved_address.pk,
                'delivery_full_name': saved_address.full_name,
                'delivery_phone': saved_address.phone,
                'house_number': saved_address.house_number,
                'street': saved_address.street,
                'landmark': saved_address.landmark,
                'city': saved_address.city,
                'state': saved_address.state,
                'pin_code': saved_address.pin_code,
                'country': saved_address.country,
            }
        )
    return initial


def _render_checkout(request, form=None):
    items, coupon, totals, coupon_warning = checkout_pricing(request)
    if not items:
        messages.info(request, "Your cart is empty. Add a product before checkout.")
        return redirect('cart')
    if coupon_warning:
        messages.warning(request, coupon_warning)

    if form is None:
        form = CheckoutForm(user=request.user, initial=_checkout_initial(request.user))

    checkout_token = uuid.uuid4().hex
    request.session[CHECKOUT_TOKEN_SESSION_KEY] = checkout_token
    payload = {
        'form': form,
        'items': items,
        'coupon': coupon,
        'subtotal': totals.subtotal,
        'coupon_discount': totals.discount,
        'shipping_charge': totals.shipping,
        'tax_amount': totals.tax,
        'cart_total': totals.total,
        'free_shipping_remaining': totals.free_shipping_remaining,
        'free_shipping_threshold': settings.STORE_FREE_SHIPPING_THRESHOLD,
        'total_quantity': sum(item.quantity for item in items),
        'checkout_token': checkout_token,
        'razorpay_enabled': razorpay_configured(),
    }
    return render(request, 'checkout.html', payload)


@login_required
def checkout(request):
    if request.method != 'POST':
        return _render_checkout(request)

    posted_token = request.POST.get('checkout_token', '')
    expected_token = request.session.pop(CHECKOUT_TOKEN_SESSION_KEY, None)
    if not expected_token or posted_token != expected_token:
        messages.error(
            request,
            "This checkout form has expired or was submitted twice. Please review your cart and try again.",
        )
        return redirect('cart')

    items, coupon, totals, coupon_warning = checkout_pricing(request)
    if not items:
        messages.info(request, "Your cart is empty. Add a product before checkout.")
        return redirect('cart')
    if coupon_warning:
        messages.warning(
            request,
            f"Coupon removed: {coupon_warning} Review the updated total before placing the order.",
        )
        return _render_checkout(request)

    form = CheckoutForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, "Please correct the highlighted checkout fields.")
        return _render_checkout(request, form=form)

    payment_method = form.cleaned_data['payment_method']
    if payment_method == Order.PAYMENT_METHOD_RAZORPAY and not razorpay_configured():
        form.add_error(
            'payment_method',
            'Online payment is not configured yet. Please choose Cash on Delivery '
            'or contact the store administrator.',
        )
        return _render_checkout(request, form=form)

    saved_address = form.cleaned_data.get('saved_address')
    shipping = form.shipping_data()
    address = saved_address
    if saved_address is None and form.cleaned_data.get('save_address'):
        address = Address.objects.create(
            user=request.user,
            full_name=shipping['full_name'],
            phone=shipping['phone'],
            house_number=shipping['house_number'],
            street=shipping['street'],
            landmark=shipping.get('landmark', ''),
            city=shipping['city'],
            state=shipping['state'],
            pin_code=shipping['pin_code'],
            country=shipping['country'],
        )

    order = None
    try:
        order = create_order(
            user=request.user,
            customer=form.customer_data(),
            shipping=shipping,
            address=address,
            coupon_code=coupon.code if coupon else None,
            payment_method=payment_method,
            increment_coupon=(payment_method == Order.PAYMENT_METHOD_COD),
        )
        if payment_method == Order.PAYMENT_METHOD_RAZORPAY:
            create_razorpay_order(order)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else 'The order could not be created.'
        form.add_error(None, message)
        return _render_checkout(request, form=form)
    except RazorpayError as exc:
        if order is not None:
            order.delete()
        form.add_error('payment_method', str(exc))
        return _render_checkout(request, form=form)

    if payment_method == Order.PAYMENT_METHOD_COD:
        remove_ordered_products_from_cart(order)
        clear_session_coupon(request)
        messages.success(
            request,
            f"Order {order.order_number} placed successfully. "
            "Payment is pending because you selected Cash on Delivery.",
        )
        return redirect('order_success', order_number=order.order_number)

    messages.success(
        request,
        f"Order {order.order_number} created. Complete the Razorpay payment to confirm it.",
    )
    return redirect('order_payment', order_number=order.order_number)


@login_required
def order_list(request):
    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related('items')
        .order_by('-created_at')
    )
    paginator = Paginator(orders, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'orders.html', {'orders': page_obj, 'page_obj': page_obj})


@login_required
def order_detail(request, order_number):
    order = get_object_or_404(
        Order.objects.prefetch_related('items').select_related('address'),
        order_number=order_number,
        user=request.user,
    )
    return render(
        request,
        'order_detail.html',
        {
            'order': order,
            'store_profile': StoreProfile.objects.first(),
        },
    )


@login_required
def order_success(request, order_number):
    """Private confirmation page shown after COD placement or verified payment."""
    order = get_object_or_404(
        Order.objects.prefetch_related('items').select_related('address'),
        order_number=order_number,
        user=request.user,
    )
    if order.order_status == Order.ORDER_CANCELLED:
        messages.error(request, "This order has been cancelled.")
        return redirect('order_detail', order_number=order.order_number)
    if (
        order.payment_method == Order.PAYMENT_METHOD_RAZORPAY
        and order.payment_status != Order.PAYMENT_SUCCESS
    ):
        messages.info(request, "Complete the verified online payment to finish this order.")
        return redirect('order_payment', order_number=order.order_number)
    return render(
        request,
        'order_detail.html',
        {
            'order': order,
            'store_profile': StoreProfile.objects.first(),
            'success': True,
        },
    )


@login_required
def order_payment(request, order_number):
    order = get_object_or_404(
        Order.objects.prefetch_related('items'),
        order_number=order_number,
        user=request.user,
    )
    if order.payment_method != Order.PAYMENT_METHOD_RAZORPAY:
        messages.error(request, "This order is not an online-payment order.")
        return redirect('order_detail', order_number=order.order_number)
    if order.payment_status == Order.PAYMENT_SUCCESS:
        messages.info(request, "This order has already been paid.")
        return redirect('order_detail', order_number=order.order_number)
    if order.order_status == Order.ORDER_CANCELLED:
        messages.error(request, "This order has been cancelled and cannot be paid.")
        return redirect('order_detail', order_number=order.order_number)
    if not razorpay_configured():
        messages.error(
            request,
            "Online payment is not configured. Add RAZORPAY_KEY_ID and "
            "RAZORPAY_KEY_SECRET to the environment, or contact the store.",
        )
        return redirect('order_detail', order_number=order.order_number)

    if not order.razorpay_order_id:
        try:
            create_razorpay_order(order)
        except RazorpayError as exc:
            messages.error(request, str(exc))
            return redirect('order_detail', order_number=order.order_number)

    return render(
        request,
        'order_payment.html',
        {
            'order': order,
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'razorpay_order_id': order.razorpay_order_id,
            'amount_paise': int((order.final_total * 100).to_integral_value()),
            'currency': 'INR',
        },
    )


@login_required
@require_POST
def verify_payment(request, order_number):
    order = get_object_or_404(
        Order.objects.prefetch_related('items'),
        order_number=order_number,
        user=request.user,
    )
    if order.payment_method != Order.PAYMENT_METHOD_RAZORPAY:
        messages.error(request, "This order does not use online payment.")
        return redirect('order_detail', order_number=order.order_number)
    if order.payment_status == Order.PAYMENT_SUCCESS:
        messages.info(request, "This payment has already been verified.")
        return redirect('order_success', order_number=order.order_number)

    razorpay_order_id = request.POST.get('razorpay_order_id', '').strip()
    razorpay_payment_id = request.POST.get('razorpay_payment_id', '').strip()
    razorpay_signature = request.POST.get('razorpay_signature', '').strip()

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        mark_order_payment_failed(order)
        record_payment_result(
            order,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            verified=False,
            error_message='Incomplete Razorpay callback fields.',
        )
        messages.error(request, "The payment response was incomplete. Please try the payment again.")
        return redirect('order_payment', order_number=order.order_number)

    if razorpay_order_id != order.razorpay_order_id or not verify_signature(
        razorpay_order_id, razorpay_payment_id, razorpay_signature
    ):
        mark_order_payment_failed(order)
        record_payment_result(
            order,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            verified=False,
            error_message='Razorpay signature verification failed.',
        )
        messages.error(
            request,
            "Payment verification failed. The order is not marked as paid. Please try again.",
        )
        return redirect('order_payment', order_number=order.order_number)

    try:
        payment = fetch_payment(razorpay_payment_id)
    except RazorpayError as exc:
        messages.error(
            request,
            f"{exc} The order remains pending; please retry verification shortly.",
        )
        return redirect('order_payment', order_number=order.order_number)

    payment_error = validate_payment(order, payment)
    if payment_error:
        mark_order_payment_failed(order)
        record_payment_result(
            order,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            verified=False,
            raw_response=json.dumps(payment),
            error_message=payment_error,
        )
        messages.error(request, f"Payment verification failed: {payment_error}")
        return redirect('order_payment', order_number=order.order_number)

    order, newly_paid = mark_order_paid(order, razorpay_payment_id)
    if newly_paid:
        record_payment_result(
            order,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            verified=True,
            raw_response=json.dumps(payment),
        )
        clear_session_coupon(request)
        messages.success(
            request,
            f"Payment verified. Order {order.order_number} is confirmed.",
        )
    else:
        messages.info(request, "This payment was already recorded.")
    return redirect('order_success', order_number=order.order_number)
