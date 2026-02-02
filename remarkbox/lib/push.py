"""
Web Push notification support using the VAPID protocol.

This module provides:
  - VAPID key generation and management
  - Push subscription storage helpers
  - Sending push notifications via the Web Push protocol

Dependencies:
  - py_vapid: VAPID key generation and signing
  - pywebpush: Web Push API client

If these packages are not installed, push notifications are silently
disabled and all functions become no-ops.
"""

import json
import logging
import os

log = logging.getLogger(__name__)

# Try to import push dependencies.  If they are not installed, push
# notification support is silently disabled.
try:
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    PUSH_AVAILABLE = True
except ImportError:
    PUSH_AVAILABLE = False
    log.info("pywebpush/py_vapid not installed; push notifications disabled")


def get_vapid_keys(settings):
    """
    Return a dict with 'private_key' and 'public_key' VAPID strings.

    Reads from the application settings (ini file):
        push.vapid_private_key
        push.vapid_public_key
        push.vapid_contact  (mailto: URI for the VAPID contact)

    If keys are not configured, returns None.
    """
    private_key = settings.get("push.vapid_private_key")
    public_key = settings.get("push.vapid_public_key")
    contact = settings.get("push.vapid_contact", "")

    if private_key and public_key:
        return {
            "private_key": private_key,
            "public_key": public_key,
            "contact": contact,
        }
    return None


def generate_vapid_keys():
    """
    Generate a new VAPID key pair for initial setup.

    Returns a dict with 'private_key' and 'public_key' as base64url strings,
    suitable for pasting into the .ini configuration file.

    Usage (from a Python shell):
        from remarkbox.lib.push import generate_vapid_keys
        keys = generate_vapid_keys()
        print(keys)
    """
    if not PUSH_AVAILABLE:
        raise RuntimeError(
            "pywebpush and py_vapid must be installed to generate VAPID keys. "
            "Run: pip install pywebpush py_vapid"
        )
    vapid = Vapid()
    vapid.generate_keys()
    return {
        "private_key": vapid.private_pem(),
        "public_key": vapid.public_key_urlsafe_base64(),
    }


def send_push_notification(subscription_info, payload, vapid_keys):
    """
    Send a push notification to a single subscription.

    Args:
        subscription_info: dict with 'endpoint', 'keys' (p256dh, auth)
        payload: dict to JSON-encode as the notification body
        vapid_keys: dict from get_vapid_keys()

    Returns True on success, False on failure.
    """
    if not PUSH_AVAILABLE:
        return False

    if not vapid_keys:
        log.warning("VAPID keys not configured; cannot send push notification")
        return False

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=vapid_keys["private_key"],
            vapid_claims={
                "sub": vapid_keys["contact"],
            },
        )
        return True
    except WebPushException as e:
        log.warning("Push notification failed: %s", e, exc_info=True)
        # A 410 Gone response means the subscription is no longer valid.
        if hasattr(e, "response") and e.response is not None:
            if e.response.status_code == 410:
                log.info("Subscription expired (410 Gone), should be removed")
        return False
    except Exception:
        log.warning("Unexpected error sending push notification", exc_info=True)
        return False


def send_push_to_user(request, user, payload):
    """
    Send a push notification to all active subscriptions for a user.

    Args:
        request: Pyramid request (used to read settings)
        user: User model instance
        payload: dict to send as the notification body

    Returns the number of successful sends.
    """
    if not PUSH_AVAILABLE:
        return 0

    vapid_keys = get_vapid_keys(request.registry.settings)
    if not vapid_keys:
        return 0

    subscriptions = get_push_subscriptions(user)
    if not subscriptions:
        return 0

    success_count = 0
    expired = []

    for sub in subscriptions:
        ok = send_push_notification(sub, payload, vapid_keys)
        if ok:
            success_count += 1
        else:
            # Track potentially expired subscriptions for cleanup.
            expired.append(sub)

    return success_count


def get_push_subscriptions(user):
    """
    Return the list of push subscription dicts for a user.

    Subscriptions are stored as a JSON string in user.push_subscriptions.
    Returns an empty list if no subscriptions exist.
    """
    if not user.push_subscriptions:
        return []
    try:
        return json.loads(user.push_subscriptions)
    except (json.JSONDecodeError, TypeError):
        return []


def add_push_subscription(user, subscription_info):
    """
    Add a push subscription for a user, avoiding duplicates.

    Args:
        user: User model instance
        subscription_info: dict with 'endpoint', 'keys' (p256dh, auth)

    Returns True if the subscription was added, False if already exists.
    """
    subscriptions = get_push_subscriptions(user)

    # Check for duplicate endpoint.
    for sub in subscriptions:
        if sub.get("endpoint") == subscription_info.get("endpoint"):
            return False

    subscriptions.append(subscription_info)
    user.push_subscriptions = json.dumps(subscriptions)
    return True


def remove_push_subscription(user, endpoint):
    """
    Remove a push subscription by endpoint URL.

    Args:
        user: User model instance
        endpoint: The push subscription endpoint URL to remove

    Returns True if removed, False if not found.
    """
    subscriptions = get_push_subscriptions(user)
    original_count = len(subscriptions)
    subscriptions = [s for s in subscriptions if s.get("endpoint") != endpoint]

    if len(subscriptions) < original_count:
        user.push_subscriptions = json.dumps(subscriptions) if subscriptions else None
        return True
    return False
