from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "firelab_site" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "firelab_site" / "styles.css").read_text(encoding="utf-8")


class FireLabM43B2ScientificPlanFrontendTests(unittest.TestCase):
    def test_plan_schema_version_is_checked(self):
        start = APP.index("function normalizeScientificPlan(value)")
        end = APP.index("function normalizeStructuredAnswerFields(answer)", start)
        helper = APP[start:end]
        self.assertIn('value.schema !== "sira.firelab.scientific_plan.v1"', helper)
        self.assertIn("value.plannerVersion !== 1", helper)

    def test_plan_investigations_are_restricted_to_registered_ids(self):
        start = APP.index("function normalizeScientificPlan(value)")
        end = APP.index("function normalizeStructuredAnswerFields(answer)", start)
        helper = APP[start:end]
        self.assertIn("APPROVED_INVESTIGATION_IDS.includes(requestedInvestigation)", helper)
        self.assertIn("REGISTERED_INVESTIGATION_IDS.includes(resolvedInvestigation)", helper)

    def test_plan_operations_use_an_exact_operation_map(self):
        self.assertIn("const SCIENTIFIC_PLAN_OPERATION_MAP = Object.freeze({", APP)
        for operation in (
            "flex.dataset.snapshot", "flex.outcomes.by_fuel",
            "flex.burning_rate.exact_by_fuel", "flex.measurement_quality",
            "flex.oxygen_cohort_sensitivity", "psi25.bass_ii.v4.snapshot",
            "psi25.bass_ii.v4.research_questions",
        ):
            self.assertIn(f'"{operation}"', APP)
        for metric in ("o2", "co2", "co"):
            for suffix in ("insights", "ranking", "research_questions"):
                self.assertIn(f'"psi25.bass_ii.v4.{metric}.{suffix}"', APP)

    def test_operation_investigation_metric_and_scope_must_match(self):
        start = APP.index("function normalizeScientificPlan(value)")
        end = APP.index("function normalizeStructuredAnswerFields(answer)", start)
        helper = APP[start:end]
        self.assertIn("const expected = SCIENTIFIC_PLAN_OPERATION_MAP[operationId]", helper)
        self.assertIn("expected.investigationId !== resolvedInvestigation", helper)
        self.assertIn("expected.metric !== metric", helper)
        self.assertIn("expected.dataScope !== dataScope", helper)

    def test_abstentions_cannot_carry_an_executable_operation(self):
        start = APP.index("function normalizeScientificPlan(value)")
        end = APP.index("function normalizeStructuredAnswerFields(answer)", start)
        helper = APP[start:end]
        self.assertIn('decision !== "execute" && decision !== "abstain"', helper)
        self.assertIn('operationId !== "" || dataScope !== "none"', helper)

    def test_evidence_requirements_are_allowlisted(self):
        start = APP.index("function normalizeScientificPlan(value)")
        end = APP.index("function normalizeStructuredAnswerFields(answer)", start)
        helper = APP[start:end]
        self.assertIn("SCIENTIFIC_PLAN_EVIDENCE_IDS.includes(item)", helper)
        self.assertIn('"psi69.source_manifest"', APP)
        self.assertIn('"psi25.evidence_synthesis"', APP)

    def test_plan_text_fields_are_bounded(self):
        start = APP.index("function normalizeScientificPlan(value)")
        end = APP.index("function normalizeStructuredAnswerFields(answer)", start)
        helper = APP[start:end]
        self.assertIn("item.length <= maxLength", helper)
        self.assertIn("value.explanation.slice(0, 700)", helper)
        self.assertIn("normalizeTextList(value.selectionRules, 8, 500)", helper)

    def test_scientific_plan_is_included_in_structured_normalization(self):
        start = APP.index("function normalizeStructuredAnswerFields(answer)")
        end = APP.index("function makeAnswerDisclosure", start)
        helper = APP[start:end]
        self.assertIn("scientificPlan: normalizeScientificPlan(answer.scientificPlan)", helper)

    def test_legacy_answers_without_plan_remain_supported(self):
        start = APP.index("function normalizeScientificPlan(value)")
        end = APP.index("function normalizeStructuredAnswerFields(answer)", start)
        helper = APP[start:end]
        self.assertIn("if (!value || typeof value !== \"object\" || Array.isArray(value)) return null", helper)
        self.assertIn("scientificPlan: normalizeScientificPlan(answer.scientificPlan)", APP)

    def test_plan_is_rendered_inside_structured_answer(self):
        start = APP.index("function makeStructuredAnswerDetails(answer)")
        end = APP.index("function makeTraceDataTable(answer)", start)
        renderer = APP[start:end]
        self.assertIn("makeScientificPlanDisclosure(answer.scientificPlan)", renderer)

    def test_renderer_displays_execution_and_abstention_states(self):
        start = APP.index("function makeScientificPlanDisclosure(plan)")
        end = APP.index("function makeStructuredAnswerDetails(answer)", start)
        renderer = APP[start:end]
        self.assertIn('plan.decision === "execute"', renderer)
        self.assertIn('"Abstained · no analysis run"', renderer)
        self.assertIn("plan.reasonCodes", renderer)

    def test_renderer_displays_registered_operation_and_evidence_plan(self):
        start = APP.index("function makeScientificPlanDisclosure(plan)")
        end = APP.index("function makeStructuredAnswerDetails(answer)", start)
        renderer = APP[start:end]
        for field in ("requestedInvestigation", "resolvedInvestigation", "intent", "metric", "operationId", "dataScope", "evidenceRequirements", "constraintCodes", "selectionRules", "explanation"):
            self.assertIn(f"plan.{field}", renderer)

    def test_plan_renderer_uses_dom_text_not_html_injection(self):
        start = APP.index("function makeScientificPlanDisclosure(plan)")
        end = APP.index("function makeStructuredAnswerDetails(answer)", start)
        renderer = APP[start:end]
        self.assertIn("document.createElement", renderer)
        self.assertIn("textContent", renderer)
        self.assertNotIn("innerHTML", renderer)

    def test_plan_styles_include_compact_and_mobile_layouts(self):
        self.assertIn(".answer-scientific-plan", CSS)
        self.assertIn(".answer-scientific-plan-facts", CSS)
        self.assertIn(".answer-scientific-plan-list", CSS)
        self.assertIn("@media(max-width:600px)", CSS)
        self.assertIn(".answer-scientific-plan-facts{grid-template-columns:1fr}", CSS)


if __name__ == "__main__":
    unittest.main()
