from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "firelab_site/data/derived/psi25_bass_ii_v4/findings_ranking_v1"


class Psi25FindingsDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "firelab_site/index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "firelab_site/psi25.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "firelab_site/styles.css").read_text(encoding="utf-8")
        cls.payload_bytes = (DATA / "findings_ranking.json").read_bytes()
        cls.payload = json.loads(cls.payload_bytes)
        cls.manifest = json.loads((DATA / "findings_manifest.json").read_text(encoding="utf-8"))

    def test_panel_is_inside_dedicated_bass_ii_page(self):
        start = self.html.index('id="view-psi25"')
        end = self.html.index('data-view="research"', start)
        page = self.html[start:end]
        self.assertIn('id="psi25-findings-title"', page)
        self.assertIn('class="panel psi25-findings-panel"', page)

    def test_metric_specific_controls_are_present(self):
        for token in ('psi25-findings-metric', 'psi25-findings-pi', 'psi25-findings-material', 'psi25-findings-restrictor', 'psi25-findings-reset'):
            self.assertIn(token, self.html)

    def test_ranked_and_not_rankable_tables_are_separate(self):
        self.assertIn('id="psi25-findings-ranked"', self.html)
        self.assertIn('id="psi25-findings-not-ranked"', self.html)
        self.assertIn("NOT RANKABLE", self.html)

    def test_supporting_and_excluded_evidence_are_inspectable(self):
        self.assertIn('id="psi25-findings-eligible-evidence"', self.html)
        self.assertIn('id="psi25-findings-excluded-evidence"', self.html)
        self.assertIn("Open source record", self.js)
        self.assertIn("renderRecordDetails(record)", self.js)

    def test_findings_payload_is_loaded_as_local_versioned_asset(self):
        self.assertIn('findings_ranking_v1/findings_ranking.json', self.js)
        self.assertIn('findings_ranking_v1/findings_manifest.json', self.js)
        self.assertNotIn("https://", self.js[self.js.index("const FINDINGS_FILES"):self.js.index("const $ =")])

    def test_payload_hash_and_byte_size_are_verified(self):
        actual = hashlib.sha256(self.payload_bytes).hexdigest()
        self.assertEqual(actual, self.manifest["derived_output"]["sha256"])
        self.assertEqual(len(self.payload_bytes), self.manifest["derived_output"]["bytes"])
        self.assertIn("crypto.subtle.digest(\"SHA-256\", bytes)", self.js)

    def test_findings_source_lineage_matches_paired_analysis(self):
        paired = self.manifest["source_artifacts"]["paired_measurement_analysis"]
        self.assertEqual(paired["sha256"], "a0562fe7a587e4f63cbb09fff226e5e9bfc5d7ee4bc1cd9aeee03085cf504e4b")
        self.assertIn("source_artifacts?.paired_measurement_analysis?.sha256 !== expectedPairedHash", self.js)
        self.assertIn("await loadPsi25Findings(digest)", self.js)

    def test_metric_rankings_are_precomputed_and_separate(self):
        self.assertEqual(set(self.payload["metrics"]), {"o2", "co2", "co"})
        for metric in self.payload["metrics"].values():
            self.assertEqual(metric["ranked_cohorts"][0]["ranked_by"], "signed_mean_paired_change_within_metric_only")
        self.assertIn("metric.ranked_cohorts", self.js)
        self.assertNotIn("ranked.sort(", self.js)

    def test_original_rank_is_retained_when_filters_hide_cohorts(self):
        self.assertIn("item.rank", self.js)
        self.assertIn("Filters hide cohorts without recalculating or re-ranking them", self.html)
        self.assertIn("Original display order", self.js)

    def test_competition_ties_and_not_rankable_cohorts_are_preserved(self):
        self.assertIn("tie", self.js)
        for metric in self.payload["metrics"].values():
            self.assertGreaterEqual(len(metric["not_rankable_cohorts"]), 0)
            for cohort in metric["not_rankable_cohorts"]:
                self.assertEqual(cohort["eligible_pairs"], 0)
                self.assertEqual(cohort["not_rankable_reason"], "no_eligible_pairs")

    def test_sample_reuse_small_n_and_mean_median_context_are_visible(self):
        for token in ("sample_reuse_summary", "small_n_descriptive_only", "mean_median_sign_relation", "absolute_mean_median_gap"):
            self.assertIn(token, self.js)
        self.assertIn("Repeated exact Sample IDs", self.js)
        self.assertIn("Mean–median", self.html)

    def test_scientific_claim_guards_are_checked_and_displayed(self):
        self.assertFalse(self.payload["inferential_statistics_produced"])
        self.assertFalse(self.payload["causal_claims_produced"])
        self.assertFalse(self.payload["independent_sample_inference"])
        self.assertFalse(self.payload["cross_metric_ranking"])
        self.assertIn("causal_claims_produced !== false", self.js)
        self.assertIn("No causal attribution", self.js)
        self.assertIn("measurement_provenance_caveats?.o2", self.js)

    def test_dom_rendering_avoids_html_sinks_and_inline_handlers(self):
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("eval(", self.js)
        self.assertNotIn("onclick=", self.html.lower())
        self.assertIn("addEventListener", self.js)

    def test_record_evidence_covers_all_129_records_per_metric(self):
        for metric in self.payload["metrics"].values():
            keys = []
            for cohort in metric["ranked_cohorts"]:
                keys.extend(row["record_key"] for row in cohort["eligible_record_evidence"])
                keys.extend(row["record_key"] for row in cohort["excluded_record_evidence"])
            for cohort in metric["not_rankable_cohorts"]:
                keys.extend(row["record_key"] for row in cohort["excluded_record_evidence"])
            self.assertEqual(len(keys), 129)
            self.assertEqual(len(set(keys)), 129)

    def test_responsive_layout_is_declared(self):
        self.assertIn(".psi25-findings-controls", self.css)
        self.assertIn(".psi25-findings-evidence-summary", self.css)
        self.assertIn("@media(max-width:600px)", self.css)


if __name__ == "__main__":
    unittest.main()
