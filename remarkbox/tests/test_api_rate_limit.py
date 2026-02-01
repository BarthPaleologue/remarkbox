import time
import unittest
from unittest import mock

from pyramid.response import Response


class TestRateLimitTweenFactory(unittest.TestCase):
    """Unit tests for the rate limiting tween."""

    def _make_registry(self, read_requests=5, write_requests=2, window=10):
        registry = mock.MagicMock()
        registry.settings = {
            "api.rate_limit.read_requests": str(read_requests),
            "api.rate_limit.write_requests": str(write_requests),
            "api.rate_limit.window": str(window),
        }
        return registry

    def _make_request(self, path="/api/v1/threads", method="GET", ip="127.0.0.1"):
        request = mock.MagicMock()
        request.path = path
        request.method = method
        request.client_addr = ip
        request.session = {}
        return request

    def _make_handler(self):
        response = Response(json_body={"ok": True}, status=200)
        return mock.MagicMock(return_value=response)

    def test_allows_requests_under_limit(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=5)
        tween = rate_limit_tween_factory(handler, registry)

        request = self._make_request()
        response = tween(request)
        self.assertEqual(response.status_int, 200)
        self.assertTrue(handler.called)

    def test_blocks_requests_over_read_limit(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=3, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        for i in range(3):
            request = self._make_request(ip="10.0.0.1")
            response = tween(request)
            self.assertEqual(response.status_int, 200)

        # 4th request should be blocked
        request = self._make_request(ip="10.0.0.1")
        response = tween(request)
        self.assertEqual(response.status_int, 429)
        self.assertIn("Rate limit exceeded", response.json_body["error"])
        self.assertIn("retry_after", response.json_body)

    def test_blocks_requests_over_write_limit(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(write_requests=2, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        for i in range(2):
            request = self._make_request(method="POST", ip="10.0.0.2")
            response = tween(request)
            self.assertEqual(response.status_int, 200)

        # 3rd POST should be blocked
        request = self._make_request(method="POST", ip="10.0.0.2")
        response = tween(request)
        self.assertEqual(response.status_int, 429)

    def test_separate_read_write_limits(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=10, write_requests=2, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        # Exhaust write limit
        for i in range(2):
            request = self._make_request(method="POST", ip="10.0.0.3")
            tween(request)

        # POST should be blocked
        request = self._make_request(method="POST", ip="10.0.0.3")
        response = tween(request)
        self.assertEqual(response.status_int, 429)

        # But GET should still work (different limit counter but same key,
        # however read limit is 10 and we only have 2 entries)
        request = self._make_request(method="GET", ip="10.0.0.3")
        response = tween(request)
        self.assertEqual(response.status_int, 200)

    def test_skips_non_api_routes(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=1)
        tween = rate_limit_tween_factory(handler, registry)

        # Make many requests to non-API paths
        for i in range(10):
            request = self._make_request(path="/some-page", ip="10.0.0.4")
            response = tween(request)
            self.assertEqual(response.status_int, 200)

    def test_per_ip_isolation(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=2, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        # Exhaust limit for IP A
        for i in range(2):
            request = self._make_request(ip="10.0.0.5")
            tween(request)

        # IP A is blocked
        request = self._make_request(ip="10.0.0.5")
        response = tween(request)
        self.assertEqual(response.status_int, 429)

        # IP B still works
        request = self._make_request(ip="10.0.0.6")
        response = tween(request)
        self.assertEqual(response.status_int, 200)

    def test_per_user_keying_when_authenticated(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=2, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        # Authenticated user from different IPs should share limit
        for i in range(2):
            request = self._make_request(ip="10.0.0.{}".format(10 + i))
            request.session = {"authenticated_user_id": "user-abc-123"}
            tween(request)

        # 3rd request with same user, different IP, should be blocked
        request = self._make_request(ip="10.0.0.99")
        request.session = {"authenticated_user_id": "user-abc-123"}
        response = tween(request)
        self.assertEqual(response.status_int, 429)

    def test_window_expiry(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=2, window=1)
        tween = rate_limit_tween_factory(handler, registry)

        # Exhaust limit
        for i in range(2):
            request = self._make_request(ip="10.0.0.7")
            tween(request)

        # Blocked
        request = self._make_request(ip="10.0.0.7")
        response = tween(request)
        self.assertEqual(response.status_int, 429)

        # Wait for window to expire
        time.sleep(1.1)

        # Should work again
        request = self._make_request(ip="10.0.0.7")
        response = tween(request)
        self.assertEqual(response.status_int, 200)

    def test_patch_uses_write_limit(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(write_requests=1, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        request = self._make_request(method="PATCH", ip="10.0.0.8")
        response = tween(request)
        self.assertEqual(response.status_int, 200)

        request = self._make_request(method="PATCH", ip="10.0.0.8")
        response = tween(request)
        self.assertEqual(response.status_int, 429)

    def test_delete_uses_write_limit(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(write_requests=1, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        request = self._make_request(method="DELETE", ip="10.0.0.9")
        response = tween(request)
        self.assertEqual(response.status_int, 200)

        request = self._make_request(method="DELETE", ip="10.0.0.9")
        response = tween(request)
        self.assertEqual(response.status_int, 429)

    def test_retry_after_value(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry(read_requests=1, window=60)
        tween = rate_limit_tween_factory(handler, registry)

        request = self._make_request(ip="10.0.0.10")
        tween(request)

        request = self._make_request(ip="10.0.0.10")
        response = tween(request)
        self.assertEqual(response.status_int, 429)
        retry_after = response.json_body["retry_after"]
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, 61)

    def test_defaults_when_no_settings(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = mock.MagicMock()
        registry.settings = {}
        tween = rate_limit_tween_factory(handler, registry)

        # Should use defaults (120 read, 30 write, 60s window)
        request = self._make_request(ip="10.0.0.11")
        response = tween(request)
        self.assertEqual(response.status_int, 200)

    def test_global_api_disabled(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry()
        registry.settings["api.enabled"] = "false"
        tween = rate_limit_tween_factory(handler, registry)

        request = self._make_request(ip="10.0.0.12")
        response = tween(request)
        self.assertEqual(response.status_int, 404)
        self.assertIn("disabled", response.json_body["error"])
        self.assertFalse(handler.called)

    def test_global_api_disabled_skips_non_api(self):
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        handler = self._make_handler()
        registry = self._make_registry()
        registry.settings["api.enabled"] = "false"
        tween = rate_limit_tween_factory(handler, registry)

        # Non-API path should still work even if API is disabled
        request = self._make_request(path="/some-page", ip="10.0.0.13")
        response = tween(request)
        self.assertEqual(response.status_int, 200)
        self.assertTrue(handler.called)
