import json
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.ai import (
    CHAT_PRODUCTS_SESSION_KEY,
    VIEWED_SESSION_KEY,
    format_money,
    get_recommendations,
)
from core.models import (
    CartItem,
    Category,
    Favorite,
    Order,
    OrderItem,
    Product,
)
from core.ollama_client import OllamaError


class AIBaseTestCase(TestCase):
    def setUp(self):
        self.planner_patch = patch(
            'core.ai_planner.chat',
            side_effect=OllamaError('offline in test'),
        )
        self.planner_patch.start()
        self.addCleanup(self.planner_patch.stop)

        self.user = User.objects.create_user(
            username='assistant-user',
            email='assistant@example.com',
            password='test-password-123',
        )
        self.other_user = User.objects.create_user(
            username='other-user',
            email='other@example.com',
            password='test-password-123',
        )
        self.audio = Category.objects.create(name='Audio', slug='audio')
        self.laptops = Category.objects.create(name='Laptops', slug='laptops')
        self.cameras = Category.objects.create(name='Cameras', slug='cameras')

        self.headphones = Product.objects.create(
            name='Pulse Over-Ear Headphones',
            slug='pulse-over-ear-headphones',
            description='Comfortable over-ear headphones for everyday listening.',
            price=Decimal('249.00'),
            category=self.audio,
            available=True,
        )
        self.earbuds = Product.objects.create(
            name='Beat Buds Wireless',
            slug='beat-buds-wireless',
            description='Wireless earbuds with a pocket charging case.',
            price=Decimal('129.00'),
            category=self.audio,
            available=True,
        )
        self.speaker = Product.objects.create(
            name='Room Fill Speaker',
            slug='room-fill-speaker',
            description='Compact wireless speaker for a small room.',
            price=Decimal('189.00'),
            category=self.audio,
            available=True,
        )
        self.laptop = Product.objects.create(
            name='Vector 14 Laptop',
            slug='vector-14-laptop',
            description='A light laptop for study and everyday work.',
            price=Decimal('1149.00'),
            category=self.laptops,
            available=True,
        )
        self.camera = Product.objects.create(
            name='Frame X Mirrorless Camera',
            slug='frame-x-mirrorless-camera',
            description='Mirrorless camera body for travel photography.',
            price=Decimal('1299.00'),
            category=self.cameras,
            available=True,
        )
        self.charger = Product.objects.create(
            name='Wireless Charging Pad',
            slug='wireless-charging-pad',
            description='A compact wireless charging pad for a desk.',
            price=Decimal('49.00'),
            category=self.audio,
            available=True,
        )

    def chat(self, message, user=None):
        if user is not None:
            self.client.force_login(user)
        return self.client.post(
            reverse('ai_chat'),
            data=json.dumps({'message': message}),
            content_type='application/json',
        )

    def order_for(self, user, order_status=Order.ORDER_CONFIRMED, product=None):
        order = Order.objects.create(
            user=user,
            customer_name='Test Customer',
            customer_email='customer@example.com',
            customer_phone='9876543210',
            shipping_full_name='Test Customer',
            shipping_phone='9876543210',
            shipping_house_number='12',
            shipping_street='Private Street',
            shipping_landmark='',
            shipping_city='Private City',
            shipping_state='Private State',
            shipping_pin_code='123456',
            shipping_country='India',
            subtotal=Decimal('249.00'),
            final_total=Decimal('249.00'),
            payment_method=Order.PAYMENT_METHOD_COD,
            payment_status=Order.PAYMENT_PENDING,
            order_status=order_status,
        )
        OrderItem.objects.create(
            order=order,
            product=product or self.headphones,
            product_name=(product or self.headphones).name,
            unit_price=(product or self.headphones).price,
            quantity=1,
        )
        return order


