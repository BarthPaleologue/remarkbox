"""Ask Hermes to choose a colour palette that suits a community.

Runs on the same inference endpoint our spam filter uses (`spam.llm.*`), so
there is no new infrastructure to stand up or configure.

**The model never writes CSS.** It returns four numbers — three hues and a
saturation — which we clamp and contrast-check before
`theme_generator.generate_theme_css` renders them. Two reasons that boundary
matters:

* Model-authored CSS served to every visitor is an injection surface.
  Attribute selectors combined with `background-image` can exfiltrate page
  content, and absolute positioning can overlay real UI. Numbers cannot.
* No model can promise a contrast ratio. Code can compute one, so we do.

Everything fails soft: if the endpoint is disabled, unreachable, slow, or
answers with nonsense, we fall back to `hash_palette` and the community still
gets a theme. Our Hermes endpoint 404'd for weeks earlier this month when its
served model id drifted, so this path assumes failure is normal.
"""

import json
import logging

from remarkbox.lib.color import (
    contrast_ratio,
    hsl_to_hex,
    hsl_to_rgb,
    relative_luminance,
)
from remarkbox.lib.theme_generator import hash_palette
from remarkbox.models.spam_llm import _get_config, _llm_request

log = logging.getLogger(__name__)


# Below this, text on its background is hard to read. WCAG AA for body text is
# 4.5:1; we hold our generated themes to that.
MIN_CONTRAST = 4.5

SETTING_ENABLED = "theme.llm.enabled"


# Colour maths lives in lib/color.py; re-exported so callers that already
# import contrast_ratio from here keep working.
_relative_luminance = relative_luminance
_hsl_to_rgb = hsl_to_rgb


def enforce_contrast(palette):
    """Lower saturation until body text clears `MIN_CONTRAST` on its background.

    `theme_generator` renders text at lightness 15% on a 97% background in
    light mode, and 90% on 10% in dark mode. Those lightness values already do
    most of the work; saturation is what can push a hue into mud. We reduce it
    rather than shift lightness so the palette keeps its character.

    Returns the palette, annotated with the ratio we achieved.
    """
    hue = palette["hue"]
    sat = palette["sat_base"]

    for _ in range(20):
        sat_bg = max(sat - 25, 5)
        light = contrast_ratio((hue, sat, 15), (hue, sat_bg, 97))
        dark = contrast_ratio((hue, sat_bg, 90), (hue, max(sat - 30, 8), 10))
        if light >= MIN_CONTRAST and dark >= MIN_CONTRAST:
            break
        if sat <= 0:
            break
        sat = max(0, sat - 5)

    palette["sat_base"] = sat
    palette["contrast_light"] = round(light, 2)
    palette["contrast_dark"] = round(dark, 2)
    return palette


def _validate(raw, namespace_name):
    """Coerce a model answer into a usable palette, or return None.

    Deliberately strict. A model that returns prose, a hue of 4000, or a
    saturation of -1 gets rejected rather than clamped into something we then
    pretend it chose.
    """
    if not isinstance(raw, dict):
        return None

    try:
        hue = int(raw["hue"])
        secondary = int(raw["secondary_hue"])
        accent = int(raw["accent_hue"])
        sat = int(raw["saturation"])
    except (KeyError, TypeError, ValueError):
        return None

    if not all(0 <= v <= 360 for v in (hue, secondary, accent)):
        return None
    if not 0 <= sat <= 100:
        return None

    palette = {
        "hue": hue % 360,
        "secondary_hue": secondary % 360,
        "accent_hue": accent % 360,
        # Very low saturation reads as broken rather than tasteful, and very
        # high vibrates. Keep the model inside a band that renders well.
        "sat_base": max(20, min(sat, 75)),
        "source": "hermes",
        "rationale": str(raw.get("rationale", ""))[:200],
    }
    return enforce_contrast(palette)


def _is_enabled(settings):
    """Palette generation is opt-in per deployment; it costs a model call."""
    if not settings:
        return False
    return settings.get(SETTING_ENABLED, "false").strip().lower() in (
        "true",
        "1",
        "yes",
    )


def choose_palette(namespace_name, description=None, settings=None):
    """Return a palette for a community, from Hermes when we can.

    Never raises and never returns None: falls back to `hash_palette` so a
    community always has a theme.
    """
    fallback = enforce_contrast(hash_palette(namespace_name))

    if not _is_enabled(settings):
        return fallback

    endpoint, model, timeout = _get_config(settings)

    context = namespace_name
    if description:
        context = "{} — {}".format(namespace_name, description[:300])

    messages = [
        {
            "role": "system",
            "content": (
                "You choose colour palettes for online community forums. "
                "Given a community, reply with ONLY a JSON object, no prose "
                "and no code fence, with exactly these keys: "
                '"hue" (0-360), "secondary_hue" (0-360), "accent_hue" (0-360), '
                '"saturation" (20-75), "rationale" (short phrase). '
                "Choose colours that suit the community's subject matter: warm "
                "earthy tones for cooking, cool blues for technical topics, "
                "muted greens for the outdoors. The accent hue should contrast "
                "with the primary hue so links stand out."
            ),
        },
        {
            "role": "user",
            "content": "Community: {}\n\nChoose its palette.".format(context),
        },
    ]

    response = _llm_request(endpoint, model, messages, timeout)
    if not response:
        log.info("theme palette: no model response for %s, using hash", namespace_name)
        return fallback

    # Models like to wrap JSON in prose or a fence; take the first object.
    text = response.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        log.info("theme palette: no JSON in response for %s, using hash", namespace_name)
        return fallback

    try:
        raw = json.loads(text[start : end + 1])
    except ValueError:
        log.info("theme palette: unparseable JSON for %s, using hash", namespace_name)
        return fallback

    palette = _validate(raw, namespace_name)
    if palette is None:
        log.info("theme palette: rejected model palette for %s, using hash", namespace_name)
        return fallback

    return palette
