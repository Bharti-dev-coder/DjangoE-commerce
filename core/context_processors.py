from django.conf import settings
from django.db.models import Count, Q, Sum

from core.models import CartItem, Category, Favorite, StoreProfile


def storefront(request):
    """Small navigation values and store-wide display settings."""
    categories = (
        Category.objects.annotate(
            product_count=Count('products', filter=Q(products__available=True))
        )
        .order_by('name')
    )

    cart_count = 0
    favorite_count = 0
    if request.user.is_authenticated:
        cart_count = (
            CartItem.objects.filter(user=request.user).aggregate(total=Sum('quantity'))['total'] or 0
        )
        favorite_count = Favorite.objects.filter(user=request.user).count()

    return {
        'nav_categories': categories,
        'cart_count': cart_count,
        'favorite_count': favorite_count,
        'currency_symbol': settings.STORE_CURRENCY_SYMBOL,
        'currency_code': settings.STORE_CURRENCY_CODE,
        'free_shipping_threshold': settings.STORE_FREE_SHIPPING_THRESHOLD,
        'store_profile': StoreProfile.objects.first(),
        'razorpay_enabled': bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET),
        'ai_model_name': getattr(settings, 'OLLAMA_MODEL', ''),
        'ai_chat_max_message_length': int(
            getattr(settings, 'AI_CHAT_MAX_MESSAGE_LENGTH', 800)
        ),
        'ai_enabled': bool(
            getattr(settings, 'OLLAMA_ENABLED', False)
            and getattr(settings, 'OLLAMA_BASE_URL', '')
            and getattr(settings, 'OLLAMA_MODEL', '')
        ),
    }
