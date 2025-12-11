from __future__ import unicode_literals

from collections import defaultdict

from slacker import Slacker

from remarkbox.lib.mail import send_template_email

from remarkbox.models import NodeEventNotification

import logging
log = logging.getLogger(__name__)


SLACK_MESSAGE = """:mailbox_with_mail: *{}* added a {} on *{}*:

>>> {}

:link: {}/r/{}
"""


def immediately_notify_namespace_moderators_via_slack(request, node_event):
    node = node_event.node
    namespace = node.root.namespace
    node_event_to_slack_event = {"created": "new thread", "commented": "new comment"}
    if namespace.slack_oauth_records:
        for oauth in namespace.slack_oauth_records:
            slack = Slacker(oauth.token)
            slack.chat.post_message(
                "#remarks",
                SLACK_MESSAGE.format(
                    node.user.name,
                    node_event_to_slack_event[node_event.action],
                    namespace.name,
                    node.data,
                    request.host_url,
                    node.id,
                ),
            )


def filter_watchers(watchers, exclude_users=None, include_users=None):
    f_watchers = []
    tally = defaultdict(list)
    for watcher in watchers:
        if not watcher.user.verified:
            # skip unverified users to avoid sending unsolicited emails.
            # example: somebody writes a comment with another user's email.
            continue
        if exclude_users is not None and watcher.user in exclude_users:
            # skip all excluded users.
            # example: don't notify the user who generated the event.
            continue
        if include_users is not None and watcher.user not in include_users:
            # skip all users not in the include_users list.
            # example: we only want to notify moderators.
            continue
        if watcher.user in tally[watcher.notification_method]:
            # this user already has a watcher of this method, for this event.
            # example: user was replied to and also follows the thread.
            continue
        # add the user to tally notify once per event, per method.
        tally[watcher.notification_method].append(watcher.user)
        # finally add watcher to the filtered watcher list.
        f_watchers.append(watcher)
    return f_watchers


def get_all_watchers(request, node_event):
    """Given a request and node_event, return all watcher objects."""
    # Note: we only notify a user once per method per event.

    # aggregate a list of watcher objects.
    watchers = []

    # get node and namespace from event.
    node = node_event.node
    namespace = node.root.namespace

    # Note: the order that we collect watchers, acts as the order of priority
    # when we encounter duplicate notification method: reply, node, namespace.

    if node.parent and node.parent.verified and node.parent != node.root:
        # extend the watchers list to let the owner of the parent node
        # know there was a new child node added to the conversation.
        watchers.extend(node.parent.user.reply_watchers)

    # extend the watchers list with any watchers of the request's root (thread).
    watchers.extend(node.root.watchers)

    # extend the watchers list with any watchers of the request's Namespace.
    watchers.extend(namespace.watchers)

    # the user who causes an event does not need a notification.
    exclude_users = [node_event.user]
    include_users = None

    if not node.approved:
        # this may happen if moderation is enabled for a Namespace.
        # if the event node is not approved, only notify moderators.
        include_users = namespace.moderators

    # filter dupes and excluded users.
    return filter_watchers(watchers, exclude_users, include_users)


def schedule_notifications(request, node_event):

    # Slack notifications currently only supports created and commented.
    if node_event.action in {"created", "commented"}:
        immediately_notify_namespace_moderators_via_slack(request, node_event)

    # fan out and create a notification object for each watcher.
    notifications = []
    for watcher in get_all_watchers(request, node_event):
        notification = watcher.new_notification(node_event)
        request.dbsession.add(notification)
        notifications.append(notification)

    # really create all notifcation objects in database, in one transaction.
    request.dbsession.flush()

    # filter out all the notifications which should be sent immediately.
    immediate_notifications = [n for n in notifications if n.frequency == "immediately"]

    # send them.
    send_immediate_notifications(request, immediate_notifications)


def get_email_notifications(dbsession, frequency):
    """
    Returns a notification dictionary where each key holds a list of
    notifications objects for a particular user.
    """

    notifications = (
        dbsession.query(NodeEventNotification)
        .filter(NodeEventNotification.sent == False)
        .filter(NodeEventNotification.watcher.has(notification_frequency=frequency))
        .filter(NodeEventNotification.watcher.has(notification_method="email"))
        .order_by(NodeEventNotification.created_timestamp)
        .all()
    )

    # a notification dictionary where the key is the user_id
    # and value is a list of notification objects.
    notification_dict = defaultdict(list)
    for notification in notifications:
        notification_dict[notification.user_id].append(notification)
    return notification_dict


