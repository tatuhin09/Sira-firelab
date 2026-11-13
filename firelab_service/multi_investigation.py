"""Investigation-aware, deterministic Ask SIRA routing for FireLab M4.2."""
from __future__ import annotations
from datetime import datetime, timezone
import math
import uuid
from typing import Any
from .assistant import FireLabEvidenceAssistant, normalize_conversation_id, normalize_question
from .claim_ledger import ClaimLedgerContext, OPERATION_SPECS, build_claim_ledger
from .evidence_registry import EvidenceRegistry, EvidenceRegistryError, InvestigationEvidence
from .scientific_planner import (
    AUTO_ID, PSI25_ID, PSI69_ID, METRICS, ScientificPlan,
    build_scientific_plan, metrics_in, resolve_investigation, validate_scientific_plan,
    validate_scientific_plan_for_dispatch,
)

MAX_RECORD_REFS = 60
MAX_QUESTIONS = 12


def _metrics_in(question: str) -> list[str]:
    """Compatibility wrapper for the shared metric detector."""
    return metrics_in(question)


def _event(cid: str, tid: str, seq: int, kind: str, status: str, summary: str, payload=None):
    return {"event_id": str(uuid.uuid4()), "conversation_id": cid, "turn_id": tid,
            "sequence": seq, "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "type": kind, "status": status, "summary": summary, "payload": payload or {}}


def _cohort_key(cohort: Any) -> tuple[str, str, str]:
    if not isinstance(cohort, dict):
        return ("", "", "")
    return (str(cohort.get("pi", "")), str(cohort.get("material_class", "")), str(cohort.get("flow_restrictor_code", "")))


def _metrics_in(question: str) -> list[str]:
    return [m for m in METRICS if _METRIC[m].search(question)]


# M4.3-C2 PSI-25 Claim Ledger integration helpers.

def _psi25_claim_evidence_hashes(entry: InvestigationEvidence) -> dict[str, str]:
    payload = entry.payload
    artifacts = payload.get("artifact_sha256")
    if not isinstance(artifacts, dict) and not hasattr(artifacts, "get"):
        raise EvidenceRegistryError("PSI-25 verified artifact hash map is unavailable for claim ledger")
    values = {
        "psi25-source-csv": entry.source_sha256,
        "psi25-canonical-records": entry.records_sha256,
        "psi25-paired-analysis": artifacts.get("paired_analysis"),
        "psi25-findings": artifacts.get("findings"),
        "psi25-synthesis": artifacts.get("synthesis"),
    }
    if any(not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()) for value in values.values()):
        raise EvidenceRegistryError("PSI-25 claim ledger evidence hashes are incomplete or malformed")
    return values


def _psi25_claim_evidence_references(evidence_hashes: dict[str, str], *, compact: bool = False) -> list[dict[str, str]]:
    reference_ids = (
        ("psi25-source-csv", "psi25-canonical-records")
        if compact else
        ("psi25-source-csv", "psi25-canonical-records", "psi25-paired-analysis", "psi25-findings", "psi25-synthesis")
    )
    return [{"referenceId": key, "sha256": evidence_hashes[key]} for key in reference_ids]


def _psi25_claim_limitations(synthesis: dict[str, Any], metric_payload: dict[str, Any] | None = None,
                             card: dict[str, Any] | None = None) -> list[str]:
    values: list[str] = []
    if metric_payload is not None:
        interpretation_limit = metric_payload.get("interpretation_limit")
        if isinstance(interpretation_limit, str) and interpretation_limit:
            values.append(interpretation_limit)
    if card is not None:
        dimensions = card.get("evidence_dimensions")
        if isinstance(dimensions, dict):
            caveat = dimensions.get("measurement_caveat")
            if isinstance(caveat, str) and caveat:
                values.append(caveat)
        relevance = card.get("mission_research_relevance")
        if isinstance(relevance, str) and relevance:
            values.append(relevance)
    constraints = synthesis.get("scientific_use_constraints", [])
    if isinstance(constraints, list):
        values.extend(item for item in constraints if isinstance(item, str) and item)
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item not in seen:
            seen.add(item)
            deduplicated.append(item)
    if not deduplicated:
        deduplicated.append("Interpretation is limited to the verified PSI-25 BASS-II Study Version 4 artifacts and the registered descriptive operation.")
    return deduplicated[:24]


def _psi25_aggregate_record_lineage(record_count: int, selection_rule: str) -> dict[str, Any]:
    return {
        "mode": "registered_selection_scope",
        "supportingRecordIds": [],
        "excludedRecordIds": [],
        "supportingCount": record_count,
        "excludedCount": 0,
        "selectionRule": selection_rule,
        "complete": True,
    }


def _psi25_quality_dimensions(*, lineage: str, statistical_scope: str,
                              measurement_validity: list[str] | None = None,
                              sample_independence: str = "not_established") -> dict[str, Any]:
    return {
        "sourceIntegrity": "verified",
        "artifactIntegrity": "verified",
        "recordLineageIntegrity": lineage,
        "methodReproducibility": "precomputed_deterministic_artifact",
        "statisticalScope": statistical_scope,
        "measurementValidity": list(measurement_validity or []),
        "sampleIndependence": sample_independence,
        "independentReplication": "not_performed",
        "missionTransferability": "not_established",
        "scientificTruth": "not_established_by_integrity_checks",
    }


