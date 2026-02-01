def serialize_node(node, include_children=False):
    """Serialize a Node model to a dictionary."""
    result = {
        "id": str(node.id),
        "root_id": str(node.root_id) if node.root_id else None,
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "title": node.title,
        "data": node.data,
        "data_html": node.data_html,
        "is_root": node.is_root,
        "depth": node.graph_depth,
        "created": node.created,
        "created_date": node.created_date,
        "created_ago": node.human_created_timestamp,
        "changed": node.changed,
        "changed_date": node.changed_date,
        "changed_ago": node.human_changed_timestamp,
        "disabled": node.disabled,
        "verified": node.verified,
        "locked": node.locked,
        "approved": node.approved,
        "was_edited": node.was_edited,
        "author": serialize_author(node),
    }
    if include_children:
        result["stats"] = node.stats if node.cache else None
    return result


def serialize_author(node):
    """Serialize the author (User or UserSurrogate) of a node."""
    if node.user:
        return {
            "type": "user",
            "id": str(node.user.id),
            "name": node.user.name,
        }
    elif node.user_surrogate:
        return {
            "type": "surrogate",
            "id": str(node.user_surrogate.id),
            "name": node.user_surrogate.name,
        }
    return None


def serialize_namespace_brief(namespace):
    """Serialize minimal namespace info for API responses."""
    return {
        "id": str(namespace.id),
        "name": namespace.name,
        "description": namespace.description,
        "allow_anonymous": namespace.allow_anonymous,
        "node_order": namespace.node_order,
    }
