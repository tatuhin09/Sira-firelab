from dataclasses import dataclass
import unittest

from firelab_service.claim_ledger import CLAIM_LEDGER_SCHEMA, validate_claim_ledger
from firelab_service.multi_investigation import _build_psi25_claim_ledger
from firelab_service.evidence_registry import EvidenceRegistryError, InvestigationEvidence
from firelab_service.scientific_planner import PSI25_ID


HASHES = {
    "psi25-source-csv": "1" * 64,
    "psi25-canonical-records": "2" * 64,
    "psi25-paired-analysis": "3" * 64,
    "psi25-findings": "4" * 64,
    "psi25-synthesis": "5" * 64,
}
ARTIFACT_HASHES = {
    "canonical_records": HASHES["psi25-canonical-records"],
    "quality_report": "6" * 64,
    "paired_analysis": HASHES["psi25-paired-analysis"],
    "findings": HASHES["psi25-findings"],
    "synthesis": HASHES["psi25-synthesis"],
}
RECORD_KEYS = tuple(f"bass-record-{i:03d}" for i in range(1, 130))
METRICS = ("o2", "co2", "co")


@dataclass(frozen=True)
class FakePlan:
    operation_id: str
    metric: str
    data_scope: str
    execution_allowed: bool = True
    resolved_investigation: str = PSI25_ID


def make_cards(metric):
    cards = []
    cursor = 0
    for index in range(18):
        count = 7 if index < 17 else 10
        keys = RECORD_KEYS[cursor:cursor + count]
        cursor += count
        rankable = index < 17
        flags = ["sample_id_reuse_possible_dependence"] if index == 0 else ([] if rankable else ["not_rankable_no_eligible_pairs"])
        card = {
            "insight_id": f"PSI25-{metric.upper()}-{index + 1:03d}",
            "metric": metric,
            "label": metric.upper(),
            "unit": "% by volume" if metric in {"o2", "co2"} else "ppm",
            "cohort": {"pi": f"PI-{index + 1}", "material_class": "PMMA", "flow_restrictor_code": str(index % 3)},
            "rank": index + 1 if rankable else None,
            "eligible_pairs": len(keys) if rankable else 0,
            "excluded_pairs": 0 if rankable else len(keys),
            "records_in_cohort": len(keys),
            "records_marked_with_reused_sample_id": 1 if index == 0 else 0,
            "flags": flags,
            "statistics": {"n": len(keys), "mean": "0.01", "median": "0.00", "minimum": "-0.10", "maximum": "0.10"} if rankable else None,
            "direction_counts": {"positive": 3, "negative": 2, "zero": 2} if rankable else {},
            "observation": f"Among {len(keys) if rankable else 0} eligible records in PI-{index + 1}, the descriptive {metric.upper()} finding was recorded." if rankable else f"PI-{index + 1}: no eligible exact paired measurements were available; no mean or direction is assigned.",
            "distribution": "Mixed within-cohort record changes; no causal interpretation." if rankable else "No eligible paired observations; excluded source records remain inspectable.",
            "interpretation_status": "descriptive_only" if rankable else "not_rankable",
            "evidence_dimensions": {"measurement_caveat": "Source eligibility rules applied; no imputation."},
            "mission_research_relevance": "Follow-up matched research is required; this does not qualify material safety.",
            "supporting_record_evidence": ([{"record_key": key} for key in keys] if rankable else []),
            "excluded_record_evidence": ([] if rankable else [{"record_key": key} for key in keys]),
        }
        cards.append(card)
    assert cursor == 129
    return cards


