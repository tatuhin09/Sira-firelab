"""Isolated subprocess entry point. This is the only FireLab module importing SIRA."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any, Callable


def _paper_record(paper: Any) -> dict[str, Any]:
    fields = (
        "paper_id", "title", "abstract", "authors", "year", "doi", "url",
        "open_access_pdf_url", "retrieved_at", "provider", "published_date", "providers",
    )
    if isinstance(paper, dict):
        source = paper
        getter = source.get
    else:
        getter = lambda key, default=None: getattr(paper, key, default)
    result: dict[str, Any] = {}
    for field in fields:
        value = getter(field)
        if field in {"authors", "providers"} and isinstance(value, tuple):
            value = list(value)
        result[field] = value
    return result


ALLOWED_PROVIDERS = frozenset({"crossref", "openalex", "semantic_scholar", "arxiv"})


def _bound_broker_decision(decision: Any, unavailable_status: str) -> dict[str, Any]:
    if not isinstance(decision, dict):
        return {
            "status": unavailable_status,
            "selected_provider_id": None,
            "fallback_provider_ids": [],
        }
    selected = decision.get("selected_provider_id")
    fallbacks = decision.get("fallback_provider_ids")
    if selected is not None and (not isinstance(selected, str) or not selected):
        fallbacks = None
    if (
        not isinstance(fallbacks, list)
        or any(not isinstance(item, str) or not item for item in fallbacks)
        or (selected is None and fallbacks)
    ):
        blocked = dict(decision)
        blocked["status"] = unavailable_status
        blocked["selected_provider_id"] = None
        blocked["fallback_provider_ids"] = []
        return blocked
    chain = ([selected] if isinstance(selected, str) and selected else []) + list(fallbacks)
    if len(chain) > len(ALLOWED_PROVIDERS) or len(set(chain)) != len(chain) or any(provider not in ALLOWED_PROVIDERS for provider in chain):
        blocked = dict(decision)
        blocked["status"] = unavailable_status
        blocked["selected_provider_id"] = None
        blocked["fallback_provider_ids"] = []
        return blocked
    return decision


def _guarded_broker(root: Path, capability: str, **kwargs: Any) -> dict[str, Any]:
    """Call the real Capability Broker, then fail closed before provider execution.

    This is a provider-consumer boundary, not an alternate routing policy. The
    Broker still makes the decision; an unexpected provider ID is blocked before
    the orchestrator can instantiate or call that provider.
    """
    from sira.capability_broker import STATUS_CAPABILITY_UNAVAILABLE, broker_decision

    decision = broker_decision(root, capability, **kwargs)
    return _bound_broker_decision(decision, STATUS_CAPABILITY_UNAVAILABLE)


def _worker_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("research result must be an object")
    records = result.get("records", [])
    if not isinstance(records, list) or len(records) > 3:
        raise ValueError("research records exceed the worker limit")
    attempts = result.get("attempts", [])
    if not isinstance(attempts, list) or any(not isinstance(item, dict) for item in attempts):
        raise ValueError("research attempts must be a list of objects")
    skipped = result.get("providers_skipped_cooldown", [])
    if not isinstance(skipped, list) or any(not isinstance(item, dict) for item in skipped):
        raise ValueError("skipped provider records are invalid")
    return {
        "schema": result.get("schema"),
        "status": result.get("status"),
        "records": [_paper_record(paper) for paper in records],
        "providers_attempted": result.get("providers_attempted", []),
        "provider_chain": result.get("provider_chain", []),
        "attempts": [
            {"provider_id": item.get("provider_id")}
            for item in attempts
        ],
        "providers_skipped_cooldown": [
            {"provider": item.get("provider")}
            for item in skipped
        ],
        "api_requests": result.get("api_requests", 0),
    }


def main(
    argv: list[str] | None = None,
    stdin=None,
    stdout=None,
    *,
    execute: Callable[..., Any] | None = None,
) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    sys.dont_write_bytecode = True
    try:
        os.umask(0o077)
        if len(argv) != 2:
            raise ValueError("worker arguments are invalid")
        source_root = Path(argv[0]).resolve()
        sira_root = Path(argv[1]).resolve()
        if not source_root.is_dir() or not sira_root.is_dir():
            raise ValueError("worker roots are unavailable")
        raw = stdin.read(4097)
        if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > 4096:
            raise ValueError("worker input is too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"protocol", "query"} or payload.get("protocol") != 1:
            raise ValueError("worker protocol is invalid")
        query = payload.get("query")
        if not isinstance(query, str) or not 3 <= len(query) <= 200:
            raise ValueError("worker query is invalid")

        # -I excludes the repository root and user site. Insert only the SIRA
        # src package path, ahead of any ambient path, after validating argv.
        sys.path.insert(0, str(source_root))
        if execute is None:
            import resource
            from sira.research_contracts import ResearchRequest
            from sira.research_orchestrator import execute_research
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
                resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
                resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            except (OSError, ValueError):
                raise RuntimeError("worker resource limits could not be applied") from None
            request = ResearchRequest(
                query=query,
                capability="paper_search",
                max_results=3,
                allow_metered=False,
                use_cache=False,
                metadata={},
            )
            result = execute_research(sira_root, request, broker=_guarded_broker)
        else:
            # Dependency injection is available only for unit tests. The
            # production entry point never supplies this argument.
            result = execute(sira_root, query)
        envelope = _worker_result(result)
    except Exception as exc:
        # Do not disclose exception messages or query text across the process boundary.
        envelope = {"worker_error": type(exc).__name__}
        stdout.write(json.dumps(envelope, separators=(",", ":")))
        stdout.flush()
        return 2

    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 512 * 1024:
        stdout.write('{"worker_error":"OutputTooLarge"}')
        stdout.flush()
        return 2
    stdout.write(encoded)
    stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
