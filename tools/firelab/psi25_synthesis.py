#!/usr/bin/env python3
"""Deterministic, evidence-linked interpretation layer for NASA PSI-25 BASS-II.

This layer interprets verified precomputed findings. It does not recalculate
measurement statistics, infer causality, pool gas metrics, or make operational
fire-safety recommendations.
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

SCHEMA = "sira.psi25.evidence_synthesis.v1"
MANIFEST_SCHEMA = "sira.psi25.evidence_synthesis_manifest.v1"
DEFAULT_INPUT = Path("firelab_site/data/derived/psi25_bass_ii_v4/findings_ranking_v1")
DEFAULT_OUTPUT = Path("firelab_site/data/derived/psi25_bass_ii_v4/evidence_synthesis_v1")
EXPECTED_METRICS = ("o2", "co2", "co")
METRIC_LABELS = {
    "o2": "Oxygen concentration change",
    "co2": "Carbon dioxide concentration change",
    "co": "Carbon monoxide concentration change",
}


class SynthesisError(RuntimeError):
    """Raised when source integrity or synthesis invariants fail."""


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
        raise SynthesisError(f"Cannot read valid JSON: {path}") from exc


def _decimal(value: Any, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise SynthesisError(f"Missing numeric value for {label}")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SynthesisError(f"Invalid numeric value for {label}") from exc
    if not result.is_finite():
        raise SynthesisError(f"Non-finite numeric value for {label}")
    return result


def _fmt(value: Decimal) -> str:
    return format(value, "f")


def _mean_median_relation(mean: Decimal, median: Decimal) -> str:
    if mean == 0 and median == 0:
        return "both_zero"
    if mean == 0 or median == 0:
        return "one_zero"
    if (mean > 0 and median > 0) or (mean < 0 and median < 0):
        return "same_sign"
    return "opposite_sign"


def _group_label(group: dict[str, Any]) -> str:
    pi = group.get("pi") or "Unspecified PI"
    material = group.get("material_class") or "Unclassified material"
    flow = group.get("flow_restrictor_code")
    flow_text = "unspecified" if flow is None else str(flow)
    return f"{pi} · {material} · flow restrictor {flow_text}"


def _validate_inputs(repo_root: Path, input_relative: Path = DEFAULT_INPUT) -> dict[str, Any]:
    root = repo_root.resolve()
    input_dir = (root / input_relative).resolve()
    try:
        input_dir.relative_to(root)
    except ValueError as exc:
        raise SynthesisError("Findings input path must remain inside repository") from exc

    findings_path = input_dir / "findings_ranking.json"
    findings_manifest_path = input_dir / "findings_manifest.json"
    if not findings_path.is_file() or not findings_manifest_path.is_file():
        raise SynthesisError("Verified Findings & Ranking JSON and manifest are required")

    findings_hash = sha256_file(findings_path)
    findings_manifest_hash = sha256_file(findings_manifest_path)
    findings_bytes = findings_path.stat().st_size
    findings = _read_json(findings_path)
    findings_manifest = _read_json(findings_manifest_path)

    output_meta = findings_manifest.get("derived_output") or {}
    if output_meta.get("sha256") != findings_hash or output_meta.get("bytes") != findings_bytes:
        raise SynthesisError("Findings artifact SHA-256/byte-size does not match manifest")
    if findings.get("record_count") != 129 or findings_manifest.get("record_count") != 129:
        raise SynthesisError("Expected exactly 129 verified BASS-II experiment records")
    if findings_manifest.get("o2_calibration_caveat_included") is not True:
        raise SynthesisError("O2 calibration caveat is required")
    for flag in ("causal_claims_produced", "inferential_statistics_produced", "independent_sample_inference", "cross_metric_ranking"):
        if findings.get(flag) is not False:
            raise SynthesisError(f"Findings safeguard must remain false: {flag}")

    builder_path = root / "tools/firelab/psi25_findings.py"
    if not builder_path.is_file() or findings_manifest.get("builder", {}).get("sha256") != sha256_file(builder_path):
        raise SynthesisError("Findings builder hash does not match the production manifest")

    source_info = findings_manifest.get("source_artifacts", {}).get("paired_measurement_analysis") or {}
    pair_path = root / "firelab_site/data/derived/psi25_bass_ii_v4/paired_analysis_v1/paired_measurement_analysis.json"
    pair_manifest_path = pair_path.parent / "analysis_manifest.json"
    if not pair_path.is_file() or not pair_manifest_path.is_file():
        raise SynthesisError("Verified paired-analysis source and manifest are required")
    pair_hash = sha256_file(pair_path)
    pair_manifest_hash = sha256_file(pair_manifest_path)
    pair_manifest = _read_json(pair_manifest_path)
    pair_output = pair_manifest.get("derived_output") or {}
    if pair_hash != source_info.get("sha256") or pair_hash != pair_output.get("sha256"):
        raise SynthesisError("Findings-to-paired-analysis source lineage verification failed")
    if pair_path.stat().st_size != source_info.get("bytes") or pair_path.stat().st_size != pair_output.get("bytes"):
        raise SynthesisError("Paired-analysis source byte-size verification failed")
    if pair_manifest_hash != findings_manifest.get("source_artifacts", {}).get("paired_analysis_manifest", {}).get("sha256"):
        raise SynthesisError("Paired-analysis manifest lineage verification failed")

    metrics = findings.get("metrics") or {}
    if set(metrics) != set(EXPECTED_METRICS):
        raise SynthesisError("Findings must contain exactly O2, CO2, and CO metrics")

    return {
        "root": root,
        "findings": findings,
        "findings_manifest": findings_manifest,
        "findings_sha256": findings_hash,
        "findings_manifest_sha256": findings_manifest_hash,
        "findings_bytes": findings_bytes,
        "findings_manifest_bytes": findings_manifest_path.stat().st_size,
        "paired_analysis_sha256": pair_hash,
        "paired_analysis_manifest_sha256": pair_manifest_hash,
        "paired_analysis_bytes": pair_path.stat().st_size,
        "findings_builder_sha256": sha256_file(builder_path),
        "input_path": str(input_dir),
    }


def _interpret_cohort(metric_key: str, metric: dict[str, Any], cohort: dict[str, Any],
                      ordinal: int, rankable: bool) -> dict[str, Any]:
    group = cohort.get("cohort") or {}
    label = _group_label(group)
    evidence = cohort.get("eligible_record_evidence") or []
    excluded_evidence = cohort.get("excluded_record_evidence") or []
    flags: list[str] = []
    questions: list[dict[str, str]] = []

    n = int(cohort.get("eligible_pairs") or 0)
    excluded_count = int(cohort.get("excluded_pairs") or 0)
    records_in_cohort = int(cohort.get("records_in_cohort") or 0)
    reused_records = int(cohort.get("records_marked_with_reused_sample_id") or 0)
    distinct_ids = cohort.get("distinct_exact_sample_ids_in_cohort")
    if records_in_cohort != n + excluded_count:
        raise SynthesisError(f"Cohort pair accounting mismatch for {metric_key}: {label}")
    if len(evidence) != n or len(excluded_evidence) != excluded_count:
        raise SynthesisError(f"Evidence row counts mismatch for {metric_key}: {label}")

    if reused_records > 0:
        flags.append("sample_id_reuse_possible_dependence")
    if (group.get("material_class") or "unclassified").lower() == "unclassified":
        flags.append("material_class_unclassified")
    if metric_key == "o2":
        flags.append("o2_sensor_calibration_limitation")

    base = {
        "insight_id": f"PSI25-{metric_key.upper()}-{ordinal:03d}",
        "metric": metric_key,
        "label": metric.get("label") or METRIC_LABELS[metric_key],
        "unit": metric.get("unit"),
        "cohort": group,
        "cohort_label": label,
        "rank": cohort.get("rank") if rankable else None,
        "eligible_pairs": n,
        "excluded_pairs": int(cohort.get("excluded_pairs") or 0),
        "records_in_cohort": records_in_cohort,
        "distinct_exact_sample_ids": distinct_ids,
        "records_marked_with_reused_sample_id": reused_records,
        "statistics_n_definition": cohort.get("statistics_n_definition"),
        "summary_status": cohort.get("summary_status"),
        "inferential_statistics_produced": False,
        "evidence_dimensions": {
            "pair_coverage": {"eligible": n, "records": records_in_cohort},
            "sample_identity": {
                "distinct_exact_sample_ids": distinct_ids,
                "records_flagged_reused": reused_records,
                "independent_physical_sample_inference": False,
            },
            "replication": "No independent replication is established by this dataset-level analysis.",
            "measurement_caveat": "O2 sensor calibration/offset limitation applies; see source note." if metric_key == "o2" else "Source eligibility and censoring rules were applied; no imputation was performed.",
        },
        "flags": flags,
        "research_questions": questions,
        "supporting_record_evidence": evidence,
        "excluded_record_evidence": excluded_evidence,
    }

    if not rankable:
        if n != 0 or excluded_count != records_in_cohort or cohort.get("not_rankable_reason") != "no_eligible_pairs":
            raise SynthesisError(f"Invalid not-rankable cohort state for {metric_key}: {label}")
        flags.append("not_rankable_no_eligible_pairs")
        base.update({
            "interpretation_status": "not_rankable",
            "observation": f"{label}: no eligible exact initial/final pairs were available for {metric.get('label', metric_key)}. No mean or direction is assigned.",
            "distribution": "No eligible paired observations; excluded source records remain inspectable.",
            "mission_research_relevance": "This cohort identifies a data-resolution or measurement-documentation gap for follow-up research. It does not support a material-safety conclusion.",
        })
        questions.append({
            "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-EXCLUDED",
            "trigger": "no_eligible_pairs",
            "question": f"Can the source records for {label} be reviewed to resolve missing, censored, or flagged measurements without imputing or replacing source values?",
        })
        if reused_records > 0:
            questions.append({
                "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-SAMPLE",
                "trigger": "sample_id_reuse_possible_dependence",
                "question": f"Do the repeated exact Sample IDs in {label} represent repeat runs on the same physical samples, and should follow-up analysis account for that dependence?",
            })
        if (group.get("material_class") or "unclassified").lower() == "unclassified":
            questions.append({
                "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-MATERIAL",
                "trigger": "material_class_unclassified",
                "question": f"Can the retained NASA material description for {label} be resolved into a source-backed material class without guessing?",
            })
        if metric_key == "o2":
            questions.append({
                "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-CALIBRATION",
                "trigger": "o2_calibration_limitation",
                "question": "What residual O2 measurement uncertainty remains after the source-documented daily constant-offset correction, and are calibration records available to quantify it?",
            })
        return base

    stats = cohort.get("statistics") or {}
    if not isinstance(stats, dict) or n < 1 or stats.get("n") != n:
        raise SynthesisError(f"Invalid eligible cohort statistics n for {metric_key}: {label}")
    mean = _decimal(stats.get("mean"), f"{metric_key} cohort mean")
    median = _decimal(stats.get("median"), f"{metric_key} cohort median")
    minimum = _decimal(stats.get("minimum"), f"{metric_key} cohort minimum")
    maximum = _decimal(stats.get("maximum"), f"{metric_key} cohort maximum")
    gap = _decimal(cohort.get("absolute_mean_median_gap"), f"{metric_key} mean-median gap")
    deltas = [_decimal(row.get("delta_final_minus_initial"), f"{metric_key} evidence delta") for row in evidence]
    if len(deltas) != n or not deltas:
        raise SynthesisError(f"{metric_key} evidence rows do not match eligible pair count for {label}")
    if len({row.get("record_key") for row in evidence}) != len(evidence):
        raise SynthesisError(f"Duplicate supporting record key in {metric_key}: {label}")
    if minimum > maximum or not (minimum <= mean <= maximum):
        raise SynthesisError(f"Invalid cohort range or mean for {metric_key}: {label}")
    if minimum != min(deltas) or maximum != max(deltas):
        raise SynthesisError(f"Source evidence range does not match cohort summary for {metric_key}: {label}")
    if cohort.get("mean_median_sign_relation") != _mean_median_relation(mean, median):
        raise SynthesisError(f"Mean/median sign relation mismatch for {metric_key}: {label}")
    if gap != abs(mean - median):
        raise SynthesisError(f"Mean/median gap mismatch for {metric_key}: {label}")
    positive = sum(value > 0 for value in deltas)
    negative = sum(value < 0 for value in deltas)
    zero = sum(value == 0 for value in deltas)
    if positive + negative + zero != n:
        raise SynthesisError(f"Direction counts do not account for {metric_key} pairs: {label}")

    mean_text, median_text = _fmt(mean), _fmt(median)
    minimum_text, maximum_text = _fmt(minimum), _fmt(maximum)
    relation = cohort.get("mean_median_sign_relation")
    direction = "positive" if mean > 0 else "negative" if mean < 0 else "zero"
    mixed = positive > 0 and negative > 0
    includes_zero = minimum <= 0 <= maximum

    if cohort.get("summary_status") == "small_n_descriptive_only":
        flags.append("small_n_descriptive_only")
    if relation == "opposite_sign":
        flags.append("mean_median_opposite_sign")
    if gap > 0:
        flags.append("mean_median_gap_nonzero")
    if mixed:
        flags.append("mixed_positive_and_negative_record_changes")
    if includes_zero:
        flags.append("observed_range_includes_zero")
    if mixed:
        pattern = f"{positive} positive, {negative} negative, and {zero} zero paired changes; the cohort mean does not describe every experiment."
    elif positive == n:
        pattern = f"All {n} eligible experiment-record changes are positive. This is a within-cohort descriptive pattern, not a universal material property."
    elif negative == n:
        pattern = f"All {n} eligible experiment-record changes are negative. This is a within-cohort descriptive pattern, not a universal material property."
    elif zero == n:
        pattern = f"All {n} eligible experiment-record changes are zero at the precision recorded in the source."
    else:
        pattern = f"{positive} positive, {negative} negative, and {zero} zero paired changes were observed."

    observation = (
        f"Among {n} eligible experiment records in {label}, the mean final-minus-initial "
        f"{metric.get('label', metric_key).lower()} was {mean_text} {metric.get('unit')}; "
        f"the median was {median_text} {metric.get('unit')}, with an observed range of "
        f"{minimum_text} to {maximum_text} {metric.get('unit')}."
    )
    distribution = pattern
    if relation == "opposite_sign":
        distribution += " The mean and median have opposite signs; inspect record-level values before summarizing the direction."
    elif gap > 0:
        distribution += f" The mean–median gap is { _fmt(gap) } {metric.get('unit') }; this is a descriptive difference, not an outlier test."
    if metric_key == "o2":
        distribution += " O2 interpretation remains subject to the source-stated sensor calibration and daily offset-correction limitation."

    base.update({
        "interpretation_status": "descriptive_only",
        "mean_direction": direction,
        "direction_counts": {"positive": positive, "negative": negative, "zero": zero},
        "observed_range_includes_zero": includes_zero,
        "mean_median_sign_relation": relation,
        "absolute_mean_median_gap": _fmt(gap),
        "statistics": {
            "n": n,
            "mean": mean_text,
            "median": median_text,
            "minimum": minimum_text,
            "maximum": maximum_text,
        },
        "observation": observation,
        "distribution": distribution,
        "mission_research_relevance": "This cohort can help prioritize a matched follow-up combustion study. It does not qualify a material, identify a universally safer fuel, or specify an operational fire-suppression procedure.",
    })

    if "small_n_descriptive_only" in flags:
        questions.append({
            "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-REPEAT",
            "trigger": "small_n_descriptive_only",
            "question": f"Would a larger, matched set of {label} experiment records reproduce this descriptive pattern?",
        })
    if reused_records > 0:
        questions.append({
            "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-SAMPLE",
            "trigger": "sample_id_reuse_possible_dependence",
            "question": f"Do the repeated exact Sample IDs in {label} represent repeat runs on the same physical samples, and should follow-up analysis account for that dependence?",
        })
    if relation == "opposite_sign" or gap > 0:
        questions.append({
            "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-DISTRIBUTION",
            "trigger": "mean_median_divergence",
            "question": f"Which experiment-level values in {label} account for the observed mean–median difference, and is the pattern stable under a documented sensitivity review?",
        })
    if mixed:
        questions.append({
            "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-MIXED",
            "trigger": "mixed_record_directions",
            "question": f"Which recorded test conditions distinguish positive and negative paired changes within {label}, without assuming a causal effect?",
        })
    if "material_class_unclassified" in flags:
        questions.append({
            "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-MATERIAL",
            "trigger": "material_class_unclassified",
            "question": f"Can the retained NASA material description for {label} be resolved into a source-backed material class without guessing?",
        })
    if metric_key == "o2":
        questions.append({
            "question_id": f"RQ-{metric_key.upper()}-{ordinal:03d}-CALIBRATION",
            "trigger": "o2_calibration_limitation",
            "question": "What residual O2 measurement uncertainty remains after the source-documented daily constant-offset correction, and are calibration records available to quantify it?",
        })
    return base


def build_payload(inputs: dict[str, Any], builder_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    findings = inputs["findings"]
    record_count = findings["record_count"]
    metric_payload: dict[str, Any] = {}
    all_questions: list[dict[str, str]] = []
    insight_count = 0
    not_rankable_total = 0

    for metric_key in EXPECTED_METRICS:
        metric = findings["metrics"][metric_key]
        ranked = metric.get("ranked_cohorts") or []
        not_ranked = metric.get("not_rankable_cohorts") or []
        if len(ranked) + len(not_ranked) != metric.get("cohort_count"):
            raise SynthesisError(f"Cohort count mismatch in {metric_key}")
        pair_counts = metric.get("pair_counts") or {}
        if pair_counts.get("records") != record_count or pair_counts.get("eligible_pairs", 0) + pair_counts.get("excluded_pairs", 0) != record_count:
            raise SynthesisError(f"Pair accounting mismatch in {metric_key}")

        cards: list[dict[str, Any]] = []
        for ordinal, cohort in enumerate(ranked, 1):
            card = _interpret_cohort(metric_key, metric, cohort, ordinal, True)
            cards.append(card)
            all_questions.extend(card["research_questions"])
        for ordinal, cohort in enumerate(not_ranked, len(ranked) + 1):
            card = _interpret_cohort(metric_key, metric, cohort, ordinal, False)
            cards.append(card)
            all_questions.extend(card["research_questions"])

        keys = [row.get("record_key") for card in cards for row in (card.get("supporting_record_evidence", []) + card.get("excluded_record_evidence", []))]
        if len(keys) != record_count or len(set(keys)) != record_count:
            raise SynthesisError(f"Evidence coverage is not exactly {record_count} unique records in {metric_key}")

        caveat = "O2 cohort differences inherit the source-stated sensor calibration and daily offset-correction limitation; residual uncertainty is not quantified." if metric_key == "o2" else "Interpret only as source-reported paired concentration changes; excluded or censored values are not imputed."
        metric_payload[metric_key] = {
            "label": metric.get("label") or METRIC_LABELS[metric_key],
            "unit": metric.get("unit"),
            "pair_counts": pair_counts,
            "rankable_cohort_count": len(ranked),
            "not_rankable_cohort_count": len(not_ranked),
            "insight_cards": cards,
            "interpretation_limit": caveat,
        }
        insight_count += len(cards)
        not_rankable_total += len(not_ranked)

    # Dataset-level research questions are deliberately not merged into a score.
    global_questions = [{
        "question_id": "RQ-GLOBAL-SAMPLE-DEPENDENCE",
        "metric": "all",
        "trigger": "sample_reuse_across_dataset",
        "question": "Which repeated exact Sample IDs correspond to repeat runs on the same physical sample, and what dependence-aware design is appropriate for future analysis?",
    }, {
        "question_id": "RQ-GLOBAL-COHORT-COMPARABILITY",
        "metric": "all",
        "trigger": "cohort_comparability",
        "question": "Which experiment conditions must be matched before two PI/material/flow cohorts can be compared without confounding by test design or source scope?",
    }, {
        "question_id": "RQ-GLOBAL-MISSION-TRANSFER",
        "metric": "all",
        "trigger": "mission_transfer_gap",
        "question": "What additional matched microgravity, partial-gravity, atmosphere, geometry, and suppression experiments are required before laboratory observations can inform spacecraft-specific fire-safety requirements?",
    }]
    all_questions.extend(global_questions)

    payload = {
        "schema": SCHEMA,
        "dataset": findings.get("dataset", "NASA PSI-25 BASS-II"),
        "source_investigation": findings.get("source_investigation"),
        "study_version": findings.get("study_version"),
        "record_count": record_count,
        "synthesis_mode": "deterministic_rule_based_evidence_interpretation",
        "generated_with_llm": False,
        "interpretation_scope": "descriptive_within_metric_and_within_cohort_only",
        "metrics": metric_payload,
        "insight_card_count": insight_count,
        "not_rankable_cohort_count": not_rankable_total,
        "research_questions": all_questions,
        "evidence_dimensions": [
            {"dimension": "measurement_pair_coverage", "meaning": "Eligible exact initial/final pairs and exclusions are reported for each cohort."},
            {"dimension": "sample_identity_and_dependence", "meaning": "Exact Sample ID reuse is visible; experiment-record count is not treated as independent physical-sample count."},
            {"dimension": "measurement_validity", "meaning": "Source calibration limitations, censoring, missingness, and review flags are preserved."},
            {"dimension": "reproducibility", "meaning": "Artifact and builder hashes provide provenance; this is not independent scientific replication."},
            {"dimension": "mission_transfer", "meaning": "Laboratory observations identify research priorities only; spacecraft qualification and operational procedures are out of scope."},
        ],
        "measurement_provenance_caveats": findings.get("measurement_provenance_caveats", {}),
        "sample_reuse_summary": findings.get("sample_reuse_summary", {}),
        "scientific_use_constraints": findings.get("scientific_use_constraints", []),
        "safeguards": {
            "causal_claims_produced": False,
            "inferential_statistics_produced": False,
            "independent_sample_inference": False,
            "cross_metric_ranking": False,
            "operational_fire_safety_recommendations": False,
            "numeric_imputation": False,
            "llm_generated_measurements_or_claims": False,
        },
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "dataset": payload["dataset"],
        "study_version": payload["study_version"],
        "record_count": record_count,
        "builder": {"path": "tools/firelab/psi25_synthesis.py", "sha256": builder_hash},
        "source_artifacts": {
            "findings_ranking": {"path": "../findings_ranking_v1/findings_ranking.json", "sha256": inputs["findings_sha256"], "bytes": inputs["findings_bytes"]},
            "findings_manifest": {"path": "../findings_ranking_v1/findings_manifest.json", "sha256": inputs["findings_manifest_sha256"], "bytes": inputs["findings_manifest_bytes"]},
            "paired_measurement_analysis": {"path": "../paired_analysis_v1/paired_measurement_analysis.json", "sha256": inputs["paired_analysis_sha256"], "bytes": inputs["paired_analysis_bytes"]},
            "paired_analysis_manifest": {"path": "../paired_analysis_v1/analysis_manifest.json", "sha256": inputs["paired_analysis_manifest_sha256"]},
        },
        "insight_card_count": insight_count,
        "research_question_count": len(all_questions),
        "not_rankable_cohort_count": not_rankable_total,
        "deterministic_build": True,
        "llm_used": False,
        "causal_claims_produced": False,
        "inferential_statistics_produced": False,
        "independent_sample_inference": False,
        "cross_metric_ranking": False,
        "output_policy": "create_new_directory_refuse_overwrite",
    }
    return payload, manifest


def _encode_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build(repo_root: Path, output_relative: Path = DEFAULT_OUTPUT) -> Path:
    inputs = _validate_inputs(repo_root)
    root = repo_root.resolve()
    output = (root / output_relative).resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise SynthesisError("Output path must remain inside repository") from exc
    if output.exists():
        raise SynthesisError(f"Refusing to overwrite existing synthesis output: {output}")
    builder_path = Path(__file__).resolve()
    payload, manifest = build_payload(inputs, sha256_file(builder_path))
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".psi25-synthesis-stage-", dir=output.parent))
    try:
        data_path = stage / "evidence_synthesis.json"
        data_path.write_bytes(_encode_json(payload))
        manifest["derived_output"] = {"path": data_path.name, "bytes": data_path.stat().st_size, "sha256": sha256_file(data_path)}
        (stage / "synthesis_manifest.json").write_bytes(_encode_json(manifest))
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return output


def preflight(repo_root: Path, output_relative: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    inputs = _validate_inputs(repo_root)
    root = repo_root.resolve()
    output = (root / output_relative).resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise SynthesisError("Output path must remain inside repository") from exc
    if output.exists():
        raise SynthesisError(f"Synthesis output already exists; refusing overwrite: {output}")
    payload, manifest = build_payload(inputs, "preflight-builder-hash")
    return {
        "repository": str(root),
        "record_count": payload["record_count"],
        "findings_sha256": inputs["findings_sha256"],
        "paired_analysis_sha256": inputs["paired_analysis_sha256"],
        "insight_card_count": payload["insight_card_count"],
        "research_question_count": manifest["research_question_count"],
        "metric_counts": {key: {"rankable": payload["metrics"][key]["rankable_cohort_count"], "not_rankable": payload["metrics"][key]["not_rankable_cohort_count"], "cards": len(payload["metrics"][key]["insight_cards"])} for key in EXPECTED_METRICS},
        "output": str(output),
        "output_exists": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="write new deterministic evidence-synthesis artifacts")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="repository-relative output directory")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        report = preflight(root, Path(args.output))
        print("PSI-25 EVIDENCE SYNTHESIS PREFLIGHT PASSED")
        print(f"Repository: {report['repository']}")
        print(f"Canonical records represented: {report['record_count']}")
        print(f"Verified findings SHA-256: {report['findings_sha256']}")
        print(f"Verified paired-analysis SHA-256: {report['paired_analysis_sha256']}")
        for key in EXPECTED_METRICS:
            item = report["metric_counts"][key]
            print(f"{key.upper()}: {item['cards']} insight cards · {item['rankable']} rankable · {item['not_rankable']} not rankable")
        print(f"Research questions: {report['research_question_count']}")
        print("Deterministic interpretation: no LLM-generated measurements or claims")
        print("No causal claims, inferential statistics, cross-metric ranking, or operational safety advice")
        print(f"Output: {report['output']}")
        if not args.build:
            print("DRY RUN ONLY — no files were changed.")
            print("Run with --build to create the synthesis artifacts.")
            return 0
        output = build(root, Path(args.output))
        manifest = _read_json(output / "synthesis_manifest.json")
        print("PSI-25 EVIDENCE SYNTHESIS BUILD SUCCESS")
        print(f"Output directory: {output}")
        print(f"Insight cards: {manifest['insight_card_count']}")
        print(f"Research questions: {manifest['research_question_count']}")
        print("Findings, paired analysis, canonical data and NASA sources: unchanged")
        return 0
    except (SynthesisError, OSError, ValueError) as exc:
        print(f"PSI-25 SYNTHESIS ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
