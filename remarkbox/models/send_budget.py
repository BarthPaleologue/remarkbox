"""First-contact send budget tables (lib/send_budget.py).

SendLedger: one row per email sent to a never-verified address (kind
"send") & one per first verification (kind "conversion"). No address, no
IP. SendQueue: a first-contact email waiting for budget, one row per
address & purpose, holding the typed address only while queued.
"""

import uuid

from sqlalchemy import Column, BigInteger, SmallInteger, Unicode, UniqueConstraint

from .meta import Base, UUIDType, now_timestamp


class SendLedger(Base):
    __tablename__ = "rb_send_ledger"

    id = Column(UUIDType, primary_key=True, index=True)
    created_timestamp = Column(BigInteger, nullable=False, index=True)
    kind = Column(Unicode(16), nullable=False, index=True)
    purpose = Column(Unicode(32), nullable=False)

    def __init__(self, kind, purpose):
        self.id = uuid.uuid1()
        self.created_timestamp = now_timestamp()
        self.kind = kind
        self.purpose = purpose


class SendQueue(Base):
    __tablename__ = "rb_send_queue"
    __table_args__ = (UniqueConstraint("email", "purpose"),)

    id = Column(UUIDType, primary_key=True, index=True)
    created_timestamp = Column(BigInteger, nullable=False, index=True)
    expires_timestamp = Column(BigInteger, nullable=False, index=True)
    email = Column(Unicode(256), nullable=False)
    purpose = Column(Unicode(32), nullable=False)
    priority = Column(SmallInteger, nullable=False, default=0)
    domain = Column(Unicode(256), nullable=False)
    from_name = Column(Unicode(256), nullable=False, default="")

    def __init__(self, email, purpose, priority, domain, from_name, expires_timestamp):
        self.id = uuid.uuid1()
        self.created_timestamp = now_timestamp()
        self.email = email
        self.purpose = purpose
        self.priority = priority
        self.domain = domain
        self.from_name = from_name or ""
        self.expires_timestamp = expires_timestamp
