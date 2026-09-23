"""Client address from our ingress proxy.

Path: visitor -> ingress Caddy (sets X-Real-IP to the visitor) -> origin
Caddy -> uwsgi. Origin Caddy rewrites X-Forwarded-For to its own peer, the
ingress, & webob's `client_addr` reads X-Forwarded-For first, so every
visitor looked like 142.93.73.64: one shared rate-limit bucket & one IP on
every stored comment.

Trust holds because origin 443 answers only the ingress (salt firewall)
& origin port 80 only redirects. A value that does not parse as an IP is
ignored.
"""
import ipaddress


class RealIPMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        real = environ.get("HTTP_X_REAL_IP", "").strip()
        if real:
            try:
                ipaddress.ip_address(real)
            except ValueError:
                real = ""
        if real:
            environ["REMOTE_ADDR"] = real
            environ["HTTP_X_FORWARDED_FOR"] = real
        return self.app(environ, start_response)

    def __getattr__(self, name):
        return getattr(self.app, name)
