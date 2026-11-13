"""Independent deterministic verification for the bounded SIRA FireLab releases.

This module intentionally does not import FireLab calculation engines, PSI-25
builders, SIRA Core, provider/model code, or network/file APIs.  It consumes an
already hash-verified InvestigationEvidence entry and a completed answer.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any

VERIFIER_SCHEMA = "sira.firelab.scientific_verification.v1"
VERIFIER_VERSION = 1
CLAIM_LEDGER_SCHEMA = "sira.firelab.claim_ledger.v1"
PSI69_ID = "psi69-flex-v5"
PSI25_ID = "psi25-bass-ii-v4"
OUTCOME_ORDER = ("Extinction", "Disruption", "Completion")
FIXED_OXYGEN = 0.21
WILSON_Z = 1.959963984540054
PSI25_METRICS = {
    "o2": ("initial_o2", "final_o2", "% by volume", "Oxygen concentration change"),
    "co2": ("initial_co2", "final_co2", "% by volume", "Carbon dioxide concentration change"),
    "co": ("initial_co", "final_co", "ppm", "Carbon monoxide concentration change"),
}

# Exact operation registry copied as a bounded contract, not imported at runtime.
_OPERATION_SPECS: dict[str, tuple[str, str, str]] = {
    "flex.dataset.snapshot": (PSI69_ID, "", "all-records"),
    "flex.outcomes.by_fuel": (PSI69_ID, "", "all-records"),
    "flex.burning_rate.exact_by_fuel": (PSI69_ID, "", "exact-burning-rate"),
    "flex.measurement_quality": (PSI69_ID, "", "quality-summary"),
    "flex.oxygen_cohort_sensitivity": (PSI69_ID, "", "selected-records"),
    "psi25.bass_ii.v4.snapshot": (PSI25_ID, "", "all-records"),
    "psi25.bass_ii.v4.research_questions": (PSI25_ID, "", "research-questions"),
    "psi25.bass_ii.v4.o2.insights": (PSI25_ID, "o2", "cohort-evidence"),
    "psi25.bass_ii.v4.o2.ranking": (PSI25_ID, "o2", "cohort-evidence"),
    "psi25.bass_ii.v4.o2.research_questions": (PSI25_ID, "o2", "research-questions"),
    "psi25.bass_ii.v4.co2.insights": (PSI25_ID, "co2", "cohort-evidence"),
    "psi25.bass_ii.v4.co2.ranking": (PSI25_ID, "co2", "cohort-evidence"),
    "psi25.bass_ii.v4.co2.research_questions": (PSI25_ID, "co2", "research-questions"),
    "psi25.bass_ii.v4.co.insights": (PSI25_ID, "co", "cohort-evidence"),
    "psi25.bass_ii.v4.co.ranking": (PSI25_ID, "co", "cohort-evidence"),
    "psi25.bass_ii.v4.co.research_questions": (PSI25_ID, "co", "research-questions"),
}

_LIMITATIONS = [
    "Verification covers deterministic calculations over the hash-verified records supplied by the evidence registry only.",
    "It does not establish source-document correctness, measurement accuracy, sensor calibration, or scientific truth.",
    "It does not establish independent experimental replication or independent physical-sample counts.",
    "It does not establish causality, prediction, spacecraft transferability, or operational fire-safety suitability.",
    "Scholarly metadata is not measurement evidence and is not used in numerical verification.",
]
_TOLERANCES = {
    "psi69_rel_tol": 1e-12,
    "psi69_abs_tol": 1e-12,
    "psi69_percentage_point_abs_tol": 1e-10,
    "psi25_decimal": "finite Decimal numeric equality; formatting-only differences accepted",
}


class ScientificVerificationError(ValueError):
    """Raised internally for a bounded verifier contract violation."""


def _get(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _is_int(value: Any) -> bool:
    return type(value) is int


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        raise ScientificVerificationError("non_finite_decimal")
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _locale_key(value: Any) -> tuple[str, str]:
    rendered = str(value)
    return rendered.casefold(), rendered.swapcase()


_COMPARE_PATH: ContextVar[str] = ContextVar("firelab_verifier_compare_path", default="$")


def _same_numeric(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Decimal):
        observed = _as_decimal(actual)
        return observed is not None and observed == expected
    if isinstance(expected, float):
        tolerance = 1e-10 if "gapPercentagePoints" in _COMPARE_PATH.get() else 1e-12
        return _finite_number(actual) and math.isclose(
            float(actual), expected, rel_tol=1e-12, abs_tol=tolerance
        )
    if _is_int(expected):
        return _is_int(actual) and actual == expected
    return type(actual) is type(expected) and actual == expected


def _mismatch(actual: Any, expected: Any, path: str = "$") -> str | None:
    """Compare a required expected shape; extra actual mapping keys are ignored."""
    if isinstance(expected, Decimal) or isinstance(expected, float) or _is_int(expected) or isinstance(expected, bool):
        token = _COMPARE_PATH.set(path)
        try:
            return None if _same_numeric(actual, expected) else path
        finally:
            _COMPARE_PATH.reset(token)
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return path
        for key, wanted in expected.items():
            if key not in actual:
                return f"{path}.{key}"
            found = _mismatch(actual[key], wanted, f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            return path
        for index, (found_value, wanted) in enumerate(zip(actual, expected)):
            found = _mismatch(found_value, wanted, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if type(actual) is type(expected) and actual == expected else path


class _Report:
    def __init__(self, investigation: str = "", operation: str = "", metric: str = "", scope: str = ""):
        self.investigation = investigation
        self.operation = operation
        self.metric = metric
        self.scope = scope
        self.checks: list[dict[str, str]] = []
        self.claim_results: list[dict[str, str]] = []

    def add(self, check_id: str, status: str, reason_code: str = "ok") -> None:
        if status not in {"passed", "failed", "unverifiable", "not_applicable"}:
            status, reason_code = "unverifiable", "internal_contract_error"
        if len(self.checks) < 240:
            self.checks.append({"check_id": check_id[:100], "status": status, "reason_code": reason_code[:80]})

    def compare(self, check_id: str, actual: Any, expected: Any, reason_code: str = "numeric_mismatch") -> None:
        mismatch = _mismatch(actual, expected)
        self.add(check_id, "passed" if mismatch is None else "failed", "ok" if mismatch is None else reason_code)

    def missing(self, check_id: str, reason: str = "missing_answer_structure") -> None:
        self.add(check_id, "unverifiable", reason)

    def claim(self, claim_id: str, status: str, reason_code: str = "ok") -> None:
        if len(self.claim_results) < 30:
            self.claim_results.append({"claim_id": str(claim_id)[:128], "status": status, "reason_code": reason_code[:80]})

    def result(self, *, status_override: str | None = None, source_release: str = "", hashes: Mapping[str, str] | None = None) -> dict[str, Any]:
        statuses = {item["status"] for item in self.checks}
        if status_override:
            status = status_override
        elif "failed" in statuses:
            status = "failed"
        elif "unverifiable" in statuses:
            status = "unverifiable"
        elif not statuses or statuses == {"not_applicable"}:
            status = "not_applicable"
        else:
            status = "verified"
        source_context = {"source_release": source_release}
        if hashes:
            source_context["sha256"] = {k: v for k, v in hashes.items() if isinstance(v, str) and len(v) == 64}
        return {
            "schema": VERIFIER_SCHEMA,
            "verifier_version": VERIFIER_VERSION,
            "status": status,
            "investigation_id": self.investigation,
            "operation_id": self.operation,
            "metric": self.metric,
            "data_scope": self.scope,
            "method": "independent_deterministic_recomputation",
            "source_context": source_context,
            "checks": list(self.checks),
            "claim_results": list(self.claim_results),
            "limitations": list(_LIMITATIONS),
            "tolerances": dict(_TOLERANCES),
        }


def _event(answer: Mapping[str, Any], kind: str) -> Mapping[str, Any] | None:
    events = answer.get("events")
    if not isinstance(events, list) or len(events) > 100:
        return None
    for item in events:
        if isinstance(item, Mapping) and item.get("type") == kind:
            return item
    return None


def _event_payload(answer: Mapping[str, Any], kind: str) -> Mapping[str, Any] | None:
    item = _event(answer, kind)
    payload = item.get("payload") if isinstance(item, Mapping) else None
    return payload if isinstance(payload, Mapping) else None


def _source_hashes(entry: Any, iid: str) -> dict[str, str]:
    if iid == PSI69_ID:
        return {
            "psi69.source_manifest": _get(entry, "source_sha256", ""),
            "psi69.records": _get(entry, "records_sha256", ""),
            "psi69.quality_report": _get(entry, "quality_sha256", ""),
        }
    payload = _get(entry, "payload", {})
    artifacts = payload.get("artifact_sha256", {}) if isinstance(payload, Mapping) else {}
    return {
        "psi25-source-csv": _get(entry, "source_sha256", ""),
        "psi25-canonical-records": _get(entry, "records_sha256", ""),
        "psi25-paired-analysis": artifacts.get("paired_analysis", "") if isinstance(artifacts, Mapping) else "",
        "psi25-findings": artifacts.get("findings", "") if isinstance(artifacts, Mapping) else "",
        "psi25-synthesis": artifacts.get("synthesis", "") if isinstance(artifacts, Mapping) else "",
    }


def _validate_ledger(report: _Report, entry: Any, answer: Mapping[str, Any], iid: str, operation: str, metric: str, scope: str) -> Mapping[str, Any] | None:
    ledger = answer.get("claimLedger")
    if not isinstance(ledger, Mapping):
        report.missing("claim_ledger.present", "claim_ledger_mismatch")
        return None
    expected_top = {
        "schema": CLAIM_LEDGER_SCHEMA,
        "ledgerVersion": 1,
        "investigationId": iid,
        "operationId": operation,
        "metric": metric,
        "dataScope": scope,
        "ledgerStatus": "verified_provenance",
    }
    report.compare("claim_ledger.context", ledger, expected_top, "claim_ledger_mismatch")
    claims = ledger.get("claims")
    if not isinstance(claims, list) or len(claims) > 30:
        report.missing("claim_ledger.claims", "claim_ledger_mismatch")
        return None
    expected_hashes = _source_hashes(entry, iid)
    expected_source_release = str(_get(entry, "version", "")) if iid == PSI69_ID else f"PSI-25 {_get(entry, 'title', 'BASS-II')} {_get(entry, 'version', 'Study Version 4')}"
    report.compare("claim_ledger.source_release", ledger.get("sourceRelease"), expected_source_release, "source_lineage_mismatch")
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            report.add(f"claim_ledger.claim_{index}", "unverifiable", "claim_ledger_mismatch")
            continue
        dimensions = claim.get("qualityDimensions")
        lineage = claim.get("recordLineage")
        expected_lineage_quality = (
            "complete" if isinstance(lineage, Mapping) and lineage.get("mode") == "explicit_canonical_record_keys"
            else "aggregate_scope" if isinstance(lineage, Mapping) and lineage.get("mode") == "registered_selection_scope"
            else None
        )
        expected_stat_scope = {
            "source_table_count": "source_count_only",
            "measurement_quality_observation": "quality_count_only",
            "descriptive_summary": "descriptive_only",
            "descriptive_cohort_finding": "descriptive_only",
            "observed_cohort_comparison": "descriptive_only",
        }.get(claim.get("claimType"))
        dimensions_ok = isinstance(dimensions, Mapping) and (
            dimensions.get("scientificTruth") == "not_established_by_integrity_checks"
            and dimensions.get("independentReplication") == "not_performed"
            and dimensions.get("missionTransferability") == "not_established"
            and dimensions.get("sourceIntegrity") == "verified"
            and dimensions.get("artifactIntegrity") == "verified"
            and dimensions.get("recordLineageIntegrity") == expected_lineage_quality
            and dimensions.get("statisticalScope") == expected_stat_scope
        )
        report.add(f"claim_ledger.claim_{index}.scientific_boundary", "passed" if dimensions_ok else "failed",
                   "ok" if dimensions_ok else "scientific_scope_violation")
        references = claim.get("evidenceReferences")
        if not isinstance(references, list) or not 1 <= len(references) <= 8:
            report.add(f"claim_ledger.claim_{index}.references", "unverifiable", "claim_ledger_mismatch")
            continue
        seen: set[str] = set()
        refs_ok = True
        for reference in references:
            if not isinstance(reference, Mapping):
                refs_ok = False
                break
            ref_id = reference.get("referenceId")
            digest = reference.get("sha256")
            if ref_id in seen or ref_id not in expected_hashes or digest != expected_hashes.get(ref_id):
                refs_ok = False
                break
            seen.add(ref_id)
        if iid == PSI69_ID:
            expected_ref_ids = set(expected_hashes)
        elif operation == "psi25.bass_ii.v4.snapshot" and index == 0:
            expected_ref_ids = {"psi25-source-csv", "psi25-canonical-records"}
        else:
            expected_ref_ids = set(expected_hashes)
        if seen != expected_ref_ids:
            refs_ok = False
        report.add(f"claim_ledger.claim_{index}.evidence_hashes", "passed" if refs_ok else "failed", "ok" if refs_ok else "source_lineage_mismatch")
    return ledger


def _record_event(answer: Mapping[str, Any], report: _Report, kind: str, check_id: str) -> Mapping[str, Any] | None:
    item = _event(answer, kind)
    if item is None or item.get("status") not in {"complete", "completed"}:
        report.missing(check_id, "missing_answer_structure")
        return None
    payload = item.get("payload")
    if not isinstance(payload, Mapping):
        report.missing(check_id + ".payload", "missing_answer_structure")
        return None
    report.add(check_id, "passed")
    return payload


# ----------------------------- PSI-69 helpers -----------------------------

def _psi69_records(entry: Any) -> tuple[list[Mapping[str, Any]], Mapping[str, Any], Mapping[str, Any]]:
    payload = _get(entry, "payload", {})
    bundle = payload.get("bundle") if isinstance(payload, Mapping) else None
    if not isinstance(bundle, Mapping):
        raise ScientificVerificationError("missing_verified_source")
    records, quality, manifest = bundle.get("records"), bundle.get("quality"), bundle.get("manifest")
    if (not isinstance(records, list) or len(records) != 274 or not isinstance(quality, Mapping)
            or not isinstance(manifest, Mapping) or manifest.get("recordCount") != 274
            or manifest.get("sourceVersion") != _get(entry, "version")):
        raise ScientificVerificationError("missing_verified_source")
    for bundle_key, entry_key in (("sourceSha256", "source_sha256"), ("recordsSha256", "records_sha256"),
                                  ("qualitySha256", "quality_sha256")):
        if bundle.get(bundle_key) != _get(entry, entry_key):
            raise ScientificVerificationError("source_lineage_mismatch")
    ids: list[int] = []
    for row in records:
        if not isinstance(row, Mapping):
            raise ScientificVerificationError("invalid_source_record")
        value = row.get("testNumber")
        if not _is_int(value) or value <= 0:
            raise ScientificVerificationError("invalid_source_record_id")
        ids.append(value)
    if len(set(ids)) != 274 or _get(entry, "record_count") != 274:
        raise ScientificVerificationError("source_record_lineage_mismatch")
    return records, quality, bundle


def _psi69_fuel(record: Mapping[str, Any]) -> str:
    value = record.get("fuel") or "Unspecified fuel"
    return value if isinstance(value, str) else str(value)


def _psi69_quality(record: Mapping[str, Any], field: str) -> Any:
    quality = record.get("quality")
    return quality.get(field) if isinstance(quality, Mapping) else None


def _psi69_exact(record: Mapping[str, Any], field: str) -> float | None:
    value = record.get(field)
    if _psi69_quality(record, field) != "exact" or not _finite_number(value):
        return None
    return float(value)


def _wilson(successes: int, total: int) -> tuple[float | None, float | None]:
    if total <= 0 or successes < 0 or successes > total:
        return None, None
    p = successes / total
    z2 = WILSON_Z * WILSON_Z
    denominator = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denominator
    margin = WILSON_Z * math.sqrt((p * (1 - p) / total) + (z2 / (4 * total * total))) / denominator
    return (0.0 if successes == 0 else max(0.0, center - margin), 1.0 if successes == total else min(1.0, center + margin))


def _psi69_groups(records: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int], list[str]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_psi69_fuel(record)].append(record)
    groups: list[dict[str, Any]] = []
    outcome_totals = {name: 0 for name in OUTCOME_ORDER}
    unknown: list[str] = []
    fuel_counts: dict[str, int] = {}
    for fuel, rows in grouped.items():
        n = len(rows)
        counts = {name: 0 for name in OUTCOME_ORDER}
        for row in rows:
            label = row.get("testEnd")
            if label in counts:
                counts[label] += 1
            elif isinstance(label, str) and label:
                unknown.append(label)
            else:
                unknown.append("<missing>")
        for name in OUTCOME_ORDER:
            outcome_totals[name] += counts[name]
        summaries = []
        for name in OUTCOME_ORDER:
            low, high = _wilson(counts[name], n)
            summaries.append({"outcome": name, "count": counts[name], "share": counts[name] / n if n else 0.0, "ciLow": low, "ciHigh": high})
        diameters: list[float] = []
        approximate = missing = invalid = 0
        for row in rows:
            if row.get("testEnd") != "Extinction":
                continue
            quality = _psi69_quality(row, "visibleFlameExtinctionDiameterMm")
            value = row.get("visibleFlameExtinctionDiameterMm")
            if quality == "exact" and _finite_number(value):
                diameters.append(float(value))
            elif quality == "approximate":
                approximate += 1
            elif quality == "invalid":
                invalid += 1
            else:
                missing += 1
        diameters.sort()
        middle = len(diameters) // 2
        median = None if not diameters else (diameters[middle] if len(diameters) % 2 else (diameters[middle - 1] + diameters[middle]) / 2)
        groups.append({
            "fuel": fuel,
            "n": n,
            "outcomes": counts,
            "outcomeSummaries": summaries,
            "extinctionDiameter": {"exact": len(diameters), "approximate": approximate, "missing": missing, "invalid": invalid,
                                   "median": median, "min": diameters[0] if diameters else None, "max": diameters[-1] if diameters else None},
        })
        fuel_counts[fuel] = n
    groups.sort(key=lambda group: (-group["n"], _locale_key(group["fuel"])))
    return groups, fuel_counts, outcome_totals, unknown


def _psi69_measurement_quality(records: list[Mapping[str, Any]], quality: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    fields = quality.get("measurementQuality")
    if not isinstance(fields, Mapping) or len(fields) != 9:
        raise ScientificVerificationError("quality_report_contract_mismatch")
    output: list[dict[str, Any]] = []
    ok = True
    for field, metadata in fields.items():
        if not isinstance(field, str) or not isinstance(metadata, Mapping):
            raise ScientificVerificationError("quality_report_contract_mismatch")
        counts = {key: 0 for key in ("exact", "approximate", "missing", "invalid")}
        for record in records:
            status = _psi69_quality(record, field)
            if status in counts:
                counts[status] += 1
        expected = {key: metadata.get(key) for key in counts}
        if any(not _is_int(expected[key]) for key in expected) or sum(counts.values()) != len(records) or counts != expected:
            ok = False
        label = str(metadata.get("label", field))
        unit = str(metadata.get("unit", ""))
        output.append({"field": field, "label": f"{label} ({unit})".strip(), **counts})
    return output, ok


def _psi69_burning(records: list[Mapping[str, Any]]) -> tuple[list[int], list[int], list[dict[str, Any]]]:
    selected = [row["testNumber"] for row in records
                if _psi69_quality(row, "burningRateMm2PerSec") == "exact"
                and _finite_number(row.get("burningRateMm2PerSec"))]
    selected_set = set(selected)
    excluded = [row["testNumber"] for row in records if row["testNumber"] not in selected_set]
    fuels = sorted({_psi69_fuel(row) for row in records})
    groups = []
    for fuel in fuels:
        rows = [row for row in records if _psi69_fuel(row) == fuel]
        exact: list[float] = []
        approximate = missing = invalid = 0
        for row in rows:
            status = _psi69_quality(row, "burningRateMm2PerSec")
            value = row.get("burningRateMm2PerSec")
            if status == "exact" and _finite_number(value):
                exact.append(float(value))
            if status == "approximate":
                approximate += 1
            if status == "missing" or value is None:
                missing += 1
            if status == "invalid":
                invalid += 1
        n = len(exact)
        mean = sum(exact) / n if n else None
        sd = math.sqrt(sum((value - mean) ** 2 for value in exact) / (n - 1)) if n > 1 else None
        groups.append({"fuel": fuel, "n": n, "mean": mean, "sd": sd,
                       "approximate": approximate, "missing": missing, "invalid": invalid})
    return selected, excluded, groups


def _psi69_gap_ranking(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = sorted((group for group in groups if group["n"] > 0), key=lambda group: _locale_key(group["fuel"]))
    comparisons = []
    for left_index in range(len(valid)):
        for right_index in range(left_index + 1, len(valid)):
            left_group, right_group = valid[left_index], valid[right_index]
            for outcome in OUTCOME_ORDER:
                left_count = left_group["outcomes"][outcome]
                right_count = right_group["outcomes"][outcome]
                delta = left_count / left_group["n"] - right_count / right_group["n"]
                comparisons.append({
                    "outcome": outcome,
                    "left": {"fuel": left_group["fuel"], "count": left_count, "n": left_group["n"]},
                    "right": {"fuel": right_group["fuel"], "count": right_count, "n": right_group["n"]},
                    "gapPercentagePoints": abs(delta) * 100,
                    "higherShareFuel": left_group["fuel"] if delta > 0 else right_group["fuel"] if delta < 0 else None,
                    "gap": abs(delta),
                })
    order = {name: index for index, name in enumerate(OUTCOME_ORDER)}
    comparisons.sort(key=lambda row: (-row["gap"], order[row["outcome"]], _locale_key(row["left"]["fuel"]), _locale_key(row["right"]["fuel"])))
    return comparisons


def _compact_oxygen_slice(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    groups, _, _, unknown = _psi69_groups(rows)
    ranked = _psi69_gap_ranking(groups)
    return {
        "n": len(rows),
        "groups": [{"fuel": g["fuel"], "n": g["n"], "outcomes": dict(g["outcomes"])} for g in groups],
        "ranked": [{"outcome": r["outcome"], "gapPercentagePoints": r["gapPercentagePoints"],
                    "left": dict(r["left"]), "right": dict(r["right"])} for r in ranked],
        "unknown_outcomes": unknown,
    }


def _verify_psi69(report: _Report, entry: Any, answer: Mapping[str, Any], operation: str, scope: str, ledger: Mapping[str, Any]) -> None:
    records, quality, bundle = _psi69_records(entry)
    report.compare("psi69.source.record_count", len(records), 274, "source_lineage_mismatch")
    report.compare("psi69.source.hash_binding", {
        "sourceHash": answer.get("sourceHash"), "recordsHash": answer.get("recordsHash"), "qualityHash": answer.get("qualityHash")
    }, {
        "sourceHash": _get(entry, "source_sha256"), "recordsHash": _get(entry, "records_sha256"), "qualityHash": _get(entry, "quality_sha256")
    }, "source_lineage_mismatch")
    if answer.get("sampleSize") != len(records):
        # Operation-specific scopes below override this for filtered operations.
        pass
    analysis = _record_event(answer, report, "analysis.completed", "psi69.analysis_completed")
    selected_event = _record_event(answer, report, "data.selected", "psi69.data_selected") if operation in {"flex.burning_rate.exact_by_fuel", "flex.measurement_quality", "flex.oxygen_cohort_sensitivity"} else None
    claims = ledger.get("claims") if isinstance(ledger, Mapping) else None
    if not isinstance(claims, list) or len(claims) != 1 or not isinstance(claims[0], Mapping):
        report.missing("psi69.claim.single", "claim_ledger_mismatch")
        return
    claim = claims[0]
    expected_claim_type = {
        "flex.dataset.snapshot": "source_table_count",
        "flex.outcomes.by_fuel": "source_table_count",
        "flex.burning_rate.exact_by_fuel": "descriptive_summary",
        "flex.measurement_quality": "measurement_quality_observation",
        "flex.oxygen_cohort_sensitivity": "observed_cohort_comparison",
    }.get(operation)
    report.compare("psi69.claim.type_metric", {"claimType": claim.get("claimType"), "metric": claim.get("metric")},
                   {"claimType": expected_claim_type, "metric": ""}, "claim_ledger_mismatch")
    if operation in {"flex.dataset.snapshot", "flex.outcomes.by_fuel"}:
        groups, fuel_counts, outcomes, unknown = _psi69_groups(records)
        if unknown:
            report.add("psi69.outcome_categories.closed_set", "failed", "scientific_scope_violation")
        else:
            report.add("psi69.outcome_categories.closed_set", "passed")
        report.compare("psi69.answer.sample_size", answer.get("sampleSize"), 274, "numeric_mismatch")
        if analysis is not None:
            actual_groups_key = "fuel_groups" if operation == "flex.dataset.snapshot" else "groups"
            report.compare("psi69.event.fuel_groups", analysis.get(actual_groups_key), groups, "numeric_mismatch")
            if operation == "flex.dataset.snapshot":
                report.compare("psi69.event.outcomes", analysis.get("outcomes"), outcomes, "numeric_mismatch")
        compact = [{"fuel": g["fuel"], "n": g["n"], "outcomes": g["outcomes"]} for g in groups]
        expected_claim = {"recordCount": 274, "fuelCounts": fuel_counts, "outcomeCounts": outcomes, "fuelOutcomeCounts": compact}
        report.compare("psi69.claim.result", claim.get("result"), expected_claim, "claim_ledger_mismatch")
        report.compare("psi69.claim.lineage_counts", claim.get("recordLineage"), {
            "mode": "registered_selection_scope", "supportingRecordIds": [], "excludedRecordIds": [],
            "supportingCount": 274, "excludedCount": 0, "complete": True
        }, "claim_ledger_mismatch")
    elif operation == "flex.burning_rate.exact_by_fuel":
        selected, excluded, groups = _psi69_burning(records)
        report.compare("psi69.answer.sample_size", answer.get("sampleSize"), len(selected), "numeric_mismatch")
        report.compare("psi69.answer.record_ids", answer.get("recordIds"), selected, "record_selection_mismatch")
        if selected_event is not None:
            report.compare("psi69.selection.event_ids", selected_event.get("record_ids"), selected, "record_selection_mismatch")
            report.compare("psi69.selection.event_count", selected_event.get("record_count"), len(selected), "numeric_mismatch")
        if analysis is not None:
            report.compare("psi69.analysis.selected_ids", analysis.get("record_ids"), selected, "record_selection_mismatch")
            report.compare("psi69.analysis.groups", analysis.get("groups"), groups, "numeric_mismatch")
            report.compare("psi69.analysis.exact_count", analysis.get("exact_record_count"), len(selected), "numeric_mismatch")
        report.compare("psi69.answer.groups", answer.get("burningRateSummaries"), groups, "numeric_mismatch")
        report.compare("psi69.claim.result", claim.get("result"), {
            "exactRecordCount": len(selected), "unit": "mm²/s", "groups": groups
        }, "claim_ledger_mismatch")
        report.compare("psi69.claim.lineage", claim.get("recordLineage"), {
            "mode": "registered_selection_scope", "supportingRecordIds": selected, "excludedRecordIds": excluded,
            "supportingCount": len(selected), "excludedCount": len(excluded), "complete": True
        }, "claim_ledger_mismatch")
        if len(selected) + len(excluded) != len(records):
            report.add("psi69.selection.partition", "failed", "record_selection_mismatch")
        else:
            report.add("psi69.selection.partition", "passed")
    elif operation == "flex.measurement_quality":
        expected_rows, consistent = _psi69_measurement_quality(records, quality)
        report.compare("psi69.answer.sample_size", answer.get("sampleSize"), 274, "numeric_mismatch")
        report.add("psi69.quality.source_reconciliation", "passed" if consistent else "failed",
                   "ok" if consistent else "numeric_mismatch")
        if selected_event is not None:
            report.compare("psi69.quality.selected_fields", selected_event.get("measurement_fields"), 9, "numeric_mismatch")
        if analysis is not None:
            report.compare("psi69.quality.event_field_count", analysis.get("measurement_fields"), 9, "numeric_mismatch")
        answer_expected_rows = [{k: v for k, v in row.items() if k != "field"} for row in expected_rows]
        report.compare("psi69.quality.answer_rows", answer.get("qualityRows"), answer_expected_rows, "numeric_mismatch")
        report.compare("psi69.quality.claim_rows", claim.get("result"), {
            "recordCount": 274,
            "measurementFields": [{k: v for k, v in row.items() if k != "field"} for row in expected_rows],
        }, "claim_ledger_mismatch")
        report.compare("psi69.quality.lineage", claim.get("recordLineage"), {
            "mode": "registered_selection_scope", "supportingRecordIds": [], "excludedRecordIds": [],
            "supportingCount": 274, "excludedCount": 0, "complete": True
        }, "claim_ledger_mismatch")
    elif operation == "flex.oxygen_cohort_sensitivity":
        fixed_ids: list[int] = []
        broad_ids: list[int] = []
        for row in records:
            pressure = _psi69_exact(row, "ambientPressureMmHg")
            oxygen = _psi69_exact(row, "oxygenMoleFraction")
            co_value = _psi69_exact(row, "coSourceMoleFraction")
            helium = _psi69_exact(row, "heliumMoleFraction")
            eligible = (pressure is not None and oxygen is not None and co_value is not None and helium is not None
                        and 750 <= pressure <= 770 and co_value == 0 and helium == 0)
            if eligible:
                broad_ids.append(row["testNumber"])
                if oxygen == FIXED_OXYGEN:
                    fixed_ids.append(row["testNumber"])
        broad_rows = [row for row in records if row["testNumber"] in set(broad_ids)]
        fixed_rows = [row for row in records if row["testNumber"] in set(fixed_ids)]
        fixed = _compact_oxygen_slice(fixed_rows)
        broad = _compact_oxygen_slice(broad_rows)
        filters = {"pressureMin": 750, "pressureMax": 770, "coSourceMoleFraction": 0, "heliumMoleFraction": 0}
        comparison = {"filters": filters, "fixedOxygen": FIXED_OXYGEN, "fixedRecordCount": len(fixed_ids),
                      "broadRecordCount": len(broad_ids), "fixed": {k: v for k, v in fixed.items() if k != "unknown_outcomes"},
                      "broad": {k: v for k, v in broad.items() if k != "unknown_outcomes"},
                      "fixedOrder": [item["outcome"] for item in fixed["ranked"]],
                      "broadOrder": [item["outcome"] for item in broad["ranked"]]}
        comparison["orderChanged"] = comparison["fixedOrder"] != comparison["broadOrder"]
        report.compare("psi69.answer.sample_size", answer.get("sampleSize"), len(broad_ids), "numeric_mismatch")
        report.compare("psi69.oxygen.broad_ids", answer.get("recordIds"), broad_ids, "record_selection_mismatch")
        report.compare("psi69.oxygen.fixed_ids", answer.get("fixedRecordIds"), fixed_ids, "record_selection_mismatch")
        report.compare("psi69.oxygen.fixed_subset", fixed_ids, [value for value in broad_ids if value in set(fixed_ids)], "record_selection_mismatch")
        if selected_event is not None:
            report.compare("psi69.oxygen.selection_event", {
                "fixed_record_ids": selected_event.get("fixed_record_ids"),
                "broad_record_ids": selected_event.get("broad_record_ids"),
                "fixed_count": selected_event.get("fixed_count"), "broad_count": selected_event.get("broad_count")
            }, {"fixed_record_ids": fixed_ids, "broad_record_ids": broad_ids,
                "fixed_count": len(fixed_ids), "broad_count": len(broad_ids)}, "record_selection_mismatch")
        if fixed["unknown_outcomes"] or broad["unknown_outcomes"]:
            report.add("psi69.oxygen.closed_outcomes", "failed", "scientific_scope_violation")
        else:
            report.add("psi69.oxygen.closed_outcomes", "passed")
        report.compare("psi69.oxygen.answer_comparison", answer.get("oxygenComparison"), comparison, "numeric_mismatch")
        if analysis is not None:
            report.compare("psi69.oxygen.analysis_comparison", analysis.get("oxygen_comparison"), comparison, "numeric_mismatch")
        report.compare("psi69.oxygen.claim_result", claim.get("result"), comparison, "claim_ledger_mismatch")
        excluded = [row["testNumber"] for row in records if row["testNumber"] not in set(broad_ids)]
        report.compare("psi69.oxygen.claim_lineage", claim.get("recordLineage"), {
            "mode": "registered_selection_scope", "supportingRecordIds": broad_ids, "excludedRecordIds": excluded,
            "supportingCount": len(broad_ids), "excludedCount": len(excluded), "complete": True
        }, "claim_ledger_mismatch")
    else:
        report.add("psi69.operation", "unverifiable", "unsupported_operation")


# ----------------------------- PSI-25 helpers -----------------------------

def _psi25_cohort(record: Mapping[str, Any]) -> tuple[str, str, str]:
    identity = record.get("identity") if isinstance(record.get("identity"), Mapping) else {}
    material = record.get("material") if isinstance(record.get("material"), Mapping) else {}
    restrictor = record.get("flow_restrictor") if isinstance(record.get("flow_restrictor"), Mapping) else {}
    pi = identity.get("pi")
    material_class = material.get("canonical_class") or "unclassified"
    flow = restrictor.get("code")
    return ("" if pi is None else str(pi), str(material_class), "" if flow is None else str(flow))


def _psi25_cohort_object(key: tuple[str, str, str]) -> dict[str, str]:
    return {"pi": key[0], "material_class": key[1], "flow_restrictor_code": key[2]}


def _psi25_evidence_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("test_id") or row.get("test_id_raw") or ""))


def _psi25_flags(row: Mapping[str, Any], metric: str) -> list[str]:
    flags: list[str] = []
    if row["records_marked_with_reused_sample_id"] > 0:
        flags.append("sample_id_reuse_possible_dependence")
    if (row["cohort"].get("material_class") or "unclassified").lower() == "unclassified":
        flags.append("material_class_unclassified")
    if metric == "o2":
        flags.append("o2_sensor_calibration_limitation")
    stats = row["statistics"]
    if stats is None:
        flags.append("not_rankable_no_eligible_pairs")
        return flags
    if row["summary_status"] == "small_n_descriptive_only":
        flags.append("small_n_descriptive_only")
    if row.get("mean_median_sign_relation") == "opposite_sign":
        flags.append("mean_median_opposite_sign")
    if row.get("absolute_mean_median_gap", Decimal(0)) > 0:
        flags.append("mean_median_gap_nonzero")
    directions = row.get("direction_counts", {})
    if directions.get("positive", 0) > 0 and directions.get("negative", 0) > 0:
        flags.append("mixed_positive_and_negative_record_changes")
    if row.get("observed_range_includes_zero"):
        flags.append("observed_range_includes_zero")
    return flags


def _psi25_pair(record: Mapping[str, Any], metric: str) -> dict[str, Any]:
    initial_field, final_field, expected_unit, _ = PSI25_METRICS[metric]
    measurements = record.get("measurements") if isinstance(record.get("measurements"), Mapping) else {}
    initial = measurements.get(initial_field) if isinstance(measurements.get(initial_field), Mapping) else {}
    final = measurements.get(final_field) if isinstance(measurements.get(final_field), Mapping) else {}
    reasons: list[str] = []
    values: dict[str, Decimal | None] = {}
    for label, item in (("initial", initial), ("final", final)):
        status = item.get("status", "missing_status")
        eligible = item.get("aggregation_eligible") is True
        parsed = _as_decimal(item.get("parsed_decimal"))
        if status != "numeric_exact":
            reasons.append(f"{label}_status_not_numeric_exact:{status}")
        if not eligible:
            reasons.append(f"{label}_aggregation_eligible_false")
        if parsed is None:
            reasons.append(f"{label}_parsed_decimal_missing_or_invalid")
        values[label] = parsed
    initial_unit, final_unit = initial.get("unit"), final.get("unit")
    if initial_unit != final_unit:
        reasons.append("initial_final_unit_mismatch")
    if initial_unit != expected_unit or final_unit != expected_unit:
        reasons.append("unit_does_not_match_expected_documented_unit")
    if metric == "co":
        for label, value in values.items():
            if value is not None and value < 0:
                reasons.append(f"{label}_negative_co_requires_review")
    eligible_pair = not reasons and values["initial"] is not None and values["final"] is not None
    delta = values["final"] - values["initial"] if eligible_pair else None
    identity = record.get("identity") if isinstance(record.get("identity"), Mapping) else {}
    sample = record.get("sample") if isinstance(record.get("sample"), Mapping) else {}
    return {
        "record_key": identity.get("record_key"),
        "test_id": identity.get("test_id"),
        "test_id_raw": identity.get("test_id_raw"),
        "cohort": _psi25_cohort(record),
        "sample_id_raw": sample.get("id_raw"),
        "sample_id_reused": sample.get("is_reused_exact_raw_id") is True,
        "sample_id_reuse_count_exact_raw_id": sample.get("reuse_count_exact_raw_id"),
        "pair_eligible": eligible_pair,
        "delta": delta,
        "exclusion_reasons": sorted(set(reasons)),
    }


def _psi25_statistics(values: list[Decimal]) -> dict[str, Any] | None:
    if not values:
        return None
    ordered = sorted(values)
    with localcontext() as ctx:
        ctx.prec = 28
        mean = sum(ordered, Decimal(0)) / Decimal(len(ordered))
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    return {"n": len(ordered), "mean": mean, "median": median, "minimum": ordered[0], "maximum": ordered[-1]}


def _psi25_relation(mean: Decimal, median: Decimal) -> str:
    if mean == 0 and median == 0:
        return "both_zero"
    if mean == 0 or median == 0:
        return "one_zero"
    return "same_sign" if (mean > 0 and median > 0) or (mean < 0 and median < 0) else "opposite_sign"


def _psi25_recompute(records: list[Mapping[str, Any]], metric: str) -> dict[str, Any]:
    rows = [_psi25_pair(record, metric) for record in records]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    global_sample_ids = [row["sample_id_raw"] for row in rows if isinstance(row["sample_id_raw"], str) and row["sample_id_raw"] != ""]
    global_sample_counts = Counter(global_sample_ids)
    sample_reuse_summary = {
        "distinct_nonblank_exact_raw_sample_ids": len(global_sample_counts),
        "reused_exact_raw_id_groups": sum(count > 1 for count in global_sample_counts.values()),
        "records_in_reused_exact_raw_id_groups": sum(count for count in global_sample_counts.values() if count > 1),
        "records_flagged_reused_by_canonicalizer": sum(row["sample_id_reused"] for row in rows),
        "identifier_matching": "exact_raw_case_sensitive",
    }
    for row in rows:
        grouped[row["cohort"]].append(row)
    if len(grouped) != 18:
        raise ScientificVerificationError("cohort_mismatch")
    cohort_rows: list[dict[str, Any]] = []
    for key in sorted(grouped):
        members = grouped[key]
        eligible = [row for row in members if row["pair_eligible"]]
        excluded = [row for row in members if not row["pair_eligible"]]
        values = [row["delta"] for row in eligible]
        stats = _psi25_statistics(values)
        ids = {row["sample_id_raw"] for row in members if isinstance(row["sample_id_raw"], str) and row["sample_id_raw"] != ""}
        reused = sum(row["sample_id_reused"] for row in members)
        cohort_rows.append({
            "cohort": _psi25_cohort_object(key),
            "key": key,
            "records_in_cohort": len(members),
            "eligible_pairs": len(eligible),
            "excluded_pairs": len(excluded),
            "distinct_exact_sample_ids_in_cohort": len(ids),
            "records_marked_with_reused_sample_id": reused,
            "summary_status": "no_eligible_pairs" if not values else ("small_n_descriptive_only" if len(values) < 5 else "descriptive_only"),
            "statistics_n_definition": "eligible experiment records; not necessarily independent physical samples",
            "sample_reuse_caveat": "Repeated exact Sample IDs may indicate dependent experiment records; do not interpret record-pair n as independent physical-sample n.",
            "statistics": stats,
            "eligible_rows": eligible,
            "excluded_rows": excluded,
        })
    eligible_total = sum(row["pair_eligible"] for row in rows)
    pair_counts = {"records": len(rows), "eligible_pairs": eligible_total, "excluded_pairs": len(rows) - eligible_total}
    rankable = [row for row in cohort_rows if row["eligible_pairs"] > 0]
    unranked = [row for row in cohort_rows if row["eligible_pairs"] == 0]
    rankable.sort(key=lambda row: (-row["statistics"]["mean"], *row["key"]))
    previous: Decimal | None = None
    current_rank = 0
    for position, row in enumerate(rankable, 1):
        mean = row["statistics"]["mean"]
        if previous is None or mean != previous:
            current_rank = position
        row["rank"] = current_rank
        row["display_order"] = position
        previous = mean
    unranked.sort(key=lambda row: row["key"])
    for row in unranked:
        row["rank"] = None
        row["display_order"] = None
    for row in rankable:
        stats = row["statistics"]
        mean, median = stats["mean"], stats["median"]
        deltas = [item["delta"] for item in row["eligible_rows"]]
        positive, negative, zero = sum(x > 0 for x in deltas), sum(x < 0 for x in deltas), sum(x == 0 for x in deltas)
        row["mean_direction"] = "positive_mean_change" if mean > 0 else "negative_mean_change" if mean < 0 else "zero_mean_change"
        row["mean_median_sign_relation"] = _psi25_relation(mean, median)
        row["absolute_mean_median_gap"] = abs(mean - median)
        row["direction_counts"] = {"positive": positive, "negative": negative, "zero": zero}
        row["observed_range_includes_zero"] = stats["minimum"] <= 0 <= stats["maximum"]
        row["ranked_by"] = "signed_mean_paired_change_within_metric_only"
    return {"metric": metric, "rows": rows, "cohorts": cohort_rows, "ranked": rankable, "unranked": unranked,
            "pair_counts": pair_counts, "sample_reuse_summary": sample_reuse_summary}


def _psi25_claims(report: _Report, ledger: Mapping[str, Any], recomputed: Mapping[str, Any], operation: str, metric: str) -> None:
    claims = ledger.get("claims")
    if not isinstance(claims, list):
        report.missing("psi25.claims.shape", "claim_ledger_mismatch")
        return
    if operation == "psi25.bass_ii.v4.snapshot":
        if len(claims) != 4:
            report.add("psi25.snapshot.claim_count", "failed", "claim_ledger_mismatch")
            return
        report.add("psi25.snapshot.claim_count", "passed")
        first_expected = {"claimType": "source_table_count", "metric": "", "result": {"recordCount": 129},
                          "recordLineage": {"mode": "registered_selection_scope", "supportingRecordIds": [],
                                            "excludedRecordIds": [], "supportingCount": 129, "excludedCount": 0, "complete": True}}
        report.compare("psi25.snapshot.source_claim", claims[0], first_expected, "claim_ledger_mismatch")
        report.claim(claims[0].get("claimId", ""), "passed" if _mismatch(claims[0], first_expected) is None else "failed",
                     "ok" if _mismatch(claims[0], first_expected) is None else "claim_ledger_mismatch")
        for index, key in enumerate(("o2", "co2", "co"), 1):
            data = recomputed[key]
            expected = {"claimType": "descriptive_summary", "metric": key,
                        "result": {"recordCount": 129, "eligiblePairs": data["pair_counts"]["eligible_pairs"],
                                   "excludedPairs": data["pair_counts"]["excluded_pairs"],
                                   "rankableCohorts": len(data["ranked"]), "notRankableCohorts": len(data["unranked"]),
                                   "insightCards": 18}}
            report.compare(f"psi25.snapshot.{key}.claim", claims[index], expected, "claim_ledger_mismatch")
            report.claim(claims[index].get("claimId", ""), "passed" if _mismatch(claims[index], expected) is None else "failed",
                         "ok" if _mismatch(claims[index], expected) is None else "claim_ledger_mismatch")
        return
    expected_order = recomputed[metric]["ranked"] + recomputed[metric]["unranked"]
    if len(claims) != len(expected_order) or len(expected_order) != 18:
        report.add("psi25.metric.claim_count", "failed", "claim_ledger_mismatch")
        return
    report.add("psi25.metric.claim_count", "passed")
    by_id = {row.get("claimId"): row for row in claims if isinstance(row, Mapping)}
    for ordinal, card in enumerate(expected_order, 1):
        claim_id = f"PSI25-{metric.upper()}-{ordinal:03d}"
        actual = by_id.get(claim_id)
        if actual is None:
            report.add(f"psi25.claim.{ordinal}.present", "failed", "claim_ledger_mismatch")
            report.claim(claim_id, "failed", "claim_ledger_mismatch")
            continue
        eligible = _psi25_evidence_order(card["eligible_rows"])
        excluded = _psi25_evidence_order(card["excluded_rows"])
        stats = card["statistics"]
        expected_stats = {} if stats is None else {"n": stats["n"], "mean": stats["mean"], "median": stats["median"],
                                                   "minimum": stats["minimum"], "maximum": stats["maximum"]}
        expected_result = {
            "rank": card["rank"], "eligiblePairs": len(eligible), "excludedPairs": len(excluded),
            "recordsInCohort": card["records_in_cohort"], "statistics": expected_stats,
            "directionCounts": card.get("direction_counts", {}),
            "flags": _psi25_flags(card, metric),
        }
        expected_lineage = {
            "mode": "explicit_canonical_record_keys",
            "supportingRecordKeys": [row["record_key"] for row in eligible],
            "excludedRecordKeys": [row["record_key"] for row in excluded],
            "supportingCount": len(eligible), "excludedCount": len(excluded), "complete": True,
        }
        cohort = card["cohort"]
        expected_cohort = {"pi": cohort["pi"], "materialClass": cohort["material_class"],
                           "flowRestrictorCode": cohort["flow_restrictor_code"]}
        expected_status = "descriptive_only" if stats is not None else "descriptive_with_limitations"
        check_expected = {"claimType": "descriptive_cohort_finding", "metric": metric,
                          "cohort": expected_cohort, "result": expected_result,
                          "recordLineage": expected_lineage, "interpretationStatus": expected_status}
        mismatch = _mismatch(actual, check_expected)
        report.add(f"psi25.claim.{ordinal}.numeric_lineage", "passed" if mismatch is None else "failed",
                   "ok" if mismatch is None else "claim_ledger_mismatch")
        report.claim(claim_id, "passed" if mismatch is None else "failed", "ok" if mismatch is None else "claim_ledger_mismatch")


def _verify_psi25(report: _Report, entry: Any, answer: Mapping[str, Any], operation: str, metric: str, scope: str, ledger: Mapping[str, Any]) -> None:
    payload = _get(entry, "payload", {})
    canonical = payload.get("canonical") if isinstance(payload, Mapping) else None
    paired_artifact = payload.get("paired") if isinstance(payload, Mapping) else None
    findings_artifact = payload.get("findings") if isinstance(payload, Mapping) else None
    synthesis_artifact = payload.get("synthesis") if isinstance(payload, Mapping) else None
    if not isinstance(canonical, Mapping) or canonical.get("schema") != "sira.firelab.psi25.canonical_records.v1":
        raise ScientificVerificationError("missing_verified_source")
    records = canonical.get("records")
    if not isinstance(records, list) or len(records) != 129 or _get(entry, "record_count") != 129:
        raise ScientificVerificationError("missing_verified_source")
    if (canonical.get("record_count") != 129 or canonical.get("study_version") != 4
            or canonical.get("source_investigation") != "PSI-25"
            or _get(entry, "version") != "Study Version 4"):
        raise ScientificVerificationError("source_lineage_mismatch")
    report.compare("psi25.answer.source_hashes", {
        "sourceHash": answer.get("sourceHash"), "recordsHash": answer.get("recordsHash"), "qualityHash": answer.get("qualityHash")
    }, {"sourceHash": _get(entry, "source_sha256"), "recordsHash": _get(entry, "records_sha256"),
        "qualityHash": _get(entry, "quality_sha256")}, "source_lineage_mismatch")
    keys = [((row.get("identity") or {}).get("record_key") if isinstance(row, Mapping) else None) for row in records]
    if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != 129:
        raise ScientificVerificationError("source_lineage_mismatch")
    recomputed = {key: _psi25_recompute(records, key) for key in PSI25_METRICS}
    report.compare("psi25.source.record_count", len(records), 129, "source_lineage_mismatch")
    # Paired-analysis artifact comparison: each metric's complete pair accounting and cohort statistics.
    if not isinstance(paired_artifact, Mapping) or not isinstance(findings_artifact, Mapping) or not isinstance(synthesis_artifact, Mapping):
        raise ScientificVerificationError("missing_verified_source")
    report.compare("psi25.paired.root_metadata", {
        "dataset": paired_artifact.get("dataset"),
        "source_investigation": paired_artifact.get("source_investigation"),
        "record_count": paired_artifact.get("record_count"),
        "study_version": paired_artifact.get("study_version"),
        "analysis_type": paired_artifact.get("analysis_type"),
        "cohort_dimensions": paired_artifact.get("cohort_dimensions"),
    }, {"dataset": "NASA PSI-25 BASS-II", "source_investigation": "PSI-25",
        "record_count": 129, "study_version": 4,
        "analysis_type": "paired_descriptive_concentration_change",
        "cohort_dimensions": ["pi", "canonical_material_class", "flow_restrictor_code"]}, "source_lineage_mismatch")
    report.compare("psi25.findings.root_safeguards", {
        "record_count": findings_artifact.get("record_count"),
        "causal_claims_produced": findings_artifact.get("causal_claims_produced"),
        "cross_metric_ranking": findings_artifact.get("cross_metric_ranking"),
        "inferential_statistics_produced": findings_artifact.get("inferential_statistics_produced"),
        "independent_sample_inference": findings_artifact.get("independent_sample_inference"),
    }, {"record_count": 129, "causal_claims_produced": False, "cross_metric_ranking": False,
        "inferential_statistics_produced": False, "independent_sample_inference": False}, "scientific_scope_violation")
    for key, data in recomputed.items():
        paired_metric = (paired_artifact.get("metrics") or {}).get(key)
        findings_metric = (findings_artifact.get("metrics") or {}).get(key)
        synthesis_metric = (synthesis_artifact.get("metrics") or {}).get(key)
        if not all(isinstance(item, Mapping) for item in (paired_metric, findings_metric, synthesis_metric)):
            raise ScientificVerificationError("missing_verified_source")
        report.compare(f"psi25.{key}.paired_counts", paired_metric.get("pair_counts"), data["pair_counts"], "pair_eligibility_mismatch")
        report.compare(f"psi25.{key}.paired_scope", {
            "paired_difference_definition": paired_metric.get("paired_difference_definition"),
            "inferential_statistics_produced": paired_metric.get("inferential_statistics_produced"),
            "statistics_n_definition": paired_metric.get("statistics_n_definition"),
        }, {"paired_difference_definition": "final - initial", "inferential_statistics_produced": False,
            "statistics_n_definition": "n counts eligible experiment records, not necessarily independent physical samples"}, "scientific_scope_violation")
        audit = paired_metric.get("record_level_audit")
        expected_audit = []
        for row in data["rows"]:
            expected_audit.append({
                "record_key": row["record_key"], "pair_eligible": row["pair_eligible"],
                "delta_final_minus_initial": _decimal_text(row["delta"]),
                "exclusion_reasons": row["exclusion_reasons"],
                "test_id": row["test_id"], "test_id_raw": row["test_id_raw"],
                "sample_id_raw": row["sample_id_raw"], "sample_id_reused": row["sample_id_reused"],
                "sample_id_reuse_count_exact_raw_id": row["sample_id_reuse_count_exact_raw_id"],
            })
        # Compare only independent decision fields; other audit metadata is descriptive lineage.
        actual_audit = []
        if isinstance(audit, list):
            for row in audit:
                if isinstance(row, Mapping):
                    actual_audit.append({
                        "record_key": row.get("record_key"), "pair_eligible": row.get("pair_eligible"),
                        "delta_final_minus_initial": row.get("delta_final_minus_initial"),
                        "exclusion_reasons": row.get("exclusion_reasons"),
                        "test_id": row.get("test_id"), "test_id_raw": row.get("test_id_raw"),
                        "sample_id_raw": row.get("sample_id_raw"), "sample_id_reused": row.get("sample_id_reused"),
                        "sample_id_reuse_count_exact_raw_id": row.get("sample_id_reuse_count_exact_raw_id"),
                    })
        report.compare(f"psi25.{key}.paired_record_audit", actual_audit, expected_audit, "pair_eligibility_mismatch")
        paired_cohorts = paired_metric.get("cohort_summaries")
        expected_paired_cohorts = []
        for row in data["cohorts"]:
            stats = row["statistics"]
            expected_paired_cohorts.append({
                "cohort": row["cohort"], "records_in_cohort": row["records_in_cohort"],
                "eligible_pairs": row["eligible_pairs"], "excluded_pairs": row["excluded_pairs"],
                "distinct_exact_sample_ids_in_cohort": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "sample_reuse_caveat": row["sample_reuse_caveat"],
                "inferential_statistics_produced": False,
                "summary_status": row["summary_status"],
                "statistics_n_definition": row["statistics_n_definition"],
                "statistics": None if stats is None else {"n": stats["n"], "mean": stats["mean"], "median": stats["median"],
                                                          "minimum": stats["minimum"], "maximum": stats["maximum"]},
            })
        actual_paired_cohorts = []
        if isinstance(paired_cohorts, list):
            for row in paired_cohorts:
                if isinstance(row, Mapping):
                    actual_paired_cohorts.append({k: row.get(k) for k in (
                        "cohort", "records_in_cohort", "eligible_pairs", "excluded_pairs",
                        "distinct_exact_sample_ids_in_cohort", "records_marked_with_reused_sample_id",
                        "sample_reuse_caveat", "inferential_statistics_produced",
                        "summary_status", "statistics_n_definition", "statistics")})
        report.compare(f"psi25.{key}.paired_cohort_summaries", actual_paired_cohorts, expected_paired_cohorts, "numeric_mismatch")
        report.compare(f"psi25.{key}.paired_sample_reuse", paired_metric.get("sample_reuse_summary"),
                       data["sample_reuse_summary"], "source_lineage_mismatch") if paired_metric.get("sample_reuse_summary") is not None else None
        # Findings ranking and per-cohort numeric results.
        expected_ranked = []
        for row in data["ranked"]:
            ordered_eligible = _psi25_evidence_order(row["eligible_rows"])
            ordered_excluded = _psi25_evidence_order(row["excluded_rows"])
            expected_ranked.append({
                "cohort": row["cohort"], "rank": row["rank"], "display_order": row["display_order"],
                "eligible_pairs": row["eligible_pairs"], "excluded_pairs": row["excluded_pairs"],
                "records_in_cohort": row["records_in_cohort"],
                "distinct_exact_sample_ids_in_cohort": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "sample_reuse_caveat": row["sample_reuse_caveat"],
                "statistics_n_definition": row["statistics_n_definition"],
                "inferential_statistics_produced": False,
                "summary_status": row["summary_status"],
                "statistics": {k: v for k, v in row["statistics"].items()},
                "mean_direction": row["mean_direction"],
                "mean_median_sign_relation": row["mean_median_sign_relation"],
                "absolute_mean_median_gap": row["absolute_mean_median_gap"],
                "eligible_record_evidence": [{
                    "record_key": member["record_key"],
                    "test_id": member["test_id"] or member["test_id_raw"],
                    "sample_id_raw": member["sample_id_raw"],
                    "sample_id_reused": member["sample_id_reused"],
                    "delta_final_minus_initial": _decimal_text(member["delta"]),
                } for member in ordered_eligible],
                "excluded_record_evidence": [{
                    "record_key": member["record_key"],
                    "test_id": member["test_id"] or member["test_id_raw"],
                    "sample_id_raw": member["sample_id_raw"],
                    "exclusion_reasons": member["exclusion_reasons"],
                } for member in ordered_excluded],
            })
        expected_unranked = []
        for row in data["unranked"]:
            ordered_excluded = _psi25_evidence_order(row["excluded_rows"])
            expected_unranked.append({
                "cohort": row["cohort"], "eligible_pairs": 0,
                "excluded_pairs": row["excluded_pairs"], "records_in_cohort": row["records_in_cohort"],
                "distinct_exact_sample_ids_in_cohort": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "sample_reuse_caveat": row["sample_reuse_caveat"],
                "statistics_n_definition": row["statistics_n_definition"],
                "inferential_statistics_produced": False,
                "summary_status": row["summary_status"],
                "not_rankable_reason": "no_eligible_pairs",
                "excluded_record_evidence": [{
                    "record_key": member["record_key"],
                    "test_id": member["test_id"] or member["test_id_raw"],
                    "sample_id_raw": member["sample_id_raw"],
                    "exclusion_reasons": member["exclusion_reasons"],
                } for member in ordered_excluded],
            })
        actual_ranked = findings_metric.get("ranked_cohorts")
        actual_unranked = findings_metric.get("not_rankable_cohorts")
        if isinstance(actual_ranked, list):
            actual_ranked = [{"cohort": row.get("cohort"), "rank": row.get("rank"), "display_order": row.get("display_order"),
                              "eligible_pairs": row.get("eligible_pairs"), "excluded_pairs": row.get("excluded_pairs"),
                              "records_in_cohort": row.get("records_in_cohort"),
                              "distinct_exact_sample_ids_in_cohort": row.get("distinct_exact_sample_ids_in_cohort"),
                              "records_marked_with_reused_sample_id": row.get("records_marked_with_reused_sample_id"),
                              "sample_reuse_caveat": row.get("sample_reuse_caveat"),
                              "statistics_n_definition": row.get("statistics_n_definition"),
                              "inferential_statistics_produced": row.get("inferential_statistics_produced"),
                              "summary_status": row.get("summary_status"), "statistics": row.get("statistics"),
                              "mean_direction": row.get("mean_direction"),
                              "mean_median_sign_relation": row.get("mean_median_sign_relation"),
                              "absolute_mean_median_gap": row.get("absolute_mean_median_gap"),
                              "eligible_record_evidence": row.get("eligible_record_evidence"),
                              "excluded_record_evidence": row.get("excluded_record_evidence")}
                             for row in actual_ranked if isinstance(row, Mapping)]
        if isinstance(actual_unranked, list):
            actual_unranked = [{"cohort": row.get("cohort"), "eligible_pairs": row.get("eligible_pairs"),
                                "excluded_pairs": row.get("excluded_pairs"), "records_in_cohort": row.get("records_in_cohort"),
                                "distinct_exact_sample_ids_in_cohort": row.get("distinct_exact_sample_ids_in_cohort"),
                                "records_marked_with_reused_sample_id": row.get("records_marked_with_reused_sample_id"),
                                "sample_reuse_caveat": row.get("sample_reuse_caveat"),
                                "statistics_n_definition": row.get("statistics_n_definition"),
                                "inferential_statistics_produced": row.get("inferential_statistics_produced"),
                                "summary_status": row.get("summary_status"),
                                "not_rankable_reason": row.get("not_rankable_reason"),
                                "excluded_record_evidence": row.get("excluded_record_evidence")}
                               for row in actual_unranked if isinstance(row, Mapping)]
        report.compare(f"psi25.{key}.findings_ranked", actual_ranked, expected_ranked, "numeric_mismatch")
        report.compare(f"psi25.{key}.findings_unranked", actual_unranked, expected_unranked, "numeric_mismatch")
        report.compare(f"psi25.{key}.findings_pair_counts", findings_metric.get("pair_counts"), data["pair_counts"], "pair_eligibility_mismatch")
        report.compare(f"psi25.{key}.findings_cohort_counts", {
            "cohort_count": findings_metric.get("cohort_count"),
            "rankable_cohort_count": findings_metric.get("rankable_cohort_count"),
            "not_rankable_cohort_count": findings_metric.get("not_rankable_cohort_count"),
        }, {"cohort_count": 18, "rankable_cohort_count": len(data["ranked"]),
            "not_rankable_cohort_count": len(data["unranked"])}, "cohort_mismatch")
        def extreme(row: Mapping[str, Any] | None) -> Any:
            if row is None:
                return None
            return {"rank": row["rank"], "display_order": row["display_order"], "cohort": row["cohort"],
                    "eligible_pairs": row["eligible_pairs"], "mean": row["statistics"]["mean"],
                    "median": row["statistics"]["median"], "summary_status": row["summary_status"],
                    "mean_median_sign_relation": row["mean_median_sign_relation"]}
        positive = next((row for row in data["ranked"] if row["statistics"]["mean"] > 0), None)
        negative = next((row for row in reversed(data["ranked"]) if row["statistics"]["mean"] < 0), None)
        expected_extremes = {
            "highest_mean": extreme(data["ranked"][0] if data["ranked"] else None),
            "lowest_mean": extreme(data["ranked"][-1] if data["ranked"] else None),
            "strongest_positive_mean": extreme(positive), "most_negative_mean": extreme(negative),
        }
        actual_extremes = findings_metric.get("extremes")
        report.compare(f"psi25.{key}.findings_extremes", actual_extremes, expected_extremes, "numeric_mismatch")
        # Synthesis cards: numeric fields, status, and exact record lineage only.
        cards = synthesis_metric.get("insight_cards")
        if not isinstance(cards, list) or len(cards) != 18:
            report.add(f"psi25.{key}.synthesis_card_count", "failed", "cohort_mismatch")
            continue
        expected_order = data["ranked"] + data["unranked"]
        card_expected_rows = []
        for ordinal, row in enumerate(expected_order, 1):
            stats = row["statistics"]
            deltas = [member["delta"] for member in row["eligible_rows"]]
            pos = sum(value > 0 for value in deltas)
            neg = sum(value < 0 for value in deltas)
            zero = sum(value == 0 for value in deltas)
            expected_stats = None if stats is None else {"n": stats["n"], "mean": stats["mean"], "median": stats["median"],
                                                           "minimum": stats["minimum"], "maximum": stats["maximum"]}
            expected_card = {
                "insight_id": f"PSI25-{key.upper()}-{ordinal:03d}", "metric": key, "cohort": row["cohort"],
                "rank": row["rank"], "eligible_pairs": row["eligible_pairs"], "excluded_pairs": row["excluded_pairs"],
                "records_in_cohort": row["records_in_cohort"], "interpretation_status": "not_rankable" if stats is None else "descriptive_only",
                "distinct_exact_sample_ids": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "summary_status": row["summary_status"], "flags": _psi25_flags(row, key),
                "statistics_n_definition": row["statistics_n_definition"],
                "inferential_statistics_produced": False,
                "statistics": expected_stats,
                "direction_counts": {"positive": pos, "negative": neg, "zero": zero} if stats is not None else None,
                "mean_direction": {
                    "positive_mean_change": "positive",
                    "negative_mean_change": "negative",
                    "zero_mean_change": "zero",
                }.get(row.get("mean_direction")),
                "mean_median_sign_relation": row.get("mean_median_sign_relation"),
                "absolute_mean_median_gap": row.get("absolute_mean_median_gap"),
                "observed_range_includes_zero": row.get("observed_range_includes_zero"),
                "supporting_record_evidence": [{
                    "record_key": member["record_key"],
                    "test_id": member["test_id"] or member["test_id_raw"],
                    "sample_id_raw": member["sample_id_raw"],
                    "sample_id_reused": member["sample_id_reused"],
                    "delta_final_minus_initial": _decimal_text(member["delta"]),
                } for member in _psi25_evidence_order(row["eligible_rows"])],
                "excluded_record_evidence": [{
                    "record_key": member["record_key"],
                    "test_id": member["test_id"] or member["test_id_raw"],
                    "sample_id_raw": member["sample_id_raw"],
                    "exclusion_reasons": member["exclusion_reasons"],
                } for member in _psi25_evidence_order(row["excluded_rows"])],
            }
            card_expected_rows.append(expected_card)
        actual_card_rows = []
        for card in cards:
            if not isinstance(card, Mapping):
                actual_card_rows.append(None)
                continue
            actual_card_rows.append({k: card.get(k) for k in (
                "insight_id", "metric", "cohort", "rank", "eligible_pairs", "excluded_pairs", "records_in_cohort",
                "interpretation_status", "distinct_exact_sample_ids", "records_marked_with_reused_sample_id", "summary_status",
                "statistics_n_definition", "inferential_statistics_produced",
                "flags", "statistics", "direction_counts", "mean_direction", "mean_median_sign_relation",
                "absolute_mean_median_gap", "observed_range_includes_zero", "supporting_record_evidence", "excluded_record_evidence")})
        report.compare(f"psi25.{key}.synthesis_numeric_lineage", actual_card_rows, card_expected_rows, "numeric_mismatch")
        report.compare(f"psi25.{key}.synthesis_pair_counts", synthesis_metric.get("pair_counts"), data["pair_counts"], "pair_eligibility_mismatch")
        # Claim content is checked after artifacts have independently matched.
    report.compare("psi25.paired.sample_reuse_summary", paired_artifact.get("sample_reuse_summary"),
                   recomputed["co"]["sample_reuse_summary"], "source_lineage_mismatch")
    report.compare("psi25.synthesis.deterministic_safeguards", {
        "generated_with_llm": synthesis_artifact.get("generated_with_llm"),
        "causal_claims_produced": (synthesis_artifact.get("safeguards") or {}).get("causal_claims_produced"),
        "inferential_statistics_produced": (synthesis_artifact.get("safeguards") or {}).get("inferential_statistics_produced"),
        "independent_sample_inference": (synthesis_artifact.get("safeguards") or {}).get("independent_sample_inference"),
        "cross_metric_ranking": (synthesis_artifact.get("safeguards") or {}).get("cross_metric_ranking"),
        "operational_fire_safety_recommendations": (synthesis_artifact.get("safeguards") or {}).get("operational_fire_safety_recommendations"),
        "numeric_imputation": (synthesis_artifact.get("safeguards") or {}).get("numeric_imputation"),
        "llm_generated_measurements_or_claims": (synthesis_artifact.get("safeguards") or {}).get("llm_generated_measurements_or_claims"),
    }, {"generated_with_llm": False, "causal_claims_produced": False,
        "inferential_statistics_produced": False, "independent_sample_inference": False,
        "cross_metric_ranking": False, "operational_fire_safety_recommendations": False,
        "numeric_imputation": False, "llm_generated_measurements_or_claims": False}, "scientific_scope_violation")
    o2_caveat = (synthesis_artifact.get("measurement_provenance_caveats") or {}).get("o2")
    caveat_ok = isinstance(o2_caveat, Mapping) and bool(o2_caveat.get("interpretation_limit")) and bool(o2_caveat.get("source_note"))
    report.add("psi25.o2.calibration_caveat", "passed" if caveat_ok else "failed",
               "ok" if caveat_ok else "scientific_scope_violation")
    o2_cards = (synthesis_artifact.get("metrics") or {}).get("o2", {}).get("insight_cards", [])
    o2_card_caveats_ok = isinstance(o2_cards, list) and len(o2_cards) == 18 and all(
        isinstance(card, Mapping)
        and "o2_sensor_calibration_limitation" in (card.get("flags") or [])
        and "O2" in str(((card.get("evidence_dimensions") or {}).get("measurement_caveat", "")))
        for card in o2_cards
    )
    report.add("psi25.o2.card_caveats", "passed" if o2_card_caveats_ok else "failed",
               "ok" if o2_card_caveats_ok else "scientific_scope_violation")
    if operation == "psi25.bass_ii.v4.snapshot":
        expected_summary = {}
        for key, data in recomputed.items():
            expected_summary[key] = {"metric": key, "eligible_pairs": data["pair_counts"]["eligible_pairs"],
                                     "excluded_pairs": data["pair_counts"]["excluded_pairs"],
                                     "rankable_cohorts": len(data["ranked"]), "not_rankable_cohorts": len(data["unranked"]),
                                     "insight_cards": 18}
        snapshot_event = _record_event(answer, report, "analysis.completed", "psi25.snapshot.analysis_completed")
        if snapshot_event is not None:
            report.compare("psi25.snapshot.event_scope", snapshot_event, {"record_count": 129, "metric_scopes": expected_summary}, "numeric_mismatch")
        report.compare("psi25.answer.sample_size", answer.get("sampleSize"), 129, "numeric_mismatch")
        report.compare("psi25.answer.metric_summary", answer.get("metricSummary"), expected_summary, "numeric_mismatch")
    elif scope == "cohort-evidence":
        data = recomputed[metric]
        expected_refs = []
        for row in data["ranked"][:5]:
            ordered_eligible = _psi25_evidence_order(row["eligible_rows"])
            ordered_excluded = _psi25_evidence_order(row["excluded_rows"])
            expected_refs.append({
                "claim_id": f"PSI25-{metric.upper()}-{row['display_order']:03d}",
                "rank": row["rank"], "metric": metric, "cohort": row["cohort"],
                "statistics": {k: row["statistics"][k] for k in ("n", "mean", "median", "minimum", "maximum")},
                "supporting_record_keys": [member["record_key"] for member in ordered_eligible],
                "excluded_record_keys": [member["record_key"] for member in ordered_excluded],
            })
        actual_refs = answer.get("claimReferences")
        if isinstance(actual_refs, list):
            actual_refs = [{k: row.get(k) for k in ("claim_id", "rank", "metric", "cohort", "statistics", "supporting_record_keys", "excluded_record_keys")} for row in actual_refs if isinstance(row, Mapping)]
        report.compare("psi25.answer.sample_size", answer.get("sampleSize"), data["pair_counts"]["eligible_pairs"], "numeric_mismatch")
        report.compare("psi25.answer.pair_counts", {"eligible": answer.get("eligiblePairCount"), "excluded": answer.get("excludedPairCount"),
                                                     "rankable": answer.get("rankableCohortCount"), "not_rankable": answer.get("notRankableCohortCount")},
                       {"eligible": data["pair_counts"]["eligible_pairs"], "excluded": data["pair_counts"]["excluded_pairs"],
                        "rankable": len(data["ranked"]), "not_rankable": len(data["unranked"])}, "numeric_mismatch")
        report.compare("psi25.answer.top_five_claim_references", actual_refs, expected_refs, "claim_ledger_mismatch")
        metric_event = _record_event(answer, report, "analysis.completed", "psi25.metric.analysis_completed")
        if metric_event is not None:
            report.compare("psi25.metric.event_counts", metric_event, {
                "analysis_id": operation, "ranked_cohorts": len(data["ranked"]),
                "not_rankable_cohorts": len(data["unranked"]),
            }, "numeric_mismatch")
    _psi25_claims(report, ledger, recomputed, operation, metric)


def verify_completed_answer(evidence_entry: Any, answer: Any) -> dict[str, Any]:
    """Independently verify a completed answer against one trusted registry entry.

    The function is pure with respect to caller inputs and does not access files,
    the network, model providers, or the original calculation modules.
    """
    iid = _get(evidence_entry, "investigation_id", "")
    operation = answer.get("analysisId", "") if isinstance(answer, Mapping) else ""
    metric = answer.get("metric", "") if isinstance(answer, Mapping) else ""
    scope = answer.get("dataScope", "") if isinstance(answer, Mapping) else ""
    report = _Report(str(iid or ""), str(operation or ""), str(metric or ""), str(scope or ""))
    hashes: dict[str, str] = {}
    source_release = str(_get(evidence_entry, "version", ""))
    try:
        if not isinstance(answer, Mapping):
            report.add("context.answer", "unverifiable", "invalid_context")
            return report.result(source_release=source_release)
        if answer.get("status") == "abstained":
            report.add("answer.abstained", "not_applicable", "not_applicable")
            return report.result(status_override="not_applicable", source_release=source_release)
        if answer.get("status") != "completed":
            report.add("answer.status", "unverifiable", "missing_answer_structure")
            return report.result(source_release=source_release)
        spec = _OPERATION_SPECS.get(operation)
        if spec is None:
            report.add("context.operation", "unverifiable", "unsupported_operation")
            return report.result(source_release=source_release)
        expected_iid, expected_metric, expected_scope = spec
        if iid != expected_iid or answer.get("investigationId") != iid:
            report.add("context.investigation", "failed", "invalid_context")
            return report.result(source_release=source_release)
        if metric != expected_metric or scope != expected_scope:
            report.add("context.operation_scope", "failed", "invalid_context")
            return report.result(source_release=source_release)
        if not _is_int(answer.get("sampleSize")) or answer.get("sampleSize") < 0:
            report.add("context.sample_size", "unverifiable", "missing_answer_structure")
            return report.result(source_release=source_release)
        plan = answer.get("scientificPlan")
        if not isinstance(plan, Mapping):
            report.add("context.scientific_plan", "unverifiable", "missing_answer_structure")
            return report.result(source_release=source_release)
        plan_expect = {"operationId": operation, "dataScope": scope}
        if plan.get("resolvedInvestigation") is not None:
            plan_expect["resolvedInvestigation"] = iid
        elif plan.get("investigationId") is not None:
            plan_expect["investigationId"] = iid
        if plan.get("metric") is not None:
            plan_expect["metric"] = metric
        report.compare("context.scientific_plan", plan, plan_expect, "invalid_context")
        if report.checks[-1]["status"] != "passed":
            return report.result(source_release=source_release)
        hashes = _source_hashes(evidence_entry, iid)
        if any(not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()) for value in hashes.values()):
            report.add("context.verified_hashes", "unverifiable", "missing_verified_source")
            return report.result(source_release=source_release)
        if expected_scope == "research-questions":
            report.add("research_questions.no_measurement_verification", "not_applicable", "not_applicable")
            if answer.get("claimLedger") is not None:
                report.add("research_questions.no_claim_ledger", "failed", "scientific_scope_violation")
                return report.result(source_release=source_release, hashes=hashes)
            return report.result(status_override="not_applicable", source_release=source_release, hashes=hashes)
        ledger = _validate_ledger(report, evidence_entry, answer, iid, operation, metric, scope)
        if ledger is None:
            return report.result(source_release=source_release, hashes=hashes)
        if iid == PSI69_ID:
            _verify_psi69(report, evidence_entry, answer, operation, scope, ledger)
        elif iid == PSI25_ID:
            _verify_psi25(report, evidence_entry, answer, operation, metric, scope, ledger)
        else:
            report.add("context.investigation", "unverifiable", "unsupported_operation")
    except ScientificVerificationError as exc:
        reason = str(exc) if str(exc) in {"missing_verified_source", "source_lineage_mismatch", "cohort_mismatch", "invalid_source_record", "invalid_source_record_id", "quality_report_contract_mismatch"} else "internal_contract_error"
        report.add("verification.input_contract", "unverifiable", reason)
    except Exception:
        # Do not leak record values, paths, or arbitrary exception text.
        report.add("verification.internal", "unverifiable", "internal_contract_error")
    return report.result(source_release=source_release, hashes=hashes)
