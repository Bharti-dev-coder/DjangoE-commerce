import shutil
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Category, Product


CATEGORIES = [
    ('smartphones', 'Smartphones', 'Phones and mobile devices for everyday use.'),
    ('laptops', 'Laptops', 'Portable computers for work, study, and creative projects.'),
    ('audio', 'Audio', 'Headphones, speakers, and personal listening gear.'),
    ('cameras', 'Cameras', 'Cameras and lenses for photos and video.'),
    ('wearables', 'Wearables', 'Smart watches and wearable accessories.'),
    ('accessories', 'Accessories', 'Useful extras for phones, computers, and cameras.'),
]

# (slug, name, category slug, price, image number, description)
PRODUCTS = [
    ('aurora-x1-smartphone', 'Aurora X1 Smartphone', 'smartphones', '649.00', 1, 'A compact everyday phone with a bright display and dependable battery life.'),
    ('nova-pro-5g', 'Nova Pro 5G', 'smartphones', '829.00', 2, 'A larger-screen phone with fast connectivity and a versatile camera system.'),
    ('pocket-mini-phone', 'Pocket Mini Phone', 'smartphones', '429.00', 3, 'A smaller-format phone designed for simple calls, messages, and photos.'),
    ('vector-14-laptop', 'Vector 14 Laptop', 'laptops', '1,149.00', 4, 'A portable 14-inch laptop for everyday productivity and study.'),
    ('studio-16-creator', 'Studio 16 Creator', 'laptops', '1,799.00', 5, 'A larger laptop aimed at design, photo editing, and heavier multitasking.'),
    ('commuter-chromebook', 'Commuter Chromebook', 'laptops', '499.00', 6, 'A lightweight laptop for browsing, writing, and cloud-based work.'),
    ('pulse-over-ear-headphones', 'Pulse Over-Ear Headphones', 'audio', '249.00', 7, 'Comfortable over-ear headphones with a balanced everyday sound.'),
    ('beat-buds-wireless', 'Beat Buds Wireless', 'audio', '129.00', 8, 'Compact wireless earbuds with a pocket-sized charging case.'),
    ('room-fill-speaker', 'Room Fill Speaker', 'audio', '189.00', 9, 'A compact speaker for desks, kitchens, and small rooms.'),
    ('frame-x-mirrorless-camera', 'Frame X Mirrorless Camera', 'cameras', '1,299.00', 10, 'A mirrorless camera body for still photography and video.'),
    ('travel-zoom-lens', 'Travel Zoom Lens', 'cameras', '549.00', 11, 'A versatile zoom lens for travel and everyday photography.'),
    ('action-cam-mini', 'Action Cam Mini', 'cameras', '329.00', 12, 'A small action camera for outdoor clips and quick video capture.'),
    ('pulse-watch-active', 'Pulse Watch Active', 'wearables', '219.00', 13, 'A fitness-focused smart watch with an always-visible display.'),
    ('classic-watch-band', 'Classic Watch Band', 'wearables', '49.00', 14, 'A replacement band for compatible smart watches.'),
    ('night-mode-fitness-band', 'Night Mode Fitness Band', 'wearables', '89.00', 15, 'A lightweight band for step, sleep, and activity tracking.'),
    ('usb-c-travel-hub', 'USB-C Travel Hub', 'accessories', '79.00', 16, 'A compact hub for connecting displays, storage, and peripherals.'),
    ('wireless-charging-pad', 'Wireless Charging Pad', 'accessories', '39.00', 17, 'A slim charging pad for compatible phones and earbuds.'),
    ('camera-tripod-kit', 'Camera Tripod Kit', 'accessories', '69.00', 18, 'A compact tripod kit for stable photos and video.'),
]


class Command(BaseCommand):
    help = (
        'Create a repeatable demonstration catalog. Existing categories and products are '
        'left unchanged. Demo images are copied from the bundled Electro theme assets.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without writing categories, products, or images.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        created_categories = 0
        created_products = 0
        skipped_products = 0

        category_map = {}
        for slug, name, description in CATEGORIES:
            if dry_run:
                category = Category.objects.filter(slug=slug).first()
                if category is None:
                    self.stdout.write(f'[dry-run] Would create category: {name}')
                category_map[slug] = category
            else:
                category, created = Category.objects.get_or_create(
                    slug=slug,
                    defaults={'name': name, 'description': description},
                )
                category_map[slug] = category
                if created:
                    created_categories += 1
                    self.stdout.write(f'Created category: {name}')

        media_products = settings.MEDIA_ROOT / 'products'
        if not dry_run:
            media_products.mkdir(parents=True, exist_ok=True)

        for slug, name, category_slug, price, image_number, description in PRODUCTS:
            source = settings.BASE_DIR / 'static' / 'theme' / 'img' / f'product-{image_number}.png'
            image_name = f'products/demo-{slug}.png'
            destination = settings.MEDIA_ROOT / image_name

            # Recreate demo images even when the database rows already exist.
            # Ephemeral deployments start each build with an empty media folder.
            if not dry_run and source.exists() and not destination.exists():
                shutil.copyfile(source, destination)

            existing = Product.objects.filter(slug=slug).first()
            if existing is not None:
                skipped_products += 1
                continue

            if dry_run:
                self.stdout.write(f'[dry-run] Would create product: {name}')
                continue

            Product.objects.create(
                slug=slug,
                name=name,
                category=category_map[category_slug],
                price=Decimal(price.replace(',', '')),
                image=image_name if source.exists() else None,
                available=True,
                description=f'Demo catalog item. {description}',
            )
            created_products += 1
            self.stdout.write(f'Created product: {name}')

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run complete; no data or files were written.'))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Demo catalog ready: {created_categories} categor'
                f'{"y" if created_categories == 1 else "ies"} created, '
                f'{created_products} product{"s" if created_products != 1 else ""} created, '
                f'{skipped_products} existing product{"s" if skipped_products != 1 else ""} skipped.'
            )
        )
