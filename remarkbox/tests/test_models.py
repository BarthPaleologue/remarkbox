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

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def test_email_normalized_to_lowercase(self):
        """Emails should be stored lowercase to prevent case-sensitive duplicates."""
        user = User("Russell@Ballestrini.NET")
        self.assertEqual(user.email, "russell@ballestrini.net")

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def test_email_mixed_case_normalized(self):
        """Mixed case emails should be normalized to lowercase."""
        user = User("Grop3r@Protonmail.com")
        self.assertEqual(user.email, "grop3r@protonmail.com")

    def test_new_password(self):
        raw_password = self.user.new_password()
        self.assertEqual(len(raw_password), 6)

    def test_check_password_success(self):
        raw_password = self.user.new_password()
        self.assertTrue(self.user.check_password(raw_password))

    def test_check_password_failure(self):
        raw_password = self.user.new_password()
        self.assertFalse(self.user.check_password("fake password"))

    def test_unverified_otp_backoff_ladder(self):
        """Unverified accounts escalate to a 48h gap; verified stay at 90s."""
        from remarkbox.models.user import UNVERIFIED_OTP_BACKOFF_MS

        # Fresh account: constructor's password doesn't count.
        self.assertEqual(self.user.otp_send_count, 0)
        self.assertFalse(self.user.throttle_password())

        for expected_count in range(1, len(UNVERIFIED_OTP_BACKOFF_MS) + 2):
            self.user.new_password()
            self.assertEqual(self.user.otp_send_count, expected_count)
            self.assertTrue(self.user.throttle_password())
            # Past the flat 90s throttle an unverified account beyond
            # step one must STILL be throttled by the ladder.
            self.user.password_timestamp -= 91000
            if expected_count >= 2:
                self.assertTrue(self.user.throttle_password())
            # Past this step's ladder gap the next send frees up.
            step = min(expected_count - 1, len(UNVERIFIED_OTP_BACKOFF_MS) - 1)
            self.user.password_timestamp -= UNVERIFIED_OTP_BACKOFF_MS[step]
            self.assertFalse(self.user.throttle_password())

        # Successful code entry resets the ladder...
        raw_password = self.user.new_password()
        self.assertTrue(self.user.check_password(raw_password))
        self.assertEqual(self.user.otp_send_count, 0)

        # ...and verified accounts feel only the flat 90s throttle.
        self.user.verified = True
        self.user.otp_send_count = 99
        self.user.new_password()
        self.user.password_timestamp -= 91000
        self.assertFalse(self.user.throttle_password())

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


# ---------------------------------------------------------------------------
# T1: Case-insensitive URI and Namespace lookups (unit tests)
# ---------------------------------------------------------------------------


class TestCaseInsensitiveUri(unittest.TestCase):
    """
    Regression tests for T1: case-insensitive URI and namespace lookups.

    When creating a node by URI, the namespace is extracted from the hostname.
    The namespace lookup normalises the domain to lowercase during the setup
    step (setup_namespace view lowercases the domain).
    """

    @mock.patch("remarkbox.models.namespace.get_namespace_by_name", mock_always_none)
    @mock.patch("remarkbox.models.uri.get_uri_by_uri", mock_always_none)
    def test_uri_data_is_stored(self):
        """get_or_create_node_by_uri stores the URI and extracts hostname."""
        dbsession = mock.MagicMock()
        node = get_or_create_node_by_uri(
            dbsession, "http://example.com/SomePath"
        )
        self.assertTrue(node.uri)
        # The URI data is stored.
        self.assertEqual(node.uri.data, "http://example.com/SomePath")

    @mock.patch("remarkbox.models.namespace.get_namespace_by_name", mock_always_none)
    @mock.patch("remarkbox.models.uri.get_uri_by_uri", mock_always_none)
    def test_uri_preserves_path_case(self):
        """URI path case is preserved even when hostname is lowercase."""
        dbsession = mock.MagicMock()
        node = get_or_create_node_by_uri(
            dbsession, "http://example.com/My-Blog-Post"
        )
        self.assertTrue(node.uri)
        self.assertIn("/My-Blog-Post", node.uri.data)

    @mock.patch("remarkbox.models.namespace.get_namespace_by_name", mock_always_none)
    @mock.patch("remarkbox.models.uri.get_uri_by_uri", mock_always_none)
    def test_uri_strips_fragment(self):
        """Fragment (#section) is stripped from URIs before storage."""
        dbsession = mock.MagicMock()
        node = get_or_create_node_by_uri(
            dbsession, "http://example.com/page#section"
        )
        self.assertTrue(node.uri)
        self.assertNotIn("#", node.uri.data)
        self.assertEqual(node.uri.data, "http://example.com/page")