def _build_psi25_claim_ledger(entry: InvestigationEvidence, plan: ScientificPlan,
                              answer: dict[str, Any]) -> dict[str, Any] | None:
    """Create a provenance-only ledger from the already verified PSI-25 registry.

    No measurements are recalculated and no text is inferred from rendered prose.
    Existing claimReferences and recordRefs remain untouched for compatibility.
    Research-question retrieval intentionally returns no ledger: questions are
    evidence-gap prompts, not scientific claim entries.
    """
    if not isinstance(entry, InvestigationEvidence) or entry.investigation_id != PSI25_ID:
        raise EvidenceRegistryError("PSI-25 claim ledger requires its verified registry entry")
    if not isinstance(answer, dict) or answer.get("status") != "completed":
        raise EvidenceRegistryError("PSI-25 claim ledger requires a completed answer")
    if not getattr(plan, "execution_allowed", False) or getattr(plan, "resolved_investigation", None) != PSI25_ID:
        raise EvidenceRegistryError("PSI-25 claim ledger requires an executable validated PSI-25 plan")
    operation_id = getattr(plan, "operation_id", "")
    metric = getattr(plan, "metric", "") or ""
    data_scope = getattr(plan, "data_scope", "")
    if answer.get("analysisId") != operation_id or answer.get("dataScope") != data_scope or answer.get("metric", "") != metric:
        raise EvidenceRegistryError("PSI-25 answer operation, metric or data scope does not match its validated plan")
    plan_payload = answer.get("scientificPlan")
    if (not isinstance(plan_payload, dict) or plan_payload.get("operationId") != operation_id
            or plan_payload.get("resolvedInvestigation", plan_payload.get("investigationId", PSI25_ID)) != PSI25_ID
            or plan_payload.get("metric", metric) != metric
            or plan_payload.get("dataScope", data_scope) != data_scope):
        raise EvidenceRegistryError("PSI-25 answer is missing its matching serialized scientific plan")
    if "claimLedger" in answer:
        raise EvidenceRegistryError("PSI-25 answer already contains a Claim Ledger; refusing replacement")

    research_operations = {
        "psi25.bass_ii.v4.research_questions",
        "psi25.bass_ii.v4.o2.research_questions",
        "psi25.bass_ii.v4.co2.research_questions",
        "psi25.bass_ii.v4.co.research_questions",
    }
    if operation_id in research_operations:
        return None

    payload = entry.payload
    paired = payload.get("paired")
    findings = payload.get("findings")
    synthesis = payload.get("synthesis")
    if not all(isinstance(value, dict) or hasattr(value, "get") for value in (paired, findings, synthesis)):
        raise EvidenceRegistryError("PSI-25 verified paired/findings/synthesis payload is incomplete")
    evidence_hashes = _psi25_claim_evidence_hashes(entry)
    evidence_refs = _psi25_claim_evidence_references(evidence_hashes)
    record_keys = frozenset(payload.get("record_keys", ()))
    if len(record_keys) != entry.record_count:
        raise EvidenceRegistryError("PSI-25 verified canonical record-key set does not match registry record count")

    claim_entries: list[dict[str, Any]] = []
    expected_claim_ids = None
    expected_record_lineage = None

    if operation_id == "psi25.bass_ii.v4.snapshot":
        selection_rule = f"All {entry.record_count} verified PSI-25 BASS-II canonical records; O2, CO2 and CO remain separate metric scopes."
        aggregate_lineage = _psi25_aggregate_record_lineage(entry.record_count, selection_rule)
        global_limitations = _psi25_claim_limitations(synthesis)
        claim_entries.append({
            "claimId": "psi25.bass_ii.v4.snapshot.record-count",
            "claimType": "source_table_count",
            "statement": f"The verified PSI-25 BASS-II {entry.version} canonical dataset contains {entry.record_count} experiment records.",
            "result": {"recordCount": entry.record_count},
            "metric": "",
            "unit": "records",
            "cohort": None,
            "evidenceReferences": _psi25_claim_evidence_references(evidence_hashes, compact=True),
            "recordLineage": aggregate_lineage,
            "qualityDimensions": _psi25_quality_dimensions(
                lineage="aggregate_scope", statistical_scope="source_count_only",
                measurement_validity=["canonical_record_count_only"], sample_independence="not_applicable"),
            "limitations": ["This is a canonical experiment-record count, not an independent physical-sample count, effect estimate, safety ranking or mission qualification.", *global_limitations][:24],
            "interpretationStatus": "source_reported",
        })
        for metric_key in ("o2", "co2", "co"):
            pair_metric = paired["metrics"][metric_key]
            finding_metric = findings["metrics"][metric_key]
            synthesis_metric = synthesis["metrics"][metric_key]
            counts = pair_metric["pair_counts"]
            if counts.get("records") != entry.record_count or counts.get("eligible_pairs", 0) + counts.get("excluded_pairs", 0) != entry.record_count:
                raise EvidenceRegistryError(f"PSI-25 {metric_key.upper()} snapshot pair accounting mismatch")
            claim_entries.append({
                "claimId": f"psi25.bass_ii.v4.snapshot.{metric_key}.pair-accounting",
                "claimType": "descriptive_summary",
                "statement": (f"The verified PSI-25 BASS-II {metric_key.upper()} analysis accounts for {entry.record_count} records: "
                              f"{counts['eligible_pairs']} eligible paired measurements and {counts['excluded_pairs']} excluded records."),
                "result": {
                    "recordCount": entry.record_count,
                    "eligiblePairs": counts["eligible_pairs"],
                    "excludedPairs": counts["excluded_pairs"],
                    "rankableCohorts": finding_metric["rankable_cohort_count"],
                    "notRankableCohorts": finding_metric["not_rankable_cohort_count"],
                    "insightCards": len(synthesis_metric["insight_cards"]),
                },
                "metric": metric_key,
                "unit": "paired experiment records",
                "cohort": None,
                "evidenceReferences": evidence_refs,
                "recordLineage": aggregate_lineage,
                "qualityDimensions": _psi25_quality_dimensions(
                    lineage="aggregate_scope", statistical_scope="descriptive_only",
                    measurement_validity=[f"{metric_key}_metric_specific_pair_eligibility_rules_applied"]),
                "limitations": _psi25_claim_limitations(synthesis, synthesis_metric),
                "interpretationStatus": "descriptive_only",
            })
    elif operation_id in {f"psi25.bass_ii.v4.{m}.{suffix}" for m in ("o2", "co2", "co") for suffix in ("insights", "ranking")}:
        if metric not in {"o2", "co2", "co"} or data_scope != "cohort-evidence":
            raise EvidenceRegistryError("PSI-25 cohort claim ledger received an unsupported metric or scope")
        metric_payload = synthesis["metrics"][metric]
        cards = metric_payload.get("insight_cards")
        if not isinstance(cards, list) or not cards or len(cards) > 30:
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} synthesis insight-card set is invalid")
        expected_claim_id_set: set[str] = set()
        expected_record_lineage = {}
        covered_keys: list[str] = []
        for card in cards:
            if not isinstance(card, dict):
                raise EvidenceRegistryError("PSI-25 synthesis contains a malformed insight card")
            claim_id = card.get("insight_id")
            if not isinstance(claim_id, str) or not claim_id:
                raise EvidenceRegistryError("PSI-25 synthesis insight card has no stable ID")
            if card.get("metric") != metric:
                raise EvidenceRegistryError("PSI-25 synthesis insight card crosses the selected metric")
            supporting_rows = card.get("supporting_record_evidence")
            excluded_rows = card.get("excluded_record_evidence")
            if not isinstance(supporting_rows, list) or not isinstance(excluded_rows, list):
                raise EvidenceRegistryError("PSI-25 insight card record evidence arrays are malformed")
            supporting_keys = [row.get("record_key") for row in supporting_rows if isinstance(row, dict)]
            excluded_keys = [row.get("record_key") for row in excluded_rows if isinstance(row, dict)]
            if len(supporting_keys) != len(supporting_rows) or len(excluded_keys) != len(excluded_rows):
                raise EvidenceRegistryError("PSI-25 insight card contains a malformed record reference")
            if card.get("eligible_pairs") != len(supporting_keys) or card.get("excluded_pairs") != len(excluded_keys):
                raise EvidenceRegistryError("PSI-25 insight card record counts do not match its lineage")
            if card.get("records_in_cohort") != len(supporting_keys) + len(excluded_keys):
                raise EvidenceRegistryError("PSI-25 insight card cohort count does not reconcile")
            if claim_id in expected_claim_id_set:
                raise EvidenceRegistryError("PSI-25 synthesis contains duplicate insight IDs")
            expected_claim_id_set.add(claim_id)
            expected_record_lineage[claim_id] = {
                "supportingRecordKeys": tuple(supporting_keys),
                "excludedRecordKeys": tuple(excluded_keys),
            }
            covered_keys.extend(supporting_keys + excluded_keys)

        expected_claim_ids = frozenset(expected_claim_id_set)
        if len(covered_keys) != entry.record_count or len(set(covered_keys)) != entry.record_count or set(covered_keys) != set(record_keys):
            raise EvidenceRegistryError(f"PSI-25 {metric.upper()} insight cards do not cover the 129 verified canonical records exactly once")

        global_limitations = _psi25_claim_limitations(synthesis, metric_payload)
        for card in cards:
            claim_id = card["insight_id"]
            flags = card.get("flags") if isinstance(card.get("flags"), list) else []
            statistics = card.get("statistics") if isinstance(card.get("statistics"), dict) else {}
            interpretation = card.get("interpretation_status")
            is_rankable = interpretation == "descriptive_only"
            if not is_rankable and interpretation != "not_rankable":
                raise EvidenceRegistryError("PSI-25 insight card has an unsupported interpretation status")
            sample_independence = (
                "potential_dependence_flagged"
                if "sample_id_reuse_possible_dependence" in flags or card.get("records_marked_with_reused_sample_id", 0) > 0
                else "not_established"
            )
            record_lineage = {
                "mode": "explicit_canonical_record_keys",
                "supportingRecordKeys": list(expected_record_lineage[claim_id]["supportingRecordKeys"]),
                "excludedRecordKeys": list(expected_record_lineage[claim_id]["excludedRecordKeys"]),
                "supportingCount": len(expected_record_lineage[claim_id]["supportingRecordKeys"]),
                "excludedCount": len(expected_record_lineage[claim_id]["excludedRecordKeys"]),
                "complete": True,
            }
            cohort = card.get("cohort") or {}
            claim_entries.append({
                "claimId": claim_id,
                "claimType": "descriptive_cohort_finding",
                "statement": card.get("observation") or card.get("distribution") or "This cohort has no eligible exact paired measurements and is not rankable.",
                "result": {
                    "rank": card.get("rank"),
                    "eligiblePairs": card.get("eligible_pairs", 0),
                    "excludedPairs": card.get("excluded_pairs", 0),
                    "recordsInCohort": card.get("records_in_cohort", 0),
                    "statistics": statistics,
                    "directionCounts": card.get("direction_counts") if isinstance(card.get("direction_counts"), dict) else {},
                    "flags": list(flags),
                    "distribution": card.get("distribution", ""),
                },
                "metric": metric,
                "unit": card.get("unit") or "",
                "cohort": {
                    "pi": cohort.get("pi"),
                    "materialClass": cohort.get("material_class"),
                    "flowRestrictorCode": cohort.get("flow_restrictor_code"),
                },
                "evidenceReferences": evidence_refs,
                "recordLineage": record_lineage,
                "qualityDimensions": _psi25_quality_dimensions(
                    lineage="complete", statistical_scope="descriptive_only",
                    measurement_validity=[str(flag) for flag in flags],
                    sample_independence=sample_independence),
                "limitations": _psi25_claim_limitations(synthesis, metric_payload, card),
                "interpretationStatus": "descriptive_only" if is_rankable else "descriptive_with_limitations",
            })
    else:
        raise EvidenceRegistryError("PSI-25 claim ledger operation is not registered for claim generation")

    context = ClaimLedgerContext(
        investigation_id=PSI25_ID,
        source_release=f"PSI-25 {entry.title} {entry.version}",
        operation_id=operation_id,
        metric=metric,
        data_scope=data_scope,
        evidence_hashes=evidence_hashes,
        upstream_verification="verified",
        answer_status=answer["status"],
        execution_allowed=True,
        allowed_record_keys=record_keys,
        expected_claim_ids=expected_claim_ids,
        expected_record_lineage=expected_record_lineage,
    )
    return build_claim_ledger(context, claim_entries)


