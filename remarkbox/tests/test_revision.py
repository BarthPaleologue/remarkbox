"""Unit tests for remarkbox.models.revision — wiki mode revision tracking."""

import unittest
from unittest import mock

from remarkbox.models.revision import Revision
from remarkbox.models.node import Node
from remarkbox.models.namespace import Namespace


class TestRevisionModel(unittest.TestCase):
    """Unit tests for the Revision model."""

    def test_init_sets_uuid(self):
        rev = Revision()
        self.assertIsNotNone(rev.id)

    def test_init_sets_timestamp(self):
        rev = Revision()
        self.assertIsNotNone(rev.created)
        self.assertGreater(rev.created, 0)

    def test_init_with_data(self):
        rev = Revision(
            data="Some content",
            source_format="markdown",
            revision_number=3,
        )
        self.assertEqual(rev.data, "Some content")
        self.assertEqual(rev.source_format, "markdown")
        self.assertEqual(rev.revision_number, 3)

    def test_default_source_format(self):
        rev = Revision()
        self.assertEqual(rev.source_format, "markdown")

    def test_default_revision_number(self):
        rev = Revision()
        self.assertEqual(rev.revision_number, 1)


class TestNamespaceCanWikiEdit(unittest.TestCase):
    """Unit tests for Namespace.can_wiki_edit()."""

    def setUp(self):
        self.ns = Namespace("test-wiki.com")
        self.ns.subscription_type = "production"

    def test_unauthenticated_user_denied(self):
        user = mock.Mock()
        user.authenticated = False
        node = mock.Mock()
        self.assertFalse(self.ns.can_wiki_edit(node, user))

    def test_none_user_denied(self):
        node = mock.Mock()
        self.assertFalse(self.ns.can_wiki_edit(node, None))

    def test_owner_can_always_edit(self):
        user = mock.Mock()
        user.authenticated = True
        node = mock.Mock()
        node.is_root = False
        # can_alter_node returns True for owners
        with mock.patch.object(self.ns, 'can_alter_node', return_value=True):
            self.assertTrue(self.ns.can_wiki_edit(node, user))

    def test_wiki_mode_allows_root_edit(self):
        self.ns.wiki = True
        user = mock.Mock()
        user.authenticated = True
        node = mock.Mock()
        node.is_root = True
        with mock.patch.object(self.ns, 'can_alter_node', return_value=False):
            self.assertTrue(self.ns.can_wiki_edit(node, user))

    def test_wiki_mode_denies_non_root_edit(self):
        self.ns.wiki = True
        user = mock.Mock()
        user.authenticated = True
        node = mock.Mock()
        node.is_root = False
        with mock.patch.object(self.ns, 'can_alter_node', return_value=False):
            self.assertFalse(self.ns.can_wiki_edit(node, user))

    def test_non_wiki_mode_denies_non_owner(self):
        self.ns.wiki = False
        user = mock.Mock()
        user.authenticated = True
        node = mock.Mock()
        node.is_root = True
        with mock.patch.object(self.ns, 'can_alter_node', return_value=False):
            self.assertFalse(self.ns.can_wiki_edit(node, user))
