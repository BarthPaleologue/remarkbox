#!/usr/bin/env python3

import transaction
import logging
from . import base_parser
from pyramid.paster import bootstrap, setup_logging
from sqlalchemy import select
from ..models import Node, get_session_factory, get_tm_session
from ..models.vote import Vote
from ..models.watcher import Watcher
from ..models.event import NodeEvent
from ..models.notification import NodeEventNotification
from ..models.uri import Uri
from ..models.meta import now_timestamp

log = logging.getLogger(__name__)

def is_node_anonymized(node):
    """
    Check if a node has already been anonymized based on its attributes.
    
    Args:
        node: Node object to check
        
    Returns:
        bool: True if already anonymized, False otherwise
    """
    return (
        (node.title == 'deleted' or node.title is None) and
        node.data == 'deleted' and
        node.data_html == 'deleted' and
        node.user_id is None and
        node.user_surrogate_id is None and
        node.ip_address is None
    )

def delete_disabled_nodes(request):
    """
    Delete disabled leaf nodes and anonymize disabled parent nodes while leaving children intact.
    Skips re-anonymizing already anonymized parent nodes.
    
    This function:
    1. Queries for all disabled nodes
    2. Deletes disabled nodes without children
    3. Anonymizes disabled nodes with children leaving children intact (if not already anonymized)
    4. Verifies the deletion/anonymization was successful
    
    Args:
        request: Pyramid request object with transaction manager
        
    Returns:
        bool: True if successful, False on error
    """
    try:
        dbsession = get_tm_session(request.registry['dbsession_factory'], transaction.manager)
        
        # Query disabled nodes using the Node model's properties
        disabled_nodes = dbsession.query(Node).filter(Node.disabled == True).all()
        print(f"Found {len(disabled_nodes)} disabled nodes.")
        
        deleted_count = 0
        anonymized_count = 0
        skipped_count = 0
        
        # Process all nodes in one pass
        for node in disabled_nodes:
            # Use the children relationship from Node model
            children_query = node.children
            has_children = children_query.count() > 0
            
            if has_children:
                # Check if node is already anonymized
                if is_node_anonymized(node):
                    print(f"Skipped already anonymized parent node {node.id} with {children_query.count()} children")
                    skipped_count += 1
                    continue
                
                # Anonymize parent node with children, leave children intact
                node.title = 'deleted' if node.title else None
                node.data = 'deleted'
                node.data_html = 'deleted'
                node.ip_address = None
                node.user_id = None
                node.user_surrogate_id = None
                node.events = None
                node.user = None
                node.watchers = None
                node.cache = None
                node.changed = now_timestamp()
                
                # Clean up related objects using relationship properties
                if node.has_uri and node.uri:
                    node.uri.data = 'deleted'
                    node.has_uri = False
                    
                if node.cache:
                    node.cache.stats = {}
                    node.cache.invalidate()
                
                print(f"Anonymized parent node {node.id} with {children_query.count()} children")
                anonymized_count += 1
            else:
                # Delete disabled node with no children
                node.events.delete()
                dbsession.query(Vote).filter(Vote.node_id == node.id).delete()
                watchers = node.watchers
                for watcher in watchers:
                    dbsession.query(NodeEventNotification).filter(
                        NodeEventNotification.watcher_id == watcher.id
                    ).delete()
                watchers.delete()
                
                if node.cache:
                    dbsession.delete(node.cache)
                
                if node.has_uri and node.uri:
                    dbsession.delete(node.uri.ConcurrentModificationException)
                
                dbsession.delete(node)
                print(f"Deleted leaf node {node.id}")
                deleted_count += 1
        
        # Verify using Node model queries
        remaining_disabled_nodes = dbsession.query(Node).filter(Node.disabled == True).count()
        active_nodes_count = dbsession.query(Node).filter(Node.disabled == False).count()

        print(f"Summary: Deleted {deleted_count} leaf nodes, anonymized {anonymized_count} parent nodes with children, skipped {skipped_count} already anonymized nodes")
        
        if remaining_disabled_nodes > 0:
            print(f"Note: {remaining_disabled_nodes} disabled nodes remain (all have children)")
        
        print(f"Total active nodes: {active_nodes_count}, Remaining disabled nodes: {remaining_disabled_nodes}")

        return True
        
    except Exception as e:
        print(f"An error occurred: {e}")
        dbsession.rollback()
        return False

def main():
    """
    Main entry point for the script.
    """
    parser = base_parser("Delete disabled leaf nodes and anonymize disabled parent nodes with children.")
    args = parser.parse_args()
    setup_logging(args.config)
    
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