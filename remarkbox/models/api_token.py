"""Bearer tokens for API authentication.

Our session cookie is ambient: a browser attaches it to any request aimed at
us, including one a hostile page triggered. A bearer token is not ambient —
nothing but our own client can put an `Authorization` header on a request, so
token-authenticated writes cannot be forged cross-site.

Tokens are stored hashed. Unlike our six-digit OTP, a token carries 256 bits
of entropy, so there is nothing to brute force and a single SHA-256 is the
right tool: bcrypt's slowness would buy no security here while taxing every
API request.
"""

import hashlib
import secrets

from sqlalchemy import Boolean, Column, ForeignKey, Unicode, BigInteger, Index
from sqlalchemy.orm import relationship
from sqlalchemy_utils import UUIDType

from uuid import uuid1

from .meta import Base, RBase, now_timestamp


# Prefixed so a leaked token is greppable in logs and recognisable in a paste.
TOKEN_PREFIX = "rbx_"
TOKEN_BYTES = 32


def generate_api_token():
    """Return a fresh raw token. Shown to its owner once, never stored."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def hash_api_token(raw_token):
    """Return the stored form of a raw token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class ApiToken(RBase, Base):
    """A named, revocable bearer credential belonging to one user."""

    __tablename__ = "rb_api_token"

    id = Column(UUIDType(binary=False), primary_key=True, index=True)
    user_id = Column(
        UUIDType(binary=False), ForeignKey("rb_user.id"), nullable=False, index=True
    )
    # Human label so an owner can tell their tokens apart when revoking.
    name = Column(Unicode(64), nullable=True)
    token_hash = Column(Unicode(64), nullable=False, unique=True, index=True)
    created_timestamp = Column(BigInteger, nullable=False)
    last_used_timestamp = Column(BigInteger, nullable=True)
    revoked = Column(Boolean, default=False, nullable=False)

    user = relationship("User", backref="api_tokens")

    def __init__(self, user, name=None):
        self.id = uuid1()
        self.user = user
        self.name = name
        self.created_timestamp = now_timestamp()
        self.revoked = False

    def touch(self):
        """Record use, so an owner can spot a token they no longer recognise."""
        self.last_used_timestamp = now_timestamp()


Index("ix_rb_api_token_lookup", ApiToken.token_hash, ApiToken.revoked)


def create_api_token(dbsession, user, name=None):
    """Mint a token for `user`. Returns `(ApiToken, raw_token)`.

    The raw token is returned exactly once, here. We keep only its hash, so a
    database read cannot recover a working credential.
    """
    raw_token = generate_api_token()
    token = ApiToken(user, name=name)
    token.token_hash = hash_api_token(raw_token)
    dbsession.add(token)
    dbsession.flush()
    return token, raw_token


def get_api_token_by_raw(dbsession, raw_token):
    """Return a live ApiToken matching `raw_token`, or None."""
    if not raw_token:
        return None
    return (
        dbsession.query(ApiToken)
        .filter(
            ApiToken.token_hash == hash_api_token(raw_token),
            ApiToken.revoked == False,
        )
        .first()
    )


def get_api_tokens_by_user(dbsession, user):
    """Return every unrevoked token belonging to `user`, newest first."""
    return (
        dbsession.query(ApiToken)
        .filter(ApiToken.user_id == user.id, ApiToken.revoked == False)
        .order_by(ApiToken.created_timestamp.desc())
        .all()
    )


def get_api_token_by_id(dbsession, token_id):
    return dbsession.query(ApiToken).filter(ApiToken.id == token_id).first()
