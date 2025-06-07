from pyramid.paster import bootstrap, setup_logging
from ..lib.notify import deliver_scheduled_notifications
from . import base_parser
import transaction



def get_arg_parser():
    parser = base_parser(" Send Node Notification Digests.")
    return parser

def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env:
        request = env["request"]
        with request.tm:
            try:
                deliver_scheduled_notifications(request) 
                print("Notifications processed successfully.")
                transaction.commit()
                raise SystemExit(0)
            except Exception as e:
                print("Error processing notifications:", str(e))
                transaction.abort()
                raise SystemExit(1)
    
if __name__ == "__main__":
    main()
