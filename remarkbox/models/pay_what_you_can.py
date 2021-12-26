from sqlalchemy import BigInteger, Boolean, Column, Enum

from sqlalchemy.orm import relationship, backref

from sqlalchemy.ext.associationproxy import association_proxy

from .meta import Base, RBase
from .meta import now_timestamp, foreign_key
from .meta import UUIDType


class PayWhatYouCan(RBase, Base):
    user_id = Column(UUIDType, foreign_key("User", "id"), primary_key=True, index=True)
    # whether or not this is a one time charge or a yearly.
    frequency = Column(Enum("once","yearly", name="frequency"), nullable=False)
    # the amount in cents to charge this user.
    amount = Column(BigInteger, nullable=False)
    # the total contributions from this user in cents.
    contributions = Column(BigInteger, default=0, nullable=False)
    created_timestamp = Column(BigInteger, nullable=False)
    updated_timestamp = Column(BigInteger, nullable=False)

    # 1-to-1 relationships.
    user = relationship(argument="User", uselist=False, lazy="joined", back_populates="pay_what_you_can")

    def __init__(self, user, frequency, amount):
        self.created_timestamp = now_timestamp()
        self.updated_timestamp = now_timestamp()
        self.user = user
        self.frequency = frequency
        self.amount = amount

    def update(self, frequency, amount):
        if frequency != self.frequency:
            self.frequency = frequency
            self.updated_timestamp = now_timestamp()
        if amount != self.amount:
            self.amount = amount
            self.updated_timestamp = now_timestamp()
