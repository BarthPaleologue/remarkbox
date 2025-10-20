#!/usr/bin/env python3
"""
Send Node Digest Notifications Script

This script sends scheduled node event notifications via email digest and ensures
all sent notifications are properly marked as sent in the database to prevent
duplicate notifications on subsequent runs.

Usage:
    remarkbox_send_node_digest_notifications production.ini
"""

import logging
import transaction
from pyramid.paster import bootstrap, setup_logging

from ..lib.notify import get_email_notifications, send_digest_notifications, filter_orphaned_notifications
from ..models import get_tm_session
from ..models.notification import NodeEventNotification
from ..models.meta import now_timestamp
from . import base_parser

log = logging.getLogger(__name__)


def get_arg_parser():
    """Configure command line argument parser."""
    return base_parser("Send Node Notification Digests.")


def should_have_been_sent(notification):
    """
    Check if notification should have been sent based on frequency and age.

    Args:
        notification: NodeEventNotification object to check

    Returns:
        bool: True if notification should have been sent, False otherwise
    """
    frequency = notification.frequency
    age_ms = now_timestamp() - notification.created_timestamp
    
    if frequency == "immediately":
        return True
    elif frequency == "daily":
        # Should be sent if older than 24 hours
        return age_ms >= (24 * 60 * 60 * 1000)
    elif frequency == "weekly":
        # Should be sent if older than 7 days
        return age_ms >= (7 * 24 * 60 * 60 * 1000)
    elif frequency == "never":
        return False
    
    return False


def safe_deliver_scheduled_notifications(request, dbsession):
    """
    Deliver scheduled notifications with protection against orphaned notifications.
    """
    from datetime import datetime

    # Temporarily replace request.dbsession with our transaction-managed session
    old_dbsession = request.dbsession
    request.dbsession = dbsession

    try:
        # Get daily notifications and filter out orphaned ones
        notification_dict = get_email_notifications(dbsession, "daily")
        filtered_dict = filter_orphaned_notifications(notification_dict)
        send_digest_notifications(request, filtered_dict, "daily")

        # Send weekly on Monday
        if datetime.today().weekday() == 0:
            notification_dict = get_email_notifications(dbsession, "weekly")
            filtered_dict = filter_orphaned_notifications(notification_dict)
            send_digest_notifications(request, filtered_dict, "weekly")
    finally:
        # Restore original dbsession
        request.dbsession = old_dbsession


def get_unsent_notification_count(request):
    """
    Get count of unsent notifications using a fresh database session.

    Args:
        request: Pyramid request object

    Returns:
        int: Number of unsent notifications
    """
    with transaction.manager:
        dbsession = get_tm_session(
            request.registry["dbsession_factory"], transaction.manager
        )
        return dbsession.query(NodeEventNotification).filter(
            NodeEventNotification.sent == False
        ).count()


def mark_ready_notifications_as_sent(request):
    """
    Mark notifications as sent if they were ready to be delivered based on frequency rules.
    Only marks non-orphaned notifications (those with valid node_event).

    Args:
        request: Pyramid request object

    Returns:
        tuple: (total_unsent, marked_as_sent, left_for_later)
    """
    with transaction.manager:
        dbsession = get_tm_session(
            request.registry["dbsession_factory"], transaction.manager
        )

        # Get all unsent notifications
        unsent_notifications = dbsession.query(NodeEventNotification).filter(
            NodeEventNotification.sent == False
        ).all()

        total_unsent = len(unsent_notifications)

        if total_unsent == 0:
            return total_unsent, 0, 0

        # Only mark notifications that should have been sent based on frequency
        # and are not orphaned (have valid node_event)
        ready_notification_ids = [
            n.id for n in unsent_notifications
            if should_have_been_sent(n) and n.node_event is not None
        ]

        # Count orphaned notifications separately
        orphaned_count = sum(1 for n in unsent_notifications if n.node_event is None)
        if orphaned_count > 0:
            log.warning(f"Found {orphaned_count} orphaned notifications that will not be marked as sent")

        marked_as_sent = 0
        if ready_notification_ids:
            marked_as_sent = dbsession.query(NodeEventNotification).filter(
                NodeEventNotification.id.in_(ready_notification_ids)
            ).update({
                'sent': True,
                'updated_timestamp': now_timestamp()
            }, synchronize_session=False)

            # Ensure changes are persisted
            dbsession.flush()
            transaction.commit()

        left_for_later = total_unsent - marked_as_sent
        return total_unsent, marked_as_sent, left_for_later


def main():
    """Main entry point for the digest notification script."""
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    log.info("Starting node digest notification delivery")

    try:
        with bootstrap(args.config) as env:
            request = env["request"]
            
            # Check initial state
            before_count = get_unsent_notification_count(request)
            log.info(f"Found {before_count} unsent notifications before delivery")
            
            if before_count == 0:
                log.info("No notifications to process")
                return
            
            # Deliver scheduled notifications with orphaned notification protection
            log.info("Delivering scheduled notifications...")
            with transaction.manager:
                dbsession = get_tm_session(
                    request.registry["dbsession_factory"], transaction.manager
                )
                safe_deliver_scheduled_notifications(request, dbsession)
                transaction.commit()
            
            # Check final state and mark ready notifications as sent
            log.info("Checking for notifications that need to be marked as sent...")
            total_unsent, marked_as_sent, left_for_later = mark_ready_notifications_as_sent(request)
            
            # Log results
            if total_unsent == 0:
                log.info("All notifications were properly marked as sent by delivery function")
            elif marked_as_sent > 0:
                log.info(f"Marked {marked_as_sent} ready notifications as sent")
                if left_for_later > 0:
                    log.info(f"Left {left_for_later} notifications for later delivery based on frequency rules")
            else:
                log.info("No notifications were ready to be sent based on frequency rules")
            
            log.info("Node digest notification delivery completed successfully")
            
    except Exception as e:
        log.error(f"Error during digest notification delivery: {e}")
        raise


if __name__ == "__main__":
    main()