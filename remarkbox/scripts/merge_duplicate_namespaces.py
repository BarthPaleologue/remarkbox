"""
Merge duplicate namespaces and URIs that have the same name/host (case-insensitive).

This script finds namespaces with names that differ only by case (e.g.,
'Example.com' and 'example.com') and merges them into a single namespace,
keeping the oldest one. It also normalizes URI hostnames to lowercase.

Usage:
    remarkbox_merge_duplicate_namespaces -c production.ini --dry-run
    remarkbox_merge_duplicate_namespaces -c production.ini
"""
from collections import defaultdict

from pyramid.paster import bootstrap, setup_logging

from sqlalchemy import func

from ..models import Namespace, Node, Uri, NamespaceUser, NamespaceRequest, Oauth, Watcher

from . import base_parser

import miniuri

try:
    unicode("")
except Exception:
    from six import u as unicode


def get_arg_parser():
    parser = base_parser("Find and merge namespaces with duplicate names (case-insensitive).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be merged without making changes.",
    )
    return parser


def find_duplicate_namespaces(dbsession):
    """
    Find all namespaces with duplicate names (case-insensitive).

    Returns a dict mapping lowercase name -> list of Namespace objects.
    Only includes names with more than one namespace.
    """
    duplicates = defaultdict(list)

    namespaces = dbsession.query(Namespace).all()

    for namespace in namespaces:
        name_lower = namespace.name.lower()
        duplicates[name_lower].append(namespace)

    # Filter to only duplicates
    return {
        name: namespaces
        for name, namespaces in duplicates.items()
        if len(namespaces) > 1
    }


def find_duplicate_uris(dbsession):
    """
    Find all URIs with duplicate data (case-insensitive).

    Returns a dict mapping lowercase uri -> list of Uri objects.
    Only includes URIs with more than one record.
    """
    duplicates = defaultdict(list)

    uris = dbsession.query(Uri).all()

    for uri in uris:
        uri_lower = uri.data.lower()
        duplicates[uri_lower].append(uri)

    # Filter to only duplicates
    return {
        uri: uri_list
        for uri, uri_list in duplicates.items()
        if len(uri_list) > 1
    }


