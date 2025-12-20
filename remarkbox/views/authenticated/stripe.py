"""
Stripe payment views for Remarkbox.

Supports:
- Pay What You Want (custom amount, one-time payment)
- Annual subscription (yearly payment with duration)
- Top-up payments (extend subscription)
"""

from pyramid.view import view_config
from pyramid.httpexceptions import HTTPFound, HTTPBadRequest
from pyramid.response import Response

from remarkbox.views import user_required
from remarkbox.lib.mail import send_operator_email
from remarkbox.stripe.checkout import (
    configure_stripe,
    create_checkout_session,
    retrieve_checkout_session,
    verify_webhook_signature,
)
from remarkbox.models import Payment, get_payment_by_session_id, create_payment

import logging

log = logging.getLogger(__name__)


@view_config(route_name="billing", renderer="billing.j2")
@user_required(
    flash_msg="Please verify your email to access billing.",
    flash_level="info",
    return_to_route_name="billing",
)
def billing(request):
    """Display the billing/payment page."""
    # Get user's payment history
    payments = request.user.payments.filter(Payment.status == "completed").limit(10).all()

    return {
        "the_title": "Billing",
        "payments": payments,
    }


@view_config(route_name="create-checkout", request_method="POST")
@user_required()
def create_checkout(request):
    """Create a Stripe Checkout session and redirect to it."""
    configure_stripe(request.app.get("stripe.secret"))

    # Get form parameters
    payment_type = request.params.get("payment_type", "pay_what_you_want")
    amount_str = request.params.get("amount", "0")
    duration_str = request.params.get("duration_months", "12")

    # Parse amount (convert dollars to cents)
    try:
        amount_dollars = float(amount_str.replace("$", "").replace(",", "").strip())
        amount_cents = int(amount_dollars * 100)
    except (ValueError, AttributeError):
        request.session.flash(("Invalid amount specified.", "error"))
        return HTTPFound("/billing")

    # Parse duration
    try:
        duration_months = int(duration_str)
    except (ValueError, AttributeError):
        duration_months = 12

    if amount_cents < 100:
        request.session.flash(("Minimum payment is $1.00.", "error"))
        return HTTPFound("/billing")

    # Build URLs
    base_url = request.app.get("app_url", request.host_url)
    success_url = f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/billing"

    # Create checkout session
    session, error = create_checkout_session(
        amount_cents=amount_cents,
        payment_type=payment_type,
        duration_months=duration_months,
        email=request.user.email,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": str(request.user.id)},
    )

    if error:
        log.error(f"Checkout creation failed for user {request.user.id}: {error}")
        request.session.flash((f"Payment error: {error}", "error"))
        return HTTPFound("/billing")

    # Create pending payment record
    create_payment(
        dbsession=request.dbsession,
        user=request.user,
        stripe_session_id=session.id,
        payment_type=payment_type,
        amount_cents=amount_cents,
        duration_months=duration_months,
    )

    # Redirect to Stripe Checkout
    return HTTPFound(session.url)


@view_config(route_name="billing-success", renderer="billing-success.j2")
@user_required()
def billing_success(request):
    """Handle successful payment return from Stripe."""
    configure_stripe(request.app.get("stripe.secret"))

    session_id = request.params.get("session_id")
    if not session_id:
        request.session.flash(("Missing session information.", "error"))
        return HTTPFound("/billing")

    # Retrieve the session from Stripe
    session, error = retrieve_checkout_session(session_id)
    if error:
        log.error(f"Failed to retrieve session {session_id}: {error}")
        request.session.flash(("Could not verify payment.", "error"))
        return HTTPFound("/billing")

    # Check payment status
    if session.payment_status != "paid":
        log.warning(f"Session {session_id} not paid: {session.payment_status}")
        request.session.flash(("Payment not completed.", "error"))
        return HTTPFound("/billing")

    # Update payment record
    payment = get_payment_by_session_id(request.dbsession, session_id)
    if payment and payment.status == "pending":
        payment.mark_completed()
        request.dbsession.add(payment)

        # Send notification to operator
        send_operator_email(
            request,
            f"New payment received! User: {request.user.email}, "
            f"Amount: ${payment.amount_cents/100:.2f}, Type: {payment.payment_type}",
        )

    return {
        "the_title": "Payment Successful",
        "session": session,
        "payment": payment,
    }


@view_config(route_name="stripe-webhook", request_method="POST")
def stripe_webhook(request):
    """Handle Stripe webhook events."""
    webhook_secret = request.app.get("stripe.webhook_secret")
    if not webhook_secret:
        log.error("Stripe webhook secret not configured")
        return Response(status=500, json_body={"error": "Webhook not configured"})

    configure_stripe(request.app.get("stripe.secret"))

    # Get the raw body and signature
    payload = request.body
    sig_header = request.headers.get("Stripe-Signature")

    if not sig_header:
        return Response(status=400, json_body={"error": "Missing signature"})

    # Verify webhook signature
    event, error = verify_webhook_signature(payload, sig_header, webhook_secret)
    if error:
        log.error(f"Webhook signature verification failed: {error}")
        return Response(status=400, json_body={"error": error})

    log.info(f"Received Stripe webhook: {event.type}")

    # Handle the event
    if event.type == "checkout.session.completed":
        session = event.data.object
        _handle_checkout_completed(request.dbsession, session)
    elif event.type == "payment_intent.payment_failed":
        payment_intent = event.data.object
        log.warning(f"Payment failed: {payment_intent.id}")
    else:
        log.debug(f"Unhandled webhook event type: {event.type}")

    return Response(status=200, json_body={"received": True})


def _handle_checkout_completed(dbsession, session):
    """Process a completed checkout session from webhook."""
    session_id = session.id

    if session.payment_status != "paid":
        log.info(f"Session {session_id} not paid yet: {session.payment_status}")
        return

    # Find and update the payment record
    payment = get_payment_by_session_id(dbsession, session_id)
    if payment:
        if payment.status == "pending":
            payment.mark_completed()
            dbsession.add(payment)
            log.info(f"Payment {payment.id} marked as completed via webhook")
        else:
            log.info(f"Payment {payment.id} already processed: {payment.status}")
    else:
        log.warning(f"No payment record found for session {session_id}")
