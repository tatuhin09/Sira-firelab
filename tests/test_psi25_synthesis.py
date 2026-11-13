from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "firelab"))
import psi25_synthesis as synthesis


def cohort(group, rows, *, rank=1, mean=None, median=None, minimum=None, maximum=None,
           distinct=2, reused=0, status="small_n_descriptive_only"):
    eligible = len(rows)
    if eligible == 0:
        return {
            "cohort": group,
            "records_in_cohort": 1,
            "eligible_pairs": 0,
            "excluded_pairs": 1,
            "distinct_exact_sample_ids_in_cohort": distinct,
            "records_marked_with_reused_sample_id": reused,
            "summary_status": "no_eligible_pairs",
            "statistics_n_definition": "eligible experiment records; not necessarily independent physical samples",
            "sample_reuse_caveat": "Repeated exact Sample IDs may indicate dependent records.",
            "eligible_record_evidence": [],
            "excluded_record_evidence": [{
                "record_key": "R4", "test_id": "T4", "sample_id_raw": "S4",
                "exclusion_reasons": ["final_status_not_numeric_exact:source_none"]
            }],
            "not_rankable_reason": "no_eligible_pairs",
        }
    values = [synthesis._decimal(r["delta_final_minus_initial"], "fixture") for r in rows]
    mean = str(sum(values) / len(values)) if mean is None else str(mean)
    median = mean if median is None else str(median)
    minimum = str(min(values)) if minimum is None else str(minimum)
    maximum = str(max(values)) if maximum is None else str(maximum)
    mean_d = synthesis._decimal(mean, "mean")
    median_d = synthesis._decimal(median, "median")
    relation = synthesis._mean_median_relation(mean_d, median_d)
    return {
        "cohort": group,
        "rank": rank,
        "display_order": rank,
        "ranked_by": "signed_mean_paired_change_within_metric_only",
        "records_in_cohort": eligible,
        "eligible_pairs": eligible,
        "excluded_pairs": 0,
        "distinct_exact_sample_ids_in_cohort": distinct,
        "records_marked_with_reused_sample_id": reused,
        "summary_status": status,
        "statistics_n_definition": "eligible experiment records; not necessarily independent physical samples",
        "sample_reuse_caveat": "Repeated exact Sample IDs may indicate dependent records.",
        "statistics": {"n": eligible, "mean": mean, "median": median, "minimum": minimum, "maximum": maximum},
        "mean_median_sign_relation": relation,
        "absolute_mean_median_gap": str(abs(mean_d - median_d)),
        "eligible_record_evidence": rows,
        "excluded_record_evidence": [],
    }


def make_inputs():
    metrics = {}
    for key, unit in (("o2", "% by volume"), ("co2", "% by volume"), ("co", "ppm")):
        rows = [
            {"record_key": "R1", "test_id": "T1", "sample_id_raw": "S1", "sample_id_reused": True, "delta_final_minus_initial": "2"},
            {"record_key": "R2", "test_id": "T2", "sample_id_raw": "S1", "sample_id_reused": True, "delta_final_minus_initial": "-1"},
            {"record_key": "R3", "test_id": "T3", "sample_id_raw": "S3", "sample_id_reused": False, "delta_final_minus_initial": "0"},
        ]
        c1 = cohort({"pi": "PI-A", "material_class": "PMMA", "flow_restrictor_code": "0"}, rows[:2], rank=1, mean="0.5", median="0.5", minimum="-1", maximum="2", distinct=1, reused=2)
        c2 = cohort({"pi": "PI-B", "material_class": "SIBAL fabric", "flow_restrictor_code": "2"}, rows[2:], rank=2, status="small_n_descriptive_only")
        c3 = cohort({"pi": "PI-C", "material_class": "unclassified", "flow_restrictor_code": "1"}, [], distinct=1)
        metrics[key] = {
            "label": {"o2": "Oxygen concentration change", "co2": "Carbon dioxide concentration change", "co": "Carbon monoxide concentration change"}[key],
            "unit": unit,
            "cohort_count": 3,
            "rankable_cohort_count": 2,
            "not_rankable_cohort_count": 1,
            "pair_counts": {"records": 4, "eligible_pairs": 3, "excluded_pairs": 1},
            "ranked_cohorts": [c1, c2],
            "not_rankable_cohorts": [c3],
        }
    return {
        "findings": {
            "dataset": "NASA PSI-25 BASS-II",
            "source_investigation": "PSI-25",
            "study_version": 4,
            "record_count": 4,
            "metrics": metrics,
            "measurement_provenance_caveats": {
                "o2": {"source_note": "O2 sensor was out of calibration; daily constant-offset correction was applied."}
            },
            "sample_reuse_summary": {"distinct_nonblank_exact_raw_sample_ids": 3, "reused_exact_raw_id_groups": 1},
            "scientific_use_constraints": ["Descriptive only; no operational safety recommendations."],
            "causal_claims_produced": False,
            "inferential_statistics_produced": False,
            "independent_sample_inference": False,
            "cross_metric_ranking": False,
        },
        "findings_manifest": {},
        "findings_sha256": "findings-hash",
        "findings_manifest_sha256": "manifest-hash",
        "findings_bytes": 123,
        "findings_manifest_bytes": 234,
        "paired_analysis_sha256": "paired-hash",
        "paired_analysis_manifest_sha256": "paired-manifest-hash",
        "paired_analysis_bytes": 456,
        "findings_builder_sha256": "builder-hash",
    }


