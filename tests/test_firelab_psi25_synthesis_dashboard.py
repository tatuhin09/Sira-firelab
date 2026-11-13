import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "firelab_site/index.html").read_text(encoding="utf-8")
JS = (ROOT / "firelab_site/psi25.js").read_text(encoding="utf-8")
CSS = (ROOT / "firelab_site/styles.css").read_text(encoding="utf-8")


class Psi25SynthesisDashboardTests(unittest.TestCase):
    def test_dashboard_is_inside_dedicated_bass_ii_page(self):
        start = INDEX.index('id="view-psi25"')
        end = INDEX.index('data-view="research"', start)
        self.assertIn('id="psi25-synthesis-panel"', INDEX[start:end])

    def test_local_versioned_synthesis_assets_are_declared(self):
        self.assertIn('evidence_synthesis_v1/evidence_synthesis.json', JS)
        self.assertIn('evidence_synthesis_v1/synthesis_manifest.json', JS)

    def test_synthesis_loads_only_after_findings_verification(self):
        success = JS.index('status.classList.add("is-verified");', JS.index("async function loadPsi25Findings"))
        call = JS.index("await loadPsi25Synthesis();", success)
        self.assertLess(success, call)

    def test_synthesis_bytes_and_manifest_are_sha256_verified(self):
        self.assertIn('crypto.subtle.digest("SHA-256", bytes)', JS)
        self.assertIn('digest !== output.sha256 || bytes.byteLength !== output.bytes', JS)

    def test_findings_and_paired_analysis_lineage_are_compared(self):
        self.assertIn('source_artifacts?.findings_ranking?.sha256 !== findingsBundle?.sha256', JS)
        self.assertIn('source_artifacts?.paired_measurement_analysis?.sha256 !== pairedAnalysisHash', JS)

    def test_three_metrics_are_rendered_separately(self):
        self.assertIn('payload.metrics?.[key]', JS)
        self.assertIn('["o2", "co2", "co"]', JS)
        self.assertIn('insight_cards', JS)

    def test_all_insight_and_question_counts_are_guarded(self):
        self.assertIn('payload.insight_card_count !== 54', JS)
        self.assertIn('manifestData.research_question_count !== 146', JS)
        self.assertIn('payload.research_questions?.length !== 146', JS)

    def test_evidence_coverage_is_verified_against_source_records(self):
        self.assertIn('seen.size !== records.length', JS)
        self.assertIn('byRecordKey.has(row.record_key)', JS)
        self.assertIn('pairedMetric.record_level_audit', JS)

    def test_not_rankable_cohorts_are_never_assigned_fake_statistics(self):
        self.assertIn('card.interpretation_status === "not_rankable"', JS)
        self.assertIn('card.statistics !== undefined', JS)
        self.assertIn('No eligible exact paired observations', JS)

    def test_filters_do_not_recalculate_or_re_rank(self):
        self.assertIn('function synthesisMatches(card)', JS)
        self.assertIn('(metric.insight_cards || []).filter(synthesisMatches)', JS)
        self.assertIn('Filters hide or show precomputed insight cards', INDEX)
        self.assertNotIn('sort(', JS[JS.index('function renderPsi25Synthesis()'):JS.index('function initializeSynthesisFilters()')])

    def test_mean_median_mixed_direction_and_flags_are_displayed(self):
        for token in ['card.direction_counts', 'card.absolute_mean_median_gap', 'card.distribution', 'card.flags']:
            self.assertIn(token, JS)

    def test_research_questions_include_card_and_global_questions(self):
        self.assertIn('card.research_questions', JS)
        self.assertIn('question.metric === "all"', JS)
        self.assertIn('psi25-synthesis-global-questions', INDEX)

    def test_o2_sample_reuse_and_no_safety_claims_are_visible(self):
        for token in ['measurement_provenance_caveats?.o2', 'sample_reuse_summary', 'operational_fire_safety_recommendations', 'independent_sample_inference']:
            self.assertIn(token, JS)
        self.assertIn('do not qualify materials', JS)

    def test_dom_uses_text_nodes_without_html_sinks_or_external_dependencies(self):
        section = JS[JS.index('let synthesisBundle'):JS.index('async function loadPsi25Findings')]
        self.assertIn('textContent', section)  # messages are assigned through DOM text
        self.assertNotIn('innerHTML', section)
        self.assertNotIn('insertAdjacentHTML', section)
        self.assertNotIn('eval(', section)
        self.assertNotIn('https://', section)

    def test_source_record_buttons_link_to_existing_canonical_record_details(self):
        self.assertIn('data-synthesis-record-key', JS)
        self.assertIn('byRecordKey.get(button.dataset.synthesisRecordKey)', JS)
        self.assertIn('renderRecordDetails(record)', JS)

    def test_responsive_styles_are_present(self):
        self.assertIn('.psi25-synthesis-card', CSS)
        self.assertIn('@media(max-width:1050px)', CSS)
        self.assertIn('@media(max-width:600px)', CSS)

    def test_dashboard_is_local_and_read_only(self):
        self.assertIn('read-only', INDEX)
        self.assertIn('deterministic', INDEX.lower())
        self.assertNotIn('fetch("https://', JS)


if __name__ == "__main__":
    unittest.main()