class TestCaseInsensitiveNamespace(unittest.TestCase):
    """
    Regression tests for T1: case-insensitive Namespace lookups.

    Namespace names should be compared case-insensitively. The setup_namespace
    view lowercases domain names before creation.
    """

    def test_namespace_name_stored_as_given(self):
        """Namespace stores the name as given."""
        ns = Namespace("Example.Com")
        self.assertEqual(ns.name, "Example.Com")

    def test_namespace_name_lowercase(self):
        """Namespace with lowercase name is stored correctly."""
        ns = Namespace("example.com")
        self.assertEqual(ns.name, "example.com")


# ---------------------------------------------------------------------------
# T3: GDPR/CCPA - export_user_data structure (unit tests)
# ---------------------------------------------------------------------------


class TestUserExportDataStructure(unittest.TestCase):
    """
    Unit tests for User.export_user_data() method.

    These test the shape of the returned dict without requiring a database.
    We mock the nodes dynamic relationship by patching the instance after creation.
    """

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def test_export_data_has_profile_and_comments(self):
        """export_user_data returns a dict with 'profile' and 'comments' keys."""
        user = User("export-test@example.com")
        with mock.patch.object(type(user), "nodes", new_callable=mock.PropertyMock) as mock_nodes:
            mock_query = mock.MagicMock()
            mock_query.all.return_value = []
            mock_nodes.return_value = mock_query

            data = user.export_user_data()
        self.assertIn("profile", data)
        self.assertIn("comments", data)
        self.assertIsInstance(data["profile"], dict)
        self.assertIsInstance(data["comments"], list)
        self.assertEqual(len(data["comments"]), 0)

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def test_export_data_profile_fields(self):
        """export_user_data profile contains expected fields."""
        user = User("export-test2@example.com")
        with mock.patch.object(type(user), "nodes", new_callable=mock.PropertyMock) as mock_nodes:
            mock_query = mock.MagicMock()
            mock_query.all.return_value = []
            mock_nodes.return_value = mock_query

            data = user.export_user_data()
        profile = data["profile"]
        for key in ("id", "name", "email", "created", "gravatar", "verified", "theme_mode"):
            self.assertIn(key, profile, "Missing profile key: {}".format(key))
        self.assertEqual(profile["email"], "export-test2@example.com")

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def test_export_data_includes_node_comments(self):
        """export_user_data includes comments for each attached node."""
        user = User("export-test3@example.com")

        mock_node = mock.MagicMock()
        mock_node.id = "fake-uuid"
        mock_node.created = 1700000000000
        mock_node.changed = 1700000001000
        mock_node.data = "Hello world"
        mock_node.disabled = False
        mock_node.verified = True
        mock_node.approved = True
        mock_node.title = None
        mock_node.namespace = None
        mock_node.root = mock.MagicMock()
        mock_node.root.title = None
        mock_node.root.uri = None

        with mock.patch.object(type(user), "nodes", new_callable=mock.PropertyMock) as mock_nodes:
            mock_query = mock.MagicMock()
            mock_query.all.return_value = [mock_node]
            mock_query.count.return_value = 1
            mock_nodes.return_value = mock_query

            data = user.export_user_data()
        self.assertEqual(len(data["comments"]), 1)
        comment = data["comments"][0]
        self.assertEqual(comment["content"], "Hello world")
        self.assertFalse(comment["disabled"])
        self.assertTrue(comment["verified"])
        self.assertTrue(comment["approved"])

    @mock.patch("remarkbox.models.user.is_user_name_available", mock_always_true)
    def test_export_data_includes_namespace_and_thread_info(self):
        """export_user_data includes namespace and thread info when present."""
        user = User("export-test4@example.com")

        mock_node = mock.MagicMock()
        mock_node.id = "fake-uuid-2"
        mock_node.created = 1700000000000
        mock_node.changed = 1700000001000
        mock_node.data = "Comment in thread"
        mock_node.disabled = False
        mock_node.verified = True
        mock_node.approved = True
        mock_node.title = "My Thread Title"
        mock_node.namespace = mock.MagicMock()
        mock_node.namespace.name = "example.com"
        mock_node.root = mock.MagicMock()
        mock_node.root.title = "Root Thread"
        mock_node.root.uri = mock.MagicMock()
        mock_node.root.uri.data = "https://example.com/page"

        with mock.patch.object(type(user), "nodes", new_callable=mock.PropertyMock) as mock_nodes:
            mock_query = mock.MagicMock()
            mock_query.all.return_value = [mock_node]
            mock_nodes.return_value = mock_query

            data = user.export_user_data()
        comment = data["comments"][0]
        self.assertEqual(comment["title"], "My Thread Title")
        self.assertEqual(comment["namespace"], "example.com")
        self.assertEqual(comment["thread_title"], "Root Thread")
        self.assertEqual(comment["thread_uri"], "https://example.com/page")


