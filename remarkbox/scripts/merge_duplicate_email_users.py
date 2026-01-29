"""
Merge duplicate user accounts that have the same email (case-insensitive).

This script finds users with emails that differ only by case (e.g.,
'user@example.com' and 'User@Example.com') and merges them into a single
account, keeping the oldest one.

Usage:
    remarkbox_merge_duplicate_email_users -c production.ini --dry-run
    remarkbox_merge_duplicate_email_users -c production.ini
"""
from collections import defaultdict

from pyramid.paster import bootstrap, setup_logging

from sqlalchemy import func

from ..models import User

from . import base_parser


def get_arg_parser():
    parser = base_parser("Find and merge user accounts with duplicate emails (case-insensitive).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be merged without making changes.",
    )
    return parser


def find_duplicate_email_users(dbsession):
    """
    Find all users with duplicate emails (case-insensitive).

    Returns a dict mapping lowercase email -> list of User objects.
    Only includes emails with more than one user.
    """
    duplicates = defaultdict(list)

    # Get all users
    users = dbsession.query(User).all()

    for user in users:
        email_lower = user.email.lower()
        duplicates[email_lower].append(user)

    # Filter to only duplicates
    return {
        email: users
        for email, users in duplicates.items()
        if len(users) > 1
    }


def merge_users(dbsession, keep_user, delete_user, dry_run=False):
    """
    Merge delete_user into keep_user by transferring all related records.

    Transfers:
    - nodes (comments)
    - votes
    - watchers
    - node_event_notifications
    - namespace_user associations
    - namespace_requests
    - oauth records
    - payments
    - pay_what_you_can
    """
    keep_id = keep_user.id
    delete_id = delete_user.id

    print(f"  Merging '{delete_user.name}' ({delete_user.email}) into '{keep_user.name}' ({keep_user.email})")

    if dry_run:
        # Count records that would be transferred
        from ..models import (
            Node, Vote, Watcher, NodeEventNotification,
            NamespaceUser, NamespaceRequest, Oauth, Payment, PayWhatYouCan
        )

        counts = {
            'nodes': dbsession.query(Node).filter(Node.user_id == delete_id).count(),
            'votes': dbsession.query(Vote).filter(Vote.user_id == delete_id).count(),
            'watchers': dbsession.query(Watcher).filter(Watcher.user_id == delete_id).count(),
            'notifications': dbsession.query(NodeEventNotification).filter(NodeEventNotification.user_id == delete_id).count(),
            'namespace_users': dbsession.query(NamespaceUser).filter(NamespaceUser.user_id == delete_id).count(),
            'namespace_requests': dbsession.query(NamespaceRequest).filter(NamespaceRequest.user_id == delete_id).count(),
            'oauth': dbsession.query(Oauth).filter(Oauth.user_id == delete_id).count(),
            'payments': dbsession.query(Payment).filter(Payment.user_id == delete_id).count(),
            'pay_what_you_can': dbsession.query(PayWhatYouCan).filter(PayWhatYouCan.user_id == delete_id).count(),
        }

        for table, count in counts.items():
            if count > 0:
                print(f"    Would transfer {count} {table}")

        return

    # Transfer all related records
    from ..models import (
        Node, Vote, Watcher, NodeEventNotification,
        NamespaceUser, NamespaceRequest, Oauth, Payment, PayWhatYouCan
    )

    # Update nodes
    updated = dbsession.query(Node).filter(Node.user_id == delete_id).update(
        {Node.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} nodes")

    # Update votes
    updated = dbsession.query(Vote).filter(Vote.user_id == delete_id).update(
        {Vote.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} votes")

    # Update watchers
    updated = dbsession.query(Watcher).filter(Watcher.user_id == delete_id).update(
        {Watcher.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} watchers")

    # Update notifications
    updated = dbsession.query(NodeEventNotification).filter(NodeEventNotification.user_id == delete_id).update(
        {NodeEventNotification.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} notifications")

    # Update namespace_user associations
    updated = dbsession.query(NamespaceUser).filter(NamespaceUser.user_id == delete_id).update(
        {NamespaceUser.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} namespace associations")

    # Update namespace requests
    updated = dbsession.query(NamespaceRequest).filter(NamespaceRequest.user_id == delete_id).update(
        {NamespaceRequest.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} namespace requests")

    # Update oauth records
    updated = dbsession.query(Oauth).filter(Oauth.user_id == delete_id).update(
        {Oauth.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} oauth records")

    # Update payments
    updated = dbsession.query(Payment).filter(Payment.user_id == delete_id).update(
        {Payment.user_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} payments")

    # Update pay_what_you_can (1-to-1, may need special handling)
    existing_pwuc = dbsession.query(PayWhatYouCan).filter(PayWhatYouCan.user_id == keep_id).first()
    delete_pwuc = dbsession.query(PayWhatYouCan).filter(PayWhatYouCan.user_id == delete_id).first()
    if delete_pwuc:
        if existing_pwuc:
            # Keep user already has one, delete the duplicate's
            dbsession.delete(delete_pwuc)
            print(f"    Deleted duplicate pay_what_you_can record")
        else:
            delete_pwuc.user_id = keep_id
            print(f"    Transferred pay_what_you_can record")

    dbsession.flush()

    # Delete the duplicate user
    dbsession.delete(delete_user)
    dbsession.flush()
    print(f"    Deleted user '{delete_user.name}'")


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]
        dbsession = request.dbsession

        print("Searching for duplicate email users (case-insensitive)...")
        duplicates = find_duplicate_email_users(dbsession)

        if not duplicates:
            print("No duplicate email users found.")
            return

        print(f"Found {len(duplicates)} email(s) with duplicate users:\n")

        for email, users in duplicates.items():
            # Sort by created timestamp (oldest first)
            users_sorted = sorted(users, key=lambda u: u.created)
            keep_user = users_sorted[0]
            delete_users = users_sorted[1:]

            print(f"Email: {email}")
            print(f"  Keeping: '{keep_user.name}' (id={keep_user.id}, created={keep_user.created})")

            for delete_user in delete_users:
                print(f"  Deleting: '{delete_user.name}' (id={delete_user.id}, created={delete_user.created})")
                merge_users(dbsession, keep_user, delete_user, dry_run=args.dry_run)

            # Normalize the kept user's email to lowercase
            if keep_user.email != email:
                if args.dry_run:
                    print(f"  Would normalize email from '{keep_user.email}' to '{email}'")
                else:
                    keep_user.email = email
                    dbsession.add(keep_user)
                    dbsession.flush()
                    print(f"  Normalized email to '{email}'")

            print()

        if args.dry_run:
            print("DRY RUN - No changes were made. Run without --dry-run to apply changes.")
        else:
            print("Done. All duplicate users have been merged.")
