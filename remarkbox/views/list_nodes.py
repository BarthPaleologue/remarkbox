from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound, HTTPForbidden

from remarkbox.models import (
    get_user_by_name,
    get_root_nodes_by_keywords,
)

from . import (
    get_referer_or_home,
    get_node_route_uri,
    get_embed_route_uri,
    get_join_or_log_in_route_uri,
)

try:
    unicode("")
except:
    from six import u as unicode


@view_config(route_name="sitemap", renderer="sitemap.xml.j2")
@view_config(route_name="sitemap2", renderer="sitemap.xml.j2")
@view_config(route_name="basic-namespace-threads-rss", renderer="rss.xml.j2")
def rss_xml(request):
    request.response.content_type = "text/xml"
    return {"nodes": request.namespace.visible_roots.all()}


@view_config(route_name="basic-namespace-nodes-rss", renderer="rss.xml.j2")
def rss_nodes_xml(request):
    request.response.content_type = "text/xml"
    if request.namespace.hide_unless_approved:
        nodes = request.namespace.approved_nodes
    else:
        nodes = request.namespace.page_nodes(
            limit=request.page_size, offset=request.page_offset
        )
    request.response.content_type = "text/xml"
    return {"nodes": nodes}


@view_config(route_name="basic-namespace-pending-rss", renderer="rss.xml.j2")
def rss_pending_xml(request):
    request.response.content_type = "text/xml"
    nodes = request.namespace.unapproved_nodes
    if request.namespace.hide_unless_approved:
        feed_key = request.matchdict.get("feed_key", None)
        # should we bcrypt this password?
        if feed_key != request.namespace.feed_key:
            return HTTPForbidden("The feed password was invalid!")
    return {"nodes": nodes}


@view_config(route_name="basic-namespace", renderer="home.j2")
@view_config(route_name="embed-namespace", renderer="home.j2")
@view_config(route_name="home", renderer="home.j2")
def namespace(request):
    return {
        "nodes": request.namespace.visible_roots,
        "the_title": request.namespace.name,
    }


@view_config(route_name="basic-namespace-nodes", renderer="list-nodes.j2")
@view_config(route_name="embed-namespace-nodes", renderer="list-nodes.j2")
def namespace_nodes(request):
    # TODO: the way I'm currently protecting views (or in this case certain urls)
    #       is causing a lot of copy and paste and even confusing conditional logic.
    if request.namespace.hide_unless_approved:
        if "disabled" in request.params or "pending" in request.params:
            # TODO: maybe dry this out and turn it into a decorator?
            if not request.user or not request.user.authenticated:
                request.session.flash(("You must log in to access that area.", "error"))
                return HTTPFound(get_join_or_log_in_route_uri(request))

            # TODO: maybe dry this out and turn it into a decorator?
            if request.user not in request.namespace.moderators:
                request.session.flash(
                    ("You must be a moderator in to access that area.", "error")
                )
                return HTTPFound(get_join_or_log_in_route_uri(request))

            if "disabled" in request.params:
                # TODO: pagination.
                state = "disabled"
                nodes = request.namespace.disabled_nodes
            elif "pending" in request.params:
                # TODO: pagination.
                state = "pending"
                nodes = request.namespace.unapproved_nodes
        else:
            state = "active"
            nodes = request.namespace.page_nodes(
                limit=request.page_size, offset=request.page_offset
            )
    else:
        if "disabled" in request.params:
            # TODO: pagination.
            state = "disabled"
            nodes = request.namespace.disabled_nodes
        else:
            state = "active"
            nodes = request.namespace.page_nodes(
                limit=request.page_size, offset=request.page_offset
            )
    return {
        "nodes": nodes,
        "the_title": "{} - {} nodes".format(request.namespace.name, state),
    }


@view_config(route_name="basic-user", renderer="list-nodes.j2")
@view_config(route_name="embed-user", renderer="list-nodes.j2")
def user_nodes(request):
    subject_user_name = request.matchdict.get("user_name", None)
    subject_user = get_user_by_name(request.dbsession, subject_user_name)
    if subject_user is None:
        return HTTPFound(get_referer_or_home(request))
    if "disabled" in request.params:
        # TODO: pagination.
        state = "disabled"
        nodes = subject_user.disabled_nodes
    elif "pending" in request.params:
        # TODO: pagination.
        state = "pending"
        nodes = subject_user.unverified_nodes
    else:
        state = "active"
        nodes = subject_user.page_nodes(
            limit=request.page_size, offset=request.page_offset
        )
    return {
        "nodes": nodes,
        "the_title": "{} - {} nodes".format(subject_user.name, state),
    }


@view_config(route_name="search", renderer="home.j2")
def search(request):
    # TODO: maybe we should maintain a search table where we have: root_id, data
    #       where data is the concatenated data from all nodes in a tree.
    #       whenever a new node is added to a tree, it would recompute this value.
    keywords = request.params.get("keywords", None)

    if not keywords:
        return HTTPFound(get_referer_or_home(request))

    # Note: a search from topsecret page does not pass a namespace.
    nodes = get_root_nodes_by_keywords(
        request.dbsession,
        keywords.split(" "),
        request.namespace
    )

    if len(nodes) == 1:
        # redirect to only match, the title slugified node uri.
        return HTTPFound(nodes[0].path)

    return {
        "nodes": nodes,
        "the_title": '"{}" on {}'.format(keywords, request.namespace.name),
    }


def verify_namespace_request(request):
    """check if namespace_request is present on the target."""
    if request.namespace_request:
        user = request.namespace_request.user
        request.namespace_request.verify_target(request.node.root.uri.data)
        request.namespace.update_owner_request_timestamp()
        if request.namespace_request.verified and user not in request.namespace.owners:
            request.namespace.set_role_for_user(user, unicode("owner"))
            request.session.flash(
                (
                    "Namespace owner was verified! ({})".format(request.namespace.name),
                    "Success"
                )
            )
        request.dbsession.add(request.namespace_request)
        request.dbsession.add(request.namespace)
        request.dbsession.flush()


#@view_config(route_name="basic-show-node", renderer="show-node2.j2")
#@view_config(route_name="basic-show-node2", renderer="show-node2.j2")
@view_config(route_name="basic-show-node", renderer="show-node.j2")
@view_config(route_name="basic-show-node2", renderer="show-node.j2")
@view_config(route_name="embed-show-node", renderer="show-node.j2")
@view_config(route_name="embed-show-node2", renderer="show-node.j2")
@view_config(route_name="embed-show-node3", renderer="show-node.j2")
def show_node(request):
    """Show a node."""
    if request.node is None:
        # unable to find node by id or thread_uri, or create by thread_uri.
        return HTTPFound(get_referer_or_home(request))

    if request.node.has_uri == False and request.node.slug is not None and "slug" not in request.matchdict:
        # redirect to the title slugified node uri.
        return HTTPFound(get_node_route_uri(request, request.node))

    # logic to magically verify an owner of a namespace.
    verify_namespace_request(request)

    return {}
