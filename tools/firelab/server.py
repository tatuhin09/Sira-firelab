"""Local static preview server; there are no write or runtime-control routes."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


class ReadOnlyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self._site_root = Path(directory or Path.cwd()).resolve()
        self._safe_path_override = None
        super().__init__(*args, directory=str(self._site_root), **kwargs)

    def _safe_translation(self, path):
        try:
            parsed = urlsplit(path)
            decoded = unquote(parsed.path, errors="strict")
            if "\\" in decoded or "\x00" in decoded:
                return None
            parts = PurePosixPath(decoded).parts
            if any(part in {".", ".."} or part.startswith(".") or part.startswith("data_backup_") for part in parts):
                return None
            candidate = Path(super().translate_path(parsed.path))
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self._site_root)
            return resolved
        except (OSError, RuntimeError, UnicodeError, ValueError):
            return None

    def translate_path(self, path):
        if self._safe_path_override is not None and path == self.path:
            return str(self._safe_path_override)
        resolved = self._safe_translation(path)
        if resolved is not None:
            return str(resolved)
        # A stable, deliberately non-existent path keeps the parent handler
        # from opening a denied backup/traversal/symlink target. send_head()
        # intercepts normal requests first and returns 404 directly.
        return str(self._site_root / "__firelab_denied_404__" / "missing")

    def send_head(self):
        resolved = self._safe_translation(self.path)
        if resolved is None:
            self.send_error(404, "File not found")
            return None
        self._safe_path_override = resolved
        try:
            return super().send_head()
        finally:
            self._safe_path_override = None

    def _reject_mutation(self):
        self.send_error(405, "Read-only preview server")

    do_POST = _reject_mutation
    do_PUT = _reject_mutation
    do_PATCH = _reject_mutation
    do_DELETE = _reject_mutation


def serve(site, host="127.0.0.1", port=8765):
    root = Path(site).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Site directory not found: {root}")
    handler = lambda *args, **kwargs: ReadOnlyHandler(*args, directory=root, **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        print(f"FireLab preview: http://{host}:{port}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
