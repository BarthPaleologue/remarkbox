from pyramid.paster import bootstrap, setup_logging

from remarkbox.models import invalidate_all_node_cache_objects

from . import base_parser


def main():
    parser = base_parser("Recompute denormalized fields and caches.")
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]

        # invalidate all NodeCache objs to force recomputation.
        invalidate_all_node_cache_objects(request.dbsession)

        # get all Uri objects.
        uris = m.uri.get_all_uris(request.dbsession)

        # interate over all Uri objects.
        for uri in uris:

            if uri.node:
                # modify the Uri's related Node.
                uri.node.has_uri = True
                # add the related Node object to the sqlalchemy session.
                request.dbsession.add(uri.node)

        # flush / commit all changes stored the the sqlachemy session.
        request.dbsession.flush()
