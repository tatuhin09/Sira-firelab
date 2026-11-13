"""Deterministic scientific intent planning for NASA FireLab evidence requests.

The planner selects only registered, reviewed evidence operations. It performs
no scientific calculations, data access, file resolution, network access, or
provider calls. Existing investigation-specific executors remain responsible
for deterministic calculations and verified artifact retrieval.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

PLAN_SCHEMA = "sira.firelab.scientific_plan.v1"
PLANNER_VERSION = 1
PSI69_ID = "psi69-flex-v5"
PSI25_ID = "psi25-bass-ii-v4"
AUTO_ID = "auto"
METRICS = ("o2", "co2", "co")
APPROVED_INVESTIGATIONS = frozenset({PSI69_ID, PSI25_ID})
APPROVED_REQUEST_SCOPES = frozenset({AUTO_ID, PSI69_ID, PSI25_ID})

_SAFETY = re.compile(
    r"\b(?:safe\w*|unsafe|risk\w*|danger\w*|hazard\w*|harm\w*|"
    r"caus\w*|effect\w*|predict\w*|recommend\w*|prevent\w*|protect\w*|"
    r"best fuel|worst fuel|suitab\w*|appropriat\w*|preferable|"
    r"should\s+(?:i|we|they)\s+(?:use|choose|select|avoid)|"
    r"should\s+be\s+(?:used|chosen|selected|avoided|recommended))\b", re.I
)
_PSI25 = re.compile(r"\b(?:psi\s*[- ]?25|bass\s*[- ]?ii)\b", re.I)
_PSI69 = re.compile(r"\b(?:psi\s*[- ]?69|flex)\b", re.I)
_METRIC = {
    "co2": re.compile(r"\b(?:co\s*2|co₂|carbon\s+dioxide)\b", re.I),
    "o2": re.compile(r"\b(?:o\s*2|o₂|oxygen)\b", re.I),
    "co": re.compile(r"\b(?:co|carbon\s+monoxide)\b", re.I),
}
_RANK = re.compile(r"\b(?:rank\w*|ranking|highest|lowest|top\s+\d+|ordered)\b", re.I)
_QUESTIONS = re.compile(r"\b(?:research\s+questions?|open\s+questions?|evidence\s+gaps?)\b", re.I)
_SUMMARY = re.compile(r"\b(?:summar\w*|overview|snapshot|dataset|records|findings?|insights?|patterns?)\b", re.I)


@dataclass(frozen=True)
class ScientificPlan:
    """Immutable, serializable plan for one normalized evidence question."""

    decision: str
    requested_investigation: str
    resolved_investigation: str
    intent: str
    metric: str
    operation_id: str
    data_scope: str
    evidence_requirements: tuple[str, ...]
    constraint_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    selection_rules: tuple[str, ...]
    explanation: str

    @property
    def execution_allowed(self) -> bool:
        return self.decision == "execute" and bool(self.operation_id)

    def as_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-safe public representation; never expose paths."""
        return {
            "schema": PLAN_SCHEMA,
            "plannerVersion": PLANNER_VERSION,
            "decision": self.decision,
            "executionAllowed": self.execution_allowed,
            "requestedInvestigation": self.requested_investigation,
            "resolvedInvestigation": self.resolved_investigation,
            "intent": self.intent,
            "metric": self.metric,
            "operationId": self.operation_id,
            "dataScope": self.data_scope,
            "evidenceRequirements": list(self.evidence_requirements),
            "constraintCodes": list(self.constraint_codes),
            "reasonCodes": list(self.reason_codes),
            "selectionRules": list(self.selection_rules),
            "explanation": self.explanation,
        }