def filter_orphaned_notifications(notification_dict):
    """
    Filter out notifications with null node_event from the notification dictionary.

    Args:
        notification_dict: Dictionary mapping user_id to list of notifications

    Returns:
        dict: Filtered notification dictionary with orphaned notifications removed
    """
    filtered_dict = {}
    total_orphaned = 0

    for user_id, notifications in notification_dict.items():
        valid_notifications = []
        for notification in notifications:
            if notification.node_event is None:
                total_orphaned += 1
                log.warning(f"Skipping orphaned notification {notification.id} for user {user_id}")
            else:
                valid_notifications.append(notification)

        if valid_notifications:
            filtered_dict[user_id] = valid_notifications

    if total_orphaned > 0:
        log.warning(f"Filtered out {total_orphaned} orphaned notifications")

    return filtered_dict


def deliver_scheduled_notifications(request=None):
    from datetime import datetime
    from pyramid.scripting import prepare

    # this allows us to pass a None request.
    with prepare(request) as env, env["request"].tm as tm:
        request = env["request"]

        notification_dict = get_email_notifications(request.dbsession, "daily")
        filtered_dict = filter_orphaned_notifications(notification_dict)
        send_digest_notifications(request, filtered_dict, "daily")

        # Send weekly on Monday.
        if datetime.today().weekday() == 0:
            notification_dict = get_email_notifications(request.dbsession, "weekly")
            filtered_dict = filter_orphaned_notifications(notification_dict)
            send_digest_notifications(request, filtered_dict, "weekly")
    

def send_immediate_notifications(request, notifications):
    deliver_email_notifications = request.app.get("deliver_email_notifications", True)

    if len(notifications) == 0:
        return None

    node_event = notifications[0].node_event
    root = node_event.node.root
    namespace = root.namespace

    subject = "[{}] new activity".format(namespace.name)

    for notification in notifications:
        if deliver_email_notifications and notification.method == "email":
            send_template_email(
                request,
                notification.user.email,
                subject,
                "mail_immediate_text.j2",
                "mail_immediate_html.j2",
                {
                    "request": request,
                    "notification": notification,
                    "root": root,
                    "subject": subject,
                },
            )
            log.info(
                "notification frequency=immediately user={} ({}), count={}".format(
                    notification.user.name,
                    notification.user_id,
                    notification.id,
                )
            )
            notification.sent = True
            request.dbsession.add(notification)
            request.dbsession.flush()


def group_notifications_by_root(notifications):
    """
    group notifications by root node, where the key is
    the root node and the value is a list of notification objects.
    Skips orphaned notifications (where node_event is None).
    """
    groups = defaultdict(list)
    for notification in notifications:
        if notification.node_event is not None:
            groups[notification.node_event.node.root].append(notification)
        else:
            log.warning(f"Skipping orphaned notification {notification.id} in group_notifications_by_root")
    return groups


def send_digest_notifications(request, notification_dict, frequency="daily"):
    day_or_week = "day" if frequency == "daily" else "week"
    deliver_email_notifications = request.app.get("deliver_email_notifications", True)
    if not deliver_email_notifications:
        return None

    for user_id, notifications in notification_dict.items():
        user = notifications[0].user
        recipient_email = user.email
        notifications_count = len(notifications)
        plural = "" if notifications_count == 1 else "s"
        subject = "{} notification{} over the past {}".format(notifications_count, plural, day_or_week)
        send_template_email(
            request,
            recipient_email,
            subject,
            "mail_digest_text.j2",
            "mail_digest_html.j2",
            {
                "request": request,
                "notifications": notifications,
                "subject": subject,
                "user": user,
                "frequency": frequency,
                "day_or_week": day_or_week,
                "plural": plural,
                "notifications_count": notifications_count,
                "grouped_notifications": group_notifications_by_root(notifications),
            },
        )
        log.info(
            "notification frequency={} user={} ({}), count={}".format(
                frequency,
                user.name,
                user_id,
                notifications_count,
            )
        )
        for notification in notifications:
            notification.sent = True
            request.dbsession.add(notification)
        request.dbsession.flush()
