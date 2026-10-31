#!/usr/bin/env python3
"""
BooStudy Mini App Isolated Reverse Proxy Gateway.

Restricts public exposure when tunneling to Telegram Mini App:
- Exposes ONLY: /tg-app, /tg-app/*, whitelisted /static/*, and /healthz.
- Strictly BLOCKS all other BooStudy routes (/admin, /login, /workspace, /api, etc.) with 403.
- Strips ambient session cookies on /tg-app/api/* to enforce pure initData auth.
- Normalizes Host headers to prevent Host Header Injection attacks.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [GATEWAY] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('mini_app_gateway')

# Whitelisted path patterns
ALLOWED_STATIC_PREFIXES = (
    '/static/dist/',
    '/static/icons/',
    '/static/fonts/',
    '/static/css/',
    '/static/js/',
    '/static/platform-feedback.js',
    '/static/toast.js',
)


def is_path_permitted(path: str) -> tuple[bool, str]:
    """Inspect request path against strict Mini App whitelist."""
    if not path or not path.startswith('/'):
        return False, "Path must start with /"
    if path.startswith('//') or '//' in path:
        return False, "Double slash in path rejected"

    unquoted_path = urllib.parse.unquote(path)
    if '..' in unquoted_path:
        return False, "Directory traversal rejected"

    parsed = urllib.parse.urlparse(unquoted_path)
    clean_path = parsed.path

    # Root redirect
    if clean_path == '/':
        return True, "root_redirect"

    # Diagnostic ping
    if clean_path == '/healthz':
        return True, "health_check"

    # Mini App routes
    if clean_path == '/tg-app' or clean_path.startswith('/tg-app/'):
        return True, "mini_app"

    # Static assets needed by Mini App UI
    if any(clean_path.startswith(prefix) for prefix in ALLOWED_STATIC_PREFIXES):
        return True, "static_asset"

    return False, f"Path '{clean_path}' is not in Mini App whitelist"


def is_method_permitted(method: str, path: str) -> bool:
    """Enforce minimal HTTP methods per path."""
    clean_path = urllib.parse.urlparse(path).path
    if clean_path.startswith('/tg-app/api/'):
        return method in ('POST', 'GET')
    return method in ('GET', 'HEAD')


class MiniAppGatewayHandler(BaseHTTPRequestHandler):
    """Proxy HTTP handler enforcing security boundary."""

    server_version = "BooStudyMiniAppGateway/2.0"

    def log_message(self, format: str, *args) -> None:
        # Override BaseHTTPRequestHandler default logging to use standard logger
        pass

    def do_HEAD(self) -> None:
        self._handle_request('HEAD')

    def do_GET(self) -> None:
        self._handle_request('GET')

    def do_POST(self) -> None:
        self._handle_request('POST')

    def do_PUT(self) -> None:
        self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "Method PUT not permitted on Mini App Gateway")

    def do_DELETE(self) -> None:
        self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "Method DELETE not permitted on Mini App Gateway")

    def do_PATCH(self) -> None:
        self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "Method PATCH not permitted on Mini App Gateway")

    def _reject(self, status: HTTPStatus, message: str) -> None:
        logger.warning("[BLOCKED %s] %s %s -> %s", status.value, self.command, self.path, message)
        body = json.dumps({
            "error": "access_denied",
            "status": status.value,
            "message": message,
            "path": self.path,
        }, indent=2).encode('utf-8')

        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

    def _handle_request(self, method: str) -> None:
        clean_path = urllib.parse.urlparse(self.path).path

        # 1. Root redirect to /tg-app/
        if clean_path in ('', '/'):
            self.send_response(HTTPStatus.FOUND)
            self.send_header('Location', '/tg-app/')
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
            logger.info("[REDIRECT] %s -> /tg-app/", self.path)
            return

        # 2. Diagnostic health route
        if clean_path == '/healthz':
            body = json.dumps({
                "status": "healthy",
                "service": "boostudy-mini-app-gateway",
                "upstream": self.server.upstream_url,
                "exposed_endpoints": ["/tg-app/", "/tg-app/api/*"],
            }, indent=2).encode('utf-8')
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            if method != 'HEAD':
                self.wfile.write(body)
            return

        # 3. Path whitelist check
        permitted, reason = is_path_permitted(self.path)
        if not permitted:
            self._reject(HTTPStatus.FORBIDDEN, reason)
            return

        # 4. Method restriction check
        if not is_method_permitted(method, self.path):
            self._reject(HTTPStatus.METHOD_NOT_ALLOWED, f"Method {method} not allowed for {clean_path}")
            return

        # 5. Read incoming body if POST
        content_length = int(self.headers.get('Content-Length', 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else None

        # 6. Build upstream request
        target_url = f"{self.server.upstream_url.rstrip('/')}{self.path}"
        req = urllib.request.Request(target_url, data=body_bytes, method=method)

        # 7. Header sanitization & proxy forwarding
        for header, value in self.headers.items():
            h_lower = header.lower()
            # Strip dangerous or hop-by-hop headers
            if h_lower in (
                'host', 'connection', 'proxy-connection',
                'x-forwarded-host', 'x-forwarded-prefix', 'x-original-url', 'x-rewrite-url',
            ):
                continue

            # Strip session / ambient cookies entirely to ensure pure token/initData auth
            # and prevent cookie leakage between environments.
            if h_lower == 'cookie':
                continue

            req.add_header(header, value)

        # Set normalized host and forwarding headers
        upstream_parsed = urllib.parse.urlparse(self.server.upstream_url)
        req.add_header('Host', upstream_parsed.netloc)
        client_ip = self.client_address[0] if self.client_address else '127.0.0.1'
        req.add_header('X-Forwarded-For', client_ip)
        req.add_header('X-Forwarded-Proto', 'https' if self.headers.get('X-Forwarded-Proto') == 'https' else 'http')

        # 8. Execute upstream call
        try:
            direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with direct_opener.open(req, timeout=15) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for h, v in resp.getheaders():
                    # Strip hop-by-hop headers and prevent cookie setting across tunnel
                    if h.lower() in ('connection', 'transfer-encoding', 'keep-alive', 'set-cookie'):
                        continue
                    self.send_header(h, v)
                self.send_header('Connection', 'close')
                self.end_headers()
                if method != 'HEAD':
                    self.wfile.write(resp_body)
                logger.info("[PROXY OK %s] %s %s (%d bytes)", resp.status, method, clean_path, len(resp_body))
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            for h, v in e.headers.items():
                if h.lower() in ('connection', 'transfer-encoding', 'set-cookie'):
                    continue
                self.send_header(h, v)
            self.send_header('Connection', 'close')
            self.end_headers()
            if method != 'HEAD':
                self.wfile.write(err_body)
            logger.info("[PROXY ERR %s] %s %s", e.code, method, clean_path)
        except Exception as exc:
            logger.error("[GATEWAY FAIL] %s %s -> %s", method, clean_path, exc)
            self._reject(HTTPStatus.BAD_GATEWAY, f"Upstream BooStudy backend unreachable: {exc}")


class MiniAppGatewayServer(ThreadingHTTPServer):
    """Threading HTTP Server holding upstream URL configuration."""

    def __init__(self, server_address, RequestHandlerClass, upstream_url: str):
        self.upstream_url = upstream_url
        super().__init__(server_address, RequestHandlerClass)


def run_gateway(bind_host: str = "127.0.0.1", port: int = 5050, upstream: str = "http://127.0.0.1:5000") -> None:
    """Launch the Mini App Gateway."""
    server = MiniAppGatewayServer((bind_host, port), MiniAppGatewayHandler, upstream_url=upstream)
    print("=" * 64)
    print("  BooStudy Mini App Isolated Reverse Proxy Gateway")
    print("=" * 64)
    print(f"  * Gateway listening on:  http://{bind_host}:{port}")
    print(f"  * Upstream backend:      {upstream}")
    print("  * Allowed public routes: /tg-app/, /tg-app/api/*, /static/*, /healthz")
    print("  * Blocked public routes: /admin, /login, /workspace, /api/*, ALL others")
    print("  * Session cookies:       Stripped for /tg-app/api/* (initData only)")
    print("=" * 64)
    print("Ready to receive requests. Press Ctrl+C to terminate.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[GATEWAY] Shutting down Mini App Gateway...")
    finally:
        server.server_close()
        print("[GATEWAY] Gateway stopped cleanly.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="BooStudy Mini App Isolated Gateway")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind IP address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5050, help="Listen port (default 5050)")
    parser.add_argument("--upstream", default="http://127.0.0.1:5000", help="Upstream Flask URL (default http://127.0.0.1:5000)")
    args = parser.parse_args()

    run_gateway(bind_host=args.bind, port=args.port, upstream=args.upstream)
