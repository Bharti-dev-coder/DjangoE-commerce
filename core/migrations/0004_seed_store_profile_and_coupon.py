from datetime import timedelta
from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def seed_store_defaults(apps, schema_editor):
    Coupon = apps.get_model('core', 'Coupon')
    StoreProfile = apps.get_model('core', 'StoreProfile')

    now = timezone.now()
    Coupon.objects.get_or_create(
        code='Bharti123',
        defaults={
            'discount_type': 'percentage',
            'discount_value': Decimal('10.00'),
            'minimum_order_amount': Decimal('0.00'),
            'maximum_discount': Decimal('500.00'),
            'valid_from': now,
            'expiry_date': now + timedelta(days=365),
            'is_active': True,
            'usage_limit': 1000,
            'usage_count': 0,
        },
    )
    StoreProfile.objects.get_or_create(
        pk=1,
        defaults={
            'business_name': 'EuphoriaDJ',
            'email': 'support@euphoriasj.com',
            'country': 'India',
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_coupon_storeprofile_cartitem_source_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_store_defaults, migrations.RunPython.noop),
    ]