def make_entry():
    metrics_payload = {}
    paired_metrics = {}
    findings_metrics = {}
    for metric in METRICS:
        cards = make_cards(metric)
        pair_counts = {"records": 129, "eligible_pairs": 119, "excluded_pairs": 10}
        metrics_payload[metric] = {
            "label": metric.upper(),
            "unit": cards[0]["unit"],
            "pair_counts": pair_counts,
            "rankable_cohort_count": 17,
            "not_rankable_cohort_count": 1,
            "insight_cards": cards,
            "interpretation_limit": "Descriptive within-metric findings only; no causal or safety conclusion.",
        }
        paired_metrics[metric] = {"pair_counts": pair_counts}
        findings_metrics[metric] = {"rankable_cohort_count": 17, "not_rankable_cohort_count": 1}
    payload = {
        "artifact_sha256": ARTIFACT_HASHES,
        "record_keys": RECORD_KEYS,
        "paired": {"metrics": paired_metrics},
        "findings": {"metrics": findings_metrics},
        "synthesis": {
            "metrics": metrics_payload,
            "scientific_use_constraints": [
                "No cross-metric ranking or pooling.",
                "No causal or inferential claim is supported.",
                "No independent physical-sample inference is made.",
                "No operational fire-safety recommendation is produced.",
                "Mission transferability is not established.",
            ],
        },
    }
    return InvestigationEvidence(
        investigation_id=PSI25_ID,
        title="BASS-II",
        source="NASA PSI-25",
        source_url="https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
        version="Study Version 4",
        record_count=129,
        source_sha256=HASHES["psi25-source-csv"],
        records_sha256=HASHES["psi25-canonical-records"],
        quality_sha256=ARTIFACT_HASHES["quality_report"],
        payload=payload,
    )


