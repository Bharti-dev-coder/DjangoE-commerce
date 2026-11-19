import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from core.models import Order, PaymentRecord


logger = logging.getLogger(__name__)


class RazorpayError(Exception):
    """A safe, user-facing error raised when Razorpay cannot be used."""


def razorpay_configured():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def amount_in_paise(amount):
    return int(
        (Decimal(amount) * Decimal('100')).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP
        )
    )


def _razorpay_request(method, path, payload=None):
    if not razorpay_configured():
        raise RazorpayError(
            'Online payment is not configured. Please choose Cash on Delivery or contact the store.'
        )

    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(
        settings.RAZORPAY_API_BASE.rstrip('/') + path,
        data=data,
        method=method,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
    )
    credentials = f'{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}'
    request.add_header(
        'Authorization',
        'Basic ' + base64.b64encode(credentials.encode('utf-8')).decode('ascii'),
    )

    try:
        with urlopen(request, timeout=settings.RAZORPAY_TIMEOUT) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        logger.error('Razorpay HTTP error %s: %s', exc.code, body)
        raise RazorpayError(
            'The payment gateway could not start this payment. Please try again or use Cash on Delivery.'
        ) from exc
    except (URLError, TimeoutError, ValueError) as exc:
        logger.error('Razorpay request failed: %s', exc)
        raise RazorpayError(
            'The payment gateway could not be reached. Please try again or use Cash on Delivery.'
        ) from exc


def create_razorpay_order(order):
    """Create a server-side Razorpay order and persist its identifier."""
    if order.final_total is None or order.final_total <= 0:
        raise RazorpayError('This order does not have a payable amount.')
    if settings.RAZORPAY_CURRENCY != 'INR':
        raise RazorpayError('Online payments must use INR for this store.')

    expected_amount = amount_in_paise(order.final_total)
    response = _razorpay_request(
        'POST',
        '/orders',
        {
            'amount': expected_amount,
            'currency': 'INR',
            'receipt': order.order_number[:40],
            'payment_capture': 1,
            'notes': {
                'order_number': order.order_number,
                'customer_email': order.customer_email,
            },
        },
    )

    razorpay_order_id = response.get('id')
    if not razorpay_order_id:
        logger.error('Razorpay order response had no id: %s', response)
        raise RazorpayError('The payment gateway did not return a valid order. Please try again.')
    if response.get('amount') not in (None, expected_amount) or response.get('currency') not in (None, 'INR'):
        logger.error('Razorpay order amount/currency mismatch: %s', response)
        raise RazorpayError('The payment gateway returned an unexpected amount. Please try again.')

    order.razorpay_order_id = razorpay_order_id
    order.save(update_fields=['razorpay_order_id', 'updated_at'])
    PaymentRecord.objects.create(
        order=order,
        razorpay_order_id=razorpay_order_id,
        amount=order.final_total,
        currency='INR',
        status=PaymentRecord.STATUS_CREATED,
        raw_response=json.dumps(response),
    )
    return response


def verify_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    if not razorpay_configured():
        return False
    if not (razorpay_order_id and razorpay_payment_id and razorpay_signature):
        return False
    message = f'{razorpay_order_id}|{razorpay_payment_id}'.encode('utf-8')
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode('utf-8'),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)


def fetch_payment(razorpay_payment_id):
    return _razorpay_request('GET', f'/payments/{razorpay_payment_id}')


def validate_payment(order, payment):
    """Check that a fetched Razorpay payment belongs to this order and amount."""
    if payment.get('order_id') != order.razorpay_order_id:
        return 'The payment does not belong to this order.'
    if payment.get('status') != 'captured':
        return 'The payment has not been captured by the gateway.'
    if payment.get('currency') != 'INR':
        return 'The payment currency does not match this store.'
    expected_amount = amount_in_paise(order.final_total)
    if int(payment.get('amount', 0)) != expected_amount:
        return 'The paid amount does not match the order total.'
    return None


def record_payment_result(
    order,
    *,
    razorpay_order_id='',
    razorpay_payment_id='',
    verified=False,
    raw_response='',
    error_message='',
):
    return PaymentRecord.objects.create(
        order=order,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        amount=order.final_total,
        currency='INR',
        status=(
            PaymentRecord.STATUS_SUCCESS
            if verified
            else PaymentRecord.STATUS_FAILED
        ),
        signature_verified=verified,
        raw_response=raw_response,
        error_message=error_message,
    )
