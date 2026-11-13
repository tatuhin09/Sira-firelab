from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from firelab_service.http_app import create_server
from firelab_service.multi_investigation import MultiInvestigationEvidenceAssistant
from firelab_service.research_synthesis import FireLabResearchSynthesisService


ROOT = Path(__file__).resolve().parents[1]
RESPONSE_SCHEMA = "sira.firelab.research_synthesis_response.v1"


class FakeAssistant(MultiInvestigationEvidenceAssistant):
    def __init__(self):
        self.registry = FakeRegistry()
        self.calls = []
        self.answer = {
            "title": "Verified answer",
            "text": "Server-generated deterministic evidence answer.",
            "status": "completed",
            "investigationId": "psi69-flex-v5",
            "analysisId": "flex.dataset.snapshot",
            "dataScope": "all-records",
            "events": [{"type": "answer.completed", "summary": "Done"}],
        }

    def ask(self, question, *, conversation_id, investigation_id="psi69-flex-v5"):
        self.calls.append((question, conversation_id, investigation_id))
        answer = dict(self.answer)
        answer["investigationId"] = investigation_id
        answer["conversationId"] = conversation_id
        return answer


class FakeSynthesisService:
    def __init__(self):
        self.calls = []
        self.packet = {
            "schema": "sira.firelab.research_synthesis.v1",
            "status": "limited_no_literature",
            "dataset_context": {"operation_id": "flex.dataset.snapshot"},
            "literature": {"state": "cache_miss_offline", "source_count": 0, "sources": []},
        }
        self.raise_error = False

    def synthesize(self, *, literature_query, completed_answer):
        self.calls.append((literature_query, completed_answer))
        if self.raise_error:
            raise RuntimeError("private synthetic failure detail")
        return self.packet


class FakeRegistry:
    def get(self, investigation_id):
        raise AssertionError("registry lookup is not part of service construction")


class FakePaperSearchService:
    def search(self, query, *, refresh=False):
        return {"state": "cache_miss_offline", "query": query, "papers": [],
                "retrieved_at": None, "providers": [], "partial": False}