class FireLabM43C2Psi25ClaimIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.entry = make_entry()

    def answer_for(self, plan):
        return {
            "status": "completed",
            "analysisId": plan.operation_id,
            "dataScope": plan.data_scope,
            "metric": plan.metric,
            "scientificPlan": {
                "resolvedInvestigation": PSI25_ID,
                "operationId": plan.operation_id,
            },
            "claimReferences": [{"claim_id": "legacy-top-five"}],
            "recordRefs": ["legacy-ref-1", "legacy-ref-2"],
            "trace": [],
        }

    def build_for(self, operation, metric="", scope="all-records"):
        plan = FakePlan(operation, metric, scope)
        answer = self.answer_for(plan)
        ledger = _build_psi25_claim_ledger(self.entry, plan, answer)
        return plan, answer, ledger

    def test_o2_ranking_builds_all_eighteen_claims_and_full_129_record_lineage(self):
        _, _, ledger = self.build_for("psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        self.assertEqual(ledger["schema"], CLAIM_LEDGER_SCHEMA)
        self.assertEqual(len(ledger["claims"]), 18)
        self.assertEqual({claim["metric"] for claim in ledger["claims"]}, {"o2"})
        all_keys = []
        for claim in ledger["claims"]:
            lineage = claim["recordLineage"]
            all_keys.extend(lineage["supportingRecordKeys"] + lineage["excludedRecordKeys"])
            self.assertTrue(lineage["complete"])
        self.assertEqual(len(all_keys), 129)
        self.assertEqual(set(all_keys), set(RECORD_KEYS))
        self.assertEqual(len(set(all_keys)), 129)

    def test_all_three_metric_operations_keep_claims_metric_isolated(self):
        for metric in METRICS:
            for suffix in ("insights", "ranking"):
                with self.subTest(metric=metric, suffix=suffix):
                    _, _, ledger = self.build_for(f"psi25.bass_ii.v4.{metric}.{suffix}", metric, "cohort-evidence")
                    self.assertEqual(len(ledger["claims"]), 18)
                    self.assertEqual({claim["metric"] for claim in ledger["claims"]}, {metric})

    def test_non_rankable_cohort_is_recorded_as_descriptive_with_limitations(self):
        _, _, ledger = self.build_for("psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        non_rankable = [claim for claim in ledger["claims"] if claim["result"]["eligiblePairs"] == 0]
        self.assertEqual(len(non_rankable), 1)
        self.assertEqual(non_rankable[0]["interpretationStatus"], "descriptive_with_limitations")
        self.assertIsNone(non_rankable[0]["result"]["rank"])
        self.assertEqual(non_rankable[0]["result"]["statistics"], {})

    def test_snapshot_builds_one_record_count_and_three_separate_metric_summaries(self):
        _, _, ledger = self.build_for("psi25.bass_ii.v4.snapshot", "", "all-records")
        self.assertEqual(len(ledger["claims"]), 4)
        self.assertEqual(ledger["claims"][0]["claimType"], "source_table_count")
        summaries = ledger["claims"][1:]
        self.assertEqual({claim["metric"] for claim in summaries}, set(METRICS))
        for claim in summaries:
            self.assertEqual(claim["result"]["recordCount"], 129)
            self.assertEqual(claim["result"]["eligiblePairs"] + claim["result"]["excludedPairs"], 129)

    def test_research_question_operations_do_not_emit_scientific_claim_ledger(self):
        for operation, metric in (
            ("psi25.bass_ii.v4.research_questions", ""),
            ("psi25.bass_ii.v4.o2.research_questions", "o2"),
            ("psi25.bass_ii.v4.co2.research_questions", "co2"),
            ("psi25.bass_ii.v4.co.research_questions", "co"),
        ):
            with self.subTest(operation=operation):
                _, _, ledger = self.build_for(operation, metric, "research-questions")
                self.assertIsNone(ledger)

    def test_answer_legacy_claim_references_and_record_refs_are_not_mutated(self):
        _, answer, _ = self.build_for("psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        self.assertEqual(answer["claimReferences"], [{"claim_id": "legacy-top-five"}])
        self.assertEqual(answer["recordRefs"], ["legacy-ref-1", "legacy-ref-2"])

    def test_ledger_evidence_hashes_match_registry_hashes(self):
        _, _, ledger = self.build_for("psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        refs = {item["referenceId"]: item["sha256"] for item in ledger["claims"][0]["evidenceReferences"]}
        self.assertEqual(refs, HASHES)

    def test_wrong_answer_metric_or_scope_fails_closed(self):
        plan = FakePlan("psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        for changes in ({"metric": "co2"}, {"dataScope": "all-records"}, {"analysisId": "psi25.bass_ii.v4.co2.ranking"}):
            with self.subTest(changes=changes):
                answer = self.answer_for(plan)
                answer.update(changes)
                with self.assertRaises((EvidenceRegistryError, ValueError)):
                    _build_psi25_claim_ledger(self.entry, plan, answer)

    def test_plan_must_be_executable_and_context_bound(self):
        plan = FakePlan("psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence", execution_allowed=False)
        with self.assertRaises(EvidenceRegistryError):
            _build_psi25_claim_ledger(self.entry, plan, self.answer_for(plan))

    def test_registry_metric_cards_must_cover_canonical_records_exactly_once(self):
        broken = make_entry()
        broken.payload["synthesis"]["metrics"]["o2"]["insight_cards"][1]["supporting_record_evidence"].append(
            broken.payload["synthesis"]["metrics"]["o2"]["insight_cards"][0]["supporting_record_evidence"][0]
        )
        plan = FakePlan("psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        with self.assertRaises((EvidenceRegistryError, ValueError)):
            _build_psi25_claim_ledger(broken, plan, self.answer_for(plan))

    def test_output_passes_the_c1_contract_and_is_deterministic(self):
        plan = FakePlan("psi25.bass_ii.v4.co.ranking", "co", "cohort-evidence")
        answer = self.answer_for(plan)
        first = _build_psi25_claim_ledger(self.entry, plan, answer)
        second = _build_psi25_claim_ledger(self.entry, plan, answer)
        self.assertEqual(first, second)
        self.assertEqual(first["ledgerStatus"], "verified_provenance")
        self.assertTrue(all(claim["qualityDimensions"]["scientificTruth"] == "not_established_by_integrity_checks" for claim in first["claims"]))


if __name__ == "__main__":
    unittest.main()
