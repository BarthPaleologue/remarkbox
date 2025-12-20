from pyramid.config import Configurator

from sqlalchemy import engine_from_config

from .models import (
    get_user_by_id,
    get_or_create_user_by_email,
    get_node_by_id,
    get_or_create_node_by_uri,
    get_nodes_who_share_root,
    get_node_id_map,
    get_graph_from_nodes,
    get_or_create_namespace,
    get_namespace_request_by_id,
    get_conversation_graph_from_nodes,
    flatten_graph,
)

# reject spammers.
from pyramid.httpexceptions import HTTPUnauthorized

# cookie only session, not encrypted but signed to prevent tampering!
from pyramid.session import SignedCookieSessionFactory

# email validation.
import re

# needed to load themes.
from pkg_resources import iter_entry_points

import logging

log = logging.getLogger(__name__)

JINJA2_EXTENSION = ".j2"


def get_int_or_bool_or_none_or_str(value):
    """
    Given a string value pulled from a configuration file,
    this function attempts to return the value with the proper type.
    """
    # Handle non-string values
    if not isinstance(value, str):
        return value

    # Handle string values
    try:
        return int(value)
    except ValueError:
        value_lower = value.lower()
        if value_lower in {"yes", "y", "true", "t", "1"}:
            return True
        elif value_lower in {"no", "n", "false", "f", "0"}:
            return False
        elif value_lower in {"none", "null"}:
            return None
        return str(value)


def expand_env_vars(value):
    """Expand environment variables including ${VAR:-default} syntax."""
    if not isinstance(value, str):
        return value

    import os
    import re

    # Handle ${VAR:-default} syntax
    # Use a non-greedy match to stop at the first closing brace
    pattern = r"\$\{([^:}]*)(?::-([^}]*?))?\}"

    def replacer(match):
        var_name = match.group(1)
        # Handle empty variable name case ${:-default}
        if not var_name:
            return match.group(2) if match.group(2) is not None else match.group(0)
        default_value = match.group(2) if match.group(2) is not None else ""
        return os.environ.get(var_name, default_value)

    return re.sub(pattern, replacer, value)


def get_children_settings(settings, parent_key):
    """
    Accept a settings dict and parent key, return dict of children

    For example:

      auth_tkt.hashalg = md5

    Results to:

      {'auth_tkt.hashalg': 'md5'}

    This function returns the following:

      >>> get_children_settings({'auth_tkt.hashalg': 'md5'}, 'auth_tkt')
      {'hashalg': 'md5'}

    """
    # the +1 is the . between parent and child settings.
    parent_len = len(parent_key) + 1
    children = {}
    for key, value in settings.items():
        if parent_key in key:
            # Expand environment variables with support for defaults
            expanded_value = expand_env_vars(value)
            children[key[parent_len:]] = get_int_or_bool_or_none_or_str(expanded_value)
    return children


def load_entry_points(group_name):
    """Return a dictionary of entry_points related to given group_name"""
    entry_points = {}
    for entry_point in iter_entry_points(group=group_name, name=None):
        entry_points[entry_point.name] = entry_point.load()
    return entry_points


def load_jinja2_themes(config):
    """Automatically load any entry_point registered Remarkbox theme."""
    themes = load_entry_points("remarkbox.themes")
    theme_defaults = {}

    for theme_name, theme_module in themes.items():
        theme_module_name = theme_module.__name__
        # teach Jinja2 about the template dir in the theme package.
        config.add_jinja2_search_path(
            "{}:templates/".format(theme_module_name), name=JINJA2_EXTENSION
        )
        # teach Pyramid about the static assets in the theme package.
        config.add_static_view(
            "static/theme/{}".format(theme_name),
            "{}:static/theme/{}".format(theme_module_name, theme_name),
            cache_max_age=3600,
        )
        # Collect theme's default mode if defined
        if hasattr(theme_module, 'default_theme_mode'):
            theme_defaults[theme_name] = theme_module.default_theme_mode

    # Store theme defaults in config registry for later access
    config.registry.settings['theme_defaults'] = theme_defaults
    return config


def is_ipv4(string):
    try:
        parts = list(map(int, string.split(".")))
    except:
        return False
    if len(parts) != 4:
        return False
    for part in parts:
        if part < 0 or part > 256:
            return False
    return True


def maybe_root_domain(string):
    """
    Maybe get valid "root" domain from given string, for example -

    valid:

      * hi.www.example.com -> example.com
      * www.example.com -> example.com
      * example.com -> example.com

    invalid:

      * comments.cryptocoin.com.au -> com.au
    """
    return ".".join(string.split(".")[-2:])


