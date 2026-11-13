#!/usr/bin/env python3
"""Deterministic, source-traceable paired descriptive analysis for NASA PSI-25 BASS-II.

This module does not alter canonical source/derived inputs. It computes exact paired
final-minus-initial concentration differences only when both source measurements are
explicitly numeric_exact and aggregation_eligible, with matching documented units.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

SCHEMA = "sira.psi25.paired_analysis.v1"
DEFAULT_OUTPUT = Path("firelab_site/data/derived/psi25_bass_ii_v4/paired_analysis_v1")
METRICS = {
    "o2": {
        "label": "Oxygen concentration change",
        "initial": "initial_o2",
        "final": "final_o2",
        "expected_unit": "% by volume",
    },
    "co2": {
        "label": "Carbon dioxide concentration change",
        "initial": "initial_co2",
        "final": "final_co2",
        "expected_unit": "% by volume",
    },
    "co": {
        "label": "Carbon monoxide concentration change",
        "initial": "initial_co",
        "final": "final_co",
        "expected_unit": "ppm",
    },
}
LIMITS = [
    "Descriptive within-record final-minus-initial differences only; no causal inference.",
    "No values are imputed, normalized, or converted between units.",
    "Only paired numeric_exact measurements with aggregation_eligible=true are included.",
    "Censored, over-range, approximate, negative-review, missing, and otherwise ineligible values are excluded and retained in the record-level audit.",
    "Cohorts are stratified by PI, canonical material class, and flow-restrictor code; no dataset-wide pooled summary is produced.",
    "Repeated Sample IDs do not merge experiment records; each canonical record key remains a separate experiment, but repeated IDs may represent dependent observations from the same physical sample.",
    "O2 sensor caveat: the BASS-II ReadMe states the O2 sensor was out of calibration and an MCA ISS reading was used for daily constant-offset correction; this engine uses canonical exported calibrated values as-is and does not independently validate calibration or residual uncertainty.",
    "Descriptive cohort statistics count eligible experiment records, not necessarily independent physical samples; no sample-cluster adjustment, standard errors, confidence intervals, p-values, or inferential comparisons are produced.",
    "A concentration difference is not an emission rate, heat-release rate, combustion efficiency, or independent measure of flame intensity.",
    "The fan calibration workbook, fan display, air display, and radiometer gain are not used in this analysis.",
]


class AnalysisError(RuntimeError):
    """Raised when canonical inputs fail integrity or schema checks."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"Cannot read valid JSON input: {path}") from exc


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise AnalysisError("Non-finite decimal encountered")
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def load_inputs(repo_root: Path) -> dict[str, Any]:
    base = repo_root / "firelab_site/data/derived/psi25_bass_ii_v4"
    paths = {
        "canonical_records": base / "canonical_records.json",
        "quality_report": base / "quality_report.json",
        "canonical_manifest": base / "canonical_manifest.json",
    }
    for label, path in paths.items():
        if not path.is_file():
            raise AnalysisError(f"Required {label} input is missing: {path}")

    canonical = _read_json(paths["canonical_records"])
    quality = _read_json(paths["quality_report"])
    manifest = _read_json(paths["canonical_manifest"])
    if not isinstance(canonical, dict) or not isinstance(canonical.get("records"), list):
        raise AnalysisError("canonical_records.json must contain a records array")
    records = canonical["records"]
    declared_count = canonical.get("record_count")
    if declared_count != len(records):
        raise AnalysisError("Canonical record_count does not match records array length")
    if quality.get("record_count") != len(records):
        raise AnalysisError("quality_report record_count does not match canonical records")
    if manifest.get("record_count") != len(records):
        raise AnalysisError("canonical_manifest record_count does not match canonical records")
    if canonical.get("study_version") != manifest.get("study_version"):
        raise AnalysisError("Canonical and manifest study versions do not agree")

    keys: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise AnalysisError(f"Record {index} is not an object")
        identity = record.get("identity") or {}
        key = identity.get("record_key")
        test_id = identity.get("test_id")
        if not isinstance(key, str) or not key or not isinstance(test_id, str) or not test_id:
            raise AnalysisError(f"Record {index} lacks a stable record_key/test_id")
        keys.append(key)
        if not isinstance(record.get("measurements"), dict):
            raise AnalysisError(f"Record {key} has no measurements object")
    if len(set(keys)) != len(keys):
        raise AnalysisError("Canonical record_key values are not unique")

    source_hashes = {
        label: {
            "path": str(path.relative_to(repo_root)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in paths.items()
    }
    return {
        "base": base,
        "canonical": canonical,
        "quality": quality,
        "manifest": manifest,
        "records": records,
        "source_hashes": source_hashes,
    }


def _cohort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    identity = record.get("identity") or {}
    material = record.get("material") or {}
    restrictor = record.get("flow_restrictor") or {}
    pi = str(identity.get("pi") or "not_stated")
    material_class = str(material.get("canonical_class") or "unclassified")
    code = restrictor.get("code")
    restrictor_code = str(code) if code in (0, 1, 2) else "not_stated"
    return pi, material_class, restrictor_code


def _pair_record(record: dict[str, Any], metric_key: str, spec: dict[str, str]) -> dict[str, Any]:
    measurements = record.get("measurements") or {}
    initial = measurements.get(spec["initial"]) or {}
    final = measurements.get(spec["final"]) or {}
    reasons: list[str] = []
    values: dict[str, Decimal | None] = {}

    for label, item in (("initial", initial), ("final", final)):
        status = item.get("status", "missing_status")
        eligible = item.get("aggregation_eligible") is True
        parsed = _parse_decimal(item.get("parsed_decimal"))
        if status != "numeric_exact":
            reasons.append(f"{label}_status_not_numeric_exact:{status}")
        if not eligible:
            reasons.append(f"{label}_aggregation_eligible_false")
        if parsed is None:
            reasons.append(f"{label}_parsed_decimal_missing_or_invalid")
        values[label] = parsed

    initial_unit = initial.get("unit")
    final_unit = final.get("unit")
    expected_unit = spec["expected_unit"]
    if initial_unit != final_unit:
        reasons.append("initial_final_unit_mismatch")
    if initial_unit != expected_unit or final_unit != expected_unit:
        reasons.append("unit_does_not_match_expected_documented_unit")

    # Defensive scientific guard: CO values below zero remain excluded even if an
    # upstream eligibility flag is accidentally changed in a future source revision.
    if metric_key == "co":
        for label, value in values.items():
            if value is not None and value < 0:
                reasons.append(f"{label}_negative_co_requires_review")

    eligible_pair = not reasons and values["initial"] is not None and values["final"] is not None
    delta = values["final"] - values["initial"] if eligible_pair else None
    identity = record.get("identity") or {}
    sample = record.get("sample") or {}
    material = record.get("material") or {}
    restrictor = record.get("flow_restrictor") or {}
    return {
        "record_key": identity.get("record_key"),
        "test_id": identity.get("test_id"),
        "test_id_raw": identity.get("test_id_raw"),
        "pi": identity.get("pi"),
        "date": (record.get("date") or {}).get("iso") or (record.get("date") or {}).get("raw"),
        "sample_id_raw": sample.get("id_raw"),
        "sample_id_reused": sample.get("is_reused_exact_raw_id") is True,
        "sample_id_reuse_count_exact_raw_id": sample.get("reuse_count_exact_raw_id"),
        "material_raw": material.get("raw"),
        "material_class": material.get("canonical_class") or "unclassified",
        "flow_restrictor_code": restrictor.get("code"),
        "initial": {
            "field": spec["initial"],
            "raw": initial.get("raw"),
            "status": initial.get("status"),
            "aggregation_eligible": initial.get("aggregation_eligible") is True,
            "parsed_decimal": _canonical_decimal(values["initial"]) if values["initial"] is not None else None,
            "unit": initial.get("unit"),
        },
        "final": {
            "field": spec["final"],
            "raw": final.get("raw"),
            "status": final.get("status"),
            "aggregation_eligible": final.get("aggregation_eligible") is True,
            "parsed_decimal": _canonical_decimal(values["final"]) if values["final"] is not None else None,
            "unit": final.get("unit"),
        },
        "pair_eligible": eligible_pair,
        "exclusion_reasons": sorted(set(reasons)),
        "delta_final_minus_initial": _canonical_decimal(delta) if delta is not None else None,
        "unit": expected_unit,
    }


def _stats(values: list[Decimal]) -> dict[str, Any]:
    ordered = sorted(values)
    with localcontext() as ctx:
        ctx.prec = 28
        mean = sum(ordered, Decimal(0)) / Decimal(len(ordered))
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    return {
        "n": len(ordered),
        "mean": _canonical_decimal(mean),
        "median": _canonical_decimal(median),
        "minimum": _canonical_decimal(ordered[0]),
        "maximum": _canonical_decimal(ordered[-1]),
    }


def build_payload(inputs: dict[str, Any], builder_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    records = inputs["records"]
    exact_sample_ids = [
        (record.get("sample") or {}).get("id_raw")
        for record in records
        if isinstance((record.get("sample") or {}).get("id_raw"), str)
        and (record.get("sample") or {}).get("id_raw") != ""
    ]
    exact_sample_counts = Counter(exact_sample_ids)
    sample_reuse_summary = {
        "distinct_nonblank_exact_raw_sample_ids": len(exact_sample_counts),
        "reused_exact_raw_id_groups": sum(count > 1 for count in exact_sample_counts.values()),
        "records_in_reused_exact_raw_id_groups": sum(count for count in exact_sample_counts.values() if count > 1),
        "records_flagged_reused_by_canonicalizer": sum(
            (record.get("sample") or {}).get("is_reused_exact_raw_id") is True
            for record in records
        ),
        "identifier_matching": "exact_raw_case_sensitive",
    }
    per_metric: dict[str, Any] = {}
    all_pair_counts: dict[str, Any] = {}

    for metric_key, spec in METRICS.items():
        audited_rows = [_pair_record(record, metric_key, spec) for record in records]
        group_values: dict[tuple[str, str, str], list[Decimal]] = defaultdict(list)
        group_counts: Counter[tuple[str, str, str]] = Counter()
        group_sample_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        group_reused_records: Counter[tuple[str, str, str]] = Counter()
        for record, row in zip(records, audited_rows):
            cohort = _cohort_key(record)
            group_counts[cohort] += 1
            if isinstance(row.get("sample_id_raw"), str) and row["sample_id_raw"] != "":
                group_sample_ids[cohort].add(row["sample_id_raw"])
            if row.get("sample_id_reused") is True:
                group_reused_records[cohort] += 1
            if row["pair_eligible"]:
                parsed_delta = _parse_decimal(row["delta_final_minus_initial"])
                if parsed_delta is None:
                    raise AnalysisError("Internal error: eligible pair has invalid delta")
                group_values[cohort].append(parsed_delta)

        summaries = []
        for cohort in sorted(group_counts):
            values = group_values.get(cohort, [])
            pi, material_class, restrictor_code = cohort
            summary = {
                "cohort": {
                    "pi": pi,
                    "material_class": material_class,
                    "flow_restrictor_code": restrictor_code,
                },
                "records_in_cohort": group_counts[cohort],
                "eligible_pairs": len(values),
                "excluded_pairs": group_counts[cohort] - len(values),
                "distinct_exact_sample_ids_in_cohort": len(group_sample_ids[cohort]),
                "records_marked_with_reused_sample_id": group_reused_records[cohort],
                "sample_reuse_caveat": "Repeated exact Sample IDs may indicate dependent experiment records; do not interpret record-pair n as independent physical-sample n.",
                "statistics_n_definition": "eligible experiment records; not necessarily independent physical samples",
                "inferential_statistics_produced": False,
                "summary_status": "no_eligible_pairs" if not values else ("small_n_descriptive_only" if len(values) < 5 else "descriptive_only"),
                "statistics": _stats(values) if values else None,
            }
            summaries.append(summary)

        eligible = sum(row["pair_eligible"] for row in audited_rows)
        excluded = len(audited_rows) - eligible
        all_pair_counts[metric_key] = {
            "records": len(audited_rows),
            "eligible_pairs": eligible,
            "excluded_pairs": excluded,
        }
        per_metric[metric_key] = {
            "label": spec["label"],
            "initial_field": spec["initial"],
            "final_field": spec["final"],
            "unit": spec["expected_unit"],
            "paired_difference_definition": "final - initial",
            "pair_counts": all_pair_counts[metric_key],
            "statistics_n_definition": "n counts eligible experiment records, not necessarily independent physical samples",
            "inferential_statistics_produced": False,
            "cohort_summaries": summaries,
            "record_level_audit": audited_rows,
        }

    payload = {
        "schema": SCHEMA,
        "dataset": "NASA PSI-25 BASS-II",
        "study_version": inputs["canonical"].get("study_version"),
        "source_investigation": inputs["canonical"].get("source_investigation"),
        "record_count": len(records),
        "analysis_type": "paired_descriptive_concentration_change",
        "cohort_dimensions": ["pi", "canonical_material_class", "flow_restrictor_code"],
        "metrics": per_metric,
        "sample_reuse_summary": sample_reuse_summary,
        "measurement_provenance_caveats": {
            "o2": {
                "source_document": "PSI-25_Science Documents_BASS-II_ReadMe.docx",
                "source_sha256": "69f32647792f54ab2a561e3cdafc6c87d854564fe487aed2b09265286bd84e1d",
                "source_note": "The BASS-II ReadMe states that the O2 sensor was out of calibration and that an MCA ISS reading was used for daily constant-offset correction.",
                "analysis_handling": "Use canonical exported calibrated values as recorded; no independent recalibration or new offset correction is performed.",
                "interpretation_limit": "O2 differences remain subject to the source-stated sensor/calibration limitation; residual measurement uncertainty is not quantified by this analysis.",
            }
        },
        "scientific_use_constraints": LIMITS,
    }
    manifest = {
        "schema": "sira.psi25.paired_analysis_manifest.v1",
        "dataset": "NASA PSI-25 BASS-II",
        "study_version": inputs["canonical"].get("study_version"),
        "record_count": len(records),
        "analysis_type": "paired_descriptive_concentration_change",
        "builder": {
            "path": "tools/firelab/psi25_analysis.py",
            "sha256": builder_hash,
        },
        "source_artifacts": inputs["source_hashes"],
        "pair_counts": all_pair_counts,
        "sample_reuse_summary": sample_reuse_summary,
        "o2_calibration_caveat_included": True,
        "independent_sample_inference": False,
        "output_policy": "create_new_directory_refuse_overwrite",
        "deterministic_build": True,
    }
    return payload, manifest


def _write_json(path: Path, value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8", newline="\n")


def build(repo_root: Path, output_relative: Path = DEFAULT_OUTPUT) -> Path:
    inputs = load_inputs(repo_root)
    output = (repo_root / output_relative).resolve()
    try:
        output.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise AnalysisError("Output path must remain inside the repository") from exc
    if output.exists():
        raise AnalysisError(f"Refusing to overwrite existing analysis output: {output}")
    builder_path = Path(__file__).resolve()
    builder_hash = sha256_file(builder_path)
    payload, manifest = build_payload(inputs, builder_hash)

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".psi25-analysis-stage-", dir=output.parent))
    try:
        analysis_path = stage / "paired_measurement_analysis.json"
        _write_json(analysis_path, payload)
        manifest["derived_output"] = {
            "path": "paired_measurement_analysis.json",
            "bytes": analysis_path.stat().st_size,
            "sha256": sha256_file(analysis_path),
        }
        _write_json(stage / "analysis_manifest.json", manifest)
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def preflight(repo_root: Path, output_relative: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    inputs = load_inputs(repo_root)
    output = repo_root / output_relative
    if output.exists():
        raise AnalysisError(f"Output already exists; build will not overwrite it: {output}")
    return {
        "repository": str(repo_root.resolve()),
        "record_count": len(inputs["records"]),
        "study_version": inputs["canonical"].get("study_version"),
        "source_hashes": inputs["source_hashes"],
        "output": str(output),
        "output_exists": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="write a new paired-analysis output directory")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="repository-relative output directory")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    output_relative = Path(args.output)
    try:
        report = preflight(repo_root, output_relative)
        print("PSI-25 PAIRED ANALYSIS PREFLIGHT PASSED")
        print(f"Repository: {report['repository']}")
        print(f"Canonical records: {report['record_count']}")
        print(f"Study version: {report['study_version']}")
        print(f"Output: {report['output']}")
        print("Source artifact SHA-256 checks: computed")
        print("No source or canonical input files will be modified.")
        if not args.build:
            print("DRY RUN ONLY — no files were changed.")
            print("Run with --build to create the new analysis output.")
            return 0
        output = build(repo_root, output_relative)
        result = _read_json(output / "analysis_manifest.json")
        print("PSI-25 PAIRED ANALYSIS BUILD SUCCESS")
        print(f"Output directory: {output}")
        for metric, counts in result["pair_counts"].items():
            print(f"{metric.upper()}: {counts['eligible_pairs']} eligible pairs; {counts['excluded_pairs']} excluded")
        print("Original source files modified: NO")
        print("Canonical records and quality report modified: NO")
        return 0
    except (AnalysisError, OSError, ValueError) as exc:
        print(f"PSI-25 ANALYSIS ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
