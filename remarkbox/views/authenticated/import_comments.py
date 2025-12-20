from pyramid.view import view_config
from pyramid.httpexceptions import HTTPFound
import json
import tempfile
import os
from datetime import datetime

from remarkbox.models import (
    User,
    UserSurrogate,
    generate_user_name,
    get_user_by_email,
    get_user_surrogate_by_name,
    get_or_create_node_by_uri,
    is_user_name_valid,
    is_user_name_available,
)

from remarkbox.views import get_referer_or_home, user_required

try:
    unicode("")
except:
    from six import u as unicode


def generate_password(size=32):
    """Return a system generated password"""
    from random import choice
    letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = "0123456789"
    pool = letters + digits
    return "".join([choice(pool) for i in range(size)])


def generate_group_prefix_from_namespace(namespace_name):
    """
    Generate a short, safe group prefix from namespace domain.
    Takes first letters of domain parts, max 6 chars.
    Example: russell.ballestrini.net -> rb, my.remarkbox.com -> mrc
    """
    # Remove common TLDs and split on dots
    domain = namespace_name.lower()
    # Remove www prefix if present
    if domain.startswith('www.'):
        domain = domain[4:]

    # Split on dots and filter out common TLDs
    parts = domain.split('.')
    # Remove TLDs like com, org, net, io, etc
    tlds = {'com', 'org', 'net', 'io', 'co', 'edu', 'gov', 'mil', 'int'}
    parts = [p for p in parts if p not in tlds]

    if not parts:
        # Use first 6 chars of full domain if no valid parts
        prefix = ''.join(c for c in namespace_name if c.isalnum())[:6]
        if len(prefix) < 2:
            # Absolutely no valid characters, use hash of namespace
            import hashlib
            prefix = hashlib.md5(namespace_name.encode()).hexdigest()[:6]
        return prefix

    # Strategy 1: Take first letter of each part (e.g., russell.ballestrini -> rb)
    prefix = ''.join(p[0] for p in parts if p)

    # Strategy 2: If too short or just one part, take first few chars
    if len(prefix) < 2 or len(parts) == 1:
        prefix = parts[0][:6]

    # Ensure max 6 chars and only alphanumeric
    prefix = ''.join(c for c in prefix if c.isalnum())[:6]

    # Final safety check - ensure at least 2 chars
    if len(prefix) < 2:
        # Use hash of namespace as last resort
        import hashlib
        prefix = hashlib.md5(namespace_name.encode()).hexdigest()[:6]

    return prefix




