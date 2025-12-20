def includeme(config):
    # shared routes
    config.add_static_view("static", "static", cache_max_age=3600)

    config.add_route("favicon", "/favicon.ico")
    config.add_route("robots", "/robots.txt")
    config.add_route("embed-iframe", "/embed-iframe.txt")
    config.add_route("embed-iframe-min", "/embed-iframe-min.txt")

    # stripe: payment processing via Stripe Checkout
    config.add_route("billing", "/billing")
    config.add_route("create-checkout", "/billing/checkout")
    config.add_route("billing-success", "/billing/success")
    config.add_route("stripe-webhook", "/webhook/stripe")

    # slack: bot notifications and oauth.
    config.add_route("oauth-slack", "/oauth/slack")
    config.add_route("oauth-slack-delete", "/oauth/slack/delete")

    # todo: if namespace.public == False:
    #       lock this routes down to only load for namespace owners
    config.add_route("home", "/")

    config.add_route("sitemap", "/all.sitemap.xml")
    config.add_route("sitemap2", "/ns/{namespace}/all.sitemap.xml")

    config.add_route("namespace-dump-to-json", "/ns/{namespace}/dump.json")

    # allows us to dynamically generate CSS regarding nesting based on
    # the avatar_size configured in config file (move to Namespace settings?)
    config.add_route("dynamic-remarkbox-css", "/dynamic-remarkbox.css")

    config.add_route("search", "/search")

    config.add_route("setup", "/setup")
    config.add_route("setup-namespace-request-cancel", "/nsr/cancel")

    config.add_route("log-out", "/log-out")

    config.add_route("preview-post", "/preview-post")

    config.add_route("new", "/new")

    config.add_route("watch", "/watch")
    config.add_route("unwatch", "/unwatch")
    config.add_route("update-watching", "/update-watching")

    # lock and unlock a thread.
    config.add_route("lock", "/lock")
    config.add_route("unlock", "/unlock")

    # Given a node_id redirect to the node's root.
    config.add_route("redirect-to-root", "/r/{node_id}")

    # superfly admins: locked down routes.
    config.add_route("topsecret-namespace-requests", "/topsecret/namespace-requests")
    config.add_route("topsecret-namespace-owners", "/topsecret/namespace-owners")
    config.add_route("topsecret-namespaces", "/topsecret/namespaces")
    config.add_route("topsecret-notifications", "/topsecret/notifications")
    config.add_route("topsecret-nodes", "/topsecret/nodes")
    config.add_route("topsecret", "/topsecret")

    # embed routes:
    config.add_route("embed-join-or-log-in", "/embed/ns/{namespace}/join-or-log-in")
    config.add_route("embed-verification-challenge", "/embed/ns/{namespace}/verification-challenge")

    config.add_route("embed-log-out", "/embed/ns/{namespace}/log-out")

    config.add_route("embed-namespace-nodes", "/embed/ns/{namespace}/nodes")
    config.add_route("embed-namespace-settings", "/embed/ns/{namespace}/settings")
    config.add_route("embed-namespace-import-comments", "/embed/ns/{namespace}/import-comments")
    config.add_route(
        "embed-namespace-stylesheet", "/embed/ns/{namespace}/{filename}.css"
    )
    config.add_route("embed-namespace", "/embed/ns/{namespace}")

    config.add_route("embed-user-settings", "/embed/ns/{namespace}/u/settings")
    config.add_route("embed-user-watching", "/embed/ns/{namespace}/u/watching")
    config.add_route("embed-user-notifications", "/embed/ns/{namespace}/u/notifications")
    config.add_route("embed-user", "/embed/ns/{namespace}/u/{user_name}")

    config.add_route("embed-verify", "/embed/ns/{namespace}/{node_id}/verify")
    config.add_route("embed-disable", "/embed/ns/{namespace}/{node_id}/disable")
    config.add_route("embed-enable", "/embed/ns/{namespace}/{node_id}/enable")
    config.add_route("embed-approve", "/embed/ns/{namespace}/{node_id}/approve")
    config.add_route("embed-deny", "/embed/ns/{namespace}/{node_id}/deny")
    config.add_route("embed-edit", "/embed/ns/{namespace}/{node_id}/edit")
    config.add_route("embed-reply", "/embed/ns/{namespace}/reply")
    config.add_route("embed-reply2", "/embed/ns/{namespace}/{node_id}/reply")
    config.add_route("embed-show-node2", "/embed/ns/{namespace}/{node_id}")

    config.add_route("embed-show-count", "/embed/count")
    config.add_route("embed-show-node", "/embed")
    config.add_route("embed-show-node3", "/embed/{node_id}")

    # basic routes:
    config.add_route("basic-join-or-log-in", "/join-or-log-in")

    config.add_route("basic-verification-challenge", "/verification-challenge")

    config.add_route("basic-namespace-nodes", "/ns/{namespace}/nodes")
    config.add_route("basic-namespace-settings", "/ns/{namespace}/settings")
    config.add_route("basic-namespace-import-comments", "/ns/{namespace}/import-comments")
    config.add_route("basic-namespace-stats-json", "/ns/{namespace}/stats.json")
    config.add_route("basic-namespace-stylesheet", "/ns/{namespace}/{filename}.css")
    config.add_route("basic-namespace-threads-rss", "/ns/{namespace}.threads.xml")
    config.add_route("basic-namespace-nodes-rss", "/ns/{namespace}.nodes.xml")
    config.add_route(
        "basic-namespace-pending-rss", "/ns/{namespace}.pending.{feed_key}.xml"
    )
    config.add_route("basic-namespace", "/ns/{namespace}")

    config.add_route("basic-user-settings", "/u/settings")
    config.add_route("basic-user-watching", "/u/watching")
    config.add_route("basic-user-notifications", "/u/notifications")
    config.add_route("basic-user", "/u/{user_name}")

    config.add_route("basic-verify", "/{node_id}/verify")
    config.add_route("basic-disable", "/{node_id}/disable")
    config.add_route("basic-enable", "/{node_id}/enable")
    config.add_route("basic-approve", "/{node_id}/approve")
    config.add_route("basic-deny", "/{node_id}/deny")
    config.add_route("basic-edit", "/{node_id}/edit")
    config.add_route("basic-edit2", "/{node_id}/{slug:.*}/edit")
    config.add_route("basic-reply", "/{node_id}/reply")
    config.add_route("basic-reply2", "/{node_id}/{slug:.*}/reply")
    config.add_route("basic-show-count", "/{node_id}/count")
    config.add_route("basic-show-count2", "/{node_id}/{slug:.*}/count")
    config.add_route("basic-show-node", "/{node_id}")
    config.add_route("basic-show-node2", "/{node_id}/{slug:.*}")  # must be last.
