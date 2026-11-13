from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from firelab_service.evidence_registry import (
    EvidenceRegistryError,
    load_evidence_registry,
)

ROOT = Path(__file__).resolve().parents[1]


class FireLabEvidenceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_evidence_registry(ROOT)

    def _copy_repo(self):
        temp = tempfile.TemporaryDirectory(prefix="firelab-m4-registry-")
        root = Path(temp.name)
        shutil.copytree(ROOT / "firelab_site", root / "firelab_site")
        (root / "tools" / "firelab").mkdir(parents=True)
        for name in (
            "psi25_canonical.py", "psi25_analysis.py",
            "psi25_findings.py", "psi25_synthesis.py",
        ):
            shutil.copy2(ROOT / "tools" / "firelab" / name, root / "tools" / "firelab" / name)
        return temp, root

    def test_registry_contains_only_the_two_approved_investigation_releases(self):
        self.assertEqual(
            set(self.registry.investigation_ids),
            {"psi69-flex-v5", "psi25-bass-ii-v4"},
        )

    def test_psi69_reuses_the_existing_hash_verified_bundle(self):
        item = self.registry.get("psi69-flex-v5")
        bundle = item.payload["bundle"]
        self.assertEqual(item.record_count, 274)
        self.assertEqual(item.version, "PSI-69 Version 5")
        self.assertEqual(item.source_sha256, bundle["sourceSha256"])
        self.assertEqual(item.records_sha256, bundle["recordsSha256"])
        self.assertEqual(item.quality_sha256, bundle["qualitySha256"])

    def test_psi25_full_artifact_chain_and_counts_are_verified(self):
        item = self.registry.get("psi25-bass-ii-v4")
        payload = item.payload
        self.assertEqual(item.record_count, 129)
        self.assertEqual(item.version, "Study Version 4")
        self.assertEqual(
            item.source_sha256,
            payload["source_sha256"],
            "source_sha256 must identify the selected NASA CSV, not provenance.json",
        )
        self.assertEqual(len(payload["record_keys"]), 129)
        self.assertEqual(payload["synthesis"]["insight_card_count"], 54)
        self.assertEqual(len(payload["synthesis"]["research_questions"]), 146)
        self.assertEqual(len(payload["artifact_sha256"]), 9)

    def test_each_psi25_metric_preserves_complete_record_lineage(self):
        payload = self.registry.get("psi25-bass-ii-v4").payload
        expected = set(payload["record_keys"])
        for metric in ("co", "co2", "o2"):
            paired_keys = {
                row["record_key"]
                for row in payload["paired"]["metrics"][metric]["record_level_audit"]
            }
            self.assertEqual(paired_keys, expected)
            findings_keys = set()
            finding = payload["findings"]["metrics"][metric]
            for cohort in finding["ranked_cohorts"] + finding["not_rankable_cohorts"]:
                for evidence_key in ("eligible_record_evidence", "excluded_record_evidence"):
                    findings_keys.update(row["record_key"] for row in cohort[evidence_key])
            self.assertEqual(findings_keys, expected)
            synthesis_keys = set()
            for card in payload["synthesis"]["metrics"][metric]["insight_cards"]:
                synthesis_keys.update(row["record_key"] for row in card["supporting_record_evidence"])
                synthesis_keys.update(row["record_key"] for row in card["excluded_record_evidence"])
            self.assertEqual(synthesis_keys, expected)

    def test_scientific_caveats_and_non_claim_safeguards_are_preserved(self):
        payload = self.registry.get("psi25-bass-ii-v4").payload
        synthesis = payload["synthesis"]
        self.assertFalse(synthesis["generated_with_llm"])
        self.assertFalse(synthesis["safeguards"]["causal_claims_produced"])
        self.assertFalse(synthesis["safeguards"]["cross_metric_ranking"])
        self.assertFalse(synthesis["safeguards"]["operational_fire_safety_recommendations"])
        self.assertIn("o2", synthesis["measurement_provenance_caveats"])
        self.assertEqual(payload["quality"]["sample_reuse"]["reused_exact_raw_id_groups"], 20)

    def test_unknown_investigation_fails_closed(self):
        with self.assertRaises(EvidenceRegistryError):
            self.registry.get("psi25-all-metrics-combined")

    def test_tampered_synthesis_payload_is_rejected(self):
        temp, root = self._copy_repo()
        self.addCleanup(temp.cleanup)
        target = root / "firelab_site/data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/evidence_synthesis.json"
        raw = target.read_bytes()
        target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaisesRegex(EvidenceRegistryError, "SHA-256 mismatch"):
            load_evidence_registry(root)

    def test_tampered_source_asset_is_rejected(self):
        temp, root = self._copy_repo()
        self.addCleanup(temp.cleanup)
        target = root / "firelab_site/data/source/PSI-25_BASS-II_v4_selected/PSI-25_Experimental table_BASS-II.csv"
        raw = target.read_bytes()
        target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaisesRegex(EvidenceRegistryError, "SHA-256 mismatch"):
            load_evidence_registry(root)

    def test_source_byte_count_mismatch_is_rejected(self):
        temp, root = self._copy_repo()
        self.addCleanup(temp.cleanup)
        target = root / "firelab_site/data/source/PSI-25_BASS-II_v4_selected/PSI-25_Experimental table_BASS-II.csv"
        target.write_bytes(target.read_bytes() + b"\n")
        with self.assertRaisesRegex(EvidenceRegistryError, "manifest byte count mismatch"):
            load_evidence_registry(root)

    def test_tampered_lineage_manifest_is_rejected_by_trust_anchor(self):
        temp, root = self._copy_repo()
        self.addCleanup(temp.cleanup)
        target = root / "firelab_site/data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/synthesis_manifest.json"
        manifest = json.loads(target.read_text(encoding="utf-8"))
        manifest["record_count"] = 128
        target.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(EvidenceRegistryError, "trust anchor"):
            load_evidence_registry(root)

    def test_psi25_evidence_root_symlink_cannot_escape_repository(self):
        temp, root = self._copy_repo()
        self.addCleanup(temp.cleanup)
        outside = root.parent / f"{root.name}-external-evidence"
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        source = root / "firelab_site/data/derived/psi25_bass_ii_v4"
        shutil.copytree(source, outside)
        shutil.rmtree(source)
        source.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(EvidenceRegistryError, "escapes the approved repository root"):
            load_evidence_registry(root)

    def test_psi25_nested_artifact_directory_symlink_cannot_escape_repository(self):
        temp, root = self._copy_repo()
        self.addCleanup(temp.cleanup)
        outside = root.parent / f"{root.name}-external-paired"
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        source = root / "firelab_site/data/derived/psi25_bass_ii_v4/paired_analysis_v1"
        shutil.copytree(source, outside)
        shutil.rmtree(source)
        source.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(EvidenceRegistryError, "escapes the approved evidence root"):
            load_evidence_registry(root)


if __name__ == "__main__":
    unittest.main()
