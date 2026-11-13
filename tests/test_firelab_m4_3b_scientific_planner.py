from dataclasses import replace
from pathlib import Path
import unittest

from firelab_service.evidence_registry import load_evidence_registry
from firelab_service.multi_investigation import (
    AUTO_ID, PSI25_ID, PSI69_ID, MultiInvestigationEvidenceAssistant,
)
from firelab_service.scientific_planner import (
    PLAN_SCHEMA, ScientificPlan, build_scientific_plan,
    classify_psi69_intent, metrics_in, validate_scientific_plan,
    validate_scientific_plan_for_dispatch,
)

ROOT = Path(__file__).resolve().parents[1]


class FireLabM43BScientificPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_evidence_registry(ROOT)
        cls.assistant = MultiInvestigationEvidenceAssistant(cls.registry)

    def plan(self, question, scope=PSI69_ID):
        return build_scientific_plan(question, scope)

    def ask(self, question, scope=PSI69_ID):
        return self.assistant.ask(question, conversation_id="m43b-plan-test", investigation_id=scope)

    def test_psi69_dataset_snapshot_plan_matches_legacy_operation_contract(self):
        plan = self.plan("Summarize the FLEX dataset")
        self.assertEqual((plan.decision, plan.resolved_investigation, plan.intent,
                          plan.operation_id, plan.data_scope),
                         ("execute", PSI69_ID, "dataset_summary", "flex.dataset.snapshot", "all-records"))
        self.assertIn("psi69.records", plan.evidence_requirements)

    def test_psi69_outcome_plan_is_descriptive_and_not_causal(self):
        plan = self.plan("Show outcome counts by fuel")
        self.assertEqual(plan.operation_id, "flex.outcomes.by_fuel")
        self.assertIn("no_causal_inference", plan.constraint_codes)
        self.assertIn("no_safety_ranking", plan.constraint_codes)

    def test_psi69_burning_rate_plan_requires_exact_finite_values(self):
        plan = self.plan("Summarize the burning rate")
        self.assertEqual((plan.operation_id, plan.data_scope),
                         ("flex.burning_rate.exact_by_fuel", "exact-burning-rate"))
        self.assertIn("exact_finite_values_only", plan.constraint_codes)
        self.assertIn("psi69.quality_report", plan.evidence_requirements)

    def test_psi69_quality_plan_preserves_quality_categories(self):
        plan = self.plan("What should I know about data quality?")
        self.assertEqual((plan.intent, plan.operation_id, plan.data_scope),
                         ("data_quality", "flex.measurement_quality", "quality-summary"))
        self.assertIn("no_imputation", plan.constraint_codes)

    def test_psi69_oxygen_plan_records_fixed_conditions_and_overlap(self):
        plan = self.plan("Compare oxygen conditions")
        self.assertEqual((plan.operation_id, plan.data_scope),
                         ("flex.oxygen_cohort_sensitivity", "selected-records"))
        for code in ("fixed_pressure_750_770_mmhg", "source_co_zero", "helium_zero",
                     "overlapping_cohorts", "descriptive_not_causal"):
            self.assertIn(code, plan.constraint_codes)

    def test_auto_defaults_to_psi69_when_no_investigation_is_named(self):
        plan = self.plan("Summarize the dataset", AUTO_ID)
        self.assertEqual(plan.resolved_investigation, PSI69_ID)

    def test_auto_routes_explicit_bass_ii_to_psi25(self):
        plan = self.plan("Summarize PSI-25 BASS-II", AUTO_ID)
        self.assertEqual((plan.resolved_investigation, plan.operation_id),
                         (PSI25_ID, "psi25.bass_ii.v4.snapshot"))

    def test_psi25_snapshot_keeps_metrics_separate(self):
        plan = self.plan("Summarize BASS-II dataset", PSI25_ID)
        self.assertEqual((plan.intent, plan.data_scope, plan.metric),
                         ("psi25_snapshot", "all-records", ""))
        self.assertIn("metrics_kept_separate", plan.constraint_codes)
        self.assertIn("psi25.evidence_synthesis", plan.evidence_requirements)

    def test_psi25_metric_insight_plan_maps_o2_co2_and_co(self):
        expected = {
            "Show O2 findings in BASS-II": ("o2", "psi25.bass_ii.v4.o2.insights"),
            "Show CO2 findings in BASS-II": ("co2", "psi25.bass_ii.v4.co2.insights"),
            "Show CO findings in BASS-II": ("co", "psi25.bass_ii.v4.co.insights"),
        }
        for question, pair in expected.items():
            with self.subTest(question=question):
                plan = self.plan(question, PSI25_ID)
                self.assertEqual((plan.metric, plan.operation_id), pair)
                self.assertEqual(plan.data_scope, "cohort-evidence")
                self.assertIn("metric_isolation", plan.constraint_codes)

    def test_psi25_metric_ranking_plan_uses_registered_rank_operation(self):
        plan = self.plan("Show O2 ranking in BASS-II", PSI25_ID)
        self.assertEqual((plan.intent, plan.operation_id),
                         ("psi25_metric_ranking", "psi25.bass_ii.v4.o2.ranking"))
        self.assertIn("precomputed_artifacts_only", plan.constraint_codes)

    def test_psi25_metric_research_questions_use_synthesis_only(self):
        plan = self.plan("List oxygen research questions for BASS-II", PSI25_ID)
        self.assertEqual((plan.intent, plan.metric, plan.data_scope),
                         ("psi25_research_questions", "o2", "research-questions"))
        self.assertEqual(plan.evidence_requirements, ("psi25.evidence_synthesis",))

    def test_dispatch_allowlist_accepts_each_metric_specific_research_question_operation(self):
        cases = (
            ("List oxygen research questions for BASS-II", "o2"),
            ("List CO2 research questions for BASS-II", "co2"),
            ("List carbon monoxide research questions for BASS-II", "co"),
        )
        for question, metric in cases:
            with self.subTest(metric=metric):
                plan = self.plan(question, PSI25_ID)
                validated = validate_scientific_plan_for_dispatch(plan, question)
                self.assertTrue(validated.execution_allowed)
                self.assertEqual(validated.metric, metric)
                self.assertEqual(
                    validated.operation_id,
                    f"psi25.bass_ii.v4.{metric}.research_questions",
                )
                self.assertEqual(validated.evidence_requirements, ("psi25.evidence_synthesis",))

    def test_live_metric_specific_research_question_operations_execute_from_verified_synthesis(self):
        cases = (
            ("List oxygen research questions for BASS-II", "o2"),
            ("List CO2 research questions for BASS-II", "co2"),
            ("List carbon monoxide research questions for BASS-II", "co"),
        )
        for question, metric in cases:
            with self.subTest(metric=metric):
                answer = self.ask(question, PSI25_ID)
                expected_operation = f"psi25.bass_ii.v4.{metric}.research_questions"
                self.assertEqual(answer["status"], "completed")
                self.assertEqual(answer["metric"], metric)
                self.assertEqual(answer["dataScope"], "research-questions")
                self.assertEqual(answer["analysisId"], expected_operation)
                self.assertEqual(answer["scientificPlan"]["operationId"], expected_operation)
                self.assertEqual(
                    answer["scientificPlan"]["evidenceRequirements"],
                    ["psi25.evidence_synthesis"],
                )
                self.assertTrue(answer["researchQuestions"])

    def test_psi25_all_research_questions_remain_a_separate_operation(self):
        plan = self.plan("List BASS-II research questions", PSI25_ID)
        self.assertEqual(plan.operation_id, "psi25.bass_ii.v4.research_questions")
        self.assertEqual(plan.metric, "")

    def test_cross_investigation_request_abstains_before_execution(self):
        plan = self.plan("Compare PSI-69 FLEX with PSI-25 BASS-II", AUTO_ID)
        self.assertEqual((plan.decision, plan.reason_codes, plan.data_scope),
                         ("abstain", ("cross_investigation",), "none"))
        self.assertFalse(plan.execution_allowed)

    def test_selected_scope_conflict_abstains_before_execution(self):
        plan = self.plan("Summarize PSI-25 BASS-II", PSI69_ID)
        self.assertEqual((plan.decision, plan.reason_codes, plan.resolved_investigation),
                         ("abstain", ("investigation_context_conflict",), PSI69_ID))

    def test_unknown_investigation_fails_closed(self):
        plan = self.plan("Summarize BASS-II", "private-sira-core")
        self.assertEqual((plan.decision, plan.reason_codes, plan.operation_id),
                         ("abstain", ("unknown_investigation",), ""))

    def test_psi69_safety_request_abstains_without_operation(self):
        plan = self.plan("Which fuel is safer?")
        self.assertEqual((plan.decision, plan.intent, plan.operation_id, plan.data_scope),
                         ("abstain", "safety_or_causality", "", "none"))

    def test_psi25_safety_guard_precedes_cross_metric_guard(self):
        plan = self.plan("Which is safer, O2 or CO2, in BASS-II?", PSI25_ID)
        self.assertEqual(plan.reason_codes, ("safety_or_causality",))

    def test_psi25_cross_metric_request_abstains(self):
        plan = self.plan("Compare oxygen and CO2 changes in BASS-II", PSI25_ID)
        self.assertEqual((plan.decision, plan.intent, plan.operation_id),
                         ("abstain", "cross_metric_comparison", ""))
        self.assertIn("no_cross_metric_pooling", plan.constraint_codes)

    def test_unsupported_requests_abstain_without_evidence_selection(self):
        for question, scope in (("Tell me a joke", PSI69_ID),
                                ("Tell me a joke about BASS-II", PSI25_ID)):
            with self.subTest(question=question):
                plan = self.plan(question, scope)
                self.assertEqual((plan.decision, plan.operation_id, plan.evidence_requirements),
                                 ("abstain", "", ()))

    def test_psi69_classifier_precedence_is_preserved(self):
        self.assertEqual(classify_psi69_intent("Which fuel is safer and what is its oxygen level?"),
                         "safety_or_causality")
        self.assertEqual(classify_psi69_intent("What should I know about data quality?"),
                         "data_quality")

    def test_metric_detection_keeps_co_separate_from_co2(self):
        self.assertEqual(metrics_in("O2, CO2 and CO findings"), ["o2", "co2", "co"])
        self.assertEqual(metrics_in("CO2 findings"), ["co2"])

    def test_plan_serialization_is_versioned_and_contains_no_paths_or_urls(self):
        plan = self.plan("Show O2 ranking in BASS-II", PSI25_ID)
        payload = plan.as_dict()
        self.assertEqual(payload["schema"], PLAN_SCHEMA)
        self.assertEqual(payload["plannerVersion"], 1)
        rendered = repr(payload).casefold()
        self.assertNotIn("/home/", rendered)
        self.assertNotIn("https://", rendered)
        self.assertTrue(payload["executionAllowed"])

    def test_plan_is_immutable_and_serialization_returns_fresh_lists(self):
        plan = self.plan("Show O2 ranking in BASS-II", PSI25_ID)
        public = plan.as_dict()
        public["constraintCodes"].append("tampered")
        self.assertNotIn("tampered", plan.constraint_codes)
        self.assertIsInstance(plan, ScientificPlan)

    def test_execution_validation_rejects_a_tampered_operation(self):
        plan = self.plan("Summarize the FLEX dataset", PSI69_ID)
        tampered = replace(plan, operation_id="private.sira.operation")
        with self.assertRaises(ValueError):
            validate_scientific_plan(tampered, "Summarize the FLEX dataset")

    def test_execution_validation_rejects_a_question_plan_mismatch(self):
        plan = self.plan("Summarize the FLEX dataset", PSI69_ID)
        with self.assertRaises(ValueError):
            validate_scientific_plan(plan, "Show outcome counts by fuel")

    def test_live_psi69_answer_contains_a_plan_matching_the_executed_analysis(self):
        answer = self.ask("Show outcome counts by fuel", PSI69_ID)
        self.assertEqual(answer["scientificPlan"]["operationId"], answer["analysisId"])
        self.assertEqual(answer["scientificPlan"]["dataScope"], answer["dataScope"])
        self.assertEqual(answer["sampleSize"], 274)

    def test_live_psi25_answer_contains_a_plan_matching_the_executed_analysis(self):
        answer = self.ask("Show O2 ranking in BASS-II", PSI25_ID)
        self.assertEqual(answer["scientificPlan"]["operationId"], answer["analysisId"])
        self.assertEqual(answer["scientificPlan"]["metric"], answer["metric"])
        self.assertEqual(answer["scientificPlan"]["dataScope"], answer["dataScope"])

    def test_live_abstention_exposes_plan_without_changing_event_contract(self):
        answer = self.ask("Compare PSI-69 FLEX with PSI-25 BASS-II", AUTO_ID)
        self.assertEqual(answer["scientificPlan"]["decision"], "abstain")
        self.assertEqual([event["type"] for event in answer["events"]],
                         ["turn.started", "answer.abstained"])
        self.assertEqual(answer["dataScope"], "none")


if __name__ == "__main__":
    unittest.main()
