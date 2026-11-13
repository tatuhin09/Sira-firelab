"""Regression tests for PSI-25 synthesis upstream hash lineage."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "firelab_site" / "psi25.js"


class Psi25SynthesisLineageRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = JS_PATH.read_text(encoding="utf-8")

    def test_paired_payload_and_verified_hash_have_separate_state(self):
        self.assertIn("let pairedAnalysis = null;", self.source)
        self.assertIn("let pairedAnalysisHash = null;", self.source)

    def test_verified_digest_is_saved_only_after_hash_and_size_check(self):
        start = self.source.index("async function loadPsi25Analysis()")
        end = self.source.index("async function loadPsi25()", start)
        loader = self.source[start:end]
        digest_at = loader.index("const digest = bytesToHex(")
        verification_at = loader.index("if (digest !== derived.sha256 || bytes.byteLength !== derived.bytes)")
        payload_assignment_at = loader.index("pairedAnalysis = payload;")
        hash_assignment_at = loader.index("pairedAnalysisHash = digest;")
        self.assertLess(digest_at, verification_at)
        self.assertLess(verification_at, payload_assignment_at)
        self.assertLess(payload_assignment_at, hash_assignment_at)

    def test_synthesis_payload_validator_uses_verified_paired_hash(self):
        self.assertIn(
            "source.paired_measurement_analysis?.sha256 !== pairedAnalysisHash",
            self.source,
        )
        self.assertNotIn(
            "source.paired_measurement_analysis?.sha256 !== pairedAnalysis?.sha256",
            self.source,
        )

    def test_synthesis_loader_uses_verified_paired_hash(self):
        self.assertIn(
            "manifestData.source_artifacts?.paired_measurement_analysis?.sha256 !== pairedAnalysisHash",
            self.source,
        )
        self.assertNotIn(
            "manifestData.source_artifacts?.paired_measurement_analysis?.sha256 !== pairedAnalysis?.sha256",
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
