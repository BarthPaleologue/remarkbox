import unittest

from unittest import mock

from remarkbox.models.user import User, is_user_name_valid

from remarkbox.models.node import (
    Node,
    get_or_create_node_by_uri,
    get_graph_from_nodes,
    get_group_conversation_ids,
    get_conversation_graph_from_nodes,
    flatten_graph,
)

from remarkbox.models.namespace import Namespace

from remarkbox.models.namespace_request import NamespaceRequest

from remarkbox.models.vote import Vote

mock_always_none = mock.Mock(return_value=None)
mock_always_true = mock.Mock(return_value=True)
mock_false_then_true = mock.Mock(side_effect=[False, False, True])


class TestUser(unittest.TestCase):

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def setUp(self):
        self.user = User("russell@ballestrini.net")

    def test_created_timestamp_set(self):
        self.assertGreater(self.user.created, 100000)

    def test_email_set(self):
        self.assertEqual(self.user.email, "russell@ballestrini.net")

    def test_new_password(self):
        raw_password = self.user.new_password()
        self.assertEqual(len(raw_password), 6)

    def test_check_password_success(self):
        raw_password = self.user.new_password()
        self.assertTrue(self.user.check_password(raw_password))

    def test_check_password_failure(self):
        raw_password = self.user.new_password()
        self.assertFalse(self.user.check_password("fake password"))

    def test_is_user_name_valid(self):
        self.assertTrue(is_user_name_valid("validusername"))
        self.assertTrue(is_user_name_valid("validusername2"))
        self.assertTrue(is_user_name_valid("ValidUsername"))
        self.assertTrue(is_user_name_valid("valid-username"))

        self.assertFalse(is_user_name_valid("invalid username"))
        self.assertFalse(is_user_name_valid("invalid!!!"))
        self.assertFalse(is_user_name_valid(""))

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def test_generate_user_name_no_dash_prefix(self):
        u = User("tim@example.com")
        self.assertFalse(u.name.startswith("-"))


class TestNode(unittest.TestCase):

    def setUp(self):
        self.node = Node()
        self.node.id = 21
        self.node.data = u"taco"
        self.node.title = u"Taco, Nacho, and Burrito"

    def test_equality(self):
        self.assertEqual(self.node, self.node)
        cloned_node = Node()
        cloned_node.id = 21
        self.assertEqual(self.node, cloned_node)

    def test_inequality(self):
        another_node = Node()
        another_node.id = 22
        self.assertNotEqual(self.node, another_node)

    def test_expected_in_slug(self):
        for item in ("taco", "nacho", "burrito", "-"):
            self.assertIn(item, self.node.slug)

    def test_unexpected_not_in_slug(self):
        for item in (",", " ", "T"):
            self.assertNotIn(item, self.node.slug)

    def test_path_with_slug(self):
        self.assertEqual(self.node.path, "/21/taco-nacho-and-burrito")

    def test_path_without_slug(self):
        n = Node()
        n.id = 45
        n.title = None
        self.assertEqual(n.path, "/45")

    def test_uri_is_none(self):
        self.assertEqual(self.node.uri, None)

    @mock.patch("remarkbox.models.namespace.get_namespace_by_name", mock_always_none)
    @mock.patch("remarkbox.models.uri.get_uri_by_uri", mock_always_none)
    # @mock.patch('remarkbox.models.namespace.Namespace.commit', mock_always_none)
    def test_embed_parent_title_data_is_none(self):
        dbsession = mock.MagicMock()
        node = get_or_create_node_by_uri(
            dbsession, "http://russell.ballestrini.net/about"
        )
        self.assertTrue(node.uri)
        self.assertEqual(node.uri.data, "http://russell.ballestrini.net/about")
        self.assertEqual(node.title, None)
        self.assertFalse(node.title)

    def test_created_timestamp_set(self):
        self.assertGreater(self.node.created, 100000)

    def test_short_id(self):
        import uuid

        n = Node()
        n.id = uuid.UUID(hex="75b1de48-414b-11e7-aecf-9c4e369c7158")
        self.assertEqual(n.short_id, "dbHeSEFLEeeuz5xONpxxWA")


