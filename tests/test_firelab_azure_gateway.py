from __future__ import annotations

import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

from firelab_service.azure_gateway import AzurePublicGateway


class FakeBackendHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    captured = []

    def log_message(self, fmt, *args):
        return

    def _reply(self, status, body, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/session":
            self._reply(200, json.dumps({"token": "t" * 43, "offline": True}).encode())
        else:
            self._reply(200, b"<html>FireLab test</html>", "text/html; charset=utf-8")

    def do_HEAD(self):
        self._reply(200, b"", "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).captured.append({
            "path": self.path,
            "host": self.headers.get("Host"),
            "origin": self.headers.get("Origin"),
            "session": self.headers.get("X-FireLab-Session"),
            "fetch_site": self.headers.get("Sec-Fetch-Site"),
            "body": body,
        })
        self._reply(200, json.dumps({"ok": True}).encode())


class AzureGatewayTests(unittest.TestCase):
    def setUp(self):
        FakeBackendHandler.captured = []
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackendHandler)
        self.backend_thread = threading.Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        self.gateway = AzurePublicGateway(
            ("127.0.0.1", 0),
            public_hostname="demo.example.azurecontainerapps.io",
            backend_host="127.0.0.1",
            backend_port=self.backend.server_address[1],
            post_limit=90,
            rate_window=60,
        )
        self.gateway_thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.gateway_thread.start()
        self.port = self.gateway.server_address[1]
        self.host_headers = {
            "Host": "demo.example.azurecontainerapps.io",
            "X-Forwarded-Proto": "https",
        }

    def tearDown(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.backend.shutdown()
        self.backend.server_close()
        self.gateway_thread.join(timeout=2)
        self.backend_thread.join(timeout=2)

    def request(self, method, path, *, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        conn.close()
        return result

    def valid_post_headers(self, **overrides):
        headers = dict(self.host_headers)
        headers.update({
            "Content-Type": "application/json",
            "Content-Length": "19",
            "Origin": "https://demo.example.azurecontainerapps.io",
            "Sec-Fetch-Site": "same-origin",
            "X-FireLab-Session": "t" * 43,
        })
        headers.update(overrides)
        return headers

    def test_health_endpoint_is_minimal_and_has_no_secret(self):
        status, headers, body = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})
        self.assertNotIn("token", body.decode().lower())

    def test_valid_public_get_is_proxied_with_hsts(self):
        status, headers, body = self.request("GET", "/", headers=self.host_headers)
        self.assertEqual(status, 200)
        self.assertIn(b"FireLab test", body)
        self.assertEqual(headers.get("Strict-Transport-Security"), "max-age=31536000")
        self.assertEqual(headers.get("Content-Security-Policy"), "default-src 'none'; script-src 'self'")

    def test_session_bootstrap_is_proxied_without_cache(self):
        status, headers, body = self.request("GET", "/api/session", headers=self.host_headers | {"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["offline"], True)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_valid_post_translates_host_and_origin_to_loopback_backend(self):
        body = b'{"question":"ok"}'
        headers = self.valid_post_headers(**{"Content-Length": str(len(body))})
        status, _, payload = self.request("POST", "/api/assistant/ask", headers=headers, body=body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), {"ok": True})
        captured = FakeBackendHandler.captured[-1]
        self.assertEqual(captured["host"], f"127.0.0.1:{self.backend.server_address[1]}")
        self.assertEqual(captured["origin"], f"http://127.0.0.1:{self.backend.server_address[1]}")
        self.assertEqual(captured["session"], "t" * 43)
        self.assertEqual(captured["fetch_site"], "same-origin")
        self.assertEqual(captured["body"], body)

    def test_wrong_hostname_rejected(self):
        status, _, _ = self.request("GET", "/", headers=self.host_headers | {"Host": "attacker.example"})
        self.assertEqual(status, 403)

    def test_http_forwarded_protocol_rejected(self):
        status, _, _ = self.request("GET", "/", headers=self.host_headers | {"X-Forwarded-Proto": "http"})
        self.assertEqual(status, 403)

    def test_missing_forwarded_protocol_rejected(self):
        headers = {"Host": self.host_headers["Host"]}
        status, _, _ = self.request("GET", "/", headers=headers)
        self.assertEqual(status, 403)

    def test_unlisted_path_and_raw_source_rejected(self):
        for path in ("/secret.txt", "/data/source/PSI-25.csv", "/data_backup_20261030_041648/records.json", "/%2e%2e/etc/passwd"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path, headers=self.host_headers)
                self.assertIn(status, (400, 404))

    def test_post_rejects_bad_origin(self):
        body = b'{"question":"ok"}'
        headers = self.valid_post_headers(**{
            "Content-Length": str(len(body)),
            "Origin": "https://attacker.example",
        })
        self.assertEqual(self.request("POST", "/api/assistant/ask", headers=headers, body=body)[0], 403)

    def test_post_requires_origin_and_session(self):
        body = b'{"question":"ok"}'
        headers = self.valid_post_headers(**{"Content-Length": str(len(body))})
        headers.pop("Origin")
        self.assertEqual(self.request("POST", "/api/assistant/ask", headers=headers, body=body)[0], 403)
        headers = self.valid_post_headers(**{"Content-Length": str(len(body))})
        headers.pop("X-FireLab-Session")
        self.assertEqual(self.request("POST", "/api/assistant/ask", headers=headers, body=body)[0], 403)

    def test_post_rejects_cross_site_fetch(self):
        body = b'{"question":"ok"}'
        headers = self.valid_post_headers(**{
            "Content-Length": str(len(body)),
            "Sec-Fetch-Site": "cross-site",
        })
        self.assertEqual(self.request("POST", "/api/assistant/ask", headers=headers, body=body)[0], 403)

    def test_post_rejects_oversized_body_and_non_json(self):
        large = b"x" * 2049
        headers = self.valid_post_headers(**{"Content-Length": str(len(large))})
        self.assertEqual(self.request("POST", "/api/assistant/ask", headers=headers, body=large)[0], 413)
        body = b"{}"
        headers = self.valid_post_headers(**{"Content-Length": "2", "Content-Type": "text/plain"})
        self.assertEqual(self.request("POST", "/api/assistant/ask", headers=headers, body=body)[0], 415)

    def test_post_rejects_unknown_route_and_mutating_methods(self):
        body = b"{}"
        headers = self.valid_post_headers(**{"Content-Length": "2"})
        self.assertEqual(self.request("POST", "/api/admin", headers=headers, body=body)[0], 404)
        self.assertEqual(self.request("PUT", "/api/assistant/ask", headers=self.host_headers)[0], 405)

    def test_rate_limit_blocks_after_configured_window_capacity(self):
        self.gateway._rate_limiter = type(self.gateway._rate_limiter)(limit=1, window=60)
        body = b"{}"
        headers = self.valid_post_headers(**{"Content-Length": "2"})
        self.assertEqual(self.request("POST", "/api/assistant/ask", headers=headers, body=body)[0], 200)
        status, response_headers, _ = self.request("POST", "/api/assistant/ask", headers=headers, body=body)
        self.assertEqual(status, 429)
        self.assertGreaterEqual(int(response_headers["Retry-After"]), 1)

    def test_concurrency_limit_rejects_excess_requests_without_accept_loop_blocking(self):
        acquired = 0
        try:
            for _ in range(8):
                self.assertTrue(self.gateway._request_slots.acquire(blocking=False))
                acquired += 1
            status, headers, _ = self.request("GET", "/", headers=self.host_headers)
            self.assertEqual(status, 503)
            self.assertEqual(headers.get("Retry-After"), "10")
        finally:
            for _ in range(acquired):
                self.gateway._request_slots.release()

    def test_hostname_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            AzurePublicGateway(("127.0.0.1", 0), public_hostname="https://example.com")
        with self.assertRaises(ValueError):
            AzurePublicGateway(("127.0.0.1", 0), public_hostname="*.example.com")
        server = AzurePublicGateway(("127.0.0.1", 0), public_hostname=None)
        try:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            conn.request("GET", "/", headers={"Host": "demo.example.com", "X-Forwarded-Proto": "https"})
            response = conn.getresponse()
            self.assertEqual(response.status, 503)
            response.read()
            conn.close()
            server.shutdown()
            thread.join(timeout=2)
        finally:
            server.server_close()
