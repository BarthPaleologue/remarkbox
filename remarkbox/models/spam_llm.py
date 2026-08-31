"""
LLM-based relevance checking for spam detection.

Uses an OpenAI-compatible inference endpoint (e.g. hermes.ai.unturf.com)
to check whether a post is relevant to its context (namespace or thread).

The model id is detected from the endpoint's /v1/models rather than taken
from settings; spam.llm.model is only a fallback for when that lookup fails.
Reasoning is disabled per request so the verdict lands on the first line.

Configuration (from .ini):
    spam.llm.enabled = true
    spam.llm.endpoint = https://hermes.ai.unturf.com/v1/chat/completions
    spam.llm.model = solidrust/Hermes-3-Llama-3.1-8B-AWQ   # fallback only
    spam.llm.timeout = 5
"""

import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

# Defaults
DEFAULT_ENDPOINT = "https://hermes.ai.unturf.com/v1/chat/completions"
DEFAULT_MODEL = "solidrust/Hermes-3-Llama-3.1-8B-AWQ"
DEFAULT_TIMEOUT = 5  # seconds

# Cache for a server-discovered model id (see _discover_model).
_discovered_model = None


def _post_chat(endpoint, model, messages, timeout):
    """POST a chat completion to an OpenAI-compatible endpoint. May raise."""
    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": 150,
        # Greedy decoding: a relevance classifier must be deterministic for
        # identical input, or moderation outcomes (and tests) become dice.
        "temperature": 0.0,
        # Reasoning models prepend a thinking monologue to their answer, which
        # buries the verdict our parser reads. Both keys were verified against
        # vLLM to suppress it; we send both because servers differ on which
        # they honour, and ignore keys they do not know.
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _choose_model(served, configured):
    """Pick which of the served model ids to classify with.

    Taking served[0] blindly is what handed this classifier to a reasoning
    model: whatever the server happened to list first silently became our
    moderator. So prefer the operator's configured id whenever upstream
    actually serves it, fall back to the only id on offer, and when a server
    lists several without our configured one among them, sort so the choice
    is at least reproducible and say so out loud.
    """
    if not served:
        return None
    if configured and configured in served:
        return configured
    if len(served) == 1:
        return served[0]
    choice = sorted(served)[0]
    log.warning(
        "LLM endpoint serves %d models %s and none match configured %r; "
        "classifying with %r",
        len(served), served, configured, choice,
    )
    return choice


