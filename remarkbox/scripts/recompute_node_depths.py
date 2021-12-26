from pyramid.paster import bootstrap, setup_logging

from remarkbox.models import recompute_depth_on_all_node_objects

from . import base_parser


def main():
    parser = base_parser(
        "Recompute nested node.depth in relation their thread."
    )
    parser.add_argument("--chunk", type=int, default=500,)
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]

        # Run node.recompute_depth() on all Node objects.
        # Flush all changes stored in the sqlalchemy session to database.
        recompute_depth_on_all_node_objects(request.dbsession, args.chunk)
