"""Cache-first paper-search service with bounded worker concurrency."""
from __future__ import annotations

from datetime import datetime
import threading
from typing import Any, Callable

from .query import cache_key, normalize_query
from .records import ALLOWED_PROVIDERS, dedupe_key, validate_execution_result, validate_papers, with_relevance
from .store import PaperCacheStore
from .runner import WorkerTimeout


class _Flight:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.references = 0
        self.result: dict[str, Any] | None = None
        self.completed_at: float | None = None


class PaperSearchService:
    def __init__(
        self,
        store: PaperCacheStore,
        runner: Callable[[str], dict[str, Any]],
        *,
        offline: bool = False,
        max_workers: int = 2,
        singleflight_wait_seconds: float = 30.0,
    ):
        if type(max_workers) is not int or not 1 <= max_workers <= 2:
            raise ValueError("paper search workers must be 1..2")
        self.store = store
        self.runner = runner
        self.offline = bool(offline)
        self._worker_slots = threading.BoundedSemaphore(max_workers)
        self._flights: dict[str, _Flight] = {}
        self._flight_lock = threading.Lock()
        self.singleflight_wait_seconds = singleflight_wait_seconds

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        entry = self.store.get(key)
        if entry is None:
            return None
        try:
            validated = validate_papers(entry["papers"])
            if len(validated) != len(entry["papers"]):
                raise ValueError("cached paper set changed during validation")
            providers = entry.get("providers")
            if not isinstance(providers, list) or any(
                not isinstance(provider, str) or provider not in ALLOWED_PROVIDERS
                for provider in providers
            ):
                raise ValueError("cached provider attribution is invalid")
            paper_providers = list(dict.fromkeys(
                provider for paper in validated for provider in paper["providers"]
            ))
            if set(providers) != set(paper_providers):
                raise ValueError("cached provider attribution does not match papers")
            entry["providers"] = paper_providers
            entry["papers"] = validated
        except (TypeError, ValueError):
            self.store.delete(key)
            return None
        return entry

    @staticmethod
    def _response(
        state: str,
        query: str,
        *,
        papers: list[dict[str, Any]] | None = None,
        retrieved_at: str | None = None,
        providers: list[str] | None = None,
        partial: bool = False,
        message: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": state,
            "query": query,
            "papers": papers or [],
            "retrieved_at": retrieved_at,
            "providers": providers or [],
            "partial": bool(partial),
        }
        if message:
            result["message"] = message
        return result

    def _cached_response(self, query: str, entry: dict[str, Any], *, state: str) -> dict[str, Any]:
        papers = with_relevance(query, entry["papers"])
        message = "Cached result is older than 30 days." if state == "cache_stale" else None
        partial = bool(entry.get("partial", False))
        if partial:
            message = "The cached retrieved set may be incomplete."
        return self._response(
            state, query, papers=papers, retrieved_at=entry["retrieved_at"],
            providers=entry["providers"], partial=partial, message=message,
        )

    def _fallback_response(self, query: str, entry: dict[str, Any] | None, message: str) -> dict[str, Any]:
        if entry:
            state = "cache_hit" if entry["fresh"] else "cache_stale"
            response = self._cached_response(query, entry, state=state)
            response["message"] = message + " Showing the last cached retrieval."
            return response
        return self._response("timeout" if "timed out" in message else "unavailable", query, message=message)

    def _acquire_flight(self, key: str) -> _Flight:
        with self._flight_lock:
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight()
                self._flights[key] = flight
            flight.references += 1
            return flight

    def _release_flight(self, key: str, flight: _Flight) -> None:
        with self._flight_lock:
            flight.references -= 1
            if flight.references <= 0 and self._flights.get(key) is flight:
                self._flights.pop(key, None)

    def search(self, raw_query: object, *, refresh: bool = False) -> dict[str, Any]:
        if type(refresh) is not bool:
            raise ValueError("refresh must be boolean")
        query = normalize_query(raw_query)
        key = cache_key(query)
        entry = self._read_cache(key)

        if entry and entry["fresh"] and not refresh:
            return self._cached_response(query, entry, state="cache_hit")
        if self.offline:
            if entry:
                return self._cached_response(query, entry, state="cache_hit" if entry["fresh"] else "cache_stale")
            return self._response("cache_miss_offline", query, message="This query is not in the offline cache.")

        flight = self._acquire_flight(key)
        acquired = flight.lock.acquire(timeout=self.singleflight_wait_seconds)
        if not acquired:
            self._release_flight(key, flight)
            return self._response("busy", query, message="Research capacity is busy. Please retry shortly.")

        slot_acquired = False
        try:
            # Concurrent identical requests share the first completed live outcome,
            # including no-results/failure, without persisting a negative cache row.
            if flight.completed_at is not None and flight.result is not None:
                import time
                if time.monotonic() - flight.completed_at <= self.singleflight_wait_seconds:
                    shared = dict(flight.result)
                    shared["coalesced"] = True
                    return shared

            entry = self._read_cache(key)
            if entry and entry["fresh"] and not refresh:
                response = self._cached_response(query, entry, state="cache_hit")
                flight.result = response
                import time
                flight.completed_at = time.monotonic()
                return response
            if self.offline:
                if entry:
                    response = self._cached_response(query, entry, state="cache_hit" if entry["fresh"] else "cache_stale")
                else:
                    response = self._response("cache_miss_offline", query, message="This query is not in the offline cache.")
                flight.result = response
                import time
                flight.completed_at = time.monotonic()
                return response

            slot_acquired = self._worker_slots.acquire(blocking=False)
            if not slot_acquired:
                response = self._response("busy", query, message="Research capacity is busy. Please retry shortly.")
                flight.result = response
                import time
                flight.completed_at = time.monotonic()
                return response

            try:
                raw_result = self.runner(query)
                result = validate_execution_result(raw_result)
            except WorkerTimeout:
                response = self._fallback_response(query, entry, "The research request timed out.")
            except Exception:
                response = self._fallback_response(query, entry, "Scholarly sources are temporarily unavailable.")
            else:
                status = result["status"]
                papers = result["records"]
                if status in {"completed", "partial"} and papers:
                    normalized_papers = []
                    for paper in papers:
                        row = dict(paper)
                        row["dedupe_key"] = dedupe_key(paper)
                        normalized_papers.append(row)
                    stored = self.store.put(
                        key, query, normalized_papers, result["providers"],
                        partial=(status == "partial"),
                    )
                    response = self._response(
                        "fresh", query,
                        papers=with_relevance(query, stored["papers"]),
                        retrieved_at=stored["retrieved_at"],
                        providers=stored["providers"],
                        partial=bool(stored.get("partial", False)),
                        message="The retrieved set may be incomplete." if stored.get("partial") else None,
                    )
                elif status == "no_results":
                    response = self._response("no_results", query, message="No paper records were returned by the available scholarly providers.")
                elif status in {"unavailable", "failed", "cancelled"} and entry:
                    response = self._fallback_response(query, entry, "Scholarly sources are temporarily unavailable.")
                else:
                    response = self._response("unavailable", query, message="Scholarly sources are temporarily unavailable.")

            flight.result = response
            import time
            flight.completed_at = time.monotonic()
            return response
        finally:
            if slot_acquired:
                self._worker_slots.release()
            flight.lock.release()
            self._release_flight(key, flight)
