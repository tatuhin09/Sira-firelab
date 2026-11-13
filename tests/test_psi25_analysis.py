import json
import tempfile
import unittest
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools/firelab"))

from psi25_analysis import (
    AnalysisError,
    METRICS,
    _pair_record,
    build_payload,
    load_inputs,
    build,
)


def measurement(raw, status="numeric_exact", eligible=True, unit="ppm", parsed=None):
    if parsed is None and status == "numeric_exact":
        parsed = str(raw)
    return {
        "raw": str(raw),
        "status": status,
        "aggregation_eligible": eligible,
        "parsed_decimal": parsed,
        "unit": unit,
    }


def make_record(key, pi="Olson", material="PMMA rod", restrictor=0,
                initial_co="10", final_co="15", initial_co_status="numeric_exact",
                initial_co_eligible=True, sample="S1"):
    return {
        "identity": {"record_key": key, "test_id": key, "test_id_raw": key, "pi": pi},
        "date": {"iso": "2000-01-01", "raw": "2000-01-01"},
        "sample": {"id_raw": sample, "is_reused_exact_raw_id": sample == "S1"},
        "material": {"raw": material, "canonical_class": material},
        "flow_restrictor": {"code": restrictor},
        "measurements": {
            "initial_co": measurement(initial_co, initial_co_status, initial_co_eligible),
            "final_co": measurement(final_co),
            "initial_o2": measurement("21", unit="% by volume"),
            "final_o2": measurement("20", unit="% by volume"),
            "initial_co2": measurement("0.4", unit="% by volume"),
            "final_co2": measurement("0.5", unit="% by volume"),
        },
    }


class Psi25AnalysisTests(unittest.TestCase):
    def test_exact_pair_computes_final_minus_initial(self):
        row = _pair_record(make_record("O1"), "co", METRICS["co"])
        self.assertTrue(row["pair_eligible"])
        self.assertEqual(row["delta_final_minus_initial"], "5")

    def test_censored_or_ineligible_initial_value_is_excluded(self):
        record = make_record("O2", initial_co="OR", initial_co_status="right_censored",
                             initial_co_eligible=False, )
        record["measurements"]["initial_co"]["parsed_decimal"] = None
        row = _pair_record(record, "co", METRICS["co"])
        self.assertFalse(row["pair_eligible"])
        self.assertIsNone(row["delta_final_minus_initial"])
        self.assertTrue(any("right_censored" in reason for reason in row["exclusion_reasons"]))

    def test_negative_co_is_defensively_excluded(self):
        record = make_record("O3", initial_co="-1", initial_co_status="numeric_exact", initial_co_eligible=True)
        row = _pair_record(record, "co", METRICS["co"])
        self.assertFalse(row["pair_eligible"])
        self.assertIn("initial_negative_co_requires_review", row["exclusion_reasons"])

    def test_unit_mismatch_is_excluded(self):
        record = make_record("O4")
        record["measurements"]["final_co"]["unit"] = "% by volume"
        row = _pair_record(record, "co", METRICS["co"])
        self.assertFalse(row["pair_eligible"])
        self.assertIn("initial_final_unit_mismatch", row["exclusion_reasons"])

    def test_reused_sample_records_are_not_deduplicated_and_cohorts_stay_separate(self):
        r1 = make_record("O1", pi="Olson", sample="SAME")
        r2 = make_record("F1", pi="Ferkul", sample="SAME")
        canonical = {"study_version": 4, "source_investigation": "PSI-25", "records": [r1, r2]}
        inputs = {"records": [r1, r2], "canonical": canonical, "source_hashes": {}}
        payload, _ = build_payload(inputs, "builderhash")
        audit = payload["metrics"]["co"]["record_level_audit"]
        self.assertEqual(len(audit), 2)
        self.assertNotEqual(
            payload["metrics"]["co"]["cohort_summaries"][0]["cohort"]["pi"],
            payload["metrics"]["co"]["cohort_summaries"][1]["cohort"]["pi"],
        )

    def test_o2_calibration_caveat_is_explicit_in_output(self):
        record = make_record("O2-1")
        canonical = {"study_version": 4, "source_investigation": "PSI-25", "records": [record]}
        inputs = {"records": [record], "canonical": canonical, "source_hashes": {}}
        payload, manifest = build_payload(inputs, "builderhash")
        caveat = payload["measurement_provenance_caveats"]["o2"]
        self.assertIn("out of calibration", caveat["source_note"])
        self.assertIn("daily constant-offset correction", caveat["source_note"])
        self.assertIn("residual measurement uncertainty", caveat["interpretation_limit"])
        self.assertTrue(manifest["o2_calibration_caveat_included"])

    def test_reused_sample_ids_are_reported_as_potentially_dependent(self):
        r1 = make_record("O1", sample="S1")
        r2 = make_record("O2", sample="S1")
        canonical = {"study_version": 4, "source_investigation": "PSI-25", "records": [r1, r2]}
        inputs = {"records": [r1, r2], "canonical": canonical, "source_hashes": {}}
        payload, manifest = build_payload(inputs, "builderhash")
        summary = payload["metrics"]["co"]["cohort_summaries"][0]
        self.assertEqual(payload["sample_reuse_summary"]["reused_exact_raw_id_groups"], 1)
        self.assertEqual(summary["records_marked_with_reused_sample_id"], 2)
        self.assertEqual(summary["statistics"]["n"], 2)
        self.assertIn("not necessarily independent physical samples", summary["statistics_n_definition"])
        self.assertFalse(summary["inferential_statistics_produced"])
        self.assertFalse(manifest["independent_sample_inference"])

    def test_source_count_mismatch_fails_integrity_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "firelab_site/data/derived/psi25_bass_ii_v4"
            base.mkdir(parents=True)
            (base / "canonical_records.json").write_text(json.dumps({"record_count": 1, "records": []}), encoding="utf-8")
            (base / "quality_report.json").write_text(json.dumps({"record_count": 0}), encoding="utf-8")
            (base / "canonical_manifest.json").write_text(json.dumps({"record_count": 0, "study_version": 4}), encoding="utf-8")
            with self.assertRaises(AnalysisError):
                load_inputs(root)


if __name__ == "__main__":
    unittest.main()
