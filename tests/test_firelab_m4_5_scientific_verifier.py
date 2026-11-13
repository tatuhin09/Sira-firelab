from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import ast
import hashlib
import json
import math
import unittest
from pathlib import Path

from firelab_service import scientific_verifier as verifier


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@dataclass
class FakeEntry:
    investigation_id: str
    version: str
    record_count: int
    source_sha256: str
    records_sha256: str
    quality_sha256: str
    payload: dict
    title: str = "BASS-II"


def quality_dimensions(lineage: str = "aggregate_scope", statistical_scope: str = "descriptive_only") -> dict:
    return {"scientificTruth": "not_established_by_integrity_checks",
            "independentReplication": "not_performed", "missionTransferability": "not_established",
            "sourceIntegrity": "verified", "artifactIntegrity": "verified",
            "recordLineageIntegrity": lineage, "statisticalScope": statistical_scope}


def psi69_entry(unknown_outcome: bool = False) -> FakeEntry:
    fields = {
        "ambientPressureMmHg": ("Ambient pressure", "mmHg"),
        "oxygenMoleFraction": ("Oxygen mole fraction", ""),
        "nitrogenMoleFraction": ("Nitrogen mole fraction", ""),
        "coSourceMoleFraction": ("Source CO mole fraction", ""),
        "heliumMoleFraction": ("Helium mole fraction", ""),
        "initialDropletDiameterMm": ("Initial droplet diameter", "mm"),
        "visibleFlameExtinctionDiameterMm": ("Visible flame extinction diameter", "mm"),
        "burningRateMm2PerSec": ("Burning rate", "mm²/s"),
        "burnTimeSeconds": ("Burn time", "s"),
    }
    records = []
    for number in range(1, 275):
        fuel = "Heptane" if number % 2 else "Methanol"
        outcome = verifier.OUTCOME_ORDER[(number - 1) % 3]
        if unknown_outcome and number == 274:
            outcome = "Mystery"
        pressure = 760 if number <= 64 else 780
        oxygen = 0.21 if number <= 25 else (0.18 if number <= 64 else 0.21)
        quality = {key: "exact" for key in fields}
        if number > 258:
            quality["burningRateMm2PerSec"] = "missing"
        records.append({
            "testNumber": number,
            "fuel": fuel,
            "testEnd": outcome,
            "ambientPressureMmHg": pressure,
            "oxygenMoleFraction": oxygen,
            "nitrogenMoleFraction": 0.79,
            "coSourceMoleFraction": 0,
            "heliumMoleFraction": 0,
            "initialDropletDiameterMm": 1.2,
            "visibleFlameExtinctionDiameterMm": 0.8 + number / 1000,
            "burningRateMm2PerSec": 0.5 + number / 100 if number <= 258 else None,
            "burnTimeSeconds": 10.0 + number / 10,
            "quality": quality,
        })
    measurement_quality = {}
    for key, (label, unit) in fields.items():
        exact = 258 if key == "burningRateMm2PerSec" else 274
        missing = 16 if key == "burningRateMm2PerSec" else 0
        measurement_quality[key] = {
            "label": label, "unit": unit, "exact": exact, "approximate": 0,
            "missing": missing, "invalid": 0, "sourceHeader": key,
        }
    quality_report = {"recordCount": 274, "measurementQuality": measurement_quality}
    source_hash, records_hash, quality_hash = digest("flex-source"), digest("flex-records"), digest("flex-quality")
    bundle = {
        "manifest": {"recordCount": 274, "sourceVersion": "PSI-69 Version 5"},
        "records": records,
        "quality": quality_report,
        "sourceSha256": source_hash,
        "recordsSha256": records_hash,
        "qualitySha256": quality_hash,
    }
    return FakeEntry( verifier.PSI69_ID, "PSI-69 Version 5", 274, source_hash, records_hash, quality_hash,
                      {"bundle": bundle}, title="Flame Extinguishment Experiment")


def refs_for(entry: FakeEntry, iid: str) -> list[dict]:
    hashes = verifier._source_hashes(entry, iid)
    return [{"referenceId": key, "sha256": value} for key, value in hashes.items()]


