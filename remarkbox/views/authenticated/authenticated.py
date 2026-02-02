from json import dumps

from pyramid.view import view_config

from pyramid.httpexceptions import HTTPFound

from pyramid.response import Response

from remarkbox.models.meta import NOTIFICATION_FREQUENCIES

from remarkbox.models import (
    get_or_create_namespace,
    get_or_create_namespace_request,
    get_namespace_request_by_id,
    is_user_name_available,
    is_user_name_valid,
)

from remarkbox.views import get_referer_or_home, user_required, reject_stand_alone

from remarkbox.scripts.modify_namespace import delete_namespace_cascade

from string import digits

try:
    # Python 2.
    from string import lowercase
except ImportError:
    # Python 3.
    from string import ascii_lowercase as lowercase


domain_name_set = set(lowercase + digits + ".-")


def checkbox_to_bool(checkbox):
    return True if checkbox == "on" else False


@view_config(route_name="basic-namespace-settings", renderer="namespace-settings.j2")
@view_config(route_name="embed-namespace-settings", renderer="namespace-settings.j2")
@user_required()
def namespace_settings(request):

    if not request.user in request.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_referer_or_home(request))

    # temporarily set attribute protection to False
    # so that an unpaid Namespace still displays the set values.
    request.namespace.memoized_attr_protection = False

    if request.method == "POST":
        p = request.params
        stylesheet_embed = p.get("stylesheet-embed", request.namespace.stylesheet_embed)
        stylesheet_embed_uri = p.get(
            "stylesheet-embed-uri", request.namespace.stylesheet_embed_uri
        )
        description = p.get("description", request.namespace.description)
        no_nodes_text = p.get("no-nodes-text", request.namespace.no_nodes_text)
        placeholder_text = p.get("placeholder-text", request.namespace.placeholder_text)
        google_analytics_id = p.get(
            "google-analytics-id", request.namespace.google_analytics_id
        )
        google_site_verification = p.get(
            "google-site-verification", request.namespace.google_site_verification
        )

        # T4: customizable button text and comment labels
        submit_button_text = p.get("submit-button-text", request.namespace.submit_button_text)
        comment_label_singular = p.get("comment-label-singular", request.namespace.comment_label_singular)
        comment_label_plural = p.get("comment-label-plural", request.namespace.comment_label_plural)

        # T8: nesting depth settings
        max_nesting_depth_raw = p.get("max-nesting-depth", "").strip()
        collapse_depth_raw = p.get("collapse-depth", "").strip()

        hide_unless_approved_checkbox = p.get("hide-unless-approved-checkbox", "off")
        allow_anonymous_checkbox = p.get("allow-anonymous-checkbox", "off")
        link_protection_checkbox = p.get("link-protection-checkbox", "off")
        reverse_order_checkbox = p.get("reverse-order-checkbox", "off")
        group_conversations_checkbox = p.get("group-conversations-checkbox", "off")
        mathjax_checkbox = p.get("mathjax-checkbox", "off")
        ignore_query_string_checkbox = p.get("ignore-query-string-checkbox", "off")
        hide_powered_by_checkbox = p.get("hide-powered-by-checkbox", "off")
        api_access_checkbox = p.get("api-access-checkbox", "off")
        spam_filter_enabled_checkbox = p.get("spam-filter-enabled-checkbox", "off")

        hide_unless_approved = checkbox_to_bool(hide_unless_approved_checkbox)
        allow_anonymous = checkbox_to_bool(allow_anonymous_checkbox)
        link_protection = checkbox_to_bool(link_protection_checkbox)
        reverse_order = checkbox_to_bool(reverse_order_checkbox)
        group_conversations = checkbox_to_bool(group_conversations_checkbox)
        mathjax = checkbox_to_bool(mathjax_checkbox)
        ignore_query_string = checkbox_to_bool(ignore_query_string_checkbox)
        hide_powered_by = checkbox_to_bool(hide_powered_by_checkbox)
        api_access = checkbox_to_bool(api_access_checkbox)
        spam_filter_enabled = checkbox_to_bool(spam_filter_enabled_checkbox)

        if stylesheet_embed != request.namespace.stylesheet_embed and (
            stylesheet_embed or request.namespace.stylesheet_embed
        ):
            request.namespace.set_stylesheet_embed(stylesheet_embed)
            request.session.flash(("Success, you changed the stylesheet", "success"))

        if stylesheet_embed_uri != request.namespace.stylesheet_embed_uri and (
            stylesheet_embed_uri or request.namespace.stylesheet_embed_uri
        ):
            request.namespace.stylesheet_embed_uri = stylesheet_embed_uri
            request.session.flash(
                ("Success, you changed the stylesheet URI", "success")
            )

        if description != request.namespace.description and (
            description or request.namespace.description
        ):
            request.namespace.description = description
            request.session.flash(
                (
                    "Success, you changed the description for {}".format(
                        request.namespace.name
                    ),
                    "success",
                )
            )

        if no_nodes_text != request.namespace.no_nodes_text and (
            no_nodes_text or request.namespace.no_nodes_text
        ):
            request.namespace.no_nodes_text = no_nodes_text
            request.session.flash(
                (
                    "Success, you changed the text when there are no nodes in the thread.",
                    "success",
                )
            )

        if placeholder_text != request.namespace.placeholder_text and (
            placeholder_text or request.namespace.placeholder_text
        ):
            request.namespace.placeholder_text = placeholder_text
            request.session.flash(
                (
                    "Success, you changed the placeholder textarea text for new nodes.",
                    "success",
                )
            )

        if google_analytics_id != request.namespace.google_analytics_id and (
            google_analytics_id or request.namespace.google_analytics_id
        ):
            request.namespace.google_analytics_id = google_analytics_id
            request.session.flash(
                (
                    "Success, you changed the Google Analytics ID for stand alone mode.",
                    "success",
                )
            )

        if google_site_verification != request.namespace.google_site_verification and (
            google_site_verification or request.namespace.google_site_verification
        ):
            request.namespace.google_site_verification = google_site_verification
            request.session.flash(
                (
                    "Success, you changed the Google Site Verification code for stand alone mode.",
                    "success",
                )
            )

        if hide_unless_approved != request.namespace.hide_unless_approved:
            request.namespace.hide_unless_approved = hide_unless_approved
            request.session.flash(
                (
                    "You turned {} hide_unless_approved".format(
                        hide_unless_approved_checkbox
                    ),
                    "success",
                )
            )

        if allow_anonymous != request.namespace.allow_anonymous:
            request.namespace.allow_anonymous = allow_anonymous
            request.session.flash(
                (
                    "You turned {} allow_anonymous".format(
                        allow_anonymous_checkbox
                    ),
                    "success",
                )
            )

        if link_protection != request.namespace.link_protection:
            request.namespace.link_protection = link_protection
            request.session.flash(
                (
                    "You turned {} link_protection".format(link_protection_checkbox),
                    "success",
                )
            )

        if reverse_order != request.namespace.reverse_order:
            request.namespace.reverse_order = reverse_order
            request.session.flash(
                (
                    "You turned {} reverse_order".format(reverse_order_checkbox),
                    "success",
                )
            )

        if group_conversations != request.namespace.group_conversations:
            request.namespace.group_conversations = group_conversations
            request.session.flash(
                (
                    "You turned {} group_conversations".format(
                        group_conversations_checkbox
                    ),
                    "success",
                )
            )

        if ignore_query_string != request.namespace.ignore_query_string:
            request.namespace.ignore_query_string = ignore_query_string
            request.session.flash(
                (
                    "You turned {} ignore_query_string".format(
                        ignore_query_string_checkbox
                    ),
                    "success",
                )
            )

        if hide_powered_by != request.namespace.hide_powered_by:
            request.namespace.hide_powered_by = hide_powered_by
            request.session.flash(
                (
                    "You turned {} hide_powered_by".format(hide_powered_by_checkbox),
                    "success",
                )
            )

        if mathjax != request.namespace.mathjax:
            request.namespace.mathjax = mathjax
            request.session.flash(
                ("You turned {} MathJax".format(mathjax_checkbox), "success")
            )

        if api_access != request.namespace.api_access:
            request.namespace.api_access = api_access
            request.session.flash(
                (
                    "You turned {} api_access".format(api_access_checkbox),
                    "success",
                )
            )

        if spam_filter_enabled != (request.namespace.spam_filter_enabled is not False):
            request.namespace.spam_filter_enabled = spam_filter_enabled
            request.session.flash(
                (
                    "You turned {} spam_filter (Hermes)".format(
                        spam_filter_enabled_checkbox
                    ),
                    "success",
                )
            )

        # T4: customizable button text and comment labels
        if submit_button_text != request.namespace.submit_button_text and (
            submit_button_text or request.namespace.submit_button_text
        ):
            request.namespace.submit_button_text = submit_button_text
            request.session.flash(
                ("Success, you changed the submit button text.", "success")
            )

        if comment_label_singular != request.namespace.comment_label_singular and (
            comment_label_singular or request.namespace.comment_label_singular
        ):
            request.namespace.comment_label_singular = comment_label_singular
            request.session.flash(
                ("Success, you changed the singular comment label.", "success")
            )

        if comment_label_plural != request.namespace.comment_label_plural and (
            comment_label_plural or request.namespace.comment_label_plural
        ):
            request.namespace.comment_label_plural = comment_label_plural
            request.session.flash(
                ("Success, you changed the plural comment label.", "success")
            )

        # T8: nesting depth settings
        max_nesting_depth = int(max_nesting_depth_raw) if max_nesting_depth_raw else None
        if max_nesting_depth != request.namespace.max_nesting_depth:
            request.namespace.max_nesting_depth = max_nesting_depth
            if max_nesting_depth is not None:
                request.session.flash(
                    ("Max nesting depth set to {}.".format(max_nesting_depth), "success")
                )
            else:
                request.session.flash(
                    ("Max nesting depth set to unlimited.", "success")
                )

        collapse_depth = int(collapse_depth_raw) if collapse_depth_raw else None
        if collapse_depth != request.namespace.collapse_depth:
            request.namespace.collapse_depth = collapse_depth
            if collapse_depth is not None:
                request.session.flash(
                    ("Collapse depth set to {}.".format(collapse_depth), "success")
                )
            else:
                request.session.flash(
                    ("Collapse depth disabled.", "success")
                )

        request.dbsession.add(request.namespace)
        request.dbsession.flush()

    return {"the_title": "Namespace settings for {}".format(request.namespace.name)}


