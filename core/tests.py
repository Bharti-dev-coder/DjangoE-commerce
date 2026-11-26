import hashlib
import hmac
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

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

STRONG_PASSWORD = 'V7x!qPz2#Lm9'
LOCMEM_EMAIL = 'django.core.mail.backends.locmem.EmailBackend'


def registration_payload(**overrides):
    payload = {
        'name': 'Ada Lovelace',
        'email': 'ada@example.com',
        'phone': '5551234567',
        'password': STRONG_PASSWORD,
        'confirm_password': STRONG_PASSWORD,
        'terms': 'on',
    }
    payload.update(overrides)
    return payload


class HomepageAndTemplateTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Audio', slug='audio')
        self.product = Product.objects.create(
            name='Pulse Headphones',
            slug='pulse-headphones',
            price=Decimal('129.00'),
            category=self.category,
            available=True,
        )

    def test_homepage_renders_storefront_template_and_assets(self):
        response = self.client.get(reverse('home_page'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')
        self.assertTemplateUsed(response, 'app.html')
        self.assertContains(response, 'Featured products')
        self.assertContains(response, 'Pulse Headphones')
        self.assertContains(response, 'aria-label="View product details for Pulse Headphones"')
        self.assertContains(response, reverse('product_detail', args=[self.product.slug]))
        self.assertContains(response, '/static/theme/css/store.css')
        self.assertContains(response, '/static/theme/js/main.js')
        self.assertNotContains(response, '{% load')

    def test_homepage_empty_catalog_has_usable_empty_state(self):
        self.product.delete()
        response = self.client.get(reverse('home_page'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The shelves are being stocked')
        self.assertContains(response, 'No products are available yet')

    def test_homepage_anonymous_navigation_has_login_and_register(self):
        response = self.client.get(reverse('home_page'))
        self.assertContains(response, 'Sign in')
        self.assertContains(response, 'Create account')
        self.assertContains(response, self.category.name)

    def test_homepage_authenticated_navigation_has_account_controls(self):
        user = User.objects.create_user(username='shopper', password=STRONG_PASSWORD)
        Favorite.objects.create(user=user, product=self.product)
        self.client.force_login(user)
        response = self.client.get(reverse('home_page'))
        self.assertEqual(response.context['favorite_count'], 1)
        self.assertContains(response, 'Employee directory')
        self.assertContains(response, 'Sign out')
        self.assertContains(response, reverse('favorites'))
        self.assertContains(response, 'Open favorites')
        self.assertContains(response, 'quick-action-count')

    def test_public_pages_extend_the_storefront_base(self):
        for url_name in ['about_page', 'service_page', 'contact_page', 'shop_page']:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'app.html')
                self.assertContains(response, '/static/theme/css/store.css')


@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL)
class RegistrationEmailTests(TestCase):
    def test_successful_registration_creates_user_and_sends_welcome_email(self):
        response = self.client.post(reverse('user_register'), registration_payload())
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('user_login'))
        user = User.objects.get(email='ada@example.com')
        self.assertEqual(user.username, 'ada@example.com')
        self.assertEqual(user.first_name, 'Ada Lovelace')
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Registration Successful', mail.outbox[0].subject)
        self.assertIn('ada@example.com', mail.outbox[0].to)
        self.assertIn('Welcome to EuphoriaDJ', mail.outbox[0].body)

    def test_missing_required_fields_render_field_errors_without_email(self):
        with patch('core.views.custom_mail', return_value=True) as mocked_mail:
            response = self.client.post(reverse('user_register'), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required.')
        self.assertFalse(User.objects.filter(email='ada@example.com').exists())
        self.assertEqual(len(mail.outbox), 0)
        mocked_mail.assert_not_called()

    def test_password_mismatch_renders_confirm_password_error(self):
        response = self.client.post(
            reverse('user_register'),
            registration_payload(confirm_password='Different!234'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Passwords do not match.')
        self.assertFalse(User.objects.filter(email='ada@example.com').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_duplicate_email_renders_field_error(self):
        User.objects.create_user(username='ada@example.com', email='ada@example.com', password=STRONG_PASSWORD)
        response = self.client.post(reverse('user_register'), registration_payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'An account with this email already exists.')
        self.assertEqual(User.objects.filter(email='ada@example.com').count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_weak_password_is_rejected(self):
        response = self.client.post(
            reverse('user_register'),
            registration_payload(password='password', confirm_password='password'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'too common')
        self.assertFalse(User.objects.filter(email='ada@example.com').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_welcome_email_failure_does_not_corrupt_registration(self):
        with patch('core.views.custom_mail', return_value=False):
            response = self.client.post(reverse('user_register'), registration_payload(), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(email='ada@example.com').exists())
        self.assertContains(response, 'welcome email could not be sent')

    def test_custom_mail_is_called_only_after_account_creation(self):
        with patch('core.views.custom_mail', return_value=True) as mocked_mail:
            response = self.client.post(reverse('user_register'), registration_payload())
        self.assertEqual(response.status_code, 302)
        mocked_mail.assert_called_once()
        self.assertEqual(mocked_mail.call_args.kwargs['recipients'], ['ada@example.com'])

    def test_register_login_logout_flow(self):
        response = self.client.post(reverse('user_register'), registration_payload())
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            reverse('user_login'),
            {'username': 'ada@example.com', 'password': STRONG_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse('user_logout'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('home_page'))


class AuthRedirectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='shopper@example.com',
            email='shopper@example.com',
            password=STRONG_PASSWORD,
        )

    def test_anonymous_favorites_redirects_to_existing_login(self):
        response = self.client.get(reverse('favorites'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('user_login'), response.url)
        self.assertIn('next=/favorites/', response.url)

    def test_anonymous_cart_redirects_to_existing_login(self):
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('user_login'), response.url)
        self.assertIn('next=/cart/', response.url)

    def test_anonymous_add_action_redirects_to_login(self):
        category = Category.objects.create(name='C', slug='c')
        product = Product.objects.create(name='P', slug='p', price=Decimal('1.00'), category=category)
        response = self.client.post(reverse('add_cart', args=[product.id]), {'quantity': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('user_login'), response.url)

    def test_anonymous_favorite_action_redirects_to_login(self):
        category = Category.objects.create(name='Favorites', slug='favorites')
        product = Product.objects.create(
            name='Favorite Product',
            slug='favorite-product',
            price=Decimal('3.00'),
            category=category,
        )
        response = self.client.post(reverse('add_favorite', args=[product.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('user_login'), response.url)
        self.assertFalse(Favorite.objects.filter(product=product).exists())

    def test_anonymous_product_cards_link_to_login_for_cart_and_favorites(self):
        category = Category.objects.create(name='Cards', slug='cards')
        Product.objects.create(
            name='Card Product',
            slug='card-product',
            price=Decimal('2.00'),
            category=category,
        )
        response = self.client.get(reverse('shop_page'))
        login_link = f'{reverse("user_login")}?next={reverse("shop_page")}'
        self.assertContains(response, 'Sign in to add to cart')
        self.assertContains(response, login_link)
        self.assertContains(response, 'Sign in to save Card Product')

    def test_login_returns_to_safe_next_destination(self):
        login_url = reverse('user_login') + '?' + urlencode({'next': reverse('favorites')})
        response = self.client.get(login_url)
        self.assertContains(response, 'name="next"')
        self.assertContains(response, 'value="/favorites/"')
        response = self.client.post(
            reverse('user_login'),
            {'username': 'shopper@example.com', 'password': STRONG_PASSWORD, 'next': reverse('favorites')},
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('favorites'))

    def test_login_ignores_unsafe_external_next(self):
        response = self.client.post(
            reverse('user_login'),
            {'username': 'shopper@example.com', 'password': STRONG_PASSWORD, 'next': 'https://evil.example/steal'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('home_page'))

    def test_invalid_login_shows_error_and_does_not_authenticate(self):
        response = self.client.post(
            reverse('user_login'),
            {'username': 'shopper@example.com', 'password': 'wrong-password'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Raised issues during login')
        self.assertContains(response, 'alert alert-danger')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_successful_login_shows_message_redirects_home_with_navigation(self):
        response = self.client.post(
            reverse('user_login'),
            {'username': 'shopper@example.com', 'password': STRONG_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('home_page'))

        response = self.client.get(reverse('home_page'))
        self.assertContains(response, 'Welcome back, shopper@example.com.')
        self.assertContains(response, 'alert alert-success')
        self.assertContains(response, 'Sign out')
        self.assertContains(response, reverse('favorites'))

    def test_logout_redirects_home(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('user_logout'))
        self.assertRedirects(response, reverse('home_page'))
        self.assertNotIn('_auth_user_id', self.client.session)


class ProductCatalogTests(TestCase):
    def setUp(self):
        self.audio = Category.objects.create(name='Audio', slug='audio')
        self.laptops = Category.objects.create(name='Laptops', slug='laptops')
        self.alpha = Product.objects.create(
            name='Alpha Headphones',
            slug='alpha-headphones',
            description='Quiet noise cancelling headphones.',
            price=Decimal('20.00'),
            category=self.audio,
            available=True,
        )
        self.beta = Product.objects.create(
            name='Beta Laptop',
            slug='beta-laptop',
            description='A portable work laptop.',
            price=Decimal('10.00'),
            category=self.laptops,
            available=True,
        )

    def test_shop_lists_products_with_cards_and_actions(self):
        self.client.force_login(User.objects.create_user(username='u', password=STRONG_PASSWORD))
        response = self.client.get(reverse('shop_page'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'shop.html')
        self.assertContains(response, 'Alpha Headphones')
        self.assertContains(response, 'Beta Laptop')
        self.assertContains(response, 'Add to cart')
        self.assertContains(response, reverse('add_cart', args=[self.alpha.id]))
        self.assertContains(response, 'aria-label="View product details for Alpha Headphones"')
        self.assertContains(response, f'href="{reverse("product_detail", args=[self.alpha.slug])}"')

    def test_shop_empty_state(self):
        Product.objects.all().delete()
        response = self.client.get(reverse('shop_page'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No products are available yet')

    def test_product_detail_renders_product_and_actions(self):
        user = User.objects.create_user(username='u', password=STRONG_PASSWORD)
        self.client.force_login(user)
        response = self.client.get(reverse('product_detail', args=[self.alpha.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'product_detail.html')
        self.assertContains(response, 'Alpha Headphones')
        self.assertContains(response, '₹20.00')
        self.assertContains(response, 'Quiet noise cancelling headphones.')
        self.assertContains(response, self.audio.name)
        self.assertContains(response, 'In stock and available to order')
        self.assertContains(response, 'Continue shopping')
        self.assertContains(response, 'name="quantity"')
        self.assertContains(response, reverse('add_cart', args=[self.alpha.id]))
        self.assertContains(response, reverse('add_favorite', args=[self.alpha.id]))

    def test_product_detail_missing_or_unavailable_redirects_to_shop(self):
        missing = self.client.get(reverse('product_detail', args=['does-not-exist']))
        self.assertRedirects(missing, reverse('shop_page'))
        self.beta.available = False
        self.beta.save(update_fields=['available'])
        unavailable = self.client.get(reverse('product_detail', args=[self.beta.slug]))
        self.assertRedirects(unavailable, reverse('shop_page'))

    def test_image_and_fallback_render_on_detail_and_cards(self):
        without_image = self.client.get(reverse('product_detail', args=[self.alpha.slug]))
        self.assertContains(without_image, '/static/theme/img/product-1.png')
        self.alpha.image = 'products/alpha.png'
        self.alpha.save(update_fields=['image'])
        with_image = self.client.get(reverse('product_detail', args=[self.alpha.slug]))
        self.assertContains(with_image, '/media/products/alpha.png')

    def test_category_filter(self):
        response = self.client.get(reverse('shop_page'), {'category': self.audio.id})
        self.assertContains(response, 'Alpha Headphones')
        self.assertNotContains(response, 'Beta Laptop')

    def test_invalid_category_filter_does_not_crash(self):
        response = self.client.get(reverse('shop_page'), {'category': 'not-an-id'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alpha Headphones')

    def test_search_matches_name_and_description(self):
        name_response = self.client.get(reverse('shop_page'), {'q': 'Alpha'})
        self.assertContains(name_response, 'Alpha Headphones')
        self.assertNotContains(name_response, 'Beta Laptop')
        description_response = self.client.get(reverse('shop_page'), {'q': 'noise cancelling'})
        self.assertContains(description_response, 'Alpha Headphones')
        self.assertNotContains(description_response, 'Beta Laptop')

    def test_combined_filters(self):
        response = self.client.get(
            reverse('shop_page'),
            {'q': 'Alpha', 'category': self.audio.id, 'min_price': '15', 'max_price': '25'},
        )
        self.assertContains(response, 'Alpha Headphones')
        self.assertNotContains(response, 'Beta Laptop')

    def test_invalid_or_negative_price_filters_are_ignored(self):
        response = self.client.get(reverse('shop_page'), {'min_price': 'nope', 'max_price': '-5'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alpha Headphones')
        self.assertContains(response, 'Beta Laptop')

    def test_sorting_by_price_and_name(self):
        response = self.client.get(reverse('shop_page'), {'sort': 'price_asc'})
        self.assertEqual([p.name for p in response.context['products']], ['Beta Laptop', 'Alpha Headphones'])
        response = self.client.get(reverse('shop_page'), {'sort': 'price_desc'})
        self.assertEqual([p.name for p in response.context['products']], ['Alpha Headphones', 'Beta Laptop'])
        response = self.client.get(reverse('shop_page'), {'sort': 'name_asc'})
        self.assertEqual([p.name for p in response.context['products']], ['Alpha Headphones', 'Beta Laptop'])
        response = self.client.get(reverse('shop_page'), {'sort': 'name_desc'})
        self.assertEqual([p.name for p in response.context['products']], ['Beta Laptop', 'Alpha Headphones'])
        self.assertContains(response, 'Name Z–A')

    def test_pagination_and_query_string_preservation(self):
        for index in range(10):
            Product.objects.create(
                name=f'Widget {index}',
                slug=f'widget-{index}',
                description='Widget for pagination.',
                price=Decimal('5.00') + index,
                category=self.audio,
                available=True,
            )
        first_page = self.client.get(reverse('shop_page'), {'q': 'Widget', 'category': self.audio.id})
        self.assertEqual(len(first_page.context['products']), 8)
        self.assertTrue(first_page.context['products'].has_next())
        self.assertContains(first_page, 'page=2')
        self.assertContains(first_page, 'q=Widget')
        second_page = self.client.get(
            reverse('shop_page'),
            {'q': 'Widget', 'category': self.audio.id, 'page': '2'},
        )
        self.assertEqual(len(second_page.context['products']), 2)


class FavoritesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u1', password=STRONG_PASSWORD)
        self.other = User.objects.create_user(username='u2', password=STRONG_PASSWORD)
        self.category = Category.objects.create(name='Audio', slug='audio')
        self.product = Product.objects.create(
            name='Favorite Product',
            slug='favorite-product',
            price=Decimal('9.99'),
            category=self.category,
        )
        self.other_product = Product.objects.create(
            name='Other Product',
            slug='other-product',
            price=Decimal('4.00'),
            category=self.category,
        )
        self.client.force_login(self.user)

    def test_add_list_and_remove_favorite(self):
        response = self.client.post(reverse('add_favorite', args=[self.product.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Favorite.objects.filter(user=self.user, product=self.product).exists())
        self.assertContains(response, 'Favorite Product')
        favorite = Favorite.objects.get(user=self.user, product=self.product)
        response = self.client.post(reverse('remove_favorite', args=[favorite.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Favorite.objects.filter(user=self.user, product=self.product).exists())

    def test_duplicate_favorites_are_prevented(self):
        self.client.post(reverse('add_favorite', args=[self.product.id]))
        self.client.post(reverse('add_favorite', args=[self.product.id]))
        self.assertEqual(Favorite.objects.filter(user=self.user, product=self.product).count(), 1)

    def test_favorites_are_private_to_the_owner(self):
        Favorite.objects.create(user=self.user, product=self.product)
        Favorite.objects.create(user=self.other, product=self.other_product)
        response = self.client.get(reverse('favorites'))
        self.assertContains(response, 'Favorite Product')
        self.assertNotContains(response, 'Other Product')

    def test_owner_cannot_remove_another_users_favorite(self):
        other_favorite = Favorite.objects.create(user=self.other, product=self.other_product)
        response = self.client.post(reverse('remove_favorite', args=[other_favorite.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Favorite.objects.filter(id=other_favorite.id).exists())

    def test_favorites_empty_state(self):
        response = self.client.get(reverse('favorites'))
        self.assertContains(response, 'Your favorites list is empty')

    def test_get_does_not_change_favorites(self):
        response = self.client.get(reverse('add_favorite', args=[self.product.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Favorite.objects.filter(user=self.user, product=self.product).exists())

    def test_csrf_is_required_for_favorite_posts(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(reverse('add_favorite', args=[self.product.id]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Favorite.objects.filter(user=self.user, product=self.product).exists())


class CartTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u1', password=STRONG_PASSWORD)
        self.other = User.objects.create_user(username='u2', password=STRONG_PASSWORD)
        self.category = Category.objects.create(name='Audio', slug='audio')
        self.product = Product.objects.create(
            name='Cart Product',
            slug='cart-product',
            price=Decimal('9.99'),
            category=self.category,
        )
        self.product2 = Product.objects.create(
            name='Second Product',
            slug='second-product',
            price=Decimal('5.00'),
            category=self.category,
        )
        self.client.force_login(self.user)

    def test_add_update_remove_cart_item(self):
        response = self.client.post(reverse('add_cart', args=[self.product.id]), {'quantity': '2'}, follow=True)
        self.assertEqual(response.status_code, 200)
        item = CartItem.objects.get(user=self.user, product=self.product)
        self.assertEqual(item.quantity, 2)
        self.client.post(reverse('update_cart', args=[item.id]), {'quantity': '3'})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 3)
        self.client.post(reverse('remove_cart', args=[item.id]))
        self.assertFalse(CartItem.objects.filter(id=item.id).exists())

    def test_adding_same_product_increments_quantity(self):
        self.client.post(reverse('add_cart', args=[self.product.id]), {'quantity': '2'})
        self.client.post(reverse('add_cart', args=[self.product.id]), {'quantity': '3'})
        item = CartItem.objects.get(user=self.user, product=self.product)
        self.assertEqual(item.quantity, 5)

    def test_cart_total_is_decimal_and_accurate(self):
        CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        CartItem.objects.create(user=self.user, product=self.product2, quantity=1)
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['subtotal'], Decimal('24.98'))
        self.assertEqual(response.context['shipping_charge'], Decimal('49.00'))
        self.assertEqual(response.context['cart_total'], Decimal('73.98'))
        self.assertContains(response, '₹24.98')
        self.assertContains(response, '₹49.00')
        self.assertContains(response, '₹73.98')

    def test_free_shipping_is_applied_at_threshold(self):
        self.product.price = Decimal('1000.00')
        self.product.save(update_fields=['price'])
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['shipping_charge'], Decimal('0.00'))
        self.assertEqual(response.context['free_shipping_remaining'], Decimal('0.00'))
        self.assertEqual(response.context['cart_total'], Decimal('1000.00'))
        self.assertContains(response, 'Free')
        self.assertContains(response, '₹1,000.00')

    def test_invalid_quantities_are_rejected_without_500(self):
        for value in ['0', '-2', 'abc', '1000']:
            with self.subTest(value=value):
                response = self.client.post(reverse('add_cart', args=[self.product.id]), {'quantity': value})
                self.assertEqual(response.status_code, 302)
                self.assertFalse(CartItem.objects.filter(user=self.user, product=self.product).exists())

    def test_invalid_update_leaves_quantity_unchanged(self):
        item = CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        response = self.client.post(reverse('update_cart', args=[item.id]), {'quantity': 'abc'}, follow=True)
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)
        self.assertContains(response, 'Quantity must be a whole number')

    def test_cart_is_private_to_the_owner(self):
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        CartItem.objects.create(user=self.other, product=self.product2, quantity=4)
        response = self.client.get(reverse('cart'))
        self.assertContains(response, 'Cart Product')
        self.assertNotContains(response, 'Second Product')
        other_item = CartItem.objects.get(user=self.other)
        self.client.post(reverse('update_cart', args=[other_item.id]), {'quantity': '9'})
        other_item.refresh_from_db()
        self.assertEqual(other_item.quantity, 4)
        self.client.post(reverse('remove_cart', args=[other_item.id]))
        self.assertTrue(CartItem.objects.filter(id=other_item.id).exists())

    def test_cart_empty_state(self):
        response = self.client.get(reverse('cart'))
        self.assertContains(response, 'Your cart is empty')

    def test_unavailable_product_cannot_be_added(self):
        self.product.available = False
        self.product.save(update_fields=['available'])
        self.client.post(reverse('add_cart', args=[self.product.id]), {'quantity': '1'})
        self.assertFalse(CartItem.objects.filter(user=self.user, product=self.product).exists())

    def test_get_does_not_change_cart(self):
        response = self.client.get(reverse('add_cart', args=[self.product.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CartItem.objects.filter(user=self.user, product=self.product).exists())

    def test_csrf_is_required_for_cart_posts(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(reverse('add_cart', args=[self.product.id]), {'quantity': '1'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CartItem.objects.filter(user=self.user, product=self.product).exists())

    def test_cart_page_shows_full_product_information(self):
        self.product.description = 'Comfortable headphones with a balanced sound signature.'
        self.product.image = 'products/cart-product.png'
        self.product.save(update_fields=['description', 'image'])
        CartItem.objects.create(user=self.user, product=self.product, quantity=2)

        response = self.client.get(reverse('cart'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Comfortable headphones with a balanced sound signature.')
        self.assertContains(response, self.category.name)
        self.assertContains(response, '/media/products/cart-product.png')
        self.assertContains(response, self.product.name)
        self.assertContains(response, '₹9.99')
        self.assertContains(response, '₹19.98')
        self.assertContains(response, 'value="2"')
        self.assertContains(response, reverse('product_detail', args=[self.product.slug]))
        self.assertContains(response, reverse('update_cart', args=[CartItem.objects.get().id]))
        self.assertContains(response, reverse('remove_cart', args=[CartItem.objects.get().id]))
        self.assertContains(response, 'Continue shopping')
        self.assertEqual(response.context['total_quantity'], 2)
        self.assertEqual(response.context['cart_total'], Decimal('68.98'))

    def test_cart_page_uses_fallback_image_and_description_when_missing(self):
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        response = self.client.get(reverse('cart'))
        self.assertContains(response, '/static/theme/img/product-1.png')
        self.assertContains(response, 'No description available.')

    def test_header_cart_count_reflects_total_quantity(self):
        CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        CartItem.objects.create(user=self.user, product=self.product2, quantity=3)
        response = self.client.get(reverse('home_page'))
        self.assertContains(response, '5 in cart')

    def test_update_and_remove_require_post(self):
        item = CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        update_response = self.client.get(reverse('update_cart', args=[item.id]))
        remove_response = self.client.get(reverse('remove_cart', args=[item.id]))
        self.assertRedirects(update_response, reverse('cart'))
        self.assertRedirects(remove_response, reverse('cart'))
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)

    def test_unavailable_product_cannot_have_quantity_changed(self):
        item = CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        self.product.available = False
        self.product.save(update_fields=['available'])
        response = self.client.post(
            reverse('update_cart', args=[item.id]),
            {'quantity': '5'},
            follow=True,
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)
        self.assertContains(response, 'no longer available')


class StaticMediaTests(TestCase):
    def test_static_and_media_settings_are_configured(self):
        self.assertEqual(settings.STATIC_URL, '/static/')
        self.assertEqual(settings.MEDIA_URL, '/media/')
        self.assertIn(settings.BASE_DIR / 'static', [Path(path) for path in settings.STATICFILES_DIRS])
        self.assertEqual(settings.MEDIA_ROOT, settings.BASE_DIR / 'media')
        self.assertEqual(settings.LOGIN_URL, 'user_login')

    def test_theme_assets_are_found_by_staticfiles(self):
        for asset in [
            'theme/css/style.css',
            'theme/css/store.css',
            'theme/js/main.js',
            'theme/img/product-1.png',
            'theme/vendor/jquery-3.6.4.min.js',
            'theme/vendor/bootstrap.bundle.min.js',
            'theme/vendor/fonts/google-fonts.css',
            'theme/vendor/fontawesome/all.min.css',
        ]:
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset), asset)

    def test_page_references_local_theme_assets_not_missing_cdn(self):
        response = self.client.get(reverse('home_page'))
        self.assertContains(response, '/static/theme/css/bootstrap.min.css')
        self.assertContains(response, '/static/theme/css/store.css')
        self.assertContains(response, '/static/theme/css/ai_chat.css')
        self.assertContains(response, '/static/theme/js/main.js')
        self.assertContains(response, '/static/theme/js/ai_chat.js')

    def test_image_field_url_uses_media_url_and_file_can_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(MEDIA_ROOT=temp_dir):
                product_dir = Path(temp_dir) / 'products'
                product_dir.mkdir()
                (product_dir / 'example.png').write_bytes(b'not-a-real-image')
                product = Product.objects.create(
                    name='Image Product',
                    slug='image-product',
                    price=Decimal('1.00'),
                    image='products/example.png',
                )
                self.assertEqual(product.image.url, '/media/products/example.png')
                self.assertTrue(Path(product.image.path).exists())

    def test_templates_do_not_leak_django_tags(self):
        for url_name in ['home_page', 'shop_page', 'user_login', 'user_register']:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertNotContains(response, '{% load')
                self.assertNotContains(response, '{% static')


class EmployeePreservationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='employee-admin', password=STRONG_PASSWORD)

    def test_employee_model_still_stores_records(self):
        employee = Employee.objects.create(
            emp_name='Existing Employee',
            emp_email='existing@example.com',
            emp_mobile='5551234567',
            emp_dept='it',
            emp_dob='1990-01-01',
            emp_address='123 Existing Street',
        )
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(Employee.objects.get(pk=employee.pk).emp_name, 'Existing Employee')

    def test_employee_directory_requires_login_and_renders(self):
        Employee.objects.create(emp_name='Directory Employee', emp_email='directory@example.com', emp_dept='sales')
        anonymous = self.client.get(reverse('get_all_employees'))
        self.assertEqual(anonymous.status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(reverse('get_all_employees'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Directory Employee')

    def test_employee_create_update_and_delete_routes_still_work(self):
        response = self.client.post(
            reverse('create_employee'),
            {
                'emp_name': 'New Employee',
                'emp_email': 'new@example.com',
                'emp_mobile': '5551234567',
                'emp_dept': 'marketing',
                'emp_dob': '1995-05-05',
                'emp_address': 'New Address',
            },
        )
        self.assertEqual(response.status_code, 302)
        employee = Employee.objects.get(emp_email='new@example.com')
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('update_employee', args=[employee.id]),
            {
                'emp_name': 'Updated Employee',
                'emp_mobile': '5557654321',
                'emp_dept': 'admin',
                'emp_dob': '1995-05-05',
                'emp_address': 'Updated Address',
            },
        )
        self.assertRedirects(response, reverse('get_all_employees'))
        employee.refresh_from_db()
        self.assertEqual(employee.emp_name, 'Updated Employee')
        self.assertEqual(employee.emp_dept, 'admin')
        response = self.client.get(reverse('delete_employee', args=[employee.id]))
        self.assertRedirects(response, reverse('get_all_employees'))
        self.assertFalse(Employee.objects.filter(id=employee.id).exists())


class AdminProductPublishingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='catalog-admin',
            email='catalog-admin@example.com',
            password=STRONG_PASSWORD,
        )
        self.category = Category.objects.create(
            name='Workspace',
            slug='workspace',
            description='Desk and office products.',
        )
        self.client.force_login(self.admin)

    def admin_product_payload(self, **overrides):
        payload = {
            'name': 'Admin Created Widget',
            'slug': '',
            'category': str(self.category.id),
            'description': 'A distinctive product saved from Django Admin.',
            'price': '149.95',
            'available': 'on',
        }
        payload.update(overrides)
        return payload

    def test_admin_can_publish_product_with_blank_slug_and_it_appears_on_the_storefront(self):
        image_source = settings.BASE_DIR / 'static' / 'theme' / 'img' / 'product-1.png'

        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                upload = SimpleUploadedFile(
                    'admin-created-widget.png',
                    image_source.read_bytes(),
                    content_type='image/png',
                )
                response = self.client.post(
                    reverse('admin:core_product_add'),
                    self.admin_product_payload(image=upload),
                )

                self.assertRedirects(response, reverse('admin:core_product_changelist'))
                product = Product.objects.get(name='Admin Created Widget')
                self.assertEqual(product.slug, 'admin-created-widget')
                self.assertEqual(product.category, self.category)
                self.assertEqual(product.price, Decimal('149.95'))
                self.assertTrue(product.available)
                self.assertTrue(product.image.name.startswith('products/'))
                self.assertTrue(Path(product.image.path).exists())

                shop_response = self.client.get(reverse('shop_page'))
                self.assertEqual(shop_response.status_code, 200)
                self.assertContains(shop_response, 'Admin Created Widget')
                self.assertContains(shop_response, '₹149.95')
                self.assertContains(shop_response, 'A distinctive product saved from Django Admin.')
                self.assertContains(shop_response, self.category.name)
                self.assertContains(shop_response, product.image.url)
                self.assertContains(
                    shop_response,
                    'aria-label="View product details for Admin Created Widget"',
                )

                home_response = self.client.get(reverse('home_page'))
                self.assertContains(home_response, 'Admin Created Widget')

                detail_response = self.client.get(
                    reverse('product_detail', args=[product.slug])
                )
                self.assertContains(detail_response, 'Admin Created Widget')
                self.assertContains(detail_response, 'A distinctive product saved from Django Admin.')
                self.assertContains(detail_response, '₹149.95')
                self.assertContains(detail_response, self.category.name)
                self.assertContains(detail_response, product.image.url)
                self.assertContains(detail_response, 'Add to cart')
                self.assertContains(
                    detail_response,
                    reverse('add_cart', args=[product.id]),
                )

                filtered_response = self.client.get(
                    reverse('shop_page'),
                    {'category': self.category.id},
                )
                self.assertContains(filtered_response, 'Admin Created Widget')
                other_category = Category.objects.create(name='Elsewhere', slug='elsewhere')
                Product.objects.create(
                    name='Elsewhere Product',
                    slug='elsewhere-product',
                    description='Not in the workspace category.',
                    price=Decimal('10.00'),
                    category=other_category,
                    available=True,
                )
                filtered_response = self.client.get(
                    reverse('shop_page'),
                    {'category': other_category.id},
                )
                self.assertNotContains(filtered_response, 'Admin Created Widget')
                self.assertContains(filtered_response, 'Elsewhere Product')

    def test_customer_can_add_admin_created_product_to_cart(self):
        product = Product.objects.create(
            name='Admin Cart Product',
            slug='admin-cart-product',
            category=self.category,
            description='Cart details entered in the admin.',
            price=Decimal('12.50'),
            available=True,
        )
        customer = User.objects.create_user(username='admin-product-buyer', password=STRONG_PASSWORD)
        self.client.force_login(customer)

        response = self.client.post(reverse('add_cart', args=[product.id]), {'quantity': '2'})
        self.assertRedirects(response, reverse('cart'))
        cart_response = self.client.get(reverse('cart'))
        self.assertContains(cart_response, 'Admin Cart Product')
        self.assertContains(cart_response, 'Cart details entered in the admin.')
        self.assertContains(cart_response, '₹25.00')

    def test_unpublished_admin_product_is_hidden_from_storefront(self):
        product = Product.objects.create(
            name='Hidden Draft Product',
            slug='hidden-draft-product',
            category=self.category,
            description='Still being prepared.',
            price=Decimal('99.00'),
            available=False,
        )
        shop_response = self.client.get(reverse('shop_page'))
        self.assertNotContains(shop_response, 'Hidden Draft Product')
        detail_response = self.client.get(reverse('product_detail', args=[product.slug]))
        self.assertRedirects(detail_response, reverse('shop_page'))

    def test_admin_generates_unique_slug_when_name_already_exists(self):
        Product.objects.create(
            name='Admin Created Widget',
            slug='admin-created-widget',
            category=self.category,
            price=Decimal('1.00'),
            available=True,
        )
        response = self.client.post(
            reverse('admin:core_product_add'),
            self.admin_product_payload(price='2.00'),
        )
        self.assertRedirects(response, reverse('admin:core_product_changelist'))
        duplicate = Product.objects.get(slug='admin-created-widget-2')
        self.assertEqual(duplicate.name, 'Admin Created Widget')

    def test_admin_category_can_be_created_with_blank_slug(self):
        response = self.client.post(
            reverse('admin:core_category_add'),
            {'name': 'Home & Kitchen', 'slug': '', 'description': 'Home goods.'},
        )
        self.assertRedirects(response, reverse('admin:core_category_changelist'))
        category = Category.objects.get(name='Home & Kitchen')
        self.assertEqual(category.slug, 'home-kitchen')

    def test_admin_product_list_and_forms_load(self):
        changelist = self.client.get(reverse('admin:core_product_changelist'))
        add_form = self.client.get(reverse('admin:core_product_add'))
        self.assertEqual(changelist.status_code, 200)
        self.assertEqual(add_form.status_code, 200)
        self.assertContains(add_form, 'Leave blank to generate a unique slug')


class CategoryBrowsingTests(TestCase):
    def setUp(self):
        self.electronics = Category.objects.create(name='Electronics', slug='electronics')
        self.clothing = Category.objects.create(name='Clothing', slug='clothing')
        self.empty_category = Category.objects.create(name='Accessories', slug='accessories')
        self.phone = Product.objects.create(
            name='Everyday Phone',
            slug='everyday-phone',
            description='A pocket-sized phone.',
            price=Decimal('299.00'),
            category=self.electronics,
            available=True,
        )
        self.jacket = Product.objects.create(
            name='Weather Jacket',
            slug='weather-jacket',
            description='A light rain jacket.',
            price=Decimal('89.00'),
            category=self.clothing,
            available=True,
        )

    def test_two_categories_show_only_their_own_products(self):
        electronics = self.client.get(reverse('shop_page'), {'category': self.electronics.id})
        self.assertEqual(electronics.status_code, 200)
        self.assertContains(electronics, 'Everyday Phone')
        self.assertNotContains(electronics, 'Weather Jacket')
        self.assertContains(electronics, 'Electronics')

        clothing = self.client.get(reverse('shop_page'), {'category': self.clothing.id})
        self.assertEqual(clothing.status_code, 200)
        self.assertContains(clothing, 'Weather Jacket')
        self.assertNotContains(clothing, 'Everyday Phone')
        self.assertContains(clothing, 'Clothing')

    def test_category_links_are_dynamic_and_include_all_products(self):
        response = self.client.get(reverse('home_page'))
        self.assertContains(response, f'?category={self.electronics.id}')
        self.assertContains(response, f'?category={self.clothing.id}')
        self.assertContains(response, f'?category={self.empty_category.id}')
        self.assertContains(response, 'All products')

    def test_empty_category_shows_friendly_empty_state(self):
        response = self.client.get(reverse('shop_page'), {'category': self.empty_category.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Accessories')
        self.assertContains(response, 'No products match your filters')
        self.assertContains(response, 'Clear filters')

    def test_category_filter_combines_with_search_and_sort(self):
        response = self.client.get(
            reverse('shop_page'),
            {'category': self.electronics.id, 'q': 'Phone', 'sort': 'price_asc'},
        )
        self.assertContains(response, 'Everyday Phone')
        self.assertNotContains(response, 'Weather Jacket')
        self.assertEqual(response.context['sort'], 'price_asc')
        self.assertEqual(response.context['q'], 'Phone')

    def test_filtered_products_keep_eye_and_cart_actions(self):
        response = self.client.get(reverse('shop_page'), {'category': self.clothing.id})
        self.assertContains(response, 'aria-label="View product details for Weather Jacket"')
        self.assertContains(response, 'Sign in to add to cart')
        self.client.force_login(User.objects.create_user(username='category-buyer', password=STRONG_PASSWORD))
        response = self.client.get(reverse('shop_page'), {'category': self.clothing.id})
        self.assertContains(response, reverse('add_cart', args=[self.jacket.id]))


def checkout_payload(token, **overrides):
    payload = {
        'full_name': 'Checkout Buyer',
        'email': 'checkout@example.com',
        'phone': '9876543210',
        'saved_address': '',
        'delivery_full_name': 'Checkout Recipient',
        'delivery_phone': '9876543210',
        'house_number': '12A',
        'street': 'MG Road',
        'landmark': 'Near the park',
        'city': 'Kolkata',
        'state': 'West Bengal',
        'pin_code': '700001',
        'country': 'India',
        'save_address': 'on',
        'payment_method': 'cod',
        'checkout_token': token,
    }
    payload.update(overrides)
    return payload


class CartQuantityAndQuickAddTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='quantity-buyer', password=STRONG_PASSWORD)
        self.category = Category.objects.create(name='Quantity', slug='quantity')
        self.product = Product.objects.create(
            name='Quantity Product',
            slug='quantity-product',
            price=Decimal('100.00'),
            category=self.category,
            available=True,
        )
        self.client.force_login(self.user)

    def test_quick_add_tracks_source_and_updates_cart_count(self):
        response = self.client.post(
            reverse('add_cart', args=[self.product.id]),
            {'quantity': '1', 'source': 'quick_add'},
        )
        self.assertRedirects(response, reverse('cart'))
        item = CartItem.objects.get(user=self.user, product=self.product)
        self.assertEqual(item.source, CartItem.SOURCE_QUICK_ADD)
        home_response = self.client.get(reverse('home_page'))
        self.assertContains(home_response, '1 in cart')

    def test_product_detail_add_tracks_source_and_selected_quantity(self):
        self.client.post(
            reverse('add_cart', args=[self.product.id]),
            {'quantity': '4', 'source': 'product_detail'},
        )
        item = CartItem.objects.get(user=self.user, product=self.product)
        self.assertEqual(item.source, CartItem.SOURCE_PRODUCT_DETAIL)
        self.assertEqual(item.quantity, 4)

    def test_repeated_add_caps_quantity_at_five_without_duplicate_rows(self):
        self.client.post(reverse('add_cart', args=[self.product.id]), {'quantity': '3'})
        response = self.client.post(
            reverse('add_cart', args=[self.product.id]),
            {'quantity': '3'},
            follow=True,
        )
        item = CartItem.objects.get(user=self.user, product=self.product)
        self.assertEqual(item.quantity, 5)
        self.assertEqual(CartItem.objects.filter(user=self.user, product=self.product).count(), 1)
        self.assertContains(response, 'maximum quantity of 5')

        response = self.client.post(
            reverse('add_cart', args=[self.product.id]),
            {'quantity': '1'},
            follow=True,
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)
        self.assertContains(response, 'already at the maximum quantity of 5')

    def test_quantity_six_is_rejected_on_add_and_update(self):
        response = self.client.post(
            reverse('add_cart', args=[self.product.id]),
            {'quantity': '6'},
            follow=True,
        )
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())
        self.assertContains(response, 'between 1 and 5')

        item = CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        response = self.client.post(
            reverse('update_cart', args=[item.id]),
            {'quantity': '6'},
            follow=True,
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)
        self.assertContains(response, 'between 1 and 5')

    def test_quantity_controls_use_maximum_five(self):
        item = CartItem.objects.create(user=self.user, product=self.product, quantity=5)
        cart_response = self.client.get(reverse('cart'))
        detail_response = self.client.get(reverse('product_detail', args=[self.product.slug]))
        self.assertContains(cart_response, 'max="5"')
        self.assertContains(cart_response, reverse('update_cart', args=[item.id]))
        self.assertContains(detail_response, 'max="5"')
        self.assertNotContains(cart_response, 'max="999"')
        self.assertNotContains(detail_response, 'max="999"')

    def test_frontend_price_values_are_not_used_for_cart_subtotals(self):
        self.client.post(
            reverse('add_cart', args=[self.product.id]),
            {'quantity': '1', 'price': '0.01', 'subtotal': '0.01'},
        )
        response = self.client.get(reverse('cart'))
        item = CartItem.objects.get(user=self.user, product=self.product)
        self.assertEqual(item.product.price, Decimal('100.00'))
        self.assertEqual(response.context['subtotal'], Decimal('100.00'))
        self.assertContains(response, '₹100.00')

    def test_product_card_uses_quick_add_source(self):
        response = self.client.get(reverse('shop_page'))
        self.assertContains(response, 'name="source" value="quick_add"')


class CouponTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='coupon-buyer', password=STRONG_PASSWORD)
        self.category = Category.objects.create(name='Coupons', slug='coupons')
        self.product = Product.objects.create(
            name='Coupon Product',
            slug='coupon-product',
            price=Decimal('1000.00'),
            category=self.category,
            available=True,
        )
        self.client.force_login(self.user)
        self.item = CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        self.coupon = Coupon.objects.get(code='Bharti123')

    def test_seeded_coupon_applies_percentage_discount_and_case_insensitively(self):
        response = self.client.post(
            reverse('apply_coupon'),
            {'coupon_code': 'bharti123'},
            follow=True,
        )
        self.assertContains(response, 'Coupon Bharti123 applied')
        self.assertEqual(self.client.session['storefront_coupon_code'], 'Bharti123')

        cart_response = self.client.get(reverse('cart'))
        self.assertEqual(cart_response.context['coupon'].code, 'Bharti123')
        self.assertEqual(cart_response.context['subtotal'], Decimal('2000.00'))
        self.assertEqual(cart_response.context['coupon_discount'], Decimal('200.00'))
        self.assertEqual(cart_response.context['cart_total'], Decimal('1800.00'))
        self.assertContains(cart_response, 'Bharti123')
        self.assertContains(cart_response, '−₹200.00')

    def test_invalid_coupon_is_rejected_without_session_state(self):
        response = self.client.post(
            reverse('apply_coupon'),
            {'coupon_code': 'DOES-NOT-EXIST'},
            follow=True,
        )
        self.assertContains(response, 'This coupon code is not valid.')
        self.assertNotIn('storefront_coupon_code', self.client.session)
        self.assertIsNone(self.client.get(reverse('cart')).context['coupon'])

    def test_expired_coupon_is_rejected(self):
        Coupon.objects.create(
            code='EXPIRED10',
            discount_type=Coupon.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('10.00'),
            valid_from=timezone.now() - timedelta(days=10),
            expiry_date=timezone.now() - timedelta(days=1),
            is_active=True,
        )
        response = self.client.post(
            reverse('apply_coupon'),
            {'coupon_code': 'EXPIRED10'},
            follow=True,
        )
        self.assertContains(response, 'This coupon has expired.')

    def test_inactive_coupon_is_rejected(self):
        Coupon.objects.create(
            code='INACTIVE10',
            discount_type=Coupon.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('10.00'),
            valid_from=timezone.now() - timedelta(days=1),
            expiry_date=timezone.now() + timedelta(days=1),
            is_active=False,
        )
        response = self.client.post(
            reverse('apply_coupon'),
            {'coupon_code': 'INACTIVE10'},
            follow=True,
        )
        self.assertContains(response, 'This coupon is not active.')

    def test_minimum_order_amount_is_enforced(self):
        Coupon.objects.create(
            code='BIGORDER',
            discount_type=Coupon.DISCOUNT_FIXED,
            discount_value=Decimal('100.00'),
            minimum_order_amount=Decimal('5000.00'),
            valid_from=timezone.now() - timedelta(days=1),
            expiry_date=timezone.now() + timedelta(days=1),
            is_active=True,
        )
        response = self.client.post(
            reverse('apply_coupon'),
            {'coupon_code': 'BIGORDER'},
            follow=True,
        )
        self.assertContains(response, 'requires a minimum order')

    def test_percentage_coupon_honors_maximum_discount(self):
        Coupon.objects.create(
            code='CAP100',
            discount_type=Coupon.DISCOUNT_PERCENTAGE,
            discount_value=Decimal('50.00'),
            maximum_discount=Decimal('100.00'),
            valid_from=timezone.now() - timedelta(days=1),
            expiry_date=timezone.now() + timedelta(days=1),
            is_active=True,
        )
        self.client.post(reverse('apply_coupon'), {'coupon_code': 'CAP100'})
        cart_response = self.client.get(reverse('cart'))
        self.assertEqual(cart_response.context['coupon_discount'], Decimal('100.00'))
        self.assertEqual(cart_response.context['cart_total'], Decimal('1900.00'))

    def test_remove_coupon_recalculates_total(self):
        self.client.post(reverse('apply_coupon'), {'coupon_code': 'Bharti123'})
        response = self.client.post(reverse('remove_coupon'), follow=True)
        self.assertContains(response, 'Coupon removed.')
        cart_response = self.client.get(reverse('cart'))
        self.assertIsNone(cart_response.context['coupon'])
        self.assertEqual(cart_response.context['coupon_discount'], Decimal('0.00'))
        self.assertEqual(cart_response.context['cart_total'], Decimal('2000.00'))

    def test_coupon_requires_a_non_empty_cart(self):
        self.item.delete()
        response = self.client.post(
            reverse('apply_coupon'),
            {'coupon_code': 'Bharti123'},
            follow=True,
        )
        self.assertContains(response, 'Add a product to your cart before applying a coupon.')

    def test_coupon_is_removed_when_cart_stops_meeting_minimum(self):
        coupon = Coupon.objects.create(
            code='MIN1500',
            discount_type=Coupon.DISCOUNT_FIXED,
            discount_value=Decimal('100.00'),
            minimum_order_amount=Decimal('1500.00'),
            valid_from=timezone.now() - timedelta(days=1),
            expiry_date=timezone.now() + timedelta(days=1),
            is_active=True,
        )
        self.client.post(reverse('apply_coupon'), {'coupon_code': coupon.code})
        self.client.post(reverse('update_cart', args=[self.item.id]), {'quantity': '1'})
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.context['coupon'], None)
        self.assertEqual(response.context['coupon_discount'], Decimal('0.00'))
        self.assertNotIn('storefront_coupon_code', self.client.session)

    def test_coupon_usage_limit_is_enforced(self):
        Coupon.objects.filter(pk=self.coupon.pk).update(usage_limit=1, usage_count=1)
        response = self.client.post(
            reverse('apply_coupon'),
            {'coupon_code': 'Bharti123'},
            follow=True,
        )
        self.assertContains(response, 'usage limit')

    def test_coupon_posts_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(reverse('apply_coupon'), {'coupon_code': 'Bharti123'})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('storefront_coupon_code', csrf_client.session)


class CheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='checkout-user',
            email='checkout-user@example.com',
            password=STRONG_PASSWORD,
            first_name='Checkout User',
        )
        self.other = User.objects.create_user(username='other-user', password=STRONG_PASSWORD)
        self.category = Category.objects.create(name='Checkout', slug='checkout')
        self.product = Product.objects.create(
            name='Checkout Product',
            slug='checkout-product',
            price=Decimal('600.00'),
            category=self.category,
            available=True,
        )
        self.product2 = Product.objects.create(
            name='Second Checkout Product',
            slug='second-checkout-product',
            price=Decimal('500.00'),
            category=self.category,
            available=True,
        )
        CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        CartItem.objects.create(user=self.user, product=self.product2, quantity=1)
        self.client.force_login(self.user)
        self.coupon = Coupon.objects.get(code='Bharti123')

    def get_checkout_token(self):
        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 200)
        return self.client.session['checkout_token']

    def test_checkout_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('user_login'), response.url)

    def test_checkout_page_shows_review_and_prefills_customer(self):
        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Checkout Product')
        self.assertContains(response, 'Second Checkout Product')
        self.assertContains(response, '₹1,700.00')
        self.assertContains(response, 'checkout-user@example.com')
        self.assertContains(response, 'Cash on Delivery')
        self.assertContains(response, 'Online payment (Razorpay)')
        self.assertContains(response, 'checkout_token')

    def test_cod_checkout_creates_order_items_and_default_pending_statuses(self):
        self.client.post(reverse('apply_coupon'), {'coupon_code': 'Bharti123'})
        token = self.get_checkout_token()
        response = self.client.post(
            reverse('checkout'),
            checkout_payload(token),
        )

        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order_success', args=[order.order_number]))
        self.assertEqual(order.subtotal, Decimal('1700.00'))
        self.assertEqual(order.coupon_discount, Decimal('170.00'))
        self.assertEqual(order.shipping_charge, Decimal('0.00'))
        self.assertEqual(order.tax_amount, Decimal('0.00'))
        self.assertEqual(order.final_total, Decimal('1530.00'))
        self.assertEqual(order.coupon_code, 'Bharti123')
        self.assertEqual(order.payment_method, Order.PAYMENT_METHOD_COD)
        self.assertEqual(order.payment_status, Order.PAYMENT_PENDING)
        self.assertEqual(order.order_status, Order.ORDER_PENDING)
        self.assertEqual(order.customer_email, 'checkout@example.com')
        self.assertEqual(order.shipping_pin_code, '700001')
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.items.get(product=self.product).quantity, 2)
        self.assertEqual(order.items.get(product=self.product).subtotal, Decimal('1200.00'))
        self.assertEqual(order.items.get(product=self.product2).quantity, 1)
        self.assertEqual(order.items.get(product=self.product2).subtotal, Decimal('500.00'))
        self.assertEqual(order.total_quantity, 3)
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())
        self.assertNotIn('storefront_coupon_code', self.client.session)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.usage_count, 1)

        address = Address.objects.get(user=self.user)
        self.assertEqual(order.address, address)
        self.assertEqual(address.full_name, 'Checkout Recipient')
        self.assertEqual(address.city, 'Kolkata')
        self.assertTrue(address.is_default)

        detail_response = self.client.get(response.url)
        self.assertContains(detail_response, 'Order successful')
        self.assertContains(detail_response, 'Order placed successfully')
        self.assertContains(detail_response, order.order_number)
        self.assertContains(detail_response, 'Checkout Product')
        self.assertContains(detail_response, 'Cash on Delivery')
        self.assertContains(detail_response, '₹1,530.00')

    def test_checkout_uses_server_prices_and_totals(self):
        token = self.get_checkout_token()
        response = self.client.post(
            reverse('checkout'),
            checkout_payload(
                token,
                price='0.01',
                subtotal='0.01',
                coupon_discount='9999.00',
                final_total='0.01',
            ),
        )
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order_success', args=[order.order_number]))
        self.assertEqual(order.subtotal, Decimal('1700.00'))
        self.assertEqual(order.final_total, Decimal('1700.00'))
        self.assertEqual(order.payment_status, Order.PAYMENT_PENDING)

    def test_saved_address_can_be_reused_without_duplicate_address(self):
        address = Address.objects.create(
            user=self.user,
            full_name='Saved Recipient',
            phone='9123456789',
            house_number='99',
            street='Saved Street',
            city='Delhi',
            state='Delhi',
            pin_code='110001',
            country='India',
            is_default=True,
        )
        token = self.get_checkout_token()
        response = self.client.post(
            reverse('checkout'),
            checkout_payload(
                token,
                saved_address=str(address.pk),
                delivery_full_name='',
                delivery_phone='',
                house_number='',
                street='',
                landmark='',
                city='',
                state='',
                pin_code='',
                country='',
            ),
        )
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order_success', args=[order.order_number]))
        self.assertEqual(order.address, address)
        self.assertEqual(order.shipping_full_name, 'Saved Recipient')
        self.assertEqual(order.shipping_city, 'Delhi')
        self.assertEqual(Address.objects.filter(user=self.user).count(), 1)

    def test_new_address_is_saved_and_available_for_next_checkout(self):
        token = self.get_checkout_token()
        self.client.post(reverse('checkout'), checkout_payload(token))
        address = Address.objects.get(user=self.user)
        self.assertEqual(address.house_number, '12A')

        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        response = self.client.get(reverse('checkout'))
        self.assertContains(response, '12A')
        self.assertContains(response, 'MG Road')
        self.assertContains(response, f'value="{address.pk}"')

    def test_checkout_rejects_invalid_token_and_keeps_cart(self):
        response = self.client.post(
            reverse('checkout'),
            checkout_payload('not-the-token'),
            follow=True,
        )
        self.assertContains(response, 'expired or was submitted twice')
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 2)

    def test_checkout_rejects_reusing_a_consumed_token(self):
        token = self.get_checkout_token()
        payload = checkout_payload(token)
        self.client.post(reverse('checkout'), payload)
        self.assertEqual(Order.objects.filter(user=self.user).count(), 1)

        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        self.client.post(reverse('checkout'), payload)
        self.assertEqual(Order.objects.filter(user=self.user).count(), 1)

    def test_checkout_with_empty_cart_redirects_to_cart(self):
        CartItem.objects.filter(user=self.user).delete()
        response = self.client.get(reverse('checkout'))
        self.assertRedirects(response, reverse('cart'))

    def test_checkout_requires_a_delivery_address_when_no_saved_address(self):
        token = self.get_checkout_token()
        response = self.client.post(
            reverse('checkout'),
            checkout_payload(
                token,
                delivery_full_name='',
                house_number='',
                street='',
                city='',
                state='',
                pin_code='',
                country='',
                save_address='',
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter the house or flat number.')
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 2)

    def test_invalid_coupon_at_checkout_is_not_silently_dropped(self):
        self.client.post(reverse('apply_coupon'), {'coupon_code': 'Bharti123'})
        token = self.get_checkout_token()
        Coupon.objects.filter(pk=self.coupon.pk).update(
            expiry_date=timezone.now() - timedelta(days=1)
        )
        response = self.client.post(
            reverse('checkout'),
            checkout_payload(token),
            follow=True,
        )
        self.assertContains(response, 'Coupon removed')
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.assertEqual(CartItem.objects.filter(user=self.user).count(), 2)

    def test_order_items_keep_snapshots_after_product_deletion(self):
        token = self.get_checkout_token()
        self.client.post(reverse('checkout'), checkout_payload(token))
        self.product.delete()
        item = OrderItem.objects.get(order__user=self.user, product_name='Checkout Product')
        self.assertIsNone(item.product)
        self.assertEqual(item.unit_price, Decimal('600.00'))
        self.assertEqual(item.subtotal, Decimal('1200.00'))

    def test_checkout_posts_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(reverse('checkout'), checkout_payload('anything'))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Order.objects.filter(user=self.user).exists())


class OrderHistorySecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='order-owner', password=STRONG_PASSWORD)
        self.other = User.objects.create_user(username='order-other', password=STRONG_PASSWORD)
        self.category = Category.objects.create(name='History', slug='history')
        self.product = Product.objects.create(
            name='History Product',
            slug='history-product',
            price=Decimal('250.00'),
            category=self.category,
            available=True,
        )
        self.client.force_login(self.user)
        self.order = self.make_order(self.user, 'EUP-OWN-001')
        self.other_order = self.make_order(self.other, 'EUP-OTHER-001')

    def make_order(self, user, number, payment_method=Order.PAYMENT_METHOD_COD):
        order = Order.objects.create(
            order_number=number,
            user=user,
            customer_name='Customer ' + user.username,
            customer_email=user.username + '@example.com',
            customer_phone='9999999999',
            shipping_full_name='Recipient ' + user.username,
            shipping_phone='9999999999',
            shipping_house_number='1',
            shipping_street='Order Street',
            shipping_city='Mumbai',
            shipping_state='Maharashtra',
            shipping_pin_code='400001',
            shipping_country='India',
            subtotal=Decimal('250.00'),
            final_total=Decimal('250.00'),
            payment_method=payment_method,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name='History Product',
            unit_price=Decimal('250.00'),
            quantity=1,
            subtotal=Decimal('250.00'),
        )
        return order

    def test_orders_require_login(self):
        self.client.logout()
        response = self.client.get(reverse('order_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('user_login'), response.url)

    def test_order_list_only_shows_the_signed_in_users_orders(self):
        response = self.client.get(reverse('order_list'))
        self.assertContains(response, self.order.order_number)
        self.assertNotContains(response, self.other_order.order_number)

    def test_order_detail_is_private_to_the_owner(self):
        own_response = self.client.get(
            reverse('order_detail', args=[self.order.order_number])
        )
        self.assertEqual(own_response.status_code, 200)
        self.assertContains(own_response, self.order.order_number)
        self.assertContains(own_response, 'History Product')
        self.assertContains(own_response, '₹250.00')
        self.assertContains(own_response, 'EuphoriaDJ')

        other_response = self.client.get(
            reverse('order_detail', args=[self.other_order.order_number])
        )
        self.assertEqual(other_response.status_code, 404)

    def test_order_success_page_is_private_to_the_owner(self):
        own_response = self.client.get(
            reverse('order_success', args=[self.order.order_number])
        )
        self.assertEqual(own_response.status_code, 200)
        self.assertContains(own_response, 'Order successful')
        self.assertContains(own_response, 'Order placed successfully')
        self.assertContains(own_response, self.order.order_number)

        other_response = self.client.get(
            reverse('order_success', args=[self.other_order.order_number])
        )
        self.assertEqual(other_response.status_code, 404)

    def test_order_payment_pages_are_private_to_the_owner(self):
        other_razorpay_order = self.make_order(
            self.other,
            'EUP-OTHER-PAY',
            payment_method=Order.PAYMENT_METHOD_RAZORPAY,
        )
        other_razorpay_order.razorpay_order_id = 'order_other'
        other_razorpay_order.save(update_fields=['razorpay_order_id'])
        payment_response = self.client.get(
            reverse('order_payment', args=[other_razorpay_order.order_number])
        )
        verify_response = self.client.post(
            reverse('verify_payment', args=[other_razorpay_order.order_number]),
            {
                'razorpay_order_id': 'order_other',
                'razorpay_payment_id': 'pay_other',
                'razorpay_signature': 'signature',
            },
        )
        self.assertEqual(payment_response.status_code, 404)
        self.assertEqual(verify_response.status_code, 404)


@override_settings(
    RAZORPAY_KEY_ID='rzp_test_public_key',
    RAZORPAY_KEY_SECRET='test_secret_key',
)
class RazorpayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='razorpay-user',
            email='razorpay-user@example.com',
            password=STRONG_PASSWORD,
        )
        self.category = Category.objects.create(name='Payments', slug='payments')
        self.product = Product.objects.create(
            name='Payment Product',
            slug='payment-product',
            price=Decimal('1000.00'),
            category=self.category,
            available=True,
        )
        self.client.force_login(self.user)

    def make_pending_order(self, *, total=Decimal('1000.00'), coupon=None):
        order = Order.objects.create(
            user=self.user,
            customer_name='Razorpay Buyer',
            customer_email='razorpay@example.com',
            customer_phone='9876543210',
            shipping_full_name='Razorpay Buyer',
            shipping_phone='9876543210',
            shipping_house_number='5',
            shipping_street='Payment Street',
            shipping_city='Bengaluru',
            shipping_state='Karnataka',
            shipping_pin_code='560001',
            shipping_country='India',
            subtotal=total,
            coupon=coupon,
            coupon_code=coupon.code if coupon else '',
            final_total=total,
            payment_method=Order.PAYMENT_METHOD_RAZORPAY,
            razorpay_order_id='order_razorpay_1',
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            unit_price=total,
            quantity=1,
            subtotal=total,
        )
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        return order

    def valid_payment(self, order, **overrides):
        payment = {
            'id': 'pay_razorpay_1',
            'order_id': order.razorpay_order_id,
            'status': 'captured',
            'currency': 'INR',
            'amount': int(order.final_total * 100),
        }
        payment.update(overrides)
        return payment

    def test_create_razorpay_order_uses_inr_paise_and_records_attempt(self):
        order = self.make_pending_order()
        order.razorpay_order_id = ''
        order.save(update_fields=['razorpay_order_id'])
        with patch('core.payments._razorpay_request') as request_mock:
            request_mock.return_value = {
                'id': 'order_created_1',
                'amount': 100000,
                'currency': 'INR',
            }
            from core.payments import create_razorpay_order

            response = create_razorpay_order(order)

        self.assertEqual(response['id'], 'order_created_1')
        args, kwargs = request_mock.call_args
        self.assertEqual(args[0], 'POST')
        self.assertEqual(args[1], '/orders')
        payload = args[2]
        self.assertEqual(payload['amount'], 100000)
        self.assertEqual(payload['currency'], 'INR')
        self.assertEqual(payload['receipt'], order.order_number)
        order.refresh_from_db()
        self.assertEqual(order.razorpay_order_id, 'order_created_1')
        record = order.payment_records.get()
        self.assertEqual(record.status, PaymentRecord.STATUS_CREATED)
        self.assertEqual(record.razorpay_order_id, 'order_created_1')
        self.assertEqual(record.amount, Decimal('1000.00'))

    def test_signature_verification_uses_hmac_sha256(self):
        from core.payments import verify_signature

        order_id = 'order_signature_1'
        payment_id = 'pay_signature_1'
        signature = hmac.new(
            b'test_secret_key',
            f'{order_id}|{payment_id}'.encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertTrue(verify_signature(order_id, payment_id, signature))
        self.assertFalse(verify_signature(order_id, payment_id, 'wrong-signature'))
        self.assertFalse(verify_signature(order_id, '', signature))

    def test_razorpay_checkout_creates_pending_order_and_keeps_cart_until_paid(self):
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        self.client.post(reverse('apply_coupon'), {'coupon_code': 'Bharti123'})
        self.client.get(reverse('checkout'))
        token = self.client.session['checkout_token']

        def fake_create_razorpay_order(order):
            order.razorpay_order_id = 'order_checkout_1'
            order.save(update_fields=['razorpay_order_id', 'updated_at'])
            return {'id': 'order_checkout_1', 'amount': 90000, 'currency': 'INR'}

        with patch('core.views.create_razorpay_order', side_effect=fake_create_razorpay_order):
            response = self.client.post(
                reverse('checkout'),
                checkout_payload(token, payment_method='razorpay'),
            )

        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse('order_payment', args=[order.order_number]))
        self.assertEqual(order.payment_method, Order.PAYMENT_METHOD_RAZORPAY)
        self.assertEqual(order.payment_status, Order.PAYMENT_PENDING)
        self.assertEqual(order.razorpay_order_id, 'order_checkout_1')
        self.assertEqual(order.final_total, Decimal('900.00'))
        self.assertTrue(CartItem.objects.filter(user=self.user).exists())
        coupon = Coupon.objects.get(code='Bharti123')
        self.assertEqual(coupon.usage_count, 0)

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_razorpay_checkout_is_blocked_without_credentials(self):
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        self.client.get(reverse('checkout'))
        token = self.client.session['checkout_token']
        response = self.client.post(
            reverse('checkout'),
            checkout_payload(token, payment_method='razorpay'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Online payment is not configured yet.')
        self.assertFalse(Order.objects.filter(user=self.user).exists())
        self.assertTrue(CartItem.objects.filter(user=self.user).exists())

    def test_payment_page_exposes_only_the_public_key(self):
        order = self.make_pending_order()
        response = self.client.get(reverse('order_payment', args=[order.order_number]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rzp_test_public_key')
        self.assertNotContains(response, 'test_secret_key')
        self.assertContains(response, 'checkout.razorpay.com/v1/checkout.js')
        self.assertContains(response, 'order_razorpay_1')
        self.assertContains(response, '₹1,000.00')

    @override_settings(RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='')
    def test_payment_page_requires_razorpay_configuration(self):
        order = self.make_pending_order()
        response = self.client.get(
            reverse('order_payment', args=[order.order_number]),
            follow=True,
        )
        self.assertContains(response, 'Online payment is not configured')
        self.assertRedirects(
            response,
            reverse('order_detail', args=[order.order_number]),
        )

    def test_unpaid_order_success_redirects_to_payment_page(self):
        order = self.make_pending_order()
        response = self.client.get(
            reverse('order_success', args=[order.order_number])
        )
        self.assertRedirects(
            response,
            reverse('order_payment', args=[order.order_number]),
        )

    def test_verified_payment_marks_order_paid_and_clears_ordered_cart_lines(self):
        coupon = Coupon.objects.get(code='Bharti123')
        order = self.make_pending_order(coupon=coupon)
        payment = self.valid_payment(order)
        with patch('core.views.verify_signature', return_value=True), patch(
            'core.views.fetch_payment', return_value=payment
        ):
            response = self.client.post(
                reverse('verify_payment', args=[order.order_number]),
                {
                    'razorpay_order_id': order.razorpay_order_id,
                    'razorpay_payment_id': payment['id'],
                    'razorpay_signature': 'verified-signature',
                    'status': 'success',
                },
            )

        order.refresh_from_db()
        self.assertRedirects(response, reverse('order_success', args=[order.order_number]))
        self.assertEqual(order.payment_status, Order.PAYMENT_SUCCESS)
        self.assertEqual(order.order_status, Order.ORDER_CONFIRMED)
        self.assertEqual(order.transaction_id, payment['id'])
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())
        coupon.refresh_from_db()
        self.assertEqual(coupon.usage_count, 1)
        record = order.payment_records.get(status=PaymentRecord.STATUS_SUCCESS)
        self.assertTrue(record.signature_verified)
        self.assertEqual(record.razorpay_payment_id, payment['id'])

        success_response = self.client.get(response.url)
        self.assertEqual(success_response.status_code, 200)
        self.assertContains(success_response, 'Order successful')
        self.assertContains(success_response, 'Payment successful and verified')
        self.assertContains(success_response, order.order_number)
        self.assertContains(success_response, 'Payment Product')
        self.assertContains(success_response, '₹1,000.00')

    def test_duplicate_verified_callback_is_idempotent(self):
        coupon = Coupon.objects.get(code='Bharti123')
        order = self.make_pending_order(coupon=coupon)
        payment = self.valid_payment(order)
        payload = {
            'razorpay_order_id': order.razorpay_order_id,
            'razorpay_payment_id': payment['id'],
            'razorpay_signature': 'verified-signature',
        }
        with patch('core.views.verify_signature', return_value=True), patch(
            'core.views.fetch_payment', return_value=payment
        ):
            first_response = self.client.post(
                reverse('verify_payment', args=[order.order_number]),
                payload,
            )
            second_response = self.client.post(
                reverse('verify_payment', args=[order.order_number]),
                payload,
            )

        order.refresh_from_db()
        coupon.refresh_from_db()
        self.assertRedirects(
            first_response,
            reverse('order_success', args=[order.order_number]),
        )
        self.assertRedirects(
            second_response,
            reverse('order_success', args=[order.order_number]),
        )
        self.assertEqual(order.payment_status, Order.PAYMENT_SUCCESS)
        self.assertEqual(order.transaction_id, payment['id'])
        self.assertEqual(coupon.usage_count, 1)
        self.assertEqual(
            order.payment_records.filter(status=PaymentRecord.STATUS_SUCCESS).count(),
            1,
        )

    def test_invalid_signature_never_marks_order_paid(self):
        coupon = Coupon.objects.get(code='Bharti123')
        order = self.make_pending_order(coupon=coupon)
        with patch('core.views.verify_signature', return_value=False):
            response = self.client.post(
                reverse('verify_payment', args=[order.order_number]),
                {
                    'razorpay_order_id': order.razorpay_order_id,
                    'razorpay_payment_id': 'pay_forged',
                    'razorpay_signature': 'forged',
                    'status': 'success',
                },
            )

        order.refresh_from_db()
        self.assertRedirects(response, reverse('order_payment', args=[order.order_number]))
        self.assertEqual(order.payment_status, Order.PAYMENT_FAILED)
        self.assertEqual(order.transaction_id, '')
        self.assertTrue(CartItem.objects.filter(user=self.user).exists())
        coupon.refresh_from_db()
        self.assertEqual(coupon.usage_count, 0)
        record = order.payment_records.get(status=PaymentRecord.STATUS_FAILED)
        self.assertFalse(record.signature_verified)

    def test_gateway_amount_mismatch_never_marks_order_paid(self):
        order = self.make_pending_order()
        payment = self.valid_payment(order, amount=1)
        with patch('core.views.verify_signature', return_value=True), patch(
            'core.views.fetch_payment', return_value=payment
        ):
            response = self.client.post(
                reverse('verify_payment', args=[order.order_number]),
                {
                    'razorpay_order_id': order.razorpay_order_id,
                    'razorpay_payment_id': payment['id'],
                    'razorpay_signature': 'verified-signature',
                },
            )

        order.refresh_from_db()
        self.assertRedirects(response, reverse('order_payment', args=[order.order_number]))
        self.assertEqual(order.payment_status, Order.PAYMENT_FAILED)
        self.assertEqual(order.transaction_id, '')
        self.assertTrue(CartItem.objects.filter(user=self.user).exists())

    def test_incomplete_callback_never_marks_order_paid(self):
        order = self.make_pending_order()
        response = self.client.post(
            reverse('verify_payment', args=[order.order_number]),
            {},
            follow=True,
        )
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PAYMENT_FAILED)
        self.assertContains(response, 'response was incomplete')
        self.assertFalse(
            order.payment_records.filter(status=PaymentRecord.STATUS_SUCCESS).exists()
        )

    def test_payment_verification_requires_csrf(self):
        order = self.make_pending_order()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            reverse('verify_payment', args=[order.order_number]),
            {
                'razorpay_order_id': order.razorpay_order_id,
                'razorpay_payment_id': 'pay_csrf',
                'razorpay_signature': 'signature',
            },
        )
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PAYMENT_PENDING)


class AdminStoreManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='store-admin',
            email='store-admin@example.com',
            password=STRONG_PASSWORD,
        )
        self.customer = User.objects.create_user(
            username='admin-customer',
            email='admin-customer@example.com',
            password=STRONG_PASSWORD,
        )
        self.category = Category.objects.create(name='Admin Store', slug='admin-store')
        self.product = Product.objects.create(
            name='Admin Store Product',
            slug='admin-store-product',
            price=Decimal('300.00'),
            category=self.category,
            available=True,
        )
        self.cart_item = CartItem.objects.create(
            user=self.customer,
            product=self.product,
            quantity=2,
            source=CartItem.SOURCE_QUICK_ADD,
        )
        self.favorite = Favorite.objects.create(user=self.customer, product=self.product)
        self.address = Address.objects.create(
            user=self.customer,
            full_name='Admin Address Recipient',
            phone='9876543210',
            house_number='7',
            street='Admin Street',
            city='Pune',
            state='Maharashtra',
            pin_code='411001',
            country='India',
            is_default=True,
        )
        self.order = Order.objects.create(
            user=self.customer,
            customer_name='Admin Order Customer',
            customer_email='admin-customer@example.com',
            customer_phone='9876543210',
            address=self.address,
            shipping_full_name=self.address.full_name,
            shipping_phone=self.address.phone,
            shipping_house_number=self.address.house_number,
            shipping_street=self.address.street,
            shipping_city=self.address.city,
            shipping_state=self.address.state,
            shipping_pin_code=self.address.pin_code,
            shipping_country=self.address.country,
            subtotal=Decimal('600.00'),
            final_total=Decimal('600.00'),
            payment_method=Order.PAYMENT_METHOD_COD,
            payment_status=Order.PAYMENT_PENDING,
            order_status=Order.ORDER_PENDING,
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            unit_price=Decimal('300.00'),
            quantity=2,
            subtotal=Decimal('600.00'),
        )
        self.payment_record = PaymentRecord.objects.create(
            order=self.order,
            amount=Decimal('600.00'),
            currency='INR',
            status=PaymentRecord.STATUS_CREATED,
        )
        self.coupon = Coupon.objects.get(code='Bharti123')
        self.client.force_login(self.admin)

    def test_new_admin_changelists_load(self):
        names = [
            'core_coupon_changelist',
            'core_address_changelist',
            'core_storeprofile_changelist',
            'core_order_changelist',
            'core_orderitem_changelist',
            'core_paymentrecord_changelist',
            'core_cartitem_changelist',
            'core_favorite_changelist',
        ]
        for name in names:
            with self.subTest(name=name):
                response = self.client.get(reverse('admin:' + name))
                self.assertEqual(response.status_code, 200)

    def test_order_admin_shows_customer_address_and_line_items(self):
        response = self.client.get(
            reverse('admin:core_order_change', args=[self.order.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'Admin Order Customer')
        self.assertContains(response, 'Admin Store Product')
        self.assertContains(response, 'Pune')
        self.assertContains(response, '₹600.00')
        self.assertContains(response, 'Order items')
        self.assertContains(response, 'Payment records')
        self.assertNotContains(response, 'class="add-row"')

    def test_cart_and_favorite_admin_show_customer_product_and_totals(self):
        cart_response = self.client.get(reverse('admin:core_cartitem_changelist'))
        favorite_response = self.client.get(reverse('admin:core_favorite_changelist'))
        self.assertContains(cart_response, 'admin-customer')
        self.assertContains(cart_response, 'Admin Store Product')
        self.assertContains(cart_response, '₹600.00')
        self.assertContains(favorite_response, 'admin-customer')
        self.assertContains(favorite_response, 'Admin Store Product')

    def test_store_profile_is_editable_but_remains_a_singleton(self):
        profile = StoreProfile.get_solo()
        response = self.client.post(
            reverse('admin:core_storeprofile_change', args=[profile.pk]),
            {
                'business_name': 'Updated Euphoria Store',
                'owner_name': 'Store Owner',
                'email': 'store@example.com',
                'contact_number': '9800000000',
                'house_number': '10',
                'street': 'Store Road',
                'city': 'Kolkata',
                'state': 'West Bengal',
                'pin_code': '700002',
                'country': 'India',
                'gstin': 'GSTIN123456',
                'additional_info': 'Updated from admin.',
            },
        )
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.business_name, 'Updated Euphoria Store')
        self.assertEqual(profile.city, 'Kolkata')
        self.assertEqual(StoreProfile.objects.count(), 1)
        add_response = self.client.get(reverse('admin:core_storeprofile_add'))
        self.assertEqual(add_response.status_code, 403)

    def test_order_add_is_disabled_and_coupon_admin_loads(self):
        add_response = self.client.get(reverse('admin:core_order_add'))
        coupon_response = self.client.get(
            reverse('admin:core_coupon_change', args=[self.coupon.pk])
        )
        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(coupon_response.status_code, 200)
        self.assertContains(coupon_response, 'Bharti123')
        self.assertContains(coupon_response, '10.00')

    def test_payment_record_admin_is_read_only(self):
        response = self.client.get(
            reverse('admin:core_paymentrecord_change', args=[self.payment_record.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, '₹600.00')
        add_response = self.client.get(reverse('admin:core_paymentrecord_add'))
        self.assertEqual(add_response.status_code, 403)
        delete_response = self.client.get(
            reverse('admin:core_paymentrecord_delete', args=[self.payment_record.pk])
        )
        self.assertEqual(delete_response.status_code, 403)


class CurrencyAndStoreProfileTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Currency', slug='currency')
        self.product = Product.objects.create(
            name='Currency Product',
            slug='currency-product',
            price=Decimal('649.00'),
            category=self.category,
            available=True,
        )

    def test_storefront_uses_configured_inr_currency(self):
        home_response = self.client.get(reverse('home_page'))
        shop_response = self.client.get(reverse('shop_page'))
        self.assertContains(home_response, '₹649.00')
        self.assertContains(shop_response, '₹649.00')
        self.assertContains(shop_response, 'Price range (INR)')
        self.assertNotContains(home_response, 'shown in USD')

    def test_default_store_profile_exists_and_has_support_details(self):
        profile = StoreProfile.objects.get()
        self.assertEqual(profile.business_name, 'EuphoriaDJ')
        self.assertEqual(profile.country, 'India')
        self.assertEqual(profile.email, 'support@euphoriasj.com')

class DemoCatalogCommandTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name='Laptops',
            slug='laptops',
            description='Portable computers for work, study, and creative projects.',
        )
        self.product = Product.objects.create(
            slug='aurora-x1-smartphone',
            name='Aurora X1 Smartphone',
            category=self.category,
            price=Decimal('649.00'),
            description='Demo catalog item. Placeholder description.',
            available=True,
        )

    def run_demo_catalog(self):
        call_command('populate_demo_data', stdout=StringIO())

    def test_legacy_demo_rows_are_corrected_in_place(self):
        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=Path(media_root)):
                self.run_demo_catalog()

        self.product.refresh_from_db()
        self.category.refresh_from_db()

        self.assertEqual(self.product.slug, 'polaroid-onestep-2-instant-camera')
        self.assertEqual(self.product.name, 'Polaroid OneStep 2 Instant Camera')
        self.assertEqual(self.product.category.name, 'Cameras')
        self.assertEqual(self.product.price, Decimal('11999.00'))
        self.assertEqual(
            self.product.image.name,
            'products/demo-polaroid-onestep-2-instant-camera.png',
        )
        self.assertFalse(self.product.description.startswith('Demo catalog item.'))
        self.assertEqual(self.category.name, 'Computers')
        self.assertEqual(Product.objects.count(), 19)
        self.assertTrue(Product.objects.filter(slug='vivo-v70-fe-5g').exists())

    def test_manual_edits_survive_a_later_demo_sync(self):
        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=Path(media_root)):
                self.run_demo_catalog()

                product = Product.objects.get(slug='vivo-v70-fe-5g')
                product.name = 'vivo V70 FE — Store Edition'
                product.price = Decimal('37999.00')
                product.save(update_fields=['name', 'price'])

                self.run_demo_catalog()

        product.refresh_from_db()
        self.assertEqual(product.name, 'vivo V70 FE — Store Edition')
        self.assertEqual(product.price, Decimal('37999.00'))
        self.assertEqual(Product.objects.count(), 19)
