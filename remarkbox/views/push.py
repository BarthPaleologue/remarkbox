"""
Web Push notification subscribe/unsubscribe endpoints.
"""

import logging

from pyramid.view import view_config

from remarkbox.lib.push import (
    PUSH_AVAILABLE,
    add_push_subscription,
    remove_push_subscription,
    get_vapid_keys,
)

log = logging.getLogger(__name__)


@view_config(route_name="push-vapid-key", request_method="GET", renderer="json", require_csrf=False)
def get_vapid_public_key(request):
    if not PUSH_AVAILABLE:
        return {"available": False, "reason": "Push libraries not installed"}
    vapid_keys = get_vapid_keys(request.registry.settings)
    if not vapid_keys:
        return {"available": False, "reason": "VAPID keys not configured"}
    return {"available": True, "public_key": vapid_keys["public_key"]}


@view_config(route_name="push-subscribe", request_method="POST", renderer="json", require_csrf=False)
def push_subscribe(request):
    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}
    try:
        body = request.json_body
    except Exception:
        request.response.status_code = 400
        return {"error": "JSON body required"}
    subscription = body.get("subscription")
    if not subscription or not subscription.get("endpoint"):
        request.response.status_code = 400
        return {"error": "subscription with endpoint is required"}
    added = add_push_subscription(request.user, subscription)
    request.dbsession.add(request.user)
    request.dbsession.flush()
    if added:
        log.info("Push subscription added for user=%s", request.user.id)
        return {"status": "subscribed"}
    return {"status": "already_subscribed"}


@view_config(route_name="push-unsubscribe", request_method="POST", renderer="json", require_csrf=False)
def push_unsubscribe(request):
    if not request.user or not request.user.authenticated:
        request.response.status_code = 401
        return {"error": "Authentication required"}
    try:
        body = request.json_body
    except Exception:
        request.response.status_code = 400
        return {"error": "JSON body required"}
    endpoint = body.get("endpoint")
    if not endpoint:
        request.response.status_code = 400
        return {"error": "endpoint is required"}
    removed = remove_push_subscription(request.user, endpoint)
    request.dbsession.add(request.user)
    request.dbsession.flush()
    if removed:
        log.info("Push subscription removed for user=%s", request.user.id)
        return {"status": "unsubscribed"}
    return {"status": "not_found"}
