import unittest

from webob import Request

from remarkbox.lib.real_ip import RealIPMiddleware


def _client_addr(headers, remote="127.0.0.1"):
    seen = {}

    def app(environ, start_response):
        seen["addr"] = Request(environ).client_addr
        start_response("200 OK", [])
        return [b""]

    req = Request.blank("/", headers=headers, remote_addr=remote)
    req.get_response(RealIPMiddleware(app))
    return seen["addr"]


class TestRealIP(unittest.TestCase):
    def test_x_real_ip_beats_rewritten_forwarded_for(self):
        # Origin Caddy rewrites X-Forwarded-For to the ingress.
        headers = {"X-Real-IP": "203.0.113.9", "X-Forwarded-For": "142.93.73.64"}
        self.assertEqual(_client_addr(headers), "203.0.113.9")

    def test_ipv6(self):
        self.assertEqual(_client_addr({"X-Real-IP": "2001:db8::1"}), "2001:db8::1")

    def test_garbage_ignored(self):
        headers = {"X-Real-IP": "not-an-ip", "X-Forwarded-For": "142.93.73.64"}
        self.assertEqual(_client_addr(headers), "142.93.73.64")

    def test_absent_leaves_request_alone(self):
        self.assertEqual(_client_addr({}, remote="198.51.100.4"), "198.51.100.4")
