"""Deterministic, server-side SIRA FireLab evidence assistant.

This service is deliberately model-free: it routes a small allowlist of
questions to reviewed calculations in ``firelab_service.engine``. It never
calls a provider, accesses SIRA private memory, or accepts user-supplied tools,
filters, file paths, or URLs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import unicodedata
import uuid
from typing import Any

from . import engine
from .scientific_planner import classify_psi69_intent, validate_psi69_scientific_plan

MAX_QUESTION_CHARS = 400
_CONVERSATION_ID = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_question(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("question must be text")
    text = unicodedata.normalize("NFKC", value)
    if _CONTROL.search(text) or any(unicodedata.category(ch) in {"Cf", "Cs"} for ch in text):
        raise ValueError("question contains unsupported characters")
    text = " ".join(text.split())
    if not 3 <= len(text) <= MAX_QUESTION_CHARS or not any(ch.isalnum() for ch in text):
        raise ValueError("question length or content is invalid")
    return text


def normalize_conversation_id(value: object) -> str:
    if not isinstance(value, str) or not _CONVERSATION_ID.fullmatch(value):
        raise ValueError("conversation_id is invalid")
    return value


def _event(conversation_id: str, turn_id: str, sequence: int, kind: str,
           status: str, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "sequence": sequence,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "type": kind,
        "status": status,
        "summary": summary,
        "payload": payload or {},
    }


def _classify(question: str) -> str:
    """Compatibility wrapper around the shared scientific planner classifier."""
    return classify_psi69_intent(question)


class FireLabEvidenceAssistant:
    """Answer questions from one hash-verified NASA PSI-69 bundle."""

    def __init__(self, bundle: dict[str, Any]):
        self.bundle = bundle
        self.manifest = bundle["manifest"]
        self.quality = bundle["quality"]
        self.records = bundle["records"]
        if len(self.records) != self.manifest.get("recordCount"):
            raise ValueError("FireLab assistant record count mismatch")

    def _base(self, question: str, conversation_id: str, intent: str) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
        turn_id = str(uuid.uuid4())
        events = [_event(conversation_id, turn_id, 1, "turn.started", "accepted", "Question accepted by the FireLab evidence service.", {"intent": intent})]
        return {
            "title": "SIRA FireLab evidence result",
            "text": "",
            "bullets": [],
            "evidence": [],
            "trace": [],
            "fields": [],
            "sampleSize": 0,
            "dataScope": "none",
            "recordIds": [],
            "qualityRows": [],
            "source": self.manifest.get("source", "NASA PSI-69"),
            "sourceFile": self.manifest.get("sourceFile", ""),
            "sourceVersion": self.manifest.get("sourceVersion", ""),
            "sourceHash": self.bundle.get("sourceSha256", ""),
            "recordsHash": self.bundle.get("recordsSha256", ""),
            "qualityHash": self.bundle.get("qualitySha256", ""),
            "sourceUrl": self.manifest.get("sourceUrl", ""),
            "reportUrl": self.manifest.get("reportUrl", ""),
            "doi": self.manifest.get("doi", ""),
            "license": self.manifest.get("license", ""),
            "analysisId": "",
            "analysisVersion": 1,
            "intent": intent,
            "status": "abstained",
            "events": events,
        }, events, turn_id

    def _finish(self, answer: dict[str, Any], events: list[dict[str, Any]], turn_id: str,
                status: str, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        answer["status"] = status
        kind = "answer.completed" if status == "completed" else "answer.abstained"
        events.append(_event(events[0]["conversation_id"], turn_id, len(events) + 1,
                             kind, status, summary, payload))
        answer["events"] = events
        return answer

    def ask(self, question: object, *, conversation_id: object, scientific_plan: object = None) -> dict[str, Any]:
        question = normalize_question(question)
        conversation_id = normalize_conversation_id(conversation_id)
        if scientific_plan is None:
            intent = _classify(question)
        else:
            validated_plan = validate_psi69_scientific_plan(scientific_plan, question)
            intent = validated_plan.intent
        answer, events, turn_id = self._base(question, conversation_id, intent)

        if intent in {"safety_or_causality", "unsupported"}:
            if intent == "safety_or_causality":
                answer.update({
                    "title": "The available dataset cannot establish a safety ranking or causal effect.",
                    "text": ("The PSI-69 table can support descriptive summaries, but the requested safety, "
                             "causal, predictive, or prescriptive conclusion is not established by the "
                             "approved analyses. Pressure, oxygen, suppressant mixture, and other test "
                             "conditions can differ between groups."),
                    "bullets": [
                        "No safety ranking, causal effect, prediction, or operational recommendation was calculated.",
                        "A condition-aware, prespecified analysis and scientific review would be required.",
                    ],
                    "evidence": ["Abstained", "No calculation run", "No causal or safety claim"],
                    "trace": ["Classified the request as a safety/causality question outside the approved evidence contract.",
                              "Did not filter source rows or run a calculation."],
                })
            else:
                answer.update({
                    "title": "This question is not covered by the approved FireLab analyses yet.",
                    "text": ("I can currently summarize the NASA FLEX dataset, compare reported outcomes "
                             "by fuel, inspect measurement quality, summarize exact burning-rate values, "
                             "and compare the approved oxygen cohorts. No analysis was run for this question."),
                    "bullets": [
                        "Try: “Summarize the FLEX dataset.”",
                        "Try: “Show outcome counts by fuel.”",
                        "Try: “Compare oxygen conditions.”",
                        "Try: “What should I know about data quality?”",
                    ],
                    "evidence": ["Approved analysis allowlist", "No analysis run"],
                    "trace": ["No registered analysis matched the question.", "No source rows were filtered and no calculation was performed."],
                })
            return self._finish(answer, events, turn_id, "abstained", "No analysis was run.")

        m = self.manifest
        analysis_ids = {
            "dataset_summary": "flex.dataset.snapshot",
            "outcomes_by_fuel": "flex.outcomes.by_fuel",
            "burning_rate": "flex.burning_rate.exact_by_fuel",
            "data_quality": "flex.measurement_quality",
            "oxygen_sensitivity": "flex.oxygen_cohort_sensitivity",
        }
        answer["analysisId"] = analysis_ids[intent]
        source_payload = {
            "source_id": "nasa-psi-69-flex-v5",
            "title": m.get("title", "Flame Extinguishment Experiment"),
            "version": m.get("sourceVersion"),
            "source_url": m.get("sourceUrl"),
            "report_url": m.get("reportUrl"),
            "sha256": self.bundle.get("sourceSha256"),
        }
        events.append(_event(conversation_id, turn_id, len(events) + 1,
                             "source.opened", "verified", "Opened the hash-verified NASA PSI-69 FLEX bundle.", source_payload))
        answer["evidence"] = [
            f"{m.get('recordCount', len(self.records))} retained FLEX records",
            m.get("source", "NASA PSI-69"),
            f"{m.get('sourceVersion', 'FLEX release')}",
            f"Source SHA-256 {self.bundle.get('sourceSha256', '')}",
        ]

        if intent == "dataset_summary":
            rows = self.records
            fields = ["testNumber", "fuel", "testEnd"]
            events.append(_event(conversation_id, turn_id, len(events) + 1, "data.selected", "complete",
                                 f"Selected all {len(rows)} retained NASA FLEX records.",
                                 {"record_count": len(rows), "fields": fields}))
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.started", "running",
                                 "Counting records by fuel and reported outcome."))
            groups = engine.summarize_by_fuel(rows)
            outcomes = engine.counts_by(rows, "testEnd")
            bullets = [f"{group['fuel']}: n={group['n']}" for group in groups]
            bullets.extend(f"{name}: {outcomes.get(name, 0)}" for name in engine.OUTCOME_ORDER)
            answer.update({
                "title": "NASA PSI-69 FLEX dataset snapshot.",
                "text": (f"The verified {m.get('sourceVersion', 'FLEX')} bundle contains {len(rows)} "
                         "retained experiment records. These are source-table counts, not a scientific or safety conclusion."),
                "bullets": bullets,
                "fields": fields,
                "sampleSize": len(rows),
                "dataScope": "all-records",
                "trace": [f"Loaded {len(rows)} retained records from the hash-verified source bundle.",
                          "Grouped rows by source-reported fuel and counted source-reported Test end categories.",
                          "No records were imputed, reclassified, or treated as adjusted effects."],
            })
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.completed", "complete",
                                 "Completed source-table counts.", {"record_count": len(rows), "outcomes": outcomes,
                                 "fuel_groups": groups}))

        elif intent == "outcomes_by_fuel":
            rows = self.records
            fields = ["testNumber", "fuel", "testEnd"]
            events.append(_event(conversation_id, turn_id, len(events) + 1, "data.selected", "complete",
                                 f"Selected all {len(rows)} retained records.", {"record_count": len(rows), "fields": fields}))
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.started", "running",
                                 "Grouping source outcomes by fuel."))
            groups = engine.summarize_by_fuel(rows)
            bullets = []
            for group in groups:
                outcome_text = ", ".join(f"{name} {group['outcomes'].get(name, 0)}" for name in engine.OUTCOME_ORDER)
                bullets.append(f"{group['fuel']} (n={group['n']}): {outcome_text}")
            answer.update({
                "title": "Reported test outcomes grouped by fuel.",
                "text": ("These are unadjusted counts from the source-reported fuel and Test end fields. "
                         "They do not establish a fuel effect or comparative safety."),
                "bullets": bullets,
                "fields": fields,
                "sampleSize": len(rows),
                "dataScope": "all-records",
                "trace": [f"Selected all {len(rows)} retained records.",
                          "Grouped records by source-reported fuel and counted source-reported Test end categories.",
                          "Reported raw counts only; no condition adjustment or causal comparison was performed."],
            })
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.completed", "complete",
                                 "Completed descriptive outcome counts.", {"groups": groups}))

        elif intent == "burning_rate":
            exact_rows = [row for row in self.records
                          if row.get("quality", {}).get("burningRateMm2PerSec") == "exact"
                          and isinstance(row.get("burningRateMm2PerSec"), (int, float))
                          and not isinstance(row.get("burningRateMm2PerSec"), bool)
                          and math.isfinite(row.get("burningRateMm2PerSec"))]
            fields = ["testNumber", "fuel", "burningRateMm2PerSec", "testEnd"]
            exact_record_ids = [row.get("testNumber") for row in exact_rows]
            if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in exact_record_ids):
                raise ValueError("exact burning-rate selection contains an invalid source record ID")
            if len(set(exact_record_ids)) != len(exact_record_ids):
                raise ValueError("exact burning-rate selection contains duplicate source record IDs")
            events.append(_event(conversation_id, turn_id, len(events) + 1, "data.selected", "complete",
                                 f"Selected {len(exact_rows)} exact finite burning-rate records.",
                                 {"record_count": len(exact_rows), "fields": fields, "unit": "mm²/s",
                                  "record_ids": exact_record_ids}))
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.started", "running",
                                 "Calculating mean and sample standard deviation by fuel."))
            grouped_bullets = []
            burning_rate_summaries = []
            for fuel in sorted({row.get("fuel") for row in exact_rows if row.get("fuel")}):
                fuel_rows = [row for row in self.records if row.get("fuel") == fuel]
                summary = engine.exact_measurement_summary(fuel_rows, "burningRateMm2PerSec")
                structured_summary = {
                    "fuel": fuel,
                    "n": summary["n"],
                    "mean": summary["mean"],
                    "sd": summary["sd"],
                    "approximate": summary["approximate"],
                    "missing": summary["missing"],
                    "invalid": summary["invalid"],
                }
                burning_rate_summaries.append(structured_summary)
                mean = "—" if summary["mean"] is None else f"{summary['mean']:.3f}"
                sd = "—" if summary["sd"] is None else f"{summary['sd']:.3f}"
                grouped_bullets.append(f"{fuel}: mean {mean} ± {sd} mm²/s; n={summary['n']} exact, {summary['approximate']} approximate, {summary['missing']} missing")
            answer.update({
                "title": "Exact-value burning-rate summary.",
                "text": ("The NASA report documents the average burning-rate constant in mm²/s. "
                         "This summary uses exact finite values only, grouped by source-reported fuel; "
                         "it is descriptive and not condition-adjusted."),
                "bullets": grouped_bullets,
                "fields": fields,
                "sampleSize": len(exact_rows),
                "dataScope": "exact-burning-rate",
                "recordIds": exact_record_ids,
                "burningRateSummaries": burning_rate_summaries,
                "trace": [f"Filtered {len(self.records)} source records to {len(exact_rows)} exact, finite burning-rate values.",
                          "Grouped exact values by source-reported fuel; mean = Σx/n and sample SD = sqrt(Σ(x−mean)²/(n−1)).",
                          "Approximate and missing entries were excluded; groups were not adjusted for test conditions."],
            })
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.completed", "complete",
                                 "Completed exact-value burning-rate summaries.", {
                                     "exact_record_count": len(exact_rows),
                                     "record_ids": exact_record_ids,
                                     "groups": burning_rate_summaries,
                                 }))

        elif intent == "data_quality":
            metrics = self.quality.get("measurementQuality", {})
            events.append(_event(conversation_id, turn_id, len(events) + 1, "data.selected", "complete",
                                 "Selected field-level quality metadata for the retained source rows.",
                                 {"record_count": len(self.records), "measurement_fields": len(metrics)}))
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.started", "running",
                                 "Summarizing measurement-quality categories."))
            quality_rows = []
            for key, metric in metrics.items():
                quality_rows.append({
                    "label": f"{metric.get('label', key)} ({metric.get('unit', '')})".strip(),
                    "exact": metric.get("exact", 0),
                    "approximate": metric.get("approximate", 0),
                    "missing": metric.get("missing", 0),
                    "invalid": metric.get("invalid", 0),
                })
            answer.update({
                "title": "Measurement quality in the PSI-69 bundle.",
                "text": ("The quality report counts exact, approximate, missing, and invalid values per measurement. "
                         "Approximate values remain visible and are not included in exact-value summaries; "
                         "missing values are not imputed."),
                "bullets": [
                    f"Records retained: {self.quality.get('acceptedRows', len(self.records))}",
                    f"Rows excluded during ingestion: {self.quality.get('excludedRows', 0)}",
                    f"Source-reported zero-pressure FLEX Test ID(s): {', '.join(map(str, self.quality.get('zeroPressureTestNumbers', []))) or 'none recorded'}",
                    f"Mixture rows outside ±0.01 of a mole-fraction sum of 1: {self.quality.get('compositionCheck', {}).get('outsideOnePercent', 0)}",
                ],
                "fields": ["measurementQuality"],
                "sampleSize": len(self.records),
                "dataScope": "quality-summary",
                "qualityRows": quality_rows,
                "trace": [f"Read the verified field-level quality report for {len(self.records)} retained records.",
                          "Counted exact, approximate, missing, and invalid values separately for each measurement.",
                          "Did not impute missing values; approximate entries remain outside exact-value summaries."],
            })
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.completed", "complete",
                                 "Completed field-level quality counts.", {"measurement_fields": len(quality_rows)}))

        elif intent == "oxygen_sensitivity":
            filters = {"pressureMin": 750, "pressureMax": 770,
                       "coSourceMoleFraction": 0, "heliumMoleFraction": 0}
            fixed_rows = engine.filter_records(self.records, {**filters, "oxygenMoleFraction": 0.21})["rows"]
            broad_rows = engine.filter_records(self.records, {**filters, "oxygenMoleFraction": None})["rows"]
            fixed_record_ids = [row.get("testNumber") for row in fixed_rows]
            record_ids = [row.get("testNumber") for row in broad_rows]
            if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                   for value in fixed_record_ids + record_ids):
                raise ValueError("oxygen cohort selection contains an invalid source record ID")
            if (len(set(fixed_record_ids)) != len(fixed_record_ids)
                    or len(set(record_ids)) != len(record_ids)
                    or not set(fixed_record_ids).issubset(set(record_ids))):
                raise ValueError("oxygen cohort record-ID selections are duplicate or inconsistent")
            events.append(_event(conversation_id, turn_id, len(events) + 1, "data.selected", "complete",
                                 f"Selected {len(broad_rows)} records across the two registered oxygen cohorts.",
                                 {"filters": filters, "fixed_oxygen": 0.21, "fixed_count": len(fixed_rows),
                                  "broad_count": len(broad_rows), "record_count": len(broad_rows),
                                  "fixed_record_ids": fixed_record_ids, "broad_record_ids": record_ids}))
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.started", "running",
                                 "Calculating the two oxygen-cohort summaries and ranked observed outcome-share gaps."))
            sensitivity = engine.oxygen_sensitivity(self.records, filters)
            if sensitivity.get("status") != "ok":
                answer.update({
                    "title": "Oxygen-cohort comparison is unavailable.",
                    "text": sensitivity.get("message") or "The registered comparison could not be completed.",
                    "evidence": answer["evidence"] + ["No comparative ranking produced"],
                    "trace": ["Applied the predefined pressure, source-CO, and helium filters.",
                              "The analysis did not meet its minimum group requirements; no ranking was produced."],
                })
                events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.completed", "unavailable",
                                     "The minimum group requirements were not met."))
                return self._finish(answer, events, turn_id, "abstained", "The oxygen cohort analysis was unavailable.")
            fixed, broad = sensitivity["slices"]
            def compact_oxygen_slice(slice_data: dict[str, Any]) -> dict[str, Any]:
                groups = []
                for group in slice_data["groups"]:
                    groups.append({
                        "fuel": group["fuel"],
                        "n": group["n"],
                        "outcomes": dict(group["outcomes"]),
                    })
                ranked = []
                for item in slice_data["ranked"]:
                    ranked.append({
                        "outcome": item["outcome"],
                        "gapPercentagePoints": item["gapPercentagePoints"],
                        "left": {
                            "fuel": item["left"]["fuel"],
                            "count": item["left"]["count"],
                            "n": item["left"]["n"],
                        },
                        "right": {
                            "fuel": item["right"]["fuel"],
                            "count": item["right"]["count"],
                            "n": item["right"]["n"],
                        },
                    })
                return {"n": slice_data["n"], "groups": groups, "ranked": ranked}

            oxygen_comparison = {
                "filters": dict(filters),
                "fixedOxygen": 0.21,
                "fixedRecordCount": len(fixed_record_ids),
                "broadRecordCount": len(record_ids),
                "fixed": compact_oxygen_slice(fixed),
                "broad": compact_oxygen_slice(broad),
                "fixedOrder": list(sensitivity["fixedOrder"]),
                "broadOrder": list(sensitivity["broadOrder"]),
                "orderChanged": bool(sensitivity["orderChanged"]),
            }

            def render_ranked(slice_data: dict[str, Any]) -> list[str]:
                out = []
                for item in slice_data["ranked"]:
                    out.append(
                        f"{item['outcome']}: {item['gapPercentagePoints']:.1f} pp absolute observed share gap; "
                        f"{item['left']['fuel']} {item['left']['count']}/{item['left']['n']} vs "
                        f"{item['right']['fuel']} {item['right']['count']}/{item['right']['n']}"
                    )
                return out
            fixed_group_label = ", ".join(f"{group['fuel']} n={group['n']}" for group in fixed["groups"])
            broad_group_label = ", ".join(f"{group['fuel']} n={group['n']}" for group in broad["groups"])
            answer.update({
                "title": "Oxygen-cohort sensitivity comparison.",
                "text": ("This registered descriptive comparison holds pressure at 750–770 mmHg, source CO at 0, "
                         "and helium at 0. It compares exact O₂ = 0.21 with all exact oxygen values. "
                         "The cohorts overlap; the broader cohort pools oxygen levels. The percentage-point gaps "
                         "are unadjusted observed outcome-share differences, not oxygen effects or safety rankings."),
                "bullets": [
                    f"Fixed O₂ = 0.21: n={fixed['n']} ({fixed_group_label})",
                    *render_ranked(fixed),
                    f"All exact O₂ values: n={broad['n']} ({broad_group_label})",
                    *render_ranked(broad),
                    f"Order of absolute observed outcome-share gaps changed between cohorts: {'yes' if sensitivity['orderChanged'] else 'no'}",
                ],
                "fields": ["testNumber", "fuel", "ambientPressureMmHg", "oxygenMoleFraction", "coSourceMoleFraction", "heliumMoleFraction", "testEnd"],
                "sampleSize": len(record_ids),
                "dataScope": "selected-records",
                "recordIds": record_ids,
                "fixedRecordIds": fixed_record_ids,
                "oxygenComparison": oxygen_comparison,
                "trace": [
                    "Applied fixed conditions: pressure 750–770 mmHg, source CO = 0, and helium = 0.",
                    f"Compared exact O₂ = 0.21 (n={fixed['n']}) with all exact oxygen values (n={broad['n']}).",
                    "Ranked absolute pairwise outcome-share gaps by outcome using each fuel group's own denominator.",
                    "The cohorts overlap; the broader cohort includes the fixed-O₂ cohort and pools oxygen levels.",
                    "No causal oxygen effect, predictive model, or safety recommendation was calculated.",
                ],
            })
            events.append(_event(conversation_id, turn_id, len(events) + 1, "analysis.completed", "complete",
                                 "Completed the registered oxygen-cohort sensitivity comparison.",
                                 {"fixed_count": fixed["n"], "broad_count": broad["n"],
                                  "fixed_order": sensitivity["fixedOrder"], "broad_order": sensitivity["broadOrder"],
                                  "order_changed": sensitivity["orderChanged"],
                                  "fixed_record_ids": fixed_record_ids,
                                  "broad_record_ids": record_ids,
                                  "oxygen_comparison": oxygen_comparison}))

        answer["evidence"].extend([
            "Deterministic FireLab calculation",
            "Descriptive analysis only",
        ])
        return self._finish(answer, events, turn_id, "completed", "The evidence-backed analysis completed.",
                            {"intent": intent, "analysis_id": answer["analysisId"], "analysis_version": answer["analysisVersion"],
                             "sample_size": answer["sampleSize"], "source_sha256": self.bundle.get("sourceSha256"),
                             "records_sha256": self.bundle.get("recordsSha256"), "quality_sha256": self.bundle.get("qualitySha256")})