@view_config(route_name="embed-user-settings", renderer="user-settings.j2")
@view_config(route_name="basic-user-settings", renderer="user-settings.j2")
@user_required()
def user_settings(request):
    if request.method == "POST":
        _msg = "<b>{}</b> was turned <b>{}</b>"
        display_name = request.params.get("display-name", request.user.name)

        gravatar_checkbox = request.params.get("gravatar-checkbox", "off")
        auto_watch_create_checkbox = request.params.get(
            "auto-watch-threads-i-create-checkbox", "off"
        )
        auto_watch_participate_checkbox = request.params.get(
            "auto-watch-threads-i-participate-checkbox", "off"
        )

        gravatar = checkbox_to_bool(gravatar_checkbox)
        auto_watch_create = checkbox_to_bool(auto_watch_create_checkbox)
        auto_watch_participate = checkbox_to_bool(auto_watch_participate_checkbox)

        reply_watcher_frequency = request.params["reply-watcher-frequency"]
        default_node_watcher_frequency = request.params[
            "default-node-watcher-frequency"
        ]
        theme_mode = request.params.get("theme-mode", "auto")

        if display_name != request.user.name:
            if is_user_name_valid(display_name) == False:
                request.session.flash(
                    ("Sorry, display name must be alpha numeric", "error")
                )
            elif is_user_name_available(request.dbsession, display_name) == False:
                request.session.flash(
                    ('Sorry, "{}" is already in use'.format(display_name), "error")
                )
            else:
                request.user.name = display_name
                request.session.flash(
                    (
                        "Nice to meet you <b>{}</b>! (preferred display name saved!)".format(
                            request.user.name
                        ),
                        "success",
                    )
                )

        if gravatar != request.user.gravatar:
            request.user.gravatar = gravatar
            request.session.flash(
                (_msg.format("gravatar", gravatar_checkbox), "success")
            )

        """
        if auto_watch_create != request.user.auto_watch_threads_i_create:
            request.user.auto_watch_threads_i_create = auto_watch_create
            request.session.flash(
                (
                    _msg.format(
                        "auto_watch_threads_i_create"
                        auto_watch_create_checkbox,
                    ),
                    "success",
                )
            )

        if auto_watch_participate != request.user.auto_watch_threads_i_participate:
            request.user.auto_watch_threads_i_participate = auto_watch_participate
            request.session.flash(
                (
                    _msg.format(
                        "auto_watch_threads_i_participate",
                        auto_watch_participate_checkbox,
                    ),
                    "success",
                )
            )
        """

        if (
            default_node_watcher_frequency
            != request.user.default_node_watcher_frequency
        ):
            if default_node_watcher_frequency in NOTIFICATION_FREQUENCIES:
                request.user.default_node_watcher_frequency = (
                    default_node_watcher_frequency
                )
                request.session.flash(
                    (
                        "By default, when you <b>watch a thread</b>, we will notify you <b>{}</b>".format(
                            default_node_watcher_frequency
                        ),
                        "success",
                    )
                )
            else:
                request.session.flash(
                    ("Invalid Enum value for default_node_watcher_frequency.", "error")
                )

        if reply_watcher_frequency != request.user.reply_watcher.notification_frequency:
            if reply_watcher_frequency in NOTIFICATION_FREQUENCIES:
                request.user.reply_watcher.notification_frequency = (
                    reply_watcher_frequency
                )
                request.session.flash(
                    (
                        "When any of your comments get a reply, we will notify you <b>{}</b> via <b>{}</b>".format(
                            request.user.reply_watcher.notification_frequency,
                            request.user.reply_watcher.notification_method,
                        ),
                        "success",
                    )
                )
            else:
                request.session.flash(
                    ("Invalid Enum value for reply_watcher_frequency.", "error")
                )

        if theme_mode != request.user.theme_mode:
            if theme_mode in ('auto', 'light', 'dark'):
                request.user.theme_mode = theme_mode
                theme_labels = {
                    'auto': 'Auto (follow parent site)',
                    'light': 'Light',
                    'dark': 'Dark'
                }
                request.session.flash(
                    (
                        "Theme appearance set to <b>{}</b>".format(theme_labels[theme_mode]),
                        "success",
                    )
                )
            else:
                request.session.flash(
                    ("Invalid theme mode value.", "error")
                )

        notification_preference = request.params.get(
            "notification-preference",
            getattr(request.user, "notification_preference", "email"),
        )
        current_pref = getattr(request.user, "notification_preference", "email")
        if notification_preference != current_pref:
            if notification_preference in ("email", "push", "both", "none"):
                request.user.notification_preference = notification_preference
                pref_labels = {
                    "email": "Email only",
                    "push": "Browser push only",
                    "both": "Email and browser push",
                    "none": "None",
                }
                request.session.flash(
                    (
                        "Notification delivery set to <b>{}</b>".format(
                            pref_labels[notification_preference]
                        ),
                        "success",
                    )
                )
            else:
                request.session.flash(
                    ("Invalid notification preference value.", "error")
                )

        request.dbsession.add(request.user)
        request.dbsession.flush()

    return {"the_title": "{}'s settings".format(request.user.name)}


