"""Enrolled multi-factor authentication factors, one row per device.

A row per factor rather than columns on a user: a person may enroll
several devices, label them, & revoke one without touching the others.
Enrolling a replacement phone stays additive, so an account never drops
back to emailed codes during a swap.

`method_type` carries `totp` today. A security key or a push-approval
factor slots into the same table later without reshaping login.

The shared secret rides encrypted at rest. Unlike a paper code it cannot
be hashed: verifying a time-based code needs the secret back, so it only
ever decrypts inside a verify, with a key derived from settings.
"""

import uuid

from sqlalchemy import BigInteger, Boolean, Column, Unicode

from .meta import Base, RBase, UUIDType, foreign_key, now_timestamp


class MfaMethod(RBase, Base):
    """One enrolled multi-factor authentication factor for a user."""

    id = Column(UUIDType, primary_key=True, index=True)
    user_id = Column(UUIDType, foreign_key("User", "id"), nullable=False, index=True)
    method_type = Column(Unicode(16), nullable=False, default="totp")
    # Human label so an owner can tell their devices apart when revoking.
    label = Column(Unicode(64), nullable=False)
    # Shared secret for time-based one-time passwords, encrypted at rest.
    # Other factor types leave this empty & carry material elsewhere.
    # Width holds the wrapped form, not the bare 32-character base32
    # secret: 12-byte nonce + ciphertext + 16-byte tag, base64 encoded
    # behind a "v1:" prefix, runs 83 characters. SQLite ignores a
    # declared width; PostgreSQL does not.
    secret = Column(Unicode(128), nullable=True)
    # Highest accepted time-step counter: refuses replay of a code
    # already spent, per device.
    last_counter = Column(BigInteger, nullable=True)
    created_timestamp = Column(BigInteger, nullable=False)
    last_used_timestamp = Column(BigInteger, nullable=True)
    disabled = Column(Boolean, nullable=False, default=False)

    def __init__(self, user_id, secret, key, label=None, method_type="totp"):
        from remarkbox.lib.totp import encrypt_secret

        self.id = uuid.uuid1()
        self.user_id = user_id
        self.method_type = method_type
        self.label = label or "authenticator app"
        self.secret = encrypt_secret(secret, key)
        self.created_timestamp = now_timestamp()
        self.disabled = False

    def plain_secret(self, key):
        """Unwrap this factor's secret, or None when it will not open."""
        from remarkbox.lib.totp import decrypt_secret

        return decrypt_secret(self.secret, key)

    def verify(self, code, key):
        """True when `code` matches this factor right now.

        Stamps the replay counter & last-used time on success. Callers
        throttle; this method never counts attempts itself.
        """
        from remarkbox.lib.totp import verify_code

        if self.disabled or self.method_type != "totp":
            return False
        secret = self.plain_secret(key)
        if not secret:
            return False
        ok, counter = verify_code(secret, code, last_counter=self.last_counter)
        if ok:
            self.last_counter = counter
            self.last_used_timestamp = now_timestamp()
        return ok

    def revoke(self):
        """Retire this factor & leave every other one alone."""
        self.disabled = True