def psi69_answer(entry: FakeEntry, operation: str) -> dict:
    records, quality, _ = verifier._psi69_records(entry)
    scope = verifier._OPERATION_SPECS[operation][2]
    groups, fuel_counts, outcome_counts, unknown = verifier._psi69_groups(records)
    compact_groups = [{"fuel": row["fuel"], "n": row["n"], "outcomes": row["outcomes"]} for row in groups]
    claim_result = {}
    lineage = {"mode": "registered_selection_scope", "supportingRecordIds": [], "excludedRecordIds": [],
               "supportingCount": 274, "excludedCount": 0, "selectionRule": "all source records", "complete": True}
    events = []
    answer_fields = {}
    if operation == "flex.dataset.snapshot":
        claim_type = "source_table_count"
        claim_result = {"recordCount": 274, "fuelCounts": fuel_counts,
                        "outcomeCounts": outcome_counts, "fuelOutcomeCounts": compact_groups}
        analysis_payload = {"record_count": 274, "outcomes": outcome_counts, "fuel_groups": groups}
    elif operation == "flex.outcomes.by_fuel":
        claim_type = "source_table_count"
        claim_result = {"recordCount": 274, "fuelCounts": fuel_counts,
                        "outcomeCounts": outcome_counts, "fuelOutcomeCounts": compact_groups}
        analysis_payload = {"groups": groups}
    elif operation == "flex.burning_rate.exact_by_fuel":
        claim_type = "descriptive_summary"
        selected, excluded, summaries = verifier._psi69_burning(records)
        lineage = {"mode": "registered_selection_scope", "supportingRecordIds": selected,
                   "excludedRecordIds": excluded, "supportingCount": len(selected),
                   "excludedCount": len(excluded), "selectionRule": "exact finite values", "complete": True}
        claim_result = {"exactRecordCount": len(selected), "unit": "mm²/s", "groups": summaries}
        answer_fields.update({"recordIds": selected, "burningRateSummaries": summaries})
        events.append({"type": "data.selected", "status": "complete",
                       "payload": {"record_count": len(selected), "record_ids": selected}})
        analysis_payload = {"exact_record_count": len(selected), "record_ids": selected, "groups": summaries}
        sample_size = len(selected)
    elif operation == "flex.measurement_quality":
        claim_type = "measurement_quality_observation"
        rows, consistent = verifier._psi69_measurement_quality(records, quality)
        fields = [{key: value for key, value in row.items() if key != "field"} for row in rows]
        claim_result = {"recordCount": 274, "measurementFields": fields}
        answer_fields["qualityRows"] = fields
        events.append({"type": "data.selected", "status": "complete", "payload": {"measurement_fields": 9}})
        analysis_payload = {"measurement_fields": 9}
        sample_size = 274
    elif operation == "flex.oxygen_cohort_sensitivity":
        claim_type = "observed_cohort_comparison"
        fixed_ids, broad_ids = [], []
        for row in records:
            pressure = verifier._psi69_exact(row, "ambientPressureMmHg")
            oxygen = verifier._psi69_exact(row, "oxygenMoleFraction")
            co_value = verifier._psi69_exact(row, "coSourceMoleFraction")
            helium = verifier._psi69_exact(row, "heliumMoleFraction")
            if pressure is not None and oxygen is not None and co_value is not None and helium is not None and 750 <= pressure <= 770 and co_value == 0 and helium == 0:
                broad_ids.append(row["testNumber"])
                if oxygen == verifier.FIXED_OXYGEN:
                    fixed_ids.append(row["testNumber"])
        fixed = verifier._compact_oxygen_slice([row for row in records if row["testNumber"] in set(fixed_ids)])
        broad = verifier._compact_oxygen_slice([row for row in records if row["testNumber"] in set(broad_ids)])
        comparison = {"filters": {"pressureMin": 750, "pressureMax": 770, "coSourceMoleFraction": 0, "heliumMoleFraction": 0},
                      "fixedOxygen": 0.21, "fixedRecordCount": len(fixed_ids), "broadRecordCount": len(broad_ids),
                      "fixed": {k: v for k, v in fixed.items() if k != "unknown_outcomes"},
                      "broad": {k: v for k, v in broad.items() if k != "unknown_outcomes"},
                      "fixedOrder": [x["outcome"] for x in fixed["ranked"]],
                      "broadOrder": [x["outcome"] for x in broad["ranked"]]}
        comparison["orderChanged"] = comparison["fixedOrder"] != comparison["broadOrder"]
        lineage = {"mode": "registered_selection_scope", "supportingRecordIds": broad_ids,
                   "excludedRecordIds": [row["testNumber"] for row in records if row["testNumber"] not in set(broad_ids)],
                   "supportingCount": len(broad_ids), "excludedCount": len(records) - len(broad_ids),
                   "selectionRule": "registered exact condition filters", "complete": True}
        claim_result = comparison
        answer_fields.update({"recordIds": broad_ids, "fixedRecordIds": fixed_ids, "oxygenComparison": comparison})
        events.append({"type": "data.selected", "status": "complete", "payload": {
            "fixed_record_ids": fixed_ids, "broad_record_ids": broad_ids,
            "fixed_count": len(fixed_ids), "broad_count": len(broad_ids)}})
        analysis_payload = {"fixed_count": len(fixed_ids), "broad_count": len(broad_ids),
                           "fixed_record_ids": fixed_ids, "broad_record_ids": broad_ids,
                           "oxygen_comparison": comparison}
        sample_size = len(broad_ids)
    else:
        raise AssertionError(operation)
    if operation in {"flex.dataset.snapshot", "flex.outcomes.by_fuel"}:
        sample_size = 274
    if operation == "flex.measurement_quality":
        pass
    events.append({"type": "analysis.completed", "status": "complete", "payload": analysis_payload})
    claim = {"claimId": operation + ".claim", "claimType": claim_type, "metric": "", "result": claim_result,
             "qualityDimensions": quality_dimensions("aggregate_scope", {
                 "source_table_count": "source_count_only",
                 "measurement_quality_observation": "quality_count_only",
             }.get(claim_type, "descriptive_only")),
             "recordLineage": lineage, "evidenceReferences": refs_for(entry, verifier.PSI69_ID)}
    return {
        "status": "completed", "investigationId": verifier.PSI69_ID, "analysisId": operation,
        "metric": "", "dataScope": scope, "sampleSize": sample_size,
        "scientificPlan": {"operationId": operation, "resolvedInvestigation": verifier.PSI69_ID, "metric": "", "dataScope": scope},
        "sourceHash": entry.source_sha256, "recordsHash": entry.records_sha256, "qualityHash": entry.quality_sha256,
        "events": events, "claimLedger": {
            "schema": verifier.CLAIM_LEDGER_SCHEMA, "ledgerVersion": 1, "investigationId": verifier.PSI69_ID,
            "sourceRelease": entry.version, "operationId": operation, "metric": "", "dataScope": scope,
            "ledgerStatus": "verified_provenance", "claims": [claim]},
        **answer_fields,
    }


