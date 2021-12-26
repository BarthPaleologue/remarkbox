from pyramid.paster import bootstrap, setup_logging

from ..models import get_namespace_by_name

from . import base_parser


def get_arg_parser():
    parser = base_parser("Modify all uris which fall under namespace.")
    parser.add_argument("namespace")
    parser.add_argument("--add-trailing-slash", action="store_true", default=False)
    parser.add_argument("--https", action="store_true", default=False)
    parser.add_argument("--http", action="store_true", default=False)
    parser.add_argument("--move-namespace-domain")
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]

        namespace = get_namespace_by_name(request.dbsession, args.namespace)
        if namespace is not None:

            for root in namespace.roots:
                if root.uri is None:
                    continue

                # parsed miniuri object.
                puri = root.uri.parsed

                if args.add_trailing_slash and not root.uri.data.endswith("/"):
                    print("adding trailing slash to: {}".format(root.uri.data))
                    puri.path = puri.path + "/"

                if args.move_namespace_domain and "." in args.move_namespace_domain:
                    namespace.name = args.move_namespace_domain
                    puri.hostname = args.move_namespace_domain

                if args.http:
                    puri.scheme = "http"

                if args.https:
                    puri.scheme = "https"

                root.uri.data = puri.uri
                request.dbsession.add(root.uri)

            request.dbsession.flush()
        else:
            print("no such namespace ({})".format(args.namespace))
