import transaction
import unittest
import webtest
import json
import io

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_user_by_email,
    get_or_create_namespace,
)

from remarkbox.models.meta import Base
from pyramid.paster import get_appsettings

try:
    unicode("")
except:
    from six import u as unicode


class ImportCommentsFunctionalTests(unittest.TestCase):
    """Tests for the import comments functionality"""

    @classmethod
    def setUpClass(cls):
        from remarkbox import main

        cls.settings = get_appsettings("test.ini")
        cls.app = main({}, **cls.settings)
        cls.testapp = webtest.TestApp(cls.app)

        cls.session_factory = cls.app.registry["dbsession_factory"]
        cls.engine = cls.session_factory.kw["bind"]
        Base.metadata.create_all(bind=cls.engine)

        cls.tm = transaction.manager
        cls.dbsession = get_tm_session(cls.session_factory, cls.tm)

    @classmethod
    def tearDownClass(cls):
        cls.dbsession.close()
        Base.metadata.drop_all(bind=cls.engine)

    def setUp(self):
        # Create test user and authenticate
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "owner@example.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)
        self.dbsession.flush()
        self.tm.commit()

        # Requery to avoid detached instance error
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "owner@example.com"
        )

        # Log in the test user
        self.testapp.post(
            f"/verification-challenge?email=owner@example.com&raw-otp={self.raw_otp}&submit"
        )

        # Get CSRF token
        res_csrf = self.testapp.get("/")
        self.csrf = res_csrf.form.fields["csrf_token"][0].value

        # Create a test namespace and make the user an owner
        self.test_namespace = get_or_create_namespace(
            self.dbsession, "test.example.com"
        )
        self.test_namespace.set_role_for_user(self.test_user, role="owner")
        self.dbsession.add(self.test_namespace)
        self.dbsession.flush()
        self.tm.commit()

    def tearDown(self):
        # Clean up: log out
        self.testapp.get("/log-out")

    def get_test_namespace(self):
        """Helper to get fresh namespace object from DB"""
        from remarkbox.models import get_namespace_by_name
        return get_namespace_by_name(self.dbsession, "test.example.com")

    def test_import_page_requires_authentication(self):
        """Test that the import page requires user authentication"""
        self.testapp.get("/log-out")
        redirect_res = self.testapp.get(
            "/ns/test.example.com/import-comments", status=302
        )
        res = redirect_res.follow()
        self.assertIn(b"You must log in to access that area.", res.body)

    def test_import_page_requires_namespace_ownership(self):
        """Test that the import page requires namespace ownership"""
        # Create a different user
        other_user = get_or_create_user_by_email(
            self.dbsession, "other@example.com"
        )
        other_otp = other_user.new_password()
        self.dbsession.add(other_user)
        self.dbsession.flush()
        self.tm.commit()

        # Log out current user and log in as other user
        self.testapp.get("/log-out")
        self.testapp.post(
            f"/verification-challenge?email=other@example.com&raw-otp={other_otp}&submit"
        )

        # Try to access import page
        redirect_res = self.testapp.get(
            "/ns/test.example.com/import-comments", status=302
        )
        res = redirect_res.follow()
        self.assertIn(b"You do not own that Namespace.", res.body)

        # Clean up
        self.dbsession.delete(other_user)
        self.dbsession.flush()
        self.tm.commit()

    def test_import_page_displays_correctly(self):
        """Test that the import page displays correctly for namespace owners"""
        res = self.testapp.get("/ns/test.example.com/import-comments", status=200)
        self.assertIn(b"Import Comments", res.body)
        self.assertIn(b"blog-to-json", res.body)
        self.assertIn(b"How to Use", res.body)
        self.assertIn(b"JSON File:", res.body)
        self.assertIn(b"Automatic user creation", res.body)

    def test_import_requires_file(self):
        """Test that import fails without a file upload"""
        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            status=200,
        )
        self.assertIn(b"Please select a JSON file to upload.", res.body)

    def test_import_invalid_json(self):
        """Test that import fails with invalid JSON"""
        invalid_json_content = b"{ invalid json content"

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "test.json", invalid_json_content)],
            status=200,
        )
        self.assertIn(b"Invalid JSON file", res.body)

    def test_import_valid_json_with_comments(self):
        """Test successful import of comments from valid JSON"""
        # Create a valid Disqus export JSON
        disqus_data = {
            "test-post": {
                "link": "https://example.com/test-post",
                "comments": [
                    {
                        "id": "1",
                        "author": "John Doe",
                        "email": "john@example.com",
                        "content": "This is a test comment",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                    {
                        "id": "2",
                        "author": "Jane Smith",
                        "email": "jane@example.com",
                        "content": "This is a reply",
                        "timestamp": 1234567900,
                        "parent_id": "1",
                        "author_ip": "127.0.0.2",
                    },
                ],
            }
        }

        json_content = json.dumps(disqus_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "disqus.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"1 threads", res.body)
        self.assertIn(b"2 comments", res.body)

    def test_import_with_user_surrogates(self):
        """Test import automatically creates surrogates for comments without email"""
        disqus_data = {
            "test-post": {
                "link": "https://example.com/surrogate-test",
                "comments": [
                    {
                        "id": "1",
                        "author": "Anonymous User",
                        "email": "",
                        "content": "Anonymous comment",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                ],
            }
        }

        json_content = json.dumps(disqus_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "disqus.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"1 comments", res.body)

    def test_import_with_automatic_group_postfix(self):
        """Test import automatically adds group postfix to all new users"""
        disqus_data = {
            "test-post": {
                "link": "https://example.com/group-test",
                "comments": [
                    {
                        "id": "1",
                        "author": "Test User",
                        "email": "testgroup@example.com",
                        "content": "Test comment",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                ],
            }
        }

        json_content = json.dumps(disqus_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "disqus.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)

        # Verify user was created with automatic group postfix
        user = get_user_by_email(self.dbsession, "testgroup@example.com")
        self.assertIsNotNone(user)
        # Should have postfix pattern in username (e.g., "Test-User-te")
        self.assertIn("-", user.name)

    def test_import_empty_comments(self):
        """Test import with threads that have no comments"""
        disqus_data = {
            "empty-post": {
                "link": "https://example.com/empty-post",
                "comments": [],
            }
        }

        json_content = json.dumps(disqus_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "disqus.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"0 threads", res.body)
        self.assertIn(b"0 comments", res.body)

    def test_namespace_settings_links_to_import(self):
        """Test that namespace settings page has a link to import page"""
        res = self.testapp.get("/ns/test.example.com/settings", status=200)
        self.assertIn(b"Import Comments", res.body)
        self.assertIn(b"import-comments", res.body)

    def test_import_wordpress_format(self):
        """Test import from WordPress XML export (blog-to-json format)"""
        # Mock WordPress export data converted by wordpress-xml-to-json
        wordpress_data = {
            "homegrown-python-bread-crumb-module": {
                "name": "a-homegrown-python-bread-crumb-module",
                "title": "A homegrown python bread crumb module",
                "timestamp": 1293995686,
                "link": "http://russell.ballestrini.net/a-homegrown-python-bread-crumb-module/",
                "date": "2011-01-02 14:14:46",
                "content": "<p>Some content here</p>",
                "comments": [
                    {
                        "id": "wp-1",
                        "date": "2011-04-03 10:33:07",
                        "timestamp": 1301841187,
                        "content": "Hi, this was just what I needed",
                        "email": "kristian@example.com",
                        "author": "Kristian",
                        "author_ip": "192.168.1.5",
                        "parent_id": None,
                    },
                    {
                        "id": "wp-2",
                        "date": "2011-04-03 14:19:46",
                        "timestamp": 1301854786,
                        "content": "I'm interested in the modifications",
                        "email": "russell@example.com",
                        "author": "Russell Ballestrini",
                        "author_ip": "192.168.1.6",
                        "parent_id": None,
                    }
                ],
            }
        }

        json_content = json.dumps(wordpress_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "wordpress.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"1 threads", res.body)
        self.assertIn(b"2 comments", res.body)

        # Verify users were created
        kristian = get_user_by_email(self.dbsession, "kristian@example.com")
        self.assertIsNotNone(kristian)
        russell = get_user_by_email(self.dbsession, "russell@example.com")
        self.assertIsNotNone(russell)

    def test_import_graphcomment_format(self):
        """Test import from Graphcomment WordPress XML export (blog-to-json format)"""
        # Mock Graphcomment export data converted by graphcomment-xml-to-json
        graphcomment_data = {
            "posts_jupyter-orgmode": {
                "content": None,
                "link": "https://abc.xyz/posts/jupyter-orgmode/",
                "name": "posts_jupyter-orgmode",
                "title": "Reflections on Jupyter",
                "date": "2020-09-22 15:57:34",
                "timestamp": 1600790254,
                "id": "5f6a1eee2f57815d17188de2",
                "metadata": {},
                "comments": [
                    {
                        "id": "60750d2613ebd3704ec85f6f",
                        "content": "Thanks!!!!! a lot!!!",
                        "parent_id": None,
                        "author": "SamTux",
                        "date": "2021-04-13 03:16:54",
                        "timestamp": 1618283814,
                        "author_ip": "190.25.34.217",
                        "email": "samtux@example.com"
                    },
                    {
                        "id": "60750d2613ebd3704ec85f70",
                        "content": "You're welcome!",
                        "parent_id": "60750d2613ebd3704ec85f6f",
                        "author": "BlogAuthor",
                        "date": "2021-04-14 10:20:00",
                        "timestamp": 1618395600,
                        "author_ip": "192.168.1.1",
                        "email": "author@example.com"
                    }
                ],
            }
        }

        json_content = json.dumps(graphcomment_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "graphcomment.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"1 threads", res.body)
        self.assertIn(b"2 comments", res.body)

    def test_import_with_deep_nesting(self):
        """Test import with deeply nested comment hierarchy"""
        nested_data = {
            "nested-discussion": {
                "link": "https://example.com/nested-discussion",
                "title": "Nested Discussion",
                "timestamp": 1234567890,
                "comments": [
                    {
                        "id": "1",
                        "author": "User1",
                        "email": "user1@example.com",
                        "content": "Top level comment",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                    {
                        "id": "2",
                        "author": "User2",
                        "email": "user2@example.com",
                        "content": "Reply to comment 1",
                        "timestamp": 1234567900,
                        "parent_id": "1",
                        "author_ip": "127.0.0.2",
                    },
                    {
                        "id": "3",
                        "author": "User3",
                        "email": "user3@example.com",
                        "content": "Reply to comment 2",
                        "timestamp": 1234567910,
                        "parent_id": "2",
                        "author_ip": "127.0.0.3",
                    },
                    {
                        "id": "4",
                        "author": "User4",
                        "email": "user4@example.com",
                        "content": "Reply to comment 3",
                        "timestamp": 1234567920,
                        "parent_id": "3",
                        "author_ip": "127.0.0.4",
                    },
                ],
            }
        }

        json_content = json.dumps(nested_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "nested.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"1 threads", res.body)
        self.assertIn(b"4 comments", res.body)

    def test_import_duplicate_prevention(self):
        """Test that re-importing the same data reuses existing users"""
        test_data = {
            "test-duplicate": {
                "link": "https://example.com/test-duplicate",
                "comments": [
                    {
                        "id": "dup-1",
                        "author": "DupUser",
                        "email": "dup@example.com",
                        "content": "First import",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                ],
            }
        }

        json_content = json.dumps(test_data).encode("utf-8")

        # First import
        res1 = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "dup.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res1.body)
        self.assertIn(b"1 threads", res1.body)
        self.assertIn(b"1 comments", res1.body)

        # Second import - should succeed and reuse existing user
        res2 = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "dup.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res2.body)
        self.assertIn(b"1 threads", res2.body)
        self.assertIn(b"1 comments", res2.body)

        # Verify only one user was created (this check works across transactions)
        from remarkbox.models import User
        user_count = self.dbsession.query(User).filter(
            User.email == "dup@example.com"
        ).count()
        self.assertEqual(user_count, 1)

    def test_import_with_locked_group_postfix(self):
        """Test that group postfix gets locked after first import"""
        # Create a unique namespace for this test
        from remarkbox.models import get_namespace_by_name
        lock_test_ns = get_or_create_namespace(self.dbsession, "lock-test.example.com")
        lock_test_ns.set_role_for_user(self.test_user, role="owner")
        self.dbsession.add(lock_test_ns)
        self.dbsession.flush()
        self.tm.commit()

        test_data = {
            "test-lock": {
                "link": "https://example.com/test-lock",
                "comments": [
                    {
                        "id": "lock-1",
                        "author": "LockUser",
                        "email": "lock@example.com",
                        "content": "Test locking",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                ],
            }
        }

        json_content = json.dumps(test_data).encode("utf-8")

        # First import - postfix should be set
        res1 = self.testapp.post(
            "/ns/lock-test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
                "group-prefix": "mygrp",
            },
            upload_files=[("json-file", "lock.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res1.body)

        # Reload namespace to check postfix was locked
        namespace = get_namespace_by_name(self.dbsession, "lock-test.example.com")
        self.assertEqual(namespace.import_group_postfix, "mygrp")

        # Second import should use locked postfix regardless of input
        res2 = self.testapp.post(
            "/ns/lock-test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
                "group-prefix": "different",  # This should be ignored
            },
            upload_files=[("json-file", "lock2.json", json_content)],
            status=200,
        )

        # Verify postfix didn't change
        namespace = get_namespace_by_name(self.dbsession, "lock-test.example.com")
        self.assertEqual(namespace.import_group_postfix, "mygrp")

    def test_import_with_missing_email_creates_surrogates(self):
        """Test that comments without email create unique surrogates"""
        test_data = {
            "test-surrogates": {
                "link": "https://example.com/test-surrogates",
                "comments": [
                    {
                        "id": "s1",
                        "author": "Guest1",
                        "email": "",
                        "content": "First guest comment",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                    {
                        "id": "s2",
                        "author": "Guest2",
                        "email": "",
                        "content": "Second guest comment",
                        "timestamp": 1234567900,
                        "parent_id": None,
                        "author_ip": "127.0.0.2",
                    },
                    {
                        "id": "s3",
                        "author": "Guest1",  # Same name as first
                        "email": "",
                        "content": "Another comment from Guest1",
                        "timestamp": 1234567910,
                        "parent_id": None,
                        "author_ip": "127.0.0.3",
                    },
                ],
            }
        }

        json_content = json.dumps(test_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "surrogates.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"3 comments", res.body)

        # Verify surrogates were created
        from remarkbox.models import UserSurrogate
        namespace = self.get_test_namespace()
        surrogates = self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == namespace.id
        ).all()

        # Should have 2 unique surrogates (Guest1 and Guest2)
        # Guest1 appearing twice should reuse the same surrogate
        self.assertEqual(len(surrogates), 2)

        # Verify surrogate names include group postfix
        surrogate_names = [s.name for s in surrogates]
        for name in surrogate_names:
            self.assertIn("-", name)  # Should have postfix

    def test_import_with_missing_fields(self):
        """Test import handles missing optional fields gracefully"""
        test_data = {
            "test-missing-fields": {
                "link": "https://example.com/test-missing",
                "comments": [
                    {
                        "id": "m1",
                        "author": "MinimalUser",
                        "email": "minimal@example.com",
                        "content": "Minimal comment",
                        "timestamp": 1234567890,
                        # Missing parent_id
                        # Missing author_ip
                    },
                ],
            }
        }

        json_content = json.dumps(test_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "missing.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"1 comments", res.body)

    def test_import_multiple_threads(self):
        """Test importing multiple threads in one file"""
        multi_thread_data = {
            "thread-1": {
                "link": "https://example.com/thread-1",
                "comments": [
                    {
                        "id": "t1-c1",
                        "author": "User1",
                        "email": "user1@example.com",
                        "content": "Comment on thread 1",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                ],
            },
            "thread-2": {
                "link": "https://example.com/thread-2",
                "comments": [
                    {
                        "id": "t2-c1",
                        "author": "User2",
                        "email": "user2@example.com",
                        "content": "Comment on thread 2",
                        "timestamp": 1234567900,
                        "parent_id": None,
                        "author_ip": "127.0.0.2",
                    },
                ],
            },
            "thread-3": {
                "link": "https://example.com/thread-3",
                "comments": [
                    {
                        "id": "t3-c1",
                        "author": "User3",
                        "email": "user3@example.com",
                        "content": "Comment on thread 3",
                        "timestamp": 1234567910,
                        "parent_id": None,
                        "author_ip": "127.0.0.3",
                    },
                ],
            },
        }

        json_content = json.dumps(multi_thread_data).encode("utf-8")

        res = self.testapp.post(
            "/ns/test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
            },
            upload_files=[("json-file", "multi.json", json_content)],
            status=200,
        )

        self.assertIn(b"Successfully imported", res.body)
        self.assertIn(b"3 threads", res.body)
        self.assertIn(b"3 comments", res.body)

    def test_import_with_invalid_group_postfix(self):
        """Test that invalid group postfix shows error"""
        # Create a unique namespace for this test
        invalid_test_ns = get_or_create_namespace(self.dbsession, "invalid-test.example.com")
        invalid_test_ns.set_role_for_user(self.test_user, role="owner")
        self.dbsession.add(invalid_test_ns)
        self.dbsession.flush()
        self.tm.commit()

        test_data = {
            "test": {
                "link": "https://example.com/test",
                "comments": [
                    {
                        "id": "1",
                        "author": "User",
                        "email": "user@example.com",
                        "content": "Test",
                        "timestamp": 1234567890,
                        "parent_id": None,
                        "author_ip": "127.0.0.1",
                    },
                ],
            }
        }

        json_content = json.dumps(test_data).encode("utf-8")

        # Try with too short postfix
        res = self.testapp.post(
            "/ns/invalid-test.example.com/import-comments",
            {
                "csrf_token": self.csrf,
                "group-prefix": "x",  # Only 1 char, minimum is 2
            },
            upload_files=[("json-file", "invalid.json", json_content)],
            status=200,
        )

        self.assertIn(b"Group postfix is required and must be at least 2 alphanumeric characters", res.body)


class ImportCommentsUnitTests(unittest.TestCase):
    """Unit tests for import_comments view functions"""

    def test_generate_password(self):
        """Test password generation utility"""
        from remarkbox.views.authenticated.import_comments import generate_password

        password = generate_password(32)
        self.assertEqual(len(password), 32)
        self.assertTrue(all(c.isalnum() for c in password))

    def test_generate_password_custom_size(self):
        """Test password generation with custom size"""
        from remarkbox.views.authenticated.import_comments import generate_password

        password = generate_password(16)
        self.assertEqual(len(password), 16)

    def test_generate_group_prefix_from_namespace(self):
        """Test group prefix generation from namespace domain"""
        from remarkbox.views.authenticated.import_comments import generate_group_prefix_from_namespace

        # Test multi-part domain
        self.assertEqual(generate_group_prefix_from_namespace("russell.ballestrini.net"), "rb")

        # Test with www prefix
        self.assertEqual(generate_group_prefix_from_namespace("www.example.com"), "exampl")

        # Test single-part domain
        self.assertEqual(generate_group_prefix_from_namespace("example.com"), "exampl")

        # Test my.remarkbox.com style
        prefix = generate_group_prefix_from_namespace("my.remarkbox.com")
        self.assertTrue(len(prefix) <= 6)
        self.assertTrue(prefix.isalnum())

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_import_comments")