class Step6AResearchSynthesisHTTPTests(unittest.TestCase):
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
        self.server = create_server(
            self.repo, port=0, service=FakePaperSearchService(),
            assistant_service=FakeAssistant(),
            research_synthesis_service=FakeSynthesisService(),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def request(self, method, path, *, payload=None, headers=None):
        request_headers = dict(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload)
            request_headers.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        try:
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            content = response.read()
            return response.status, response.headers, content
        finally:
            conn.close()

    def session_headers(self):
        status, _, body = self.request("GET", "/api/session")
        self.assertEqual(status, 200)
        return {"X-FireLab-Session": json.loads(body)["token"]}

    @staticmethod
    def payload(**updates):
        result = {
            "question": "Summarize the FLEX dataset",
            "conversation_id": "step6a-chat-001",
            "investigation_id": "psi69-flex-v5",
            "literature_query": "microgravity flame combustion",
        }
        result.update(updates)
        return result

    def test_server_builds_synthesis_service_from_shared_registry_and_search_service(self):
        registry = FakeRegistry()
        assistant = MultiInvestigationEvidenceAssistant.__new__(MultiInvestigationEvidenceAssistant)
        assistant.registry = registry
        paper_service = FakePaperSearchService()
        server = create_server(
            self.repo, port=0, service=paper_service, assistant_service=assistant,
        )
        try:
            self.assertIsInstance(server.research_synthesis_service, FireLabResearchSynthesisService)
            self.assertIs(server.research_synthesis_service.registry, registry)
            self.assertIs(server.research_synthesis_service.research_adapter._paper_search_service, paper_service)
        finally:
            server.server_close()

    def test_synthesis_route_uses_server_generated_answer_and_packet(self):
        headers = self.session_headers()
        status, response_headers, body = self.request(
            "POST", "/api/research/synthesis", payload=self.payload(), headers=headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(response_headers.get("Cache-Control"), "no-store")
        result = json.loads(body)
        self.assertEqual(result["schema"], RESPONSE_SCHEMA)
        self.assertEqual(result["answer"]["analysisId"], "flex.dataset.snapshot")
        self.assertEqual(result["research_synthesis"]["status"], "limited_no_literature")
        self.assertEqual(len(self.server.assistant_service.calls), 1)
        self.assertEqual(len(self.server.research_synthesis_service.calls), 1)
        query, answer = self.server.research_synthesis_service.calls[0]
        self.assertEqual(query, "microgravity flame combustion")
        self.assertIsInstance(answer, dict)
        self.assertEqual(answer["conversationId"], "step6a-chat-001")

    def test_synthesis_route_passes_only_allowlisted_investigation(self):
        headers = self.session_headers()
        body = self.payload(investigation_id="psi25-bass-ii-v4")
        status, _, content = self.request("POST", "/api/research/synthesis", payload=body, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.server.assistant_service.calls[-1][2], "psi25-bass-ii-v4")

    def test_synthesis_route_rejects_auto_or_unknown_investigation(self):
        headers = self.session_headers()
        for investigation in ("auto", "private-sira-core", "../secret", None):
            with self.subTest(investigation=investigation):
                status, _, body = self.request(
                    "POST", "/api/research/synthesis",
                    payload=self.payload(investigation_id=investigation), headers=headers,
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body)["error"], "invalid_request")
        self.assertEqual(self.server.assistant_service.calls, [])

    def test_synthesis_route_rejects_missing_extra_and_invalid_fields(self):
        headers = self.session_headers()
        invalid = [
            {"question": "Summarize FLEX", "conversation_id": "chat-1", "investigation_id": "psi69-flex-v5"},
            self.payload(untrusted_answer={"status": "completed"}),
            self.payload(refresh=True),
            self.payload(question="x"),
            self.payload(conversation_id="../secret"),
            self.payload(literature_query="  "),
        ]
        for item in invalid:
            with self.subTest(item=item):
                status, _, body = self.request(
                    "POST", "/api/research/synthesis", payload=item, headers=headers
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body)["error"], "invalid_request")
        self.assertEqual(self.server.assistant_service.calls, [])
        self.assertEqual(self.server.research_synthesis_service.calls, [])

    def test_synthesis_route_requires_configured_services(self):
        headers = self.session_headers()
        self.server.research_synthesis_service = None
        status, _, body = self.request(
            "POST", "/api/research/synthesis", payload=self.payload(), headers=headers
        )
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "research_synthesis_unavailable")

    def test_synthesis_route_does_not_leak_internal_exception(self):
        headers = self.session_headers()
        self.server.research_synthesis_service.raise_error = True
        status, _, body = self.request(
            "POST", "/api/research/synthesis", payload=self.payload(), headers=headers
        )
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(body), {"error": "internal_error"})
        self.assertNotIn(b"private synthetic failure detail", body)

    def test_synthesis_route_obeys_session_protection(self):
        status, _, body = self.request(
            "POST", "/api/research/synthesis", payload=self.payload()
        )
        self.assertEqual(status, 403)

    def test_synthesis_route_obeys_same_origin_protection(self):
        headers = self.session_headers() | {"Origin": "http://attacker.example"}
        status, _, _ = self.request(
            "POST", "/api/research/synthesis", payload=self.payload(), headers=headers
        )
        self.assertEqual(status, 403)

    def test_existing_assistant_route_is_still_present(self):
        headers = self.session_headers()
        payload = {"question": "Summarize FLEX", "conversation_id": "legacy-chat"}
        status, _, body = self.request("POST", "/api/assistant/ask", payload=payload, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["title"], "Verified answer")

    def test_existing_paper_search_route_is_still_present(self):
        headers = self.session_headers()
        status, _, body = self.request(
            "POST", "/api/papers/search", payload={"query": "microgravity flame"}, headers=headers
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["state"], "cache_miss_offline")

    def test_unknown_get_route_remains_not_found(self):
        headers = self.session_headers()
        status, _, body = self.request("GET", "/api/research/synthesis", headers=headers)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