def classify_psi69_intent(question: str) -> str:
    """Preserve the established FLEX classifier and its precedence exactly."""
    q = question.casefold()
    if _SAFETY.search(q):
        return "safety_or_causality"
    if re.search(r"\b(oxygen|o2|o₂)\b", q):
        return "oxygen_sensitivity"
    if re.search(r"\b(quality|missing|approximate|invalid|data flag|data issue|data quality)\b", q):
        return "data_quality"
    if re.search(r"\b(burning rate|burn rate|mm2/s|mm²/s|combustion rate)\b", q):
        return "burning_rate"
    if re.search(r"\b(outcome|test end|extinction|disruption|completion|fuel|methanol|heptane|compare|comparison)\b", q):
        return "outcomes_by_fuel"
    if re.search(r"\b(summar(?:y|ize|ise)|dataset|records|how many|what data|what is flex|overview)\b", q):
        return "dataset_summary"
    return "unsupported"


def resolve_investigation(question: str, requested: str) -> tuple[str | None, str | None]:
    """Preserve M4.2 investigation routing and conflict behavior."""
    has25, has69 = bool(_PSI25.search(question)), bool(_PSI69.search(question))
    if has25 and has69:
        return None, "cross_investigation"
    if requested == AUTO_ID:
        return (PSI25_ID if has25 else PSI69_ID), None
    if requested not in APPROVED_INVESTIGATIONS:
        return None, "unknown_investigation"
    if (requested == PSI69_ID and has25) or (requested == PSI25_ID and has69):
        return None, "investigation_context_conflict"
    return requested, None


def metrics_in(question: str) -> list[str]:
    """Return mentioned BASS-II metrics in the stable registered order."""
    return [metric for metric in METRICS if _METRIC[metric].search(question)]


_PSI69_SPECS: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "dataset_summary": (
        "flex.dataset.snapshot", "all-records",
        ("psi69.source_manifest", "psi69.records"),
        ("hash_verified_source", "registered_operation_only", "descriptive_counts_only", "no_imputation"),
        ("Use all retained records from the verified PSI-69 FLEX bundle.",
         "Count source-reported fuels and Test end categories; do not infer adjusted effects."),
    ),
    "outcomes_by_fuel": (
        "flex.outcomes.by_fuel", "all-records",
        ("psi69.records",),
        ("hash_verified_source", "registered_operation_only", "descriptive_only", "no_causal_inference", "no_safety_ranking"),
        ("Group all retained records by source-reported fuel.",
         "Count source-reported Test end categories without condition adjustment."),
    ),
    "burning_rate": (
        "flex.burning_rate.exact_by_fuel", "exact-burning-rate",
        ("psi69.records", "psi69.quality_report"),
        ("hash_verified_source", "registered_operation_only", "exact_finite_values_only", "exclude_approximate_and_missing", "descriptive_only"),
        ("Select only finite burning-rate values marked exact by the quality report.",
         "Group by source-reported fuel; report mean and sample standard deviation."),
    ),
    "data_quality": (
        "flex.measurement_quality", "quality-summary",
        ("psi69.quality_report",),
        ("hash_verified_source", "registered_operation_only", "quality_categories_separate", "no_imputation"),
        ("Read field-level exact, approximate, missing, and invalid counts.",
         "Preserve source flags; do not impute or recategorize measurements."),
    ),
    "oxygen_sensitivity": (
        "flex.oxygen_cohort_sensitivity", "selected-records",
        ("psi69.records", "psi69.quality_report"),
        ("hash_verified_source", "registered_operation_only", "fixed_pressure_750_770_mmhg", "source_co_zero", "helium_zero", "overlapping_cohorts", "descriptive_not_causal", "no_safety_ranking"),
        ("Hold pressure at 750–770 mmHg, source CO at 0, and helium at 0.",
         "Compare exact O2 = 0.21 with all exact oxygen values; cohorts overlap.",
         "Rank unadjusted observed outcome-share gaps; do not interpret them as oxygen effects."),
    ),
}


def _abstain_plan(requested: str, resolved: str, intent: str, metric: str,
                  reason: str, explanation: str, constraints: tuple[str, ...] = ()) -> ScientificPlan:
    return ScientificPlan(
        decision="abstain", requested_investigation=requested,
        resolved_investigation=resolved, intent=intent, metric=metric,
        operation_id="", data_scope="none", evidence_requirements=(),
        constraint_codes=constraints + ("no_source_selection", "no_analysis_execution"),
        reason_codes=(reason,),
        selection_rules=("Do not select source rows or execute a calculation.",),
        explanation=explanation,
    )


