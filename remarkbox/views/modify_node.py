from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound

from . import get_referer_or_home, get_node_route_uri, get_embed_route_uri


@view_config(route_name="embed-edit", renderer="edit-node.j2")
@view_config(route_name="basic-edit", renderer="edit-node.j2")
@view_config(route_name="basic-edit2", renderer="edit-node.j2")
def edit_node(request):
    """handle posting of edit form from show-node pages."""
    thread_data = request.params.get("thread_data", "")
    thread_title = request.params.get("thread_title", "")

    if request.user is None:
        request.session.flash(("You must log in to edit your messages.", "error"))
        return HTTPFound(get_referer_or_home(request))

    if not request.namespace.can_alter_node(request.node, request.user):
        request.session.flash(("You do not own this message.", "error"))
        return HTTPFound(get_referer_or_home(request))

    if thread_data or thread_title:
        if thread_title:
            request.node.title = thread_title
        request.node.edit(thread_data)

        # set return_to URI.
        return_to = get_node_route_uri(request, request.node.root, request.node.id)
        if request.mode == "embed":
            return_to = get_embed_route_uri(
                request, request.node.root.uri.data, request.node.id
            )

        return HTTPFound(return_to)

    return {}


def _node_route_uri(request):
    """accept a request, return the request's node route uri"""
    if request.mode == "embed":
        return get_embed_route_uri(request, request.node.root.uri.data, request.node.id)
    return get_node_route_uri(request, request.node.root, request.node.id)


@view_config(route_name="embed-disable", request_method=("POST", "PUT"))
@view_config(route_name="basic-disable", request_method=("POST", "PUT"))
def disable_node(request):
    """disable node if user allowed."""
    if request.namespace.can_alter_node(request.node, request.user):
        request.node.disable()
        request.dbsession.add(request.node)
        request.dbsession.flush()
    return HTTPFound(_node_route_uri(request))


@view_config(route_name="embed-enable", request_method=("POST", "PUT"))
@view_config(route_name="basic-enable", request_method=("POST", "PUT"))
def enable_node(request):
    """enable node if user allowed."""
    if request.namespace.can_alter_node(request.node, request.user):
        request.node.enable()
        request.dbsession.add(request.node)
        request.dbsession.flush()
    return HTTPFound(_node_route_uri(request))


@view_config(route_name="embed-verify", request_method=("POST", "PUT"))
@view_config(route_name="basic-verify", request_method=("POST", "PUT"))
def verify_node(request):
    """only the node creator may verify ownership of a node."""
    if request.node.user == request.user:
        request.node.verify()
        request.dbsession.add(request.node)
        request.dbsession.flush()
    return HTTPFound(_node_route_uri(request))


@view_config(route_name="embed-approve", request_method=("POST", "PUT"))
@view_config(route_name="basic-approve", request_method=("POST", "PUT"))
def approve_node(request):
    """approve node if user allowed."""
    if request.namespace.is_moderator(request.user):
        request.node.approve()
        request.dbsession.add(request.node)
        request.dbsession.flush()
    return HTTPFound(_node_route_uri(request))


@view_config(route_name="embed-deny", request_method=("POST", "PUT"))
@view_config(route_name="basic-deny", request_method=("POST", "PUT"))
def deny_node(request):
    """deny node if user allowed."""
    if request.namespace.is_moderator(request.user):
        request.node.deny()
        request.dbsession.add(request.node)
        request.dbsession.flush()
    return HTTPFound(_node_route_uri(request))