def psi25_records() -> list[dict]:
    records = []
    for index in range(129):
        cohort = 0
        # 18 cohort IDs; the first three have 8 records, the remaining 15 have 7.
        if index < 24:
            cohort = index // 8
            member = index % 8
        else:
            cohort = 3 + (index - 24) // 7
            member = (index - 24) % 7
        sample_id = "S-REUSED" if index < 2 else f"S-{index:03d}"
        sample_reused = index < 2
        measurements = {}
        for metric, (initial_field, final_field, unit, _) in verifier.PSI25_METRICS.items():
            initial = Decimal("20") if metric == "co2" else (Decimal("100") if metric == "co" else Decimal("1"))
            delta = Decimal(cohort - 4) + Decimal(member - 3) / Decimal(10)
            final = initial + delta
            status = "numeric_exact"
            eligible = True
            if metric == "o2" and cohort == 17:
                status, eligible = "source_none", False
                initial_parsed = final_parsed = None
            else:
                initial_parsed, final_parsed = str(initial), str(final)
            if metric == "co" and index == 1:
                initial_parsed = "-1"
                final_parsed = "100"
            measurements[initial_field] = {"status": status, "aggregation_eligible": eligible,
                                           "parsed_decimal": initial_parsed, "unit": unit, "raw": initial_parsed}
            measurements[final_field] = {"status": status, "aggregation_eligible": eligible,
                                         "parsed_decimal": final_parsed, "unit": unit, "raw": final_parsed}
        records.append({
            "identity": {"pi": f"PI-{cohort:02d}", "record_key": f"R-{index+1:03d}",
                         "test_id": f"T-{index+1:03d}", "test_id_raw": str(index + 1)},
            "sample": {"id_raw": sample_id, "is_reused_exact_raw_id": sample_reused,
                       "reuse_count_exact_raw_id": 2 if sample_reused else 1},
            "material": {"canonical_class": "polymer"},
            "flow_restrictor": {"code": cohort % 3 + 1},
            "measurements": measurements,
        })
    return records