def _discover_model(endpoint, timeout, configured=None):
    """Ask an OpenAI-compatible server which model it actually serves.

    Inference servers swap model builds (quantization, publisher) without
    warning, so upstream is the authority on which ids exist and the
    configured id is only a preference among them. The result is cached for
    the process; `forget_discovered_model` clears it.
    """
    global _discovered_model
    if _discovered_model:
        return _discovered_model
    models_uri = endpoint.replace("/chat/completions", "/models")
    try:
        resp = urllib.request.urlopen(models_uri, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
        served = [m["id"] for m in data.get("data", []) if m.get("id")]
    except Exception as e:
        log.warning("LLM model discovery failed: %s", e)
        return None

    _discovered_model = _choose_model(served, configured)
    if _discovered_model is None:
        log.warning("LLM endpoint %s serves no models", models_uri)
    return _discovered_model


def forget_discovered_model():
    """Drop the cached model id so the next call rediscovers it."""
    global _discovered_model
    _discovered_model = None


def current_model():
    """Which model id we last resolved, or None if we never got one.

    Recorded alongside each spam decision so a model swapped in under us is
    visible in our telemetry rather than inferred weeks later.
    """
    return _discovered_model


def _llm_request(endpoint, model, messages, timeout):
    """Make a chat completion request to an OpenAI-compatible endpoint.

    The model served upstream is detected from /v1/models rather than trusted
    from settings, so a model swap heals itself without a config change.
    """
    served = _discover_model(endpoint, timeout, configured=model) or model
    try:
        return _post_chat(endpoint, served, messages, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Our cached id went stale mid-process: rediscover once and retry.
            forget_discovered_model()
            fresh = _discover_model(endpoint, timeout, configured=model)
            if fresh and fresh != served:
                log.warning(
                    "LLM model %s not served; retrying with %s", served, fresh
                )
                try:
                    return _post_chat(endpoint, fresh, messages, timeout)
                except Exception as retry_error:
                    log.warning("LLM relevance check failed: %s", retry_error)
                    return None
        log.warning("LLM relevance check failed: %s", e)
        return None
    except Exception as e:
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
                "You are a spam filter for a discussion site. Decide whether "
                "a new thread was posted to exploit that site or to take part "
                "in it. Judge intent, not topic. "
                "Answer IRRELEVANT when a thread exists to extract value from "
                "an audience that did not ask for it: advertising a product or "
                "service, driving traffic to a site the author benefits from, "
                "search-engine link placement, deception or impersonation, or "
                "bulk automated text. A promotional pitch stays spam even when "
                "its subject matter is close to the site's own. "
                "Answer RELEVANT when a person is genuinely addressing this "
                "community, including when they are off topic, mistaken, "
                "brief, opinionated or new. Wandering off topic is a "
                "moderator's business, not a spam filter's. "
                "When in doubt answer RELEVANT: wrongly flagging turns away a "
                "real person, while a missed one is tidied up later. "
                "Respond with exactly 'RELEVANT' or 'IRRELEVANT' on the first "
                "line, followed by a brief one-sentence explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                "Site: {ns}\n\n"
                "New thread title: {title}\n\n"
                "Thread content (first 500 chars):\n{content}\n\n"
                "Is this thread spam?"
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
               "Is this reply spam?".format(
                   context="\n\n".join(context_parts),
                   reply=(reply_content or "")[:500],
               )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a spam filter for a discussion site. Decide whether "
                "a reply is spam. "
                "Spam means content posted to exploit the thread rather than "
                "take part in it: unsolicited advertising, link farming, "
                "promotion of a product or site to an audience that did not "
                "ask for it, deception, or automated junk. "
                "Anything a genuine participant might write is not spam, even "
                "when it wanders off topic. Jokes, sarcasm, emoji, agreement, "
                "tangents, personal asides and links shared in good faith "
                "among people already talking are ordinary conversation. "
                "Digression is not spam. Being brief, informal or "
                "unsubstantive is not spam. "
                "Answer IRRELEVANT only for spam, not for a reply that is "
                "merely off topic. When in doubt answer RELEVANT: a wrongly "
                "flagged reply silences a real person, while a missed one is "
                "tidied up later by a moderator. "
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


def health_check(settings):
    """Classify a known-relevant canary and report what the pipeline did.

    Both failures this module has had degraded to a safe default instead of
    raising, so nothing alerted for weeks. This asks the whole path -- reach
    the endpoint, pick a model, get a readable verdict -- to prove itself,
    and turns "quietly inert" into something a monitor can see.

    Returns a dict with `ok`, `model`, `verdict` and `detail`.
    """
    endpoint, model, timeout = _get_config(settings)
    forget_discovered_model()

    served = _discover_model(endpoint, timeout, configured=model)
    if served is None:
        return {
            "ok": False,
            "model": None,
            "verdict": None,
            "detail": "model discovery failed against {}".format(endpoint),
        }

    messages = [
        {
            "role": "system",
            "content": (
                "You are a content moderation assistant. Respond with exactly "
                "'RELEVANT' or 'IRRELEVANT' on the first line, followed by a "
                "brief one-sentence explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                "Site: example.com, a blog about beekeeping.\n"
                "Thread: How do I overwinter a hive?\n"
                "New reply: Wrap the hive and leave them enough honey stores.\n"
                "Is this reply relevant to the discussion?"
            ),
        },
    ]

    raw = _llm_request(endpoint, served, messages, timeout)
    if raw is None:
        return {
            "ok": False,
            "model": served,
            "verdict": None,
            "detail": "no response from endpoint",
        }

    verdict, _ = _parse_verdict(raw)
    if verdict is None:
        return {
            "ok": False,
            "model": served,
            "verdict": None,
            "detail": "verdict unparseable; first line was {!r}".format(
                raw.strip().split("\n")[0][:120]
            ),
        }
    if verdict is not True:
        return {
            "ok": False,
            "model": served,
            "verdict": verdict,
            "detail": "canary is plainly on topic but was judged irrelevant",
        }
    return {
        "ok": True,
        "model": served,
        "verdict": True,
        "detail": "endpoint reachable, model resolved, verdict readable",
    }


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

    # Ambiguous response -- treat as inconclusive. Say so loudly: callers act
    # only on a False verdict, so an unreadable answer disables this check
    # rather than breaking it. That is exactly how a reasoning model sat here
    # unnoticed, answering every question with a monologue.
    log.warning(
        "LLM verdict unparseable; relevance check inert for this post. "
        "First line was %r",
        first_line[:120],
    )
    return None, response
