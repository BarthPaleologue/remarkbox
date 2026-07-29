"""Authenticator-app support for passwordless login via time-based
one-time passwords (TOTP, RFC 6238).

An optional alternative to email OTP: a user enrolls any standard
authenticator app by scanning a QR code (or typing the secret), proves
enrollment with one code, & receives ten single-use paper backup codes.
Login then asks for a current app code instead of sending email, which
also removes that address from the email-bombing attack surface
entirely.

Replay protection: every accepted code records its time-step counter &
any code at or below the recorded counter is refused, so a shoulder-
surfed or intercepted code dies within its 30s window.

Each enrolled device is its own `MfaMethod` row, so an account may carry
several & revoke one without disturbing the rest. Paper codes get hashed;
a shared secret cannot, since verifying a code needs the secret back, so
it rides wrapped in authenticated encryption instead & only ever unwraps
inside a verify.
"""
import base64
import json
import secrets
import time

import bcrypt
import pyotp
import qrcode
import qrcode.image.svg
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

TOTP_PERIOD = 30
TOTP_VALID_WINDOW = 1  # accept +/- one time-step of clock drift
BACKUP_CODE_COUNT = 10


SECRET_PREFIX = "v1:"


def derive_secret_key(settings):
    """Return the 32-byte key that wraps enrolled factor secrets.

    A shared secret cannot be hashed the way paper codes are: verifying
    a time-based code needs the secret back. So it rides encrypted at
    rest & only ever decrypts inside a verify. Set `app.mfa.secret_key`
    (64 hex characters) in production; without it we derive a key from
    `session.secret`, which keeps development & tests working while
    still refusing to store anything in cleartext.
    """
    configured = (settings.get("app.mfa.secret_key") or "").strip()
    if configured:
        return bytes.fromhex(configured)
    seed = (settings.get("session.secret") or "remarkbox").encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"remarkbox-mfa-secret-v1",
    ).derive(seed)


def encrypt_secret(secret, key):
    """Wrap a factor secret for storage. Returns text, never bytes."""
    nonce = secrets.token_bytes(12)
    blob = ChaCha20Poly1305(key).encrypt(nonce, secret.encode("utf-8"), None)
    return SECRET_PREFIX + base64.b64encode(nonce + blob).decode("ascii")


def decrypt_secret(stored, key):
    """Unwrap a stored factor secret, or None when it will not open.

    Tolerates a value written before encryption existed by returning it
    unchanged, so an early enrollment keeps working instead of locking
    somebody out of their account.
    """
    if not stored:
        return None
    if not stored.startswith(SECRET_PREFIX):
        return stored
    try:
        raw = base64.b64decode(stored[len(SECRET_PREFIX):])
        return ChaCha20Poly1305(key).decrypt(raw[:12], raw[12:], None).decode(
            "utf-8"
        )
    except Exception:
        return None


def new_secret():
    """Return a fresh base32 time-based one-time password (TOTP) secret."""
    return pyotp.random_base32()


def provisioning_uri(secret, account_name, issuer):
    """Return the otpauth:// URI an authenticator app enrolls from."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=account_name, issuer_name=issuer
    )


def qr_svg(uri):
    """Return an inline SVG QR code for the provisioning URI.

    SVG renders without JavaScript & without pillow, keeping our
    progressive-enhancement floor: the enrollment page works in any
    browser.
    """
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage)
    return img.to_string(encoding="unicode")


def verify_code(secret, code, last_counter=None, now=None):
    """Verify a time-based one-time password (TOTP) code with drift
    window & replay protection.

    Returns (ok, matched_counter). A code only verifies when its
    time-step counter is strictly greater than last_counter, so an
    already-used code can never be replayed.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False, None
    now = int(now if now is not None else time.time())
    totp = pyotp.TOTP(secret)
    for offset in range(-TOTP_VALID_WINDOW, TOTP_VALID_WINDOW + 1):
        step_time = now + (offset * TOTP_PERIOD)
        counter = step_time // TOTP_PERIOD
        if last_counter is not None and counter <= last_counter:
            continue
        if pyotp.utils.strings_equal(totp.at(step_time), code):
            return True, counter
    return False, None


def generate_backup_codes(count=BACKUP_CODE_COUNT):
    """Return single-use paper codes in the form XXXX-XXXX (digits)."""
    codes = []
    for _ in range(count):
        raw = f"{secrets.randbelow(10**8):08d}"
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_backup_codes(codes):
    """Return a JSON string of bcrypt hashes for storage at rest."""
    hashes = [
        bcrypt.hashpw(c.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        for c in codes
    ]
    return json.dumps(hashes)


def count_backup_codes(stored_json):
    """Return how many unused paper codes remain in storage.

    Returns 0 for missing, blank or unparsable storage so a caller can
    always render a number.
    """
    if not stored_json:
        return 0
    try:
        hashes = json.loads(stored_json)
    except (ValueError, TypeError):
        return 0
    if not isinstance(hashes, list):
        return 0
    return len(hashes)


def check_and_consume_backup_code(stored_json, code):
    """Check a paper code & burn it on success.

    Returns (ok, new_stored_json). A matched hash is removed so each
    code works exactly once.
    """
    code = (code or "").strip()
    if not stored_json or not code:
        return False, stored_json
    try:
        hashes = json.loads(stored_json)
    except (ValueError, TypeError):
        return False, stored_json
    for i, h in enumerate(hashes):
        try:
            if bcrypt.checkpw(code.encode("utf-8"), h.encode("utf-8")):
                del hashes[i]
                return True, json.dumps(hashes)
        except ValueError:
            continue
    return False, stored_json
