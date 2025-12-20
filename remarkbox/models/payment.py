"""Payment model for tracking Stripe payments."""

from sqlalchemy import BigInteger, Column, Unicode, Enum
from sqlalchemy.orm import relationship

from .meta import Base, RBase, UUIDType, now_timestamp, foreign_key

from remarkbox.lib import timestamp_to_date

import uuid


class Payment(RBase, Base):
    """
    Track payments made through Stripe Checkout.

    Each payment record corresponds to a completed Stripe Checkout session.
    """

    id = Column(UUIDType, primary_key=True, index=True)

    # Link to user who made the payment
    user_id = Column(UUIDType, foreign_key("User", "id"), index=True, nullable=False)

    # Stripe session ID for reference
    stripe_session_id = Column(Unicode(128), unique=True, nullable=False, index=True)

    # Payment type: pay_what_you_want, annual, top_up
    payment_type = Column(
        Enum("pay_what_you_want", "annual", "top_up", name="payment_type_enum"),
        nullable=False,
    )

    # Amount in cents
    amount_cents = Column(BigInteger, nullable=False)

    # Duration in months (for annual/top_up payments)
    duration_months = Column(BigInteger, default=0, nullable=False)

    # Payment status: pending, completed, failed, refunded
    status = Column(
        Enum("pending", "completed", "failed", "refunded", name="payment_status_enum"),
        default="pending",
        nullable=False,
    )

    # Timestamps
    created_timestamp = Column(BigInteger, nullable=False)
    completed_timestamp = Column(BigInteger, nullable=True)

    # Relationship to user
    user = relationship(
        argument="User",
        uselist=False,
        lazy="joined",
        back_populates="payments",
    )

    def __init__(self, user, stripe_session_id, payment_type, amount_cents, duration_months=0):
        self.id = uuid.uuid1()
        self.user_id = user.id
        self.stripe_session_id = stripe_session_id
        self.payment_type = payment_type
        self.amount_cents = amount_cents
        self.duration_months = duration_months
        self.status = "pending"
        self.created_timestamp = now_timestamp()

    def mark_completed(self):
        """Mark payment as completed."""
        self.status = "completed"
        self.completed_timestamp = now_timestamp()

    def mark_failed(self):
        """Mark payment as failed."""
        self.status = "failed"

    @property
    def amount_dollars(self):
        """Return amount in dollars."""
        return self.amount_cents / 100.0

    @property
    def human_created_date(self):
        """Return human-readable creation date."""
        return timestamp_to_date(self.created_timestamp)


def get_payment_by_session_id(dbsession, session_id):
    """Get payment by Stripe session ID."""
    return (
        dbsession.query(Payment)
        .filter(Payment.stripe_session_id == session_id)
        .one_or_none()
    )


def create_payment(dbsession, user, stripe_session_id, payment_type, amount_cents, duration_months=0):
    """Create a new payment record."""
    payment = Payment(
        user=user,
        stripe_session_id=stripe_session_id,
        payment_type=payment_type,
        amount_cents=amount_cents,
        duration_months=duration_months,
    )
    dbsession.add(payment)
    dbsession.flush()
    return payment