def build_scientific_plan(question: str, requested_investigation: object = PSI69_ID) -> ScientificPlan:
    """Resolve routing, scientific intent, registered evidence and constraints.

    ``question`` must already have passed ``normalize_question`` in the caller.
    This function is deterministic and side-effect free.
    """
    if not isinstance(question, str) or not question or len(question) > 400:
        raise ValueError("scientific planner requires a normalized question")
    requested = requested_investigation if isinstance(requested_investigation, str) else ""
    resolved, route_error = resolve_investigation(question, requested)

    if route_error == "cross_investigation":
        return _abstain_plan(requested, "", route_error, "", route_error,
            "The request names both registered investigations, whose experimental designs and evidence contracts cannot be pooled.",
            ("no_cross_investigation_pooling",))
    if route_error == "investigation_context_conflict":
        return _abstain_plan(requested, requested, route_error, "", route_error,
            "The question names an investigation different from the selected conversation scope.",
            ("selected_scope_must_match_question",))
    if route_error or resolved is None:
        return _abstain_plan(requested, "", "unknown_investigation", "", "unknown_investigation",
            "Only PSI-69 FLEX Version 5 and PSI-25 BASS-II Study Version 4 are registered.",
            ("approved_investigation_allowlist_only",))

    if resolved == PSI69_ID:
        intent = classify_psi69_intent(question)
        if intent == "safety_or_causality":
            return _abstain_plan(requested, resolved, intent, "", intent,
                "The approved FLEX analyses cannot establish safety rankings, causal effects, predictions, or operational recommendations.",
                ("no_causal_or_safety_claim", "registered_operation_only"))
        if intent == "unsupported":
            return _abstain_plan(requested, resolved, intent, "", intent,
                "No registered PSI-69 analysis matches this request.",
                ("registered_operation_only",))
        operation, scope, evidence, constraints, rules = _PSI69_SPECS[intent]
        return ScientificPlan(
            decision="execute", requested_investigation=requested,
            resolved_investigation=resolved, intent=intent, metric="",
            operation_id=operation, data_scope=scope,
            evidence_requirements=evidence, constraint_codes=constraints,
            reason_codes=("registered_analysis_match",), selection_rules=rules,
            explanation=f"Selected the registered PSI-69 operation {operation} for the {intent} request.",
        )

    # BASS-II rules intentionally preserve the existing safety-before-metric
    # precedence, followed by cross-metric rejection and intent classification.
    if _SAFETY.search(question):
        return _abstain_plan(requested, PSI25_ID, "safety_or_causality", "", "safety_or_causality",
            "BASS-II evidence supports descriptive paired changes and within-metric rankings, not safety, causal, predictive, or operational conclusions.",
            ("no_causal_or_safety_claim", "metric_isolation"))
    mentioned = metrics_in(question)
    if len(mentioned) > 1:
        return _abstain_plan(requested, PSI25_ID, "cross_metric_comparison", "", "cross_metric_comparison",
            "O2, CO2, and CO have different measurement properties; no cross-metric composite or ranking is registered.",
            ("no_cross_metric_pooling", "metric_isolation"))
    metric = mentioned[0] if mentioned else ""
    if _QUESTIONS.search(question):
        intent = "psi25_research_questions"
        operation = f"psi25.bass_ii.v4.{metric + '.' if metric else ''}research_questions"
        scope = "research-questions"
        evidence = ("psi25.evidence_synthesis",)
        constraints = ("hash_verified_source", "registered_operation_only", "research_questions_are_evidence_gaps", "metric_isolation", "no_operational_recommendation")
        rules = ("Retrieve research questions from the verified deterministic synthesis.",
                 "Treat questions as evidence gaps, not measurements, findings, or recommendations.")
    elif metric and _RANK.search(question):
        intent = "psi25_metric_ranking"
        operation = f"psi25.bass_ii.v4.{metric}.ranking"
        scope = "cohort-evidence"
        evidence = ("psi25.canonical_records", "psi25.paired_analysis", "psi25.findings", "psi25.evidence_synthesis")
        constraints = ("hash_verified_source", "registered_operation_only", "metric_isolation", "no_cross_metric_pooling", "precomputed_artifacts_only", "descriptive_signed_mean_ranking", "no_causal_or_safety_claim")
        rules = (f"Use the {metric.upper()} metric only.",
                 "Read the verified paired-analysis and findings artifacts; do not calculate new statistics.",
                 "Rank cohorts by signed mean paired change under the registered analysis rules.")
    elif metric:
        intent = "psi25_metric_insights"
        operation = f"psi25.bass_ii.v4.{metric}.insights"
        scope = "cohort-evidence"
        evidence = ("psi25.canonical_records", "psi25.paired_analysis", "psi25.findings", "psi25.evidence_synthesis")
        constraints = ("hash_verified_source", "registered_operation_only", "metric_isolation", "no_cross_metric_pooling", "precomputed_artifacts_only", "descriptive_only", "no_causal_or_safety_claim")
        rules = (f"Use the {metric.upper()} metric only.",
                 "Read verified paired-change findings and their linked cohort evidence.",
                 "Preserve rankability, exclusions, and source-linked record provenance.")
    elif _SUMMARY.search(question):
        intent = "psi25_snapshot"
        operation = "psi25.bass_ii.v4.snapshot"
        scope = "all-records"
        evidence = ("psi25.canonical_records", "psi25.paired_analysis", "psi25.findings", "psi25.evidence_synthesis")
        constraints = ("hash_verified_source", "registered_operation_only", "metrics_kept_separate", "no_cross_metric_pooling", "descriptive_only", "no_causal_or_safety_claim")
        rules = ("Use the verified 129-record BASS-II canonical release.",
                 "Summarize O2, CO2, and CO separately; do not pool, composite-score, or rank across metrics.")
    else:
        return _abstain_plan(requested, PSI25_ID, "unsupported", metric, "unsupported",
            "No registered PSI-25 operation matches this request. Ask for a dataset summary, one metric's findings or ranking, or research questions.",
            ("registered_operation_only", "metric_isolation"))

    return ScientificPlan(
        decision="execute", requested_investigation=requested,
        resolved_investigation=PSI25_ID, intent=intent, metric=metric,
        operation_id=operation, data_scope=scope,
        evidence_requirements=evidence, constraint_codes=constraints,
        reason_codes=("registered_analysis_match",), selection_rules=rules,
        explanation=f"Selected the registered PSI-25 operation {operation}; metric scope is {metric.upper() if metric else 'separate metrics'}.",
    )