def psi25_entry_and_artifacts() -> tuple[FakeEntry, dict[str, dict]]:
    records = psi25_records()
    canonical = {"schema": "sira.firelab.psi25.canonical_records.v1", "record_count": 129,
                 "study_version": 4, "source_investigation": "PSI-25", "records": records}
    recomputed = {metric: verifier._psi25_recompute(records, metric) for metric in verifier.PSI25_METRICS}
    paired_metrics, findings_metrics, synthesis_metrics = {}, {}, {}
    for metric, data in recomputed.items():
        audit = []
        for row in data["rows"]:
            audit.append({"record_key": row["record_key"], "pair_eligible": row["pair_eligible"],
                          "delta_final_minus_initial": verifier._decimal_text(row["delta"]),
                          "exclusion_reasons": row["exclusion_reasons"], "pi": row["cohort"][0],
                          "material_class": row["cohort"][1], "flow_restrictor_code": row["cohort"][2],
                          "test_id": row["test_id"], "test_id_raw": row["test_id_raw"],
                          "sample_id_raw": row["sample_id_raw"], "sample_id_reused": row["sample_id_reused"],
                          "sample_id_reuse_count_exact_raw_id": row["sample_id_reuse_count_exact_raw_id"]})
        cohort_summaries = []
        for row in data["cohorts"]:
            st = row["statistics"]
            cohort_summaries.append({
                "cohort": row["cohort"], "records_in_cohort": row["records_in_cohort"],
                "eligible_pairs": row["eligible_pairs"], "excluded_pairs": row["excluded_pairs"],
                "distinct_exact_sample_ids_in_cohort": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "sample_reuse_caveat": row["sample_reuse_caveat"], "statistics_n_definition": row["statistics_n_definition"],
                "inferential_statistics_produced": False, "summary_status": row["summary_status"],
                "statistics": None if st is None else {"n": st["n"], "mean": verifier._decimal_text(st["mean"]),
                    "median": verifier._decimal_text(st["median"]), "minimum": verifier._decimal_text(st["minimum"]),
                    "maximum": verifier._decimal_text(st["maximum"])},
            })
        paired_metrics[metric] = {"pair_counts": data["pair_counts"], "record_level_audit": audit,
                                  "cohort_summaries": cohort_summaries}
        ranked, unranked = [], []
        for row in data["ranked"]:
            eligible = verifier._psi25_evidence_order(row["eligible_rows"])
            excluded = verifier._psi25_evidence_order(row["excluded_rows"])
            ranked.append({
                "cohort": row["cohort"], "rank": row["rank"], "display_order": row["display_order"],
                "eligible_pairs": row["eligible_pairs"], "excluded_pairs": row["excluded_pairs"],
                "records_in_cohort": row["records_in_cohort"],
                "distinct_exact_sample_ids_in_cohort": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "sample_reuse_caveat": row["sample_reuse_caveat"],
                "statistics_n_definition": row["statistics_n_definition"],
                "inferential_statistics_produced": False, "summary_status": row["summary_status"],
                "statistics": {
                    "n": row["statistics"]["n"], "mean": format(row["statistics"]["mean"], "f"),
                    "median": format(row["statistics"]["median"], "f"),
                    "minimum": format(row["statistics"]["minimum"], "f"), "maximum": format(row["statistics"]["maximum"], "f")},
                "mean_direction": row["mean_direction"], "mean_median_sign_relation": row["mean_median_sign_relation"],
                "absolute_mean_median_gap": format(row["absolute_mean_median_gap"], "f"),
                "eligible_record_evidence": [{"record_key": x["record_key"], "test_id": x["test_id"] or x["test_id_raw"],
                    "sample_id_raw": x["sample_id_raw"], "sample_id_reused": x["sample_id_reused"],
                    "delta_final_minus_initial": verifier._decimal_text(x["delta"])} for x in eligible],
                "excluded_record_evidence": [{"record_key": x["record_key"], "test_id": x["test_id"] or x["test_id_raw"],
                    "sample_id_raw": x["sample_id_raw"], "exclusion_reasons": x["exclusion_reasons"]} for x in excluded],
            })
        for row in data["unranked"]:
            excluded = verifier._psi25_evidence_order(row["excluded_rows"])
            unranked.append({"cohort": row["cohort"], "eligible_pairs": 0, "excluded_pairs": row["excluded_pairs"],
                "records_in_cohort": row["records_in_cohort"],
                "distinct_exact_sample_ids_in_cohort": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "sample_reuse_caveat": row["sample_reuse_caveat"],
                "statistics_n_definition": row["statistics_n_definition"],
                "inferential_statistics_produced": False, "summary_status": row["summary_status"],
                "not_rankable_reason": "no_eligible_pairs",
                "eligible_record_evidence": [], "excluded_record_evidence": [{"record_key": x["record_key"],
                    "test_id": x["test_id"] or x["test_id_raw"], "sample_id_raw": x["sample_id_raw"],
                    "exclusion_reasons": x["exclusion_reasons"]} for x in excluded]})
        def extreme(row):
            if row is None:
                return None
            return {"rank": row["rank"], "display_order": row["display_order"], "cohort": row["cohort"],
                "eligible_pairs": row["eligible_pairs"], "mean": format(row["statistics"]["mean"], "f"),
                "median": format(row["statistics"]["median"], "f"), "summary_status": row["summary_status"],
                "mean_median_sign_relation": row["mean_median_sign_relation"]}
        positive = next((row for row in data["ranked"] if row["statistics"]["mean"] > 0), None)
        negative = next((row for row in reversed(data["ranked"]) if row["statistics"]["mean"] < 0), None)
        extremes = {"highest_mean": extreme(data["ranked"][0] if data["ranked"] else None),
            "lowest_mean": extreme(data["ranked"][-1] if data["ranked"] else None),
            "strongest_positive_mean": extreme(positive), "most_negative_mean": extreme(negative)}
        findings_metrics[metric] = {"pair_counts": data["pair_counts"], "cohort_count": 18,
            "rankable_cohort_count": len(ranked), "not_rankable_cohort_count": len(unranked),
            "ranked_cohorts": ranked, "not_rankable_cohorts": unranked, "extremes": extremes}
        cards = []
        for ordinal, row in enumerate(data["ranked"] + data["unranked"], 1):
            eligible = verifier._psi25_evidence_order(row["eligible_rows"])
            excluded = verifier._psi25_evidence_order(row["excluded_rows"])
            stats = row["statistics"]
            directions = row.get("direction_counts", {})
            card = {
                "insight_id": f"PSI25-{metric.upper()}-{ordinal:03d}", "metric": metric, "cohort": row["cohort"],
                "rank": row["rank"], "eligible_pairs": row["eligible_pairs"], "excluded_pairs": row["excluded_pairs"],
                "records_in_cohort": row["records_in_cohort"],
                "distinct_exact_sample_ids": row["distinct_exact_sample_ids_in_cohort"],
                "records_marked_with_reused_sample_id": row["records_marked_with_reused_sample_id"],
                "summary_status": row["summary_status"], "interpretation_status": "not_rankable" if stats is None else "descriptive_only",
                "statistics_n_definition": row["statistics_n_definition"], "inferential_statistics_produced": False,
                "flags": verifier._psi25_flags(row, metric),
                "evidence_dimensions": {"measurement_caveat": "O2 sensor calibration caveat applies." if metric == "o2" else "Source eligibility applied."},
                "supporting_record_evidence": [
                    {"record_key": x["record_key"], "test_id": x["test_id"] or x["test_id_raw"], "sample_id_raw": x["sample_id_raw"],
                     "sample_id_reused": x["sample_id_reused"], "delta_final_minus_initial": verifier._decimal_text(x["delta"])} for x in eligible],
                "excluded_record_evidence": [{"record_key": x["record_key"], "test_id": x["test_id"] or x["test_id_raw"],
                    "sample_id_raw": x["sample_id_raw"], "exclusion_reasons": x["exclusion_reasons"]} for x in excluded],
            }
            if stats is not None:
                card.update({"statistics": {"n": stats["n"], "mean": format(stats["mean"], "f"),
                    "median": format(stats["median"], "f"), "minimum": format(stats["minimum"], "f"),
                    "maximum": format(stats["maximum"], "f")}, "direction_counts": directions,
                    "mean_direction": {"positive_mean_change": "positive", "negative_mean_change": "negative", "zero_mean_change": "zero"}.get(row["mean_direction"]),
                    "mean_median_sign_relation": row["mean_median_sign_relation"],
                    "absolute_mean_median_gap": format(row["absolute_mean_median_gap"], "f"),
                    "observed_range_includes_zero": row["observed_range_includes_zero"]})
            cards.append(card)
        synthesis_metrics[metric] = {"pair_counts": data["pair_counts"], "insight_cards": cards,
            "rankable_cohort_count": len(ranked), "not_rankable_cohort_count": len(unranked)}
    paired = {"dataset": "NASA PSI-25 BASS-II", "source_investigation": "PSI-25",
              "record_count": 129, "study_version": 4,
              "analysis_type": "paired_descriptive_concentration_change",
              "cohort_dimensions": ["pi", "canonical_material_class", "flow_restrictor_code"],
              "metrics": paired_metrics,
              "sample_reuse_summary": recomputed["co"]["sample_reuse_summary"]}
    for _metric_payload in paired_metrics.values():
        _metric_payload["paired_difference_definition"] = "final - initial"
        _metric_payload["inferential_statistics_produced"] = False
        _metric_payload["statistics_n_definition"] = "n counts eligible experiment records, not necessarily independent physical samples"
    findings = {"record_count": 129, "causal_claims_produced": False, "cross_metric_ranking": False,
                "inferential_statistics_produced": False, "independent_sample_inference": False,
                "metrics": findings_metrics}
    synthesis = {"record_count": 129, "metrics": synthesis_metrics, "generated_with_llm": False,
                 "measurement_provenance_caveats": {"o2": {"source_note": "O2 sensor out of calibration; daily constant-offset correction.",
                     "interpretation_limit": "Residual O2 measurement uncertainty is not quantified."}},
                 "safeguards": {"causal_claims_produced": False, "inferential_statistics_produced": False,
                    "independent_sample_inference": False, "cross_metric_ranking": False,
                    "operational_fire_safety_recommendations": False, "numeric_imputation": False,
                    "llm_generated_measurements_or_claims": False}}
    hashes = {"paired_analysis": digest("paired"), "findings": digest("findings"), "synthesis": digest("synthesis")}
    source_hash, records_hash, quality_hash = digest("psi25-source"), digest("psi25-records"), digest("psi25-quality")
    entry = FakeEntry(verifier.PSI25_ID, "Study Version 4", 129, source_hash, records_hash, quality_hash,
                      {"canonical": canonical, "paired": paired, "findings": findings,
                       "synthesis": synthesis, "artifact_sha256": hashes}, title="BASS-II")
    return entry, recomputed