# ---------------------------------------------------------------------------
# T4: Namespace custom button text and comment labels
# ---------------------------------------------------------------------------


class TestNamespaceCustomText(unittest.TestCase):
    """Unit tests for T4: customizable button text and comment labels."""

    def setUp(self):
        self.namespace = Namespace("custom-text.example.com")
        # Ensure production subscription so protected attrs return real values.
        self.namespace.subscription_type = "production"

    def test_default_submit_button_text_is_none(self):
        """Default submit_button_text is None (template falls back to 'save message')."""
        self.assertIsNone(self.namespace.submit_button_text)

    def test_default_comment_label_singular_is_none(self):
        """Default comment_label_singular is None (template falls back to 'remark')."""
        self.assertIsNone(self.namespace.comment_label_singular)

    def test_default_comment_label_plural_is_none(self):
        """Default comment_label_plural is None (template falls back to 'remarks')."""
        self.assertIsNone(self.namespace.comment_label_plural)

    def test_custom_submit_button_text_stores_and_retrieves(self):
        """Setting submit_button_text stores and retrieves correctly."""
        self.namespace.submit_button_text = "Post Comment"
        self.assertEqual(self.namespace.submit_button_text, "Post Comment")

    def test_custom_comment_label_singular_stores_and_retrieves(self):
        """Setting comment_label_singular stores and retrieves correctly."""
        self.namespace.comment_label_singular = "comment"
        self.assertEqual(self.namespace.comment_label_singular, "comment")

    def test_custom_comment_label_plural_stores_and_retrieves(self):
        """Setting comment_label_plural stores and retrieves correctly."""
        self.namespace.comment_label_plural = "comments"
        self.assertEqual(self.namespace.comment_label_plural, "comments")

    def test_custom_text_protected_on_development_subscription(self):
        """Custom text returns None defaults when namespace subscription expires."""
        self.namespace.submit_button_text = "Submit"
        self.namespace.comment_label_singular = "thought"
        self.namespace.comment_label_plural = "thoughts"
        # Simulate subscription expiry.
        self.namespace.subscription_type = "development"
        self.namespace.reload_memoized_attr_protection()
        self.assertIsNone(self.namespace.submit_button_text)
        self.assertIsNone(self.namespace.comment_label_singular)
        self.assertIsNone(self.namespace.comment_label_plural)


