from __future__ import print_function

from pyramid.paster import bootstrap, setup_logging

from ..models import get_or_create_namespace, get_namespace_by_name, get_nodes_who_share_roots

from ..models.meta import SUBSCRIPTION_TYPES

from . import base_parser


toggle = lambda x: not x


def get_arg_parser():
    parser = base_parser("Modify a Namespace.")
    parser.add_argument(
        "--toggle-hide-unless-approved", action="store_true", default=False
    )
    parser.add_argument("--create", action="store_true", default=False)
    parser.add_argument("--delete", action="store_true", default=False)
    parser.add_argument("--delete-children-nodes", action="store_true", default=False, help="this is useful if you mess up an import.")
    parser.add_argument("--info", action="store_true", default=False)
    parser.add_argument("--subscription-type", choices=SUBSCRIPTION_TYPES)
    parser.add_argument("namespace")
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        sp = tm.savepoint()
        request = env["request"]

        if args.create:
            namespace = get_or_create_namespace(request.dbsession, args.namespace)
            request.dbsession.add(namespace)
            request.dbsession.flush()
        else:
            namespace = get_namespace_by_name(request.dbsession, args.namespace)

        if not namespace:
            print("Namespace '{}' not found.".format(args.namespace))
            exit()

        if args.info:
            from collections import OrderedDict

            namespace_dict = OrderedDict(
                sorted(namespace.__dict__.items(), key=lambda t: t[0])
            )
            for key, value in namespace_dict.items():
                print("{}: ".format(key), end="")
                print(value)

            print("owners:")
            for user in namespace.owners:
                print("  {}: {}".format(user.name, user.email))

            print("moderators:")
            for user in namespace.moderators:
                print("  {}: {}".format(user.name, user.email))

            exit()

        elif args.subscription_type:
            namespace.subscription_type = args.subscription_type
            request.dbsession.add(namespace)
            request.dbsession.flush()

        elif args.toggle_hide_unless_approved:
            namespace.hide_unless_approved = toggle(namespace.hide_unless_approved)
            request.dbsession.add(namespace)
            request.dbsession.flush()

        elif args.delete_children_nodes:
            nodes = get_nodes_who_share_roots(request.dbsession, namespace.roots)

            # delete all children nodes.
            for node in nodes:
                if node.is_root:
                    # Skip root nodes to keep Uri and Watchers relations.
                    continue
                request.dbsession.delete(node)

            if (
                raw_input("*** DANGER: Really delete Nodes forever? [yes, no]: ")
                == "yes"
            ):
                request.dbsession.flush()
                print("Flushed transaction to database, the Nodes were completely destroyed!")
            else:
                sp.rollback()
                print("Rolled back transaction, sheepishly refused to delete anything!")

        elif args.delete:

            nodes = get_nodes_who_share_roots(request.dbsession, namespace.roots)

            # delete all nodes.
            for node in nodes:
                if node.events:
                    # delete all related NodeEvents.
                    for event in node.events:
                        request.dbsession.delete(event)

                # delete node.
                request.dbsession.delete(node)

            for root in namespace.roots:
                if root.uri:
                    # delete related Uri.
                    request.dbsession.delete(root.uri)
                if root.cache:
                    # delete related NodeCache.
                    request.dbsession.delete(root.cache)
                if root.watchers:
                    # delete all related NodeEventWatchers.
                    for watcher in root.watchers:
                        # delete all unsent NodeEventNotifications.
                        if watcher.unsent_notifications():
                            for notification in watcher.unsent_notifications():
                                request.dbsession.delete(notification)
                        request.dbsession.delete(watcher)

            if namespace.watchers:
               for watcher in namespace.watchers:
                   # delete all unsent NodeEventNotifications.
                   if watcher.unsent_notifications():
                       for notification in watcher.unsent_notifications():
                           request.dbsession.delete(notification)
                   request.dbsession.delete(watcher)

            # disable all related NamespaceUser objects.
            if namespace.namespace_users:
                for nsu in namespace.namespace_users:
                    # delete related NamespaceUser.
                   request.dbsession.delete(nsu)

            # delete all related OauthRecords.
            if namespace.oauth_records:
                for oauth_record in namespace.oauth_records:
                    request.dbsession.delete(oauth_record)

            # finally delete Namespace.
            request.dbsession.delete(namespace)

            if (
                raw_input("*** DANGER: Delete Namespace '{}' ({}) forever? [yes, no]: ".format(namespace.name, namespace.id))
                == "yes"
            ):
                request.dbsession.flush()
                print("Flushed transaction to database, the Namespace was completely destroyed!")
            else:
                sp.rollback()
                print("Rolled back transaction, sheepishly refused to delete anything!")
