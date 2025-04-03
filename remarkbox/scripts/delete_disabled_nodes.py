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

def delete_disabled_nodes(request):
    """
    Delete disabled parent nodes and anonymize their children in one pass.
    
    This function:
    1. Queries for all disabled nodes
    2. Anonymizes all children of disabled nodes
    3. Deletes disabled parent nodes (nodes with no children)
    4. Verifies the deletion was successful
    
    Args:
        request: Pyramid request object with transaction manager
        
    Returns:
        bool: True if successful, False on error
    """
    try:
        # Use the request's transaction-managed session instead of creating a new one
        dbsession = get_tm_session(request.registry['dbsession_factory'], transaction.manager)
        
        # Query disabled nodes
        disabled_nodes = dbsession.query(Node).filter(Node.disabled == True).all()
        print(f"Found {len(disabled_nodes)} disabled nodes.")
        
        deleted_count = 0
        anonymized_count = 0
        already_anonymized_count = 0
        
        # Process all nodes in one pass
        for node in disabled_nodes:
            # Get all children (actual objects, not just count)
            children = dbsession.query(Node).filter(Node.parent_id == node.id).all()
            
            if children:
            
                
                # Anonymize each child
                for child in children:
                    #check if child is already anonymized
                    if (child.title == 'deleted' or child.title is None) and \
                       child.data == 'deleted' and \
                       child.data_html == 'deleted':
                        already_anonymized_count += 1
                        continue

                    child.title = 'deleted' if child.title else None
                    child.data = 'deleted'
                    child.data_html = 'deleted'
                    child.ip_address = None
                    child.user_id = None
                    child.user_surrogate_id = None
                    child.changed = now_timestamp()
                    child.disabled_timestamp = now_timestamp()
                    
                    # Process related objects for the child
                    # Anonymize Events
                    events = dbsession.query(NodeEvent).filter(NodeEvent.node_id == child.id).all()
                    for event in events:
                        event.user_id = None

                    # Anonymize Votes
                    votes = dbsession.query(Vote).filter(Vote.node_id == child.id).all()
                    for vote in votes:
                        vote.user_id = None

                    # Anonymize Watchers
                    watchers = dbsession.query(Watcher).filter(Watcher.node_id == child.id).all()
                    for watcher in watchers:
                        notifications = dbsession.query(NodeEventNotification).filter(
                            NodeEventNotification.watcher_id == watcher.id
                        ).all()
                        for notification in notifications:
                            notification.user_id = None
                    
                    # Anonymize optional related objects
                    if child.uri:
                        child.uri.data = 'deleted'
                        child.has_uri = False

                    if child.cache:
                        child.cache.stats = {}
                        child.cache.invalidate()

                    print(f"Anonymized child node {child.id} of disabled parent {node.id}")
                    anonymized_count += 1
            else:
                # Delete node with no children (parent node)
                dbsession.query(NodeEvent).filter(NodeEvent.node_id == node.id).delete()
                dbsession.query(Vote).filter(Vote.node_id == node.id).delete()
                dbsession.query(Watcher).filter(Watcher.node_id == node.id).delete()
                
                if node.cache:
                    dbsession.delete(node.cache)
                
                if node.uri:
                    dbsession.delete(node.uri)
                
                #delete the node
                dbsession.delete(node)
                print(f"Deleted parent node {node.id}")
                deleted_count += 1
        
        # Check remaining disabled parent nodes using a subquery
        subquery = select(Node.id).where(
            Node.parent_id.in_(
                select(Node.id).where(Node.disabled == True)
            )
        ).subquery()
        remaining_disabled_parent_nodes = dbsession.query(Node).filter(
            Node.disabled == True,
            ~Node.id.in_(subquery.select())  
        ).count()

        

        active_nodes_count = dbsession.query(Node).filter(Node.disabled == False).count()

        print(f"Summary: Deleted {deleted_count} parent nodes, anonymized {anonymized_count} child nodes. ")

        print(f"Total Nodes previously anonymized: {already_anonymized_count}.")

        
        

        if remaining_disabled_parent_nodes > 0:
            print(f"Warning: {remaining_disabled_parent_nodes} disabled leaf nodes remain ")
        
        print(f"Total active nodes: {active_nodes_count}, Remaining disabled leaf nodes: {remaining_disabled_parent_nodes}")
        
        return True
        
        
    except Exception as e:
        print(f"An error occurred: {e}")
        dbsession.rollback()
        return False

def main():

    """
    Main entry point for the script.
    
    This function:
    1. Sets up Pyramid environment
    2. Configures logging
    3. Manages transaction scope
    4. Handles script execution and exit status
    """
    parser = base_parser("Delete disabled parent nodes and anonymize their children in one pass.")
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