def psi25_ledger(entry: FakeEntry, operation: str, metric: str, scope: str, recomputed: dict) -> dict:
    refs = refs_for(entry, verifier.PSI25_ID)
    claims = []
    if operation == "psi25.bass_ii.v4.snapshot":
        claims.append({"claimId": "psi25.bass_ii.v4.snapshot.record-count", "claimType": "source_table_count", "metric": "",
            "result": {"recordCount": 129}, "qualityDimensions": quality_dimensions("aggregate_scope", "source_count_only"),
            "recordLineage": {"mode": "registered_selection_scope", "supportingRecordIds": [],
                "excludedRecordIds": [], "supportingCount": 129, "excludedCount": 0, "complete": True},
            "evidenceReferences": refs[:2]})
        for key in ("o2", "co2", "co"):
            data = recomputed[key]
            claims.append({"claimId": f"psi25.bass_ii.v4.snapshot.{key}.pair-accounting", "claimType": "descriptive_summary", "metric": key,
                "result": {"recordCount": 129, "eligiblePairs": data["pair_counts"]["eligible_pairs"],
                    "excludedPairs": data["pair_counts"]["excluded_pairs"], "rankableCohorts": len(data["ranked"]),
                    "notRankableCohorts": len(data["unranked"]), "insightCards": 18},
                "qualityDimensions": quality_dimensions("aggregate_scope", "descriptive_only"),
                "recordLineage": {"mode": "registered_selection_scope", "supportingRecordIds": [],
                    "excludedRecordIds": [], "supportingCount": 129, "excludedCount": 0,
                    "selectionRule": "All 129 verified PSI-25 BASS-II canonical records; O2, CO2 and CO remain separate metric scopes.",
                    "complete": True}, "evidenceReferences": refs})
    else:
        data = recomputed[metric]
        for ordinal, card in enumerate(data["ranked"] + data["unranked"], 1):
            eligible = verifier._psi25_evidence_order(card["eligible_rows"])
            excluded = verifier._psi25_evidence_order(card["excluded_rows"])
            stats = card["statistics"]
            result_stats = {} if stats is None else {"n": stats["n"], "mean": format(stats["mean"], "f"),
                "median": format(stats["median"], "f"), "minimum": format(stats["minimum"], "f"), "maximum": format(stats["maximum"], "f")}
            cohort = card["cohort"]
            claims.append({"claimId": f"PSI25-{metric.upper()}-{ordinal:03d}", "claimType": "descriptive_cohort_finding",
                "metric": metric, "cohort": {"pi": cohort["pi"], "materialClass": cohort["material_class"],
                    "flowRestrictorCode": cohort["flow_restrictor_code"]},
                "result": {"rank": card["rank"], "eligiblePairs": len(eligible), "excludedPairs": len(excluded),
                    "recordsInCohort": card["records_in_cohort"], "statistics": result_stats,
                    "directionCounts": card.get("direction_counts", {}), "flags": verifier._psi25_flags(card, metric),
                    "distribution": "descriptive"},
                "recordLineage": {"mode": "explicit_canonical_record_keys",
                    "supportingRecordKeys": [x["record_key"] for x in eligible],
                    "excludedRecordKeys": [x["record_key"] for x in excluded],
                    "supportingCount": len(eligible), "excludedCount": len(excluded), "complete": True},
                "interpretationStatus": "descriptive_only" if stats is not None else "descriptive_with_limitations",
                "qualityDimensions": quality_dimensions("complete"), "evidenceReferences": refs})
    return {"schema": verifier.CLAIM_LEDGER_SCHEMA, "ledgerVersion": 1, "investigationId": verifier.PSI25_ID,
            "sourceRelease": "PSI-25 BASS-II Study Version 4", "operationId": operation,
            "metric": metric, "dataScope": scope, "ledgerStatus": "verified_provenance", "claims": claims}


