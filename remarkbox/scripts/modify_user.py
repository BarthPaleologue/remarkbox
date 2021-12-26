from pyramid.paster import bootstrap, setup_logging

from ..models import (
    get_user_by_email,
    get_namespace_by_name,
    get_namespace_request,
    is_user_name_valid,
    is_user_name_available,
)

from . import base_parser

from six import u as unicode


def get_arg_parser():
    parser = base_parser("Modify a user.")
    parser.add_argument("-i", "--info", action="store_true", default=False)
    parser.add_argument("email", type=unicode)
    parser.add_argument("--namespace-remove", default=None, type=unicode)
    parser.add_argument("--namespace-add", default=None, type=unicode)
    parser.add_argument(
        "--namespace-role", default=None, type=unicode, choices=[None, "owner"]
    )
    parser.add_argument("--change-user-name", type=unicode)
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]

        user = get_user_by_email(request.dbsession, args.email)

        if user is None:
            print("No such user found by email: {}.".format(args.email))
            exit()

        if args.info:
            from collections import OrderedDict

            user_dict = OrderedDict(sorted(user.__dict__.items(), key=lambda t: t[0]))
            del user_dict["password"]
            del user_dict["email_id"]
            for key, value in user_dict.items():
                print("{}: {}".format(key, value))

            print("namespaces:")
            for namespace in user.namespaces:
                print(" - {}".format(namespace.name))
            exit()

        if args.namespace_add:
            namespace_to_add = get_namespace_by_name(
                request.dbsession, args.namespace_add
            )
            if namespace_to_add:
                namespace_to_add.set_role_for_user(user, role=args.namespace_role)
        if args.namespace_remove:
            namespace_to_remove = get_namespace_by_name(
                request.dbsession, args.namespace_remove
            )
            if namespace_to_remove:
                namespace_request_to_remove = get_namespace_request(
                    request.dbsession, user, namespace_to_remove
                )
                if namespace_request_to_remove:
                    request.dbsession.delete(namespace_request_to_remove)
                namespace_to_remove.clear_owner_request_timestamp()
                namespace_to_remove.remove_user(user)

        if args.change_user_name:
            if is_user_name_valid(args.change_user_name) and is_user_name_available(
                request.dbsession, args.change_user_name
            ):
                user.name = args.change_user_name

        request.dbsession.add(user)
        request.dbsession.flush()
