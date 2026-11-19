# Razorpay setup and verification notes

## Current status

Cash on Delivery is implemented and tested. Razorpay order creation, checkout UI,
server-side signature verification, payment-status fetching, and payment audit
records are implemented and were verified with a live **test-mode** card payment
on 19 November 2026.

The test keys are configured only in the git-ignored `.env`; never commit the key
secret. The test secret was shared during setup, so rotate it in the Razorpay
dashboard and replace the value in `.env` after verification.

## Live verification result (19 November 2026)

A ₹178.00 test-mode card payment was captured for order
`EUP-20261118-E45E6A75` (gateway order `order_U1mAxLtu2xw7WC`, payment
`pay_U1mDA721P3O6d1`). The server verified the HMAC-SHA256 signature, fetched the
captured payment from Razorpay, checked the order/amount/currency/status, marked
the order **Success / Confirmed**, stored the transaction ID, created a
`PaymentRecord` with `signature_verified = True`, cleared the cart, rendered the
success page, and exposed both records in Django Admin. A repeated callback was
idempotent.

During this run, Razorpay's demo-bank flow closed the browser checkout tab before
its automatic callback could post. The captured payment was then submitted to the
app's signed callback endpoint directly. That exercised the real gateway payment,
live payment lookup, signature verification, state transition, and success page.
Add a webhook if automatic recovery from a closed browser is required.

## Configure credentials

1. Create or open a Razorpay account and use **Test mode** first.
2. Generate a test key ID and key secret from the Razorpay dashboard.
3. Copy `.env.example` to `.env` and fill in:

```dotenv
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_server_side_secret
```

4. Keep `RAZORPAY_KEY_SECRET` out of templates, JavaScript, screenshots, and
   source control. Only `RAZORPAY_KEY_ID` is sent to the browser.
5. Restart the Django server after changing `.env`.

The implementation uses Python's standard library for Razorpay REST calls, so
no Razorpay SDK install is required.

## What the server does

- Creates the Razorpay order on the server with the order total converted to
  paise and the currency fixed to INR.
- Stores the Razorpay order ID on the local order and creates a payment audit
  record.
- Sends only the public key ID and Razorpay order ID to the checkout page.
- Receives the Razorpay callback fields on a CSRF-protected POST endpoint.
- Verifies the callback with an HMAC-SHA256 signature using the secret key.
- Calls Razorpay's payment API and checks that the payment belongs to the local
  order, is captured, uses INR, and matches the local order amount.
- Marks the order paid only after those checks pass.
- Makes verification idempotent so a repeated callback cannot mark the same
  order paid twice or count a coupon twice.
- Keeps the cart available while an online order is pending. The ordered cart
  lines are removed only after a verified payment.
- Leaves failed/cancelled/incomplete payments pending or failed; the customer
  can retry from **My orders** or the order detail page.

## Manual test checklist for a new account

1. Add a product to the cart and apply `Bharti123`.
2. Choose **Online payment (Razorpay)** at checkout.
3. Confirm the Razorpay window shows the same final total in INR.
4. Complete a test payment.
5. Confirm the order changes to payment status **Success** and order status
   **Confirmed**, the payment ID is stored, and the ordered cart lines are gone.
6. Confirm the payment record in Django Admin has `signature_verified = True`.
7. Attempt a deliberately invalid or tampered callback and confirm the order is
   not marked paid.

## Limitations

- Razorpay webhooks are not implemented. Payment verification relies on the
  callback plus server-side gateway verification. For production hardening,
  add webhook handling for asynchronous payment events.
- There is no product stock field in the current schema, so stock validation is
  limited to the existing `Product.available` flag.
- Shipping, tax, and free-shipping thresholds are configurable in `.env`.
