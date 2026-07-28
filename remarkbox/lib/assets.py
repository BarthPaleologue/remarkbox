"""Resolve package-relative asset paths ourselves, without pkg_resources.

Pyramid accepts asset *specs* like `remarkbox_theme_meta:static/theme/meta`
and resolves them through `pkg_resources.resource_filename`
(`pyramid/asset.py`). That works today only because setuptools still ships
`pkg_resources` below 82, and because we vendor a shim when it does not.

We resolve them ourselves instead, with `importlib.resources` from the stdlib,
and hand pyramid absolute filesystem paths — which `add_static_view` and
`add_jinja2_search_path` both accept. Two reasons:

* **Themes are about to multiply.** Every theme package contributes a template
  directory and a static directory. A generated-theme-per-community model
  (T17 P3) turns a handful of resolutions into hundreds, all of them running
  through a deprecated API we do not control.
* **We should own our own asset resolution before we need it.** pyramid may
  drop `pkg_resources`, or setuptools may move again — both have already
  happened once this week. Resolving paths ourselves means neither event
  reaches our themes.

This does not retire `remarkbox/_vendor/pkg_resources`: pyramid still imports
it internally for its own machinery. It removes *our* asset paths from that
dependency, which is the part that scales with theme count.
"""

import os

from importlib.resources import files as _resource_files


def package_path(package_name, *relative):
    """Return an absolute filesystem path inside an installed package.

    `package_path("remarkbox_theme_meta", "static", "theme", "meta")` is our
    replacement for the asset spec `remarkbox_theme_meta:static/theme/meta`.

    Raises `ModuleNotFoundError` if the package is not installed, matching what
    an unresolvable asset spec would have done, only sooner and more clearly.
    """
    base = _resource_files(package_name)
    target = base.joinpath(*relative) if relative else base
    return os.path.abspath(str(target))


def package_dir_exists(package_name, *relative):
    """True when the package directory exists on disk.

    A theme that ships no templates, or names its static directory something
    unexpected, should be skipped rather than crash our whole configuration —
    one malformed theme must not take down every other one.
    """
    try:
        return os.path.isdir(package_path(package_name, *relative))
    except (ModuleNotFoundError, TypeError, ValueError):
        return False
