from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound
from pyramid.response import Response

from remarkbox.models import get_node_by_id

from remarkbox.views import get_referer_or_home, user_required

import logging

log = logging.getLogger(__name__)


@view_config(route_name="lock", request_method=("POST", "PUT"))
@user_required()
def lock(request):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    root_id = request.params.get("root-id", None)
    root = get_node_by_id(request.dbsession, root_id)

    if not root:
        if is_ajax:
            return Response(json={"ok": False, "error": "Thread does not exist."}, status=404)
        request.session.flash(
            (
                "Thread does not exist (root-id={}).".format(root_id),
                "error",
            )
        )
    elif root.namespace.is_moderator(request.user):
        root.locked = True
        request.dbsession.add(root)
        request.dbsession.flush()
        if is_ajax:
            return Response(json={"ok": True, "action": "locked"}, status=200)
        request.session.flash(
            (
                "You <b>locked</b> this thread to prevent new comments.",
                "success",
            )
        )
        log.info(
            "event={} user={} root={} namespace={}".format(
                "locked-thread",
                request.user.id,
                root.id,
                root.namespace.id,
            )
        )
    else:
        if is_ajax:
            return Response(json={"ok": False, "error": "Namespace moderator role needed."}, status=403)
        request.session.flash(
            (
                "You may <ul>not</ul> lock this thread. Namespace moderator role needed. ({}).".format(root.namespace.name),
                "error",
            )
        )

    return HTTPFound(get_referer_or_home(request))


@view_config(route_name="unlock", request_method=("POST", "PUT"))
@user_required()
def unlock(request):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    root_id = request.params.get("root-id", None)
    root = get_node_by_id(request.dbsession, root_id)

    if not root:
        if is_ajax:
            return Response(json={"ok": False, "error": "Thread does not exist."}, status=404)
        request.session.flash(
            (
                "Thread does not exist (root-id={}).".format(root_id),
                "error",
            )
        )
    elif root.namespace.is_moderator(request.user):
        root.locked = False
        request.dbsession.add(root)
        request.dbsession.flush()
        if is_ajax:
            return Response(json={"ok": True, "action": "unlocked"}, status=200)
        request.session.flash(
            (
                "You <b>unlocked</b> this thread to allow new comments.",
                "success",
            )
        )
        log.info(
            "event={} user={} root={} namespace={}".format(
                "unlocked-thread",
                request.user.id,
                root.id,
                root.namespace.id,
            )
        )
    else:
        if is_ajax:
            return Response(json={"ok": False, "error": "Namespace moderator role needed."}, status=403)
        request.session.flash(
            (
                "You may <ul>not</ul> unlock this thread. Namespace moderator role needed. ({}).".format(root.namespace.name),
                "error",
            )
        )

    return HTTPFound(get_referer_or_home(request))