def main(global_config, **settings):
    """This function returns a Pyramid WSGI application."""

    # Expand environment variables in all settings using our custom function
    for key, value in list(settings.items()):
        if isinstance(value, str):
            settings[key] = expand_env_vars(value)

    app_settings = get_children_settings(settings, "app")
    session_settings = get_children_settings(settings, "session")

    def wild_signed_cookie_session_factory(request):
        """
        Hack SignedCookieSessionFactory to have `wild_domain`.
        Pyramid devs do not want to support this.

        In addition the domain is determined per request!

        This means a single deployment of this app can support managing a
        `wild_domain` cookie for any domain (likely using CNAMES).
        """
        root_domain = maybe_root_domain(request.domain)
        if is_ipv4(request.domain) or root_domain.startswith("com"):
            session_settings["domain"] = request.domain
        else:
            session_settings["domain"] = root_domain

        factory = SignedCookieSessionFactory(**session_settings)
        return factory(request)

    # setup session factory to use unencrypted but signed cookies.
    # session_factory = SignedCookieSessionFactory(**session_settings)
    session_factory = wild_signed_cookie_session_factory

    # build app config object from ini.
    config = Configurator(settings=settings, session_factory=session_factory)

    # setup and require automatic CSRF checking.
    config.set_default_csrf_options(require_csrf=True)

    # Create database engine from connection details in ini.
    # make request.dbsession available for use in Pyramid.
    config.include(".models")

    # setup jinja2 template support.
    config.include("pyramid_jinja2")
    config.add_jinja2_search_path("remarkbox:templates/", name=JINJA2_EXTENSION)
    config.add_jinja2_renderer(JINJA2_EXTENSION)
    config = load_jinja2_themes(config)

    # compile the email validator regex outside of the functions.
    _email_regex = re.compile("^[^@]+@[^@]+\.[^.@]+$")

    def add_debug_mode(request):
        """Return True if debug toolbar is enabled."""
        return "pyramid_debugtoolbar" in request.registry.settings.get(
            "pyramid.includes", ""
        )

    '''
    def add_redis(request):
        """Return Redis Connection"""
        redis_host = request.app.get("redis.host", "localhost")
        redis_port = request.app.get("redis.port", 6379)
        redis_db = request.app.get("redis.db", 0)
        return redis.Redis(host=redis_host, port=redis_port, db=redis_db)
    '''

    def add_email(request):
        """Return Email or None. Email must pass regex."""
        email = request.params.get("email", "")
        if _email_regex.match(email) is not None:
            return email

    def add_user(request):
        """Return User object or None. User.authenticated may be True or False."""
        user = None
        authenticated_user_id = request.session.get("authenticated_user_id", None)

        if authenticated_user_id:
            # attach the user object from DB to the request.
            user = get_user_by_id(request.dbsession, authenticated_user_id)
            if user is not None:
                user.authenticated = True

        elif request.email:
            user = get_or_create_user_by_email(request.dbsession, request.email)

        return user

    def add_csrf_token(request):
        if request.user and request.user.authenticated:
            return request.session.get_csrf_token()

    def add_node(request):
        """Return Node object or None from matchdict or params."""
        thread_uri = request.params.get("thread_uri")
        thread_title = request.params.get("thread_title")
        node_id = request.matchdict.get("node_id")
        nojs = request.params.get("nojs", False)

        node = None

        # TODO: thread_uri must take priority over node_id because our forms
        # are dumb. If we fix our forms to only pass node_id/node_path when not
        # None, the priority / order will not matter.
        if thread_uri:
            # Remove "/reply" from the end of the URL if present
            url = request.url
            if url.endswith("/reply"):
                url = url[:-6]  # Remove the last 6 characters ("/reply")
            request.session["back_to_thread"] = url

            node = get_or_create_node_by_uri(
                request.dbsession, thread_uri, thread_title
            )
        elif node_id:
            node = get_node_by_id(request.dbsession, node_id)
        elif nojs and request.referer:
            # if javascript is disabled, use the referer.
            node = get_or_create_node_by_uri(request.dbsession, request.referer)

        return node

    def add_root_node(request):
        return request.node.root

    def add_nodes(request):
        if request.node:
            return get_nodes_who_share_root(
                request.dbsession,
                request.node.root,
                request.node_order,
            )

    def add_node_id_map(request):
        return get_node_id_map(request.nodes)

    def add_node_graph(request):
        return get_graph_from_nodes(request.nodes)

    def add_node_flat_graph(request):
        return flatten_graph(request.node.root.id, request.node_graph)

    def add_conversation_graph(request):
        return get_conversation_graph_from_nodes(
            request.nodes,
            graph=request.node_graph,
            node_id_map=request.node_id_map,
            order=request.node_order,
        )

    def add_namespace(request):
        namespace_name = request.matchdict.get(
            "namespace", request.params.get("namespace", None)
        )
        if namespace_name:
            return get_or_create_namespace(request.dbsession, namespace_name)
        elif request.node:
            return request.node.root.namespace
        return get_or_create_namespace(request.dbsession, request.domain)

    def add_mode(request):
        """return mode of 'embed' or 'basic'"""
        return "embed" if "embed" in request.matched_route.name else "basic"

    def add_link_prefix(request):
        if request.mode == "embed":
            return "/embed/ns/{}".format(request.namespace.name)
        return ""

    def add_spam(request):
        """Test if request looks spammy HTTP Error or False."""
        if request.params.get("email2", "") != "":
            # spam filter, hidden email2 field tricks bots.
            return HTTPUnauthorized("you smell like a spammer")
        return False

    def add_owner_key(request):
        return request.params.get("rb_owner_key", None)

    def add_namespace_request(request):
        """Add namespace_request if pending, else None"""
        # we reduce database lookups by only querying when owner_key is
        # present and request.namespace has a pending owner_request.
        if request.owner_key and request.namespace.owner_request_pending:
            namespace_request = get_namespace_request_by_id(
                request.dbsession, request.owner_key
            )
            # for dubugging purposes only.
            # log.info("owner_key={}, pending={}".format(request.owner_key,request.namespace.owner_request_pending))
            if namespace_request and namespace_request.namespace == request.namespace:
                return namespace_request

    def add_app(request):
        """Attach app settings dictionary."""
        return app_settings

    def add_app_url(request):
        """
        Use the app_url from config if request.domain ends with the
        configured root_domain. Otherwise just use the request's host_url
        """
        config_app_url = request.app.get("app_url", request.host_url)
        root_domain = request.app.get("root_domain")
        if root_domain and request.domain.endswith(root_domain):
            return config_app_url
        elif request.domain == "localhost":
            return config_app_url
        return request.host_url

    def add_app_domain(request):
        return request.app_url.split("://")[-1].split(":")[0]

    def add_marketing_url(request):
        return request.app.get("marketing_url", request.app_url)

    def add_marketing_domain(request):
        return request.marketing_url.split("://")[-1].split(":")[0]

    def add_faq_home(request):
        """Return True if this request's domain equals namespace name."""
        return request.domain == request.namespace.name

    def add_saas_home(request):
        """Only one domain should have this method return True per deployment."""
        root_domain = request.app.get("root_domain")
        return (
            root_domain
            and request.domain.endswith(root_domain)
            and request.app_domain == request.namespace.name
        )


    def add_avatar_size(request):
        """Attach avatar size or default."""
        if request.namespace:
            if request.namespace.avatar_size:
                return request.namespace.avatar_size
        return request.app.get("avatar.size", 30)

    def add_stand_alone_mode(request):
        if request.app.get("stand_alone_mode", "disabled") == "enabled":
            return True
        return False

    def add_theme(request):
        """Attach theme name or None."""
        if request.mode == "embed":
            if request.namespace and request.namespace.theme_embed:
                return request.namespace.theme_embed
            return request.app.get("theme_embed", None)

        if request.namespace and request.namespace.theme:
            return request.namespace.theme
        return request.app.get("theme", None)

    def add_stylesheet(request):
        """Attach stylesheet or empty string."""
        if request.mode == "embed":
            return request.stylesheet_embed
        return request.stylesheet_basic

    def add_stylesheet_basic(request):
        """Attach stylesheet or empty string."""
        if request.namespace and request.namespace.stylesheet:
            return request.namespace.stylesheet
        return ""

    def add_stylesheet_embed(request):
        """Attach stylesheet_embed or empty string."""
        if request.namespace and request.namespace.stylesheet_embed:
            return request.namespace.stylesheet_embed
        return ""

    def add_stylesheet_uri(request):
        """Attach stylesheet uri or empty string."""
        if request.mode == "embed":
            return request.stylesheet_embed_uri
        return request.stylesheet_basic_uri

    def add_stylesheet_basic_uri(request):
        """Attach stylesheet uri or empty string."""
        if request.namespace and request.namespace.stylesheet_uri:
            return request.namespace.stylesheet_uri
        return ""

    def add_stylesheet_embed_uri(request):
        """Attach stylesheet_embed uri or empty string."""
        if request.namespace and request.namespace.stylesheet_embed_uri:
            return request.namespace.stylesheet_embed_uri
        return ""

    def add_base_template(request):
        """Attach base_template filename."""
        if request.theme:
            return "{}-base.j2".format(request.theme)
        return "base.j2"

    def add_base_funnel_template(request):
        """Attach base_funnel template filename."""
        if request.theme:
            return "{}-base-funnel.j2".format(request.theme)
        return "base.j2"

    def add_page_number(request):
        """Attach page_number starting at 0"""
        page_number = int(request.params.get("page", 1))
        return page_number if page_number >= 1 else 1

    def add_page_size(request):
        # if we want to support custom page sizes, set it here.
        return 100

    def add_page_offset(request):
        return (request.page_number - 1) * request.page_size

    def add_node_order(request):
        return request.params.get("order", request.namespace.node_order)

    def add_mathjax(request):
        return "true" if request.namespace.mathjax else "false"

    def add_theme_mode(request):
        """
        Return theme mode 'light' or 'dark'.
        Priority: user preference > query params > theme default > 'light'.
        """
        # If user is authenticated and has a preference
        if request.user and request.user.authenticated and request.user.theme_mode != 'auto':
            return request.user.theme_mode

        # Check if there's a mode parameter (for embeds or overrides)
        param_mode = request.params.get("mode")
        if param_mode in ("light", "dark"):
            return param_mode

        # Use theme's default mode if available
        if request.theme:
            theme_defaults = request.registry.settings.get('theme_defaults', {})
            theme_default = theme_defaults.get(request.theme)
            if theme_default in ("light", "dark"):
                return theme_default

        # Final fallback to light
        return "light"

    # register functions to app config as request methods.
    # each request instance will run these functions and attach results.
    # cache result with `reify=True` to prevent multiple db lookups.
    # config.add_request_method(add_redis, "redis", reify=True)
    config.add_request_method(add_debug_mode, "debug_mode", reify=True)
    config.add_request_method(add_user, "user", reify=True)
    config.add_request_method(add_csrf_token, "csrf_token", reify=True)
    config.add_request_method(add_email, "email", reify=True)
    config.add_request_method(add_node, "node", reify=True)
    config.add_request_method(add_root_node, "root_node", reify=True)
    config.add_request_method(add_nodes, "nodes", reify=True)
    config.add_request_method(add_node_id_map, "node_id_map", reify=True)
    config.add_request_method(add_node_graph, "node_graph", reify=True)
    config.add_request_method(add_node_flat_graph, "node_flat_graph", reify=True)
    config.add_request_method(add_conversation_graph, "conversation_graph", reify=True)
    config.add_request_method(add_namespace, "namespace", reify=True)
    config.add_request_method(add_mode, "mode", reify=True)
    config.add_request_method(add_link_prefix, "link_prefix", reify=True)
    config.add_request_method(add_spam, "spam", reify=True)
    config.add_request_method(add_owner_key, "owner_key", reify=True)
    config.add_request_method(add_namespace_request, "namespace_request", reify=True)
    config.add_request_method(add_app, "app", reify=True)
    config.add_request_method(add_app_url, "app_url", reify=True)
    config.add_request_method(add_app_domain, "app_domain", reify=True)
    config.add_request_method(add_marketing_url, "marketing_url", reify=True)
    config.add_request_method(add_marketing_domain, "marketing_domain", reify=True)
    config.add_request_method(add_faq_home, "faq_home", reify=True)
    config.add_request_method(add_saas_home, "saas_home", reify=True)
    config.add_request_method(add_stand_alone_mode, "stand_alone_mode", reify=True)
    config.add_request_method(add_avatar_size, "avatar_size", reify=True)
    config.add_request_method(add_theme, "theme", reify=True)
    config.add_request_method(add_stylesheet_basic, "stylesheet_basic", reify=True)
    config.add_request_method(add_stylesheet_embed, "stylesheet_embed", reify=True)
    config.add_request_method(add_stylesheet, "stylesheet", reify=True)
    config.add_request_method(
        add_stylesheet_basic_uri, "stylesheet_basic_uri", reify=True
    )
    config.add_request_method(
        add_stylesheet_embed_uri, "stylesheet_embed_uri", reify=True
    )
    config.add_request_method(add_stylesheet_uri, "stylesheet_uri", reify=True)
    config.add_request_method(add_base_template, "base_template", reify=True)
    config.add_request_method(
        add_base_funnel_template, "base_funnel_template", reify=True
    )
    config.add_request_method(add_page_number, "page_number", reify=True)
    config.add_request_method(add_page_size, "page_size", reify=True)
    config.add_request_method(add_page_offset, "page_offset", reify=True)
    config.add_request_method(add_node_order, "node_order", reify=True)
    config.add_request_method(add_mathjax, "mathjax", reify=True)
    config.add_request_method(add_theme_mode, "theme_mode", reify=True)

    # all of the web application routes.
    config.include(".routes")

    # Scan for views.
    config.scan()

    return config.make_wsgi_app()
