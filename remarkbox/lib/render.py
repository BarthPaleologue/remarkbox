from .sanitize_html import (
    default_cleaner,
    default_tag_acl,
    markdown_to_raw_html,
    clean_raw_html,
)

import logging

log = logging.getLogger(__name__)


def remarkbox_tag_acl(namespace):
    """
    Returns a tag_acl document, in this form:

    tag_acl = {
        "script": [
            ("type", "math/tex; mode=display", "allow"),
        ],
    }
    """
    # defaultdict which assumes new keys are lists.
    tag_acl = default_tag_acl()

    allow_mathjax_acl = ("type", "math/tex; mode=display", "allow")
    deny_mathjax_acl  = ("type", "math/tex; mode=display", "deny")

    log.info("Building remarkbox_tag_acl.")
    mathjax_acl = deny_mathjax_acl
    if namespace.mathjax:
        log.info("This Namespace has Mathjax enabled.")
        mathjax_acl = allow_mathjax_acl

    tag_acl["script"].append(mathjax_acl)

    return tag_acl


def make_cleaner_from_namespace(namespace):
    """Given a Namespace return a bleach Cleaner object."""
    cleaner = default_cleaner(
        # pass tag_acl for Remarkbox.
        remarkbox_tag_acl(namespace)
    )
    # add some properties onto the cleaner object.
    cleaner.link_protection = namespace.link_protection
    cleaner.mathjax = namespace.mathjax
    cleaner.whitelist_domains.append(namespace.name)
    cleaner.absolute_domain = namespace.name
    return cleaner


def markdown_to_html(data, namespace=None):
    raw_html = markdown_to_raw_html(data, extra_extensions=["mdx_math"])
    if namespace:
        cleaner = make_cleaner_from_namespace(namespace)
    else:
        cleaner = default_cleaner()
    return clean_raw_html(raw_html, cleaner)
