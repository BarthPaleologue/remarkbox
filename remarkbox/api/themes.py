"""Theme generation API endpoints."""

from pyramid.response import Response
from pyramid.view import view_config

from remarkbox.models.namespace import get_namespace_by_name
from remarkbox.lib.theme_generator import generate_theme_css


@view_config(
    route_name="api-namespace-theme",
    request_method="GET",
    require_csrf=False,
)
def api_namespace_theme(request):
    """Generate and serve a theme CSS for a namespace.

    The theme is deterministic -- same namespace always gets the same theme.
    Cache-friendly: can be cached indefinitely (changes only if we change the algorithm).
    """
    namespace_name = request.matchdict["namespace_name"]

    # Validate namespace exists
    namespace = get_namespace_by_name(request.dbsession, namespace_name)
    if namespace is None:
        request.response.status_code = 404
        request.response.content_type = "application/json"
        request.response.json_body = {"error": "Namespace not found"}
        return request.response

    css = generate_theme_css(namespace_name)

    response = Response(
        body=css,
        content_type="text/css; charset=utf-8",
    )
    # Cache for 1 day -- theme is deterministic but we might update the algorithm
    response.cache_control.max_age = 86400
    response.cache_control.public = True
    return response


@view_config(
    route_name="api-theme-preview",
    request_method="GET",
    renderer="json",
    require_csrf=False,
)
def api_theme_preview(request):
    """Preview theme variables for a namespace (JSON format).

    Useful for theme customization UI -- shows the computed palette
    without needing to parse CSS.
    """
    namespace_name = request.matchdict["namespace_name"]

    namespace = get_namespace_by_name(request.dbsession, namespace_name)
    if namespace is None:
        request.response.status_code = 404
        return {"error": "Namespace not found"}

    from remarkbox.lib.theme_generator import _name_to_seed
    seed = _name_to_seed(namespace_name)

    hue = seed[0] % 360
    hue_offset = 30 + (seed[1] % 30)
    secondary_hue = (hue + hue_offset) % 360
    accent_hue = (hue + 180 + (seed[2] % 40 - 20)) % 360
    sat_base = 40 + (seed[3] % 25)

    return {
        "namespace": namespace_name,
        "palette": {
            "primary_hue": hue,
            "secondary_hue": secondary_hue,
            "accent_hue": accent_hue,
            "saturation_base": sat_base,
        },
        "css_url": "/api/v1/themes/{}/css".format(namespace_name),
    }
