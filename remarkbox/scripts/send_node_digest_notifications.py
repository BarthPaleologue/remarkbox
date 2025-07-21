from pyramid.paster import bootstrap, setup_logging
import transaction

from ..lib.notify import deliver_scheduled_notifications
from ..models.notification import NodeEventNotification
from ..models.meta import now_timestamp

from . import base_parser


def get_arg_parser():
    parser = base_parser("Send Node Notification Digests.")
    return parser


def main():
    parser = get_arg_parser()
    args = parser.parse_args()
    setup_logging(args.config)

    with bootstrap(args.config) as env:
        request = env["request"]
        
        try:
            with request.tm:
                # Check before
                dbsession = request.dbsession
                before_count = dbsession.query(NodeEventNotification).filter(
                    NodeEventNotification.sent == False
                ).count()
                print(f"Unsent notifications before: {before_count}")
                
                deliver_scheduled_notifications(request)
                
                # Check after deliver function
                after_deliver_count = dbsession.query(NodeEventNotification).filter(
                    NodeEventNotification.sent == False
                ).count()
                print(f"Unsent notifications after deliver: {after_deliver_count}")
                
                # Mark remaining as sent
                updated = dbsession.query(NodeEventNotification).filter(
                    NodeEventNotification.sent == False
                ).update({'sent': True, 'updated_timestamp': now_timestamp()})
                print(f"Updated {updated} notifications to sent=True")
                
                # Final check
                final_count = dbsession.query(NodeEventNotification).filter(
                    NodeEventNotification.sent == False
                ).count()
                print(f"Unsent notifications after update: {final_count}")
                
        except Exception as e:
            print(f"Error occurred: {e}")
            transaction.abort()
            raise