class Psi25SynthesisTests(unittest.TestCase):
    def test_build_creates_separate_metric_insight_cards(self):
        payload, manifest = synthesis.build_payload(make_inputs(), "builder")
        self.assertEqual(set(payload["metrics"]), {"o2", "co2", "co"})
        self.assertEqual(payload["insight_card_count"], 9)
        self.assertEqual(manifest["insight_card_count"], 9)
        self.assertEqual(payload["record_count"], 4)

    def test_positive_negative_zero_direction_counts_are_explicit(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        card = payload["metrics"]["o2"]["insight_cards"][0]
        self.assertEqual(card["direction_counts"], {"positive": 1, "negative": 1, "zero": 0})
        self.assertIn("mixed_positive_and_negative_record_changes", card["flags"])

    def test_mixed_changes_do_not_get_simplified_to_mean_direction(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        card = payload["metrics"]["co"]["insight_cards"][0]
        self.assertEqual(card["mean_direction"], "positive")
        self.assertIn("1 positive, 1 negative", card["distribution"])

    def test_small_n_flag_is_retained(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        card = payload["metrics"]["co2"]["insight_cards"][1]
        self.assertIn("small_n_descriptive_only", card["flags"])

    def test_sample_reuse_flag_and_question_are_created(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        card = payload["metrics"]["o2"]["insight_cards"][0]
        self.assertIn("sample_id_reuse_possible_dependence", card["flags"])
        self.assertTrue(any(q["trigger"] == "sample_id_reuse_possible_dependence" for q in card["research_questions"]))

    def test_zero_pair_cohort_is_not_interpreted_or_assigned_zero(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        card = payload["metrics"]["o2"]["insight_cards"][2]
        self.assertEqual(card["interpretation_status"], "not_rankable")
        self.assertNotIn("statistics", card)
        self.assertIsNone(card["rank"])

    def test_o2_sensor_calibration_caveat_is_attached_to_each_o2_cohort(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        for card in payload["metrics"]["o2"]["insight_cards"]:
            self.assertIn("O2", card["evidence_dimensions"]["measurement_caveat"])
            if card["eligible_pairs"]:
                self.assertIn("o2_sensor_calibration_limitation", card["flags"])

    def test_unclassified_material_is_flagged_without_reclassification(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        card = payload["metrics"]["o2"]["insight_cards"][2]
        self.assertEqual(card["cohort"]["material_class"], "unclassified")
        self.assertIn("material_class_unclassified", card["flags"])

    def test_research_questions_prioritize_observed_evidence_gaps(self):
        payload, manifest = synthesis.build_payload(make_inputs(), "builder")
        triggers = {q["trigger"] for q in payload["research_questions"]}
        self.assertIn("sample_reuse_across_dataset", triggers)
        self.assertIn("mission_transfer_gap", triggers)
        self.assertIn("o2_calibration_limitation", triggers)
        self.assertGreater(manifest["research_question_count"], 3)

    def test_no_composite_confidence_score_or_cross_metric_ranking(self):
        payload, manifest = synthesis.build_payload(make_inputs(), "builder")
        self.assertFalse(payload["safeguards"]["cross_metric_ranking"])
        self.assertFalse(payload["safeguards"]["causal_claims_produced"])
        self.assertFalse(payload["safeguards"]["inferential_statistics_produced"])
        self.assertFalse(payload["safeguards"]["operational_fire_safety_recommendations"])
        self.assertFalse(payload["generated_with_llm"])
        self.assertNotIn("confidence_score", json.dumps(payload))
        self.assertFalse(manifest["llm_used"])

    def test_evidence_record_keys_cover_all_records_once_per_metric(self):
        payload, _ = synthesis.build_payload(make_inputs(), "builder")
        for metric in payload["metrics"].values():
            keys = []
            for card in metric["insight_cards"]:
                keys.extend(row["record_key"] for row in card["supporting_record_evidence"] + card["excluded_record_evidence"])
            self.assertEqual(len(keys), 4)
            self.assertEqual(len(set(keys)), 4)

    def test_duplicate_evidence_key_is_rejected(self):
        inputs = make_inputs()
        inputs["findings"]["metrics"]["o2"]["ranked_cohorts"][0]["eligible_record_evidence"][1]["record_key"] = "R1"
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.build_payload(inputs, "builder")

    def test_evidence_count_mismatch_is_rejected(self):
        inputs = make_inputs()
        inputs["findings"]["metrics"]["co2"]["ranked_cohorts"][0]["eligible_record_evidence"].pop()
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.build_payload(inputs, "builder")

    def test_nonfinite_delta_is_rejected(self):
        inputs = make_inputs()
        inputs["findings"]["metrics"]["co"]["ranked_cohorts"][0]["eligible_record_evidence"][0]["delta_final_minus_initial"] = "NaN"
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.build_payload(inputs, "builder")

    def test_payload_is_deterministic(self):
        first, first_manifest = synthesis.build_payload(make_inputs(), "builder")
        second, second_manifest = synthesis.build_payload(make_inputs(), "builder")
        self.assertEqual(synthesis._encode_json(first), synthesis._encode_json(second))
        self.assertEqual(first_manifest, second_manifest)

    def test_zero_eligible_pair_cohort_with_evidence_is_rejected(self):
        inputs = make_inputs()
        c = inputs["findings"]["metrics"]["o2"]["not_rankable_cohorts"][0]
        c["eligible_record_evidence"] = [{"record_key": "R4", "delta_final_minus_initial": "0"}]
        with self.assertRaises(synthesis.SynthesisError):
            synthesis.build_payload(inputs, "builder")


if __name__ == "__main__":
    unittest.main()
