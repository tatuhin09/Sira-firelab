"""Evidence-separated research synthesis for SIRA FireLab.

This service joins an independently verified deterministic FireLab answer to
bounded scholarly metadata retrieved through FireLabResearchAdapter (which
uses PaperSearchService and the existing SIRA Research Core worker).

It does not call a model, recalculate NASA measurements, write persistent
knowledge, infer that paper metadata supports a NASA claim, pool investigations,
or make operational fire-safety recommendations.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable

from .claim_ledger import OPERATION_SPECS
from .research_adapter import CLAIM_LEDGER_SCHEMA, ResearchAdapterError
from .scientific_verifier import verify_completed_answer

SCHEMA = "sira.firelab.research_synthesis.v1"
MAX_PACKET_BYTES = 512 * 1024
MAX_CLAIMS = 30
MAX_PAPERS = 3

_MISSION_INTERPRETATIONS = {
    "flex.dataset.snapshot": (
        "This operation is a source-table inventory. It can establish the scope of the retained FLEX records, but it does not establish a flame-spread outcome, material ranking, or mission qualification."
    ),
    "flex.outcomes.by_fuel": (
        "Source-reported outcome counts can help identify fuel groups for follow-up controlled combustion research. Unadjusted group counts do not establish causal fuel effects or comparative fire safety."
    ),
    "flex.burning_rate.exact_by_fuel": (
        "Exact finite burning-rate summaries can help prioritize condition-specific follow-up analysis. The unadjusted summaries do not qualify a material, establish a causal fuel effect, or support an operational safety conclusion."
    ),
    "flex.measurement_quality": (
        "Measurement-quality coverage can guide source-data review and future measurement planning. Quality labels alone do not establish instrument calibration validity or physical measurement accuracy."
    ),
    "flex.oxygen_cohort_sensitivity": (
        "The fixed and broad oxygen cohorts can reveal sensitivity of descriptive ordering to cohort definition. Because the cohorts overlap, this comparison does not isolate a causal oxygen effect or provide independent cohort replication."
    ),
    "psi25.bass_ii.v4.snapshot": (
        "The BASS-II snapshot identifies evidence coverage across three separately maintained gas metrics. It can help prioritize metric-specific follow-up research, but cannot support a composite score or cross-metric ranking."
    ),
}


def _json_copy(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        if len(encoded.encode("utf-8")) > MAX_PACKET_BYTES:
            raise ValueError(f"{label} exceeds the packet size limit")
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{label} is not bounded finite JSON data") from exc


def _verification_summary(report: Any) -> dict[str, Any] | None:
    if not isinstance(report, Mapping) or report.get("status") != "verified":
        return None
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        return None
    if any(not isinstance(row, Mapping) or row.get("status") != "passed" for row in checks):
        return None
    claim_results = report.get("claim_results", [])
    if not isinstance(claim_results, list):
        return None
    return {
        "status": "verified",
        "check_count": len(checks),
        "passed_check_count": len(checks),
        "claim_result_count": len(claim_results),
        "failed_check_count": 0,
        "unverifiable_check_count": 0,
    }


def _verified_ledger(answer: Mapping[str, Any], operation: str,
                     investigation: str, metric: str, data_scope: str) -> dict[str, Any] | None:
    ledger = answer.get("claimLedger")
    if not isinstance(ledger, Mapping):
        return None
    if (
        ledger.get("schema") != CLAIM_LEDGER_SCHEMA
        or ledger.get("ledgerVersion") != 1
        or ledger.get("ledgerStatus") != "verified_provenance"
        or ledger.get("investigationId") != investigation
        or ledger.get("operationId") != operation
        or ledger.get("metric") != metric
        or ledger.get("dataScope") != data_scope
    ):
        return None
    claims = ledger.get("claims")
    if not isinstance(claims, list) or not 1 <= len(claims) <= MAX_CLAIMS:
        return None
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            return None
        claim_id = claim.get("claimId")
        statement = claim.get("statement")
        if (
            not isinstance(claim_id, str) or not claim_id or len(claim_id) > 160
            or claim_id in seen
            or not isinstance(statement, str) or not statement.strip() or len(statement) > 1200
        ):
            return None
        seen.add(claim_id)
    return _json_copy(dict(ledger), "verified Claim Ledger")


def _mission_interpretation(operation: str, metric: str,
                            ledger: Mapping[str, Any]) -> dict[str, Any]:
    statement = _MISSION_INTERPRETATIONS.get(operation)
    if statement is None and operation.startswith("psi25.bass_ii.v4.") and metric in {"o2", "co2", "co"}:
        label = {"o2": "oxygen", "co2": "carbon dioxide", "co": "carbon monoxide"}[metric]
        statement = (
            f"The {label}-specific paired changes and cohort patterns may help prioritize controlled follow-up combustion research. They do not establish causality, material safety, independent physical-sample inference, or transferability to spacecraft, lunar, or Martian conditions."
        )
        if metric == "o2":
            statement += " The source-stated O2 sensor calibration/offset limitation remains material to interpretation."
    if statement is None:
        statement = (
            "This registered result may help define a follow-up research question within its recorded experimental scope. It does not establish mission transferability or an operational fire-safety conclusion."
        )

    claims = ledger.get("claims", [])
    claim_ids = [row["claimId"] for row in claims if isinstance(row, Mapping) and isinstance(row.get("claimId"), str)]
    limitations: list[str] = []
    for row in claims:
        if not isinstance(row, Mapping):
            continue
        values = row.get("limitations", [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value and value not in limitations:
                    limitations.append(value)
    limitations.extend([
        "Mission transferability is not established by the registered dataset or this synthesis.",
        "No causal inference, predictive model, cross-investigation pooling, or operational fire-safety recommendation was produced.",
        "Scholarly metadata/abstracts are discovery references and have not been independently verified as full-text support for individual NASA claims.",
    ])
    limitations = list(dict.fromkeys(limitations))[:24]
    return {
        "status": "bounded_research_context",
        "method": "pre_registered_deterministic_interpretation",
        "generated_with_model": False,
        "statement": statement,
        "basis_claim_ids": claim_ids,
        "limitations": limitations,
        "mission_transferability": "not_established",
        "operational_safety_conclusion": False,
    }


class FireLabResearchSynthesisService:
    """Verify a completed FireLab result, retrieve literature, and assemble a
    source-separated deterministic research brief.

    `research_adapter` must be an existing FireLabResearchAdapter-compatible
    object. In production it is constructed around the existing
    PaperSearchService; that service delegates retrieval to the isolated SIRA
    Research Core worker. The service deliberately has no model or knowledge-
    consolidation dependency.
    """

    def __init__(self, registry: Any, research_adapter: Any,
                 *, verifier: Callable[[Any, Any], dict[str, Any]] | None = None):
        if not callable(getattr(registry, "get", None)):
            raise TypeError("registry must expose get(investigation_id)")
        if not callable(getattr(research_adapter, "retrieve_supporting_literature", None)):
            raise TypeError("research_adapter must expose retrieve_supporting_literature")
        self.registry = registry
        self.research_adapter = research_adapter
        self.verifier = verifier or verify_completed_answer

    @staticmethod
    def _abstention(reason: str, *, verification: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": SCHEMA,
            "status": "abstained",
            "reason": reason,
            "literature_retrieval_performed": False,
            "literature": {"state": "not_run", "source_count": 0, "sources": []},
            "synthesis": {
                "method": "deterministic_source_separated_assembly",
                "generated_with_model": False,
                "model_synthesis_status": "not_run",
                "claim_to_literature_links": [],
                "cross_source_support_status": "not_assessed",
            },
        }
        if verification is not None:
            result["scientific_verification"] = verification
        return result

    def synthesize(self, *, literature_query: str, completed_answer: Mapping[str, Any],
                   refresh: bool = False) -> dict[str, Any]:
        if type(refresh) is not bool:
            raise ValueError("refresh must be boolean")
        if not isinstance(completed_answer, Mapping):
            raise ValueError("completed FireLab answer must be an object")
        if completed_answer.get("status") != "completed":
            return self._abstention("firelab_answer_not_completed")

        investigation = completed_answer.get("investigationId")
        operation = completed_answer.get("analysisId")
        metric = completed_answer.get("metric", "")
        data_scope = completed_answer.get("dataScope")
        spec = OPERATION_SPECS.get(operation) if isinstance(operation, str) else None
        if (
            spec is None or investigation != spec.investigation_id
            or metric != spec.metric or data_scope != spec.data_scope
            or operation.endswith("research_questions")
        ):
            return self._abstention("operation_not_registered_for_measurement_synthesis")

        entry = self.registry.get(investigation)
        report = self.verifier(entry, completed_answer)
        verification = _verification_summary(report)
        if verification is None:
            return self._abstention("independent_scientific_verification_not_passed")

        ledger = _verified_ledger(completed_answer, operation, investigation, metric, data_scope)
        if ledger is None:
            return self._abstention("verified_claim_ledger_required", verification=verification)

        # This is the first point at which the adapter may consult PaperSearchService.
        research_packet = self.research_adapter.retrieve_supporting_literature(
            query=literature_query,
            completed_answer=completed_answer,
            refresh=refresh,
        )
        if not isinstance(research_packet, Mapping) or research_packet.get("schema") != "sira.firelab.research_evidence_packet.v1":
            raise ResearchAdapterError("research adapter returned an unsupported packet")
        dataset_context = research_packet.get("dataset_context")
        if not isinstance(dataset_context, Mapping) or (
            dataset_context.get("investigation_id") != investigation
            or dataset_context.get("operation_id") != operation
            or dataset_context.get("metric") != metric
            or dataset_context.get("data_scope") != data_scope
        ):
            raise ResearchAdapterError("research packet context does not match the verified FireLab answer")
        literature = research_packet.get("literature")
        if not isinstance(literature, Mapping):
            raise ResearchAdapterError("research packet literature section is malformed")
        sources = literature.get("sources")
        if not isinstance(sources, list) or len(sources) > MAX_PAPERS:
            raise ResearchAdapterError("research packet source collection is malformed")
        if any(not isinstance(row, Mapping) for row in sources):
            raise ResearchAdapterError("research packet contains a malformed source")

        state = literature.get("state")
        partial = literature.get("partial") is True
        if sources and state in {"fresh", "cache_hit"} and not partial:
            status = "completed"
        elif sources and state == "cache_stale":
            status = "limited_stale_literature"
        elif sources and partial:
            status = "limited_partial_literature"
        else:
            status = "limited_no_literature"

        literature_rows = []
        for source in sources:
            row = _json_copy(dict(source), "scholarly source")
            row["claim_support_status"] = "not_assessed"
            literature_rows.append(row)

        claims = ledger["claims"]
        dataset_claims = []
        for claim in claims:
            dataset_claims.append({
                "claim_id": claim.get("claimId"),
                "claim_type": claim.get("claimType"),
                "statement": claim.get("statement"),
                "result": claim.get("result"),
                "metric": claim.get("metric"),
                "unit": claim.get("unit"),
                "cohort": claim.get("cohort"),
                "evidence_references": claim.get("evidenceReferences", []),
                "record_lineage": claim.get("recordLineage", {}),
                "quality_dimensions": claim.get("qualityDimensions", {}),
                "limitations": claim.get("limitations", []),
                "interpretation_status": claim.get("interpretationStatus"),
            })

        packet = {
            "schema": SCHEMA,
            "status": status,
            "reason": None if status == "completed" else "literature_retrieval_limited_or_empty",
            "scientific_verification": verification,
            "dataset_context": {
                "investigation_id": investigation,
                "source_release": ledger.get("sourceRelease"),
                "operation_id": operation,
                "metric": metric,
                "data_scope": data_scope,
                "sample_size": completed_answer.get("sampleSize"),
                "claim_ledger_status": ledger.get("ledgerStatus"),
                "claim_count": len(dataset_claims),
            },
            "dataset_claims": dataset_claims,
            "literature": {
                "query": literature.get("query"),
                "state": state,
                "retrieved_at": literature.get("retrieved_at"),
                "providers": literature.get("providers", []),
                "partial": partial,
                "source_count": len(literature_rows),
                "sources": literature_rows,
                "evidence_level": "discovery_metadata_and_optional_abstract_only",
            },
            "synthesis": {
                "method": "deterministic_source_separated_assembly",
                "generated_with_model": False,
                "model_synthesis_status": "not_run_by_default_no_metered_model_authority",
                "claim_to_literature_links": [],
                "cross_source_support_status": "not_assessed",
                "literature_verifies_nasa_measurements": False,
                "cross_investigation_pooling_performed": False,
                "causal_inference_performed": False,
            },
            "mission_interpretation": _mission_interpretation(operation, metric, ledger),
            "verification_boundary": {
                "paper_metadata_independently_verified": False,
                "full_text_review_performed": False,
                "literature_claim_support_assessed": False,
                "scientific_truth_established": False,
                "mission_transferability_established": False,
                "operational_fire_safety_conclusion": False,
            },
            "limitations": list(research_packet.get("limitations", [])) + [
                "The NASA dataset claims are independently checked by the FireLab verifier; the scholarly records are not a second verification of those measurements.",
                "A paper title, abstract, DOI, or provider metadata is not equivalent to reviewed full text or a validated experimental result.",
                "No SIRA model synthesis or persistent Knowledge Consolidation write was performed.",
            ],
        }
        return _json_copy(packet, "FireLab research synthesis")