def psi25_answer(entry: FakeEntry, operation: str, metric: str, scope: str, recomputed: dict) -> dict:
    if operation == "psi25.bass_ii.v4.snapshot":
        summary = {}
        for key, data in recomputed.items():
            summary[key] = {"metric": key, "eligible_pairs": data["pair_counts"]["eligible_pairs"],
                "excluded_pairs": data["pair_counts"]["excluded_pairs"], "rankable_cohorts": len(data["ranked"]),
                "not_rankable_cohorts": len(data["unranked"]), "insight_cards": 18}
        event_payload = {"record_count": 129, "metric_scopes": summary}
        sample_size = 129
        extra = {"metricSummary": summary}
    else:
        data = recomputed[metric]
        card_rows = []
        for row in data["ranked"][:5]:
            card_rows.append({"claim_id": f"PSI25-{metric.upper()}-{row['display_order']:03d}", "rank": row["rank"],
                "metric": metric, "cohort": row["cohort"], "statistics": {k: format(row["statistics"][k], "f") if isinstance(row["statistics"][k], Decimal) else row["statistics"][k]
                    for k in ("n", "mean", "median", "minimum", "maximum")},
                "interpretation": "", "distribution": "", "flags": [],
                "supporting_record_keys": [x["record_key"] for x in verifier._psi25_evidence_order(row["eligible_rows"])],
                "excluded_record_keys": [x["record_key"] for x in verifier._psi25_evidence_order(row["excluded_rows"])],
                "source_reference_ids": ["psi25-source-csv", "psi25-canonical-records", "psi25-paired-analysis", "psi25-findings", "psi25-synthesis"],
                "interpretation_status": "descriptive_only"})
        pairs = data["pair_counts"]
        event_payload = {"analysis_id": operation, "ranked_cohorts": len(data["ranked"]),
                         "not_rankable_cohorts": len(data["unranked"]), "record_reference_count": 0}
        sample_size = pairs["eligible_pairs"]
        extra = {"eligiblePairCount": pairs["eligible_pairs"], "excludedPairCount": pairs["excluded_pairs"],
                 "rankableCohortCount": len(data["ranked"]), "notRankableCohortCount": len(data["unranked"]),
                 "claimReferences": card_rows}
    return {"status": "completed", "investigationId": verifier.PSI25_ID, "analysisId": operation,
        "metric": metric, "dataScope": scope, "sampleSize": sample_size,
        "scientificPlan": {"operationId": operation, "resolvedInvestigation": verifier.PSI25_ID,
            "metric": metric, "dataScope": scope},
        "sourceHash": entry.source_sha256, "recordsHash": entry.records_sha256, "qualityHash": entry.quality_sha256,
        "events": [{"type": "analysis.completed", "status": "complete", "payload": event_payload}],
        "claimLedger": psi25_ledger(entry, operation, metric, scope, recomputed), **extra}


