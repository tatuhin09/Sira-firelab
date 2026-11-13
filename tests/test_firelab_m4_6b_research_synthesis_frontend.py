from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "firelab_site" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "firelab_site" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "firelab_site" / "styles.css").read_text(encoding="utf-8")


class FireLabM46BResearchSynthesisFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start = APP.index("function latestResearchSynthesisContext()")
        end = APP.index("async function submitResearchSynthesis(event)", start)
        cls.context_logic = APP[start:end]
        request_start = APP.index("function renderResearchSynthesisReceipt(packet, context)")
        request_end = APP.index("const INVESTIGATION_CONTEXTS = {", request_start)
        cls.request_logic = APP[request_start:request_end]

    def test_research_lab_has_explicit_user_triggered_panel(self):
        self.assertIn('id="research-synthesis-form"', HTML)
        self.assertIn('id="research-synthesis-query"', HTML)
        self.assertIn('id="research-synthesis-submit"', HTML)
        self.assertIn('id="research-synthesis-status"', HTML)
        self.assertIn('id="research-synthesis-results"', HTML)
        self.assertIn('disabled>Build research synthesis', HTML)

    def test_panel_is_inside_existing_research_lab(self):
        research_view = HTML[HTML.index('id="view-research"'):HTML.index('id="view-methods"')]
        self.assertIn('class="panel research-synthesis-panel"', research_view)
        self.assertIn('class="panel paper-search-panel"', research_view)

    def test_request_uses_existing_session_and_exact_endpoint(self):
        self.assertIn('const token = await assistantToken();', self.request_logic)
        self.assertIn('fetch("/api/research/synthesis"', self.request_logic)
        self.assertIn('"X-FireLab-Session": token', self.request_logic)
        self.assertIn('credentials: "same-origin"', self.request_logic)
        self.assertIn('cache: "no-store"', self.request_logic)

    def test_only_four_server_contract_fields_are_sent(self):
        payload = self.request_logic.split("body: JSON.stringify({", 1)[1].split("}),", 1)[0]
        for field in ("question:", "conversation_id:", "investigation_id:", "literature_query:"):
            self.assertIn(field, payload)
        self.assertNotIn("answer:", payload)
        self.assertNotIn("claimLedger", payload)

    def test_latest_assistant_answer_must_be_immediately_after_its_question(self):
        self.assertIn("const lastIndex = active.messages.length - 1", self.context_logic)
        self.assertIn('assistantMessage?.role !== "assistant"', self.context_logic)
        self.assertIn('userMessage?.role !== "user"', self.context_logic)
        self.assertIn('answer.status !== "completed"', self.context_logic)

    def test_only_registered_investigation_and_registered_operation_are_eligible(self):
        self.assertIn("REGISTERED_INVESTIGATION_IDS.includes(investigationId)", self.context_logic)
        self.assertIn("SCIENTIFIC_PLAN_OPERATION_MAP[analysisId]", self.context_logic)
        self.assertIn("operation.investigationId !== investigationId", self.context_logic)

    def test_research_question_operations_are_not_eligible_for_measurement_synthesis(self):
        self.assertIn('analysisId.endsWith("research_questions")', self.context_logic)

    def test_verified_claim_ledger_is_required_and_bound_to_answer(self):
        self.assertIn('ledger.ledgerStatus !== "verified_provenance"', self.context_logic)
        self.assertIn("ledger.investigationId !== investigationId", self.context_logic)
        self.assertIn("ledger.operationId !== analysisId", self.context_logic)

    def test_conversation_identifier_and_question_are_bounded(self):
        self.assertIn("question.length < 3 || question.length > 400", self.context_logic)
        self.assertIn(r"/^[A-Za-z0-9._-]{1,100}$/", self.context_logic)

    def test_response_schema_and_server_recomputation_are_checked(self):
        self.assertIn('payload.schema !== "sira.firelab.research_synthesis_response.v1"', self.request_logic)
        self.assertIn('packet.schema !== "sira.firelab.research_synthesis.v1"', self.request_logic)
        self.assertIn("datasetContext.investigation_id !== context.investigationId", self.request_logic)
        self.assertIn("datasetContext.operation_id !== context.analysisId", self.request_logic)

    def test_response_rejects_model_causality_pooling_and_literature_validation_flags(self):
        for check in (
            "packet.synthesis.generated_with_model !== false",
            "packet.synthesis.literature_verifies_nasa_measurements !== false",
            "packet.synthesis.cross_investigation_pooling_performed !== false",
            "packet.synthesis.causal_inference_performed !== false",
        ):
            self.assertIn(check, self.request_logic)

    def test_synthesis_is_not_started_automatically(self):
        self.assertIn('$("#research-synthesis-form").addEventListener("submit", submitResearchSynthesis);', APP)
        self.assertNotIn('fetch("/api/research/synthesis"', APP[:APP.index("async function submitResearchSynthesis(event)")])

    def test_chat_changes_refresh_synthesis_eligibility(self):
        self.assertIn("updateResearchSynthesisAvailability();", APP[APP.index("function renderActiveConversation()") : APP.index("function startNewConversation()")])
        self.assertIn("clearResearchSynthesisResult();", APP[APP.index("async function ask(question)") : APP.index("function latestResearchSynthesisContext()")])

    def test_rendering_uses_text_content_and_no_html_injection(self):
        self.assertIn("node.textContent = safeText(value, maximum);", self.request_logic)
        self.assertIn("host.replaceChildren()", self.request_logic)
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.request_logic)

    def test_panel_explains_external_query_and_scientific_boundaries(self):
        self.assertIn("Do not enter private information", HTML)
        self.assertIn("not validation of NASA measurements", HTML)
        self.assertIn("does not establish causality", HTML)

    def test_responsive_styles_exist(self):
        self.assertIn(".research-synthesis-panel", CSS)
        self.assertIn("@media(max-width:600px){.research-synthesis-panel", CSS)


if __name__ == "__main__":
    unittest.main()
