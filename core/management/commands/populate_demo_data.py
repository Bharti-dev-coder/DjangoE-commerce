import shutil
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Category, Product


CATEGORIES = [
    ('smartphones', 'Smartphones', 'Phones and mobile devices for everyday use.'),
    ('laptops', 'Computers', 'Laptops, desktops and displays for work, study and creative projects.'),
    ('audio', 'Audio', 'Headphones and personal listening gear.'),
    ('cameras', 'Cameras', 'Cameras, lenses and imaging gear for photos and video.'),
    ('wearables', 'Wearables', 'Fitness bands, smart watches and wearable accessories.'),
    ('accessories', 'Accessories', 'Useful extras for phones, computers and cameras.'),
]

# The theme's demo photographs show a different set of real products from the
# original placeholder names. Each entry keeps the legacy slug so an existing
# demo row is corrected in place instead of being duplicated.
PRODUCTS = [
    {
        'slug': 'polaroid-onestep-2-instant-camera',
        'legacy_slug': 'aurora-x1-smartphone',
        'name': 'Polaroid OneStep 2 Instant Camera',
        'category': 'cameras',
        'price': '11999.00',
        'image_number': 1,
        'description': (
            'A point-and-shoot instant camera with a built-in flash, selfie mirror '
            'and classic Polaroid square prints.'
        ),
    },
    {
        'slug': 'huawei-band-3e',
        'legacy_slug': 'nova-pro-5g',
        'name': 'Huawei Band 3e',
        'category': 'wearables',
        'price': '1999.00',
        'image_number': 2,
        'description': (
            'A lightweight fitness band with step, sleep and workout tracking, '
            'plus a comfortable wrist strap.'
        ),
    },
    {
        'slug': 'apple-iphone-6-16gb-refurbished',
        'legacy_slug': 'pocket-mini-phone',
        'name': 'Apple iPhone 6 16GB (Refurbished)',
        'category': 'smartphones',
        'price': '4999.00',
        'image_number': 3,
        'description': (
            'A refurbished 4.7-inch iPhone with a crisp display, Touch ID and '
            'dependable everyday performance.'
        ),
    },
    {
        'slug': 'canon-eos-5d-dslr-50mm',
        'legacy_slug': 'vector-14-laptop',
        'name': 'Canon EOS 5D DSLR with 50mm Lens',
        'category': 'cameras',
        'price': '32999.00',
        'image_number': 4,
        'description': (
            'A classic full-frame DSLR paired with a bright 50mm prime for '
            'portraits, street photography and film-like colour.'
        ),
    },
    {
        'slug': 'sigma-24-70mm-art-lens',
        'legacy_slug': 'studio-16-creator',
        'name': 'Sigma 24-70mm f/2.8 Art Lens',
        'category': 'cameras',
        'price': '72990.00',
        'image_number': 5,
        'description': (
            'A constant-aperture standard zoom with a bright f/2.8 maximum '
            'aperture for weddings, events and travel.'
        ),
    },
    {
        'slug': 'yi-home-camera-1080p',
        'legacy_slug': 'commuter-chromebook',
        'name': 'YI Home Camera 1080p',
        'category': 'cameras',
        'price': '3499.00',
        'image_number': 6,
        'description': (
            'A compact indoor security camera with 1080p video, night vision and '
            'app-based monitoring.'
        ),
    },
    {
        'slug': 'polaroid-onestep-2-vf-instant-camera',
        'legacy_slug': 'pulse-over-ear-headphones',
        'name': 'Polaroid OneStep 2 VF Instant Camera',
        'category': 'cameras',
        'price': '13499.00',
        'image_number': 7,
        'description': (
            'The viewfinder edition of the OneStep 2, with simple point-and-shoot '
            'controls and instant prints.'
        ),
    },
    {
        'slug': 'sony-wh-ch700n-headphones',
        'legacy_slug': 'beat-buds-wireless',
        'name': 'Sony WH-CH700N Wireless Headphones',
        'category': 'audio',
        'price': '8990.00',
        'image_number': 8,
        'description': (
            'Wireless over-ear headphones with noise cancellation, a comfortable '
            'fit and up to 35 hours of battery life.'
        ),
    },
    {
        'slug': 'apple-imac-21-5-inch-refurbished',
        'legacy_slug': 'room-fill-speaker',
        'name': 'Apple iMac 21.5-inch (Refurbished)',
        'category': 'laptops',
        'price': '49990.00',
        'image_number': 9,
        'description': (
            'A refurbished all-in-one desktop with a 21.5-inch display, wireless '
            'keyboard and mouse.'
        ),
    },
    {
        'slug': 'apple-iphone-5s-16gb-refurbished',
        'legacy_slug': 'frame-x-mirrorless-camera',
        'name': 'Apple iPhone 5s 16GB (Refurbished)',
        'category': 'smartphones',
        'price': '3499.00',
        'image_number': 10,
        'description': (
            'A compact refurbished iPhone with Touch ID, an aluminium finish and '
            'reliable everyday performance.'
        ),
    },
    {
        'slug': 'kd-14-inch-laptop',
        'legacy_slug': 'travel-zoom-lens',
        'name': 'KD 14-inch Everyday Laptop',
        'category': 'laptops',
        'price': '21999.00',
        'image_number': 11,
        'description': (
            'A straightforward 14-inch laptop for browsing, documents, email and '
            'everyday work.'
        ),
    },
    {
        'slug': '24-inch-full-hd-monitor',
        'legacy_slug': 'action-cam-mini',
        'name': '24-inch Full HD LED Monitor',
        'category': 'laptops',
        'price': '7999.00',
        'image_number': 12,
        'description': (
            'A slim 24-inch Full HD monitor with HDMI and VGA inputs for work, '
            'study and entertainment.'
        ),
    },
    {
        'slug': 'huawei-band-4e',
        'legacy_slug': 'pulse-watch-active',
        'name': 'Huawei Band 4e',
        'category': 'wearables',
        'price': '2499.00',
        'image_number': 13,
        'description': (
            'A slim fitness band with a compact display, six workout modes and '
            'all-day activity tracking.'
        ),
    },
    {
        'slug': 'explorer-hd-camera-drone',
        'legacy_slug': 'classic-watch-band',
        'name': 'Explorer HD Camera Drone',
        'category': 'cameras',
        'price': '4999.00',
        'image_number': 14,
        'description': (
            'A beginner-friendly quadcopter with an HD camera, one-key take-off '
            'and stable hover control.'
        ),
    },
    {
        'slug': 'samsung-galaxy-s10-refurbished',
        'legacy_slug': 'night-mode-fitness-band',
        'name': 'Samsung Galaxy S10 (Refurbished)',
        'category': 'smartphones',
        'price': '15999.00',
        'image_number': 15,
        'description': (
            'A refurbished Galaxy S10 with a Dynamic AMOLED display, triple rear '
            'camera and 128GB of storage.'
        ),
    },
    {
        'slug': 'samsung-galaxy-note-5-refurbished',
        'legacy_slug': 'usb-c-travel-hub',
        'name': 'Samsung Galaxy Note 5 (Refurbished)',
        'category': 'smartphones',
        'price': '8499.00',
        'image_number': 16,
        'description': (
            'A refurbished Galaxy Note with S Pen, a large display and 32GB of '
            'storage.'
        ),
    },
    {
        'slug': 'black-slim-phone-case',
        'legacy_slug': 'wireless-charging-pad',
        'name': 'Black Slim Protective Phone Case',
        'category': 'accessories',
        'price': '799.00',
        'image_number': 17,
        'description': (
            'A slim black protective case with a matte finish and a raised lip '
            'around the camera.'
        ),
    },
    {
        'slug': 'apple-iphone-4s-8gb-refurbished',
        'legacy_slug': 'camera-tripod-kit',
        'name': 'Apple iPhone 4s 8GB (Refurbished)',
        'category': 'smartphones',
        'price': '2499.00',
        'image_number': 18,
        'description': (
            "A compact refurbished iPhone with the classic glass-and-steel design, "
            "ideal as a backup or collector's piece."
        ),
    },
    {
        'slug': 'vivo-v70-fe-5g',
        'legacy_slug': 'vivo',
        'name': 'vivo V70 FE 5G (8GB/128GB)',
        'category': 'smartphones',
        'price': '39999.00',
        'image_number': 19,
        'description': (
            'A 5G phone with a 50MP camera, a smooth AMOLED display and a '
            '7000mAh battery.'
        ),
    },
]

