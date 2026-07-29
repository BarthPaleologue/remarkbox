"""Render a namespace theme from a palette.

This module owns the CSS: one template, light and dark, driven entirely by
CSS custom properties. What it does **not** own is where the colours come
from — that is a `palette`, a small dict of hues and saturations.

Two sources exist:

* `hash_palette(name)` — deterministic from a SHA-256 of the namespace name.
  Unique, reproducible, and meaningless: a cooking forum and a malware forum
  get unrelated hues by coincidence.
* `remarkbox.lib.theme_palette.choose_palette(...)` — asks our Hermes model to
  pick colours that suit what the community is actually about, then clamps and
  contrast-checks the result.

Keeping the model out of this file is deliberate. It never emits CSS; it
returns numbers we validate. Model-authored CSS served to every visitor would
be an injection surface — attribute selectors plus `background-image` can
exfiltrate page content — and no model can promise a contrast ratio.
"""

import hashlib
import struct


def _name_to_hue(name):
    """Deterministically map a namespace name to a hue (0-360)."""
    h = hashlib.sha256(name.encode("utf-8")).digest()
    return struct.unpack(">H", h[:2])[0] % 360


def _name_to_seed(name):
    """Get multiple deterministic values from a name."""
    h = hashlib.sha256(name.encode("utf-8")).digest()
    values = struct.unpack(">8H", h[:16])
    return values


def hash_palette(namespace_name):
    """Derive a palette deterministically from a namespace name.

    Our fallback, and what every namespace used before palettes were a
    separate concept. Same name always yields the same colours.
    """
    seed = _name_to_seed(namespace_name)

    # Primary hue from name
    hue = seed[0] % 360
    # Secondary hue offset (analogous or complementary)
    hue_offset = 30 + (seed[1] % 30)  # 30-60 degree offset
    secondary_hue = (hue + hue_offset) % 360
    # Accent hue
    accent_hue = (hue + 180 + (seed[2] % 40 - 20)) % 360  # near-complementary

    # Saturation variance
    sat_base = 40 + (seed[3] % 25)  # 40-65%

    return {
        "hue": hue,
        "secondary_hue": secondary_hue,
        "accent_hue": accent_hue,
        "sat_base": sat_base,
        "source": "hash",
    }


# Lightness values the CSS template uses, per mode. Swatches derive from these
# so a preview shows the colours a visitor will actually see rather than an
# approximation that drifts when the template changes.
_SWATCH_LIGHTNESS = {
    "light": {
        "bg": ("hue", "sat_bg", 97),
        "bg_card": ("hue", "sat_bg", 100),
        "text": ("hue", "sat_base", 15),
        "text_muted": ("hue", "sat_muted", 55),
        "link": ("accent_hue", "sat_link", 40),
        "accent": ("accent_hue", "sat_accent", 45),
        "border": ("hue", "sat_muted", 85),
    },
    "dark": {
        "bg": ("hue", "sat_dark", 10),
        "bg_card": ("hue", "sat_dark", 14),
        "text": ("hue", "sat_bg", 90),
        "text_muted": ("hue", "sat_muted", 50),
        "link": ("accent_hue", "sat_link", 65),
        "accent": ("accent_hue", "sat_accent", 55),
        "border": ("hue", "sat_muted", 25),
    },
}


def derived_saturations(sat_base):
    """The saturations our CSS template computes from `sat_base`."""
    return {
        "sat_base": sat_base,
        "sat_bg": max(sat_base - 25, 5),
        "sat_muted": max(sat_base - 15, 10),
        "sat_link": min(sat_base + 15, 75),
        "sat_accent": min(sat_base + 20, 80),
        "sat_dark": max(sat_base - 30, 8),
    }


