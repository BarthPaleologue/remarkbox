from pyramid.paster import bootstrap, setup_logging

from ..lib.notify import deliver_scheduled_notifications

from . import base_parser


def get_arg_parser():
    parser = base_parser("Send Node Notification Digests.")
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env:
        deliver_scheduled_notifications(env["request"])
