"""
Stripe Checkout integration for Remarkbox payments.

Supports:
- Pay What You Want (custom amount, one-time payment)
- Annual subscription (yearly recurring via one-time payment with duration)
- Top-up payments (extend subscription)
"""

import stripe
import logging

log = logging.getLogger(__name__)


def configure_stripe(api_key):
    """Configure Stripe with API key."""
    stripe.api_key = api_key


def create_checkout_session(
    amount_cents,
    payment_type,
    duration_months=1,
    email=None,
    success_url=None,
    cancel_url=None,
    metadata=None,
):
    """
    Create a Stripe Checkout session for payment.

    Parameters:
    - amount_cents: Payment amount in cents (USD)
    - payment_type: "pay_what_you_want", "annual", or "top_up"
    - duration_months: For annual/top_up, number of months (default 1)
    - email: Optional customer email
    - success_url: URL to redirect on success (must include {CHECKOUT_SESSION_ID})
    - cancel_url: URL to redirect on cancel
    - metadata: Additional metadata to store with the session

    Returns:
        Tuple of (session, error) - session object or None, and error message or None
    """
    if amount_cents < 100:  # Minimum $1.00
        return None, "Minimum payment amount is $1.00"

    # Build product description based on payment type
    if payment_type == "pay_what_you_want":
        product_name = "Remarkbox - Pay What You Want"
        description = "Thank you for supporting Remarkbox!"
    elif payment_type == "annual":
        product_name = f"Remarkbox - {duration_months} Month Subscription"
        description = f"Access to Remarkbox for {duration_months} month(s)"
    elif payment_type == "top_up":
        product_name = f"Remarkbox - Top Up ({duration_months} months)"
        description = f"Extend your subscription by {duration_months} month(s)"
    else:
        return None, f"Invalid payment type: {payment_type}"

    # Build session metadata
    session_metadata = {
        "payment_type": payment_type,
        "duration_months": str(duration_months),
        "amount_cents": str(amount_cents),
    }
    if metadata:
        session_metadata.update(metadata)

    # Build session parameters
    session_params = {
        "mode": "payment",
        "payment_method_types": ["card"],
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": product_name,
                        "description": description,
                    },
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }
        ],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": session_metadata,
    }

    # Add customer email if provided
    if email:
        session_params["customer_email"] = email

    try:
        session = stripe.checkout.Session.create(**session_params)
        log.info(
            f"Created Stripe checkout session: {session.id}, "
            f"type={payment_type}, amount=${amount_cents/100:.2f}"
        )
        return session, None
    except stripe.error.StripeError as e:
        log.error(f"Stripe checkout creation failed: {e}")
        return None, str(e)


def retrieve_checkout_session(session_id):
    """
    Retrieve a Stripe Checkout session by ID.

    Returns:
        Tuple of (session, error)
    """
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return session, None
    except stripe.error.StripeError as e:
        log.error(f"Failed to retrieve session {session_id}: {e}")
        return None, str(e)


def verify_webhook_signature(payload, sig_header, webhook_secret):
    """
    Verify Stripe webhook signature.

    Returns:
        Tuple of (event, error)
    """
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        return event, None
    except ValueError as e:
        log.error(f"Invalid webhook payload: {e}")
        return None, "Invalid payload"
    except stripe.error.SignatureVerificationError as e:
        log.error(f"Invalid webhook signature: {e}")
        return None, "Invalid signature"
