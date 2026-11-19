"""Catalog-grounded local AI shopping assistant.

The language model plans the conversation, but product names, prices,
availability, cart totals, and order details are always read from Django. This
module keeps enough deterministic behavior that search and store help continue
to work when Ollama is offline.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Q, Subquery, Sum
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import urlencode

from core import ai_planner
from core.models import (
    CartItem,
    Category,
    Favorite,
    Order,
    OrderItem,
    Product,
    StoreProfile,
)
from core.services import add_product_to_cart, money

HISTORY_SESSION_KEY = 'storefront_ai_history'
CHAT_PRODUCTS_SESSION_KEY = 'storefront_ai_products'
VIEWED_SESSION_KEY = 'storefront_ai_viewed_products'
MAX_SESSION_PRODUCTS = 8
MAX_VIEWED_PRODUCTS = 12


@dataclass
class Recommendation:
    product: Product
    reason: str


def format_money(value):
    return f'{settings.STORE_CURRENCY_SYMBOL}{money(value):,.2f}'


def _clean_ids(values):
    cleaned = []
    for value in values or []:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _products_from_ids(ids):
    ordered_ids = _clean_ids(ids)
    if not ordered_ids:
        return []
    products = Product.objects.filter(
        id__in=ordered_ids,
        available=True,
    ).select_related('category')
    by_id = {product.id: product for product in products}
    return [by_id[product_id] for product_id in ordered_ids if product_id in by_id]


def record_product_view(request, product):
    """Remember recent product detail views in the session for recommendations."""
    if product is None or not product.available:
        return
    viewed = _clean_ids(request.session.get(VIEWED_SESSION_KEY, []))
    viewed = [product.pk] + [value for value in viewed if value != product.pk]
    request.session[VIEWED_SESSION_KEY] = viewed[:MAX_VIEWED_PRODUCTS]


def record_chat_products(request, products):
    ids = [product.pk for product in products if product and product.pk][:MAX_SESSION_PRODUCTS]
    request.session[CHAT_PRODUCTS_SESSION_KEY] = ids


def _recent_chat_products(request):
    return _products_from_ids(request.session.get(CHAT_PRODUCTS_SESSION_KEY, []))


def _recent_viewed_products(request):
    return _products_from_ids(request.session.get(VIEWED_SESSION_KEY, []))


def _get_history(request):
    history = request.session.get(HISTORY_SESSION_KEY, [])
    if not isinstance(history, list):
        return []
    limit = max(2, int(getattr(settings, 'AI_CHAT_HISTORY_LIMIT', 8)))
    cleaned = []
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        content = item.get('content')
        if role in {'user', 'assistant'} and isinstance(content, str) and content.strip():
            cleaned.append({'role': role, 'content': content.strip()[:500]})
    return cleaned


def _append_history(request, user_message, assistant_message):
    limit = max(2, int(getattr(settings, 'AI_CHAT_HISTORY_LIMIT', 8)))
    history = _get_history(request)
    history.append({'role': 'user', 'content': user_message.strip()[:500]})
    history.append({'role': 'assistant', 'content': (assistant_message or '').strip()[:500]})
    request.session[HISTORY_SESSION_KEY] = history[-limit:]


def _build_context(request):
    history = _get_history(request)
    return {
        'categories': list(Category.objects.values_list('name', flat=True).order_by('name')),
        'sample_products': list(
            Product.objects.filter(available=True)
            .order_by('name')
            .values_list('name', flat=True)[:30]
        ),
        'recent_products': [p.name for p in _recent_chat_products(request)],
        'recent_views': [p.name for p in _recent_viewed_products(request)],
        'history': history,
        'authenticated': bool(request.user.is_authenticated),
    }


def _cart_quantities(user):
    if not user or not user.is_authenticated:
        return {}
    return {
        item['product_id']: item['quantity']
        for item in CartItem.objects.filter(user=user).values('product_id', 'quantity')
    }


def _cart_count(user):
    if not user or not user.is_authenticated:
        return 0
    result = CartItem.objects.filter(user=user).aggregate(total=Sum('quantity'))
    return result['total'] or 0


def _signin_url(next_path):
    return f"{reverse('user_login')}?{urlencode({'next': next_path})}"


def _link(label, url, icon='fas fa-arrow-right'):
    return {'label': label, 'url': url, 'icon': icon}


def _product_image_url(product):
    if product.image:
        try:
            return product.image.url
        except ValueError:
            pass
    return static('theme/img/product-1.png')


def product_payload(product, request, *, reason='', cart_quantities=None):
    cart_quantities = cart_quantities or {}
    description = re.sub(r'\s+', ' ', (product.description or '')).strip()
    if len(description) > 180:
        description = f'{description[:177].rstrip()}...'
    return {
        'id': product.pk,
        'name': product.name,
        'category': product.category.name if product.category_id else 'Uncategorized',
        'description': description,
        'price': str(money(product.price)),
        'price_display': format_money(product.price),
        'price_value': float(money(product.price)),
        'image_url': _product_image_url(product),
        'url': reverse('product_detail', args=[product.slug]),
        'available': bool(product.available),
        'in_cart_quantity': int(cart_quantities.get(product.pk, 0)),
        'can_add': bool(request and request.user.is_authenticated),
        'add_url': reverse('ai_cart_add', args=[product.pk]),
        'reason': reason,
    }


def _favorite_annotated_products(user):
    products = Product.objects.filter(available=True).select_related('category')
    if user and user.is_authenticated:
        favorite = Favorite.objects.filter(
            user=user,
            product=OuterRef('pk'),
        ).values('pk')[:1]
        products = products.annotate(user_favorite_id=Subquery(favorite))
    return products


def _product_tokens(product):
    text = f'{product.name} {product.description}'.lower()
    return [
        word for word in re.findall(r'[a-z0-9]+', text)
        if len(word) >= 3 and not word.isdigit()
    ]


def _term_matches(product, term):
    haystack = ' '.join(
        (
            product.name or '',
            product.description or '',
            product.category.name if product.category_id else '',
        )
    ).lower()
    return term in haystack


def _rank_products(products, terms):
    normalized_terms = [str(term).lower().strip() for term in terms or [] if str(term).strip()]
    scored = []
    for product in products:
        name = product.name.lower()
        description = (product.description or '').lower()
        category = (product.category.name if product.category_id else '').lower()
        score = 0
        for term in normalized_terms:
            if term in name:
                score += 5
                if name.startswith(term):
                    score += 2
            if term in description:
                score += 2
            if term in category:
                score += 2
        if normalized_terms and all(term in name for term in normalized_terms):
            score += 4
        scored.append((score, product.created_at.timestamp(), product.name.lower(), product))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in scored]


def search_products(plan, *, limit=None):
    """Search live products using validated plan filters and query terms."""
    limit = limit or int(getattr(settings, 'AI_SEARCH_LIMIT', 6))
    products = Product.objects.filter(available=True).select_related('category')

    category = (plan.get('category') or '').strip()
    if category:
        products = products.filter(category__name__iexact=category)

    min_price = plan.get('min_price')
    max_price = plan.get('max_price')
    if min_price is not None:
        products = products.filter(price__gte=min_price)
    if max_price is not None:
        products = products.filter(price__lte=max_price)

    terms = [term for term in (plan.get('search_terms') or []) if str(term).strip()]
    candidates = []
    used_term_query = False
    used_expanded_terms = False
    if terms:
        query = Q()
        for term in terms:
            query |= (
                Q(name__icontains=term)
                | Q(description__icontains=term)
                | Q(category__name__icontains=term)
            )
        candidates = list(products.filter(query).order_by('-created_at')[:80])
        used_term_query = bool(candidates)

        if not candidates:
            expanded = ai_planner.expand_search_terms(terms)
            query = Q()
            for term in expanded:
                query |= (
                    Q(name__icontains=term)
                    | Q(description__icontains=term)
                    | Q(category__name__icontains=term)
                )
            candidates = list(products.filter(query).order_by('-created_at')[:80])
            used_term_query = bool(candidates)
            used_expanded_terms = True

    if not candidates:
        # With a category or price filter, still show valid catalog options.
        candidates = list(products.order_by('-created_at')[:limit * 4])
        used_term_query = False

    # A query such as "wireless earbuds" should not return every wireless
    # accessory. When the literal query produced matches, prefer products that
    # contain its most selective term (for example "earbuds" over "wireless").
    if terms and candidates and used_term_query and not used_expanded_terms:
        term_counts = {
            term: sum(1 for product in candidates if _term_matches(product, term))
            for term in terms
        }
        positive_counts = [count for count in term_counts.values() if count]
        if positive_counts:
            smallest = min(positive_counts)
            if smallest < len(candidates):
                selective_terms = [
                    term for term, count in term_counts.items() if count == smallest
                ]
                narrowed = [
                    product
                    for product in candidates
                    if any(_term_matches(product, term) for term in selective_terms)
                ]
                if narrowed:
                    candidates = narrowed

    if terms:
        candidates = _rank_products(candidates, terms)
    else:
        candidates.sort(key=lambda product: product.created_at, reverse=True)
    return candidates[:limit]


def _recommendation_reason(top_category, viewed_seed, signals):
    if top_category:
        return f'More in {top_category} based on your recent activity.'
    if viewed_seed:
        return f'Inspired by your recent view of {viewed_seed.name}.'
    if signals:
        return 'A catalog pick based on your saved items and orders.'
    return 'New in the catalog.'


def get_recommendations(user, session, *, limit=None, exclude_ids=None):
    """Return personalized, database-backed product recommendations."""
    limit = limit or int(getattr(settings, 'AI_RECOMMENDATION_LIMIT', 4))
    exclude_ids = set(exclude_ids or [])
    signals = []
    category_weights = Counter()
    token_weights = Counter()
    viewed_products = _products_from_ids(session.get(VIEWED_SESSION_KEY, []))
    viewed_seed = viewed_products[0] if viewed_products else None

    def add_signal(product, weight):
        if product is None:
            return
        signals.append(product)
        if product.category_id:
            category_weights[product.category_id] += weight
        for token in _product_tokens(product):
            token_weights[token] += weight

    if user and user.is_authenticated:
        favorites = (
            Favorite.objects.filter(user=user)
            .select_related('product__category')
            .values_list('product', flat=True)
        )
        favorite_products = Product.objects.filter(id__in=list(favorites)).select_related('category')
        for product in favorite_products:
            add_signal(product, 4)

        cart_products = Product.objects.filter(
            cart_items__user=user,
            available=True,
        ).select_related('category')
        for product in cart_products:
            add_signal(product, 3)

        ordered_products = (
            Product.objects.filter(
                order_items__order__user=user,
                available=True,
            )
            .select_related('category')
            .distinct()
        )
        for product in ordered_products:
            add_signal(product, 2)

    for product in viewed_products:
        add_signal(product, 2)

    cart_product_ids = set()
    if user and user.is_authenticated:
        cart_product_ids = set(
            CartItem.objects.filter(user=user).values_list('product_id', flat=True)
        )

    candidates = list(_favorite_annotated_products(user))
    excluded = set(exclude_ids) | cart_product_ids
    if signals:
        excluded |= {product.pk for product in viewed_products}
    filtered_candidates = [product for product in candidates if product.pk not in excluded]
    if not filtered_candidates:
        filtered_candidates = [product for product in candidates if product.pk not in exclude_ids]

    category_names = dict(Category.objects.values_list('id', 'name'))
    top_category = ''
    if category_weights:
        top_category = category_names.get(category_weights.most_common(1)[0][0], '')

    def score(product):
        category_score = category_weights.get(product.category_id, 0) * 6
        token_score = min(
            sum(token_weights.get(token, 0) for token in _product_tokens(product)),
            18,
        )
        return category_score + token_score

    if signals:
        filtered_candidates.sort(
            key=lambda product: (score(product), product.created_at.timestamp()),
            reverse=True,
        )
        if filtered_candidates and score(filtered_candidates[0]) == 0:
            filtered_candidates.sort(key=lambda product: product.created_at, reverse=True)
    else:
        filtered_candidates.sort(key=lambda product: product.created_at, reverse=True)

    selected = []
    selected_ids = set()
    category_counts = Counter()
    for product in filtered_candidates:
        if product.category_id and category_counts[product.category_id] >= 2:
            continue
        selected.append(product)
        selected_ids.add(product.pk)
        category_counts[product.category_id] += 1
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for product in filtered_candidates:
            if product.pk in selected_ids:
                continue
            selected.append(product)
            if len(selected) >= limit:
                break

    reason = _recommendation_reason(top_category, viewed_seed, bool(signals))
    return [Recommendation(product=product, reason=reason) for product in selected]


def _order_snapshot(order):
    items = list(order.items.all()[:10])
    return {
        'order_number': order.order_number,
        'status': order.get_order_status_display(),
        'status_code': order.order_status,
        'payment_status': order.get_payment_status_display(),
        'payment_method': order.get_payment_method_display(),
        'total': format_money(order.final_total),
        'created_at': order.created_at.strftime('%d %b %Y'),
        'item_count': sum(item.quantity for item in items),
        'items': [
            {
                'name': item.product_name,
                'quantity': item.quantity,
                'subtotal': format_money(item.subtotal),
            }
            for item in items
        ],
        'detail_url': reverse('order_detail', args=[order.order_number]),
    }


def _store_contact():
    profile = StoreProfile.objects.first()
    if not profile:
        return '', []
    parts = []
    if profile.email:
        parts.append(profile.email)
    if profile.contact_number:
        parts.append(profile.contact_number)
    links = []
    if profile.email:
        links.append(_link('Email support', f'mailto:{profile.email}', 'fas fa-envelope'))
    return ', '.join(parts), links


def _support_links(request, order=None):
    links = []
    if order:
        links.append(_link('View order', reverse('order_detail', args=[order.order_number]), 'fas fa-receipt'))
    links.append(_link('My orders', reverse('order_list'), 'fas fa-box'))
    links.append(_link('Contact support', reverse('contact_page'), 'fas fa-headset'))
    if not request.user.is_authenticated:
        links.append(_link('Sign in', _signin_url(reverse('order_list')), 'fas fa-right-to-bracket'))
    return links


def _order_reply(request, plan):
    if not request.user.is_authenticated:
        return {
            'reply': (
                'I can only show order details after you sign in, so your order history '
                'stays private. Please sign in and then ask again.'
            ),
            'links': [_link('Sign in to view orders', _signin_url(reverse('order_list')), 'fas fa-right-to-bracket')],
            'signin_url': _signin_url(reverse('order_list')),
        }

    orders = Order.objects.filter(user=request.user).prefetch_related('items')
    order_number = (plan.get('order_number') or '').strip()
    order = None
    if order_number:
        order = orders.filter(order_number__iexact=order_number).first()
        if order is None:
            return {
                'reply': (
                    'I could not find that order in your account. Please check the order '
                    'number in My orders, or ask me about your latest order.'
                ),
                'links': [
                    _link('My orders', reverse('order_list'), 'fas fa-box'),
                    _link('Contact support', reverse('contact_page'), 'fas fa-headset'),
                ],
            }
    else:
        order = orders.first()

    if order is None:
        return {
            'reply': 'You do not have any orders yet. Once you check out, I can help you check its status.',
            'links': [
                _link('Browse the shop', reverse('shop_page'), 'fas fa-store'),
                _link('Contact support', reverse('contact_page'), 'fas fa-headset'),
            ],
        }

    snapshot = _order_snapshot(order)
    prefix = 'Your latest order' if not order_number else 'Order'
    reply = (
        f'{prefix} {snapshot["order_number"]} is currently {snapshot["status"].lower()}. '
        f'Payment status: {snapshot["payment_status"].lower()}. '
        f'Total: {snapshot["total"]}.'
    )
    return {
        'reply': reply,
        'order': snapshot,
        'links': _support_links(request, order),
        'suggestions': [
            'What are the shipping charges?',
            'How do I contact support?',
            'Recommend something from the catalog',
        ],
    }


def _shipping_reply():
    threshold = Decimal(settings.STORE_FREE_SHIPPING_THRESHOLD)
    charge = Decimal(settings.STORE_SHIPPING_CHARGE)
    if charge <= 0:
        shipping_line = 'Shipping is free on this storefront.'
    else:
        shipping_line = (
            f'Shipping is {format_money(charge)}. Orders with a subtotal of '
            f'{format_money(threshold)} or more ship free.'
        )
    return {
        'reply': (
            f'{shipping_line} Delivery timing is not stored in this storefront, so I '
            'cannot give you an exact delivery date. You can follow the status of your '
            'own order in My orders or contact the store team.'
        ),
        'links': [
            _link('My orders', reverse('order_list'), 'fas fa-box'),
            _link('Contact support', reverse('contact_page'), 'fas fa-headset'),
        ],
        'suggestions': [
            'How do I track my order?',
            'What payment methods are available?',
            'Show me products under a budget',
        ],
    }


def _payment_reply():
    online_enabled = bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)
    online = (
        'online payment through Razorpay'
        if online_enabled
        else 'online payment is not currently configured'
    )
    return {
        'reply': (
            f'Cash on delivery is supported, and {online}. Payment status is shown '
            'on your own order details. The storefront does not store card details.'
        ),
        'links': [
            _link('My orders', reverse('order_list'), 'fas fa-box'),
            _link('Contact support', reverse('contact_page'), 'fas fa-headset'),
        ],
        'suggestions': [
            'What are the shipping charges?',
            'Where is my order?',
            'How do coupons work?',
        ],
    }


def _returns_reply():
    contact, contact_links = _store_contact()
    contact_line = f' You can reach the store at {contact}.' if contact else ''
    return {
        'reply': (
            'This storefront does not show a returns, refunds, or exchange policy in '
            'its data, so I cannot promise a policy that is not configured.'
            f'{contact_line} Please contact the store team with your order number for help.'
        ),
        'links': [
            _link('Contact support', reverse('contact_page'), 'fas fa-headset'),
            _link('My orders', reverse('order_list'), 'fas fa-box'),
            *contact_links,
        ],
        'suggestions': [
            'How do I contact support?',
            'Where is my order?',
            'What are the shipping charges?',
        ],
    }


def _cancellation_reply():
    contact, contact_links = _store_contact()
    contact_line = f' Store contact: {contact}.' if contact else ''
    return {
        'reply': (
            'There is no self-service cancellation option in this storefront. If your '
            'order is still pending or confirmed, contact the store team with the order '
            f'number as soon as possible.{contact_line}'
        ),
        'links': [
            _link('Contact support', reverse('contact_page'), 'fas fa-headset'),
            _link('My orders', reverse('order_list'), 'fas fa-box'),
            *contact_links,
        ],
        'suggestions': [
            'Where is my order?',
            'How do I contact support?',
            'What are the shipping charges?',
        ],
    }


def _account_reply(request):
    if request.user.is_authenticated:
        return {
            'reply': (
                'You are signed in. Your cart, favorites, and order history are private '
                'to your account. You can review them from the account pages.'
            ),
            'links': [
                _link('My orders', reverse('order_list'), 'fas fa-box'),
                _link('Favorites', reverse('favorites'), 'fas fa-heart'),
                _link('Your cart', reverse('cart'), 'fas fa-shopping-cart'),
            ],
            'suggestions': [
                'Where is my latest order?',
                'Recommend something from the catalog',
                'What are the shipping charges?',
            ],
        }
    return {
        'reply': (
            'You can create an account or sign in from the account menu. Signing in '
            'keeps your favorites, cart, and order history private to you.'
        ),
        'links': [
            _link('Sign in', _signin_url(reverse('home_page')), 'fas fa-right-to-bracket'),
            _link('Create an account', reverse('user_register'), 'fas fa-user-plus'),
        ],
        'signin_url': _signin_url(reverse('home_page')),
        'suggestions': [
            'How do I track my order?',
            'Show me wireless earbuds',
            'What are the shipping charges?',
        ],
    }


def _cart_help_reply():
    return {
        'reply': (
            'Cart quantities are limited to 1-5 per product. You can update or remove '
            'items on the cart page, and a valid coupon can be applied there before '
            'checkout.'
        ),
        'links': [
            _link('Open your cart', reverse('cart'), 'fas fa-shopping-cart'),
            _link('Browse products', reverse('shop_page'), 'fas fa-store'),
        ],
        'suggestions': [
            'How do coupons work?',
            'What are the shipping charges?',
            'Recommend a laptop',
        ],
    }


def _contact_reply():
    profile = StoreProfile.objects.first()
    if not profile:
        return {
            'reply': 'The Contact page has the store team’s current details.',
            'links': [_link('Contact support', reverse('contact_page'), 'fas fa-headset')],
        }
    parts = []
    if profile.email:
        parts.append(profile.email)
    if profile.contact_number:
        parts.append(profile.contact_number)
    contact = ' or '.join(parts) if parts else 'the Contact page'
    return {
        'reply': f'You can reach the store team at {contact}.',
        'links': [
            _link('Contact page', reverse('contact_page'), 'fas fa-headset'),
            *([_link('Email support', f'mailto:{profile.email}', 'fas fa-envelope')] if profile.email else []),
        ],
        'suggestions': [
            'Where is my order?',
            'What are the shipping charges?',
            'How do I return an item?',
        ],
    }


def _website_reply():
    return {
        'reply': (
            'You can search and filter the catalog, save favorites, add products to '
            'your cart in quantities of 1-5, apply a valid coupon, and check out with '
            'a delivery address. Your order history stays available under My orders.'
        ),
        'links': [
            _link('Shop products', reverse('shop_page'), 'fas fa-store'),
            _link('My orders', reverse('order_list'), 'fas fa-box'),
            _link('Contact support', reverse('contact_page'), 'fas fa-headset'),
        ],
        'suggestions': [
            'Find wireless earbuds under a budget',
            'Recommend a laptop for study',
            'What are the shipping charges?',
        ],
    }


def _capabilities_reply():
    return {
        'reply': (
            'I can search the live EuphoriaDJ catalog, recommend products from your '
            'recent activity, add a product to your cart, and help with shipping, '
            'payment, account, and order questions. What are you shopping for?'
        ),
        'links': [
            _link('Browse the shop', reverse('shop_page'), 'fas fa-store'),
            _link('My orders', reverse('order_list'), 'fas fa-box'),
        ],
        'suggestions': [
            'Find wireless earbuds under a budget',
            'Recommend a laptop for study',
            'Where is my order?',
            'What are the shipping charges?',
        ],
    }


def _products_for_search_plan(plan, request, limit=None):
    products = search_products(plan, limit=limit)
    quantities = _cart_quantities(request.user)
    return products, [
        product_payload(product, request, cart_quantities=quantities)
        for product in products
    ]


def _handle_search(request, plan):
    products, payloads = _products_for_search_plan(plan, request)
    if not products:
        return {
            'reply': (
                'I could not find a matching product in the current catalog. Try a '
                'broader product name, another category, or a higher budget.'
            ),
            'links': [_link('Browse all products', reverse('shop_page'), 'fas fa-store')],
            'suggestions': [
                'Show me all laptops',
                'Find headphones under a budget',
                'What are the shipping charges?',
            ],
        }

    record_chat_products(request, products)
    filters = []
    if plan.get('category'):
        filters.append(f'in {plan["category"]}')
    if plan.get('max_price') is not None:
        filters.append(f'under {format_money(plan["max_price"])}')
    if plan.get('min_price') is not None and plan.get('max_price') is None:
        filters.append(f'from {format_money(plan["min_price"])}')
    suffix = f' {", ".join(filters)}' if filters else ''
    count = len(products)
    noun = 'product' if count == 1 else 'products'
    reply = (
        f'I found {count} {noun} in the live catalog{suffix}. '
        'These prices and availability come from the store database.'
    )
    suggestions = []
    if request.user.is_authenticated:
        suggestions.append('Add the first one to my cart')
    suggestions.extend([
        'Show me more options',
        'Recommend something similar',
        'What are the shipping charges?',
    ])
    return {
        'reply': reply,
        'products': payloads,
        'links': [
            _link('Open the shop', reverse('shop_page'), 'fas fa-store'),
        ],
        'suggestions': suggestions[:4],
    }


def _handle_recommendation(request, plan):
    recommendations = get_recommendations(
        request.user,
        request.session,
        limit=int(getattr(settings, 'AI_RECOMMENDATION_LIMIT', 4)),
    )
    if not recommendations:
        return {
            'reply': 'I could not build a recommendation from the current catalog. Try browsing the shop first.',
            'links': [_link('Browse the shop', reverse('shop_page'), 'fas fa-store')],
            'suggestions': ['Show me all products', 'What are the shipping charges?'],
        }
    products = [item.product for item in recommendations]
    record_chat_products(request, products)
    quantities = _cart_quantities(request.user)
    payloads = [
        product_payload(
            item.product,
            request,
            reason=item.reason,
            cart_quantities=quantities,
        )
        for item in recommendations
    ]
    personalized = any(
        item.product.category_id
        for item in recommendations
        if item.reason != 'New in the catalog.'
    )
    reply = (
        'Here are a few catalog picks based on your recent views, saved items, cart, '
        'and order history where available.'
        if personalized
        else 'Here are a few recent catalog picks while you explore.'
    )
    return {
        'reply': reply,
        'products': payloads,
        'links': [_link('Browse all products', reverse('shop_page'), 'fas fa-store')],
        'suggestions': [
            'Add the first one to my cart',
            'Show me products under a budget',
            'What are the shipping charges?',
        ],
    }


def _resolve_add_candidates(request, plan):
    recent = _recent_chat_products(request)
    search_terms = [str(term) for term in (plan.get('search_terms') or []) if str(term).strip()]
    product_name = (plan.get('product_name') or '').strip()

    if product_name:
        name_terms = [
            term for term in re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)*', product_name.lower())
            if len(term) >= 2
        ]
        search_terms = name_terms + [term for term in search_terms if term not in name_terms]

    if not search_terms and not plan.get('category') and plan.get('min_price') is None and plan.get('max_price') is None:
        if recent:
            return [recent[0]], True
        return [], True

    candidate_plan = dict(plan)
    candidate_plan['search_terms'] = search_terms[:8]
    candidates = search_products(candidate_plan, limit=8)
    reference_recent = bool(
        recent and re.search(r'\b(?:it|this|that|first|first one|same|last)\b', (plan.get('product_name') or ''))
    )
    if reference_recent:
        first = recent[0]
        candidates = [first] + [product for product in candidates if product.pk != first.pk]

    if product_name:
        normalized = product_name.lower().strip()
        exact = [product for product in candidates if product.name.lower() == normalized]
        if exact:
            return exact[:1], False
        contains = [product for product in candidates if normalized in product.name.lower()]
        if len(contains) == 1:
            return contains[:1], False

    return candidates, False


def _add_quantity_message(result, product):
    if result.created:
        return f'Added {product.name} to your cart.'
    if result.item.quantity == result.previous_quantity:
        return f'{product.name} is already at the maximum quantity of 5.'
    if result.capped:
        return f'Added {product.name}. Your cart now has {result.item.quantity}, the maximum quantity of 5.'
    return f'Added {product.name}. Your cart now has {result.item.quantity}.'


def _handle_add(request, plan):
    quantity = plan.get('quantity', 1)
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1 or quantity > 5:
        return {
            'reply': 'I can add between 1 and 5 of a product at a time. Please choose a quantity from 1 to 5.',
            'suggestions': ['Add one to my cart', 'Show me products'],
        }

    candidates, recent_reference = _resolve_add_candidates(request, plan)
    if not candidates:
        return {
            'reply': (
                'I could not find that product in the current catalog. Try naming the '
                'product or category more specifically.'
            ),
            'links': [_link('Browse the shop', reverse('shop_page'), 'fas fa-store')],
            'suggestions': ['Show me laptops', 'Find wireless earbuds', 'What are the shipping charges?'],
        }

    if not request.user.is_authenticated:
        quantities = {}
        payloads = [
            product_payload(product, request, cart_quantities=quantities)
            for product in candidates[:4]
        ]
        signin = _signin_url(reverse('cart'))
        return {
            'reply': (
                'I can add products to a cart only after you sign in, so the cart '
                'stays tied to your account. Sign in and ask me again.'
            ),
            'products': payloads,
            'links': [_link('Sign in to add to cart', signin, 'fas fa-right-to-bracket')],
            'signin_url': signin,
            'action': {'type': 'signin_required'},
            'suggestions': ['Show me the catalog', 'What are the shipping charges?'],
        }

    if len(candidates) > 1:
        quantities = _cart_quantities(request.user)
        payloads = [
            product_payload(product, request, cart_quantities=quantities)
            for product in candidates[:6]
        ]
        record_chat_products(request, candidates[:MAX_SESSION_PRODUCTS])
        return {
            'reply': (
                'I found more than one match. Which one should I add to your cart? '
                'Use the Add to cart button on a product below.'
            ),
            'products': payloads,
            'suggestions': ['Add the first one to my cart', 'Show me more options'],
        }

    product = candidates[0]
    try:
        result = add_product_to_cart(
            request.user,
            product,
            quantity=quantity,
            source=CartItem.SOURCE_AI_CHAT,
        )
    except ValidationError:
        return {
            'reply': 'That product cannot be added to the cart right now.',
            'links': [_link('Browse the shop', reverse('shop_page'), 'fas fa-store')],
        }

    record_chat_products(request, [product])
    cart_count = _cart_count(request.user)
    quantities = _cart_quantities(request.user)
    payload = product_payload(product, request, cart_quantities=quantities)
    return {
        'reply': _add_quantity_message(result, product),
        'products': [payload],
        'links': [
            _link('View your cart', reverse('cart'), 'fas fa-shopping-cart'),
            _link('Keep shopping', reverse('shop_page'), 'fas fa-store'),
        ],
        'action': {
            'type': 'cart_added',
            'product_id': product.pk,
            'product_name': product.name,
            'quantity': result.item.quantity,
            'requested_quantity': result.requested_quantity,
            'cart_count': cart_count,
            'cart_url': reverse('cart'),
            'capped': result.capped,
        },
        'suggestions': [
            'View my cart',
            'Recommend something similar',
            'What are the shipping charges?',
        ],
    }


def _handle_support(request, plan):
    topic = plan.get('support_topic') or 'other'
    if topic == 'order_status' or plan.get('intent') == 'order_status':
        return _order_reply(request, plan)
    if topic == 'shipping':
        return _shipping_reply()
    if topic == 'payment':
        return _payment_reply()
    if topic == 'returns':
        return _returns_reply()
    if topic == 'cancellation':
        return _cancellation_reply()
    if topic == 'account':
        return _account_reply(request)
    if topic == 'cart':
        return _cart_help_reply()
    if topic == 'contact':
        return _contact_reply()
    if topic == 'website':
        return _website_reply()
    if topic == 'product':
        if plan.get('search_terms') or plan.get('category') or plan.get('product_name'):
            product_plan = dict(plan)
            if not product_plan.get('search_terms') and product_plan.get('product_name'):
                product_plan['search_terms'] = [
                    term for term in re.findall(r'[a-z0-9]+', product_plan['product_name'].lower())
                    if len(term) >= 2
                ]
            return _handle_search(request, product_plan)
        return _capabilities_reply()
    return _capabilities_reply()


def _base_response():
    return {
        'reply': '',
        'intent': 'other',
        'products': [],
        'links': [],
        'order': None,
        'action': None,
        'suggestions': [
            'Find wireless earbuds under a budget',
            'Recommend a laptop for study',
            'Where is my order?',
            'What are the shipping charges?',
        ],
        'ai_available': True,
        'degraded': False,
        'notice': None,
        'signin_url': None,
    }


def handle_chat(request, message):
    """Handle one authenticated or anonymous chat turn."""
    context = _build_context(request)
    plan, ai_available = ai_planner.interpret_message(message, context)
    base = _base_response()
    base['intent'] = plan['intent']
    base['ai_available'] = ai_available
    base['degraded'] = not ai_available
    if not ai_available:
        base['notice'] = (
            'The local AI model is offline, so this reply uses catalog search and '
            'store data only. Start Ollama or pull the configured model to restore '
            'natural-language planning.'
        )

    intent = plan['intent']
    if intent == 'add_to_cart':
        result = _handle_add(request, plan)
    elif intent == 'order_status':
        result = _order_reply(request, plan)
    elif intent == 'support':
        result = _handle_support(request, plan)
    elif intent == 'recommendation':
        result = _handle_recommendation(request, plan)
    elif intent == 'greeting':
        result = {
            'reply': (
                'Hello! I can search the live catalog, recommend products, add '
                'something to your cart, or help with an order. What are you looking for?'
            ),
            'links': [_link('Browse the shop', reverse('shop_page'), 'fas fa-store')],
            'suggestions': _base_response()['suggestions'],
        }
    elif intent in {'product_search', 'other'} and (
        plan.get('search_terms') or plan.get('category')
        or plan.get('min_price') is not None or plan.get('max_price') is not None
        or intent == 'product_search'
    ):
        result = _handle_search(request, plan)
    else:
        result = _capabilities_reply()

    base.update(result)
    base['intent'] = plan['intent']
    base['ai_available'] = ai_available
    base['degraded'] = not ai_available
    base['cart_count'] = _cart_count(request.user)
    base.setdefault('signin_url', None)
    if not ai_available and not base.get('notice'):
        base['notice'] = (
            'The local AI model is offline. I can still search the catalog and '
            'answer basic store questions from database data.'
        )
    _append_history(request, message, base.get('reply', ''))
    return base


def fallback_error_response():
    response = _base_response()
    response.update({
        'reply': (
            'I hit a temporary problem while handling that message. Please try again. '
            'Catalog search and basic store help are still available.'
        ),
        'intent': 'other',
        'ai_available': False,
        'degraded': True,
        'notice': 'The local assistant could not complete this request.',
    })
    return response
