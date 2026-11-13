import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest

from firelab_service.paper_search.query import cache_key
from firelab_service.paper_search.runner import WorkerTimeout
from firelab_service.paper_search.service import PaperSearchService
from firelab_service.paper_search.store import PaperCacheStore


def paper():
    return {
        "paper_id": "crossref:123", "title": "Microgravity flame extinction",
        "abstract": None, "authors": ["Researcher"], "year": 2021,
        "doi": "10.1000/test", "url": "https://doi.org/10.1000/test",
        "open_access_pdf_url": None, "retrieved_at": "2026-10-31T00:00:00+00:00",
        "provider": "crossref", "published_date": None, "providers": ["crossref"],
    }


def execution(status="completed"):
    return {
        "schema": "sira.research_execution.v1", "status": status,
        "records": [paper()] if status in {"completed", "partial"} else [],
        "providers_attempted": ["crossref"], "provider_chain": ["crossref"],
        "attempts": [{"provider_id": "crossref"}], "providers_skipped_cooldown": [], "api_requests": 1,
    }


class StoreTests(unittest.TestCase):
    def test_store_roundtrip_foreign_keys_and_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "runtime" / "firelab"
            store = PaperCacheStore(runtime)
            row = paper() | {"dedupe_key": "doi:10.1000/test"}
            result = store.put(cache_key("microgravity flame"), "microgravity flame", [row], ["crossref"])
            self.assertEqual(len(result["papers"]), 1)
            self.assertTrue(result["fresh"])
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
            self.assertEqual(store.db_path.stat().st_mode & 0o777, 0o600)
            connection = store._connect()
            try:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM cached_paper").fetchone()[0], 1)
            finally:
                connection.close()

    def test_unknown_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "firelab"
            store = PaperCacheStore(runtime)
            with sqlite3.connect(store.db_path) as connection:
                connection.execute("UPDATE schema_meta SET value='99' WHERE key='schema_version'")
            with self.assertRaises(RuntimeError):
                PaperCacheStore(runtime)

    def test_database_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "firelab"
            runtime.mkdir()
            outside = Path(temp) / "outside.db"
            outside.write_bytes(b"not a database")
            (runtime / "firelab.sqlite3").symlink_to(outside)
            with self.assertRaises(RuntimeError):
                PaperCacheStore(runtime)

    def test_failed_insert_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            bad = {"dedupe_key": "x"}
            key = cache_key("rollback test query")
            with self.assertRaises(KeyError):
                store.put(key, "rollback test query", [bad], ["crossref"])
            self.assertIsNone(store.get(key))

    def test_cache_expiry(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab", ttl_seconds=1)
            key = cache_key("microgravity flame")
            store.put(key, "microgravity flame", [paper() | {"dedupe_key": "doi:10.1000/test"}], ["crossref"])
            with sqlite3.connect(store.db_path) as connection:
                connection.execute("UPDATE search_cache SET expires_at='2000-01-01T00:00:00Z'")
            self.assertFalse(store.get(key)["fresh"])


class ServiceTests(unittest.TestCase):
    def test_miss_calls_runner_once_then_cache_hit_calls_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            calls = []
            service = PaperSearchService(store, lambda query: calls.append(query) or execution())
            first = service.search("microgravity flame")
            second = service.search("microgravity flame")
            self.assertEqual(first["state"], "fresh")
            self.assertEqual(second["state"], "cache_hit")
            self.assertEqual(len(calls), 1)

    def test_offline_miss_is_explicit_and_does_not_call_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            service = PaperSearchService(store, lambda _query: self.fail("worker must not run"), offline=True)
            self.assertEqual(service.search("unknown query")["state"], "cache_miss_offline")

    def test_expired_offline_entry_is_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            key = cache_key("microgravity flame")
            store.put(key, "microgravity flame", [paper() | {"dedupe_key": "doi:10.1000/test"}], ["crossref"])
            with sqlite3.connect(store.db_path) as connection:
                connection.execute("UPDATE search_cache SET expires_at='2000-01-01T00:00:00Z'")
            service = PaperSearchService(store, lambda _query: self.fail("worker must not run"), offline=True)
            self.assertEqual(service.search("microgravity flame")["state"], "cache_stale")

    def test_partial_status_survives_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            service = PaperSearchService(store, lambda _query: execution("partial"))
            first = service.search("microgravity flame")
            second = service.search("microgravity flame")
            self.assertTrue(first["partial"])
            self.assertTrue(second["partial"])
            self.assertIn("incomplete", second.get("message", ""))
            self.assertEqual(second["state"], "cache_hit")

    def test_no_results_are_not_persistently_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            calls = []
            service = PaperSearchService(store, lambda query: calls.append(query) or execution("no_results"))
            self.assertEqual(service.search("microgravity flame")["state"], "no_results")
            self.assertEqual(service.search("microgravity flame")["state"], "no_results")
            self.assertEqual(len(calls), 2)

    def test_worker_failure_uses_stale_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            key = cache_key("microgravity flame")
            store.put(key, "microgravity flame", [paper() | {"dedupe_key": "doi:10.1000/test"}], ["crossref"])
            with sqlite3.connect(store.db_path) as connection:
                connection.execute("UPDATE search_cache SET expires_at='2000-01-01T00:00:00Z'")
            service = PaperSearchService(store, lambda _query: (_ for _ in ()).throw(RuntimeError("secret detail")))
            result = service.search("microgravity flame")
            self.assertEqual(result["state"], "cache_stale")
            self.assertNotIn("secret detail", str(result))

    def test_identical_concurrent_requests_share_one_live_result(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            started = threading.Event()
            release = threading.Event()
            calls = []
            def worker(query):
                calls.append(query)
                started.set()
                release.wait(3)
                return execution()
            service = PaperSearchService(store, worker)
            results = []
            first = threading.Thread(target=lambda: results.append(service.search("microgravity flame")))
            second = threading.Thread(target=lambda: results.append(service.search("microgravity flame")))
            first.start()
            self.assertTrue(started.wait(2))
            second.start()
            time.sleep(0.1)
            release.set()
            first.join(3); second.join(3)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(results), 2)
            self.assertTrue(all(result["state"] == "fresh" for result in results))

    def test_worker_slot_limit_returns_busy(self):
        with tempfile.TemporaryDirectory() as temp:
            store = PaperCacheStore(Path(temp) / "firelab")
            started = threading.Event()
            release = threading.Event()
            def worker(_query):
                started.set()
                release.wait(3)
                return execution()
            service = PaperSearchService(store, worker, max_workers=2)
            results = []
            threads = [threading.Thread(target=lambda q=q: results.append(service.search(q))) for q in (
                "query alpha", "query bravo"
            )]
            for thread in threads: thread.start()
            self.assertTrue(started.wait(2))
            time.sleep(0.1)
            third = service.search("query charlie")
            release.set()
            for thread in threads: thread.join(3)
            self.assertEqual(third["state"], "busy")


if __name__ == "__main__":
    unittest.main()