@view_config(route_name="setup", renderer="setup-namespace.j2")
@user_required(
    flash_msg="Verify your email to get started.",
    flash_level="info",
    return_to_route_name="setup",
)
@reject_stand_alone
def setup_namespace(request):
    if request.method == "POST":
        # domains are case insensitive (make lowercase).
        namespace_domain = request.params.get("namespace-domain", "").lower()
        if "." not in namespace_domain:
            request.session.flash(('A domain needs at least one "."', "error"))
        elif namespace_domain.startswith("-") or namespace_domain.startswith("."):
            request.session.flash(('A domain cannot start with "." or "-"', "error"))
        elif not set(namespace_domain).issubset(domain_name_set):
            request.session.flash(
                ('A domain has only letters, digits, "." and "-"', "error")
            )
        elif namespace_domain:
            namespace = get_or_create_namespace(request.dbsession, namespace_domain)
            namespace_request = get_or_create_namespace_request(
                request.dbsession, request.user, namespace
            )
            request.dbsession.add(namespace_request)
            request.dbsession.flush()
            request.session.flash(("Great work, on to Step 2!", "success"))
        else:
            request.session.flash(("Please enter a domain.", "error"))

    return {
        "namespaces": request.user.namespaces,
        "namespace_requests": request.user.namespace_owner_requests,
        "unverified_namespace_requests": request.user.unverified_namespace_owner_requests,
    }


