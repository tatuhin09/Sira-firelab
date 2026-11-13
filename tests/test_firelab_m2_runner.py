import io
import json
from pathlib import Path
import tempfile
import unittest

from firelab_service.paper_search.paths import FireLabPaths
from firelab_service.paper_search.runner import (
    SiraResearchRunner, WorkerOutputTooLarge, WorkerTimeout,
    build_worker_environment,
)
from firelab_service.paper_search import research_worker


class RunnerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def make_repo(self, worker_source: str) -> Path:
        root = Path(self.temp.name)
        (root / "firelab_service" / "paper_search").mkdir(parents=True, exist_ok=True)
        (root / "firelab_service" / "paper_search" / "research_worker.py").write_text(worker_source)
        (root / "src").mkdir(exist_ok=True)
        (root / "firelab_site").mkdir(exist_ok=True)
        return root

    def test_worker_environment_is_exact_allowlist(self):
        root = self.make_repo("pass\n")
        paths = FireLabPaths(root)
        paths.prepare()
        env = build_worker_environment(paths)
        self.assertEqual(set(env), {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"})
        self.assertNotIn("SIRA_SEMANTIC_SCHOLAR_API_KEY", env)
        self.assertNotIn("HTTP_PROXY", env)
        self.assertEqual(env["PATH"], "/usr/bin:/bin")

    def test_isolated_cooldown_permissions_must_be_private(self):
        root = self.make_repo("pass\n")
        paths = FireLabPaths(root)
        paths.prepare()
        cooldowns = paths.sira_root / ".cache" / "opportunity_provider_cooldowns"
        cooldowns.mkdir(parents=True, mode=0o700)
        path = cooldowns / ("a" * 64 + ".json")
        path.write_text("{}")
        path.chmod(0o644)
        with self.assertRaises(RuntimeError):
            paths.assert_isolated_sira_root()

    def test_paths_reject_existing_sira_env_or_memory(self):
        root = self.make_repo("pass\n")
        paths = FireLabPaths(root)
        paths.prepare()
        (paths.sira_root / ".env").write_text("KEY=secret\n")
        with self.assertRaises(RuntimeError):
            paths.assert_isolated_sira_root()

    def test_prepare_does_not_change_shared_runtime_parent_permissions(self):
        root = self.make_repo("pass\n")
        runtime_parent = root / "runtime"
        runtime_parent.mkdir(mode=0o750)
        runtime_parent.chmod(0o750)
        paths = FireLabPaths(root)
        paths.prepare()
        self.assertEqual(runtime_parent.stat().st_mode & 0o777, 0o750)
        self.assertEqual(paths.runtime_dir.stat().st_mode & 0o777, 0o700)

    def test_site_root_symlink_is_rejected(self):
        root = self.make_repo("pass\n")
        real_site = root / "actual_site"
        real_site.mkdir()
        (root / "firelab_site").rmdir()
        (root / "firelab_site").symlink_to(real_site, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            FireLabPaths(root).prepare()

    def test_worker_protocol_with_test_injected_execute(self):
        raw = {
            "schema": "sira.research_execution.v1", "status": "completed",
            "records": [{
                "paper_id": "crossref:1", "title": "Title", "abstract": None,
                "authors": ("A",), "year": 2020, "doi": "10.1000/x",
                "url": "https://doi.org/10.1000/x", "open_access_pdf_url": None,
                "retrieved_at": "2026-10-31T00:00:00Z", "provider": "crossref",
                "published_date": None, "providers": ("crossref",),
            }],
            "providers_attempted": ["crossref"], "provider_chain": ["crossref"],
            "attempts": [{"provider_id": "crossref", "failure_code": None}],
            "providers_skipped_cooldown": [], "api_requests": 1,
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src"
            source.mkdir()
            sira_root = root / "sira_root"
            sira_root.mkdir()
            output = io.StringIO()
            status = research_worker.main(
                [str(source), str(sira_root)],
                io.StringIO(json.dumps({"protocol": 1, "query": "microgravity flame"})),
                output,
                execute=lambda worker_root, query: raw,
            )
        self.assertEqual(status, 0)
        envelope = json.loads(output.getvalue())
        self.assertEqual(envelope["records"][0]["authors"], ["A"])
        self.assertNotIn("failure", envelope)

    def test_broker_guard_blocks_unapproved_provider_before_execution(self):
        allowed = research_worker._bound_broker_decision({
            "status": "ready", "selected_provider_id": "crossref",
            "fallback_provider_ids": ["openalex"],
        }, "capability_unavailable")
        self.assertEqual(allowed["selected_provider_id"], "crossref")
        blocked = research_worker._bound_broker_decision({
            "status": "ready", "selected_provider_id": "tavily",
            "fallback_provider_ids": ["crossref"],
        }, "capability_unavailable")
        self.assertEqual(blocked["status"], "capability_unavailable")
        self.assertIsNone(blocked["selected_provider_id"])
        self.assertEqual(blocked["fallback_provider_ids"], [])

    def test_broker_guard_fails_closed_on_malformed_or_duplicate_chain(self):
        for decision in (
            {"status": "ready", "selected_provider_id": "crossref", "fallback_provider_ids": "openalex"},
            {"status": "ready", "selected_provider_id": "crossref", "fallback_provider_ids": ["crossref"]},
            {"status": "ready", "selected_provider_id": 123, "fallback_provider_ids": []},
            {"status": "ready", "selected_provider_id": None, "fallback_provider_ids": ["crossref"]},
        ):
            with self.subTest(decision=decision):
                blocked = research_worker._bound_broker_decision(decision, "capability_unavailable")
                self.assertEqual(blocked["status"], "capability_unavailable")
                self.assertIsNone(blocked["selected_provider_id"])

    def _make_fake_sira(self, root: Path, *, provider="crossref") -> None:
        source = root / "src" / "sira"
        source.mkdir(parents=True, exist_ok=True)
        (source / "__init__.py").write_text("\n")
        (source / "research_contracts.py").write_text(
            "class ResearchRequest:\n"
            "    def __init__(self, **kwargs):\n"
            "        self.query = kwargs['query']\n"
            "        self.capability = kwargs['capability']\n"
            "        self.max_results = kwargs['max_results']\n"
            "        self.allow_metered = kwargs['allow_metered']\n"
        )
        (source / "capability_broker.py").write_text(
            "STATUS_CAPABILITY_UNAVAILABLE = 'capability_unavailable'\n"
            "def broker_decision(root, capability, **kwargs):\n"
            f"    return {{'status': 'ready', 'selected_provider_id': '{provider}', 'fallback_provider_ids': []}}\n"
        )
        (source / "research_orchestrator.py").write_text(
            "def execute_research(root, request, *, broker):\n"
            "    decision = broker(root, request.capability, allow_metered=request.allow_metered, persist=False)\n"
            "    selected = decision.get('selected_provider_id')\n"
            "    return {'schema': 'sira.research_execution.v1',\n"
            "            'status': 'no_results' if decision.get('status') == 'ready' else 'unavailable',\n"
            "            'records': [], 'providers_attempted': [],\n"
            "            'provider_chain': [selected] if selected else [],\n"
            "            'attempts': [], 'providers_skipped_cooldown': [], 'api_requests': 0}\n"
        )

    def test_isolated_worker_imports_src_package_not_repository_shadow(self):
        root = self.make_repo("pass\n")
        worker_target = root / "firelab_service" / "paper_search" / "research_worker.py"
        worker_target.write_text(Path(research_worker.__file__).read_text())
        self._make_fake_sira(root)
        (root / "sira.py").write_text("raise RuntimeError('repository shadow imported')\n")
        raw = SiraResearchRunner(FireLabPaths(root), timeout=5).run("microgravity flame")
        self.assertEqual(raw["status"], "no_results")
        self.assertEqual(raw["provider_chain"], ["crossref"])

    def test_isolated_worker_blocks_changed_broker_provider_chain(self):
        root = self.make_repo("pass\n")
        worker_target = root / "firelab_service" / "paper_search" / "research_worker.py"
        worker_target.write_text(Path(research_worker.__file__).read_text())
        self._make_fake_sira(root, provider="tavily")
        raw = SiraResearchRunner(FireLabPaths(root), timeout=5).run("microgravity flame")
        self.assertEqual(raw["status"], "unavailable")
        self.assertEqual(raw["provider_chain"], [])
        self.assertEqual(raw["providers_attempted"], [])

    def test_worker_source_has_no_production_factory_override(self):
        source = Path(research_worker.__file__).read_text()
        self.assertNotIn("provider_factories=", source)

    def test_subprocess_timeout_kills_worker(self):
        root = self.make_repo("import time\ntime.sleep(5)\n")
        runner = SiraResearchRunner(FireLabPaths(root), timeout=1)
        with self.assertRaises(WorkerTimeout):
            runner.run("microgravity flame")

    def test_subprocess_output_is_bounded(self):
        root = self.make_repo("import sys\nsys.stdout.write('x' * 600000)\n")
        runner = SiraResearchRunner(FireLabPaths(root), timeout=5)
        with self.assertRaises(WorkerOutputTooLarge):
            runner.run("microgravity flame")


if __name__ == "__main__":
    unittest.main()
