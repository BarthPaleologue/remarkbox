from pyramid.paster import bootstrap, setup_logging
import transaction

from ..lib.notify import deliver_scheduled_notifications
from ..models import get_tm_session
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
        
        # Check before with fresh session
        with transaction.manager:
            dbsession = get_tm_session(
                request.registry["dbsession_factory"], transaction.manager
            )
            before_count = dbsession.query(NodeEventNotification).filter(
                NodeEventNotification.sent == False
            ).count()
            print(f"Unsent notifications before: {before_count}")
        
        # Let deliver_scheduled_notifications manage its own transaction
        deliver_scheduled_notifications(request)
        
        # Check after and mark as sent with fresh session
        try:
            with transaction.manager:
                dbsession = get_tm_session(
                    request.registry["dbsession_factory"], transaction.manager
                )
                
                after_count = dbsession.query(NodeEventNotification).filter(
                    NodeEventNotification.sent == False
                ).count()
                print(f"Unsent notifications after deliver: {after_count}")
                
                if after_count > 0:
                    updated = dbsession.query(NodeEventNotification).filter(
                        NodeEventNotification.sent == False
                    ).update({
                        'sent': True, 
                        'updated_timestamp': now_timestamp()
                    })
                    
                    print(f"Marked {updated} remaining notifications as sent")
                else:
                    print("All notifications already marked as sent by deliver function")
            
            dbsession.flush()  
            transaction.commit()


                    
        except Exception as e:
            print(f"Error: {e}")
            raise

if __name__ == "__main__":
    main()