@view_config(route_name="setup-namespace-request-cancel")
@user_required()
@reject_stand_alone
def namespace_request_cancel(request):
    if request.method == "POST":
        namespace_request_id = request.params.get("namespace-request-id")
        if namespace_request_id:
            namespace_request = get_namespace_request_by_id(
                request.dbsession, namespace_request_id
            )
            if namespace_request and namespace_request.user == request.user:
                request.dbsession.delete(namespace_request)
                request.dbsession.flush()
    return HTTPFound(get_referer_or_home(request))


@view_config(route_name="namespace-dump-to-json")
@user_required()
@reject_stand_alone
def namespace_dump_to_json(request):

    if not request.user in request.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_referer_or_home(request))

    response = Response(body=dumps(request.namespace.dict_dump))
    response.headerlist = []
    # allow Javascript from other domains to download this resource.
    response.headerlist.extend(
        (("Access-Control-Allow-Origin", "*"), ("Content-Type", "application/json"))
    )
    return response


@view_config(route_name="basic-user-delete-account", renderer="confirm-delete-account.j2")
@view_config(route_name="embed-user-delete-account", renderer="confirm-delete-account.j2")
@user_required()
def delete_account(request):
    """Delete the authenticated user's account after confirmation."""
    if request.method == "POST":
        confirm = request.params.get("confirm-delete", "")
        if confirm == "DELETE":
            request.user.anonymize_account()
            request.session.flash(
                ("Your account has been deleted and your data has been anonymized.", "success")
            )
            request.session["authenticated_user_id"] = None
            return HTTPFound("/")
        else:
            request.session.flash(
                ('You must type "DELETE" to confirm account deletion.', "error")
            )
    return {"the_title": "Delete My Account"}


