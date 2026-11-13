from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Psi25AnalysisDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "firelab_site/index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "firelab_site/psi25.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "firelab_site/styles.css").read_text(encoding="utf-8")
        cls.analysis_path = ROOT / "firelab_site/data/derived/psi25_bass_ii_v4/paired_analysis_v1/paired_measurement_analysis.json"
        cls.manifest_path = ROOT / "firelab_site/data/derived/psi25_bass_ii_v4/paired_analysis_v1/analysis_manifest.json"

    def test_dashboard_is_inside_dedicated_psi25_page(self):
        self.assertIn('id="psi25-analysis-title"', self.html)
        self.assertIn('id="view-psi25"', self.html)
        self.assertLess(self.html.index('id="psi25-analysis-title"'), self.html.index('id="psi25-table-title"'))

    def test_dashboard_loads_local_versioned_artifact(self):
        self.assertIn('paired_analysis_v1/paired_measurement_analysis.json', self.js)
        self.assertIn('paired_analysis_v1/analysis_manifest.json', self.js)
        self.assertIn('cache: "no-store"', self.js)

    def test_analysis_bytes_are_sha256_verified_before_render(self):
        self.assertIn('crypto.subtle.digest("SHA-256", bytes)', self.js)
        self.assertIn('digest !== derived.sha256', self.js)
        self.assertIn('renderPairedAnalysis();', self.js)

    def test_ui_reads_precomputed_statistics_without_recomputing_them(self):
        for token in ("stats.mean", "stats.median", "stats.minimum", "stats.maximum", "item.eligible_pairs"):
            self.assertIn(token, self.js)
        self.assertNotIn("delta_final_minus_initial =", self.js)
        self.assertNotIn("function calculateMean", self.js)
        self.assertNotIn("function calculateMedian", self.js)

    def test_cohort_filters_and_record_audit_are_present(self):
        for element_id in (
            "psi25-analysis-metric", "psi25-analysis-pi", "psi25-analysis-material",
            "psi25-analysis-restrictor", "psi25-analysis-audit-search", "psi25-analysis-audit",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn("currentAnalysisAuditRows", self.js)

    def test_small_n_and_sample_reuse_caveats_are_visible(self):
        self.assertIn("small_n_descriptive_only", self.js)
        self.assertIn("sample_reuse_caveat", self.js)
        self.assertIn("independent physical-sample n", self.js)
        self.assertIn("records_in_reused_exact_raw_id_groups", self.js)
        self.assertIn("No inferential statistics", self.html)

    def test_filtered_summary_counts_follow_selected_cohorts(self):
        self.assertIn("cohorts.reduce((sum, item) => sum + Number(item.eligible_pairs || 0)", self.js)
        self.assertIn("cohorts.reduce((sum, item) => sum + Number(item.excluded_pairs || 0)", self.js)
        self.assertNotIn('["ELIGIBLE PAIRS", counts.eligible_pairs', self.js)

    def test_o2_calibration_caveat_and_censored_co_boundary_are_visible(self):
        self.assertIn("measurement_provenance_caveats", self.js)
        self.assertIn("O₂ calibration limitation", self.js)
        self.assertIn("censored/over-range values", self.js)

    def test_dom_rendering_uses_text_nodes_without_html_sinks_or_external_chart_deps(self):
        self.assertIn('node("td"', self.js)
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("insertAdjacentHTML", self.js)
        self.assertNotIn("chart.js", self.html.lower())
        self.assertNotIn("echarts", self.html.lower())

    def test_production_analysis_artifacts_match_manifest(self):
        self.assertTrue(self.analysis_path.is_file())
        self.assertTrue(self.manifest_path.is_file())
        raw = self.analysis_path.read_bytes()
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        payload = json.loads(raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest["derived_output"]["sha256"])
        self.assertEqual(len(raw), manifest["derived_output"]["bytes"])
        self.assertEqual(payload["record_count"], 129)

    def test_css_has_responsive_analysis_layout(self):
        self.assertIn(".psi25-analysis-panel", self.css)
        self.assertIn(".psi25-analysis-controls", self.css)
        self.assertIn(".psi25-analysis-chart", self.css)
        self.assertIn("@media(max-width:600px)", self.css)


if __name__ == "__main__":
    unittest.main()
