"""Loopback-only FireLab HTTP application (static assets, paper search and evidence answers)."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import stat
from typing import Any
from urllib.parse import unquote, urlsplit

from .assistant import FireLabEvidenceAssistant, normalize_conversation_id, normalize_question
from .engine import load_bundle
from .paper_search.paths import FireLabPaths
from .paper_search.query import normalize_query
from .paper_search.runner import SiraResearchRunner
from .paper_search.service import PaperSearchService
from .paper_search.store import PaperCacheStore
from .evidence_registry import load_evidence_registry
from .multi_investigation import MultiInvestigationEvidenceAssistant
from .research_adapter import FireLabResearchAdapter
from .research_synthesis import FireLabResearchSynthesisService

MAX_REQUEST_BYTES = 2048
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'; object-src 'none"
)
STATIC_FILES = frozenset({
    "index.html", "styles.css", "app.js", "condition-analysis.js",
    "source-label.js", "papers.js", "psi25.js", "data/manifest.json",
    "data/records.json", "data/quality.json",
    "data/derived/psi25_bass_ii_v4/canonical_records.json",
    "data/derived/psi25_bass_ii_v4/quality_report.json",
    "data/derived/psi25_bass_ii_v4/canonical_manifest.json",
    "data/derived/psi25_bass_ii_v4/paired_analysis_v1/paired_measurement_analysis.json",
    "data/derived/psi25_bass_ii_v4/paired_analysis_v1/analysis_manifest.json",
    "data/derived/psi25_bass_ii_v4/findings_ranking_v1/findings_ranking.json",
    "data/derived/psi25_bass_ii_v4/findings_ranking_v1/findings_manifest.json",
    "data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/evidence_synthesis.json",
    "data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/synthesis_manifest.json",
})


class _DuplicateKey(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("duplicate key")
        result[key] = value
    return result


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class FireLabM2HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, site_root: Path, service: PaperSearchService,
                 assistant_service: FireLabEvidenceAssistant | MultiInvestigationEvidenceAssistant | None,
                 research_synthesis_service: Any = None, offline: bool):
        candidate_site = Path(site_root)
        if candidate_site.is_symlink():
            raise RuntimeError("FireLab static site directory may not be a symlink")
        self.site_root = candidate_site.resolve(strict=True)
        if not self.site_root.is_dir():
            raise RuntimeError("FireLab static site root is not a directory")
        self.service = service
        self.assistant_service = assistant_service
        self.research_synthesis_service = research_synthesis_service
        self.offline = bool(offline)
        self.session_token = secrets.token_urlsafe(32)
        super().__init__(address, handler)


class FireLabM2Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: FireLabM2HTTPServer

    def log_message(self, format: str, *args: object) -> None:
        # Request bodies are never logged; suppress default access logging entirely.
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # BaseHTTPRequestHandler errors (including malformed request lines)
        # must carry the same security headers and must not echo attacker text.
        self.close_connection = True
        status = code if 400 <= code <= 599 else 400
        body = json.dumps({"error": "bad_request"}, separators=(",", ":")).encode("utf-8")
        self._send(status, body)

    def handle_expect_100(self) -> bool:
        # Do not send an interim 100 response before validating the custom
        # session/Origin policy and the bounded Content-Length. Browser fetch
        # does not need this mechanism; clients using it receive a safe 417.
        self.close_connection = True
        self._json(417, {"error": "expectation_failed"})
        return False

    def _headers(self, *, no_store: bool = True) -> None:
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store" if no_store else "no-cache")

    def _send(self, status: int, body: bytes = b"", content_type: str = "application/json; charset=utf-8", *, head: bool = False) -> None:
        self.send_response(status)
        self._headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head and body:
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any], *, head: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(status, body, head=head)

    def _host_ok(self) -> bool:
        port = int(self.server.server_address[1])
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        values = self.headers.get_all("Host", [])
        host = values[0] if len(values) == 1 else ""
        if host not in allowed:
            self.close_connection = True
            self._json(403, {"error": "forbidden"})
            return False
        return True

    def _fetch_site_ok(self) -> bool:
        values = self.headers.get_all("Sec-Fetch-Site", [])
        if len(values) > 1 or (values and values[0].casefold() not in {"same-origin", "none"}):
            self.close_connection = True
            self._json(403, {"error": "forbidden"})
            return False
        return True

    def _origin_ok(self) -> bool:
        values = self.headers.get_all("Origin", [])
        if not values:
            return True
        if len(values) != 1:
            self.close_connection = True
            self._json(403, {"error": "forbidden"})
            return False
        port = int(self.server.server_address[1])
        host_values = self.headers.get_all("Host", [])
        host = host_values[0] if len(host_values) == 1 else ""
        allowed = {f"http://{host}"} if host in {f"127.0.0.1:{port}", f"localhost:{port}"} else set()
        if values[0] not in allowed:
            self.close_connection = True
            self._json(403, {"error": "forbidden"})
            return False
        return True

    def _session_ok(self) -> bool:
        values = self.headers.get_all("X-FireLab-Session", [])
        supplied = values[0] if len(values) == 1 else ""
        if not supplied or not secrets.compare_digest(supplied, self.server.session_token):
            self.close_connection = True
            self._json(403, {"error": "forbidden"})
            return False
        return True

    def _path(self) -> str | None:
        try:
            parts = urlsplit(self.path)
            if parts.query or parts.fragment:
                return None
            decoded = unquote(parts.path, errors="strict")
            if "\\" in decoded or "\x00" in decoded:
                return None
            return decoded.lstrip("/") or "index.html"
        except (UnicodeError, ValueError):
            return None

    def _static(self, *, head: bool = False) -> None:
        relative = self._path()
        if relative is None:
            self._json(404, {"error": "not_found"}, head=head)
            return
        pure = Path(relative)
        if pure.is_absolute() or any(part in {".", ".."} or part.startswith(".") for part in pure.parts):
            self._json(404, {"error": "not_found"}, head=head)
            return
        if any(part.startswith("data_backup_") for part in pure.parts) or relative not in STATIC_FILES:
            self._json(404, {"error": "not_found"}, head=head)
            return
        candidate = self.server.site_root / relative
        try:
            resolved = candidate.resolve(strict=True)
            if not _inside(self.server.site_root, resolved):
                raise ValueError("outside site root")
            info = os.stat(resolved, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or resolved.is_symlink():
                raise ValueError("not a regular file")
            data = resolved.read_bytes()
        except (OSError, ValueError):
            self._json(404, {"error": "not_found"}, head=head)
            return
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._send(200, data, content_type, head=head)

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        if not self._fetch_site_ok():
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/api/session" and not parsed.query and not parsed.fragment:
            self._json(200, {"token": self.server.session_token, "offline": self.server.offline})
            return
        if parsed.path == "/api" or parsed.path.startswith("/api/"):
            if not self._session_ok():
                return
            self._json(404, {"error": "not_found"})
            return
        self._static()

    def do_HEAD(self) -> None:
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if path == "/api" or path.startswith("/api/"):
            if not self._session_ok():
                return
            self._json(404, {"error": "not_found"}, head=True)
            return
        self._static(head=True)

    def do_POST(self) -> None:
        if not self._host_ok() or not self._fetch_site_ok() or not self._origin_ok() or not self._session_ok():
            return
        parsed_path = urlsplit(self.path)
        route = parsed_path.path
        if route not in {"/api/papers/search", "/api/assistant/ask", "/api/research/synthesis"} or parsed_path.query or parsed_path.fragment:
            self.close_connection = True
            self._json(404, {"error": "not_found"})
            return
        content_types = self.headers.get_all("Content-Type", [])
        content_type = content_types[0].split(";", 1)[0].strip().casefold() if len(content_types) == 1 else ""
        content_lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get_all("Transfer-Encoding", []) or self.headers.get_all("Content-Encoding", []):
            self.close_connection = True
            self._json(400, {"error": "invalid_request"})
            return
        if content_type != "application/json":
            self.close_connection = True
            self._json(415, {"error": "unsupported_media_type"})
            return
        raw_length = content_lengths[0] if len(content_lengths) == 1 else ""
        try:
            if not raw_length.isascii() or not raw_length.isdecimal():
                raise ValueError("invalid content length")
            length = int(raw_length)
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self._json(400, {"error": "invalid_request"})
            return
        if length > MAX_REQUEST_BYTES:
            self.close_connection = True
            self._json(413, {"error": "request_too_large"})
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete request")
            self.close_connection = True
            payload = json.loads(body.decode("utf-8"), object_pairs_hook=_strict_object)
            if not isinstance(payload, dict):
                raise ValueError("request must be an object")
            if route == "/api/papers/search":
                if set(payload) - {"query", "refresh"} or "query" not in payload:
                    raise ValueError("paper request schema is invalid")
                normalized = normalize_query(payload["query"])
                refresh = payload.get("refresh", False)
                if type(refresh) is not bool:
                    raise ValueError("refresh must be boolean")
            elif route == "/api/assistant/ask":
                required = {"question", "conversation_id"}
                allowed = required | {"investigation_id"}
                if not required.issubset(payload) or set(payload) - allowed:
                    raise ValueError("assistant request schema is invalid")
                question = normalize_question(payload["question"])
                conversation_id = normalize_conversation_id(payload["conversation_id"])
                investigation_id = payload.get("investigation_id")
                if investigation_id is not None and (
                    not isinstance(investigation_id, str)
                    or investigation_id not in {"auto", "psi69-flex-v5", "psi25-bass-ii-v4"}
                ):
                    raise ValueError("assistant investigation is not approved")
            else:
                required = {"question", "conversation_id", "investigation_id", "literature_query"}
                if set(payload) != required:
                    raise ValueError("research synthesis request schema is invalid")
                question = normalize_question(payload["question"])
                conversation_id = normalize_conversation_id(payload["conversation_id"])
                investigation_id = payload["investigation_id"]
                if investigation_id not in {"psi69-flex-v5", "psi25-bass-ii-v4"}:
                    raise ValueError("research synthesis requires one explicit registered investigation")
                literature_query = normalize_query(payload["literature_query"])
        except (UnicodeError, json.JSONDecodeError, _DuplicateKey, ValueError):
            self.close_connection = True
            self._json(400, {"error": "invalid_request"})
            return

        try:
            if route == "/api/papers/search":
                response = self.server.service.search(normalized, refresh=refresh)
                status = 429 if response.get("state") == "busy" else 200
            elif route == "/api/assistant/ask":
                assistant = self.server.assistant_service
                if assistant is None:
                    self._json(503, {"error": "evidence_service_unavailable"})
                    return
                if investigation_id is None:
                    # Existing clients remain PSI-69 by default.
                    response = assistant.ask(question, conversation_id=conversation_id)
                else:
                    response = assistant.ask(question, conversation_id=conversation_id, investigation_id=investigation_id)
                status = 200
            else:
                assistant = self.server.assistant_service
                synthesis_service = self.server.research_synthesis_service
                if not isinstance(assistant, MultiInvestigationEvidenceAssistant) or synthesis_service is None:
                    self._json(503, {"error": "research_synthesis_unavailable"})
                    return
                # Never accept a browser-supplied answer or Claim Ledger.
                # Re-run the registered deterministic analysis on the server.
                completed_answer = assistant.ask(
                    question, conversation_id=conversation_id,
                    investigation_id=investigation_id,
                )
                packet = synthesis_service.synthesize(
                    literature_query=literature_query,
                    completed_answer=completed_answer,
                )
                response = {
                    "schema": "sira.firelab.research_synthesis_response.v1",
                    "answer": completed_answer,
                    "research_synthesis": packet,
                }
                status = 200
        except Exception as exc:
            # Never log input values, prompts, evidence payloads or exception messages.
            import logging
            logging.getLogger(__name__).warning("FireLab API failure (%s)", type(exc).__name__)
            self._json(500, {"error": "internal_error"})
            return
        self._json(status, response)

    def _method_not_allowed(self) -> None:
        if not self._host_ok():
            return
        api_path = urlsplit(self.path).path
        if api_path == "/api" or api_path.startswith("/api/"):
            if not self._fetch_site_ok() or not self._origin_ok() or not self._session_ok():
                return
        self._json(405, {"error": "method_not_allowed"})

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed
    do_CONNECT = _method_not_allowed


def create_server(
    repo_root: Path,
    *,
    port: int = 8765,
    offline: bool = False,
    host: str = "127.0.0.1",
    service: PaperSearchService | None = None,
    runner=None,
    assistant_service: FireLabEvidenceAssistant | MultiInvestigationEvidenceAssistant | None = None,
    research_synthesis_service: Any = None,
) -> FireLabM2HTTPServer:
    if host != "127.0.0.1":
        raise ValueError("FireLab M2 must bind to 127.0.0.1")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be 0..65535")
    root = Path(repo_root).resolve()
    paths = FireLabPaths(root)
    paths.prepare()
    if service is None:
        store = PaperCacheStore(paths.runtime_dir)
        worker = runner or SiraResearchRunner(paths)
        service = PaperSearchService(store, worker.run, offline=offline, max_workers=2)
    registry = None
    if assistant_service is None:
        # Missing-data test fixtures stay usable; a present release must pass the full registry.
        if (paths.site_root / "data" / "manifest.json").is_file():
            registry = load_evidence_registry(root)
            assistant_service = MultiInvestigationEvidenceAssistant(registry)
        else:
            assistant_service = None
    elif isinstance(assistant_service, MultiInvestigationEvidenceAssistant):
        registry = assistant_service.registry

    if research_synthesis_service is None and registry is not None:
        if callable(getattr(service, "search", None)):
            research_adapter = FireLabResearchAdapter(service)
            research_synthesis_service = FireLabResearchSynthesisService(
                registry, research_adapter
            )

    handler = FireLabM2Handler
    return FireLabM2HTTPServer(
        (host, port), handler, site_root=paths.site_root,
        service=service, assistant_service=assistant_service,
        research_synthesis_service=research_synthesis_service, offline=offline,
    )
