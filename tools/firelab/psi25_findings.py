"""Deterministic descriptive findings and ranking for NASA PSI-25 BASS-II.

Ranks precomputed cohort summaries independently within each gas metric.
It does not recompute paired measurements, infer causality, or produce
inferential statistics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCHEMA = "sira.psi25.findings_ranking.v1"
DEFAULT_INPUT = Path("firelab_site/data/derived/psi25_bass_ii_v4/paired_analysis_v1")
DEFAULT_OUTPUT = Path("firelab_site/data/derived/psi25_bass_ii_v4/findings_ranking_v1")
EXPECTED_METRICS = ("o2", "co2", "co")


class FindingsError(RuntimeError):
    """Raised when source integrity or findings invariants fail."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FindingsError(f"Cannot read valid JSON: {path}") from exc


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise FindingsError(f"Missing or invalid decimal for {label}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise FindingsError(f"Invalid decimal for {label}: {value!r}") from exc
    if not result.is_finite():
        raise FindingsError(f"Non-finite decimal for {label}")
    return result


def _json_decimal(value: Decimal) -> str:
    return format(value, "f")


def _cohort_key(group: dict[str, Any]) -> tuple[str, str, str]:
    def part(key: str) -> str:
        value = group.get(key)
        return "" if value is None else str(value)
    return (part("pi"), part("material_class"), part("flow_restrictor_code"))


def _key_object(key: tuple[str, str, str]) -> dict[str, str | None]:
    return {
        "pi": key[0] or None,
        "material_class": key[1] or None,
        "flow_restrictor_code": key[2] or None,
    }


def _direction(value: Decimal) -> str:
    if value > 0:
        return "positive_mean_change"
    if value < 0:
        return "negative_mean_change"
    return "zero_mean_change"


def _mean_median_relation(mean: Decimal, median: Decimal) -> str:
    if mean == 0 and median == 0:
        return "both_zero"
    if mean == 0 or median == 0:
        return "one_zero"
    if (mean > 0 and median > 0) or (mean < 0 and median < 0):
        return "same_sign"
    return "opposite_sign"


def load_inputs(repo_root: Path, input_relative: Path = DEFAULT_INPUT) -> dict[str, Any]:
    root = repo_root.resolve()
    input_dir = (root / input_relative).resolve()
    try:
        input_dir.relative_to(root)
    except ValueError as exc:
        raise FindingsError("Input path must remain inside the repository") from exc
    analysis_path = input_dir / "paired_measurement_analysis.json"
    manifest_path = input_dir / "analysis_manifest.json"
    if not analysis_path.is_file() or not manifest_path.is_file():
        raise FindingsError("Production paired-analysis JSON and manifest are required")
    analysis_hash = sha256_file(analysis_path)
    manifest_hash = sha256_file(manifest_path)
    analysis_bytes = analysis_path.stat().st_size
    analysis = _read_json(analysis_path)
    manifest = _read_json(manifest_path)
    expected_output = manifest.get("derived_output") or {}
    if expected_output.get("sha256") != analysis_hash:
        raise FindingsError("Paired-analysis SHA-256 does not match its manifest")
    if expected_output.get("bytes") != analysis_bytes:
        raise FindingsError("Paired-analysis byte size does not match its manifest")
    record_count = analysis.get("record_count")
    if not isinstance(record_count, int) or record_count < 1 or manifest.get("record_count") != record_count:
        raise FindingsError("Paired-analysis and manifest record counts do not agree")
    if manifest.get("o2_calibration_caveat_included") is not True:
        raise FindingsError("Required O2 calibration caveat is absent")
    if manifest.get("independent_sample_inference") is not False:
        raise FindingsError("Independent physical-sample inference must remain disabled")
    if set((analysis.get("metrics") or {}).keys()) != set(EXPECTED_METRICS):
        raise FindingsError("Analysis must contain exactly O2, CO2, and CO metrics")
    return {
        "analysis": analysis,
        "analysis_manifest": manifest,
        "analysis_sha256": analysis_hash,
        "analysis_manifest_sha256": manifest_hash,
        "analysis_bytes": analysis_bytes,
        "analysis_manifest_bytes": manifest_path.stat().st_size,
        "input_path": str(input_dir),
    }


def _build_metric(metric_key: str, metric: dict[str, Any], expected_total_records: int) -> dict[str, Any]:
    pair_counts = metric.get("pair_counts") or {}
    total_records = pair_counts.get("records")
    eligible_expected = pair_counts.get("eligible_pairs")
    excluded_expected = pair_counts.get("excluded_pairs")
    if total_records != expected_total_records or eligible_expected is None or excluded_expected is None:
        raise FindingsError(f"Invalid pair-count metadata for {metric_key}")
    if eligible_expected + excluded_expected != total_records:
        raise FindingsError(f"Pair counts do not account for all records in {metric_key}")

    cohort_summaries = metric.get("cohort_summaries") or []
    audit_rows = metric.get("record_level_audit") or []
    if len(audit_rows) != total_records:
        raise FindingsError(f"Expected {total_records} record audit rows for {metric_key}")

    audit_by_cohort: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    eligible_rows = 0
    excluded_rows = 0
    for row in audit_rows:
        if not isinstance(row, dict):
            raise FindingsError(f"Malformed record audit row in {metric_key}")
        key = _cohort_key(row)
        audit_by_cohort.setdefault(key, []).append(row)
        if row.get("pair_eligible") is True:
            eligible_rows += 1
            _decimal(row.get("delta_final_minus_initial"), f"{metric_key} record delta")
        elif row.get("pair_eligible") is False:
            excluded_rows += 1
        else:
            raise FindingsError(f"Missing pair eligibility in {metric_key} record audit")
    if eligible_rows != eligible_expected or excluded_rows != excluded_expected:
        raise FindingsError(f"Record-level pair accounting mismatch for {metric_key}")

    seen_cohorts: set[tuple[str, str, str]] = set()
    rows_seen = eligible_seen = excluded_seen = 0
    rankable: list[dict[str, Any]] = []
    not_rankable: list[dict[str, Any]] = []

    for cohort in cohort_summaries:
        if not isinstance(cohort, dict):
            raise FindingsError(f"Malformed cohort summary in {metric_key}")
        key = _cohort_key(cohort.get("cohort") or {})
        if key in seen_cohorts:
            raise FindingsError(f"Duplicate cohort key in {metric_key}: {key}")
        seen_cohorts.add(key)
        records_in_cohort = cohort.get("records_in_cohort")
        eligible = cohort.get("eligible_pairs")
        excluded = cohort.get("excluded_pairs")
        if not all(isinstance(v, int) and v >= 0 for v in (records_in_cohort, eligible, excluded)):
            raise FindingsError(f"Invalid cohort counts in {metric_key}: {key}")
        if records_in_cohort != eligible + excluded:
            raise FindingsError(f"Cohort pair accounting mismatch in {metric_key}: {key}")
        matching_audit = audit_by_cohort.get(key, [])
        if len(matching_audit) != records_in_cohort:
            raise FindingsError(f"Cohort record lineage mismatch in {metric_key}: {key}")
        audit_eligible = sum(row["pair_eligible"] is True for row in matching_audit)
        audit_excluded = sum(row["pair_eligible"] is False for row in matching_audit)
        if audit_eligible != eligible or audit_excluded != excluded:
            raise FindingsError(f"Cohort record-level accounting mismatch in {metric_key}: {key}")
        rows_seen += records_in_cohort
        eligible_seen += eligible
        excluded_seen += excluded

        stats_raw = cohort.get("statistics")
        stats = stats_raw if isinstance(stats_raw, dict) else None
        common = {
            "cohort": _key_object(key),
            "records_in_cohort": records_in_cohort,
            "eligible_pairs": eligible,
            "excluded_pairs": excluded,
            "distinct_exact_sample_ids_in_cohort": cohort.get("distinct_exact_sample_ids_in_cohort"),
            "records_marked_with_reused_sample_id": cohort.get("records_marked_with_reused_sample_id"),
            "summary_status": cohort.get("summary_status", "not_stated"),
            "statistics_n_definition": cohort.get("statistics_n_definition"),
            "sample_reuse_caveat": cohort.get("sample_reuse_caveat"),
            "inferential_statistics_produced": False,
        }
        eligible_audit = [row for row in matching_audit if row.get("pair_eligible") is True]
        excluded_audit = [row for row in matching_audit if row.get("pair_eligible") is False]
        common["eligible_record_evidence"] = [
            {
                "record_key": row.get("record_key"),
                "test_id": row.get("test_id") or row.get("test_id_raw"),
                "sample_id_raw": row.get("sample_id_raw"),
                "sample_id_reused": row.get("sample_id_reused") is True,
                "delta_final_minus_initial": str(row.get("delta_final_minus_initial")),
            }
            for row in sorted(eligible_audit, key=lambda r: str(r.get("test_id") or r.get("test_id_raw") or ""))
        ]
        common["excluded_record_evidence"] = [
            {
                "record_key": row.get("record_key"),
                "test_id": row.get("test_id") or row.get("test_id_raw"),
                "sample_id_raw": row.get("sample_id_raw"),
                "exclusion_reasons": list(row.get("exclusion_reasons") or []),
            }
            for row in sorted(excluded_audit, key=lambda r: str(r.get("test_id") or r.get("test_id_raw") or ""))
        ]

        if eligible == 0:
            if stats is not None and any(stats.get(name) is not None for name in ("mean", "median", "minimum", "maximum")):
                raise FindingsError(f"Zero-pair cohort has numeric statistics in {metric_key}: {key}")
            common["not_rankable_reason"] = "no_eligible_pairs"
            not_rankable.append(common)
            continue
        if stats is None:
            raise FindingsError(f"Eligible cohort lacks statistics in {metric_key}: {key}")
        mean = _decimal(stats.get("mean"), f"{metric_key} cohort mean")
        median = _decimal(stats.get("median"), f"{metric_key} cohort median")
        minimum = _decimal(stats.get("minimum"), f"{metric_key} cohort minimum")
        maximum = _decimal(stats.get("maximum"), f"{metric_key} cohort maximum")
        if minimum > maximum or not (minimum <= mean <= maximum):
            raise FindingsError(f"Invalid cohort range/mean in {metric_key}: {key}")
        if stats.get("n") != eligible:
            raise FindingsError(f"Statistics n does not match eligible pairs in {metric_key}: {key}")
        common["statistics"] = {
            "n": stats["n"],
            "mean": _json_decimal(mean),
            "median": _json_decimal(median),
            "minimum": _json_decimal(minimum),
            "maximum": _json_decimal(maximum),
        }
        common["mean_direction"] = _direction(mean)
        common["mean_median_sign_relation"] = _mean_median_relation(mean, median)
        common["absolute_mean_median_gap"] = _json_decimal(abs(mean - median))
        common["ranked_by"] = "signed_mean_paired_change_within_metric_only"
        rankable.append({"_sort_mean": mean, **common})

    if rows_seen != total_records or eligible_seen != eligible_expected or excluded_seen != excluded_expected:
        raise FindingsError(f"Cohort totals do not reconcile for {metric_key}")

    rankable.sort(key=lambda item: (
        -item["_sort_mean"],
        item["cohort"].get("pi") or "",
        item["cohort"].get("material_class") or "",
        item["cohort"].get("flow_restrictor_code") or "",
    ))
    previous_mean: Decimal | None = None
    current_rank = 0
    for position, item in enumerate(rankable, 1):
        mean = item.pop("_sort_mean")
        if previous_mean is None or mean != previous_mean:
            current_rank = position
        item["rank"] = current_rank
        item["display_order"] = position
        previous_mean = mean

    rankable.sort(key=lambda item: item["display_order"])
    not_rankable.sort(key=lambda item: (
        item["cohort"].get("pi") or "",
        item["cohort"].get("material_class") or "",
        item["cohort"].get("flow_restrictor_code") or "",
    ))

    def reference(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "rank": item["rank"],
            "display_order": item["display_order"],
            "cohort": item["cohort"],
            "eligible_pairs": item["eligible_pairs"],
            "mean": item["statistics"]["mean"],
            "median": item["statistics"]["median"],
            "summary_status": item["summary_status"],
            "mean_median_sign_relation": item["mean_median_sign_relation"],
        }

    highest = rankable[0] if rankable else None
    lowest = rankable[-1] if rankable else None
    positive = next((item for item in rankable if _decimal(item["statistics"]["mean"], "mean") > 0), None)
    negative = next((item for item in reversed(rankable) if _decimal(item["statistics"]["mean"], "mean") < 0), None)

    return {
        "metric": metric_key,
        "label": metric.get("label"),
        "unit": metric.get("unit"),
        "pair_counts": {
            "records": total_records,
            "eligible_pairs": eligible_expected,
            "excluded_pairs": excluded_expected,
        },
        "cohort_count": len(cohort_summaries),
        "rankable_cohort_count": len(rankable),
        "not_rankable_cohort_count": len(not_rankable),
        "ranking_method": "Descending signed mean of precomputed paired changes; ranking is confined to this metric and its unit.",
        "ranked_cohorts": rankable,
        "not_rankable_cohorts": not_rankable,
        "extremes": {
            "highest_mean": reference(highest),
            "lowest_mean": reference(lowest),
            "strongest_positive_mean": reference(positive),
            "most_negative_mean": reference(negative),
        },
        "interpretation_limit": "Descriptive cohort ordering only. No causal interpretation, inferential statistics, or independent physical-sample claim is supported.",
    }


def build_payload(inputs: dict[str, Any], builder_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = inputs["analysis"]
    record_count = analysis.get("record_count")
    if not isinstance(record_count, int) or record_count < 1:
        raise FindingsError("Invalid paired-analysis record_count")
    metrics = analysis["metrics"]
    findings_metrics = {key: _build_metric(key, metrics[key], record_count) for key in EXPECTED_METRICS}
    payload = {
        "schema": SCHEMA,
        "dataset": analysis.get("dataset"),
        "study_version": analysis.get("study_version"),
        "record_count": analysis.get("record_count"),
        "source_investigation": analysis.get("source_investigation"),
        "analysis_type": "descriptive_cohort_findings_and_rankings",
        "ranking_scope": "separate rankings within O2, CO2, and CO; never compare or combine their numerical scales",
        "ranking_basis": "signed mean paired change from the verified paired-analysis artifact; median is shown as a direction/consistency context, not a second ranking axis",
        "metrics": findings_metrics,
        "sample_reuse_summary": analysis.get("sample_reuse_summary"),
        "measurement_provenance_caveats": analysis.get("measurement_provenance_caveats"),
        "scientific_use_constraints": analysis.get("scientific_use_constraints"),
        "inferential_statistics_produced": False,
        "causal_claims_produced": False,
        "independent_sample_inference": False,
        "cross_metric_ranking": False,
    }
    manifest = {
        "schema": "sira.psi25.findings_manifest.v1",
        "dataset": analysis.get("dataset"),
        "study_version": analysis.get("study_version"),
        "record_count": analysis.get("record_count"),
        "builder": {"path": "tools/firelab/psi25_findings.py", "sha256": builder_hash},
        "source_artifacts": {
            "paired_measurement_analysis": {
                "path": "paired_analysis_v1/paired_measurement_analysis.json",
                "bytes": inputs["analysis_bytes"],
                "sha256": inputs["analysis_sha256"],
            },
            "paired_analysis_manifest": {
                "path": "paired_analysis_v1/analysis_manifest.json",
                "bytes": inputs["analysis_manifest_bytes"],
                "sha256": inputs["analysis_manifest_sha256"],
            },
        },
        "metric_pair_counts": {key: findings_metrics[key]["pair_counts"] for key in EXPECTED_METRICS},
        "metric_cohort_counts": {key: findings_metrics[key]["cohort_count"] for key in EXPECTED_METRICS},
        "o2_calibration_caveat_included": bool((analysis.get("measurement_provenance_caveats") or {}).get("o2")),
        "independent_sample_inference": False,
        "inferential_statistics_produced": False,
        "causal_claims_produced": False,
        "cross_metric_ranking": False,
        "deterministic_build": True,
        "output_policy": "create_new_directory_refuse_overwrite",
    }
    if manifest["o2_calibration_caveat_included"] is not True:
        raise FindingsError("O2 calibration caveat missing from findings payload")
    return payload, manifest


def _write_json(path: Path, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8", newline="\n")


def _inside_repo(root: Path, relative: Path) -> Path:
    resolved = (root.resolve() / relative).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise FindingsError("Output path must remain inside the repository") from exc
    return resolved


def preflight(repo_root: Path, input_relative: Path = DEFAULT_INPUT, output_relative: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output = _inside_repo(repo_root, output_relative)
    if output.exists():
        raise FindingsError(f"Refusing to overwrite existing findings output: {output}")
    inputs = load_inputs(repo_root, input_relative)
    if inputs["analysis"].get("record_count") != 129:
        raise FindingsError("Production findings require exactly 129 canonical experiment records")
    builder = Path(__file__).resolve()
    payload, manifest = build_payload(inputs, sha256_file(builder))
    return {
        "repository": str(repo_root.resolve()),
        "record_count": payload["record_count"],
        "input_analysis_sha256": inputs["analysis_sha256"],
        "output": str(output),
        "output_exists": False,
        "metrics": {
            key: {
                "cohorts": value["cohort_count"],
                "rankable": value["rankable_cohort_count"],
                "not_rankable": value["not_rankable_cohort_count"],
            }
            for key, value in payload["metrics"].items()
        },
        "o2_caveat": manifest["o2_calibration_caveat_included"],
    }


def build(repo_root: Path, input_relative: Path = DEFAULT_INPUT, output_relative: Path = DEFAULT_OUTPUT) -> Path:
    output = _inside_repo(repo_root, output_relative)
    if output.exists():
        raise FindingsError(f"Refusing to overwrite existing findings output: {output}")
    inputs = load_inputs(repo_root, input_relative)
    if inputs["analysis"].get("record_count") != 129:
        raise FindingsError("Production findings require exactly 129 canonical experiment records")
    builder = Path(__file__).resolve()
    payload, manifest = build_payload(inputs, sha256_file(builder))
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".psi25-findings-stage-", dir=output.parent))
    try:
        payload_path = stage / "findings_ranking.json"
        _write_json(payload_path, payload)
        manifest["derived_output"] = {
            "path": "findings_ranking.json",
            "bytes": payload_path.stat().st_size,
            "sha256": sha256_file(payload_path),
        }
        _write_json(stage / "findings_manifest.json", manifest)
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="write new findings and ranking artifacts")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="repository-relative output directory")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        report = preflight(root, output_relative=Path(args.output))
        print("PSI-25 FINDINGS & RANKING PREFLIGHT PASSED")
        print(f"Repository: {report['repository']}")
        print(f"Canonical records represented: {report['record_count']}")
        print(f"Paired-analysis SHA-256 verified: {report['input_analysis_sha256']}")
        for metric, counts in report["metrics"].items():
            print(f"{metric.upper()}: {counts['cohorts']} cohorts · {counts['rankable']} rankable · {counts['not_rankable']} not rankable")
        print(f"O2 calibration caveat: {'included' if report['o2_caveat'] else 'MISSING'}")
        print("No cross-metric ranking, causal claims, or inferential statistics are produced.")
        if not args.build:
            print("DRY RUN ONLY — no files were changed.")
            print("Run with --build to create the findings artifacts.")
            return 0
        output = build(root, output_relative=Path(args.output))
        manifest = _read_json(output / "findings_manifest.json")
        print("PSI-25 FINDINGS & RANKING BUILD SUCCESS")
        print(f"Output directory: {output}")
        for metric, counts in manifest["metric_pair_counts"].items():
            print(f"{metric.upper()}: {counts['eligible_pairs']} eligible · {counts['excluded_pairs']} excluded")
        print("Analysis source and canonical dataset: unchanged")
        return 0
    except (FindingsError, OSError, ValueError) as exc:
        print(f"PSI-25 FINDINGS ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
