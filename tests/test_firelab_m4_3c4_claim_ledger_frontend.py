from pathlib import Path
import unittest

APP = Path("firelab_site/app.js").read_text(encoding="utf-8")
CSS = Path("firelab_site/styles.css").read_text(encoding="utf-8")


class FireLabM43C4ClaimLedgerFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start = APP.index("function normalizeClaimLedger(answer)")
        end = APP.index("function makeClaimLedgerJsonPanel", start)
        cls.normalizer = APP[start:end]
        render_start = APP.index("function makeClaimLedgerJsonPanel")
        render_end = APP.index("function makeStructuredAnswerDetails(answer)", render_start)
        cls.renderer = APP[render_start:render_end]

    def test_claim_ledger_schema_and_version_are_checked(self):
        self.assertIn('raw.schema !== CLAIM_LEDGER_SCHEMA', self.normalizer)
        self.assertIn('raw.ledgerVersion !== 1', self.normalizer)

    def test_only_verified_provenance_status_is_renderable(self):
        self.assertIn('raw.ledgerStatus !== "verified_provenance"', self.normalizer)

    def test_abstained_answers_never_retain_a_ledger(self):
        self.assertIn('answer.status === "abstained"', self.normalizer)

    def test_investigation_context_must_match_answer(self):
        self.assertIn('investigationId !== responseInvestigation', self.normalizer)

    def test_scientific_plan_operation_and_scope_must_match(self):
        self.assertIn('plan.operationId !== operationId', self.normalizer)
        self.assertIn('plan.dataScope !== dataScope', self.normalizer)

    def test_claim_type_allowlist_exists(self):
        for value in ("source_table_count", "descriptive_summary", "measurement_quality_observation", "descriptive_cohort_finding", "observed_cohort_comparison"):
            self.assertIn(value, APP)

    def test_interpretation_status_allowlist_exists(self):
        for value in ("source_reported", "descriptive_only", "descriptive_with_limitations", "quality_observation"):
            self.assertIn(value, APP)

    def test_claim_ids_are_unique(self):
        self.assertIn("seenClaimIds.has(claimId)", self.normalizer)

    def test_claim_and_evidence_collection_limits_exist(self):
        self.assertIn("raw.claims.length > 30", self.normalizer)
        self.assertIn("row.evidenceReferences.length > 10", self.normalizer)

    def test_evidence_ids_and_sha256_are_validated(self):
        self.assertIn("CLAIM_LEDGER_EVIDENCE_REFERENCE_IDS.has(referenceId)", self.normalizer)
        self.assertIn("/^[a-f0-9]{64}$/", self.normalizer)

    def test_nested_values_are_bounded_and_score_like_fields_removed(self):
        self.assertIn("state.nodes > 2048", APP)
        self.assertIn("depth > 6", APP)
        self.assertIn("/(?:confidence|score|grade)/i", APP)

    def test_record_lineage_and_quality_dimensions_are_required(self):
        self.assertIn("row.recordLineage", self.normalizer)
        self.assertIn("row.qualityDimensions", self.normalizer)

    def test_claim_limitations_are_bounded(self):
        self.assertIn("row.limitations.length > 24", self.normalizer)
        self.assertIn("item.slice(0, 500)", self.normalizer)

    def test_json_panels_use_text_content(self):
        self.assertIn("pre.textContent = JSON.stringify(value, null, 2)", self.renderer)

    def test_claim_metric_and_unit_are_rendered(self):
        self.assertIn("claim.metric", self.renderer)
        self.assertIn("claim.unit", self.renderer)

    def test_evidence_hashes_and_lineage_are_rendered(self):
        self.assertIn("claim.evidenceReferences", self.renderer)
        self.assertIn("claim.recordLineage", self.renderer)
        self.assertIn("claim.qualityDimensions", self.renderer)

    def test_scientific_truth_boundary_is_visible(self):
        self.assertIn("NOT SCIENTIFIC TRUTH", self.renderer)
        self.assertIn("does not establish scientific truth, causality, independent replication, safety, or mission transferability", self.renderer)

    def test_shared_answer_renderer_attaches_ledger(self):
        self.assertIn("if (answer.claimLedger) root.append(makeClaimLedgerDisclosure(answer.claimLedger));", APP)

    def test_normalized_structured_fields_retain_ledger_for_history(self):
        self.assertIn("claimLedger: normalizeClaimLedger(answer)", APP)
        self.assertIn("...normalizeStructuredAnswerFields(answer)", APP)

    def test_legacy_claim_reference_renderer_remains(self):
        self.assertIn("if (answer.claimReferences?.length)", APP)
        self.assertIn('"answer-claims"', APP)

    def test_c4_viewer_does_not_use_inner_html(self):
        self.assertNotIn("innerHTML", self.normalizer + self.renderer)

    def test_mobile_layout_rules_exist(self):
        self.assertIn("@media (max-width: 700px)", CSS)
        self.assertIn(".answer-claim-ledger-metadata", CSS)

    def test_provenance_warning_styles_exist(self):
        self.assertIn(".answer-claim-ledger-warning", CSS)
        self.assertIn(".answer-claim-ledger-status", CSS)


if __name__ == "__main__":
    unittest.main()
