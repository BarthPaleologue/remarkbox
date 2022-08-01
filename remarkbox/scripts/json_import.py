import json

from pyramid.paster import bootstrap, setup_logging

from ..models import (
    User,
    UserSurrogate,
    generate_user_name,
    get_user_by_email,
    get_user_surrogate_by_name,
    get_or_create_node_by_uri,
    is_user_name_valid,
    is_user_name_available,
)

from . import base_parser

try:
    unicode("")
except:
    from six import u as unicode


def generate_password(size=32):
    """Return a system generated password"""
    from random import choice
    letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = "0123456789"
    pool = letters + digits
    return "".join([choice(pool) for i in range(size)])


def get_arg_parser():
    parser = base_parser("import comments from JSON")
    # parser.add_argument('--dry-run', action='store_true', default=False)
    parser.add_argument('--user-surrogates', action='store_true', default=False)
    parser.add_argument("--group")
    parser.add_argument("json_path", help="path to JSON file")
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    # group = generate_password(3)
    group = ""
    if args.group:
        group = args.group

    with open(args.json_path) as f:
        pages = json.load(f)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]

        users = {}
        user_surrogates = {}
        nodes = {}

        for slug, page_data in pages.items():

            comments = page_data["comments"]

            if len(comments) == 0:
                # skipping because this page has no comments.
                continue

            uri = page_data["link"]

            print("creating page for {}".format(uri))
            root = get_or_create_node_by_uri(request.dbsession, uri)
            request.dbsession.add(root)
            request.dbsession.flush()

            for comment in comments:

                email = comment["email"]

                user = None
                user_surrogate = None

                if not email:
                    if args.user_surrogates:
                        name = comment["author"]
                        if name not in user_surrogates:
                            user_surrogates[name] = UserSurrogate(
                                name,
                                root.namespace,
                            )
                        user_surrogate = user_surrogates[name]
                        request.dbsession.add(user_surrogate)
                        request.dbsession.flush()
                    else:
                        # an email may not be empty or None.
                        continue

                elif email in users:
                    user = users[email]
                else:
                    user = get_user_by_email(request.dbsession, email)
                    if user:
                        users[email] = user
                        print("found user for {} ({})".format(email, user.name))
                    else:
                        desired_name = (
                            comment["author"].replace(" ", "-").replace("_", "-")
                        )
                        if group:
                            desired_name = desired_name + "-" + group
                        if not is_user_name_valid(
                            desired_name
                        ) or not is_user_name_available(
                            request.dbsession, desired_name
                        ):
                            desired_name = generate_user_name(
                                request.dbsession, desired_name
                            )
                        user = User(email)
                        user.name = unicode(desired_name)
                        users[email] = user
                        print("created user for {} ({})".format(email, desired_name))

                        request.dbsession.add(user)
                        request.dbsession.flush()


                node = root.new_child()
                node.set_data(unicode(comment["content"]))
                node.created = int(comment["timestamp"]) * 1000
                node.changed = int(comment["timestamp"]) * 1000

                if user is not None:
                    node.user = user
                elif user_surrogate is not None:
                    node.user_surrogate = user_surrogate

                node.verified = True
                node.ip_address = comment.get("author_ip", None)
                nodes[comment["id"]] = node

                request.dbsession.add(nodes[comment["id"]])
                request.dbsession.flush()

            for comment in comments:
                if comment["parent_id"]:
                    print(
                        "id {}, parent_id {}".format(
                            comment["id"], comment["parent_id"]
                        )
                    )
                    if nodes.get(comment["parent_id"]):
                        nodes[comment["id"]].parent_id = nodes[comment["parent_id"]].id
                        request.dbsession.add(nodes[comment["id"]])
                        request.dbsession.flush()
                    else:
                        print(
                            "parent_id ({}) is not found, skipping".format(
                                comment["parent_id"]
                            )
                        )