@view_config(route_name="basic-namespace-import-comments", renderer="import-comments.j2")
@view_config(route_name="embed-namespace-import-comments", renderer="import-comments.j2")
@user_required()
def import_comments(request):
    """
    Import comments and threads from JSON dumps created by the blog-to-json tool.
    Supports WordPress, Disqus, and pre-formatted JSON exports.
    This view handles file upload and processes the JSON data.
    """

    if not request.user in request.namespace.owners:
        request.session.flash(("You do not own that Namespace.", "error"))
        return HTTPFound(get_referer_or_home(request))

    # Check if namespace already has a locked group postfix
    if request.namespace.import_group_postfix:
        # Use the locked postfix
        default_postfix = request.namespace.import_group_postfix
        postfix_locked = True
    else:
        # Generate default group postfix from namespace
        default_postfix = generate_group_prefix_from_namespace(request.namespace.name)
        postfix_locked = False

    if request.method == "POST":
        # Get the group postfix, allow user to override if not locked
        if postfix_locked:
            group = request.namespace.import_group_postfix
        else:
            group_postfix = request.params.get("group-prefix", "").strip()
            if not group_postfix:
                group_postfix = default_postfix

            # Sanitize: max 6 chars, alphanumeric only
            group = ''.join(c for c in group_postfix if c.isalnum())[:6]
            if not group or len(group) < 2:
                request.session.flash(("Group postfix is required and must be at least 2 alphanumeric characters.", "error"))
                return {
                    "the_title": "Import Comments",
                    "default_prefix": default_postfix,
                    "postfix_locked": postfix_locked,
                }

            # Lock the group postfix in the namespace on first use
            request.namespace.import_group_postfix = group
            request.dbsession.add(request.namespace)
            request.dbsession.flush()

        # Get the uploaded file
        upload_file = request.params.get("json-file", None)

        if upload_file is None or upload_file == b'':
            request.session.flash(("Please select a JSON file to upload.", "error"))
            return {"the_title": "Import Comments"}

        try:
            # Read the uploaded file
            json_content = upload_file.file.read()

            # Parse JSON
            try:
                pages = json.loads(json_content)
            except json.JSONDecodeError as e:
                request.session.flash((f"Invalid JSON file: {str(e)}", "error"))
                return {"the_title": "Import Comments"}

            # Process the import
            users = {}
            user_surrogates = {}
            nodes = {}
            imported_threads = 0
            imported_comments = 0

            for slug, page_data in pages.items():
                comments = page_data.get("comments", [])

                if len(comments) == 0:
                    continue

                uri = page_data.get("link", "")
                if not uri:
                    continue

                # Create the root node for this thread
                root = get_or_create_node_by_uri(request.dbsession, uri)
                root.namespace = request.namespace
                request.dbsession.add(root)
                request.dbsession.flush()
                imported_threads += 1

                for comment in comments:
                    email = comment.get("email", "")

                    user = None
                    user_surrogate = None

                    if not email:
                        # Always create surrogates for comments without email
                        # Use group postfix to make them identifiable
                        author_name = comment.get("author", "Anonymous")
                        # Create full name with group postfix (e.g., "Anonymous-rb-20231122-143045")
                        surrogate_name_with_group = f"{author_name}-{group}"

                        # Check in-memory cache first
                        if surrogate_name_with_group not in user_surrogates:
                            # Check if this surrogate already exists in the database
                            existing_surrogate = get_user_surrogate_by_name(
                                request.dbsession,
                                surrogate_name_with_group,
                                root.namespace
                            )
                            if existing_surrogate:
                                user_surrogates[surrogate_name_with_group] = existing_surrogate
                            else:
                                # Create new surrogate
                                user_surrogates[surrogate_name_with_group] = UserSurrogate(
                                    surrogate_name_with_group,
                                    root.namespace,
                                )
                                request.dbsession.add(user_surrogates[surrogate_name_with_group])
                                request.dbsession.flush()

                        user_surrogate = user_surrogates[surrogate_name_with_group]

                    elif email in users:
                        user = users[email]
                    else:
                        user = get_user_by_email(request.dbsession, email)
                        if user:
                            users[email] = user
                        else:
                            desired_name = (
                                comment.get("author", "Anonymous").replace(" ", "-").replace("_", "-")
                            )
                            # Always append group name to identify imported users
                            desired_name = desired_name + "-" + group

                            if not is_user_name_valid(
                                desired_name
                            ) or not is_user_name_available(
                                request.dbsession, desired_name
                            ):
                                desired_name = generate_user_name(
                                    request.dbsession, desired_name
                                )
                            user = User(email)
                            user.name = unicode(desired_name)
                            users[email] = user

                            request.dbsession.add(user)
                            request.dbsession.flush()

                    # Create the comment node
                    node = root.new_child()
                    node.set_data(unicode(comment.get("content", "")))
                    node.created = int(comment.get("timestamp", 0)) * 1000
                    node.changed = int(comment.get("timestamp", 0)) * 1000

                    if user is not None:
                        node.user = user
                    elif user_surrogate is not None:
                        node.user_surrogate = user_surrogate

                    node.verified = True
                    node.ip_address = comment.get("author_ip", None)
                    nodes[comment.get("id", "")] = node

                    request.dbsession.add(node)
                    request.dbsession.flush()
                    imported_comments += 1

                # Set up parent-child relationships
                for comment in comments:
                    parent_id = comment.get("parent_id")
                    comment_id = comment.get("id", "")
                    if parent_id and nodes.get(comment_id) and nodes.get(parent_id):
                        nodes[comment_id].parent_id = nodes[parent_id].id
                        request.dbsession.add(nodes[comment_id])
                        request.dbsession.flush()

            request.session.flash((
                f"Successfully imported {imported_threads} threads and {imported_comments} comments.",
                "success"
            ))

        except Exception as e:
            request.session.flash((f"Error during import: {str(e)}", "error"))

    return {
        "the_title": "Import Comments",
        "default_prefix": default_postfix,
        "postfix_locked": postfix_locked,
    }