@view_config(route_name="basic-user-export-data")
@view_config(route_name="embed-user-export-data")
@user_required()
def export_user_data(request):
    """Export the authenticated user's data as a JSON download."""
    data = request.user.export_user_data()
    body = dumps(data, indent=2)
    response = Response(body=body)
    response.content_type = "application/json"
    response.content_disposition = 'attachment; filename="remarkbox-data-export.json"'
    return response


@view_config(route_name="basic-namespace-delete", renderer="confirm-delete-namespace.j2")
@view_config(route_name="embed-namespace-delete", renderer="confirm-delete-namespace.j2")
@user_required()
@reject_stand_alone
def delete_namespace(request):
    """Delete a namespace and all associated data after confirmation."""
    if not request.user in request.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_referer_or_home(request))
    namespace_name = request.namespace.name
    if request.method == "POST":
        confirm = request.params.get("confirm-delete", "")
        if confirm == namespace_name:
            delete_namespace_cascade(request.dbsession, request.namespace)
            request.session.flash(
                ('Namespace "{}" and all associated data have been permanently deleted.'.format(namespace_name), "success")
            )
            return HTTPFound("/")
        else:
            request.session.flash(
                ('You must type the namespace name "{}" to confirm deletion.'.format(namespace_name), "error")
            )
    return {"the_title": "Delete Namespace: {}".format(namespace_name)}
