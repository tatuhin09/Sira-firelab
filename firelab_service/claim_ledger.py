"""Pure, deterministic SIRA FireLab Claim Ledger v1 contract.

This module validates runtime claim-ledger structures against an execution
context supplied by the already-validated Scientific Planner, answer payload,
and existing verified Evidence Registry. It deliberately performs no file,
network, database, LLM, or scientific-calculation operations.

Important: a passing ledger means provenance and structural lineage checks
passed against the supplied trusted context. It does NOT prove scientific
truth, causality, independent replication, safety, or mission transferability.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence


CLAIM_LEDGER_SCHEMA = "sira.firelab.claim_ledger.v1"
CLAIM_LEDGER_VERSION = 1
LEDGER_STATUS_VERIFIED_PROVENANCE = "verified_provenance"

PSI69_ID = "psi69-flex-v5"
PSI25_ID = "psi25-bass-ii-v4"
METRICS = frozenset({"o2", "co2", "co"})

CLAIM_TYPES = frozenset({
    "source_table_count",
    "descriptive_summary",
    "measurement_quality_observation",
    "descriptive_cohort_finding",
    "observed_cohort_comparison",
})

INTERPRETATION_STATUSES = frozenset({
    "source_reported",
    "descriptive_only",
    "descriptive_with_limitations",
    "quality_observation",
})

EVIDENCE_REFERENCE_IDS = MappingProxyType({
    PSI69_ID: frozenset({
        "psi69.source_manifest", "psi69.records", "psi69.quality_report",
    }),
    PSI25_ID: frozenset({
        "psi25-source-csv", "psi25-canonical-records", "psi25-paired-analysis",
        "psi25-findings", "psi25-synthesis",
    }),
})


@dataclass(frozen=True)
class OperationSpec:
    investigation_id: str
    metric: str
    data_scope: str
    claim_types: frozenset[str]
    allows_empty_claims: bool = False


# Exact backend operation allowlist: 5 PSI-69 operations + 11 PSI-25
# operations. Prefix or wildcard matching is intentionally not supported.
OPERATION_SPECS = MappingProxyType({
    "flex.dataset.snapshot": OperationSpec(PSI69_ID, "", "all-records", frozenset({"source_table_count"})),
    "flex.outcomes.by_fuel": OperationSpec(PSI69_ID, "", "all-records", frozenset({"source_table_count"})),
    "flex.burning_rate.exact_by_fuel": OperationSpec(PSI69_ID, "", "exact-burning-rate", frozenset({"descriptive_summary"})),
    "flex.measurement_quality": OperationSpec(PSI69_ID, "", "quality-summary", frozenset({"measurement_quality_observation"})),
    "flex.oxygen_cohort_sensitivity": OperationSpec(PSI69_ID, "", "selected-records", frozenset({"observed_cohort_comparison"})),
    "psi25.bass_ii.v4.snapshot": OperationSpec(PSI25_ID, "", "all-records", frozenset({"source_table_count", "descriptive_summary"})),
    "psi25.bass_ii.v4.research_questions": OperationSpec(PSI25_ID, "", "research-questions", frozenset(), True),
    "psi25.bass_ii.v4.o2.insights": OperationSpec(PSI25_ID, "o2", "cohort-evidence", frozenset({"descriptive_cohort_finding"})),
    "psi25.bass_ii.v4.o2.ranking": OperationSpec(PSI25_ID, "o2", "cohort-evidence", frozenset({"descriptive_cohort_finding"})),
    "psi25.bass_ii.v4.o2.research_questions": OperationSpec(PSI25_ID, "o2", "research-questions", frozenset(), True),
    "psi25.bass_ii.v4.co2.insights": OperationSpec(PSI25_ID, "co2", "cohort-evidence", frozenset({"descriptive_cohort_finding"})),
    "psi25.bass_ii.v4.co2.ranking": OperationSpec(PSI25_ID, "co2", "cohort-evidence", frozenset({"descriptive_cohort_finding"})),
    "psi25.bass_ii.v4.co2.research_questions": OperationSpec(PSI25_ID, "co2", "research-questions", frozenset(), True),
    "psi25.bass_ii.v4.co.insights": OperationSpec(PSI25_ID, "co", "cohort-evidence", frozenset({"descriptive_cohort_finding"})),
    "psi25.bass_ii.v4.co.ranking": OperationSpec(PSI25_ID, "co", "cohort-evidence", frozenset({"descriptive_cohort_finding"})),
    "psi25.bass_ii.v4.co.research_questions": OperationSpec(PSI25_ID, "co", "research-questions", frozenset(), True),
})

MAX_CLAIMS = 30
MAX_EVIDENCE_REFERENCES = 10
MAX_PSI25_RECORD_KEYS_PER_LIST = 129
MAX_PSI25_RECORD_KEYS_TOTAL = 129
MAX_PSI69_RECORD_IDS_PER_LIST = 300
MAX_LIMITATIONS = 24
MAX_STATEMENT_LENGTH = 1200
MAX_SELECTION_RULE_LENGTH = 300
MAX_ID_LENGTH = 80
MAX_RESULT_DEPTH = 6
MAX_RESULT_NODES = 256
MAX_RESULT_COLLECTION_ITEMS = 129
MAX_RESULT_STRING_LENGTH = 500

_HASH_RE = re.compile(r"^[a-f0-9]{64}$", re.I)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_RESULT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_RECORD_KEY_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,200}$")
_FORBIDDEN_SCORE_KEY_RE = re.compile(r"(?:^|_)(?:confidence|score|grade)(?:_|$)", re.I)


class ClaimLedgerError(ValueError):
    """Raised when a claim ledger is malformed, mismatched, or unsupported."""


@dataclass(frozen=True)
class ClaimLedgerContext:
    """Trusted execution context required to build or validate one ledger.

    The caller must populate this context from the already-validated
    ScientificPlan, the completed answer, the existing EvidenceRegistry and
    verified PSI-69 bundle. This module does not independently verify files or
    SHA-256 digests; it checks that the ledger exactly matches this context.
    """

    investigation_id: str
    source_release: str
    operation_id: str
    metric: str
    data_scope: str
    evidence_hashes: Mapping[str, str]
    upstream_verification: str = "verified"
    answer_status: str = "completed"
    execution_allowed: bool = True
    allowed_record_keys: frozenset[str] = frozenset()
    allowed_record_ids: frozenset[int] = frozenset()
    expected_claim_ids: frozenset[str] | None = None
    expected_record_lineage: Mapping[str, Mapping[str, Sequence[Any]]] | None = None

    def __post_init__(self) -> None:
        try:
            copied_hashes = dict(self.evidence_hashes)
            copied_keys = frozenset(self.allowed_record_keys)
            copied_ids = frozenset(self.allowed_record_ids)
            copied_claim_ids = None if self.expected_claim_ids is None else frozenset(self.expected_claim_ids)
            copied_lineage = None
            if self.expected_record_lineage is not None:
                if not isinstance(self.expected_record_lineage, Mapping):
                    raise TypeError("expected record lineage must be a mapping")
                copied_lineage = {}
                for claim_id, lineage in self.expected_record_lineage.items():
                    if not isinstance(lineage, Mapping):
                        raise TypeError("expected record lineage entry must be a mapping")
                    copied_items = {}
                    for key, items in lineage.items():
                        if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
                            raise TypeError("expected record lineage values must be sequences")
                        copied_items[key] = tuple(items)
                    copied_lineage[claim_id] = MappingProxyType(copied_items)
        except (TypeError, ValueError) as exc:
            raise ClaimLedgerError("claim-ledger context collections are malformed") from exc
        object.__setattr__(self, "evidence_hashes", MappingProxyType(copied_hashes))
        object.__setattr__(self, "allowed_record_keys", copied_keys)
        object.__setattr__(self, "allowed_record_ids", copied_ids)
        object.__setattr__(self, "expected_claim_ids", copied_claim_ids)
        object.__setattr__(self, "expected_record_lineage", None if copied_lineage is None else MappingProxyType(copied_lineage))


def _fail(message: str) -> None:
    raise ClaimLedgerError(message)


def _is_plain_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and not isinstance(value, (str, bytes, bytearray))


def _bounded_text(value: Any, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(f"{label} must be a string")
    if len(value) > maximum:
        _fail(f"{label} exceeds {maximum} characters")
    if not allow_empty and not value:
        _fail(f"{label} must not be empty")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        _fail(f"{label} contains control characters")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{label} must be a nonnegative integer")
    return value


def _copy_json_value(value: Any) -> Any:
    """Return a detached copy of an already validated JSON-compatible value."""
    if isinstance(value, Mapping):
        return {key: _copy_json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json_value(child) for child in value]
    return value


def _validate_json_value(value: Any, *, label: str, depth: int, counter: list[int]) -> None:
    counter[0] += 1
    if counter[0] > MAX_RESULT_NODES:
        _fail(f"{label} contains too many nested values")
    if depth > MAX_RESULT_DEPTH:
        _fail(f"{label} exceeds maximum nesting depth")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > 2**63 - 1:
            _fail(f"{label} contains an out-of-range integer")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(f"{label} contains a non-finite number")
        return
    if isinstance(value, str):
        _bounded_text(value, label, MAX_RESULT_STRING_LENGTH, allow_empty=True)
        return
    if isinstance(value, Mapping):
        if len(value) > 40:
            _fail(f"{label} object has too many fields")
        for key, child in value.items():
            if not isinstance(key, str) or not _RESULT_KEY_RE.fullmatch(key):
                _fail(f"{label} contains an invalid object key")
            if _FORBIDDEN_SCORE_KEY_RE.search(key):
                _fail(f"{label} must not contain a composite confidence/quality score")
            _validate_json_value(child, label=f"{label}.{key}", depth=depth + 1, counter=counter)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_RESULT_COLLECTION_ITEMS:
            _fail(f"{label} array exceeds its item limit")
        for index, child in enumerate(value):
            _validate_json_value(child, label=f"{label}[{index}]", depth=depth + 1, counter=counter)
        return
    _fail(f"{label} contains a non-JSON value")


def _validate_context(context: ClaimLedgerContext) -> OperationSpec:
    if not isinstance(context, ClaimLedgerContext):
        _fail("a ClaimLedgerContext from the validated execution path is required")
    spec = OPERATION_SPECS.get(context.operation_id)
    if spec is None:
        _fail("operation is not registered for the Claim Ledger")
    if context.investigation_id != spec.investigation_id:
        _fail("investigation does not match the registered operation")
    if context.metric != spec.metric:
        _fail("metric does not match the registered operation")
    if context.data_scope != spec.data_scope:
        _fail("data scope does not match the registered operation")
    _bounded_text(context.source_release, "source release", 120)
    if context.upstream_verification != "verified":
        _fail("upstream source/artifact verification has not passed")
    if context.answer_status != "completed" or context.execution_allowed is not True:
        _fail("claim ledgers are forbidden for abstained or non-executable responses")
    allowed_refs = EVIDENCE_REFERENCE_IDS[spec.investigation_id]
    if not isinstance(context.evidence_hashes, Mapping):
        _fail("verified evidence hash map is malformed")
    for reference_id, digest in context.evidence_hashes.items():
        if reference_id not in allowed_refs:
            _fail("context contains an unapproved evidence reference")
        if not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
            _fail("context contains an invalid evidence SHA-256")
    for key in context.allowed_record_keys:
        if not isinstance(key, str) or not _RECORD_KEY_RE.fullmatch(key):
            _fail("context contains an invalid canonical record key")
    for record_id in context.allowed_record_ids:
        if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0:
            _fail("context contains an invalid source record ID")
    if context.expected_claim_ids is not None:
        for claim_id in context.expected_claim_ids:
            if not isinstance(claim_id, str) or not _TOKEN_RE.fullmatch(claim_id):
                _fail("context contains an invalid expected claim ID")
    if context.expected_record_lineage is not None:
        for claim_id, lineage in context.expected_record_lineage.items():
            if not isinstance(claim_id, str) or not _TOKEN_RE.fullmatch(claim_id):
                _fail("context contains an invalid expected record-lineage claim ID")
            lineage_fields = set(lineage.keys())
            if lineage_fields == {"supportingRecordKeys", "excludedRecordKeys"}:
                expected_items = tuple(lineage["supportingRecordKeys"]) + tuple(lineage["excludedRecordKeys"])
                if context.investigation_id != PSI25_ID or any(not isinstance(item, str) or item not in context.allowed_record_keys for item in expected_items):
                    _fail("context contains unverified expected canonical record keys")
                if len(set(expected_items)) != len(expected_items):
                    _fail("context contains duplicate expected canonical record keys")
            elif lineage_fields == {"supportingRecordIds", "excludedRecordIds"}:
                expected_items = tuple(lineage["supportingRecordIds"]) + tuple(lineage["excludedRecordIds"])
                if context.investigation_id != PSI69_ID or any(isinstance(item, bool) or not isinstance(item, int) or item not in context.allowed_record_ids for item in expected_items):
                    _fail("context contains unverified expected source record IDs")
                if len(set(expected_items)) != len(expected_items):
                    _fail("context contains duplicate expected source record IDs")
            else:
                _fail("context contains an invalid expected record-lineage shape")
    return spec


def _validate_evidence_references(value: Any, context: ClaimLedgerContext, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_EVIDENCE_REFERENCES:
        _fail(f"{label} must contain 1 to {MAX_EVIDENCE_REFERENCES} references")
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not _is_plain_mapping(item) or set(item.keys()) != {"referenceId", "sha256"}:
            _fail(f"{label}[{index}] has an invalid reference shape")
        reference_id = _bounded_text(item.get("referenceId"), f"{label}[{index}].referenceId", 100)
        digest = item.get("sha256")
        if reference_id in seen:
            _fail(f"{label} contains a duplicate reference ID")
        seen.add(reference_id)
        if reference_id not in context.evidence_hashes:
            _fail(f"{label} references evidence outside the verified context")
        if not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
            _fail(f"{label}[{index}].sha256 is invalid")
        if digest.lower() != context.evidence_hashes[reference_id].lower():
            _fail(f"{label} SHA-256 does not match the verified context")
        result.append({"referenceId": reference_id, "sha256": digest.lower()})
    return result


def _validate_record_lineage(value: Any, context: ClaimLedgerContext, claim_type: str, claim_id: str) -> tuple[dict[str, Any], str]:
    if not _is_plain_mapping(value):
        _fail("recordLineage must be an object")
    mode = value.get("mode")
    if value.get("complete") is not True:
        _fail("record lineage must explicitly be complete")
    supporting_count = _nonnegative_int(value.get("supportingCount"), "recordLineage.supportingCount")
    excluded_count = _nonnegative_int(value.get("excludedCount"), "recordLineage.excludedCount")

    if mode == "explicit_canonical_record_keys":
        expected_fields = {"mode", "supportingRecordKeys", "excludedRecordKeys", "supportingCount", "excludedCount", "complete"}
        if set(value.keys()) != expected_fields:
            _fail("explicit canonical record lineage has an invalid shape")
        if context.investigation_id != PSI25_ID or claim_type != "descriptive_cohort_finding":
            _fail("explicit canonical record keys are restricted to PSI-25 cohort findings")
        supporting = value.get("supportingRecordKeys")
        excluded = value.get("excludedRecordKeys")
        if not isinstance(supporting, list) or not isinstance(excluded, list):
            _fail("canonical record key lists must be arrays")
        if len(supporting) > MAX_PSI25_RECORD_KEYS_PER_LIST or len(excluded) > MAX_PSI25_RECORD_KEYS_PER_LIST:
            _fail("canonical record key list exceeds the 129-record bound")
        if len(supporting) + len(excluded) > MAX_PSI25_RECORD_KEYS_TOTAL:
            _fail("combined canonical record lineage exceeds 129 records")
        all_keys = supporting + excluded
        if supporting_count != len(supporting) or excluded_count != len(excluded):
            _fail("canonical record lineage counts do not match its lists")
        if any(not isinstance(key, str) or not _RECORD_KEY_RE.fullmatch(key) for key in all_keys):
            _fail("canonical record lineage contains an invalid record key")
        if len(set(all_keys)) != len(all_keys):
            _fail("canonical record lineage contains duplicate keys")
        if not set(all_keys).issubset(context.allowed_record_keys):
            _fail("canonical record lineage contains an unverified record key")
        expected = (context.expected_record_lineage or {}).get(claim_id)
        if expected is None:
            _fail("PSI-25 cohort claim has no verified expected record-lineage mapping")
        if tuple(supporting) != tuple(expected.get("supportingRecordKeys", ())) or tuple(excluded) != tuple(expected.get("excludedRecordKeys", ())):
            _fail("PSI-25 cohort record lineage does not exactly match verified findings/synthesis evidence")
        return ({
            "mode": mode,
            "supportingRecordKeys": list(supporting),
            "excludedRecordKeys": list(excluded),
            "supportingCount": supporting_count,
            "excludedCount": excluded_count,
            "complete": True,
        }, "complete")

    if mode == "registered_selection_scope":
        expected_fields = {"mode", "supportingRecordIds", "excludedRecordIds", "supportingCount", "excludedCount", "selectionRule", "complete"}
        if set(value.keys()) != expected_fields:
            _fail("registered selection-scope lineage has an invalid shape")
        if context.investigation_id != PSI69_ID and context.operation_id != "psi25.bass_ii.v4.snapshot":
            _fail("registered selection-scope lineage is not valid for this operation")
        supporting = value.get("supportingRecordIds")
        excluded = value.get("excludedRecordIds")
        if not isinstance(supporting, list) or not isinstance(excluded, list):
            _fail("source record ID lists must be arrays")
        if len(supporting) > MAX_PSI69_RECORD_IDS_PER_LIST or len(excluded) > MAX_PSI69_RECORD_IDS_PER_LIST:
            _fail("source record ID list exceeds the 300-record bound")
        all_ids = supporting + excluded
        if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in all_ids):
            _fail("registered selection scope contains an invalid source record ID")
        if len(set(all_ids)) != len(all_ids):
            _fail("registered selection scope contains duplicate source record IDs")
        if all_ids and not set(all_ids).issubset(context.allowed_record_ids):
            _fail("registered selection scope contains an unverified source record ID")
        if supporting and len(supporting) != supporting_count:
            _fail("supporting source record IDs do not match supportingCount")
        if excluded and len(excluded) != excluded_count:
            _fail("excluded source record IDs do not match excludedCount")
        selection_rule = _bounded_text(value.get("selectionRule"), "recordLineage.selectionRule", MAX_SELECTION_RULE_LENGTH)
        if (context.operation_id == "flex.oxygen_cohort_sensitivity"
                or (context.investigation_id == PSI69_ID and context.expected_record_lineage is not None)):
            expected = (context.expected_record_lineage or {}).get(claim_id)
            if expected is None:
                _fail("PSI-69 claim has no verified selected-record mapping")
            if tuple(supporting) != tuple(expected.get("supportingRecordIds", ())) or tuple(excluded) != tuple(expected.get("excludedRecordIds", ())):
                _fail("PSI-69 record IDs do not match the verified executed selection")
        return ({
            "mode": mode,
            "supportingRecordIds": list(supporting),
            "excludedRecordIds": list(excluded),
            "supportingCount": supporting_count,
            "excludedCount": excluded_count,
            "selectionRule": selection_rule,
            "complete": True,
        }, "aggregate_scope")

    if mode == "not_applicable":
        expected_fields = {"mode", "supportingCount", "excludedCount", "complete"}
        if set(value.keys()) != expected_fields:
            _fail("not-applicable record lineage has an invalid shape")
        if supporting_count != 0 or excluded_count != 0:
            _fail("not-applicable record lineage must have zero counts")
        return ({"mode": mode, "supportingCount": 0, "excludedCount": 0, "complete": True}, "not_applicable")

    _fail("record lineage mode is not registered")


def _validate_quality_dimensions(value: Any, expected_lineage: str, claim_type: str) -> dict[str, Any]:
    required = {
        "sourceIntegrity", "artifactIntegrity", "recordLineageIntegrity",
        "methodReproducibility", "statisticalScope", "measurementValidity",
        "sampleIndependence", "independentReplication", "missionTransferability",
        "scientificTruth",
    }
    if not _is_plain_mapping(value) or set(value.keys()) != required:
        _fail("qualityDimensions must match the complete v1 dimension contract")
    enums = {
        "sourceIntegrity": {"verified", "not_applicable", "unavailable"},
        "artifactIntegrity": {"verified", "not_applicable", "unavailable"},
        "recordLineageIntegrity": {"complete", "aggregate_scope", "not_applicable", "failed"},
        "methodReproducibility": {"deterministic_registered_method", "precomputed_deterministic_artifact"},
        "statisticalScope": {"descriptive_only", "source_count_only", "quality_count_only"},
        "sampleIndependence": {"not_established", "potential_dependence_flagged", "not_applicable"},
        "independentReplication": {"not_performed"},
        "missionTransferability": {"not_established"},
        "scientificTruth": {"not_established_by_integrity_checks"},
    }
    result: dict[str, Any] = {}
    for key, allowed in enums.items():
        item = value.get(key)
        if not isinstance(item, str) or item not in allowed:
            _fail(f"qualityDimensions.{key} is not an approved value")
        result[key] = item
    if result["sourceIntegrity"] != "verified" or result["artifactIntegrity"] != "verified":
        _fail("verified-provenance ledger claims require verified source and artifact integrity")
    if result["recordLineageIntegrity"] != expected_lineage:
        _fail("record-lineage quality dimension does not match recordLineage")
    expected_stat_scope = {
        "source_table_count": "source_count_only",
        "measurement_quality_observation": "quality_count_only",
        "descriptive_summary": "descriptive_only",
        "descriptive_cohort_finding": "descriptive_only",
        "observed_cohort_comparison": "descriptive_only",
    }[claim_type]
    if result["statisticalScope"] != expected_stat_scope:
        _fail("statisticalScope does not match the claim type")
    validity = value.get("measurementValidity")
    if not isinstance(validity, list) or len(validity) > MAX_LIMITATIONS:
        _fail("qualityDimensions.measurementValidity must be a bounded array")
    clean_validity = []
    for index, flag in enumerate(validity):
        clean_validity.append(_bounded_text(flag, f"measurementValidity[{index}]", 300))
    result["measurementValidity"] = clean_validity
    return result


def _validate_claim(value: Any, index: int, context: ClaimLedgerContext, spec: OperationSpec) -> dict[str, Any]:
    label = f"claims[{index}]"
    required = {
        "claimId", "claimType", "statement", "result", "metric", "unit", "cohort",
        "evidenceReferences", "recordLineage", "qualityDimensions", "limitations",
        "interpretationStatus",
    }
    if not _is_plain_mapping(value) or set(value.keys()) != required:
        _fail(f"{label} does not match the strict claim-entry v1 contract")
    claim_id = _bounded_text(value.get("claimId"), f"{label}.claimId", MAX_ID_LENGTH)
    if not _TOKEN_RE.fullmatch(claim_id):
        _fail(f"{label}.claimId has an invalid format")
    claim_type = value.get("claimType")
    if not isinstance(claim_type, str) or claim_type not in CLAIM_TYPES:
        _fail(f"{label}.claimType is not allowlisted")
    if claim_type not in spec.claim_types:
        _fail(f"{label}.claimType is not permitted by this registered operation")
    if context.investigation_id == PSI25_ID and claim_type == "descriptive_cohort_finding":
        if context.expected_claim_ids is None or claim_id not in context.expected_claim_ids:
            _fail(f"{label}.claimId does not resolve to a verified synthesis insight ID")
    if context.expected_claim_ids is not None and claim_type == "descriptive_cohort_finding" and claim_id not in context.expected_claim_ids:
        _fail(f"{label}.claimId is not present in the selected verified insight-card set")

    statement = _bounded_text(value.get("statement"), f"{label}.statement", MAX_STATEMENT_LENGTH)
    result = value.get("result")
    if not _is_plain_mapping(result):
        _fail(f"{label}.result must be a structured object")
    _validate_json_value(result, label=f"{label}.result", depth=0, counter=[0])
    metric = value.get("metric")
    if not isinstance(metric, str) or metric not in {"", *METRICS}:
        _fail(f"{label}.metric is invalid")
    if spec.metric and metric != spec.metric:
        _fail(f"{label}.metric does not match the registered operation")
    if context.investigation_id == PSI69_ID and metric:
        _fail(f"{label}.metric must remain empty for PSI-69 operation claims")
    if context.investigation_id == PSI25_ID and spec.metric and metric != spec.metric:
        _fail(f"{label}.metric crosses the selected PSI-25 metric scope")
    if context.operation_id == "psi25.bass_ii.v4.snapshot" and claim_type == "descriptive_summary" and metric not in METRICS:
        _fail(f"{label}.metric must identify one separate metric for a PSI-25 summary claim")
    unit = _bounded_text(value.get("unit"), f"{label}.unit", 80, allow_empty=True)

    cohort = value.get("cohort")
    if cohort is not None:
        expected_cohort_fields = {"pi", "materialClass", "flowRestrictorCode"}
        if not _is_plain_mapping(cohort) or set(cohort.keys()) != expected_cohort_fields:
            _fail(f"{label}.cohort has an invalid shape")
        cohort_result = {}
        for key in ("pi", "materialClass", "flowRestrictorCode"):
            item = cohort.get(key)
            if item is not None:
                item = _bounded_text(item, f"{label}.cohort.{key}", 160, allow_empty=True)
            cohort_result[key] = item
    else:
        cohort_result = None
    if claim_type == "descriptive_cohort_finding" and cohort_result is None:
        _fail(f"{label}.cohort is required for a cohort finding")

    evidence = _validate_evidence_references(value.get("evidenceReferences"), context, f"{label}.evidenceReferences")
    lineage, lineage_quality = _validate_record_lineage(value.get("recordLineage"), context, claim_type, claim_id)
    if context.investigation_id == PSI25_ID and claim_type == "descriptive_cohort_finding" and lineage["mode"] != "explicit_canonical_record_keys":
        _fail(f"{label} PSI-25 cohort findings require explicit canonical record keys")
    if context.investigation_id == PSI69_ID and lineage["mode"] != "registered_selection_scope":
        _fail(f"{label} PSI-69 claims require a registered selection scope")
    quality = _validate_quality_dimensions(value.get("qualityDimensions"), lineage_quality, claim_type)

    limitations = value.get("limitations")
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= MAX_LIMITATIONS:
        _fail(f"{label}.limitations must contain 1 to {MAX_LIMITATIONS} items")
    clean_limitations = [
        _bounded_text(item, f"{label}.limitations[{position}]", 500)
        for position, item in enumerate(limitations)
    ]
    status = value.get("interpretationStatus")
    if not isinstance(status, str) or status not in INTERPRETATION_STATUSES:
        _fail(f"{label}.interpretationStatus is not allowlisted")
    if claim_type == "descriptive_cohort_finding" and status not in {"descriptive_only", "descriptive_with_limitations"}:
        _fail(f"{label} cohort finding must remain descriptive")

    return {
        "claimId": claim_id,
        "claimType": claim_type,
        "statement": statement,
        "result": _copy_json_value(result),
        "metric": metric,
        "unit": unit,
        "cohort": cohort_result,
        "evidenceReferences": evidence,
        "recordLineage": lineage,
        "qualityDimensions": quality,
        "limitations": clean_limitations,
        "interpretationStatus": status,
    }


def validate_claim_ledger(value: Any, context: ClaimLedgerContext) -> dict[str, Any]:
    """Validate and return a detached, bounded Claim Ledger v1 dictionary.

    `context` must be assembled by a trusted caller from a validated plan,
    completed answer and existing verified evidence registry. The returned
    `verified_provenance` status asserts only these provenance/lineage checks.
    """
    spec = _validate_context(context)
    required = {
        "schema", "ledgerVersion", "investigationId", "sourceRelease",
        "operationId", "metric", "dataScope", "ledgerStatus", "claims",
    }
    if not _is_plain_mapping(value) or set(value.keys()) != required:
        _fail("ledger does not match the strict top-level v1 contract")
    if value.get("schema") != CLAIM_LEDGER_SCHEMA:
        _fail("unknown Claim Ledger schema")
    version = value.get("ledgerVersion")
    if isinstance(version, bool) or version != CLAIM_LEDGER_VERSION:
        _fail("unsupported Claim Ledger version")
    if value.get("investigationId") != context.investigation_id:
        _fail("ledger investigation does not match validated execution context")
    if value.get("sourceRelease") != context.source_release:
        _fail("ledger source release does not match verified source metadata")
    if value.get("operationId") != context.operation_id:
        _fail("ledger operation does not match executed operation")
    if value.get("metric") != context.metric:
        _fail("ledger metric does not match validated scientific plan")
    if value.get("dataScope") != context.data_scope:
        _fail("ledger data scope does not match executed answer")
    if value.get("ledgerStatus") != LEDGER_STATUS_VERIFIED_PROVENANCE:
        _fail("ledger status must be verified_provenance after upstream checks")
    claims = value.get("claims")
    if not isinstance(claims, list) or len(claims) > MAX_CLAIMS:
        _fail(f"claims must be an array with at most {MAX_CLAIMS} entries")
    if not claims and not spec.allows_empty_claims:
        _fail("this operation must produce at least one structured claim")
    if claims and spec.allows_empty_claims:
        _fail("research-question retrieval must not be converted into claim entries")
    normalized_claims = [_validate_claim(item, index, context, spec) for index, item in enumerate(claims)]
    claim_ids = [item["claimId"] for item in normalized_claims]
    if len(set(claim_ids)) != len(claim_ids):
        _fail("ledger contains duplicate claim IDs")
    return {
        "schema": CLAIM_LEDGER_SCHEMA,
        "ledgerVersion": CLAIM_LEDGER_VERSION,
        "investigationId": context.investigation_id,
        "sourceRelease": context.source_release,
        "operationId": context.operation_id,
        "metric": context.metric,
        "dataScope": context.data_scope,
        "ledgerStatus": LEDGER_STATUS_VERIFIED_PROVENANCE,
        "claims": normalized_claims,
    }


def build_claim_ledger(context: ClaimLedgerContext, claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a deterministic ledger from already-structured trusted claim data.

    The function does not derive statements, interpret evidence, or calculate
    statistics. Callers must construct each typed claim from registered
    deterministic result objects, then this module validates the contract.
    """
    _validate_context(context)
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes, bytearray)):
        _fail("claims must be a sequence of structured entries")
    candidate = {
        "schema": CLAIM_LEDGER_SCHEMA,
        "ledgerVersion": CLAIM_LEDGER_VERSION,
        "investigationId": context.investigation_id,
        "sourceRelease": context.source_release,
        "operationId": context.operation_id,
        "metric": context.metric,
        "dataScope": context.data_scope,
        "ledgerStatus": LEDGER_STATUS_VERIFIED_PROVENANCE,
        "claims": list(claims),
    }
    return validate_claim_ledger(candidate, context)
