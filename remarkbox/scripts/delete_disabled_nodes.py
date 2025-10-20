#!/usr/bin/env python3

import transaction
import logging
from pyramid.paster import bootstrap, setup_logging
from ..models import Node, get_tm_session, now_timestamp
from ..models.notification import NodeEventNotification

from . import base_parser

log = logging.getLogger(__name__)


def is_node_anonymized(node):
    """
    Check if a node has already been anonymized based on its attributes.

    Args:
        node: Node object to check

    Returns:
        bool: True if already anonymized, False otherwise
    """
    # Check if all identifying attributes are cleared
    return (
        (node.title == "deleted" or node.title is None)
        and node.data == "deleted"
        and node.data_html == "deleted"
        and node.ip_address is None
    )


def cleanup_orphaned_notifications(dbsession):
    """
    Clean up any existing orphaned NodeEventNotification records.
    
    Args:
        dbsession: Database session
        
    Returns:
        int: Number of orphaned notifications cleaned up
    """
    # Find notifications with null node_event references
    orphaned = (
        dbsession.query(NodeEventNotification)
        .filter(NodeEventNotification.node_event_id.is_(None))
        .all()
    )
    
    count = len(orphaned)
    if count > 0:
        print(f"Found {count} orphaned notifications, cleaning them up...")
        for notification in orphaned:
            dbsession.delete(notification)
        print(f"Cleaned up {count} orphaned notifications")
    else:
        print("No orphaned notifications found")
    
    return count


def delete_disabled_nodes(request):
    """
    Delete disabled leaf nodes and anonymize disabled parent nodes while preserving children.
    Skips re-anonymizing already anonymized parent nodes.
    Also cleans up any existing orphaned notifications.

    Args:
        request: Pyramid request object with transaction manager

    Returns:
        bool: True if successful, False on error
    """
    try:
        # Get database session with transaction manager
        dbsession = get_tm_session(
            request.registry["dbsession_factory"], transaction.manager
        )

        # First, clean up any existing orphaned notifications
        print("Checking for orphaned notifications...")
        orphaned_count = cleanup_orphaned_notifications(dbsession)

        # Fetch all disabled nodes in one query
        disabled_nodes = dbsession.query(Node).filter(Node.disabled == True).all()
        print(f"Found {len(disabled_nodes)} disabled nodes.")

        # Initialize counters for reporting
        deleted_count = 0
        anonymized_count = 0
        skipped_count = 0

        # Process each disabled node
        for node in disabled_nodes:
            # Check if node has children using relationship count
            has_children = node.children.count() > 0

            if has_children:
                # Skip if node is already anonymized
                if is_node_anonymized(node):
                    print(
                        f"Skipped already anonymized parent node {node.id} with {node.children.count()} children"
                    )
                    skipped_count += 1
                    continue

                # Anonymize parent node while preserving children
                node.title = "deleted" if node.title else None
                node.data = "deleted"
                node.data_html = "deleted"
                node.ip_address = None
                node.changed = now_timestamp()

                # Clean up URI if it exists
                if node.has_uri and node.uri:
                    node.uri.data = "deleted"
                    node.has_uri = False

                # Clear cache if it exists
                if node.cache:
                    node.cache.stats = {}
                    node.cache.invalidate()

                print(
                    f"Anonymized parent node {node.id} with {node.children.count()} children"
                )
                anonymized_count += 1
            else:
                # Delete leaf node and its related data
                # Handle events deletion and cleanup associated notifications
                for event in node.events:
                    # Delete all notifications associated with this event
                    notifications = dbsession.query(NodeEventNotification).filter(
                        NodeEventNotification.node_event_id == event.id
                    ).all()
                    for notification in notifications:
                        dbsession.delete(notification)
                    
                    # Delete the event itself
                    dbsession.delete(event)

                # Handle watchers deletion with a loop
                for watcher in node.watchers:
                    dbsession.delete(watcher)

                # Delete cache if it exists
                if node.cache:
                    dbsession.delete(node.cache)

                # Delete URI if it exists
                if node.has_uri and node.uri:
                    dbsession.delete(node.uri)

                # Delete the node itself
                dbsession.delete(node)
                print(f"Deleted leaf node {node.id}")
                deleted_count += 1

        # Verify results
        remaining_disabled_nodes = (
            dbsession.query(Node).filter(Node.disabled == True).count()
        )
        active_nodes_count = (
            dbsession.query(Node).filter(Node.disabled == False).count()
        )

        # Print summary of operations
        print(
            f"Summary: Cleaned up {orphaned_count} orphaned notifications, deleted {deleted_count} leaf nodes, anonymized {anonymized_count} parent nodes with children, skipped {skipped_count} already anonymized nodes"
        )

        if remaining_disabled_nodes > 0:
            print(
                f"Note: {remaining_disabled_nodes} disabled nodes remain (all have children)"
            )

        print(
            f"Total active nodes: {active_nodes_count}, Remaining disabled nodes: {remaining_disabled_nodes}"
        )

        return True

    except Exception as e:
        # Handle any errors and rollback transaction
        print(f"An error occurred: {e}")
        dbsession.rollback()
        return False


def main():
    """
    Main entry point for the script to handle command-line execution.
    """
    # Set up argument parser with description
    parser = base_parser(
        "Delete disabled leaf nodes, anonymize disabled parent nodes with children, and clean up orphaned notifications."
    )
    args = parser.parse_args()

    # Configure logging from config file
    setup_logging(args.config)

    # Bootstrap Pyramid environment and process nodes
    with bootstrap(args.config) as env:
        request = env["request"]
        with request.tm:
            success = delete_disabled_nodes(request)
            if success:
                print("Committing transaction.")
                transaction.commit()
                raise SystemExit(0)
            else:
                print("Aborting transaction.")
                transaction.abort()
                raise SystemExit(1)


if __name__ == "__main__":
    main()
