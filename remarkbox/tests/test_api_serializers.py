import unittest
import uuid
from unittest import mock


class TestSerializeAuthor(unittest.TestCase):

    def test_with_user(self):
        from remarkbox.api.serializers import serialize_author

        user = mock.MagicMock()
        user.id = uuid.uuid1()
        user.name = "TestUser"
        node = mock.MagicMock()
        node.user = user
        node.user_surrogate = None

        result = serialize_author(node)
        self.assertEqual(result["type"], "user")
        self.assertEqual(result["id"], str(user.id))
        self.assertEqual(result["name"], "TestUser")

    def test_with_surrogate(self):
        from remarkbox.api.serializers import serialize_author

        surrogate = mock.MagicMock()
        surrogate.id = uuid.uuid1()
        surrogate.name = "AnonBot"
        node = mock.MagicMock()
        node.user = None
        node.user_surrogate = surrogate

        result = serialize_author(node)
        self.assertEqual(result["type"], "surrogate")
        self.assertEqual(result["id"], str(surrogate.id))
        self.assertEqual(result["name"], "AnonBot")

    def test_with_no_author(self):
        from remarkbox.api.serializers import serialize_author

        node = mock.MagicMock()
        node.user = None
        node.user_surrogate = None

        result = serialize_author(node)
        self.assertIsNone(result)


class TestSerializeNode(unittest.TestCase):

    def _make_mock_node(self, **kwargs):
        node = mock.MagicMock()
        node.id = kwargs.get("id", uuid.uuid1())
        node.root_id = kwargs.get("root_id", node.id)
        node.parent_id = kwargs.get("parent_id", None)
        node.title = kwargs.get("title", "Test Title")
        node.data = kwargs.get("data", "Test data")
        node.data_html = kwargs.get("data_html", "<p>Test data</p>")
        node.is_root = kwargs.get("is_root", True)
        node.graph_depth = kwargs.get("graph_depth", 0)
        node.created = kwargs.get("created", 1700000000000)
        node.created_date = "2023-11-14"
        node.human_created_timestamp = "just now"
        node.changed = kwargs.get("changed", 1700000000000)
        node.changed_date = "2023-11-14"
        node.human_changed_timestamp = "just now"
        node.disabled = kwargs.get("disabled", False)
        node.verified = kwargs.get("verified", True)
        node.locked = kwargs.get("locked", False)
        node.approved = kwargs.get("approved", True)
        node.was_edited = kwargs.get("was_edited", False)
        node.user = kwargs.get("user", None)
        node.user_surrogate = kwargs.get("user_surrogate", None)
        node.cache = kwargs.get("cache", None)
        return node

    def test_basic_fields(self):
        from remarkbox.api.serializers import serialize_node

        node = self._make_mock_node()
        result = serialize_node(node)
        self.assertEqual(result["id"], str(node.id))
        self.assertEqual(result["title"], "Test Title")
        self.assertEqual(result["data"], "Test data")
        self.assertEqual(result["data_html"], "<p>Test data</p>")
        self.assertTrue(result["is_root"])
        self.assertEqual(result["depth"], 0)
        self.assertFalse(result["disabled"])
        self.assertTrue(result["verified"])
        self.assertFalse(result["locked"])
        self.assertTrue(result["approved"])
        self.assertFalse(result["was_edited"])

    def test_uuid_fields_are_strings(self):
        from remarkbox.api.serializers import serialize_node

        node_id = uuid.uuid1()
        root_id = uuid.uuid1()
        parent_id = uuid.uuid1()
        node = self._make_mock_node(id=node_id, root_id=root_id, parent_id=parent_id)
        result = serialize_node(node)
        self.assertEqual(result["id"], str(node_id))
        self.assertEqual(result["root_id"], str(root_id))
        self.assertEqual(result["parent_id"], str(parent_id))

    def test_null_parent_id(self):
        from remarkbox.api.serializers import serialize_node

        node = self._make_mock_node(parent_id=None)
        result = serialize_node(node)
        self.assertIsNone(result["parent_id"])

    def test_disabled_node(self):
        from remarkbox.api.serializers import serialize_node

        node = self._make_mock_node(disabled=True)
        result = serialize_node(node)
        self.assertTrue(result["disabled"])

    def test_child_node(self):
        from remarkbox.api.serializers import serialize_node

        root_id = uuid.uuid1()
        parent_id = uuid.uuid1()
        node = self._make_mock_node(
            is_root=False, root_id=root_id, parent_id=parent_id, graph_depth=2
        )
        result = serialize_node(node)
        self.assertFalse(result["is_root"])
        self.assertEqual(result["depth"], 2)
        self.assertEqual(result["root_id"], str(root_id))
        self.assertEqual(result["parent_id"], str(parent_id))

    def test_include_children_with_cache(self):
        from remarkbox.api.serializers import serialize_node

        cache = mock.MagicMock()
        node = self._make_mock_node(cache=cache)
        node.stats = {"root": {"count": 5, "visible_count": 4}}
        result = serialize_node(node, include_children=True)
        self.assertEqual(result["stats"], {"root": {"count": 5, "visible_count": 4}})

    def test_include_children_no_cache(self):
        from remarkbox.api.serializers import serialize_node

        node = self._make_mock_node(cache=None)
        result = serialize_node(node, include_children=True)
        self.assertIsNone(result["stats"])

    def test_no_stats_by_default(self):
        from remarkbox.api.serializers import serialize_node

        node = self._make_mock_node()
        result = serialize_node(node)
        self.assertNotIn("stats", result)

    def test_with_user_author(self):
        from remarkbox.api.serializers import serialize_node

        user = mock.MagicMock()
        user.id = uuid.uuid1()
        user.name = "AgentSmith"
        node = self._make_mock_node(user=user)
        result = serialize_node(node)
        self.assertEqual(result["author"]["type"], "user")
        self.assertEqual(result["author"]["name"], "AgentSmith")

    def test_with_surrogate_author(self):
        from remarkbox.api.serializers import serialize_node

        surrogate = mock.MagicMock()
        surrogate.id = uuid.uuid1()
        surrogate.name = "ClaudeBot"
        node = self._make_mock_node(user_surrogate=surrogate)
        result = serialize_node(node)
        self.assertEqual(result["author"]["type"], "surrogate")
        self.assertEqual(result["author"]["name"], "ClaudeBot")

    def test_timestamps(self):
        from remarkbox.api.serializers import serialize_node

        node = self._make_mock_node(created=1700000000000, changed=1700001000000)
        result = serialize_node(node)
        self.assertEqual(result["created"], 1700000000000)
        self.assertEqual(result["changed"], 1700001000000)
        self.assertEqual(result["created_date"], "2023-11-14")


class TestSerializeNamespaceBrief(unittest.TestCase):

    def test_basic_fields(self):
        from remarkbox.api.serializers import serialize_namespace_brief

        ns = mock.MagicMock()
        ns.id = uuid.uuid1()
        ns.name = "agents.example.com"
        ns.description = "Agent discussion"
        ns.allow_anonymous = True
        ns.node_order = "oldest-first"

        result = serialize_namespace_brief(ns)
        self.assertEqual(result["id"], str(ns.id))
        self.assertEqual(result["name"], "agents.example.com")
        self.assertEqual(result["description"], "Agent discussion")
        self.assertTrue(result["allow_anonymous"])
        self.assertEqual(result["node_order"], "oldest-first")
