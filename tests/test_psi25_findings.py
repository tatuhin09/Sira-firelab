import hashlib
import json
import tempfile
import unittest
from statistics import median
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "firelab"))

import psi25_findings as findings


def make_fixture():
    def cohort(pi, material, flow, vals, status="descriptive_only", ids=2, reused=0):
        records = len(vals)
        eligible = records
        stats = {
            "n": eligible,
            "mean": str(sum(vals) / len(vals)),
            "median": str(median(vals)),
            "minimum": str(min(vals)),
            "maximum": str(max(vals)),
        }
        return {
            "cohort": {"pi": pi, "material_class": material, "flow_restrictor_code": flow},
            "records_in_cohort": records,
            "eligible_pairs": eligible,
            "excluded_pairs": 0,
            "distinct_exact_sample_ids_in_cohort": ids,
            "records_marked_with_reused_sample_id": reused,
            "summary_status": status,
            "statistics_n_definition": "eligible experiment records; not necessarily independent physical samples",
            "sample_reuse_caveat": "Repeated identifiers may be dependent.",
            "statistics": stats,
        }

    cohorts = [
        cohort("PI-A", "PMMA", "0", [1, 3, 8], ids=3, reused=1),
        cohort("PI-B", "SIBAL", "2", [-2, -4], ids=2),
        {
            "cohort": {"pi": "PI-C", "material_class": "unclassified", "flow_restrictor_code": "1"},
            "records_in_cohort": 1,
            "eligible_pairs": 0,
            "excluded_pairs": 1,
            "distinct_exact_sample_ids_in_cohort": 1,
            "records_marked_with_reused_sample_id": 0,
            "summary_status": "no_eligible_pairs",
            "statistics": None,
        },
    ]
    audits = []
    for c in cohorts:
        group = c["cohort"]
        for i in range(c["records_in_cohort"]):
            eligible = i < c["eligible_pairs"]
            values = [1, 3, 8] if group["pi"] == "PI-A" else [-2, -4]
            audits.append({
                "record_key": f"{group['pi']}-{i}",
                "test_id": f"T-{group['pi']}-{i}",
                "sample_id_raw": f"S-{group['pi']}-{i}",
                "sample_id_reused": c.get("records_marked_with_reused_sample_id", 0) > 0 and i == 0,
                "pi": group["pi"],
                "material_class": group["material_class"],
                "flow_restrictor_code": group["flow_restrictor_code"],
                "pair_eligible": eligible,
                "delta_final_minus_initial": str(values[i]) if eligible else None,
                "exclusion_reasons": [] if eligible else ["source_none"],
            })
    metric_template = {
        "label": "Metric label",
        "unit": "unit-x",
        "pair_counts": {"records": len(audits), "eligible_pairs": 5, "excluded_pairs": 1},
        "cohort_summaries": cohorts,
        "record_level_audit": audits,
    }
    analysis = {
        "dataset": "NASA PSI-25 BASS-II",
        "study_version": 4,
        "record_count": len(audits),
        "source_investigation": "PSI-25",
        "metrics": {key: metric_template for key in findings.EXPECTED_METRICS},
        "sample_reuse_summary": {"distinct_nonblank_exact_raw_sample_ids": 3, "reused_exact_raw_id_groups": 1},
        "measurement_provenance_caveats": {"o2": {"interpretation_limit": "Sensor calibration caveat."}},
        "scientific_use_constraints": ["Descriptive only."],
    }
    manifest = {
        "record_count": len(audits),
        "derived_output": {"sha256": "placeholder", "bytes": 0},
        "o2_calibration_caveat_included": True,
        "independent_sample_inference": False,
    }
    encoded = json.dumps(analysis, sort_keys=True).encode()
    analysis_hash = hashlib.sha256(encoded).hexdigest()
    manifest["derived_output"] = {"sha256": analysis_hash, "bytes": len(encoded)}
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    return analysis, manifest, analysis_hash, manifest_hash


def make_inputs():
    analysis, manifest, ah, mh = make_fixture()
    return {
        "analysis": analysis,
        "analysis_manifest": manifest,
        "analysis_sha256": ah,
        "analysis_manifest_sha256": mh,
        "analysis_bytes": manifest["derived_output"]["bytes"],
        "analysis_manifest_bytes": len(json.dumps(manifest).encode()),
        "input_path": ".",
    }


