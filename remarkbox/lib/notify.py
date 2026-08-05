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

# Discord renders unicode emoji and markdown; shortcodes stay literal.
DISCORD_MESSAGE = """📬 **{}** added a {} on **{}**:

{}

🔗 {}/r/{}
"""

NODE_EVENT_ACTION_NAMES = {"created": "new thread", "commented": "new comment"}


def build_slack_deliveries(request, node_event):
    """Return ("slack", token, message) tuples, plain strings only."""
    node = node_event.node
    namespace = node.root.namespace
    if not namespace.slack_oauth_records:
        return []
    message = SLACK_MESSAGE.format(
        node.user.name,
        NODE_EVENT_ACTION_NAMES[node_event.action],
        namespace.name,
        node.data,
        request.host_url,
        node.id,
    )
    return [
        ("slack", oauth.token, message, "#remarks")
        for oauth in namespace.slack_oauth_records
    ]


def build_discord_deliveries(request, node_event):
    """Return ("discord", webhook_uri, message) tuples, plain strings only."""
    node = node_event.node
    namespace = node.root.namespace
    if not namespace.discord_oauth_records:
        return []

    excerpt = node.data or ""
    if len(excerpt) > 900:
        excerpt = excerpt[:900] + "…"
    # quote each line of our excerpt with discord markdown.
    excerpt = "\n".join("> " + line for line in excerpt.splitlines()) or "> "

    message = DISCORD_MESSAGE.format(
        node.user.name,
        NODE_EVENT_ACTION_NAMES[node_event.action],
        namespace.name,
        excerpt,
        request.host_url,
        node.id,
    )
    return [
        ("discord", oauth.token, message, None)
        for oauth in namespace.discord_oauth_records
    ]


def deliver_webhook_notifications(deliveries):
    """
    Deliver ("slack"|"discord", target, message, channel) tuples over
    HTTPS. Channel only applies to slack; discord webhooks embed theirs.

    Runs in a background thread — must never raise, and must only touch
    plain strings (no ORM objects, no request).
    """
    from remarkbox.lib.discord import post_webhook_message

    for kind, target, message, channel in deliveries:
        if kind == "slack":
            try:
                Slacker(target).chat.post_message(channel, message)
            except Exception as e:
                # a revoked token or missing channel is not our caller's problem.
                log.warning("slack notification failed: {}".format(e))
        elif kind == "discord":
            # post_webhook_message never raises; failures are logged.
            post_webhook_message(target, message)


def deliver_webhook_notifications_async(deliveries):
    """
    Deliver webhook notifications in a daemon thread so slow or hung
    third parties never block the request that triggered the event.
    """
    if not deliveries:
        return
    import threading

    thread = threading.Thread(
        target=deliver_webhook_notifications, args=(deliveries,), daemon=True
    )
    thread.start()
    return thread


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


def get_mentioned_user_watchers(node):
    """
    Parse @mentions from a node's data and return reply watchers
    for mentioned users who exist.
    """
    from remarkbox.lib.mentions import resolve_mentions

    if not node.data:
        return []

    dbsession = node.dbsession
    if dbsession is None:
        return []

    resolved = resolve_mentions(dbsession, node.data)
    watchers = []
    for user in resolved.values():
        if user.verified:
            # Use the user's reply watcher for mention notifications.
            for w in user.reply_watchers:
                watchers.append(w)
    return watchers


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

    # extend watchers for @mentioned users.
    watchers.extend(get_mentioned_user_watchers(node))

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

    # Slack and Discord notifications currently only support created and
    # commented. Payloads are built here (inside our request, cheap) and
    # delivered in a background thread (slow third-party HTTPS) so a hung
    # webhook never blocks the comment submission.
    if node_event.action in {"created", "commented"}:
        deliveries = build_slack_deliveries(request, node_event)
        deliveries += build_discord_deliveries(request, node_event)
        deliver_webhook_notifications_async(deliveries)

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
    

def _send_push_for_notification(request, notification, root, namespace):
    """Send a push notification for a single notification if the user wants it."""
    from remarkbox.lib.push import PUSH_AVAILABLE, send_push_to_user
    if not PUSH_AVAILABLE:
        return

    user = notification.user
    pref = getattr(user, "notification_preference", "email")
    if pref not in ("push", "both"):
        return

    node = notification.node_event.node
    action = notification.node_event.action
    author = node.user.name if node.user else "Someone"

    action_text = {
        "created": "started a new thread",
        "commented": "posted a reply",
        "approved": "approved a comment",
        "enabled": "enabled a comment",
        "disabled": "disabled a comment",
        "verified": "verified a comment",
    }.get(action, action)

    title = "[{}] new activity".format(namespace.name)
    body = "{} {} on {}".format(author, action_text, root.title or "a thread")
    url = "{}/r/{}".format(request.host_url, node.id)

    payload = {
        "title": title,
        "body": body,
        "url": url,
        "tag": "remarkbox-{}".format(str(notification.id)[:8]),
    }

    send_push_to_user(request, user, payload)


def send_immediate_notifications(request, notifications):
    deliver_email_notifications = request.app.get("deliver_email_notifications", True)

    if len(notifications) == 0:
        return None

    node_event = notifications[0].node_event
    root = node_event.node.root
    namespace = root.namespace

    subject = "[{}] new activity".format(namespace.name)

    for notification in notifications:
        user_pref = getattr(notification.user, "notification_preference", "email")

        # Send email if the user wants email (or both).
        if deliver_email_notifications and notification.method == "email":
            if user_pref in ("email", "both"):
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

        # Send push notification if the user wants push (or both).
        _send_push_for_notification(request, notification, root, namespace)

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
