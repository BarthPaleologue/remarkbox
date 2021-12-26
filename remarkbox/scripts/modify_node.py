from pyramid.paster import bootstrap, setup_logging

from ..models import get_node_by_uri, get_node_by_id

from . import base_parser

# edit node.
from os import environ
from tempfile import NamedTemporaryFile
from subprocess import call

ANSI_ESCAPES = {
    "HEADER": "\033[95m",
    "OKBLUE": "\033[94m",
    "OKGREEN": "\033[92m",
    "WARNING": "\033[93m",
    "FAIL": "\033[91m",
    "DISABLED": "\033[37m",
    "ENDC": "\033[0m",
    "BOLD": "\033[1m",
    "UNDERLINE": "\033[4m",
}


def ansi(msg, codes=None):
    msg = str(msg)
    if codes:
        for code in codes:
            msg = ANSI_ESCAPES[code] + msg
    msg += ANSI_ESCAPES["ENDC"]
    return msg


def color_node(node):
    # if node.spam:
    #    return ansi(node.id, 'FAIL')
    if node.disabled == True:
        return ansi(node.id, codes=["DISABLED"])
    elif node.verified == False:
        return ansi(node.id, codes=["WARNING"])
    else:
        return ansi(node.id, codes=["OKGREEN"])


def traverse(node):
    """stolen from here: http://www.saltycrane.com/blog/2008/08/python-recursion-example-navigate-tree-data/"""
    print(" " * traverse.level + str(color_node(node)))
    for child in node.children:
        traverse.level += 2
        traverse(child)
        traverse.level -= 2


def edit_node(node):
    EDITOR = environ.get("EDITOR", "vim")
    with NamedTemporaryFile(suffix=".md") as tf:
        tf.write(node.data)
        tf.flush()
        call([EDITOR, tf.name])

        # do the parsing with `tf` using regular File operations.
        # for instance:
        tf.seek(0)
        new_node_data = tf.read()

    if new_node_data and new_node_data != node.data:
        node.data = new_node_data


def info_node(node):
    from collections import OrderedDict

    node_dict = OrderedDict(sorted(node.__dict__.items(), key=lambda t: t[0]))
    for key, value in node_dict.items():
        print("{}: {}".format(key, value))
    if node.uri:
        print(node.uri.data)


def get_arg_parser():
    parser = base_parser("Modify a Node.")
    parser.add_argument("-u", "--uri", type=unicode, default=None)
    parser.add_argument("-i", "--id", type=unicode, default=None)
    parser.add_argument("--show", default=False, action="store_true")
    parser.add_argument("--info", default=False, action="store_true")
    parser.add_argument("--move", default=False, metavar="NEW-PARENT-ID")
    parser.add_argument("--edit", default=False, action="store_true")
    parser.add_argument("--disable", default=False, action="store_true")
    parser.add_argument("--enable", default=False, action="store_true")
    parser.add_argument("--delete", default=False, action="store_true")
    parser.add_argument("--spam", default=False, action="store_true")
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    if args.uri and args.id:
        print("do not pass both -u and -i flags.")
        exit(1)

    action_flag_count = sum(
        [
            args.show,
            args.info,
            bool(args.move),
            args.disable,
            args.enable,
            args.spam,
            args.delete,
            args.edit,
        ]
    )
    if action_flag_count != 1:
        if action_flag_count == 0:
            parser.print_help()
        else:
            print("only pass one action flag.")
        exit(1)

    with bootstrap(args.config) as env, env["request"].tm as tm:
        request = env["request"]

        node = None
        if args.uri is not None:
            node = get_node_by_uri(request.dbsession, args.uri)

        elif args.id is not None:
            node = get_node_by_id(request.dbsession, args.id)

        if node is None:
            print("No such, node. Check the id or uri.")
            exit(1)

        if args.show:
            traverse.level = 1
            traverse(node)

        if args.info:
            info_node(node)

        if args.delete:
            if (
                raw_input("Delete node '{}' forever? [yes, no]: ".format(node.id))
                == "yes"
            ):
                request.dbsession.delete(node)
                request.dbsession.flush()
        else:

            if args.move:
                parent = get_node_by_id(request.dbsession, args.move)
                if parent is None:
                    print(
                        "The new parent id ({}) does not exist.".format(args.new_parent)
                    )
                    exit(0)
                node.parent_id = parent.id
                node.root_id = parent.id
                node.namespace = parent.namespace
                if node.title:
                    node.title = ""

            if args.edit:
                edit_node(node)

            if args.disable:
                node.disable()

            if args.enable:
                node.enable()

        request.dbsession.add(node)
        request.dbsession.flush()
