"""Colour maths: HSL to RGB to hex, and WCAG contrast.

Pure functions, no CSS and no model. Our themes are authored in HSL because
that is what makes them programmable — hold a hue and vary lightness to get
light and dark modes from one palette, or turn saturation down until text is
readable. Neither is convenient in hex.

Hex is what other things want: swatches in a theme editor, a colour picker's
initial value, an export. So we convert outward at the edge and keep HSL as
our internal representation.
"""


def hsl_to_rgb(hue, saturation, lightness):
    """Convert HSL to an (r, g, b) triple of floats in 0..1.

    `hue` in degrees (wraps), `saturation` and `lightness` in percent (clamped).
    """
    hue = (hue % 360) / 360.0
    saturation = max(0.0, min(saturation / 100.0, 1.0))
    lightness = max(0.0, min(lightness / 100.0, 1.0))

    if saturation == 0:
        return (lightness, lightness, lightness)

    def channel(p, q, t):
        t = t % 1.0
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = (
        lightness * (1 + saturation)
        if lightness < 0.5
        else lightness + saturation - lightness * saturation
    )
    p = 2 * lightness - q
    return (
        channel(p, q, hue + 1 / 3),
        channel(p, q, hue),
        channel(p, q, hue - 1 / 3),
    )


def hsl_to_hex(hue, saturation, lightness):
    """Convert HSL to a `#rrggbb` string.

    Rounds to nearest, so `hsl(0, 0%, 100%)` is `#ffffff` rather than `#fefefe`.
    """
    r, g, b = hsl_to_rgb(hue, saturation, lightness)
    return "#{:02x}{:02x}{:02x}".format(
        int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
    )


def relative_luminance(rgb):
    """WCAG relative luminance for an (r, g, b) triple in 0..1."""
    channels = []
    for c in rgb:
        c = c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        channels.append(c)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hsl_a, hsl_b):
    """WCAG contrast ratio between two HSL colours, 1.0 to 21.0."""
    lum_a = relative_luminance(hsl_to_rgb(*hsl_a))
    lum_b = relative_luminance(hsl_to_rgb(*hsl_b))
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)
