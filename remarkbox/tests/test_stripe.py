"""Tests for Stripe Checkout integration."""

import unittest
from unittest.mock import patch, MagicMock, PropertyMock

from remarkbox.stripe.checkout import (
    configure_stripe,
    create_checkout_session,
    retrieve_checkout_session,
    verify_webhook_signature,
)

from remarkbox.models.payment import Payment, get_payment_by_session_id, create_payment
from remarkbox.models.user import User


class TestStripeCheckoutModule(unittest.TestCase):
    """Unit tests for stripe/checkout.py"""

    def test_configure_stripe(self):
        """Test that configure_stripe sets the API key."""
        with patch('remarkbox.stripe.checkout.stripe') as mock_stripe:
            configure_stripe("sk_test_123")
            self.assertEqual(mock_stripe.api_key, "sk_test_123")

    def test_create_checkout_session_minimum_amount(self):
        """Test that minimum amount is enforced."""
        session, error = create_checkout_session(
            amount_cents=50,  # Less than $1.00
            payment_type="pay_what_you_want",
        )
        self.assertIsNone(session)
        self.assertEqual(error, "Minimum payment amount is $1.00")

    def test_create_checkout_session_invalid_payment_type(self):
        """Test that invalid payment type returns error."""
        session, error = create_checkout_session(
            amount_cents=1000,
            payment_type="invalid_type",
        )
        self.assertIsNone(session)
        self.assertIn("Invalid payment type", error)

    @patch('remarkbox.stripe.checkout.stripe.checkout.Session.create')
    def test_create_checkout_session_pay_what_you_want(self, mock_create):
        """Test creating a pay-what-you-want checkout session."""
        mock_session = MagicMock()
        mock_session.id = "cs_test_123"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test_123"
        mock_create.return_value = mock_session

        session, error = create_checkout_session(
            amount_cents=1000,
            payment_type="pay_what_you_want",
            email="test@example.com",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        self.assertIsNone(error)
        self.assertEqual(session.id, "cs_test_123")

        # Verify the call was made with correct parameters
        call_args = mock_create.call_args
        self.assertEqual(call_args.kwargs["mode"], "payment")
        self.assertEqual(call_args.kwargs["payment_method_types"], ["card"])
        self.assertEqual(call_args.kwargs["customer_email"], "test@example.com")
        self.assertEqual(call_args.kwargs["metadata"]["payment_type"], "pay_what_you_want")

    @patch('remarkbox.stripe.checkout.stripe.checkout.Session.create')
    def test_create_checkout_session_annual(self, mock_create):
        """Test creating an annual subscription checkout session."""
        mock_session = MagicMock()
        mock_session.id = "cs_test_annual"
        mock_create.return_value = mock_session

        session, error = create_checkout_session(
            amount_cents=12000,  # $120
            payment_type="annual",
            duration_months=12,
            email="test@example.com",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        self.assertIsNone(error)
        self.assertEqual(session.id, "cs_test_annual")

        call_args = mock_create.call_args
        self.assertEqual(call_args.kwargs["metadata"]["payment_type"], "annual")
        self.assertEqual(call_args.kwargs["metadata"]["duration_months"], "12")

    @patch('remarkbox.stripe.checkout.stripe.checkout.Session.create')
    def test_create_checkout_session_top_up(self, mock_create):
        """Test creating a top-up checkout session."""
        mock_session = MagicMock()
        mock_session.id = "cs_test_topup"
        mock_create.return_value = mock_session

        session, error = create_checkout_session(
            amount_cents=2500,  # $25
            payment_type="top_up",
            duration_months=0,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        self.assertIsNone(error)
        self.assertEqual(session.id, "cs_test_topup")

    @patch('remarkbox.stripe.checkout.stripe.checkout.Session.create')
    def test_create_checkout_session_stripe_error(self, mock_create):
        """Test handling Stripe errors during session creation."""
        import stripe
        mock_create.side_effect = stripe.error.StripeError("API error")

        session, error = create_checkout_session(
            amount_cents=1000,
            payment_type="pay_what_you_want",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )

        self.assertIsNone(session)
        self.assertIn("API error", error)

    @patch('remarkbox.stripe.checkout.stripe.checkout.Session.retrieve')
    def test_retrieve_checkout_session_success(self, mock_retrieve):
        """Test retrieving a checkout session."""
        mock_session = MagicMock()
        mock_session.id = "cs_test_123"
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        session, error = retrieve_checkout_session("cs_test_123")

        self.assertIsNone(error)
        self.assertEqual(session.id, "cs_test_123")
        self.assertEqual(session.payment_status, "paid")

    @patch('remarkbox.stripe.checkout.stripe.checkout.Session.retrieve')
    def test_retrieve_checkout_session_not_found(self, mock_retrieve):
        """Test retrieving a non-existent checkout session."""
        import stripe
        mock_retrieve.side_effect = stripe.error.StripeError("No such session")

        session, error = retrieve_checkout_session("cs_invalid")

        self.assertIsNone(session)
        self.assertIn("No such session", error)

    @patch('remarkbox.stripe.checkout.stripe.Webhook.construct_event')
    def test_verify_webhook_signature_success(self, mock_construct):
        """Test successful webhook signature verification."""
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"
        mock_construct.return_value = mock_event

        event, error = verify_webhook_signature(
            payload=b'{"test": "data"}',
            sig_header="sig_header",
            webhook_secret="whsec_test",
        )

        self.assertIsNone(error)
        self.assertEqual(event.type, "checkout.session.completed")

    @patch('remarkbox.stripe.checkout.stripe.Webhook.construct_event')
    def test_verify_webhook_signature_invalid(self, mock_construct):
        """Test invalid webhook signature."""
        import stripe
        mock_construct.side_effect = stripe.error.SignatureVerificationError(
            "Invalid signature", "sig_header"
        )

        event, error = verify_webhook_signature(
            payload=b'{"test": "data"}',
            sig_header="bad_sig",
            webhook_secret="whsec_test",
        )

        self.assertIsNone(event)
        self.assertEqual(error, "Invalid signature")


class TestPaymentModel(unittest.TestCase):
    """Unit tests for Payment model."""

    @patch("remarkbox.models.user.is_user_name_available", MagicMock(return_value=True))
    def setUp(self):
        self.user = User("test@example.com")
        self.user.id = "test-user-id-123"

    def test_payment_creation(self):
        """Test creating a Payment object."""
        payment = Payment(
            user=self.user,
            stripe_session_id="cs_test_123",
            payment_type="pay_what_you_want",
            amount_cents=1000,
            duration_months=0,
        )

        self.assertEqual(payment.stripe_session_id, "cs_test_123")
        self.assertEqual(payment.payment_type, "pay_what_you_want")
        self.assertEqual(payment.amount_cents, 1000)
        self.assertEqual(payment.status, "pending")
        self.assertIsNotNone(payment.created_timestamp)
        self.assertIsNone(payment.completed_timestamp)

    def test_payment_amount_dollars(self):
        """Test amount_dollars property."""
        payment = Payment(
            user=self.user,
            stripe_session_id="cs_test_123",
            payment_type="pay_what_you_want",
            amount_cents=1250,
            duration_months=0,
        )

        self.assertEqual(payment.amount_dollars, 12.50)

    def test_payment_mark_completed(self):
        """Test marking payment as completed."""
        payment = Payment(
            user=self.user,
            stripe_session_id="cs_test_123",
            payment_type="annual",
            amount_cents=12000,
            duration_months=12,
        )

        self.assertEqual(payment.status, "pending")
        self.assertIsNone(payment.completed_timestamp)

        payment.mark_completed()

        self.assertEqual(payment.status, "completed")
        self.assertIsNotNone(payment.completed_timestamp)

    def test_payment_mark_failed(self):
        """Test marking payment as failed."""
        payment = Payment(
            user=self.user,
            stripe_session_id="cs_test_123",
            payment_type="top_up",
            amount_cents=2500,
            duration_months=0,
        )

        payment.mark_failed()

        self.assertEqual(payment.status, "failed")


class TestPayWhatYouCanModel(unittest.TestCase):
    """Unit tests for PayWhatYouCan model."""

    @patch("remarkbox.models.user.is_user_name_available", MagicMock(return_value=True))
    def setUp(self):
        self.user = User("test@example.com")

    def test_pay_what_you_can_creation(self):
        """Test creating a PayWhatYouCan preference."""
        from remarkbox.models import PayWhatYouCan

        pwc = PayWhatYouCan(self.user, "yearly", 100)

        self.assertEqual(pwc.frequency, "yearly")
        self.assertEqual(pwc.amount, 100)
        # contributions defaults to 0 in DB but may be None before flush
        self.assertIn(pwc.contributions, [0, None])
        self.assertIsNotNone(pwc.created_timestamp)

    def test_pay_what_you_can_update(self):
        """Test updating PayWhatYouCan preferences."""
        from remarkbox.models import PayWhatYouCan

        pwc = PayWhatYouCan(self.user, "once", 50)
        original_timestamp = pwc.updated_timestamp

        pwc.update("yearly", 100)

        self.assertEqual(pwc.frequency, "yearly")
        self.assertEqual(pwc.amount, 100)
        self.assertGreaterEqual(pwc.updated_timestamp, original_timestamp)