class AIChatAndSearchTests(AIBaseTestCase):
    def test_offline_chat_uses_catalog_search_and_real_prices(self):
        response = self.chat('find wireless earbuds under 200')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['ai_available'])
        self.assertTrue(payload['degraded'])
        self.assertIn('offline', payload['notice'].lower())
        self.assertEqual(payload['intent'], 'product_search')
        names = [product['name'] for product in payload['products']]
        self.assertIn(self.earbuds.name, names)
        self.assertNotIn(self.headphones.name, names)
        for product in payload['products']:
            self.assertIn(product['name'], Product.objects.values_list('name', flat=True))
            self.assertEqual(product['price_display'], format_money(Decimal(product['price'])))
            self.assertFalse(product['can_add'])

    def test_unknown_search_does_not_return_unrelated_products(self):
        response = self.chat('find a quantum flux capacitor')
        payload = response.json()

        self.assertEqual(payload['intent'], 'product_search')
        self.assertEqual(payload['products'], [])
        self.assertIn('could not find', payload['reply'].lower())

    def test_llm_plan_is_validated_against_explicit_filters(self):
        fake_plan = {
            'intent': 'product_search',
            'search_terms': ['wireless', 'earbuds', 'under', '200'],
            'category': 'Laptops',
            'min_price': 200,
            'max_price': 200,
            'quantity': 1,
            'product_name': 'Vector 14 Laptop',
            'order_number': '',
            'support_topic': 'other',
        }
        with patch('core.ai_planner.chat', return_value=json.dumps(fake_plan)):
            response = self.chat('find wireless earbuds under 200')

        payload = response.json()
        self.assertTrue(payload['ai_available'])
        names = [product['name'] for product in payload['products']]
        self.assertEqual(names, [self.earbuds.name])

    def test_model_cannot_start_a_cart_action_without_an_explicit_request(self):
        fake_plan = {
            'intent': 'add_to_cart',
            'search_terms': ['wireless', 'earbuds'],
            'category': 'Audio',
            'min_price': None,
            'max_price': None,
            'quantity': 1,
            'product_name': self.earbuds.name,
            'order_number': '',
            'support_topic': 'other',
        }
        with patch('core.ai_planner.chat', return_value=json.dumps(fake_plan)):
            response = self.chat('show me wireless earbuds', self.user)

        payload = response.json()
        self.assertEqual(payload['intent'], 'product_search')
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())
        self.assertEqual(
            [product['name'] for product in payload['products']],
            [self.earbuds.name],
        )

    def test_model_cannot_downgrade_an_explicit_search_to_a_greeting(self):
        fake_plan = {
            'intent': 'greeting',
            'search_terms': [],
            'category': '',
            'min_price': None,
            'max_price': None,
            'quantity': 1,
            'product_name': '',
            'order_number': '',
            'support_topic': 'other',
        }
        with patch('core.ai_planner.chat', return_value=json.dumps(fake_plan)):
            response = self.chat('find wireless earbuds under 200')

        payload = response.json()
        self.assertEqual(payload['intent'], 'product_search')
        self.assertEqual(
            [product['name'] for product in payload['products']],
            [self.earbuds.name],
        )

    def test_malformed_llm_response_uses_deterministic_fallback(self):
        with patch('core.ai_planner.chat', return_value='not valid JSON'):
            response = self.chat('show me audio products')

        payload = response.json()
        self.assertFalse(payload['ai_available'])
        self.assertEqual(payload['intent'], 'product_search')
        self.assertTrue(payload['products'])
        self.assertTrue(all(product['name'] in [
            self.headphones.name,
            self.earbuds.name,
            self.speaker.name,
            self.charger.name,
        ] for product in payload['products']))

    def test_chat_endpoint_validates_method_and_message(self):
        self.assertEqual(self.client.get(reverse('ai_chat')).status_code, 405)
        empty = self.client.post(
            reverse('ai_chat'),
            data=json.dumps({'message': '   '}),
            content_type='application/json',
        )
        self.assertEqual(empty.status_code, 400)

        bad_json = self.client.post(
            reverse('ai_chat'),
            data='{',
            content_type='application/json',
        )
        self.assertEqual(bad_json.status_code, 400)

    @override_settings(AI_CHAT_MAX_MESSAGE_LENGTH=12)
    def test_chat_message_length_is_bounded(self):
        response = self.chat('this message is definitely too long')
        self.assertEqual(response.status_code, 400)

    def test_chat_ui_and_assets_are_available(self):
        response = self.client.get(reverse('home_page'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-ai-chat')
        self.assertContains(response, 'assistant/chat/')
        self.assertContains(response, 'theme/js/ai_chat.js')
        self.assertContains(response, 'theme/css/ai_chat.css')
        self.assertIsNotNone(finders.find('theme/js/ai_chat.js'))
        self.assertIsNotNone(finders.find('theme/css/ai_chat.css'))

    def test_chat_endpoint_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.get(reverse('home_page'))
        self.assertEqual(response.status_code, 200)
        token = csrf_client.cookies.get('csrftoken')
        self.assertIsNotNone(token)

        blocked = csrf_client.post(
            reverse('ai_chat'),
            data=json.dumps({'message': 'show me audio'}),
            content_type='application/json',
        )
        self.assertEqual(blocked.status_code, 403)

        allowed = csrf_client.post(
            reverse('ai_chat'),
            data=json.dumps({'message': 'show me audio'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token.value,
        )
        self.assertEqual(allowed.status_code, 200)

    def test_chat_saves_bounded_session_context(self):
        response = self.chat('show me audio products')
        self.assertEqual(response.status_code, 200)
        session = self.client.session
        self.assertIn(CHAT_PRODUCTS_SESSION_KEY, session)
        self.assertTrue(session[CHAT_PRODUCTS_SESSION_KEY])


class AIChatCartTests(AIBaseTestCase):
    def test_chat_adds_a_resolved_product_without_trusting_client_prices(self):
        response = self.chat('add 2 Beat Buds Wireless to my cart', self.user)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['intent'], 'add_to_cart')
        self.assertEqual(payload['action']['type'], 'cart_added')
        item = CartItem.objects.get(user=self.user, product=self.earbuds)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.source, CartItem.SOURCE_AI_CHAT)
        self.assertEqual(payload['action']['cart_count'], 2)
        self.assertEqual(payload['products'][0]['name'], self.earbuds.name)
        self.assertEqual(payload['products'][0]['price_display'], format_money(self.earbuds.price))

    def test_ambiguous_chat_add_asks_for_a_choice_and_does_not_add(self):
        response = self.chat('add wireless to my cart', self.user)

        payload = response.json()
        self.assertEqual(payload['intent'], 'add_to_cart')
        self.assertIsNone(payload['action'])
        self.assertGreater(len(payload['products']), 1)
        self.assertIn('more than one match', payload['reply'].lower())
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())

    def test_anonymous_chat_add_requests_signin_without_creating_cart(self):
        response = self.chat('add Pulse Over-Ear Headphones to my cart')

        payload = response.json()
        self.assertEqual(payload['action']['type'], 'signin_required')
        self.assertIn('sign in', payload['reply'].lower())
        self.assertTrue(payload['signin_url'])
        self.assertFalse(CartItem.objects.exists())
        self.assertFalse(payload['products'][0]['can_add'])

    def test_chat_rejects_quantity_above_five(self):
        response = self.chat('add 8 Beat Buds Wireless to my cart', self.user)

        payload = response.json()
        self.assertIn('between 1 and 5', payload['reply'].lower())
        self.assertIsNone(payload['action'])
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())

    def test_chat_uses_the_existing_cart_quantity_cap(self):
        CartItem.objects.create(
            user=self.user,
            product=self.earbuds,
            quantity=4,
            source=CartItem.SOURCE_PRODUCT_DETAIL,
        )
        response = self.chat('add 2 Beat Buds Wireless to my cart', self.user)

        payload = response.json()
        item = CartItem.objects.get(user=self.user, product=self.earbuds)
        self.assertEqual(item.quantity, 5)
        self.assertTrue(payload['action']['capped'])
        self.assertIn('maximum quantity of 5', payload['reply'].lower())

    def test_ai_cart_add_endpoint_uses_server_product_and_csrf(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('ai_cart_add', args=[self.headphones.pk]),
            data=json.dumps({'quantity': 2}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['product']['name'], self.headphones.name)
        item = CartItem.objects.get(user=self.user, product=self.headphones)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.source, CartItem.SOURCE_AI_CHAT)

    def test_ai_cart_add_endpoint_validates_auth_method_and_quantity(self):
        anonymous = self.client.post(
            reverse('ai_cart_add', args=[self.headphones.pk]),
            data=json.dumps({'quantity': 1}),
            content_type='application/json',
        )
        self.assertEqual(anonymous.status_code, 401)

        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse('ai_cart_add', args=[self.headphones.pk])).status_code,
            405,
        )
        invalid = self.client.post(
            reverse('ai_cart_add', args=[self.headphones.pk]),
            data=json.dumps({'quantity': 9}),
            content_type='application/json',
        )
        self.assertEqual(invalid.status_code, 400)

        self.headphones.available = False
        self.headphones.save(update_fields=['available'])
        missing = self.client.post(
            reverse('ai_cart_add', args=[self.headphones.pk]),
            data=json.dumps({'quantity': 1}),
            content_type='application/json',
        )
        self.assertEqual(missing.status_code, 404)

    def test_ai_cart_add_endpoint_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        page = csrf_client.get(reverse('product_detail', args=[self.headphones.slug]))
        self.assertEqual(page.status_code, 200)
        token = csrf_client.cookies.get('csrftoken')
        self.assertIsNotNone(token)

        blocked = csrf_client.post(
            reverse('ai_cart_add', args=[self.headphones.pk]),
            data=json.dumps({'quantity': 1}),
            content_type='application/json',
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(CartItem.objects.exists())

        allowed = csrf_client.post(
            reverse('ai_cart_add', args=[self.headphones.pk]),
            data=json.dumps({'quantity': 1}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token.value,
        )
        self.assertEqual(allowed.status_code, 200)


class AIOrderPrivacyTests(AIBaseTestCase):
    def test_signed_in_customer_sees_only_their_own_order_fields(self):
        own_order = self.order_for(self.user)
        other_order = self.order_for(self.other_user, product=self.camera)

        response = self.chat('where is my order?', self.user)
        payload = response.json()

        self.assertEqual(payload['intent'], 'order_status')
        self.assertEqual(payload['order']['order_number'], own_order.order_number)
        self.assertNotIn('customer_email', payload['order'])
        self.assertNotIn('shipping_full_name', payload['order'])
        self.assertNotIn('shipping_phone', payload['order'])
        serialized = json.dumps(payload)
        self.assertNotIn('Private Street', serialized)
        self.assertNotIn('customer@example.com', serialized)
        self.assertNotIn(other_order.order_number, serialized)

    def test_another_users_order_number_is_not_disclosed(self):
        other_order = self.order_for(self.other_user, product=self.camera)
        response = self.chat(f'where is my order {other_order.order_number}', self.user)

        payload = response.json()
        self.assertIsNone(payload['order'])
        self.assertIn("could not find that order in your account", payload['reply'])
        self.assertNotIn(other_order.order_number, json.dumps(payload))

    def test_anonymous_order_request_is_sent_to_signin(self):
        order = self.order_for(self.user)
        response = self.chat('where is my order?')

        payload = response.json()
        self.assertIsNone(payload['order'])
        self.assertTrue(payload['signin_url'])
        self.assertNotIn(order.order_number, json.dumps(payload))
        self.assertIn('sign in', payload['reply'].lower())

    def test_model_cannot_inject_an_order_number(self):
        fake_plan = {
            'intent': 'order_status',
            'search_terms': [],
            'category': '',
            'min_price': None,
            'max_price': None,
            'quantity': 1,
            'product_name': '',
            'order_number': 'EUP-20260101-ABCDEF12',
            'support_topic': 'order_status',
        }
        with patch('core.ai_planner.chat', return_value=json.dumps(fake_plan)):
            response = self.chat('where is my order?', self.user)

        payload = response.json()
        self.assertIsNone(payload['order'])
        self.assertIn('do not have any orders', payload['reply'])
        self.assertNotIn('EUP-20260101-ABCDEF12', json.dumps(payload))

    def test_order_status_snapshot_uses_live_order_values(self):
        order = self.order_for(self.user, order_status=Order.ORDER_SHIPPED)
        response = self.chat(f'status of order {order.order_number}', self.user)
        snapshot = response.json()['order']

        self.assertEqual(snapshot['order_number'], order.order_number)
        self.assertEqual(snapshot['status'], 'Shipped')
        self.assertEqual(snapshot['payment_status'], 'Pending')
        self.assertEqual(snapshot['total'], format_money(order.final_total))
        self.assertEqual(snapshot['items'][0]['name'], self.headphones.name)


class AISupportTests(AIBaseTestCase):
    def test_shipping_answer_uses_configured_store_values(self):
        response = self.chat('what are the delivery charges?')
        payload = response.json()

        self.assertEqual(payload['intent'], 'support')
        self.assertIn(format_money(settings.STORE_SHIPPING_CHARGE), payload['reply'])
        self.assertIn(format_money(settings.STORE_FREE_SHIPPING_THRESHOLD), payload['reply'])

    def test_model_cannot_turn_a_policy_question_into_product_search(self):
        fake_plan = {
            'intent': 'product_search',
            'search_terms': ['shipping'],
            'category': 'Audio',
            'min_price': None,
            'max_price': None,
            'quantity': 1,
            'product_name': '',
            'order_number': '',
            'support_topic': 'other',
        }
        with patch('core.ai_planner.chat', return_value=json.dumps(fake_plan)):
            response = self.chat('what are the shipping charges?')

        payload = response.json()
        self.assertEqual(payload['intent'], 'support')
        self.assertEqual(payload['products'], [])
        self.assertIn(format_money(settings.STORE_SHIPPING_CHARGE), payload['reply'])

    def test_return_policy_is_not_invented(self):
        response = self.chat('what is your return policy?')
        payload = response.json()

        self.assertIn('does not show', payload['reply'].lower())
        self.assertNotIn('30 days', payload['reply'].lower())
        self.assertTrue(any('contact' in link['url'] for link in payload['links']))

    def test_payment_answer_reflects_available_methods(self):
        response = self.chat('what payment methods do you accept?')
        payload = response.json()

        self.assertIn('cash on delivery', payload['reply'].lower())
        self.assertIn('payment status', payload['reply'].lower())
        self.assertTrue(any('orders' in link['url'] for link in payload['links']))

    def test_general_help_lists_capabilities_without_fake_facts(self):
        response = self.chat('what can you do?')
        payload = response.json()

        self.assertIn('search the live', payload['reply'].lower())
        self.assertIn('recommend', payload['reply'].lower())
        self.assertIn('cart', payload['reply'].lower())


class AIRecommendationTests(AIBaseTestCase):
    def test_favorites_produce_a_category_reason(self):
        Favorite.objects.create(user=self.user, product=self.headphones)
        self.client.force_login(self.user)
        recommendations = get_recommendations(
            self.user,
            self.client.session,
            limit=3,
        )

        self.assertTrue(recommendations)
        self.assertEqual(recommendations[0].product.category_id, self.audio.pk)
        self.assertIn('Audio', recommendations[0].reason)

    def test_cart_products_are_not_recommended_again(self):
        CartItem.objects.create(
            user=self.user,
            product=self.earbuds,
            quantity=1,
            source=CartItem.SOURCE_QUICK_ADD,
        )
        recommendations = get_recommendations(
            self.user,
            self.client.session,
            limit=4,
        )
        ids = [item.product.pk for item in recommendations]
        self.assertNotIn(self.earbuds.pk, ids)

    def test_product_detail_records_a_recent_view(self):
        response = self.client.get(reverse('product_detail', args=[self.earbuds.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.earbuds.pk, self.client.session[VIEWED_SESSION_KEY])

    def test_recommendations_are_available_for_a_fresh_visitor(self):
        recommendations = get_recommendations(
            self.user,
            self.client.session,
            limit=4,
        )
        self.assertEqual(len(recommendations), 4)
        self.assertTrue(all(item.product.available for item in recommendations))

    def test_specific_recommendation_respects_category_and_budget(self):
        response = self.chat('recommend a laptop for study under 1200', self.user)
        payload = response.json()

        self.assertEqual(payload['intent'], 'recommendation')
        self.assertTrue(payload['products'])
        self.assertTrue(
            all(product['category'] == 'Laptops' for product in payload['products'])
        )
        self.assertTrue(
            all(product['price_value'] <= 1200 for product in payload['products'])
        )
        self.assertIn('Laptops', payload['reply'])
        self.assertIn('under', payload['reply'].lower())
