"""Asset resolution must not depend on pkg_resources.

Pyramid resolves asset specs like `pkg:static/theme/x` through
`pkg_resources.resource_filename`. We resolve them ourselves with stdlib
`importlib.resources` and hand pyramid absolute paths, so that theme assets
keep working regardless of what setuptools removes or pyramid drops. This
matters more the more themes exist — a generated theme per community turns a
handful of resolutions into hundreds.
"""

import os
import unittest

import transaction
import webtest

from pyramid.paster import get_appsettings

from remarkbox.lib.assets import package_dir_exists, package_path
from remarkbox.models.meta import Base
from remarkbox.models import get_tm_session


class PackagePathTests(unittest.TestCase):
    def test_resolves_our_own_package_directories(self):
        for parts in (("templates",), ("static",), ("static", "attachment")):
            path = package_path("remarkbox", *parts)
            self.assertTrue(os.path.isabs(path))
            self.assertTrue(os.path.isdir(path), path)

    def test_resolves_an_installed_theme_package(self):
        """Themes live in site-packages, not our source tree."""
        path = package_path("remarkbox_theme_meta", "static", "theme", "meta")
        self.assertTrue(os.path.isdir(path), path)
        self.assertTrue(
            os.path.isfile(os.path.join(path, "css", "meta.css")),
            "meta theme should ship css/meta.css",
        )

    def test_missing_package_raises_rather_than_returning_nonsense(self):
        with self.assertRaises(ModuleNotFoundError):
            package_path("remarkbox_theme_that_does_not_exist")

    def test_dir_exists_is_false_for_missing_package(self):
        """A malformed theme must not take down every other theme."""
        self.assertFalse(package_dir_exists("remarkbox_theme_nope", "templates"))
        self.assertFalse(package_dir_exists("remarkbox", "no_such_directory"))

    def test_resolution_uses_no_pkg_resources(self):
        """Our resolver must stay stdlib-only.

        If someone reintroduces pkg_resources here, the whole point is lost:
        theme assets go back to depending on an API we do not control.
        """
        import remarkbox.lib.assets as assets

        source = open(assets.__file__).read()
        self.assertNotIn("import pkg_resources", source)
        self.assertIn("importlib.resources", source)


class StaticViewServingTests(unittest.TestCase):
    """End to end: the resolved paths really are what pyramid serves from."""

    @classmethod
    def setUpClass(cls):
        from remarkbox import main

        settings = get_appsettings("test.ini")
        app = main({}, **settings)
        session_factory = app.registry["dbsession_factory"]
        Base.metadata.create_all(bind=session_factory.kw["bind"])
        cls.dbsession = get_tm_session(session_factory, transaction.manager)
        cls.testapp = webtest.TestApp(app)

    @classmethod
    def tearDownClass(cls):
        cls.dbsession.close()

    def test_serves_our_built_in_stylesheet(self):
        res = self.testapp.get("/static/css/common.css", status="*")
        self.assertEqual(res.status_int, 200)

    def test_serves_theme_css_from_the_installed_theme_package(self):
        """The request that would break if asset resolution regressed."""
        res = self.testapp.get("/static/theme/meta/css/meta.css", status="*")
        self.assertEqual(res.status_int, 200)
        self.assertTrue(len(res.body) > 0)


# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_assets")
