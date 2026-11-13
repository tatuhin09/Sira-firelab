from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "firelab_site"
HTML = (SITE / "index.html").read_text(encoding="utf-8")
APP = (SITE / "app.js").read_text(encoding="utf-8")
CSS = (SITE / "styles.css").read_text(encoding="utf-8")


class FireLabM42FrontendTests(unittest.TestCase):
    def test_approved_investigation_selector_is_present_and_accessible(self):
        self.assertIn('id="investigation-select"', HTML)
        self.assertIn('for="investigation-select"', HTML)
        self.assertIn('aria-label="Select the registered investigation for Ask SIRA"', HTML)

    def test_selector_contains_only_registered_choices_plus_auto(self):
        block = HTML.split('id="investigation-select"', 1)[1].split("</select>", 1)[0]
        values = re.findall(r'<option\s+value="([^"]+)"', block)
        self.assertEqual(values, ["auto", "psi69-flex-v5", "psi25-bass-ii-v4"])

    def test_api_request_transmits_investigation_id(self):
        self.assertIn('investigation_id: normalizeInvestigationId(investigationId, "psi69-flex-v5")', APP)
        self.assertIn('async function requestAssistantAnswer(question, conversationId, investigationId', APP)

    def test_legacy_history_defaults_to_psi69(self):
        self.assertIn('normalizeInvestigationId(item?.investigationId, "psi69-flex-v5")', APP)

    def test_conversation_persists_investigation_scope(self):
        self.assertIn('investigationId: normalizeInvestigationId($("#investigation-select")?.value, "auto")', APP)
        self.assertIn('version: 1, activeConversationId, conversations:', APP)

    def test_resolved_auto_route_locks_conversation_scope(self):
        self.assertIn('const resolvedInvestigationId = normalizeInvestigationId(answer.investigationId, "")', APP)
        self.assertIn('target.investigationId = resolvedInvestigationId', APP)

    def test_changing_scope_does_not_mix_existing_conversation(self):
        self.assertIn('if (active?.messages?.length) {\n    // A conversation is investigation-scoped.', APP)
        self.assertIn('activeConversationId = null;', APP)

    def test_metric_specific_and_research_question_scopes_are_supported(self):
        self.assertIn('"cohort-evidence", "research-questions"', APP)

    def test_normalizer_preserves_all_m42_structured_fields(self):
        for field in ("recordRefs", "citations", "claimReferences", "researchQuestions", "artifactHashes", "metricSummary", "investigationId", "metric"):
            self.assertIn(field, APP)

    def test_metric_summary_keeps_o2_co2_co_separate(self):
        self.assertIn('Object.freeze(["o2", "co2", "co"])', APP)
        self.assertIn('for (const metric of PSI25_METRIC_ORDER)', APP)
        self.assertIn('O₂, CO₂ and CO remain separate measurement scopes', APP)

    def test_canonical_record_keys_are_bounded_and_validated(self):
        self.assertIn(r'answer.recordRefs.filter((value) => typeof value === "string" && value.length <= 200 && !/[\u0000-\u001f\u007f]/.test(value)).slice(0, 60)', APP)

    def test_citations_are_linked_only_to_https_nasa_psi_host(self):
        self.assertIn('url.protocol === "https:" && url.hostname === "psi.nasa.gov"', APP)
        self.assertIn('link.rel = "noopener noreferrer"', APP)

    def test_claims_questions_citations_and_hashes_have_renderers(self):
        for cls in ("answer-claims", "answer-research-questions", "answer-citations", "answer-artifact-hashes", "answer-record-refs"):
            self.assertIn(cls, APP)

    def test_structured_answer_rendering_uses_dom_text_not_html_injection(self):
        start = APP.index("function makeStructuredAnswerDetails(answer)")
        end = APP.index("function handleInvestigationSelectionChange()", start)
        renderer = APP[start:end]
        self.assertIn("document.createElement", renderer)
        self.assertIn("textContent", renderer)
        self.assertNotIn("innerHTML", renderer)

    def test_psi25_records_are_never_rebound_to_psi69_flex_table(self):
        self.assertIn('answer.investigationId === "psi25-bass-ii-v4"', APP)
        self.assertIn("BASS-II values are not rebound to the PSI-69 FLEX table", APP)

    def test_styles_cover_selector_and_structured_evidence(self):
        for selector in (".investigation-control", ".answer-metric-summary", ".answer-citations", ".answer-claim-card"):
            self.assertIn(selector, CSS)

    def test_evidence_rail_tracks_selected_investigation(self):
        self.assertIn('function updateAskEvidenceContext(value)', APP)
        self.assertIn('"NASA BASS-II"', APP)
        self.assertIn('"NASA FLEX"', APP)
        self.assertIn('"129"', APP)
        self.assertIn('assistant-evidence-title', HTML)
        self.assertIn('assistant-record-label', HTML)

    def test_welcome_prompts_follow_selected_investigation(self):
        self.assertIn('"Show O₂ ranking in BASS-II"', APP)
        self.assertIn('"List BASS-II research questions"', APP)
        self.assertIn('button.dataset.prompt = prompt', APP)

    def test_server_session_and_same_origin_request_contract_remain(self):
        self.assertIn('fetch("/api/session"', APP)
        self.assertIn('fetch("/api/assistant/ask"', APP)
        self.assertIn('"X-FireLab-Session": token', APP)
        self.assertIn('credentials: "same-origin"', APP)


if __name__ == "__main__":
    unittest.main()