class TestNamespace(unittest.TestCase):

    # @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def setUp(self):
        # self.user = User("russell@ballestrini.net")
        self.namespace = Namespace("russell.ballestrini.net")

    def test_namespace_production_custom_settings(self):
        self.namespace.subscription_type = "production"
        self.namespace.link_protection = True
        self.namespace.hide_powered_by = True
        self.namespace.mathjax = True
        self.assertTrue(self.namespace.link_protection)
        self.assertTrue(self.namespace.hide_powered_by)
        self.assertTrue(self.namespace.mathjax)
        self.assertFalse(self.namespace.memoized_attr_protection)

    def test_namespace_development_custom_settings(self):
        self.namespace.subscription_type = "development"
        self.namespace.link_protection = True
        self.namespace.hide_powered_by = True
        self.namespace.mathjax = True
        self.assertFalse(self.namespace.link_protection)
        self.assertFalse(self.namespace.hide_powered_by)
        self.assertFalse(self.namespace.mathjax)
        self.assertTrue(self.namespace.memoized_attr_protection)

    def test_namespace_simulate_expired_subscription(self):
        # first we have a production namespace with custom settings.
        self.namespace.subscription_type = "production"
        self.namespace.link_protection = True
        self.namespace.hide_powered_by = True
        self.namespace.mathjax = True
        self.assertTrue(self.namespace.link_protection)
        self.assertTrue(self.namespace.hide_powered_by)
        self.assertTrue(self.namespace.mathjax)

        # next the namespace subscription expires with custom settings.
        self.namespace.subscription_type = "development"
        self.namespace.reload_memoized_attr_protection()
        self.assertTrue(self.namespace.memoized_attr_protection)
        self.assertFalse(self.namespace.link_protection)
        self.assertFalse(self.namespace.hide_powered_by)
        self.assertFalse(self.namespace.mathjax)

        # finally the namespace subscription is renewed with custom settings.
        self.namespace.subscription_type = "production"
        self.namespace.reload_memoized_attr_protection()
        self.assertFalse(self.namespace.memoized_attr_protection)
        self.assertTrue(self.namespace.link_protection)
        self.assertTrue(self.namespace.hide_powered_by)
        self.assertTrue(self.namespace.mathjax)

class TestNamespaceRequest(unittest.TestCase):

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def setUp(self):
        self.user = User("russell@ballestrini.net")
        self.namespace = Namespace("russell.ballestrini.net")
        self.namespace_request = NamespaceRequest(self.user, self.namespace)
        # self.namespace_request.user = self.user
        # self.namespace_request.namespace = self.namespace

        self.target = "http://russell.ballestrini.net/so-you-are-planning-a-beta-test/"

    @mock.patch("remarkbox.models.NamespaceRequest.scrape_target", mock_always_true)
    def test_namespace_request_id_found(self):
        self.namespace_request.verify_target(self.target)
        self.assertEqual(self.target, self.namespace_request.target)
        self.assertTrue(self.namespace_request.verified)

    @mock.patch('remarkbox.models.NamespaceRequest.scrape_target', mock_always_none)
    def test_namespace_request_id_not_found(self):
        self.namespace_request.verify_target(self.target)
        self.assertEqual(self.target, self.namespace_request.target)      
        self.assertFalse(self.namespace_request.verified)      


