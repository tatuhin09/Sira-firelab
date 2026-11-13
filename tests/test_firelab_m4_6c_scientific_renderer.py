from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "firelab_site" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "firelab_site" / "styles.css").read_text(encoding="utf-8")


class FireLabM46CScientificRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start = APP.index("function renderResearchSynthesisReceipt(packet, context)")
        end = APP.index("async function submitResearchSynthesis(event)", start)
        cls.renderer = APP[start:end]

    def test_all_packet_sections_are_rendered(self):
        for marker in (
            'appendSection("Synthesis packet"',
            'appendSection("Independent scientific verification"',
            'appendSection("Verified dataset claims"',
            'appendSection("Scholarly literature discovery"',
            'appendSection("Deterministic synthesis and evidence separation"',
            'appendSection("Mission research interpretation"',
            'appendSection("Verification boundaries"',
            'appendSection("Packet limitations"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.renderer)

    def test_dataset_claim_fields_and_lineage_are_rendered(self):
        for field in (
            "dataset_claims", "claim.claim_id", "claim.claim_type", "claim.statement",
            "claim.result", "claim.metric", "claim.unit", "claim.cohort",
            "claim.evidence_references", "claim.record_lineage", "claim.quality_dimensions",
            "claim.limitations", "claim.interpretation_status",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.renderer)

    def test_claim_and_paper_collections_are_bounded(self):
        self.assertIn("dataset_claims.slice(0, 30)", self.renderer)
        self.assertIn("literature.sources.slice(0, 3)", self.renderer)
        self.assertIn("values.slice(0, maximumItems)", self.renderer)

    def test_verification_counts_are_rendered(self):
        for field in (
            "verification.status", "verification.check_count",
            "verification.passed_check_count", "verification.failed_check_count",
            "verification.unverifiable_check_count", "verification.claim_result_count",
        ):
            self.assertIn(field, self.renderer)

    def test_literature_metadata_and_abstract_are_rendered(self):
        for field in (
            "literature.query", "literature.state", "literature.retrieved_at",
            "literature.providers", "literature.partial", "source.title",
            "source.authors", "source.year", "source.doi", "source.provider",
            "source.published_date", "source.matched_terms", "source.abstract",
            "source.claim_support_status",
        ):
            with self.subTest(field=field):
                self.assertIn(field, self.renderer)

    def test_external_links_require_https_and_reject_credentials(self):
        self.assertIn('parsed.protocol !== "https:"', self.renderer)
        self.assertIn("parsed.username || parsed.password", self.renderer)
        self.assertIn('link.rel = "noopener noreferrer"', self.renderer)
        self.assertIn('link.target = "_blank"', self.renderer)

    def test_doi_link_uses_validated_doi_shape(self):
        self.assertIn(r"/^10\.\d{4,9}\/\S+$/i.test(doi)", self.renderer)
        self.assertIn('const doiUrl = `https://doi.org/${encodeURIComponent(doi).replace(/%2F/gi, "/")}`;', self.renderer)
        self.assertIn("appendExternalLink(card, `Open DOI: ${doi}`, doiUrl);", self.renderer)

    def test_synthesis_boundaries_are_explicit(self):
        for field in (
            "synthesis.generated_with_model", "synthesis.model_synthesis_status",
            "synthesis.claim_to_literature_links", "synthesis.cross_source_support_status",
            "synthesis.literature_verifies_nasa_measurements",
            "synthesis.cross_investigation_pooling_performed",
            "synthesis.causal_inference_performed",
            "mission.mission_transferability", "mission.operational_safety_conclusion",
        ):
            self.assertIn(field, self.renderer)

    def test_all_dynamic_values_use_text_content_and_safe_dom_apis(self):
        self.assertIn("node.textContent = safeText(value, maximum)", self.renderer)
        self.assertIn("link.textContent = label", self.renderer)
        self.assertIn("host.replaceChildren()", self.renderer)
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.renderer)

    def test_result_host_is_replaced_before_render(self):
        self.assertLess(self.renderer.index('host.replaceChildren()'), self.renderer.index('appendSection("Synthesis packet"'))

    def test_mobile_layout_rules_exist(self):
        self.assertIn(".research-synthesis-section", CSS)
        self.assertIn(".research-synthesis-facts", CSS)
        self.assertIn("@media(max-width:600px){.research-synthesis-section", CSS)


if __name__ == "__main__":
    unittest.main()
