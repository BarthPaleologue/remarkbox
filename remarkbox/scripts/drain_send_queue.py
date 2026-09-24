"""Cron entry point: send queued first-contact verification codes as the
send budget frees up (lib/send_budget.py). Silent on stdout so cron mails
nobody; runs every minute.

Usage:
    remarkbox_drain_send_queue production.ini
"""

import logging
import sys

from pyramid.paster import bootstrap, setup_logging

from .. import models  # noqa: F401  (registers the mappers)
from ..lib import send_budget
from ..lib.mail import send_verification_digits
from ..models.user import get_or_create_user_by_email

log = logging.getLogger(__name__)


def make_sender(request):
    db = request.dbsession

    def send(row):
        user = get_or_create_user_by_email(db, row.email)
        # Verified or on the per-address backoff since it queued: drop.
        if user.verified or user.throttle_password():
            return False
        raw_otp = user.new_password()
        db.add(user)
        db.flush()
        send_verification_digits(
            request.app, row.domain, request.debug_mode,
            row.email, raw_otp,
        )
        return True

    return send


def run(request):
    with request.tm:
        sent = send_budget.drain(
            request.dbsession, request.registry.settings, make_sender(request)
        )
    if sent:
        log.info("send queue: %d first-contact emails sent", sent)
    return sent


def main(argv=sys.argv):
    if len(argv) < 2:
        print(f"usage: {argv[0]} <config_uri>")
        sys.exit(1)
    setup_logging(argv[1])
    env = bootstrap(argv[1])
    try:
        run(env["request"])
    finally:
        env["closer"]()
