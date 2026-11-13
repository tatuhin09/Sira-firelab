#!/usr/bin/env python3
"""Run the public Azure gateway in front of the unchanged loopback FireLab server."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from firelab_service.http_app import create_server
from firelab_service.azure_gateway import AzurePublicGateway


def _port(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{name} must be an integer port") from exc
    if not 1 <= value <= 65535:
        raise SystemExit(f"{name} must be 1..65535")
    return value


def main() -> int:
    os.umask(0o077)
    external_port = _port("PORT", 8080)
    internal_port = _port("FIRELAB_INTERNAL_PORT", 8765)
    hostname = os.environ.get("FIRELAB_PUBLIC_HOSTNAME", "")
    if hostname and hostname != hostname.strip():
        raise SystemExit("FIRELAB_PUBLIC_HOSTNAME must not contain surrounding whitespace")

    # Crucial invariant: the original FireLab service is still loopback-only and offline.
    backend = create_server(ROOT, port=internal_port, offline=True, host="127.0.0.1")
    backend_thread = threading.Thread(
        target=backend.serve_forever,
        name="firelab-loopback-backend",
        daemon=True,
    )
    backend_thread.start()
    time.sleep(0.05)

    gateway = AzurePublicGateway(
        ("0.0.0.0", external_port),
        public_hostname=hostname or None,
        backend_host="127.0.0.1",
        backend_port=internal_port,
    )
    configured = hostname if hostname else "NOT_CONFIGURED (all non-health routes fail closed)"
    print(
        f"SIRA FireLab Azure gateway listening on 0.0.0.0:{external_port}; "
        f"hostname={configured}; backend=127.0.0.1:{internal_port}; mode=OFFLINE",
        flush=True,
    )
    try:
        gateway.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        gateway.shutdown()
        gateway.server_close()
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
