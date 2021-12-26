from pyramid.view import view_config

from remarkbox.models import (
    get_topsecret_namespace_requests,
    get_topsecret_notifications,
    get_topsecret_namespaces,
    get_topsecret_roots,
    get_topsecret_nodes,
)

from remarkbox.views import super_fly_required


@view_config(route_name="topsecret-namespaces", renderer="list-namespaces.j2")
@super_fly_required
def topsecret_namespaces(request):
    return {
        "namespaces": get_topsecret_namespaces(request.dbsession),
        "the_title": "topsecret namespaces!",
    }


@view_config(
    route_name="topsecret-namespace-requests", renderer="list-namespace-requests.j2"
)
@super_fly_required
def topsecret_namespace_requests(request):
    limit = request.params.get("limit", 100)
    page = request.params.get("page", 0)
    return {
        "namespace_requests": get_topsecret_namespace_requests(
            request.dbsession,
            limit=limit,
            offset=page,
        ),
        "the_title": "topsecret namespace requests!",
    }


@view_config(
    route_name="topsecret-namespace-owners", renderer="list-namespace-owners.j2"
)
@super_fly_required
def topsecret_namespace_owners(request):
    return {
        "namespaces": get_topsecret_namespaces(request.dbsession),
        "the_title": "topsecret namespace owners!",
    }


@view_config(route_name="topsecret-notifications", renderer="list-notifications.j2")
@super_fly_required
def topsecret_notifications(request):
    return {
        "notifications": get_topsecret_notifications(
            request.dbsession, limit=request.page_size, offset=request.page_offset
        ),
        "the_title": "topsecret notifications!",
        "topsecret": True,
    }


@view_config(route_name="topsecret", renderer="home.j2")
@super_fly_required
def topsecret_roots(request):
    return {
        "nodes": get_topsecret_roots(request.dbsession),
        "the_title": "topsecret root nodes!",
    }


@view_config(route_name="topsecret-nodes", renderer="list-nodes.j2")
@super_fly_required
def topsecret_nodes(request):
    return {
        "nodes": get_topsecret_nodes(
            request.dbsession, limit=request.page_size, offset=request.page_offset
        ),
        "the_title": "topsecret activity on everything!",
    }
