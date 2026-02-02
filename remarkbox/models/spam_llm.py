"""
LLM-based relevance checking for spam detection.

Uses an OpenAI-compatible inference endpoint (e.g. hermes.ai.unturf.com)
to check whether a post is relevant to its context (namespace or thread).

Configuration (from .ini):
    spam.llm.enabled = true
    spam.llm.endpoint = https://hermes.ai.unturf.com/v1/chat/completions
    spam.llm.model = adamo1139/Hermes-3-Llama-3.1-8B-FP8-Dynamic
    spam.llm.timeout = 5
"""

import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

# Defaults
DEFAULT_ENDPOINT = "https://hermes.ai.unturf.com/v1/chat/completions"
DEFAULT_MODEL = "adamo1139/Hermes-3-Llama-3.1-8B-FP8-Dynamic"
DEFAULT_TIMEOUT = 5  # seconds


def _llm_request(endpoint, model, messages, timeout):
    """Make a chat completion request to an OpenAI-compatible endpoint."""
    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.1,
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, Exception) as e:
        log.warning("LLM relevance check failed: %s", e)
        return None


def check_thread_relevance(namespace_name, namespace_description, title, content, settings=None):
    """Check if a new thread is relevant to the namespace.

    Args:
        namespace_name: The namespace (e.g. "meta.remarkbox.com")
        namespace_description: The namespace description (may be None)
        title: The thread title
        content: The thread body text
        settings: Pyramid registry settings dict

    Returns:
        (relevant, explanation) where relevant is True/False/None (None = LLM unavailable)
    """
    if not _is_enabled(settings):
        return None, None

    endpoint, model, timeout = _get_config(settings)

    ns_context = namespace_name
    if namespace_description:
        ns_context = "{} ({})".format(namespace_name, namespace_description)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a content moderation assistant. Your job is to determine if "
                "a new discussion thread is relevant to the site it is being posted on. "
                "Respond with exactly 'RELEVANT' or 'IRRELEVANT' on the first line, "
                "followed by a brief one-sentence explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                "Site: {ns}\n\n"
                "New thread title: {title}\n\n"
                "Thread content (first 500 chars):\n{content}\n\n"
                "Is this thread relevant to this site?"
            ).format(
                ns=ns_context,
                title=title or "(no title)",
                content=(content or "")[:500],
            ),
        },
    ]

    response = _llm_request(endpoint, model, messages, timeout)
    return _parse_verdict(response)


def check_reply_relevance(thread_title, thread_content, parent_content,
                          reply_content, page_url=None, namespace_name=None,
                          settings=None):
    """Check if a reply is relevant to the thread.

    Args:
        thread_title: Root thread title
        thread_content: Root thread body (first 300 chars)
        parent_content: Direct parent node body (first 300 chars)
        reply_content: The reply being checked
        page_url: Parent page URL if this is an embed-mode thread (may be None)
        namespace_name: Namespace/site name (may be None)
        settings: Pyramid registry settings dict

    Returns:
        (relevant, explanation) where relevant is True/False/None (None = LLM unavailable)
    """
    if not _is_enabled(settings):
        return None, None

    endpoint, model, timeout = _get_config(settings)

    # Build context block -- include parent page info when available (embed mode)
    context_parts = []
    if namespace_name:
        context_parts.append("Site: {}".format(namespace_name))
    if page_url:
        context_parts.append("Parent page URL: {}".format(page_url))
    if thread_title:
        context_parts.append("Thread title: {}".format(thread_title))
    if thread_content:
        context_parts.append(
            "Thread content (first 300 chars):\n{}".format(
                (thread_content or "")[:300]
            )
        )
    if parent_content:
        context_parts.append(
            "Parent comment (first 300 chars):\n{}".format(
                (parent_content or "")[:300]
            )
        )

    user_msg = "{context}\n\nNew reply (first 500 chars):\n{reply}\n\n" \
               "Is this reply relevant to the discussion?".format(
                   context="\n\n".join(context_parts),
                   reply=(reply_content or "")[:500],
               )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a content moderation assistant. Your job is to determine if "
                "a reply is relevant to the discussion thread it is being posted in. "
                "Off-topic spam, promotional content, and gibberish should be marked irrelevant. "
                "Respond with exactly 'RELEVANT' or 'IRRELEVANT' on the first line, "
                "followed by a brief one-sentence explanation."
            ),
        },
        {
            "role": "user",
            "content": user_msg,
        },
    ]

    response = _llm_request(endpoint, model, messages, timeout)
    return _parse_verdict(response)


def _is_enabled(settings):
    """Check if LLM relevance checking is enabled."""
    if not settings:
        return False
    return settings.get("spam.llm.enabled", "false").strip().lower() in ("true", "1", "yes")


def _get_config(settings):
    """Extract LLM config from settings."""
    endpoint = settings.get("spam.llm.endpoint", DEFAULT_ENDPOINT)
    model = settings.get("spam.llm.model", DEFAULT_MODEL)
    timeout = int(settings.get("spam.llm.timeout", DEFAULT_TIMEOUT))
    return endpoint, model, timeout


def _parse_verdict(response):
    """Parse a RELEVANT/IRRELEVANT response from the LLM."""
    if not response:
        return None, None

    first_line = response.split("\n")[0].strip().upper()
    explanation = response.split("\n", 1)[1].strip() if "\n" in response else ""

    if "IRRELEVANT" in first_line:
        return False, explanation
    elif "RELEVANT" in first_line:
        return True, explanation

    # Ambiguous response -- treat as inconclusive
    return None, response