def validate_scientific_plan_for_dispatch(plan: ScientificPlan, question: str) -> ScientificPlan:
    """Validate a freshly-created plan and its registered operation boundary."""
    validated = validate_scientific_plan(plan, question)
    if validated.execution_allowed:
        if validated.resolved_investigation == PSI69_ID:
            allowed = {spec[0] for spec in _PSI69_SPECS.values()}
        elif validated.resolved_investigation == PSI25_ID:
            allowed = {"psi25.bass_ii.v4.snapshot", "psi25.bass_ii.v4.research_questions"}
            allowed.update(f"psi25.bass_ii.v4.{metric}.{suffix}"
                           for metric in METRICS for suffix in ("insights", "ranking", "research_questions"))
        else:
            allowed = set()
        if validated.operation_id not in allowed:
            raise ValueError("scientific plan operation is not registered")
    return validated

def validate_scientific_plan(plan: object, question: str) -> ScientificPlan:
    """Recompute and compare a plan at the generic execution boundary."""
    if not isinstance(plan, ScientificPlan):
        raise ValueError("scientific plan object is invalid")
    expected = build_scientific_plan(question, plan.requested_investigation)
    if plan != expected:
        raise ValueError("scientific plan does not match the normalized request")
    return plan


def validate_psi69_scientific_plan(plan: object, question: str) -> ScientificPlan:
    """Validate a plan specifically at the PSI-69 execution boundary."""
    validated = validate_scientific_plan(plan, question)
    if validated.resolved_investigation != PSI69_ID:
        raise ValueError("scientific plan does not resolve to PSI-69")
    return validated
