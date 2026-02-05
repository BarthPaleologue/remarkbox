import os
import time

from sqlalchemy import Column, Unicode, BigInteger

from .meta import Base


class SudoOtp(Base):
    """One-time password for gating destructive operations."""

    __tablename__ = "rb_sudo_otp"

    action_key = Column(Unicode(256), primary_key=True)
    code = Column(Unicode(8), nullable=False)
    action = Column(Unicode(512), nullable=False)
    client_ip = Column(Unicode(45), nullable=True)
    created_at = Column(BigInteger, nullable=False)
    expires_at = Column(BigInteger, nullable=False)


# TTL in milliseconds (15 minutes).
SUDO_OTP_TTL_MS = 15 * 60 * 1000


def generate_sudo_otp_code():
    """Return a zero-padded 8-digit numeric string."""
    n = int.from_bytes(os.urandom(5), "big") % (10**8)
    return str(n).zfill(8)


def create_sudo_otp(dbsession, action_key, action, client_ip=None):
    """Create or replace a sudo OTP for the given action_key.

    Opportunistically cleans up expired rows.
    Returns the raw 8-digit code string.
    """
    now_ms = int(time.time() * 1000)

    # Clean up expired rows (best-effort, small table).
    dbsession.query(SudoOtp).filter(SudoOtp.expires_at < now_ms).delete()

    code = generate_sudo_otp_code()

    existing = dbsession.query(SudoOtp).get(action_key)
    if existing:
        existing.code = code
        existing.action = action
        existing.client_ip = client_ip
        existing.created_at = now_ms
        existing.expires_at = now_ms + SUDO_OTP_TTL_MS
    else:
        otp = SudoOtp(
            action_key=action_key,
            code=code,
            action=action,
            client_ip=client_ip,
            created_at=now_ms,
            expires_at=now_ms + SUDO_OTP_TTL_MS,
        )
        dbsession.add(otp)

    dbsession.flush()
    return code


def verify_sudo_otp(dbsession, action_key, code):
    """Verify a sudo OTP.

    Returns (True, None) on success or (False, error_message) on failure.
    Deletes the OTP on success (single-use).
    """
    now_ms = int(time.time() * 1000)

    otp = dbsession.query(SudoOtp).get(action_key)
    if otp is None:
        return False, "No OTP found. Please request a new code."

    if otp.expires_at < now_ms:
        dbsession.delete(otp)
        dbsession.flush()
        return False, "OTP has expired. Please request a new code."

    if otp.code != code:
        return False, "Invalid OTP code."

    # Success — single-use, delete it.
    dbsession.delete(otp)
    dbsession.flush()
    return True, None
