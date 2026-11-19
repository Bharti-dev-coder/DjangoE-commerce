from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings

register = template.Library()


@register.filter
def money(value):
    """Format a database decimal as store currency without float conversion."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f'{settings.STORE_CURRENCY_SYMBOL}{amount:,.2f}'
