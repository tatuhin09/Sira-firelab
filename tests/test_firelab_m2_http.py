import http.client
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from firelab_service.http_app import create_server


class FakeAssistantService:
    def ask(self, question, *, conversation_id):
        return {
            "title": "Verified answer", "text": f"Answer for {question}",
            "status": "completed", "conversation_id": conversation_id,
            "events": [{"type": "answer.completed", "summary": "Done"}],
        }


class FakeService:
    def search(self, query, *, refresh=False):
        return {
            "state": "fresh", "query": query,
            "papers": [{"title": "Test result"}],
            "retrieved_at": "2026-10-31T00:00:00Z",
            "providers": ["crossref"], "partial": False,
        }


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        (self.repo / "firelab_service" / "paper_search").mkdir(parents=True)
        (self.repo / "firelab_service" / "paper_search" / "research_worker.py").write_text("pass\n")
        (self.repo / "src").mkdir()
        site = self.repo / "firelab_site"
        site.mkdir()
        (site / "index.html").write_text("<html>test</html>")
        (site / "styles.css").write_text("body{}")
        (site / "data_backup_20261030_041648").mkdir()
        (site / "data_backup_20261030_041648" / "records.json").write_text("[]")
        self.server = create_server(self.repo, port=0, service=FakeService(), assistant_service=FakeAssistantService())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def request(self, method, path, *, headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        content = response.read()
        result = (response.status, response.headers, content)
        connection.close()
        return result

    def session(self):
        status, headers, body = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertIn("script-src 'self'", headers.get("Content-Security-Policy"))
        self.assertNotIn("unsafe-inline", headers.get("Content-Security-Policy").split("script-src", 1)[1].split(";", 1)[0])
        return json.loads(body)["token"]

    def test_session_bootstrap_and_same_origin_search(self):
        token = self.session()
        headers = {
            "Content-Type": "application/json",
            "X-FireLab-Session": token,
            "Origin": f"http://127.0.0.1:{self.port}",
            "Sec-Fetch-Site": "same-origin",
        }
        status, response_headers, body = self.request(
            "POST", "/api/papers/search", headers=headers,
            body=json.dumps({"query": "microgravity flame"}),
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["state"], "fresh")
        self.assertEqual(response_headers.get("Cache-Control"), "no-store")
        self.assertIsNone(response_headers.get("Access-Control-Allow-Origin"))

    def test_same_origin_assistant_ask_returns_server_answer(self):
        token = self.session()
        headers = {
            "Content-Type": "application/json",
            "X-FireLab-Session": token,
            "Origin": f"http://127.0.0.1:{self.port}",
            "Sec-Fetch-Site": "same-origin",
        }
        status, response_headers, body = self.request(
            "POST", "/api/assistant/ask", headers=headers,
            body=json.dumps({"question": "Summarize the FLEX dataset", "conversation_id": "chat-123"}),
        )
        self.assertEqual(status, 200)
        self.assertEqual(response_headers.get("Cache-Control"), "no-store")
        payload = json.loads(body)
        self.assertEqual(payload["title"], "Verified answer")
        self.assertEqual(payload["conversation_id"], "chat-123")

    def test_assistant_route_rejects_extra_or_invalid_fields(self):
        token = self.session()
        headers = {"Content-Type": "application/json", "X-FireLab-Session": token}
        invalid_bodies = [
            {"question": "summarize dataset", "conversation_id": "chat-1", "allow_metered": True},
            {"question": "summarize dataset", "conversation_id": "../secret"},
            {"question": "x", "conversation_id": "chat-1"},
        ]
        for payload in invalid_bodies:
            with self.subTest(payload=payload):
                status, _, body = self.request("POST", "/api/assistant/ask", headers=headers, body=json.dumps(payload))
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body)["error"], "invalid_request")

    def test_assistant_route_rejects_duplicate_json_keys(self):
        token = self.session()
        headers = {"Content-Type": "application/json", "X-FireLab-Session": token}
        status, _, body = self.request(
            "POST", "/api/assistant/ask", headers=headers,
            body='{"question":"summarize dataset","question":"other","conversation_id":"chat-1"}',
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_request")

    def test_assistant_is_unavailable_when_not_configured(self):
        self.server.assistant_service = None
        token = self.session()
        headers = {"Content-Type": "application/json", "X-FireLab-Session": token}
        status, _, body = self.request(
            "POST", "/api/assistant/ask", headers=headers,
            body=json.dumps({"question": "summarize dataset", "conversation_id": "chat-1"}),
        )
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "evidence_service_unavailable")

    def test_origin_must_match_the_actual_host(self):
        token = self.session()
        headers = {
            "Content-Type": "application/json",
            "X-FireLab-Session": token,
            "Origin": f"http://localhost:{self.port}",
            "Sec-Fetch-Site": "same-origin",
        }
        self.assertEqual(self.request("POST", "/api/papers/search", headers=headers,
                                      body=json.dumps({"query": "microgravity flame"}))[0], 403)

    def test_cross_site_fetch_metadata_rejected(self):
        token = self.session()
        headers = {
            "Content-Type": "application/json",
            "X-FireLab-Session": token,
            "Sec-Fetch-Site": "cross-site",
        }
        self.assertEqual(self.request("POST", "/api/papers/search", headers=headers,
                                      body=json.dumps({"query": "microgravity flame"}))[0], 403)

    def test_missing_token_and_bad_origin_rejected(self):
        token = self.session()
        base = {"Content-Type": "application/json"}
        body = json.dumps({"query": "microgravity flame"})
        self.assertEqual(self.request("POST", "/api/papers/search", headers=base, body=body)[0], 403)
        headers = base | {
            "X-FireLab-Session": token,
            "Origin": "http://attacker.example",
        }
        self.assertEqual(self.request("POST", "/api/papers/search", headers=headers, body=body)[0], 403)

    def test_host_allowlist_applies_to_static_and_bootstrap(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/session", headers={"Host": "attacker.example"})[0], 403)

    def test_body_schema_content_type_and_size(self):
        token = self.session()
        common = {"X-FireLab-Session": token}
        self.assertEqual(self.request("POST", "/api/papers/search", headers=common | {"Content-Type": "text/plain"}, body="x")[0], 415)
        self.assertEqual(self.request("POST", "/api/papers/search", headers=common | {"Content-Type": "application/json", "Content-Encoding": "gzip"}, body="{}")[0], 400)
        self.assertEqual(self.request("POST", "/api/papers/search", headers=common | {"Content-Type": "application/json"}, body=json.dumps({"query": "abc", "allow_metered": True}))[0], 400)
        large = b"{" + b" " * 2050 + b"}"
        self.assertEqual(self.request("POST", "/api/papers/search", headers=common | {"Content-Type": "application/json"}, body=large)[0], 413)

    def test_unknown_api_routes_require_session_before_404(self):
        token = self.session()
        self.assertEqual(self.request("GET", "/api/unknown")[0], 403)
        self.assertEqual(self.request("GET", "/api/unknown", headers={"X-FireLab-Session": token})[0], 404)
        self.assertEqual(self.request("HEAD", "/api/unknown")[0], 403)
        self.assertEqual(self.request("HEAD", "/api/unknown", headers={"X-FireLab-Session": token})[0], 404)

    def test_unknown_api_and_mutation_routes_rejected(self):
        token = self.session()
        self.assertEqual(self.request("PUT", "/api/papers/search")[0], 403)
        self.assertEqual(self.request("PUT", "/api/papers/search", headers={"X-FireLab-Session": token})[0], 405)

    def test_backup_directory_not_served(self):
        self.assertEqual(self.request("GET", "/data_backup_20261030_041648/records.json")[0], 404)

    def test_static_symlink_cannot_escape_site_root(self):
        outside = self.repo / "outside.json"
        outside.write_text("{\"secret\":true}")
        data_dir = self.repo / "firelab_site" / "data"
        data_dir.mkdir()
        (data_dir / "records.json").symlink_to(outside)
        self.assertEqual(self.request("GET", "/data/records.json")[0], 404)

    def test_expect_100_is_rejected_before_request_body(self):
        response = self.request(
            "POST", "/api/papers/search",
            headers={"Expect": "100-continue", "Content-Length": "20", "Content-Type": "application/json"},
            body='{"query":"microgravity"}',
        )
        self.assertEqual(response[0], 417)
        self.assertEqual(json.loads(response[2])["error"], "expectation_failed")

    def test_static_asset_served_with_security_headers(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"<html>test</html>")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")

    def test_disallowed_bind_host_rejected(self):
        with self.assertRaises(ValueError):
            create_server(self.repo, port=0, host="0.0.0.0", service=FakeService())


if __name__ == "__main__":
    unittest.main()