class TestNodeTree(unittest.TestCase):

    def setUp(self):
        self.root = Node()
        self.root.id = 21
        self.root.data = u"taco"
        self.root.title = u"Taco, Nacho, and Burrito"

        # create some children.
        self.child1 = self.root.new_child()
        self.child1.id = 24
        self.child1.parent_id = 21
        self.child1.root_id = 21
        self.child1.data = u"nacho"
        self.root.children.append(self.child1)

        self.child2 = self.root.new_child()
        self.child2.id = 27
        self.child2.parent_id = 21
        self.child2.root_id = 21
        self.child2.data = u"burrito"
        self.root.children.append(self.child2)

        self.grandchild1 = self.child1.new_child()
        self.grandchild1.id = 25
        self.grandchild1.parent_id = 24
        self.grandchild1.root_id = 21
        self.grandchild1.data = u"nacho-cheese"
        self.child1.children.append(self.grandchild1)

        self.great_grandchild1 = self.grandchild1.new_child()
        self.great_grandchild1.id = 38
        self.great_grandchild1.parent_id = 25
        self.great_grandchild1.root_id = 21
        self.great_grandchild1.data = u"tortilla"
        self.grandchild1.children.append(self.great_grandchild1)

        self.nodes = [
            self.root,
            self.child1,
            self.child2,
            self.grandchild1,
            self.great_grandchild1,
        ]

        self.graph = get_graph_from_nodes(self.nodes)

    def test_parent_child_relationship(self):
        self.assertEqual(self.child1.parent.data, u"taco")
        self.assertEqual(self.child2.parent.id, 21)

    def test_root2_node(self):
        # TODO: delete this test and the root2 attribute/property from Node.
        self.assertEqual(self.grandchild1.root2.id, self.root.id)
        self.assertEqual(self.child2.root2.id, self.root.id)

    def test_root_is_root(self):
        # TODO: delete this test and the root2 attribute/property from Node.
        self.assertEqual(self.root.id, self.root.root2.id)

    def test_path_to_root(self):
        expected_path = [self.grandchild1, self.child1, self.root]
        self.assertEqual(self.grandchild1.path_to_root, expected_path)

    def test_path_from_root(self):
        expected_path = [self.root, self.child1, self.grandchild1]
        self.assertEqual(self.grandchild1.path_from_root, expected_path)

    def test_get_graph_from_nodes(self):
        expected_graph = {21: [24, 27], 24: [25], 25: [38], 27: [], 38: []}
        self.assertEqual(get_graph_from_nodes(self.nodes), expected_graph)

    def test_get_group_conversation_ids(self):
        expected_ids = [24, 27]
        self.assertEqual(get_group_conversation_ids(self.nodes), expected_ids)

    def test_flatten_graph(self):
        expected_ids = [25, 38]
        self.assertEqual(
            flatten_graph(24, self.graph),
            expected_ids,
        )

    def test_get_conversation_graph_from_nodes(self):
        expected_graph = {24: [25, 38], 27: []}
        self.assertEqual(
            get_conversation_graph_from_nodes(self.nodes),
            expected_graph,
        )

    def test_get_conversation_graph_from_nodes2(self):
        expected_graph = {24: [25, 38], 27: []}
        self.assertEqual(
            get_conversation_graph_from_nodes(self.nodes, self.graph),
            expected_graph,
        )


class TestIntegration(unittest.TestCase):

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def setUp(self):
        self.user = User("russell@ballestrini.net")

        self.parent = Node()
        self.parent.data = u"taco"

        self.child = Node()
        self.child.data = u"nacho"
        self.child.parent = self.parent

        self.user.nodes.append(self.parent)
        self.user.nodes.append(self.child)

        self.vote1 = Vote()
        self.vote1.user = self.user
        self.vote1.node = self.parent
        self.vote1.value = 1

        self.vote2 = Vote()
        self.vote2.user = self.user
        self.vote2.node = self.child
        self.vote2.value = -1

    def test_user_vote_count(self):
        self.assertEqual(len(self.user.votes), 2)

    def test_user_node_count(self):
        self.assertEqual(len(list(self.user.nodes)), 2)

    def test_user_nodes_vote_count(self):
        for node in self.user.nodes:
            self.assertEqual(len(node.votes), 1)

    def test_node_score(self):
        self.assertEqual(self.parent.score(), 1)
        self.assertEqual(self.child.score(), -1)

    def test_node_new_child(self):
        new_child = self.parent.new_child()
        self.assertEqual(new_child.parent, self.parent)
        self.assertEqual(new_child.parent.data, "taco")
        self.assertEqual(new_child.parent.user.email, "russell@ballestrini.net")
