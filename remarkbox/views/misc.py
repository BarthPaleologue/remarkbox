# needed for favicon
import os
from pyramid.response import FileResponse, Response

from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound, HTTPNotFound

from pyramid.renderers import render_to_response

from remarkbox.lib.render import markdown_to_html

from . import get_node_route_uri

from uuid import uuid1

DEFAULT_ROBOTS_DOT_TXT = """
User-agent: *
Disallow:
"""


@view_config(route_name="basic-namespace-stats-json")
def namespace_stats_json(request):
    from json import dumps
    response = Response(body=dumps(request.namespace.visible_root_stats))
    response.headerlist = []
    # allow Javascript from other domains to download this resource.
    response.headerlist.extend(
        (
            ('Access-Control-Allow-Origin', '*'),
            ('Content-Type', 'application/json')
        )
    )
    return response


@view_config(route_name="redirect-to-root")
def redirect_to_root(request):
    """
    Given a node id, redirect to it's root uri.
    This significantly speeds up page loads for pages without a subject node.
    """
    if request.node.root.uri:
        return HTTPFound("{}#{}".format(request.node.root.uri.data, request.node.id))

    return HTTPFound(
        get_node_route_uri(request, request.node.root, anchor=request.node.id)
    )


# I set require_csfr to false because new browsers
# don't save 3rd party cookies anymore.
# This ajax endpoint should work whether a user is authenticated or not.
@view_config(route_name="preview-post", renderer="string", xhr=True, require_csrf=False)
def preview_post(request):
    """AJAJ: Accept data + optional source_format, return HTML.

    Mirrors Node.set_data dispatch so the live preview matches what the
    save path will produce. Without this, RST / HTML / mediawiki / latex
    nodes silently fell through markdown rendering & previews lied —
    e.g. an RST file showed `..` comments + literal `name_` references
    instead of resolved hyperlinks.
    """
    data = request.params.get("data", "")
    source_format = (request.params.get("source_format") or "markdown").strip().lower()
    try:
        if source_format in ("", "markdown"):
            return markdown_to_html(data, request.namespace, dbsession=request.dbsession)
        if source_format == "html":
            # match set_data: clean HTML through markdown pipeline
            from remarkbox.lib.pandoc import convert
            cleaned = convert(data, from_format="html", to_format="markdown")
            return markdown_to_html(cleaned, request.namespace, dbsession=request.dbsession)
        # pandoc handles rst, mediawiki, latex, org, etc.
        from remarkbox.lib.pandoc import convert
        from remarkbox.lib.render import make_cleaner_from_namespace
        from remarkbox.lib.sanitize_html import clean_raw_html
        html = convert(data, from_format=source_format, to_format="html5",
                       standalone=False)
        return clean_raw_html(html, make_cleaner_from_namespace(request.namespace))
    except Exception:
        return "we could not create a preview for source_format=%s." % source_format


@view_config(route_name="favicon")
def favicon_view(request):
    here = os.path.dirname(__file__)
    icon = os.path.join(here, "..", "static", "favicon.ico")
    return FileResponse(icon, request=request)


@view_config(route_name="robots")
def robots_view(request):
    """Load and return either default robots.txt or version from .ini"""
    response = Response(
        body=request.app.get(
            "robots_dot_txt",
            DEFAULT_ROBOTS_DOT_TXT
        ).lstrip()
    )
    response.content_type = "text/plain"
    return response


@view_config(route_name="embed-show-count", renderer="show-count.j2")
@view_config(route_name="basic-show-count", renderer="show-count.j2")
@view_config(route_name="basic-show-count2", renderer="show-count.j2")
def show_count(request):
    return { "stats" : request.namespace.visible_root_stats }


@view_config(route_name="embed-iframe")
@view_config(route_name="embed-iframe-min")
def embed_iframe(request):
    """Jinja render a text file and serve it as plain text."""
    context = {
        "rb_owner_key": request.params.get("rb_owner_key", "none"),
        "mode": request.params.get("mode", "light")
    }
    response = render_to_response("embed-iframe.txt.j2", context, request=request)
    response.content_type = "text/plain"
    if request.matched_route.name == "embed-iframe-min":
        response.text = " ".join(response.text.split())
    return response


@view_config(route_name="basic-namespace-stylesheet")
@view_config(route_name="embed-namespace-stylesheet")
def namespace_stylesheet(request):
    """serve a namespaces css, expire cache after a month."""
    response = Response(body=request.stylesheet)
    response.content_type = "text/css"
    response.cache_expires(seconds=2592000)
    return response


@view_config(route_name="dynamic-remarkbox-css")
def remarkbox_dynamic_stylesheet(request):
    """
    Jinja render a css file and serve it as text/css.
    Serve a dynamic css, expire cache after a month.
    """
    context = {"request": request}
    response = render_to_response(
        "dynamic-remarkbox.css.j2",
        context,
        request=request,
    )
    response.content_type = "text/css"
    response.cache_expires(seconds=2592000)
    return response