# ---------------------------------------------------------------------------
# T6: @mention parsing
# ---------------------------------------------------------------------------


class TestMentionParsing(unittest.TestCase):
    """Unit tests for T6: parse_mention_usernames()."""

    def test_parse_single_mention(self):
        """Parse a single @mention."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("Hello @alice")
        self.assertEqual(result, {"alice"})

    def test_parse_multiple_mentions(self):
        """Parse multiple @mentions."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("Hello @alice and @bob")
        self.assertEqual(result, {"alice", "bob"})

    def test_parse_mention_at_start_of_string(self):
        """@username at start of string is recognized."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("@alice is great")
        self.assertEqual(result, {"alice"})

    def test_email_is_not_a_mention(self):
        """email@example.com should not be parsed as a mention."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("email@example.com")
        self.assertEqual(result, set())

    def test_parse_mention_with_dashes(self):
        """@user-name with dashes is a valid mention."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("Hello @my-user-name")
        self.assertEqual(result, {"my-user-name"})

    def test_parse_empty_string(self):
        """Empty string returns empty set."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("")
        self.assertEqual(result, set())

    def test_parse_none_returns_empty(self):
        """None input returns empty set."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames(None)
        self.assertEqual(result, set())

    def test_parse_no_mentions(self):
        """String with no mentions returns empty set."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("Hello world, nothing here")
        self.assertEqual(result, set())

    def test_duplicate_mentions_deduped(self):
        """Duplicate mentions are de-duplicated."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("@alice said hi to @alice")
        self.assertEqual(result, {"alice"})

    def test_mention_after_newline(self):
        """@mention after newline is recognized (preceded by whitespace)."""
        from remarkbox.lib.mentions import parse_mention_usernames
        result = parse_mention_usernames("first line\n@alice second line")
        self.assertIn("alice", result)


class TestMentionResolve(unittest.TestCase):
    """Unit tests for T6: resolve_mentions() with mocked DB."""

    def test_resolve_returns_only_existing_users(self):
        """resolve_mentions returns only users that exist in the database."""
        from remarkbox.lib.mentions import resolve_mentions

        mock_user = mock.MagicMock()
        mock_user.name = "alice"

        with mock.patch("remarkbox.models.user.get_user_by_name") as mock_get:
            # alice exists, bob does not
            mock_get.side_effect = lambda db, name: mock_user if name.lower() == "alice" else None
            dbsession = mock.MagicMock()
            result = resolve_mentions(dbsession, "Hello @alice and @bob")

        self.assertIn("alice", result)
        self.assertNotIn("bob", result)
        self.assertEqual(result["alice"], mock_user)

    def test_resolve_empty_text(self):
        """resolve_mentions with empty text returns empty dict."""
        from remarkbox.lib.mentions import resolve_mentions
        dbsession = mock.MagicMock()
        result = resolve_mentions(dbsession, "")
        self.assertEqual(result, {})


class TestMentionReplaceWithLinks(unittest.TestCase):
    """Unit tests for T6: replace_mentions_with_links()."""

    def test_replace_existing_user_with_link(self):
        """Existing user's @mention is replaced with an anchor tag."""
        from remarkbox.lib.mentions import replace_mentions_with_links

        mock_user = mock.MagicMock()
        mock_user.name = "alice"
        resolved = {"alice": mock_user}

        html = "<p>Hello @alice</p>"
        result = replace_mentions_with_links(html, resolved)
        self.assertIn('class="mention"', result)
        self.assertIn("@alice", result)
        self.assertIn("/u/alice", result)

    def test_nonexistent_user_left_as_text(self):
        """Non-existent user's @mention is left as plain text."""
        from remarkbox.lib.mentions import replace_mentions_with_links

        resolved = {}  # No resolved users
        html = "<p>Hello @nonexistent</p>"
        result = replace_mentions_with_links(html, resolved)
        self.assertIn("@nonexistent", result)
        self.assertNotIn("class=\"mention\"", result)

    def test_no_resolved_users_returns_unchanged(self):
        """When resolved_users is empty or None, HTML is returned unchanged."""
        from remarkbox.lib.mentions import replace_mentions_with_links

        html = "<p>Hello @world</p>"
        result = replace_mentions_with_links(html, {})
        self.assertEqual(result, html)

        result2 = replace_mentions_with_links(html, None)
        self.assertEqual(result2, html)

    def test_replace_with_link_prefix(self):
        """Link prefix is prepended to profile URLs."""
        from remarkbox.lib.mentions import replace_mentions_with_links

        mock_user = mock.MagicMock()
        mock_user.name = "bob"
        resolved = {"bob": mock_user}

        html = "<p>Hi @bob</p>"
        result = replace_mentions_with_links(html, resolved, link_prefix="/embed/ns/test.com")
        self.assertIn("/embed/ns/test.com/u/bob", result)

    def test_mentions_inside_html_tags_not_replaced(self):
        """@mentions inside HTML tag attributes are not replaced."""
        from remarkbox.lib.mentions import replace_mentions_with_links

        mock_user = mock.MagicMock()
        mock_user.name = "alice"
        resolved = {"alice": mock_user}

        # A link with @alice in href should not be double-replaced
        html = '<a href="/u/alice">@alice</a>'
        result = replace_mentions_with_links(html, resolved)
        # The href content should not be modified
        self.assertIn('href="/u/alice"', result)


