from pyramid.view import view_config

from remarkbox.views import user_required

from remarkbox.models.notification import NodeEventNotification


@view_config(route_name="basic-user-notifications", renderer="list-notifications.j2")
@view_config(route_name="embed-user-notifications", renderer="list-notifications.j2")
@user_required()
def user_notifications(request):
    if "all" in request.params: 
        state = "all"
        notifications = request.user.node_notifications
    elif "sent" in request.params: 
        state = "sent"
        notifications = request.user.sent_node_notifications
    else:
        state = "unsent"
        notifications = request.user.unsent_node_notifications

    paginated_notifications = (
        notifications
            .order_by(
                NodeEventNotification.created_timestamp.desc(),
                NodeEventNotification.user_id,
            )
            .offset(request.page_offset)
            .limit(request.page_size)
    )

    notification_counts = {
        "all": request.user.node_notifications.count(),
        "sent": request.user.sent_node_notifications.count(),
        "unsent": request.user.unsent_node_notifications.count(),
    }

    return {
        "notifications": paginated_notifications,
        "the_title": "Notifications",
        "topsecret": False,
        "state": state,
        "counts": notification_counts,
    }
