from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound

from remarkbox.models import get_node_by_id

from remarkbox.views import get_referer_or_home, user_required


# TODO: maybe use this when javascript is enabled.
# @view_config(route_name="watch", renderer="json", request_method=("POST", "PUT"), xhr=True)
# otherwise fallback to this when javascript is disabled:
@view_config(route_name="watch", request_method=("POST", "PUT"))
@user_required()
def watch(request):
    root_id = request.params.get("root-id", None)
    if root_id:
        root = get_node_by_id(request.dbsession, root_id)
        if root:
            watcher = request.user.watch_node(root)
            request.session.flash(
                (
                    "You <b>watched</b> this thread. We will notify you of changes <b>{}</b>.".format(
                        watcher.notification_frequency
                    ),
                    "success",
                )
            )
        else:
            request.session.flash(
                ("You <b>may not</b> watch an empty thread.", "error")
            )

    return HTTPFound(get_referer_or_home(request))


# TODO: maybe use this when javascript is enabled.
# @view_config(route_name="watch", renderer="json", request_method=("POST", "PUT"), xhr=True)
# otherwise fallback to this when javascript is disabled:
@view_config(route_name="unwatch", request_method=("POST", "PUT"))
@user_required()
def unwatch(request):
    root_id = request.params.get("root-id", None)
    watcher_id = request.params.get("watcher-id", None)

    if watcher_id:
        watcher = request.user.get_watcher_by_id(watcher_id)
    elif root_id:
        watcher = request.user.get_watcher_by_node_id(root_id)

    if watcher:
        request.dbsession.delete(watcher)
        request.session.flash(
            (
                "You <b>unwatched</b> this thread. We <b>will not notify</b> you of changes.",
                "success",
            )
        )
    return HTTPFound(get_referer_or_home(request))


@view_config(route_name="embed-user-watching", renderer="user-watching.j2")
@view_config(route_name="basic-user-watching", renderer="user-watching.j2")
@user_required()
def watching(request):
    return {"the_title": "Watching"}


@view_config(route_name="update-watching", request_method=("POST", "PUT"))
@user_required()
def update_watching(request):
    changed = False
    watchers = request.user.node_watchers.all() + request.user.namespace_watchers.all()
    for watcher in watchers:
        watcher_dom_id = "watcher-{}".format(watcher.id)
        new_notification_frequency = request.params.get(watcher_dom_id)
        if new_notification_frequency:
            if watcher.notification_frequency == new_notification_frequency:
                continue
            elif new_notification_frequency == "never" and watcher.type == "node":
                request.dbsession.delete(watcher)
            else:
                watcher.notification_frequency = new_notification_frequency
                request.dbsession.add(watcher)
            changed = True

    request.dbsession.flush()

    if changed:
        request.session.flash(
            ("You updated how we notify you of changes.", "success")
        )

    return HTTPFound(get_referer_or_home(request))
