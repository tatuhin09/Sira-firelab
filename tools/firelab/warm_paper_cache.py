#!/usr/bin/env python3
"""Warm only the three fixed SIRA FireLab offline-demo paper queries."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from firelab_service.paper_search.paths import FireLabPaths
from firelab_service.paper_search.runner import SiraResearchRunner
from firelab_service.paper_search.service import PaperSearchService
from firelab_service.paper_search.store import PaperCacheStore

DEMO_QUERIES = (
    "microgravity flame extinguishment oxygen concentration",
    "spacecraft fire safety low gravity combustion",
    "flame spread microgravity solid fuel",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Warm the three fixed SIRA FireLab offline-demo paper queries."
    )
    parser.parse_args(argv)

    os.umask(0o077)
    paths = FireLabPaths(ROOT)
    paths.prepare()
    store = PaperCacheStore(paths.runtime_dir)
    service = PaperSearchService(store, SiraResearchRunner(paths).run, offline=False, max_workers=1)
    failures = 0
    for query in DEMO_QUERIES:
        result = service.search(query, refresh=True)
        papers = result.get("papers", [])
        if result.get("state") == "fresh" and papers:
            providers = ", ".join(result.get("providers", [])) or "not reported"
            print(f"SUCCESS | {query} | papers={len(papers)} | retrieved={result.get('retrieved_at')} | providers={providers}")
        else:
            failures += 1
            print(f"FAILED  | {query} | state={result.get('state')} | papers={len(papers)}")
    print(f"Warm-up complete: {len(DEMO_QUERIES) - failures}/{len(DEMO_QUERIES)} queries stored.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
