"""
Minimal vendored pkg_resources shim for Remarkbox.

setuptools 81 dropped pkg_resources from its distribution. Pyramid (and a
handful of other libraries) still import it. This shim provides the narrow
surface pyramid actually uses, backed entirely by stdlib (importlib.resources,
importlib.import_module). No setuptools coupling, no jaraco.text, no
platformdirs. Bleeding-edge friendly.

Surface (only what pyramid touches):
    resource_filename(package, name)  -> str
    resource_stream(package, name)    -> IO[bytes]
    resource_string(package, name)    -> bytes
    resource_exists(package, name)    -> bool
    resource_isdir(package, name)     -> bool
    resource_listdir(package, name)   -> list[str]
    DefaultProvider                   -- class, subclassable
    register_loader_type              -- no-op registry stub

If a future dependency needs more of the legacy pkg_resources API, extend
this file. Do not pull in upstream setuptools' pkg_resources/__init__.py
(3700 lines + jaraco.text + platformdirs); that defeats the point.
"""

import os
from importlib.resources import files


def _ref(package, name=""):
    if not isinstance(package, str):
        package = package.__name__
    ref = files(package)
    if name:
        ref = ref / name
    return ref


def resource_filename(package, name):
    return str(_ref(package, name))


def resource_stream(package, name):
    return _ref(package, name).open("rb")


def resource_string(package, name):
    return _ref(package, name).read_bytes()


def resource_exists(package, name):
    try:
        ref = _ref(package, name)
    except (FileNotFoundError, ModuleNotFoundError):
        return False
    try:
        return ref.is_file() or ref.is_dir()
    except (FileNotFoundError, NotADirectoryError):
        return False


def resource_isdir(package, name):
    try:
        return _ref(package, name).is_dir()
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError):
        return False


def resource_listdir(package, name):
    try:
        return [child.name for child in _ref(package, name).iterdir()]
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError):
        return []


class DefaultProvider:
    """Minimal stand-in for pkg_resources.DefaultProvider.

    Pyramid subclasses this to wire its asset-override system. The `manager`
    arg in get_resource_* (originally a ResourceManager for zip-egg cache
    extraction) is unused — modern pip installs are unpacked directories.
    """

    def __init__(self, module):
        self.module = module
        self.module_path = None
        if getattr(module, "__file__", None):
            self.module_path = os.path.dirname(module.__file__)

    def _name(self):
        return self.module.__name__

    def get_resource_filename(self, manager, resource_name):
        return resource_filename(self._name(), resource_name)

    def get_resource_stream(self, manager, resource_name):
        return resource_stream(self._name(), resource_name)

    def get_resource_string(self, manager, resource_name):
        return resource_string(self._name(), resource_name)

    def has_resource(self, resource_name):
        return resource_exists(self._name(), resource_name)

    def resource_isdir(self, resource_name):
        return resource_isdir(self._name(), resource_name)

    def resource_listdir(self, resource_name):
        return resource_listdir(self._name(), resource_name)


_LOADER_TYPES = {}


def register_loader_type(loader_class, provider_class):
    _LOADER_TYPES[loader_class] = provider_class