# M4.3-C3 PSI-69 Claim Ledger integration helpers.

_PSI69_OUTCOMES = ("Extinction", "Disruption", "Completion")
_PSI69_EVIDENCE_IDS = ("psi69.source_manifest", "psi69.records", "psi69.quality_report")


def _psi69_claim_evidence(entry: InvestigationEvidence) -> tuple[dict[str, str], list[dict[str, str]]]:
    bundle = entry.payload.get("bundle") if hasattr(entry.payload, "get") else None
    if not isinstance(bundle, dict):
        raise EvidenceRegistryError("PSI-69 verified bundle is unavailable for Claim Ledger")
    hashes = {
        "psi69.source_manifest": entry.source_sha256,
        "psi69.records": entry.records_sha256,
        "psi69.quality_report": entry.quality_sha256,
    }
    for reference_id, digest in hashes.items():
        if (not isinstance(digest, str) or len(digest) != 64
                or any(ch not in "0123456789abcdef" for ch in digest.lower())):
            raise EvidenceRegistryError("PSI-69 verified evidence hash is malformed")
    if (bundle.get("sourceSha256") != entry.source_sha256
            or bundle.get("recordsSha256") != entry.records_sha256
            or bundle.get("qualitySha256") != entry.quality_sha256):
        raise EvidenceRegistryError("PSI-69 bundle hashes do not match the verified registry entry")
    references = [{"referenceId": key, "sha256": hashes[key]} for key in _PSI69_EVIDENCE_IDS]
    return hashes, references


def _psi69_event(answer: dict[str, Any], event_type: str, status: str | None = None) -> dict[str, Any]:
    events = answer.get("events")
    if not isinstance(events, list):
        raise EvidenceRegistryError("PSI-69 completed answer has no event list")
    matches = [event for event in events if isinstance(event, dict)
               and event.get("type") == event_type
               and (status is None or event.get("status") == status)]
    if len(matches) != 1 or not isinstance(matches[0].get("payload"), dict):
        raise EvidenceRegistryError(f"PSI-69 answer must contain exactly one {event_type} event with a structured payload")
    return matches[0]


def _psi69_source_records(entry: InvestigationEvidence) -> tuple[list[int], dict[int, dict[str, Any]]]:
    bundle = entry.payload.get("bundle")
    records = bundle.get("records") if isinstance(bundle, dict) else None
    if not isinstance(records, list) or len(records) != entry.record_count:
        raise EvidenceRegistryError("PSI-69 verified source record list does not match its registry count")
    ids: list[int] = []
    by_id: dict[int, dict[str, Any]] = {}
    for row in records:
        if not isinstance(row, dict):
            raise EvidenceRegistryError("PSI-69 verified source contains a malformed record")
        record_id = row.get("testNumber")
        if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0 or record_id in by_id:
            raise EvidenceRegistryError("PSI-69 source record IDs must be positive, unique integers")
        ids.append(record_id)
        by_id[record_id] = row
    if len(ids) != entry.record_count:
        raise EvidenceRegistryError("PSI-69 source record identity count mismatch")
    return ids, by_id


def _psi69_integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvidenceRegistryError(f"PSI-69 {label} must be an integer >= {minimum}")
    return value


def _psi69_fuel_group_counts(groups: Any, expected_total: int) -> tuple[dict[str, int], dict[str, int], list[dict[str, Any]]]:
    if not isinstance(groups, list) or not 1 <= len(groups) <= 20:
        raise EvidenceRegistryError("PSI-69 fuel-group result is missing or outside its bound")
    fuel_counts: dict[str, int] = {}
    total_outcomes = {name: 0 for name in _PSI69_OUTCOMES}
    compact_groups: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise EvidenceRegistryError("PSI-69 fuel-group result contains a malformed group")
        fuel = group.get("fuel")
        if not isinstance(fuel, str) or not fuel or fuel in fuel_counts:
            raise EvidenceRegistryError("PSI-69 fuel-group labels must be unique non-empty strings")
        count = _psi69_integer(group.get("n"), "fuel-group count", minimum=1)
        outcomes = group.get("outcomes")
        if not isinstance(outcomes, dict) or set(outcomes) != set(_PSI69_OUTCOMES):
            raise EvidenceRegistryError("PSI-69 fuel-group outcomes do not match the registered categories")
        clean_outcomes = {}
        for name in _PSI69_OUTCOMES:
            value = _psi69_integer(outcomes.get(name), f"{fuel} {name} count")
            clean_outcomes[name] = value
            total_outcomes[name] += value
        if sum(clean_outcomes.values()) != count:
            raise EvidenceRegistryError("PSI-69 fuel-group outcome counts do not reconcile to its record count")
        fuel_counts[fuel] = count
        compact_groups.append({"fuel": fuel, "n": count, "outcomes": clean_outcomes})
    if sum(fuel_counts.values()) != expected_total:
        raise EvidenceRegistryError("PSI-69 fuel-group counts do not reconcile to the verified source scope")
    if sum(total_outcomes.values()) != expected_total:
        raise EvidenceRegistryError("PSI-69 outcome totals do not reconcile to the verified source scope")
    return fuel_counts, total_outcomes, compact_groups


def _psi69_registered_lineage(
    record_ids: list[int], all_ids: list[int], selection_rule: str,
) -> dict[str, Any]:
    selected = set(record_ids)
    if len(selected) != len(record_ids) or not selected.issubset(set(all_ids)):
        raise EvidenceRegistryError("PSI-69 selected record IDs are duplicate or outside the verified source")
    excluded = [record_id for record_id in all_ids if record_id not in selected]
    return {
        "mode": "registered_selection_scope",
        "supportingRecordIds": list(record_ids),
        "excludedRecordIds": excluded,
        "supportingCount": len(record_ids),
        "excludedCount": len(excluded),
        "selectionRule": selection_rule,
        "complete": True,
    }


def _psi69_quality_dimensions(
    statistical_scope: str, measurement_validity: list[str],
    method: str = "deterministic_registered_method",
    sample_independence: str = "not_established",
) -> dict[str, Any]:
    return {
        "sourceIntegrity": "verified",
        "artifactIntegrity": "verified",
        "recordLineageIntegrity": "aggregate_scope",
        "methodReproducibility": method,
        "statisticalScope": statistical_scope,
        "measurementValidity": measurement_validity,
        "sampleIndependence": sample_independence,
        "independentReplication": "not_performed",
        "missionTransferability": "not_established",
        "scientificTruth": "not_established_by_integrity_checks",
    }