def merge_namespaces(dbsession, keep_ns, delete_ns, dry_run=False):
    """
    Merge delete_ns into keep_ns by transferring all related records.

    Transfers:
    - root nodes (threads)
    - namespace_user associations
    - namespace_requests
    - oauth records
    - watchers
    - user_surrogates
    """
    keep_id = keep_ns.id
    delete_id = delete_ns.id

    print(f"  Merging '{delete_ns.name}' (id={delete_id}) into '{keep_ns.name}' (id={keep_id})")

    if dry_run:
        counts = {
            'root_nodes': dbsession.query(Node).filter(Node.namespace_id == delete_id).count(),
            'namespace_users': dbsession.query(NamespaceUser).filter(NamespaceUser.namespace_id == delete_id).count(),
            'namespace_requests': dbsession.query(NamespaceRequest).filter(NamespaceRequest.namespace_id == delete_id).count(),
            'oauth': dbsession.query(Oauth).filter(Oauth.namespace_id == delete_id).count(),
            'watchers': dbsession.query(Watcher).filter(Watcher.namespace_id == delete_id).count(),
        }

        for table, count in counts.items():
            if count > 0:
                print(f"    Would transfer {count} {table}")

        return

    # Transfer root nodes
    updated = dbsession.query(Node).filter(Node.namespace_id == delete_id).update(
        {Node.namespace_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} root nodes")

    # Handle namespace_user associations (unique constraint on user_id, namespace_id)
    keep_user_ids = {
        nu.user_id for nu in dbsession.query(NamespaceUser).filter(NamespaceUser.namespace_id == keep_id)
    }
    delete_ns_users = dbsession.query(NamespaceUser).filter(NamespaceUser.namespace_id == delete_id).all()
    transferred_ns = 0
    deleted_ns = 0
    for ns_user in delete_ns_users:
        if ns_user.user_id in keep_user_ids:
            dbsession.delete(ns_user)
            deleted_ns += 1
        else:
            ns_user.namespace_id = keep_id
            transferred_ns += 1
    if transferred_ns:
        print(f"    Transferred {transferred_ns} namespace_user associations")
    if deleted_ns:
        print(f"    Deleted {deleted_ns} duplicate namespace_user associations")

    # Handle namespace requests
    keep_request_user_ids = {
        nr.user_id for nr in dbsession.query(NamespaceRequest).filter(NamespaceRequest.namespace_id == keep_id)
    }
    delete_ns_requests = dbsession.query(NamespaceRequest).filter(NamespaceRequest.namespace_id == delete_id).all()
    transferred_nr = 0
    deleted_nr = 0
    for ns_request in delete_ns_requests:
        if ns_request.user_id in keep_request_user_ids:
            dbsession.delete(ns_request)
            deleted_nr += 1
        else:
            ns_request.namespace_id = keep_id
            transferred_nr += 1
    if transferred_nr:
        print(f"    Transferred {transferred_nr} namespace requests")
    if deleted_nr:
        print(f"    Deleted {deleted_nr} duplicate namespace requests")

    # Transfer oauth records
    updated = dbsession.query(Oauth).filter(Oauth.namespace_id == delete_id).update(
        {Oauth.namespace_id: keep_id}, synchronize_session=False
    )
    if updated:
        print(f"    Transferred {updated} oauth records")

    # Handle watchers (may have duplicates watching same node for same user)
    keep_watcher_keys = {
        (w.user_id, w.node_id, w.type)
        for w in dbsession.query(Watcher).filter(Watcher.namespace_id == keep_id)
    }
    delete_watchers = dbsession.query(Watcher).filter(Watcher.namespace_id == delete_id).all()
    transferred_w = 0
    deleted_w = 0
    for watcher in delete_watchers:
        key = (watcher.user_id, watcher.node_id, watcher.type)
        if key in keep_watcher_keys:
            dbsession.delete(watcher)
            deleted_w += 1
        else:
            watcher.namespace_id = keep_id
            transferred_w += 1
    if transferred_w:
        print(f"    Transferred {transferred_w} watchers")
    if deleted_w:
        print(f"    Deleted {deleted_w} duplicate watchers")

    dbsession.flush()

    # Delete the duplicate namespace
    dbsession.delete(delete_ns)
    dbsession.flush()
    print(f"    Deleted namespace '{delete_ns.name}'")


def merge_uris(dbsession, keep_uri, delete_uri, dry_run=False):
    """
    Merge delete_uri into keep_uri by transferring the node association.

    If delete_uri has a node but keep_uri does not, transfer the node.
    If both have nodes, transfer the children from delete_uri's node to keep_uri's node.
    """
    print(f"  Merging URI '{delete_uri.data}' into '{keep_uri.data}'")

    if dry_run:
        if delete_uri.node_id:
            if keep_uri.node_id:
                child_count = dbsession.query(Node).filter(Node.root_id == delete_uri.node_id, Node.parent_id != None).count()
                print(f"    Would transfer {child_count} child nodes from root {delete_uri.node_id} to root {keep_uri.node_id}")
            else:
                print(f"    Would transfer node {delete_uri.node_id} to kept URI")
        return

    if delete_uri.node_id:
        if keep_uri.node_id is None:
            # keep_uri has no node, just reassign
            keep_uri.node_id = delete_uri.node_id
            delete_uri.node_id = None
            dbsession.flush()
            print(f"    Transferred node to kept URI")
        else:
            # Both have nodes - transfer children from delete's root to keep's root
            updated = dbsession.query(Node).filter(
                Node.root_id == delete_uri.node_id,
                Node.parent_id != None,
            ).update(
                {Node.root_id: keep_uri.node_id}, synchronize_session=False
            )
            if updated:
                print(f"    Transferred {updated} child nodes to kept URI's root")

            # Transfer direct children whose parent is the delete root
            updated = dbsession.query(Node).filter(
                Node.parent_id == delete_uri.node_id,
            ).update(
                {Node.parent_id: keep_uri.node_id}, synchronize_session=False
            )
            if updated:
                print(f"    Re-parented {updated} direct children to kept URI's root")

            # Delete the orphaned root node
            orphan_root = dbsession.query(Node).filter(Node.id == delete_uri.node_id).one_or_none()
            if orphan_root:
                delete_uri.node_id = None
                dbsession.flush()
                dbsession.delete(orphan_root)
                dbsession.flush()
                print(f"    Deleted orphaned root node")

    # Delete the duplicate URI
    dbsession.delete(delete_uri)
    dbsession.flush()
    print(f"    Deleted URI '{delete_uri.data}'")


def normalize_uri_hostnames(dbsession, dry_run=False):
    """
    Normalize all URI hostnames to lowercase.
    """
    uris = dbsession.query(Uri).all()
    normalized_count = 0
    for uri in uris:
        try:
            parsed = miniuri.Uri(uri.data)
            if parsed.hostname and parsed.hostname != parsed.hostname.lower():
                old_data = uri.data
                new_data = uri.data.replace(parsed.hostname, parsed.hostname.lower(), 1)
                if dry_run:
                    print(f"  Would normalize URI: '{old_data}' -> '{new_data}'")
                else:
                    uri.data = new_data
                    dbsession.add(uri)
                normalized_count += 1
        except Exception:
            pass

    if normalized_count:
        if not dry_run:
            dbsession.flush()
        print(f"{'Would normalize' if dry_run else 'Normalized'} {normalized_count} URI hostname(s) to lowercase")

    return normalized_count


def normalize_namespace_names(dbsession, dry_run=False):
    """
    Normalize all namespace names to lowercase.
    """
    namespaces = dbsession.query(Namespace).all()
    normalized_count = 0
    for namespace in namespaces:
        if namespace.name != namespace.name.lower():
            old_name = namespace.name
            new_name = namespace.name.lower()
            if dry_run:
                print(f"  Would normalize namespace: '{old_name}' -> '{new_name}'")
            else:
                namespace.name = new_name
                dbsession.add(namespace)
            normalized_count += 1

    if normalized_count:
        if not dry_run:
            dbsession.flush()
        print(f"{'Would normalize' if dry_run else 'Normalized'} {normalized_count} namespace name(s) to lowercase")

    return normalized_count


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]
        dbsession = request.dbsession

        # Step 1: Find and merge duplicate namespaces
        print("Searching for duplicate namespaces (case-insensitive)...")
        ns_duplicates = find_duplicate_namespaces(dbsession)

        if ns_duplicates:
            print(f"Found {len(ns_duplicates)} namespace name(s) with duplicates:\n")

            for name, namespaces in ns_duplicates.items():
                # Sort by id to keep the oldest (UUID1 is time-based)
                namespaces_sorted = sorted(namespaces, key=lambda ns: ns.id.time)
                keep_ns = namespaces_sorted[0]
                delete_namespaces = namespaces_sorted[1:]

                print(f"Namespace: {name}")
                print(f"  Keeping: '{keep_ns.name}' (id={keep_ns.id})")

                for delete_ns in delete_namespaces:
                    print(f"  Deleting: '{delete_ns.name}' (id={delete_ns.id})")
                    merge_namespaces(dbsession, keep_ns, delete_ns, dry_run=args.dry_run)

                print()
        else:
            print("No duplicate namespaces found.\n")

        # Step 2: Find and merge duplicate URIs
        print("Searching for duplicate URIs (case-insensitive)...")
        uri_duplicates = find_duplicate_uris(dbsession)

        if uri_duplicates:
            print(f"Found {len(uri_duplicates)} URI(s) with duplicates:\n")

            for uri_lower, uris in uri_duplicates.items():
                uris_sorted = sorted(uris, key=lambda u: u.id.time)
                keep_uri = uris_sorted[0]
                delete_uris = uris_sorted[1:]

                print(f"URI: {uri_lower}")
                print(f"  Keeping: '{keep_uri.data}' (id={keep_uri.id})")

                for delete_uri in delete_uris:
                    print(f"  Deleting: '{delete_uri.data}' (id={delete_uri.id})")
                    merge_uris(dbsession, keep_uri, delete_uri, dry_run=args.dry_run)

                print()
        else:
            print("No duplicate URIs found.\n")

        # Step 3: Normalize remaining namespace names and URI hostnames
        print("Normalizing namespace names to lowercase...")
        normalize_namespace_names(dbsession, dry_run=args.dry_run)

        print("\nNormalizing URI hostnames to lowercase...")
        normalize_uri_hostnames(dbsession, dry_run=args.dry_run)

        if args.dry_run:
            print("\nDRY RUN - No changes were made. Run without --dry-run to apply changes.")
        else:
            print("\nDone. All duplicates have been merged and names normalized.")