# ---------------------------------------------------------------------------
# T8: Nesting depth settings
# ---------------------------------------------------------------------------


class TestNamespaceNestingDepth(unittest.TestCase):
    """Unit tests for T8: max_nesting_depth and collapse_depth."""

    def setUp(self):
        self.namespace = Namespace("nesting-test.example.com")
        self.namespace.subscription_type = "production"

    def test_default_max_nesting_depth_is_none(self):
        """Default max_nesting_depth is None (unlimited)."""
        self.assertIsNone(self.namespace.max_nesting_depth)

    def test_default_collapse_depth_is_none(self):
        """Default collapse_depth is None (never collapse)."""
        self.assertIsNone(self.namespace.collapse_depth)

    def test_max_nesting_depth_stores_correctly(self):
        """Setting max_nesting_depth stores and retrieves correctly."""
        self.namespace.max_nesting_depth = 3
        self.assertEqual(self.namespace.max_nesting_depth, 3)

    def test_collapse_depth_stores_correctly(self):
        """Setting collapse_depth stores and retrieves correctly."""
        self.namespace.collapse_depth = 5
        self.assertEqual(self.namespace.collapse_depth, 5)

    def test_nesting_depth_protected_on_development(self):
        """Nesting depth returns None defaults when subscription expires."""
        self.namespace.max_nesting_depth = 3
        self.namespace.collapse_depth = 2
        self.namespace.subscription_type = "development"
        self.namespace.reload_memoized_attr_protection()
        self.assertIsNone(self.namespace.max_nesting_depth)
        self.assertIsNone(self.namespace.collapse_depth)

    def test_node_depth_calculation(self):
        """Node depth is computed from path_to_root length."""
        root = Node()
        root.id = 1
        root.graph_depth = 0

        child = root.new_child()
        child.id = 2
        child.parent_id = 1
        child.root_id = 1
        child.graph_depth = -1
        root.children.append(child)

        grandchild = child.new_child()
        grandchild.id = 3
        grandchild.parent_id = 2
        grandchild.root_id = 1
        grandchild.graph_depth = -1
        child.children.append(grandchild)

        # Depth is length of path_to_root - 1
        self.assertEqual(root.depth, 0)
        self.assertEqual(child.depth, 1)
        self.assertEqual(grandchild.depth, 2)

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_models")
