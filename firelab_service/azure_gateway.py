"""Public HTTPS gateway for the Azure demo deployment.

The trusted FireLab application server remains loopback-only. This gateway is
its only externally exposed listener. Azure Container Apps ingress terminates
TLS and overwrites X-Forwarded-Proto; this module accepts only HTTPS-originated
requests for one exact, configured public hostname and proxies a narrow route
allowlist to 127.0.0.1.
"""
from __future__ import annotations

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import re
import threading
import time
from urllib.parse import urlsplit

MAX_REQUEST_BYTES = 2048
MAX_CONCURRENT_REQUESTS = 8
MAX_POSTS_PER_WINDOW = 90
RATE_WINDOW_SECONDS = 60.0
IDLE_SOCKET_TIMEOUT_SECONDS = 30.0
BACKEND_TIMEOUT_SECONDS = 35.0

API_POST_PATHS = frozenset({
    "/api/papers/search",
    "/api/assistant/ask",
    "/api/research/synthesis",
})
STATIC_PATHS = frozenset({
    "/",
    "/index.html",
    "/styles.css",
    "/app.js",
    "/condition-analysis.js",
    "/source-label.js",
    "/papers.js",
    "/psi25.js",
    "/data/manifest.json",
    "/data/records.json",
    "/data/quality.json",
    "/data/derived/psi25_bass_ii_v4/canonical_records.json",
    "/data/derived/psi25_bass_ii_v4/quality_report.json",
    "/data/derived/psi25_bass_ii_v4/canonical_manifest.json",
    "/data/derived/psi25_bass_ii_v4/paired_analysis_v1/paired_measurement_analysis.json",
    "/data/derived/psi25_bass_ii_v4/paired_analysis_v1/analysis_manifest.json",
    "/data/derived/psi25_bass_ii_v4/findings_ranking_v1/findings_ranking.json",
    "/data/derived/psi25_bass_ii_v4/findings_ranking_v1/findings_manifest.json",
    "/data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/evidence_synthesis.json",
    "/data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/synthesis_manifest.json",
})
HOP_BY_HOP_RESPONSE_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "server", "date", "cache-control", "x-content-type-options",
    "referrer-policy", "x-frame-options", "cross-origin-resource-policy",
    "strict-transport-security",
})
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def validate_public_hostname(value: str | None) -> str | None:
    """Accept one DNS hostname only; reject schemes, ports, paths and wildcards."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 253:
        raise ValueError("FIRELAB_PUBLIC_HOSTNAME must be a DNS hostname")
    candidate = value.strip().lower()
    if candidate != value or candidate.endswith("."):
        raise ValueError("FIRELAB_PUBLIC_HOSTNAME must be canonical lowercase DNS")
    if any(ch in candidate for ch in "/:@*?#[] \\,,"):
        raise ValueError("FIRELAB_PUBLIC_HOSTNAME must not include scheme, port, path or wildcard")
    labels = candidate.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("FIRELAB_PUBLIC_HOSTNAME is not a valid fully-qualified DNS hostname")
    return candidate


class _RollingRateLimiter:
    def __init__(self, limit: int = MAX_POSTS_PER_WINDOW, window: float = RATE_WINDOW_SECONDS):
        if limit < 1 or window <= 0:
            raise ValueError("rate limit configuration is invalid")
        self.limit = limit
        self.window = window
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self, now: float | None = None) -> tuple[bool, int]:
        moment = time.monotonic() if now is None else now
        with self._lock:
            cutoff = moment - self.window
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self.limit:
                retry = max(1, int(self.window - (moment - self._events[0]) + 0.999))
                return False, retry
            self._events.append(moment)
            return True, 0


class AzurePublicGateway(ThreadingHTTPServer):
    """Bounded public ingress proxy; FireLab backend is loopback-only."""
    daemon_threads = True
    block_on_close = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(
        self,
        address: tuple[str, int],
        *,
        public_hostname: str | None,
        backend_host: str = "127.0.0.1",
        backend_port: int = 8765,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
        post_limit: int = MAX_POSTS_PER_WINDOW,
        rate_window: float = RATE_WINDOW_SECONDS,
    ):
        if backend_host != "127.0.0.1":
            raise ValueError("Azure gateway backend must remain on loopback")
        if type(backend_port) is not int or not 1 <= backend_port <= 65535:
            raise ValueError("backend port must be 1..65535")
        if type(max_concurrent) is not int or not 1 <= max_concurrent <= 32:
            raise ValueError("max_concurrent must be 1..32")
        self.public_hostname = validate_public_hostname(public_hostname)
        self.backend_host = backend_host
        self.backend_port = backend_port
        self._request_slots = threading.BoundedSemaphore(max_concurrent)
        self._rate_limiter = _RollingRateLimiter(post_limit, rate_window)
        super().__init__(address, AzureGatewayHandler)

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            try:
                request.settimeout(2.0)
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Connection: close\r\n"
                    b"Retry-After: 10\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class AzureGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: AzurePublicGateway

    def setup(self):
        super().setup()
        self.connection.settimeout(IDLE_SOCKET_TIMEOUT_SECONDS)
        self.close_connection = True

    def version_string(self):
        return "SIRA-FireLab-Gateway"

    def log_message(self, fmt: str, *args: object) -> None:
        # Deliberately suppress URLs, request bodies, prompts, tokens and IPs.
        return

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        safe_status = code if isinstance(code, int) and 400 <= code <= 599 else 400
        self._json(safe_status, {"error": "bad_request"}, secure=False)

    def handle_expect_100(self) -> bool:
        self.close_connection = True
        self._json(417, {"error": "expectation_failed"}, secure=False)
        return False

    def _headers(self, *, secure: bool) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if secure:
            self.send_header("Strict-Transport-Security", "max-age=31536000")

    def _json(self, status: int, payload: dict, *, secure: bool = True, retry_after: int | None = None):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._headers(secure=secure)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(body)

    def _external_request_ok(self) -> bool:
        # No traffic is accepted until the ACA-assigned FQDN is configured.
        if self.server.public_hostname is None:
            self._json(503, {"error": "hostname_not_configured"}, secure=False)
            return False
        host_values = self.headers.get_all("Host", [])
        if len(host_values) != 1 or host_values[0].casefold() != self.server.public_hostname:
            self._json(403, {"error": "forbidden"}, secure=False)
            return False
        proto_values = self.headers.get_all("X-Forwarded-Proto", [])
        if len(proto_values) != 1 or proto_values[0].casefold() != "https":
            self._json(403, {"error": "https_required"}, secure=False)
            return False
        return True

    def _path(self) -> str | None:
        try:
            parts = urlsplit(self.path)
            if parts.query or parts.fragment or parts.scheme or parts.netloc:
                return None
            path = parts.path
            if not path.startswith("/") or "\\" in path or "\x00" in path:
                return None
            if "%" in path:
                # The backend also has a strict static allowlist; disallow encoded aliases here.
                return None
            return path
        except (UnicodeError, ValueError):
            return None

    def _fetch_site_ok(self) -> bool:
        values = self.headers.get_all("Sec-Fetch-Site", [])
        if len(values) > 1:
            return False
        return not values or values[0].casefold() in {"same-origin", "none"}

    def _origin_ok(self) -> bool:
        values = self.headers.get_all("Origin", [])
        expected = f"https://{self.server.public_hostname}"
        if len(values) != 1:
            return False
        try:
            origin = urlsplit(values[0])
        except ValueError:
            return False
        return (
            origin.scheme == "https"
            and origin.netloc.casefold() == self.server.public_hostname
            and origin.path == ""
            and origin.query == ""
            and origin.fragment == ""
            and values[0] == expected
        )

    def _session_token(self) -> str | None:
        values = self.headers.get_all("X-FireLab-Session", [])
        if len(values) != 1:
            return None
        value = values[0]
        if not value or len(value) > 128 or not value.isascii():
            return None
        return value

    def _proxy(self, method: str, path: str, body: bytes = b"", *, session_token: str | None = None):
        headers = {
            "Host": f"127.0.0.1:{self.server.backend_port}",
            "Connection": "close",
            "Accept-Encoding": "identity",
            "Sec-Fetch-Site": "same-origin",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
            headers["Origin"] = f"http://127.0.0.1:{self.server.backend_port}"
            headers["X-FireLab-Session"] = session_token or ""
        connection = http.client.HTTPConnection(
            self.server.backend_host,
            self.server.backend_port,
            timeout=BACKEND_TIMEOUT_SECONDS,
        )
        try:
            connection.request(method, path, body=body if method == "POST" else None, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.casefold() in HOP_BY_HOP_RESPONSE_HEADERS:
                    continue
                self.send_header(key, value)
            self._headers(secure=True)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if method != "HEAD" and response_body:
                self.wfile.write(response_body)
        except (OSError, http.client.HTTPException, TimeoutError):
            self._json(502, {"error": "upstream_unavailable"})
        finally:
            connection.close()

    def do_GET(self):
        path = self._path()
        if path == "/healthz":
            self._json(200, {"status": "ok"}, secure=False)
            return
        if not self._external_request_ok():
            return
        if path == "/api/session":
            if not self._fetch_site_ok():
                self._json(403, {"error": "forbidden"})
                return
            self._proxy("GET", path)
            return
        if path in STATIC_PATHS:
            # Public document navigation is a safe GET. Backend fetch metadata is rewritten
            # to same-origin because the public gateway has already enforced Host + HTTPS.
            self._proxy("GET", path)
            return
        self._json(404, {"error": "not_found"})

    def do_HEAD(self):
        path = self._path()
        if not self._external_request_ok():
            return
        if path in STATIC_PATHS:
            self._proxy("HEAD", path)
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self):
        path = self._path()
        if not self._external_request_ok():
            return
        if path not in API_POST_PATHS:
            self._json(404, {"error": "not_found"})
            return
        if not self._fetch_site_ok() or not self._origin_ok():
            self._json(403, {"error": "forbidden"})
            return
        token = self._session_token()
        if token is None:
            self._json(403, {"error": "forbidden"})
            return
        allowed, retry_after = self.server._rate_limiter.take()
        if not allowed:
            self._json(429, {"error": "rate_limited"}, retry_after=retry_after)
            return
        types = self.headers.get_all("Content-Type", [])
        if len(types) != 1 or types[0].split(";", 1)[0].strip().casefold() != "application/json":
            self._json(415, {"error": "unsupported_media_type"})
            return
        if self.headers.get_all("Transfer-Encoding", []) or self.headers.get_all("Content-Encoding", []):
            self._json(400, {"error": "invalid_request"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            self._json(400, {"error": "invalid_request"})
            return
        length = int(lengths[0])
        if length > MAX_REQUEST_BYTES:
            self._json(413, {"error": "request_too_large"})
            return
        try:
            body = self.rfile.read(length)
        except (OSError, TimeoutError):
            self._json(400, {"error": "invalid_request"})
            return
        if len(body) != length:
            self._json(400, {"error": "invalid_request"})
            return
        self._proxy("POST", path, body, session_token=token)

    def _method_not_allowed(self):
        self._json(405, {"error": "method_not_allowed"}, secure=False)

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed
    do_CONNECT = _method_not_allowed