def _build_psi69_claim_ledger(
    entry: InvestigationEvidence, plan: ScientificPlan, answer: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a provenance-only ledger from one completed registered PSI-69 result.

    All result values come from structured answer fields or the existing
    analysis.completed event. This helper does not parse prose or recalculate
    measurements. The verified registry supplies the bounded source ID set
    and the three already-checked evidence hashes.
    """
    if not isinstance(entry, InvestigationEvidence) or entry.investigation_id != PSI69_ID:
        raise EvidenceRegistryError("PSI-69 Claim Ledger requires its verified registry entry")
    if not isinstance(answer, dict):
        raise EvidenceRegistryError("PSI-69 Claim Ledger requires a structured answer")
    if answer.get("status") != "completed":
        return None
    if (not getattr(plan, "execution_allowed", False)
            or getattr(plan, "resolved_investigation", None) != PSI69_ID):
        raise EvidenceRegistryError("PSI-69 Claim Ledger requires an executable validated PSI-69 plan")
    operation_id = getattr(plan, "operation_id", "")
    data_scope = getattr(plan, "data_scope", "")
    metric = getattr(plan, "metric", "") or ""
    spec = OPERATION_SPECS.get(operation_id)
    if spec is None or spec.investigation_id != PSI69_ID:
        raise EvidenceRegistryError("PSI-69 Claim Ledger operation is not exactly registered")
    if answer.get("analysisId") != operation_id or answer.get("dataScope") != data_scope:
        raise EvidenceRegistryError("PSI-69 answer operation or scope does not match its validated plan")
    if metric != "" or spec.metric != "":
        raise EvidenceRegistryError("PSI-69 Claim Ledger does not accept metric-scoped PSI-25 operations")
    if answer.get("investigationId") != PSI69_ID:
        raise EvidenceRegistryError("PSI-69 answer investigation identity does not match its plan")
    serialized_plan = answer.get("scientificPlan")
    if (not isinstance(serialized_plan, dict)
            or serialized_plan.get("operationId") != operation_id
            or serialized_plan.get("resolvedInvestigation") != PSI69_ID
            or serialized_plan.get("dataScope") != data_scope
            or serialized_plan.get("metric", "") != ""):
        raise EvidenceRegistryError("PSI-69 answer is missing its matching serialized scientific plan")
    if "claimLedger" in answer:
        raise EvidenceRegistryError("PSI-69 answer already contains a Claim Ledger; refusing replacement")

    bundle = entry.payload.get("bundle") if hasattr(entry.payload, "get") else None
    manifest = bundle.get("manifest") if isinstance(bundle, dict) else None
    if not isinstance(manifest, dict) or manifest.get("sourceVersion") != entry.version:
        raise EvidenceRegistryError("PSI-69 verified release metadata is unavailable or inconsistent")
    all_ids, records_by_id = _psi69_source_records(entry)
    evidence_hashes, evidence_references = _psi69_claim_evidence(entry)

    for answer_key, expected in (
        ("sourceHash", entry.source_sha256),
        ("recordsHash", entry.records_sha256),
        ("qualityHash", entry.quality_sha256),
    ):
        if answer.get(answer_key) != expected:
            raise EvidenceRegistryError(f"PSI-69 answer {answer_key} does not match the verified registry")

    analysis_event = _psi69_event(answer, "analysis.completed", "complete")
    analysis_payload = analysis_event["payload"]
    completion_event = _psi69_event(answer, "answer.completed", "completed")
    completion_payload = completion_event["payload"]
    if (completion_payload.get("source_sha256") != entry.source_sha256
            or completion_payload.get("records_sha256") != entry.records_sha256
            or completion_payload.get("quality_sha256") != entry.quality_sha256
            or completion_payload.get("analysis_id") != operation_id
            or completion_payload.get("sample_size") != answer.get("sampleSize")):
        raise EvidenceRegistryError("PSI-69 completion event is not bound to the verified analysis and hashes")

    claim_id = operation_id + ".claim"
    expected_lineage: dict[str, dict[str, tuple[int, ...]]] = {}
    claims: list[dict[str, Any]] = []

    def add_claim(
        claim_type: str, statement: str, result: dict[str, Any], unit: str,
        lineage: dict[str, Any], statistical_scope: str,
        limitations: list[str], interpretation_status: str,
        measurement_validity: list[str], method: str = "deterministic_registered_method",
        sample_independence: str = "not_established",
    ) -> None:
        nonlocal claim_id
        expected_lineage[claim_id] = {
            "supportingRecordIds": tuple(lineage["supportingRecordIds"]),
            "excludedRecordIds": tuple(lineage["excludedRecordIds"]),
        }
        claims.append({
            "claimId": claim_id,
            "claimType": claim_type,
            "statement": statement,
            "result": result,
            "metric": "",
            "unit": unit,
            "cohort": None,
            "evidenceReferences": evidence_references,
            "recordLineage": lineage,
            "qualityDimensions": _psi69_quality_dimensions(
                statistical_scope, measurement_validity, method, sample_independence,
            ),
            "limitations": limitations,
            "interpretationStatus": interpretation_status,
        })

    # Aggregate claims deliberately omit explicit ID arrays while retaining
    # the complete source-scope counts. Selection operations carry explicit IDs.
    empty_aggregate_lineage = {
        "mode": "registered_selection_scope",
        "supportingRecordIds": [],
        "excludedRecordIds": [],
        "supportingCount": entry.record_count,
        "excludedCount": 0,
        "selectionRule": f"Aggregate scope over all {entry.record_count} retained PSI-69 FLEX Version 5 source records; IDs are verified by the registered source bundle.",
        "complete": True,
    }

    if operation_id == "flex.dataset.snapshot":
        record_count = _psi69_integer(analysis_payload.get("record_count"), "snapshot record count", minimum=1)
        if record_count != entry.record_count or answer.get("sampleSize") != entry.record_count:
            raise EvidenceRegistryError("PSI-69 snapshot count does not match the verified source table")
        fuel_counts, outcome_totals, groups = _psi69_fuel_group_counts(
            analysis_payload.get("fuel_groups"), entry.record_count,
        )
        supplied_outcomes = analysis_payload.get("outcomes")
        if not isinstance(supplied_outcomes, dict) or set(supplied_outcomes) != set(_PSI69_OUTCOMES):
            raise EvidenceRegistryError("PSI-69 snapshot outcome counts are malformed")
        clean_outcomes = {name: _psi69_integer(supplied_outcomes[name], f"snapshot {name} count") for name in _PSI69_OUTCOMES}
        if clean_outcomes != outcome_totals:
            raise EvidenceRegistryError("PSI-69 snapshot outcome totals do not match fuel-group counts")
        add_claim(
            "source_table_count",
            f"The verified PSI-69 FLEX {entry.version} source bundle contains {entry.record_count} retained experiment records.",
            {"recordCount": record_count, "fuelCounts": fuel_counts,
             "outcomeCounts": clean_outcomes, "fuelOutcomeCounts": groups},
            "records", empty_aggregate_lineage, "source_count_only",
            ["Source-table counts only; no adjusted fuel effect, causal conclusion, safety ranking or mission qualification is established."],
            "source_reported", ["source_record_count_and_categories"],
            sample_independence="not_applicable",
        )

    elif operation_id == "flex.outcomes.by_fuel":
        if answer.get("sampleSize") != entry.record_count:
            raise EvidenceRegistryError("PSI-69 outcomes-by-fuel scope does not cover the verified source table")
        fuel_counts, outcome_totals, groups = _psi69_fuel_group_counts(
            analysis_payload.get("groups"), entry.record_count,
        )
        add_claim(
            "source_table_count",
            f"The verified PSI-69 FLEX source reports outcome counts by fuel across {entry.record_count} retained records.",
            {"recordCount": entry.record_count, "fuelCounts": fuel_counts,
             "outcomeCounts": outcome_totals, "fuelOutcomeCounts": groups},
            "records", empty_aggregate_lineage, "source_count_only",
            ["Unadjusted source-reported counts only; these groups do not establish a fuel effect or comparative safety."],
            "source_reported", ["source_reported_fuel_and_test_end_categories"],
        )

    elif operation_id == "flex.burning_rate.exact_by_fuel":
        selected_event = _psi69_event(answer, "data.selected", "complete")["payload"]
        selected_ids = answer.get("recordIds")
        if not isinstance(selected_ids, list) or selected_event.get("record_ids") != selected_ids:
            raise EvidenceRegistryError("PSI-69 burning-rate answer IDs do not match the executed data selection")
        if (answer.get("sampleSize") != len(selected_ids)
                or analysis_payload.get("exact_record_count") != len(selected_ids)
                or selected_event.get("record_count") != len(selected_ids)):
            raise EvidenceRegistryError("PSI-69 exact burning-rate record counts do not reconcile")
        if len(set(selected_ids)) != len(selected_ids) or any(
            isinstance(value, bool) or not isinstance(value, int) or value not in records_by_id
            for value in selected_ids
        ):
            raise EvidenceRegistryError("PSI-69 burning-rate selection contains duplicate or unverified source IDs")
        expected_exact_ids = []
        for record_id in all_ids:
            row = records_by_id[record_id]
            value = row.get("burningRateMm2PerSec")
            quality = row.get("quality", {}).get("burningRateMm2PerSec")
            if (quality == "exact" and isinstance(value, (int, float))
                    and not isinstance(value, bool) and math.isfinite(float(value))):
                expected_exact_ids.append(record_id)
        if selected_ids != expected_exact_ids:
            raise EvidenceRegistryError("PSI-69 burning-rate selected IDs do not match the verified exact finite-value selection")
        summaries = answer.get("burningRateSummaries")
        if not isinstance(summaries, list) or summaries != analysis_payload.get("groups") or not 1 <= len(summaries) <= 20:
            raise EvidenceRegistryError("PSI-69 structured burning-rate summaries are missing or inconsistent")
        summary_groups = []
        summary_n = 0
        seen_fuels: set[str] = set()
        for row in summaries:
            if not isinstance(row, dict):
                raise EvidenceRegistryError("PSI-69 burning-rate summary contains a malformed fuel row")
            fuel = row.get("fuel")
            if not isinstance(fuel, str) or not fuel or fuel in seen_fuels:
                raise EvidenceRegistryError("PSI-69 burning-rate fuel labels must be unique")
            seen_fuels.add(fuel)
            n = _psi69_integer(row.get("n"), "exact burning-rate group count")
            summary_n += n
            clean = {"fuel": fuel, "n": n}
            for key in ("mean", "sd"):
                value = row.get(key)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))):
                    raise EvidenceRegistryError(f"PSI-69 burning-rate {key} must be finite or null")
                clean[key] = value
            for key in ("approximate", "missing", "invalid"):
                clean[key] = _psi69_integer(row.get(key), f"burning-rate {key} count")
            summary_groups.append(clean)
        if summary_n != len(selected_ids):
            raise EvidenceRegistryError("PSI-69 burning-rate group exact counts do not reconcile")
        lineage = _psi69_registered_lineage(
            selected_ids, all_ids,
            "Exact finite burningRateMm2PerSec values only; approximate, missing and invalid source records are excluded.",
        )
        add_claim(
            "descriptive_summary",
            f"The registered PSI-69 FLEX burning-rate analysis summarizes {len(selected_ids)} exact finite values by source-reported fuel.",
            {"exactRecordCount": len(selected_ids), "unit": "mm²/s", "groups": summary_groups},
            "mm²/s", lineage, "descriptive_only",
            ["Exact finite values only; approximate, missing and invalid values are not included in the exact summaries.",
             "Descriptive and not condition-adjusted; no causal fuel effect or safety conclusion is established."],
            "descriptive_only", ["exact_finite_measurements_only", "approximate_and_missing_values_not_imputed"],
        )

    elif operation_id == "flex.measurement_quality":
        if answer.get("sampleSize") != entry.record_count:
            raise EvidenceRegistryError("PSI-69 measurement-quality scope does not match the verified source table")
        quality_rows = answer.get("qualityRows")
        selected_event = _psi69_event(answer, "data.selected", "complete")["payload"]
        if (not isinstance(quality_rows, list) or not 1 <= len(quality_rows) <= 20
                or selected_event.get("measurement_fields") != len(quality_rows)
                or analysis_payload.get("measurement_fields") != len(quality_rows)):
            raise EvidenceRegistryError("PSI-69 measurement-quality rows do not match the executed quality summary")
        clean_rows = []
        labels: set[str] = set()
        for row in quality_rows:
            if not isinstance(row, dict):
                raise EvidenceRegistryError("PSI-69 measurement-quality row is malformed")
            label = row.get("label")
            if not isinstance(label, str) or not label or label in labels:
                raise EvidenceRegistryError("PSI-69 measurement-quality labels must be unique non-empty strings")
            labels.add(label)
            clean = {"label": label}
            for key in ("exact", "approximate", "missing", "invalid"):
                clean[key] = _psi69_integer(row.get(key), f"quality {key} count")
            if sum(clean[key] for key in ("exact", "approximate", "missing", "invalid")) != entry.record_count:
                raise EvidenceRegistryError("PSI-69 field quality categories do not reconcile to retained records")
            clean_rows.append(clean)
        add_claim(
            "measurement_quality_observation",
            f"The verified PSI-69 FLEX quality report contains {len(clean_rows)} field-level measurement-quality summaries across {entry.record_count} retained records.",
            {"recordCount": entry.record_count, "measurementFields": clean_rows},
            "measurement fields", empty_aggregate_lineage, "quality_count_only",
            ["Quality categories describe source measurement availability and classification; they do not establish measurement accuracy or scientific validity.",
             "Approximate values remain distinct from exact values; missing values are not imputed."],
            "quality_observation", ["exact_approximate_missing_invalid_reported_separately", "missing_values_not_imputed"],
            method="precomputed_deterministic_artifact", sample_independence="not_applicable",
        )

    elif operation_id == "flex.oxygen_cohort_sensitivity":
        selected_event = _psi69_event(answer, "data.selected", "complete")["payload"]
        selected_ids = answer.get("recordIds")
        fixed_ids = answer.get("fixedRecordIds")
        comparison = answer.get("oxygenComparison")
        if (not isinstance(selected_ids, list) or not isinstance(fixed_ids, list)
                or not isinstance(comparison, dict)):
            raise EvidenceRegistryError("PSI-69 oxygen comparison is missing structured selected-record evidence")
        if (selected_event.get("broad_record_ids") != selected_ids
                or selected_event.get("fixed_record_ids") != fixed_ids
                or analysis_payload.get("broad_count") != len(selected_ids)
                or analysis_payload.get("fixed_count") != len(fixed_ids)):
            raise EvidenceRegistryError("PSI-69 oxygen comparison IDs do not match the executed selection events")
        if (answer.get("sampleSize") != len(selected_ids)
                or comparison.get("broadRecordCount") != len(selected_ids)
                or comparison.get("fixedRecordCount") != len(fixed_ids)
                or comparison.get("fixedOxygen") != 0.21
                or comparison.get("filters") != {
                    "pressureMin": 750, "pressureMax": 770,
                    "coSourceMoleFraction": 0, "heliumMoleFraction": 0,
                }):
            raise EvidenceRegistryError("PSI-69 oxygen comparison does not match the exact registered condition scope")
        if (len(set(selected_ids)) != len(selected_ids) or len(set(fixed_ids)) != len(fixed_ids)
                or not set(selected_ids).issubset(set(all_ids))
                or not set(fixed_ids).issubset(set(selected_ids))):
            raise EvidenceRegistryError("PSI-69 oxygen cohort IDs are duplicate or outside their verified nested selection")
        if comparison != analysis_payload.get("oxygen_comparison"):
            raise EvidenceRegistryError("PSI-69 oxygen structured result does not match its completed analysis event")
        fixed = comparison.get("fixed")
        broad = comparison.get("broad")
        if not isinstance(fixed, dict) or not isinstance(broad, dict):
            raise EvidenceRegistryError("PSI-69 oxygen comparison slices are malformed")
        for label, slice_data, expected_count in (
            ("fixed", fixed, len(fixed_ids)), ("broad", broad, len(selected_ids)),
        ):
            if slice_data.get("n") != expected_count:
                raise EvidenceRegistryError(f"PSI-69 oxygen {label} cohort count does not match selected record IDs")
            groups = slice_data.get("groups")
            ranked = slice_data.get("ranked")
            if not isinstance(groups, list) or not 1 <= len(groups) <= 10 or not isinstance(ranked, list) or not 1 <= len(ranked) <= 10:
                raise EvidenceRegistryError(f"PSI-69 oxygen {label} groups or ranked outcomes are malformed")
            group_total = 0
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("fuel"), str):
                    raise EvidenceRegistryError(f"PSI-69 oxygen {label} contains a malformed fuel group")
                n = _psi69_integer(group.get("n"), f"oxygen {label} fuel count", minimum=1)
                outcomes = group.get("outcomes")
                if not isinstance(outcomes, dict) or set(outcomes) != set(_PSI69_OUTCOMES):
                    raise EvidenceRegistryError(f"PSI-69 oxygen {label} outcomes are malformed")
                outcome_counts = [_psi69_integer(outcomes[key], f"oxygen {label} outcome count") for key in _PSI69_OUTCOMES]
                if sum(outcome_counts) != n:
                    raise EvidenceRegistryError(f"PSI-69 oxygen {label} outcome counts do not reconcile")
                group_total += n
            if group_total != expected_count:
                raise EvidenceRegistryError(f"PSI-69 oxygen {label} fuel groups do not reconcile to its selected records")
            for item in ranked:
                if not isinstance(item, dict) or item.get("outcome") not in _PSI69_OUTCOMES:
                    raise EvidenceRegistryError(f"PSI-69 oxygen {label} ranked outcome is malformed")
                gap = item.get("gapPercentagePoints")
                if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(float(gap)):
                    raise EvidenceRegistryError(f"PSI-69 oxygen {label} observed gap must be finite")
                for side in ("left", "right"):
                    pair = item.get(side)
                    if not isinstance(pair, dict) or not isinstance(pair.get("fuel"), str):
                        raise EvidenceRegistryError(f"PSI-69 oxygen {label} ranked pair is malformed")
                    count = _psi69_integer(pair.get("count"), "oxygen ranked outcome count")
                    n = _psi69_integer(pair.get("n"), "oxygen ranked group denominator", minimum=1)
                    if count > n:
                        raise EvidenceRegistryError("PSI-69 oxygen ranked outcome count exceeds its group denominator")
        fixed_order = comparison.get("fixedOrder")
        broad_order = comparison.get("broadOrder")
        if (not isinstance(fixed_order, list) or not isinstance(broad_order, list)
                or any(item not in _PSI69_OUTCOMES for item in fixed_order + broad_order)
                or comparison.get("orderChanged") is not (fixed_order != broad_order)):
            raise EvidenceRegistryError("PSI-69 oxygen ranking-order metadata is inconsistent")
        lineage = _psi69_registered_lineage(
            selected_ids, all_ids,
            "All exact oxygen records selected by the registered pressure 750–770 mmHg, source CO = 0 and helium = 0 filters; the fixed O2 = 0.21 cohort is a subset.",
        )
        add_claim(
            "observed_cohort_comparison",
            f"The registered PSI-69 FLEX oxygen-cohort analysis compared {len(fixed_ids)} fixed-O2 records with {len(selected_ids)} records across all exact oxygen values under the predefined pressure, source-CO and helium filters.",
            comparison,
            "percentage points and records", lineage, "descriptive_only",
            ["The fixed-O2 cohort is nested within the broader cohort; the groups overlap.",
             "The broader cohort pools oxygen levels; observed percentage-point gaps are unadjusted and do not establish an oxygen effect.",
             "No safety ranking, prediction, operational recommendation or mission transferability is established."],
            "descriptive_with_limitations", ["overlapping_cohorts", "unadjusted_observed_outcome_shares", "fixed_condition_filters_applied"],
        )

    else:
        raise EvidenceRegistryError("PSI-69 operation has no Claim Ledger builder")

    context = ClaimLedgerContext(
        investigation_id=PSI69_ID,
        source_release=entry.version,
        operation_id=operation_id,
        metric="",
        data_scope=data_scope,
        evidence_hashes=evidence_hashes,
        upstream_verification="verified",
        answer_status="completed",
        execution_allowed=True,
        allowed_record_ids=frozenset(all_ids),
        expected_claim_ids=frozenset(claim["claimId"] for claim in claims),
        expected_record_lineage=expected_lineage,
    )
    return build_claim_ledger(context, claims)


class MultiInvestigationEvidenceAssistant:
    """Dispatches only to PSI-69 FLEX v5 or PSI-25 BASS-II v4."""
    def __init__(self, registry: EvidenceRegistry):
        if not isinstance(registry, EvidenceRegistry):
            raise TypeError("registry must be a verified EvidenceRegistry")
        self.registry = registry
        flex = registry.get(PSI69_ID)
        bundle = flex.payload.get("bundle")
        if not isinstance(bundle, dict):
            raise EvidenceRegistryError("PSI-69 registry bundle is unavailable")
        self.psi69 = FireLabEvidenceAssistant(bundle)
        self.psi25 = registry.get(PSI25_ID)

    @staticmethod
    def _base(cid: str, iid: str, intent: str):
        tid = str(uuid.uuid4())
        events = [_event(cid, tid, 1, "turn.started", "accepted",
                         "Question accepted by the investigation-aware evidence service.",
                         {"investigation_id": iid, "intent": intent})]
        answer = {
            "title": "SIRA FireLab evidence result", "text": "", "bullets": [], "evidence": [],
            "trace": [], "fields": [], "sampleSize": 0, "dataScope": "none", "recordIds": [],
            "recordRefs": [], "qualityRows": [], "citations": [], "claimReferences": [],
            "researchQuestions": [], "artifactHashes": {}, "source": "", "sourceFile": "",
            "sourceVersion": "", "sourceHash": "", "recordsHash": "", "qualityHash": "",
            "sourceUrl": "", "reportUrl": "", "doi": "", "license": "", "analysisId": "",
            "analysisVersion": 1, "intent": intent, "investigationId": iid, "metric": "",
            "status": "abstained", "events": events,
        }
        return answer, events, tid

    @staticmethod
    def _finish(answer, events, tid, status, summary, payload=None):
        answer["status"] = status
        kind = "answer.completed" if status == "completed" else "answer.abstained"
        events.append(_event(events[0]["conversation_id"], tid, len(events) + 1, kind, status, summary, payload))
        answer["events"] = events
        return answer

    def _abstain(self, cid, iid, intent, title, text, scientific_plan=None):
        answer, events, tid = self._base(cid, iid, intent)
        answer.update({"title": title, "text": text,
                       "bullets": ["No source rows were selected and no new calculation was run."],
                       "evidence": ["Evidence abstention", "No calculation run"],
                       "trace": ["The request was outside the registered investigation/analysis contract."]})
        if scientific_plan is not None:
            answer["scientificPlan"] = scientific_plan.as_dict()
        return self._finish(answer, events, tid, "abstained", "No evidence analysis was run.")

    @staticmethod
    def _route(question: str, requested: str):
        """Compatibility wrapper around the shared investigation resolver."""
        return resolve_investigation(question, requested)

    def ask(self, question: object, *, conversation_id: object, investigation_id: object = PSI69_ID):
        question = normalize_question(question)
        cid = normalize_conversation_id(conversation_id)
        plan = build_scientific_plan(question, investigation_id)
        plan = validate_scientific_plan_for_dispatch(plan, question)

        # Scope routing and scientific intent are resolved once, before either
        # deterministic executor is allowed to select evidence.
        if plan.decision == "abstain":
            reason = plan.reason_codes[0] if plan.reason_codes else "unsupported"
            if plan.resolved_investigation == PSI69_ID and reason in {"safety_or_causality", "unsupported"}:
                answer = self.psi69.ask(question, conversation_id=cid, scientific_plan=plan)
                answer["investigationId"] = PSI69_ID
                answer["scientificPlan"] = plan.as_dict()
                return answer
            return self._abstain_from_plan(cid, plan)

        if plan.resolved_investigation not in self.registry.investigation_ids:
            raise EvidenceRegistryError("scientific plan resolved outside the verified evidence registry")

        if plan.resolved_investigation == PSI69_ID:
            answer = self.psi69.ask(question, conversation_id=cid, scientific_plan=plan)
            answer["investigationId"] = PSI69_ID
            answer["scientificPlan"] = plan.as_dict()
            if answer.get("status") == "completed" and answer.get("analysisId") != plan.operation_id:
                raise RuntimeError("scientific plan operation does not match executed PSI-69 analysis")
            if answer.get("dataScope") != plan.data_scope:
                raise RuntimeError("scientific plan data scope does not match PSI-69 response")
            if answer.get("status") == "completed":
                claim_ledger = _build_psi69_claim_ledger(self.registry.get(PSI69_ID), plan, answer)
                if claim_ledger is not None:
                    answer["claimLedger"] = claim_ledger
                    answer["trace"].append(
                        f"Built and validated {len(claim_ledger['claims'])} PSI-69 claim entries against the verified source bundle and registered record lineage."
                    )
            return answer
        return self._ask_psi25(question, cid, plan)

    def _abstain_from_plan(self, cid: str, plan: ScientificPlan):
        reason = plan.reason_codes[0] if plan.reason_codes else "unsupported"
        if reason == "cross_investigation":
            title = "A cross-investigation comparison is not registered."
            text = "PSI-69 FLEX and PSI-25 BASS-II have different experimental designs and evidence contracts. FireLab will not pool or rank them together. Select one investigation and ask a source-specific question."
            iid = "unselected"
        elif reason == "investigation_context_conflict":
            title = "The question conflicts with the selected investigation."
            text = "The selected investigation does not match the investigation named in the question. Change the investigation selector; no source was opened."
            iid = plan.requested_investigation
        elif reason == "unknown_investigation":
            title = "The requested investigation is not approved."
            text = "Only PSI-69 FLEX Version 5 and PSI-25 BASS-II Study Version 4 are registered."
            iid = "unselected"
        elif reason == "safety_or_causality":
            title = "BASS-II evidence cannot establish an operational fire-safety conclusion."
            text = "The PSI-25 BASS-II artifacts support descriptive paired concentration changes and within-metric cohort rankings only. They do not establish fuel safety, causal effects, predictions, or operational recommendations."
            iid = plan.resolved_investigation or "unselected"
        elif reason == "cross_metric_comparison":
            title = "The requested metrics must remain separate."
            text = "O₂, CO₂, and CO have different units and measurement properties. No cross-metric composite score or ranking is registered. Ask about one metric at a time; no cross-metric calculation was run."
            iid = PSI25_ID
        else:
            title = "This question is not covered by a registered evidence operation."
            text = "Ask for a BASS-II dataset summary, one metric's paired-change findings or descriptive ranking, or associated research questions. Unsupported requests do not trigger filtering or calculations."
            iid = plan.resolved_investigation or "unselected"
        return self._abstain(cid, iid, plan.intent, title, text, scientific_plan=plan)

    def _citations(self):
        p = self.psi25.payload
        h = p["artifact_sha256"]
        return [
            {"reference_id": "psi25-source-csv", "title": "NASA PSI-25 BASS-II experimental table", "kind": "source_csv", "sha256": self.psi25.source_sha256, "url": self.psi25.source_url},
            {"reference_id": "psi25-canonical-records", "title": "Canonical experiment records", "kind": "canonical_records", "sha256": h["canonical_records"], "url": ""},
            {"reference_id": "psi25-paired-analysis", "title": "Paired measurement analysis", "kind": "paired_analysis", "sha256": h["paired_analysis"], "url": ""},
            {"reference_id": "psi25-findings", "title": "Metric-specific findings ranking", "kind": "findings", "sha256": h["findings"], "url": ""},
            {"reference_id": "psi25-synthesis", "title": "Deterministic evidence synthesis", "kind": "synthesis", "sha256": h["synthesis"], "url": ""},
        ]

    def _ask_psi25(self, question: str, cid: str, plan: ScientificPlan):
        validated_plan = validate_scientific_plan(plan, question)
        if not validated_plan.execution_allowed or validated_plan.resolved_investigation != PSI25_ID:
            raise ValueError("PSI-25 executor received a non-executable scientific plan")
        intent = validated_plan.intent
        metric = validated_plan.metric
        answer, events, tid = self._base(cid, PSI25_ID, intent)
        p = self.psi25.payload
        paired, findings, synthesis = p["paired"], p["findings"], p["synthesis"]
        answer.update({
            "source": self.psi25.source, "sourceFile": "PSI-25_Experimental table_BASS-II.csv",
            "sourceVersion": self.psi25.version, "sourceHash": self.psi25.source_sha256,
            "recordsHash": self.psi25.records_sha256, "qualityHash": self.psi25.quality_sha256,
            "sourceUrl": self.psi25.source_url, "artifactHashes": dict(p["artifact_sha256"]),
            "citations": self._citations(), "analysisVersion": 1,
        })
        events.append(_event(cid, tid, len(events) + 1, "source.opened", "verified",
            "Opened the hash-verified NASA PSI-25 BASS-II Study Version 4 release.",
            {"source_id": PSI25_ID, "version": self.psi25.version, "source_sha256": self.psi25.source_sha256,
             "canonical_records_sha256": self.psi25.records_sha256}))

        if intent == "psi25_snapshot":
            summary = {}
            bullets = []
            for key in METRICS:
                pm, fm, sm = paired["metrics"][key], findings["metrics"][key], synthesis["metrics"][key]
                row = {"metric": key, "eligible_pairs": pm["pair_counts"]["eligible_pairs"],
                       "excluded_pairs": pm["pair_counts"]["excluded_pairs"],
                       "rankable_cohorts": fm["rankable_cohort_count"],
                       "not_rankable_cohorts": fm["not_rankable_cohort_count"],
                       "insight_cards": len(sm["insight_cards"])}
                summary[key] = row
                bullets.append(f"{key.upper()}: {row['eligible_pairs']} eligible pairs, {row['excluded_pairs']} excluded; {row['rankable_cohorts']} rankable and {row['not_rankable_cohorts']} not-rankable cohorts; {row['insight_cards']} insight cards.")
            answer.update({"title": "NASA PSI-25 BASS-II evidence snapshot.",
                "text": "The verified Study Version 4 release contains 129 canonical experiment records. O₂, CO₂, and CO are summarized separately; their units and findings are not pooled or ranked against one another.",
                "bullets": bullets, "fields": ["initial_o2", "final_o2", "initial_co2", "final_co2", "initial_co", "final_co"],
                "sampleSize": 129, "dataScope": "all-records", "analysisId": "psi25.bass_ii.v4.snapshot", "metricSummary": summary,
                "trace": ["Loaded 129 canonical experiment records from the verified BASS-II Study Version 4 release.",
                          "Read three separately registered paired analyses, findings rankings, and deterministic synthesis artifacts.",
                          "No cross-metric score, inferential statistic, or operational safety conclusion was calculated."]})
            events.append(_event(cid, tid, len(events)+1, "data.selected", "complete", "Selected 129 canonical records and three separate metric summaries.", {"record_count":129,"metrics":list(METRICS)}))
            events.append(_event(cid, tid, len(events)+1, "analysis.started", "running", "Reading precomputed verified paired-analysis, findings, and synthesis outputs."))
            events.append(_event(cid, tid, len(events)+1, "analysis.completed", "complete", "Completed the BASS-II snapshot without combining metrics.", {"record_count":129,"metric_scopes":summary}))

        elif intent in {"psi25_metric_insights", "psi25_metric_ranking"}:
            pm, fm, sm = paired["metrics"][metric], findings["metrics"][metric], synthesis["metrics"][metric]
            ranked, unranked, cards = fm["ranked_cohorts"], fm["not_rankable_cohorts"], sm["insight_cards"]
            by_cohort = {_cohort_key(c.get("cohort")): c for c in cards}
            bullets, claims, refs = [], [], []
            for row in ranked[:5]:
                cohort, stats = row["cohort"], row.get("statistics", {})
                card = by_cohort.get(_cohort_key(cohort), {})
                rank = row.get("rank")
                bullets.append(f"Within-{metric.upper()} descriptive rank {rank}: {cohort.get('pi','Unknown PI')} · {cohort.get('material_class','unclassified')} · flow restrictor {cohort.get('flow_restrictor_code','unknown')}; mean Δ {stats.get('mean','—')} {fm.get('unit','')}; median Δ {stats.get('median','—')}; eligible n={row.get('eligible_pairs',0)}.")
                eligible = row.get("eligible_record_evidence", [])
                excluded = row.get("excluded_record_evidence", [])
                for ev in eligible + excluded:
                    key = ev.get("record_key") if isinstance(ev, dict) else None
                    if isinstance(key, str) and key not in refs:
                        refs.append(key)
                claims.append({"claim_id":card.get("insight_id",f"{metric}-rank-{rank}"),"rank":rank,"metric":metric,
                    "cohort":cohort,"statistics":stats,"interpretation":card.get("observation",""),
                    "distribution":card.get("distribution",""),"flags":card.get("flags",[]),
                    "supporting_record_keys":[x.get("record_key") for x in eligible if isinstance(x,dict)],
                    "excluded_record_keys":[x.get("record_key") for x in excluded if isinstance(x,dict)],
                    "source_reference_ids":["psi25-source-csv","psi25-canonical-records","psi25-paired-analysis","psi25-findings","psi25-synthesis"],
                    "interpretation_status":card.get("interpretation_status","descriptive_only")})
            refs = refs[:MAX_RECORD_REFS]
            caveats = list(synthesis.get("scientific_use_constraints", []))[:5]
            if metric == "o2":
                oc = synthesis.get("measurement_provenance_caveats",{}).get("o2",{}).get("interpretation_limit")
                if isinstance(oc,str):
                    caveats.insert(0,oc)
            bullets.extend(f"Limitation: {x}" for x in caveats[:6])
            pairs = pm["pair_counts"]
            answer.update({"title":f"NASA PSI-25 BASS-II {metric.upper()} paired-change findings.",
                "text":f"This view reports {metric.upper()} final-minus-initial concentration changes. Within-{metric.upper()} ordering is by signed mean paired change only; it is descriptive, not a safety ranking, causal effect, or comparison with another metric. Across 129 records, {pairs['eligible_pairs']} pairs were eligible and {pairs['excluded_pairs']} were excluded under the source-backed measurement rules.",
                "bullets":bullets or ["No cohort in this metric is rankable under the registered evidence rules."],
                "fields":[pm.get("initial_field",""),pm.get("final_field","")],"sampleSize":pairs["eligible_pairs"],
                "dataScope":"cohort-evidence","recordRefs":refs,"claimReferences":claims,"metric":metric,
                "analysisId":f"psi25.bass_ii.v4.{metric}.{'ranking' if intent == 'psi25_metric_ranking' else 'insights'}",
                "rankableCohortCount":len(ranked),"notRankableCohortCount":len(unranked),
                "eligiblePairCount":pairs["eligible_pairs"],"excludedPairCount":pairs["excluded_pairs"],
                "trace":[f"Selected the PSI-25 BASS-II {metric.upper()} metric only.",
                          f"Read {len(ranked)} rankable and {len(unranked)} not-rankable cohorts from the verified findings artifact.",
                          f"Used precomputed final-minus-initial paired changes: {pairs['eligible_pairs']} eligible and {pairs['excluded_pairs']} excluded pairs across 129 canonical records.",
                          "Returned source-linked cohort evidence; no cross-metric ranking or new statistical calculation was performed."]})
            events.append(_event(cid,tid,len(events)+1,"data.selected","complete",f"Selected {metric.upper()} cohort evidence with record provenance.",{"metric":metric,"record_count":129,"eligible_pairs":pairs["eligible_pairs"],"excluded_pairs":pairs["excluded_pairs"],"record_reference_count":len(refs)}))
            events.append(_event(cid,tid,len(events)+1,"analysis.started","running",f"Reading precomputed {metric.upper()} findings and synthesis; no new statistics were calculated."))
            events.append(_event(cid,tid,len(events)+1,"analysis.completed","complete",f"Retrieved {metric.upper()}-specific cohort findings.",{"analysis_id":answer["analysisId"],"ranked_cohorts":len(ranked),"not_rankable_cohorts":len(unranked),"record_reference_count":len(refs)}))

        else:  # research questions
            rows = []
            if metric:
                for card in synthesis["metrics"][metric]["insight_cards"]:
                    rows.extend(card.get("research_questions",[]))
            else:
                rows = synthesis.get("research_questions",[])
            unique, seen = [], set()
            for row in rows:
                qid = row.get("question_id") if isinstance(row,dict) else None
                if isinstance(qid,str) and qid not in seen:
                    seen.add(qid)
                    unique.append({"question_id":qid,"question":row.get("question",""),"trigger":row.get("trigger","")})
            returned = unique[:MAX_QUESTIONS]
            answer.update({"title":f"NASA PSI-25 BASS-II research questions{(' · '+metric.upper()) if metric else ''}.",
                "text":f"The verified synthesis contains {len(unique)} distinct research questions {('for '+metric.upper()) if metric else 'across the three separately maintained metrics'}. These are evidence-gap prompts, not established findings.",
                "bullets":[f"{q['question_id']}: {q['question']}" for q in returned],"researchQuestions":returned,
                "sampleSize":len(unique),"dataScope":"research-questions","metric":metric,
                "analysisId":f"psi25.bass_ii.v4.{metric+'.' if metric else ''}research_questions",
                "trace":["Read questions from the hash-verified deterministic evidence synthesis.","Questions were not treated as measurements, conclusions, or recommendations."]})
            events.append(_event(cid,tid,len(events)+1,"data.selected","complete","Selected precomputed evidence-gap questions.",{"metric":metric or "separate_metrics","question_count":len(unique),"returned_count":len(returned)}))
            events.append(_event(cid,tid,len(events)+1,"analysis.completed","complete","Retrieved research questions without running a numerical analysis.",{"question_count":len(unique)}))

        answer["evidence"] = ["NASA PSI-25 BASS-II · Study Version 4","Verified 129-record canonical dataset","Deterministic paired-analysis, findings, and synthesis artifacts","Metric-specific evidence; no cross-metric ranking"]
        answer["scientificPlan"] = validated_plan.as_dict()
        if answer.get("analysisId") != validated_plan.operation_id or answer.get("dataScope") != validated_plan.data_scope:
            raise RuntimeError("scientific plan does not match executed PSI-25 evidence operation")
        completed = self._finish(answer,events,tid,"completed","The registered PSI-25 evidence retrieval completed.",
            {"investigation_id":PSI25_ID,"intent":intent,"metric":metric or None,"analysis_id":answer.get("analysisId"),
             "sample_size":answer["sampleSize"],"source_sha256":self.psi25.source_sha256,"artifact_sha256":dict(p["artifact_sha256"])})
        claim_ledger = _build_psi25_claim_ledger(self.psi25, validated_plan, completed)
        if claim_ledger is not None:
            completed["claimLedger"] = claim_ledger
            completed["trace"].append(
                f"Built and validated {len(claim_ledger['claims'])} PSI-25 claim entries against the verified artifacts and complete metric-specific record lineage."
            )
        return completed