def palette_swatches(palette):
    """Return the palette's key colours as hex, for light and dark mode.

    HSL stays our internal representation — it is what lets us vary lightness
    for two modes and turn saturation down for contrast. Hex is what a theme
    editor, colour picker, or export wants, so we convert at the edge.
    """
    from remarkbox.lib.color import hsl_to_hex

    hue = int(palette.get("hue", 0)) % 360
    accent_hue = int(palette.get("accent_hue", (hue + 180) % 360)) % 360
    sats = derived_saturations(max(0, min(int(palette.get("sat_base", 50)), 100)))
    hues = {"hue": hue, "accent_hue": accent_hue}

    out = {}
    for mode, entries in _SWATCH_LIGHTNESS.items():
        out[mode] = {
            name: hsl_to_hex(hues[hue_key], sats[sat_key], lightness)
            for name, (hue_key, sat_key, lightness) in entries.items()
        }
    return out


def generate_theme_css(namespace_name, palette=None):
    """Render a complete CSS theme for a namespace.

    Args:
        namespace_name: The namespace name (e.g. "meta.remarkbox.com")
        palette: optional dict with `hue`, `secondary_hue`, `accent_hue` and
                 `sat_base`. Defaults to `hash_palette(namespace_name)`, so
                 existing callers are unaffected.

    Returns:
        CSS string with custom properties for light and dark modes.
    """
    if palette is None:
        palette = hash_palette(namespace_name)

    # Clamp here as well as at the source: this function renders CSS, and it
    # must not emit nonsense however it was called.
    hue = int(palette.get("hue", 0)) % 360
    secondary_hue = int(palette.get("secondary_hue", (hue + 40) % 360)) % 360
    accent_hue = int(palette.get("accent_hue", (hue + 180) % 360)) % 360
    sat_base = max(0, min(int(palette.get("sat_base", 50)), 100))

    css = '''/* Auto-generated theme for {name} */
/* Deterministic: regenerating from the same name produces identical output */

:root,
.theme-light {{
    --rb-bg: hsl({hue}, {sat_bg}%, 97%);
    --rb-bg-card: hsl({hue}, {sat_bg}%, 100%);
    --rb-bg-nested: hsl({hue}, {sat_bg}%, 96%);
    --rb-bg-code: hsl({hue}, {sat_bg}%, 94%);
    --rb-text: hsl({hue}, {sat_base}%, 15%);
    --rb-text-secondary: hsl({hue}, {sat_muted}%, 35%);
    --rb-text-muted: hsl({hue}, {sat_muted}%, 55%);
    --rb-link: hsl({accent_hue}, {sat_link}%, 40%);
    --rb-link-hover: hsl({accent_hue}, {sat_link}%, 30%);
    --rb-link-visited: hsl({secondary_hue}, {sat_muted}%, 45%);
    --rb-border: hsl({hue}, {sat_muted}%, 85%);
    --rb-border-light: hsl({hue}, {sat_muted}%, 91%);
    --rb-accent: hsl({accent_hue}, {sat_accent}%, 45%);
    --rb-accent-hover: hsl({accent_hue}, {sat_accent}%, 35%);
    --rb-accent-text: hsl({accent_hue}, 5%, 100%);
    --rb-blockquote-border: hsl({secondary_hue}, {sat_base}%, 70%);
    --rb-avatar-border: hsl({hue}, {sat_muted}%, 80%);
    --rb-shadow: 0 1px 3px hsla({hue}, {sat_muted}%, 30%, 0.08);
}}

@media (prefers-color-scheme: dark) {{
    :root:not(.theme-light) {{
        --rb-bg: hsl({hue}, {sat_dark}%, 10%);
        --rb-bg-card: hsl({hue}, {sat_dark}%, 14%);
        --rb-bg-nested: hsl({hue}, {sat_dark}%, 12%);
        --rb-bg-code: hsl({hue}, {sat_dark}%, 18%);
        --rb-text: hsl({hue}, {sat_bg}%, 90%);
        --rb-text-secondary: hsl({hue}, {sat_muted}%, 70%);
        --rb-text-muted: hsl({hue}, {sat_muted}%, 50%);
        --rb-link: hsl({accent_hue}, {sat_link}%, 65%);
        --rb-link-hover: hsl({accent_hue}, {sat_link}%, 75%);
        --rb-link-visited: hsl({secondary_hue}, {sat_muted}%, 60%);
        --rb-border: hsl({hue}, {sat_muted}%, 25%);
        --rb-border-light: hsl({hue}, {sat_muted}%, 20%);
        --rb-accent: hsl({accent_hue}, {sat_accent}%, 55%);
        --rb-accent-hover: hsl({accent_hue}, {sat_accent}%, 65%);
        --rb-accent-text: hsl({accent_hue}, 5%, 10%);
        --rb-blockquote-border: hsl({secondary_hue}, {sat_base}%, 40%);
        --rb-avatar-border: hsl({hue}, {sat_muted}%, 35%);
        --rb-shadow: 0 1px 3px hsla({hue}, {sat_muted}%, 5%, 0.3);
    }}
}}

.theme-dark {{
    --rb-bg: hsl({hue}, {sat_dark}%, 10%);
    --rb-bg-card: hsl({hue}, {sat_dark}%, 14%);
    --rb-bg-nested: hsl({hue}, {sat_dark}%, 12%);
    --rb-bg-code: hsl({hue}, {sat_dark}%, 18%);
    --rb-text: hsl({hue}, {sat_bg}%, 90%);
    --rb-text-secondary: hsl({hue}, {sat_muted}%, 70%);
    --rb-text-muted: hsl({hue}, {sat_muted}%, 50%);
    --rb-link: hsl({accent_hue}, {sat_link}%, 65%);
    --rb-link-hover: hsl({accent_hue}, {sat_link}%, 75%);
    --rb-link-visited: hsl({secondary_hue}, {sat_muted}%, 60%);
    --rb-border: hsl({hue}, {sat_muted}%, 25%);
    --rb-border-light: hsl({hue}, {sat_muted}%, 20%);
    --rb-accent: hsl({accent_hue}, {sat_accent}%, 55%);
    --rb-accent-hover: hsl({accent_hue}, {sat_accent}%, 65%);
    --rb-accent-text: hsl({accent_hue}, 5%, 10%);
    --rb-blockquote-border: hsl({secondary_hue}, {sat_base}%, 40%);
    --rb-avatar-border: hsl({hue}, {sat_muted}%, 35%);
    --rb-shadow: 0 1px 3px hsla({hue}, {sat_muted}%, 5%, 0.3);
}}

/* Apply theme variables to remarkbox elements */
body {{
    background-color: var(--rb-bg);
    color: var(--rb-text);
}}

.node {{
    background-color: var(--rb-bg-card);
    border-color: var(--rb-border-light);
    box-shadow: var(--rb-shadow);
}}

.node .node {{
    background-color: var(--rb-bg-nested);
}}

a {{
    color: var(--rb-link);
}}

a:hover {{
    color: var(--rb-link-hover);
}}

a:visited {{
    color: var(--rb-link-visited);
}}

.text-muted, .rb-meta {{
    color: var(--rb-text-muted);
}}

pre, code {{
    background-color: var(--rb-bg-code);
    border-color: var(--rb-border);
}}

blockquote {{
    border-left-color: var(--rb-blockquote-border);
    color: var(--rb-text-secondary);
}}

.rb-submit, .btn-primary {{
    background-color: var(--rb-accent);
    color: var(--rb-accent-text);
    border-color: var(--rb-accent);
}}

.rb-submit:hover, .btn-primary:hover {{
    background-color: var(--rb-accent-hover);
    border-color: var(--rb-accent-hover);
}}

.nested-avatar {{
    border-color: var(--rb-avatar-border);
}}

hr {{
    border-color: var(--rb-border-light);
}}

textarea, input[type="text"], input[type="email"] {{
    background-color: var(--rb-bg-card);
    color: var(--rb-text);
    border-color: var(--rb-border);
}}

textarea:focus, input:focus {{
    border-color: var(--rb-accent);
    outline-color: var(--rb-accent);
}}
'''.format(
        name=namespace_name,
        hue=hue,
        secondary_hue=secondary_hue,
        accent_hue=accent_hue,
        sat_base=sat_base,
        sat_bg=max(sat_base - 25, 5),
        sat_muted=max(sat_base - 15, 10),
        sat_link=min(sat_base + 15, 75),
        sat_accent=min(sat_base + 20, 80),
        sat_dark=max(sat_base - 30, 8),
    )

    return css
