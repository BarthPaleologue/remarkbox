from collections import defaultdict

from pyramid.paster import bootstrap, setup_logging

from ..models import get_namespace_by_name, get_nodes_who_share_root

from . import base_parser


def get_arg_parser():
    parser = base_parser("Given a namespace find dupe uri roots and merge them.")
    parser.add_argument("namespace")
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    uris = defaultdict(list)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]

        namespace = get_namespace_by_name(request.dbsession, args.namespace)
        if namespace is not None:

            for root in namespace.roots:
                if root.uri is None:
                    continue
                uris[root.uri.data].append(root)

            for uri, roots in uris.items():
                if len(roots) == 2:
                    for child in roots[0].children:
                        child.parent_id = roots[1].id
                        request.dbsession.add(child)
                    nodes = get_nodes_who_share_root(request.dbsession, roots[0])
                    for node in nodes:
                        node.root_id = roots[1].id
                        request.dbsession.add(node)
                    request.dbsession.flush()
                    request.dbsession.delete(roots[0])
                    request.dbsession.delete(roots[0].uri)
                    request.dbsession.flush()

        else:
            print("no such namespace ({})".format(args.namespace))