class FireLabScientificVerifierTests(unittest.TestCase):
    def test_psi69_all_five_registered_operations_verify(self):
        entry = psi69_entry()
        for operation in (
            "flex.dataset.snapshot", "flex.outcomes.by_fuel", "flex.burning_rate.exact_by_fuel",
            "flex.measurement_quality", "flex.oxygen_cohort_sensitivity",
        ):
            with self.subTest(operation=operation):
                result = verifier.verify_completed_answer(entry, psi69_answer(entry, operation))
                self.assertEqual(result["status"], "verified", result["checks"])

    def test_verifier_rejects_legacy_kind_event_discriminator(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.dataset.snapshot")
        event = next(item for item in answer["events"] if item.get("type") == "analysis.completed")
        event["kind"] = event.pop("type")
        self.assertNotEqual(verifier.verify_completed_answer(entry, answer)["status"], "verified")

    def test_psi25_metric_scope_and_inference_flags_are_checked(self):
        entry, recomputed = psi25_entry_and_artifacts()
        answer = psi25_answer(entry, "psi25.bass_ii.v4.snapshot", "", "all-records", recomputed)
        entry.payload["paired"]["metrics"]["co"]["inferential_statistics_produced"] = True
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_psi25_synthesis_direction_vocabulary_is_verified(self):
        entry, recomputed = psi25_entry_and_artifacts()
        answer = psi25_answer(entry, "psi25.bass_ii.v4.snapshot", "", "all-records", recomputed)
        entry.payload["synthesis"]["metrics"]["o2"]["insight_cards"][0]["mean_direction"] = "tampered"
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_psi25_top_five_reference_record_order_and_lineage_are_verified(self):
        entry, recomputed = psi25_entry_and_artifacts()
        answer = psi25_answer(entry, "psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence", recomputed)
        answer["claimReferences"][0]["supporting_record_keys"][0] = "FOREIGN-KEY"
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_psi69_numeric_tamper_fails_closed(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.dataset.snapshot")
        answer["claimLedger"]["claims"][0]["result"]["recordCount"] = 273
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_psi69_burning_rate_record_selection_tamper_fails(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.burning_rate.exact_by_fuel")
        answer["recordIds"][0] = 274
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_psi69_quality_count_tamper_fails(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.measurement_quality")
        answer["qualityRows"][0]["missing"] += 1
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_psi69_oxygen_gap_tamper_fails(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.oxygen_cohort_sensitivity")
        answer["oxygenComparison"]["fixed"]["ranked"][0]["gapPercentagePoints"] += 2
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_unknown_psi69_outcome_never_verifies(self):
        entry = psi69_entry(unknown_outcome=True)
        answer = psi69_answer(entry, "flex.dataset.snapshot")
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_psi69_wilson_reference_formula(self):
        low, high = verifier._wilson(5, 10)
        self.assertAlmostEqual(low, 0.2366, delta=5e-4)
        self.assertAlmostEqual(high, 0.7634, delta=5e-4)
        self.assertEqual(verifier._wilson(0, 12)[0], 0.0)
        self.assertEqual(verifier._wilson(12, 12)[1], 1.0)

    def test_psi69_gap_formula_and_order(self):
        groups = [
            {"fuel": "B", "n": 4, "outcomes": {"Extinction": 4, "Disruption": 0, "Completion": 0}},
            {"fuel": "A", "n": 4, "outcomes": {"Extinction": 0, "Disruption": 2, "Completion": 2}},
        ]
        ranked = verifier._psi69_gap_ranking(groups)
        self.assertEqual(ranked[0]["outcome"], "Extinction")
        self.assertEqual(ranked[0]["gapPercentagePoints"], 100.0)
        self.assertEqual(ranked[0]["left"]["fuel"], "A")

    def test_psi25_recomputation_matches_registered_pair_counts(self):
        records = psi25_records()
        o2 = verifier._psi25_recompute(records, "o2")
        co2 = verifier._psi25_recompute(records, "co2")
        co = verifier._psi25_recompute(records, "co")
        self.assertEqual(o2["pair_counts"]["records"], 129)
        self.assertEqual(len(o2["cohorts"]), 18)
        self.assertLess(o2["pair_counts"]["eligible_pairs"], 129)
        self.assertEqual(co2["pair_counts"]["eligible_pairs"], 129)
        self.assertEqual(co["pair_counts"]["eligible_pairs"], 128)

    def test_psi25_pair_eligibility_and_decimal_difference(self):
        record = psi25_records()[0]
        pair = verifier._psi25_pair(record, "co")
        self.assertTrue(pair["pair_eligible"])
        self.assertIsInstance(pair["delta"], Decimal)
        self.assertEqual(pair["delta"], Decimal("-4.3"))
        changed = deepcopy(record)
        changed["measurements"]["initial_co"]["unit"] = "% by volume"
        self.assertFalse(verifier._psi25_pair(changed, "co")["pair_eligible"])

    def test_psi25_snapshot_and_metric_family_verify(self):
        entry, recomputed = psi25_entry_and_artifacts()
        snapshot = psi25_answer(entry, "psi25.bass_ii.v4.snapshot", "", "all-records", recomputed)
        self.assertEqual(verifier.verify_completed_answer(entry, snapshot)["status"], "verified")
        for metric in ("o2", "co2", "co"):
            for suffix in ("insights", "ranking"):
                operation = f"psi25.bass_ii.v4.{metric}.{suffix}"
                metric_answer = psi25_answer(entry, operation, metric, "cohort-evidence", recomputed)
                result = verifier.verify_completed_answer(entry, metric_answer)
                self.assertEqual(result["status"], "verified", (operation, result["checks"]))

    def test_psi25_paired_delta_tamper_fails_even_with_hash_context(self):
        entry, recomputed = psi25_entry_and_artifacts()
        answer = psi25_answer(entry, "psi25.bass_ii.v4.snapshot", "", "all-records", recomputed)
        entry.payload["paired"]["metrics"]["co"]["record_level_audit"][0]["delta_final_minus_initial"] = "999"
        result = verifier.verify_completed_answer(entry, answer)
        self.assertEqual(result["status"], "failed")

    def test_psi25_claim_lineage_tamper_fails(self):
        entry, recomputed = psi25_entry_and_artifacts()
        answer = psi25_answer(entry, "psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence", recomputed)
        answer["claimLedger"]["claims"][0]["recordLineage"]["supportingRecordKeys"][0] = "FOREIGN-KEY"
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_research_questions_are_not_measurement_claims(self):
        entry, _ = psi25_entry_and_artifacts()
        operations = ["psi25.bass_ii.v4.research_questions"] + [
            f"psi25.bass_ii.v4.{metric}.research_questions" for metric in ("o2", "co2", "co")]
        for operation in operations:
            metric = "" if operation.endswith(".research_questions") and ".v4.research_questions" in operation else operation.split(".")[-2]
            answer = {"status": "completed", "investigationId": verifier.PSI25_ID,
                      "analysisId": operation, "metric": metric, "dataScope": "research-questions", "sampleSize": 1,
                      "scientificPlan": {"operationId": operation, "resolvedInvestigation": verifier.PSI25_ID,
                        "metric": metric, "dataScope": "research-questions"}}
            self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "not_applicable", operation)

    def test_psi25_zero_pair_cohort_remains_unranked(self):
        records = psi25_records()
        data = verifier._psi25_recompute(records, "o2")
        unranked = [row for row in data["unranked"] if row["eligible_pairs"] == 0]
        self.assertEqual(len(unranked), 1)
        self.assertIsNone(unranked[0]["statistics"])
        self.assertIsNone(unranked[0]["rank"])

    def test_psi25_tied_means_receive_competition_rank(self):
        records = psi25_records()
        initial_field, final_field, _unit, _label = verifier.PSI25_METRICS["co2"]
        for record in records:
            measurements = record["measurements"]
            initial = Decimal(measurements[initial_field]["parsed_decimal"])
            measurements[final_field]["parsed_decimal"] = str(initial + Decimal("1"))
        data = verifier._psi25_recompute(records, "co2")
        self.assertEqual(data["ranked"][0]["rank"], 1)
        self.assertEqual(data["ranked"][1]["rank"], 1)
        self.assertEqual(data["ranked"][1]["display_order"], 2)

    def test_psi25_o2_caveat_tamper_fails(self):
        entry, recomputed = psi25_entry_and_artifacts()
        answer = psi25_answer(entry, "psi25.bass_ii.v4.snapshot", "", "all-records", recomputed)
        entry.payload["synthesis"]["metrics"]["o2"]["insight_cards"][0]["flags"].remove("o2_sensor_calibration_limitation")
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_plan_optional_metric_field_is_not_required_when_omitted(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.dataset.snapshot")
        answer["scientificPlan"].pop("metric")
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "verified")

    def test_abstained_answer_is_not_applicable(self):
        result = verifier.verify_completed_answer(None, {"status": "abstained"})
        self.assertEqual(result["status"], "not_applicable")

    def test_missing_claim_ledger_is_unverifiable(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.dataset.snapshot")
        answer.pop("claimLedger")
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "unverifiable")

    def test_wrong_operation_scope_fails_closed(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.dataset.snapshot")
        answer["dataScope"] = "selected-records"
        self.assertEqual(verifier.verify_completed_answer(entry, answer)["status"], "failed")

    def test_inputs_are_not_mutated_and_report_is_bounded_json_safe(self):
        entry = psi69_entry()
        answer = psi69_answer(entry, "flex.dataset.snapshot")
        before = deepcopy(answer)
        report = verifier.verify_completed_answer(entry, answer)
        self.assertEqual(answer, before)
        self.assertLessEqual(len(report["checks"]), 240)
        self.assertLessEqual(len(report["claim_results"]), 30)
        self.assertEqual(report["schema"], verifier.VERIFIER_SCHEMA)
        json.dumps(report, allow_nan=False)

    def test_verifier_has_no_forbidden_project_imports(self):
        source = Path(verifier.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        forbidden = ("firelab_service.engine", "tools.firelab", "sira", "urllib", "requests", "httpx", "subprocess")
        self.assertFalse(any(any(name == root or name.startswith(root + ".") for root in forbidden) for name in imports), imports)


    def test_psi69_burning_quality_counters_match_independent_categories(self):
        entry = psi69_entry()
        records = deepcopy(entry.payload["bundle"]["records"])

        # The existing engine counts quality categories independently: a None
        # value can increment both missing and invalid/approximate counters.
        heptane = records[0]
        heptane["quality"]["burningRateMm2PerSec"] = "invalid"
        heptane["burningRateMm2PerSec"] = None
        methanol = records[1]
        methanol["quality"]["burningRateMm2PerSec"] = "approximate"
        methanol["burningRateMm2PerSec"] = None

        _selected, _excluded, groups = verifier._psi69_burning(records)
        by_fuel = {row["fuel"]: row for row in groups}
        self.assertEqual((by_fuel["Heptane"]["missing"], by_fuel["Heptane"]["invalid"]), (9, 1))
        self.assertEqual((by_fuel["Methanol"]["missing"], by_fuel["Methanol"]["approximate"]), (9, 1))


if __name__ == "__main__":
    unittest.main()
