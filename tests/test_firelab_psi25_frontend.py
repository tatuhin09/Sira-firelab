from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "firelab_site"


class FireLabPsi25FrontendTests(unittest.TestCase):
    def test_bass_ii_route_is_separate_from_psi69_data_explorer(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        app = (SITE / "app.js").read_text(encoding="utf-8")
        self.assertIn('href="#psi25" data-page="psi25"', html)
        self.assertIn('id="view-psi25" data-view="psi25"', html)
        self.assertIn('psi25: "BASS-II Explorer"', app)
        self.assertIn('href="#data" data-page="data"', html)
        self.assertIn('fetch("data/records.json"', app)

    def test_psi25_module_and_canonical_bundle_are_local_deferred_assets(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        source = (SITE / "psi25.js").read_text(encoding="utf-8")
        self.assertRegex(html, r'<script\s+src="psi25\.js"\s+defer></script>')
        for filename in ("canonical_records.json", "quality_report.json", "canonical_manifest.json"):
            self.assertIn(f"{filename}", source)
        self.assertIn('fetch(path, { cache: "no-store" })', source)
        self.assertNotRegex(source, r'fetch\(["\']https?://')

    def test_rendering_uses_dom_text_nodes_not_html_sinks(self):
        source = (SITE / "psi25.js").read_text(encoding="utf-8")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("element.textContent = String(text)", source)
        self.assertIn("body.replaceChildren()", source)

    def test_raw_measurement_states_and_aggregation_eligibility_are_retained(self):
        source = (SITE / "psi25.js").read_text(encoding="utf-8")
        for token in ("measurement.raw", "measurement.status", "measurement.aggregation_eligible", "right_censored", "over_range_threshold_unspecified", "negative_numeric_requires_review", "numeric_scalar_steady_state_unverified", "single_gain_setting", "source_none", "sequence_or_note"):
            with self.subTest(token=token):
                self.assertIn(token, source)
        self.assertIn("OR remains right-censored", source)
        self.assertIn("Raw values and parser status are shown separately", source)

    def test_sample_reuse_does_not_merge_experiment_records(self):
        source = (SITE / "psi25.js").read_text(encoding="utf-8")
        self.assertIn("is_reused_exact_raw_id", source)
        self.assertIn("records remain distinct", source)
        self.assertIn("record_key", source)

    def test_no_inline_event_handlers_or_external_script_dependencies(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r'<script[^>]+src="https?://')
        source = (SITE / "psi25.js").read_text(encoding="utf-8")
        self.assertNotRegex(source, r'\bon(click|change|input)\s*=')


if __name__ == "__main__":
    unittest.main()
