from pyramid.paster import bootstrap, setup_logging

from ..models import get_root_nodes, get_nodes_who_share_root

from . import base_parser


def main():
    parser = base_parser(
        "Safely approve all nodes, permitting namespace settings allow."
    )
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]
        for root in get_root_nodes(request.dbsession):
            if root.namespace is None:
                # skip this root, it's namespace is None?
                continue
            if root.namespace.hide_unless_approved:
                # skip this root, it's namespace is actively moderated!
                continue
            root.approved = True
            request.dbsession.add(root)
            for node in get_nodes_who_share_root(request.dbsession, root):
                node.approved = True
                request.dbsession.add(node)
        request.dbsession.flush()
