#!/usr/bin/env python3
"""Start the loopback-only FireLab M2 research-reference workspace."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from firelab_service.http_app import create_server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--offline", action="store_true", help="Disable live workers; serve only cached paper results")
    args = parser.parse_args()
    os.umask(0o077)
    server = create_server(ROOT, port=args.port, offline=args.offline)
    mode = "OFFLINE CACHE ONLY" if args.offline else "CACHE FIRST · LIVE FREE PROVIDERS"
    print(f"FireLab M2: http://127.0.0.1:{server.server_address[1]} ({mode})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