class Psi25FindingsTests(unittest.TestCase):
    def test_ranks_each_metric_independently_by_signed_mean(self):
        payload, _ = findings.build_payload(make_inputs(), "builder")
        for key in findings.EXPECTED_METRICS:
            ranked = payload["metrics"][key]["ranked_cohorts"]
            self.assertEqual(ranked[0]["cohort"]["pi"], "PI-A")
            self.assertEqual(ranked[-1]["cohort"]["pi"], "PI-B")

    def test_zero_pair_cohort_is_not_ranked(self):
        payload, _ = findings.build_payload(make_inputs(), "builder")
        metric = payload["metrics"]["o2"]
        self.assertEqual(metric["not_rankable_cohort_count"], 1)
        self.assertEqual(metric["not_rankable_cohorts"][0]["not_rankable_reason"], "no_eligible_pairs")

    def test_no_inferential_or_cross_metric_ranking(self):
        payload, manifest = findings.build_payload(make_inputs(), "builder")
        self.assertFalse(payload["inferential_statistics_produced"])
        self.assertFalse(payload["causal_claims_produced"])
        self.assertFalse(payload["cross_metric_ranking"])
        self.assertFalse(manifest["independent_sample_inference"])

    def test_sample_reuse_metadata_is_preserved(self):
        payload, _ = findings.build_payload(make_inputs(), "builder")
        first = payload["metrics"]["o2"]["ranked_cohorts"][0]
        self.assertEqual(first["records_marked_with_reused_sample_id"], 1)
        self.assertTrue(first["eligible_record_evidence"][0]["sample_id_reused"])

    def test_mean_median_sign_relation_is_explicit(self):
        payload, _ = findings.build_payload(make_inputs(), "builder")
        for metric in findings.EXPECTED_METRICS:
            rel = payload["metrics"][metric]["ranked_cohorts"][0]["mean_median_sign_relation"]
            self.assertIn(rel, {"same_sign", "opposite_sign", "one_zero", "both_zero"})

    def test_absolute_mean_median_gap_is_reported_without_outlier_claim(self):
        payload, _ = findings.build_payload(make_inputs(), "builder")
        first = payload["metrics"]["o2"]["ranked_cohorts"][0]
        self.assertEqual(first["absolute_mean_median_gap"], "1.0")

    def test_equal_means_share_competition_rank(self):
        inputs = make_inputs()
        for metric in findings.EXPECTED_METRICS:
            stats = inputs["analysis"]["metrics"][metric]["cohort_summaries"][1]["statistics"]
            stats.update({"mean": "4", "median": "4", "minimum": "3", "maximum": "5"})
            for index, row in enumerate(inputs["analysis"]["metrics"][metric]["record_level_audit"]):
                if row["pi"] == "PI-B" and row["pair_eligible"]:
                    row["delta_final_minus_initial"] = str([3, 5][index % 2])
        payload, _ = findings.build_payload(inputs, "builder")
        for metric in findings.EXPECTED_METRICS:
            ranked = payload["metrics"][metric]["ranked_cohorts"]
            self.assertEqual(ranked[0]["rank"], 1)
            self.assertEqual(ranked[1]["rank"], 1)
            self.assertEqual(ranked[1]["display_order"], 2)

    def test_record_level_evidence_links_back_to_source_records(self):
        payload, _ = findings.build_payload(make_inputs(), "builder")
        first = payload["metrics"]["o2"]["ranked_cohorts"][0]
        self.assertEqual(len(first["eligible_record_evidence"]), 3)
        self.assertTrue(first["eligible_record_evidence"][0]["record_key"])

    def test_pair_accounting_mismatch_is_rejected(self):
        inputs = make_inputs()
        inputs["analysis"]["metrics"]["o2"]["pair_counts"]["eligible_pairs"] = 99
        with self.assertRaises(findings.FindingsError):
            findings.build_payload(inputs, "builder")

    def test_statistics_n_mismatch_is_rejected(self):
        inputs = make_inputs()
        inputs["analysis"]["metrics"]["co"]["cohort_summaries"][0]["statistics"]["n"] = 99
        with self.assertRaises(findings.FindingsError):
            findings.build_payload(inputs, "builder")

    def test_zero_pair_with_fabricated_mean_is_rejected(self):
        inputs = make_inputs()
        inputs["analysis"]["metrics"]["co2"]["cohort_summaries"][2]["statistics"] = {"mean": "0"}
        with self.assertRaises(findings.FindingsError):
            findings.build_payload(inputs, "builder")

    def test_output_is_deterministic(self):
        inputs = make_inputs()
        first = findings.build_payload(inputs, "builder")
        second = findings.build_payload(inputs, "builder")
        self.assertEqual(first, second)

    def test_builder_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / findings.DEFAULT_INPUT
            base.mkdir(parents=True)
            analysis, manifest, _, _ = make_fixture()
            a = base / "paired_measurement_analysis.json"
            m = base / "analysis_manifest.json"
            a.write_text(json.dumps(analysis), encoding="utf-8")
            manifest["derived_output"] = {"sha256": hashlib.sha256(a.read_bytes()).hexdigest(), "bytes": a.stat().st_size}
            m.write_text(json.dumps(manifest), encoding="utf-8")
            builder_dir = root / "tools/firelab"
            builder_dir.mkdir(parents=True)
            (builder_dir / "psi25_findings.py").write_text("# test builder", encoding="utf-8")
            out = root / findings.DEFAULT_OUTPUT
            out.mkdir(parents=True)
            with self.assertRaises(findings.FindingsError):
                findings.build(root)


if __name__ == "__main__":
    unittest.main()
