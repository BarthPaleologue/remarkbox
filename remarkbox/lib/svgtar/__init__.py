import hashlib

try:
    # Python 2.
    from urllib import quote
except ImportError:
    # Python 3.
    from urllib.parse import quote

from .svg import make_svg


def _bg_color(colors=None, text=u"", h=u"salty-salt"):
    """Selects a background color to use.
    If `colors` is given, the value is choosen from that.
    If `colors` is not given, a unique and consistent color value is generated.
    :return (str)
    """
    h = hashlib.md5((h + text).encode("utf-8")).hexdigest()
    if colors:
        ind = int(h, 16) % len(colors)
        return colors[ind]
    cut = 142
    r = int(h[:2], 16) % cut
    g = int(h[2:4], 16) % cut
    b = int(h[4:6], 16) % cut
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def _reduce_whitespace(text):
    """a way to remove newlines and leading/trailing whitespace per line."""
    return " ".join([line.strip() for line in text.splitlines()])


def inline_svgtar(*args, **kwargs):
    quoted_svgtar = quote(_reduce_whitespace(svgtar(*args, **kwargs)))
    return "data:image/svg+xml;charset=utf-8,{}".format(quoted_svgtar)


def svgtar(
    text, h, size=55, color="#ffffff", bg=None, font_size=None, font_family="Arial"
):
    """Return an multiline svg string."""
    bg = _bg_color(h=h) if bg is None else bg
    font_size = size * .6 if font_size is None else font_size
    options = {
        "text": text,
        "size": size,
        "color": color,
        "bg": bg,
        "font_size": font_size,
        "font_family": font_family,
    }
    return make_svg(**options)
