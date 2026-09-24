"""First-contact send budget: emails to never-verified addresses draw from
a budget that only real verifications can grow.

    allowance = floor + per_conversion x conversions(last 7 days)
    spent     = first-contact sends(last 24 hours)

A bot can rotate IPs, run a real browser, solve any puzzle & read this
code, yet it cannot raise the allowance without owning the mailboxes it
types, & a bot verifying its own mailboxes harms nobody. So the number of
strangers we email stays bounded by `floor` a day however large a
campaign grows, while real traffic (people verify) raises the ceiling on
its own. Failed code entries never count, either way.

Over budget, a request waits in rb_send_queue (one row per address &
purpose, oldest first) & remarkbox_drain_send_queue sends it as budget
frees up. The visitor sees the same message either way. Numbers
live in settings (`app.send_budget.*`, private pillar in production).
"""
import logging

from ..models.send_budget import SendLedger, SendQueue
from ..models.meta import now_timestamp

log = logging.getLogger(__name__)

HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS
SPEND_WINDOW_MS = DAY_MS
CONVERSION_WINDOW_MS = 7 * DAY_MS
QUEUE_TTL_MS = 6 * HOUR_MS

# Carrier email-to-SMS gateways. Nobody joins with one; the 2026-09 wave
# used them to text strangers' phones through join forms.
SMS_GATEWAY_DOMAINS = frozenset({
    "tmomail.net", "vtext.com", "vzwpix.com", "txt.att.net", "mms.att.net",
    "messaging.sprintpcs.com", "pm.sprint.com", "mymetropcs.com",
    "msg.fi.google.com", "email.uscc.net", "sms.myboostmobile.com",
    "myboostmobile.com", "mmst5.tracfone.com", "vmobl.com",
    "text.republicwireless.com", "sms.cricketwireless.net",
    "mms.cricketwireless.net", "txt.bell.ca", "pcs.rogers.com",
    "msg.telus.com", "txt.freedommobile.ca",
})


def is_sms_gateway(email):
    return email.rsplit("@", 1)[-1].strip().lower() in SMS_GATEWAY_DOMAINS


DEFAULTS = {
    "send_budget.floor": 20,
    "send_budget.per_conversion": 10,
}


def _setting(settings, key):
    try:
        return int(settings.get("app." + key, DEFAULTS[key]))
    except (TypeError, ValueError):
        return DEFAULTS[key]


def _count(db, kind, since):
    return (
        db.query(SendLedger)
        .filter(SendLedger.kind == kind, SendLedger.created_timestamp >= since)
        .count()
    )


def allowance(db, settings, now=None):
    now = now or now_timestamp()
    return _setting(settings, "send_budget.floor") + _setting(
        settings, "send_budget.per_conversion"
    ) * _count(db, "conversion", now - CONVERSION_WINDOW_MS)


def spent(db, now=None):
    now = now or now_timestamp()
    return _count(db, "send", now - SPEND_WINDOW_MS)


def has_budget(db, settings, now=None):
    return spent(db, now) < allowance(db, settings, now)


def record_send(db, purpose):
    db.add(SendLedger("send", purpose))
    db.flush()


def record_conversion(db, purpose):
    db.add(SendLedger("conversion", purpose))
    db.flush()


def _live_queue(db, now):
    return db.query(SendQueue).filter(SendQueue.expires_timestamp > now)


def try_spend(db, settings, purpose):
    """Claim one send now when budget allows & nobody is waiting ahead;
    return False to queue instead."""
    now = now_timestamp()
    if _live_queue(db, now).count() or not has_budget(db, settings, now):
        return False
    record_send(db, purpose)
    return True


def enqueue(db, email, purpose, domain, from_name="", priority=0):
    """Queue one first-contact email; a repeat request for the same address
    & purpose keeps its place (raising priority, never lowering it)."""
    now = now_timestamp()
    row = (
        db.query(SendQueue)
        .filter(SendQueue.email == email, SendQueue.purpose == purpose)
        .one_or_none()
    )
    if row is None:
        row = SendQueue(email, purpose, priority, domain, from_name,
                        now + QUEUE_TTL_MS)
        db.add(row)
    else:
        row.priority = max(row.priority or 0, priority)
        row.expires_timestamp = max(row.expires_timestamp, now + QUEUE_TTL_MS)
    db.flush()
    return row


def prune(db, now=None):
    now = now or now_timestamp()
    db.query(SendQueue).filter(SendQueue.expires_timestamp <= now).delete(
        synchronize_session=False
    )
    db.query(SendLedger).filter(
        SendLedger.created_timestamp < now - CONVERSION_WINDOW_MS
    ).delete(synchronize_session=False)


def drain(db, settings, send):
    """Send queued first-contact emails while budget allows. `send(row)`
    delivers one & returns True when it went out (False drops the row, for
    an address verified or throttled meanwhile). Returns the count sent."""
    now = now_timestamp()
    prune(db, now)
    sent = 0
    while has_budget(db, settings):
        row = (
            _live_queue(db, now)
            .order_by(SendQueue.priority.desc(), SendQueue.created_timestamp)
            .first()
        )
        if row is None:
            break
        delivered = send(row)
        if delivered:
            record_send(db, row.purpose)
            sent += 1
        db.delete(row)
        db.flush()
    return sent


def gate(request, email, purpose, queue=True):
    """One place every first-contact send asks: True means send now (the
    spend is recorded). False means say the same thing & send nothing: an
    SMS gateway, or budget spent (queued for the drain when `queue`)."""
    if is_sms_gateway(email):
        return False
    db = request.dbsession
    if try_spend(db, request.registry.settings, purpose):
        return True
    if queue:
        enqueue(db, email, purpose, request.domain)
    return False