LEGACY_CATEGORY_NAMES = {
    'laptops': 'Laptops',
}

DEMO_DESCRIPTION_PREFIX = 'Demo catalog item.'


class Command(BaseCommand):
    help = (
        'Create or correct the repeatable demonstration catalog. Legacy demo rows '
        'are synchronized once; later manual edits are left unchanged. Demo images '
        'are copied from the bundled theme assets.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created or corrected without writing data or images.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        created_categories = 0
        updated_categories = 0
        created_products = 0
        updated_products = 0
        skipped_products = 0

        category_map = {}
        for slug, name, description in CATEGORIES:
            category = Category.objects.filter(slug=slug).first()
            if category is None:
                if dry_run:
                    self.stdout.write(f'[dry-run] Would create category: {name}')
                else:
                    category = Category.objects.create(
                        slug=slug,
                        name=name,
                        description=description,
                    )
                    created_categories += 1
                    self.stdout.write(f'Created category: {name}')
            elif (
                slug in LEGACY_CATEGORY_NAMES
                and category.name == LEGACY_CATEGORY_NAMES[slug]
            ):
                if dry_run:
                    self.stdout.write(
                        f'[dry-run] Would update category: {category.name} -> {name}'
                    )
                else:
                    category.name = name
                    category.description = description
                    category.save(update_fields=['name', 'description'])
                    updated_categories += 1
                    self.stdout.write(f'Updated category: {name}')
            category_map[slug] = category

        media_products = settings.MEDIA_ROOT / 'products'
        if not dry_run:
            media_products.mkdir(parents=True, exist_ok=True)

        for data in PRODUCTS:
            source = (
                settings.BASE_DIR
                / 'static'
                / 'theme'
                / 'img'
                / f"product-{data['image_number']}.png"
            )
            image_name = f"products/demo-{data['slug']}.png"
            destination = settings.MEDIA_ROOT / image_name

            # Recreate demo images even when the database rows already exist.
            # Ephemeral deployments start each build with an empty media folder.
            if not dry_run and source.exists() and not destination.exists():
                shutil.copyfile(source, destination)

            existing = Product.objects.filter(slug=data['slug']).first()
            found_by_legacy_slug = False
            if existing is None and data['legacy_slug']:
                existing = Product.objects.filter(slug=data['legacy_slug']).first()
                found_by_legacy_slug = existing is not None

            if existing is not None:
                has_demo_description = (existing.description or '').startswith(
                    DEMO_DESCRIPTION_PREFIX
                )
                if not (found_by_legacy_slug or has_demo_description):
                    skipped_products += 1
                    continue

                slug_conflict = (
                    existing.slug != data['slug']
                    and Product.objects.filter(slug=data['slug']).exists()
                )
                if slug_conflict:
                    skipped_products += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped {data['name']}: slug {data['slug']} is already in use."
                        )
                    )
                    continue

                if dry_run:
                    self.stdout.write(f"[dry-run] Would correct product: {data['name']}")
                    continue

                existing.slug = data['slug']
                existing.name = data['name']
                existing.category = category_map[data['category']]
                existing.price = Decimal(data['price'])
                existing.image = image_name if source.exists() else existing.image
                existing.available = True
                existing.description = data['description']
                existing.save()
                updated_products += 1
                self.stdout.write(f"Corrected product: {data['name']}")
                continue

            if dry_run:
                self.stdout.write(f"[dry-run] Would create product: {data['name']}")
                continue

            Product.objects.create(
                slug=data['slug'],
                name=data['name'],
                category=category_map[data['category']],
                price=Decimal(data['price']),
                image=image_name if source.exists() else None,
                available=True,
                description=data['description'],
            )
            created_products += 1
            self.stdout.write(f"Created product: {data['name']}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING('Dry run complete; no data or files were written.')
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Demo catalog ready: {created_categories} categories created, '
                f'{updated_categories} categories updated, '
                f'{created_products} products created, '
                f'{updated_products} products corrected, '
                f'{skipped_products} products unchanged.'
            )
        )
