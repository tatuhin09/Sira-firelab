import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from firelab_service.engine import load_bundle
from tools.ingest_firelab_flex import build_bundle, write_bundle


REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "firelab_site"


class BundleIntegrityHashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.site = Path(self.temp.name) / "site"
        shutil.copytree(SITE, self.site)

    def tearDown(self):
        self.temp.cleanup()

    def test_bundle_hashes_match_exact_json_bytes(self):
        bundle = load_bundle(self.site)
        data = self.site / "data"
        self.assertEqual(
            bundle["recordsSha256"],
            hashlib.sha256((data / "records.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            bundle["qualitySha256"],
            hashlib.sha256((data / "quality.json").read_bytes()).hexdigest(),
        )

    def test_ingestion_write_bundle_emits_loadable_hashed_manifest(self):
        source_path = SITE / "data" / "source" / "PSI-69_Experimental table_FLEX.csv"
        output_site = Path(self.temp.name) / "ingested_site"
        bundle = write_bundle(source_path, output_site, retrieved_at="2026-10-31")
        loaded = load_bundle(output_site)
        self.assertEqual(bundle["manifest"]["recordsSha256"], loaded["recordsSha256"])
        self.assertEqual(bundle["manifest"]["qualitySha256"], loaded["qualitySha256"])

    def test_records_tampering_is_rejected_before_bundle_use(self):
        path = self.site / "data" / "records.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "records.json hash"):
            load_bundle(self.site)

    def test_quality_tampering_is_rejected_before_bundle_use(self):
        path = self.site / "data" / "quality.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "quality.json hash"):
            load_bundle(self.site)

    def test_ingestion_builds_hashes_for_exact_output_json_bytes(self):
        source_path = SITE / "data" / "source" / "PSI-69_Experimental table_FLEX.csv"
        bundle = build_bundle(
            source_path.read_bytes(),
            source_name=source_path.name,
            retrieved_at="2026-10-31",
        )
        for field, key in (("recordsSha256", "records"), ("qualitySha256", "quality")):
            serialized = (json.dumps(bundle[key], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            self.assertEqual(bundle["manifest"][field], hashlib.sha256(serialized).hexdigest())

    def test_missing_or_malformed_hash_is_rejected(self):
        path = self.site / "data" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.pop("recordsSha256")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "recordsSha256"):
            load_bundle(self.site)

        manifest["recordsSha256"] = "not-a-sha256"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "recordsSha256"):
            load_bundle(self.site)


if __name__ == "__main__":
    unittest.main()
