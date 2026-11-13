from dataclasses import dataclass
from types import MappingProxyType
import unittest

from firelab_service.claim_ledger import CLAIM_LEDGER_SCHEMA, OPERATION_SPECS, ClaimLedgerError
from firelab_service.evidence_registry import EvidenceRegistry, EvidenceRegistryError, InvestigationEvidence, load_evidence_registry
from firelab_service.multi_investigation import MultiInvestigationEvidenceAssistant, _build_psi69_claim_ledger
from firelab_service.scientific_planner import PSI69_ID, build_scientific_plan, validate_scientific_plan_for_dispatch
from pathlib import Path
from copy import deepcopy

HASHES = {
    "psi69.source_manifest": "a" * 64,
    "psi69.records": "b" * 64,
    "psi69.quality_report": "c" * 64,
}
ALL_IDS = tuple(range(1, 275))
OUTCOMES = ("Extinction", "Disruption", "Completion")


@dataclass(frozen=True)
class FakePlan:
    operation_id: str
    data_scope: str
    metric: str = ""
    execution_allowed: bool = True
    resolved_investigation: str = PSI69_ID


def _fuel_groups():
    return [
        {"fuel": "Methanol", "n": 157, "outcomes": {"Extinction": 126, "Disruption": 23, "Completion": 8}},
        {"fuel": "Heptane", "n": 117, "outcomes": {"Extinction": 60, "Disruption": 38, "Completion": 19}},
    ]


def _quality_rows():
    labels = [
        "Ambient pressure (mmHg)", "O2 fraction", "N2 fraction", "CO/CO2 source field",
        "Helium fraction", "Initial droplet diameter", "Visible-flame extinction diameter",
        "Average burning-rate constant", "Burn time",
    ]
    return [{"label": label, "exact": 258, "approximate": 2, "missing": 14, "invalid": 0} for label in labels]


def _compact_slice(n, methanol_n, heptane_n):
    return {
        "n": n,
        "groups": [
            {"fuel": "Methanol", "n": methanol_n, "outcomes": {"Extinction": methanol_n - 4, "Disruption": 3, "Completion": 1}},
            {"fuel": "Heptane", "n": heptane_n, "outcomes": {"Extinction": heptane_n - 4, "Disruption": 3, "Completion": 1}},
        ],
        "ranked": [
            {"outcome": "Extinction", "gapPercentagePoints": 20.0, "left": {"fuel": "Methanol", "count": methanol_n - 4, "n": methanol_n}, "right": {"fuel": "Heptane", "count": heptane_n - 4, "n": heptane_n}},
            {"outcome": "Disruption", "gapPercentagePoints": 5.0, "left": {"fuel": "Methanol", "count": 3, "n": methanol_n}, "right": {"fuel": "Heptane", "count": 3, "n": heptane_n}},
            {"outcome": "Completion", "gapPercentagePoints": 2.0, "left": {"fuel": "Methanol", "count": 1, "n": methanol_n}, "right": {"fuel": "Heptane", "count": 1, "n": heptane_n}},
        ],
    }


def make_entry():
    records = []
    for record_id in ALL_IDS:
        fuel = "Methanol" if record_id <= 157 else "Heptane"
        exact = record_id <= 258
        records.append({
            "testNumber": record_id,
            "fuel": fuel,
            "quality": {"burningRateMm2PerSec": "exact" if exact else "missing"},
            "burningRateMm2PerSec": 0.5 + (record_id / 10000.0) if exact else None,
        })
    bundle = {
        "manifest": {"sourceVersion": "PSI-69 Version 5"},
        "records": records,
        "sourceSha256": HASHES["psi69.source_manifest"],
        "recordsSha256": HASHES["psi69.records"],
        "qualitySha256": HASHES["psi69.quality_report"],
    }
    return InvestigationEvidence(
        investigation_id=PSI69_ID,
        title="FLEX",
        source="NASA PSI-69",
        source_url="https://psi.nasa.gov/",
        version="PSI-69 Version 5",
        record_count=274,
        source_sha256=HASHES["psi69.source_manifest"],
        records_sha256=HASHES["psi69.records"],
        quality_sha256=HASHES["psi69.quality_report"],
        payload=MappingProxyType({"bundle": bundle}),
    )


def make_answer(operation_id):
    spec = OPERATION_SPECS[operation_id]
    answer = {
        "status": "completed",
        "analysisId": operation_id,
        "dataScope": spec.data_scope,
        "sampleSize": 274,
        "investigationId": PSI69_ID,
        "scientificPlan": {
            "operationId": operation_id,
            "resolvedInvestigation": PSI69_ID,
            "dataScope": spec.data_scope,
            "metric": "",
        },
        "sourceHash": HASHES["psi69.source_manifest"],
        "recordsHash": HASHES["psi69.records"],
        "qualityHash": HASHES["psi69.quality_report"],
        "recordIds": [],
        "trace": [],
    }
    selected_payload = {"record_count": 274}
    if operation_id == "flex.dataset.snapshot":
        payload = {"record_count": 274, "fuel_groups": _fuel_groups(),
                   "outcomes": {"Extinction": 186, "Disruption": 61, "Completion": 27}}
    elif operation_id == "flex.outcomes.by_fuel":
        payload = {"groups": _fuel_groups()}
    elif operation_id == "flex.burning_rate.exact_by_fuel":
        selected = list(range(1, 259))
        summaries = [
            {"fuel": "Heptane", "n": 101, "mean": 0.545, "sd": 0.161, "approximate": 0, "missing": 16, "invalid": 0},
            {"fuel": "Methanol", "n": 157, "mean": 0.610, "sd": 0.180, "approximate": 0, "missing": 0, "invalid": 0},
        ]
        answer.update({"sampleSize": 258, "dataScope": "exact-burning-rate", "recordIds": selected,
                       "burningRateSummaries": summaries})
        selected_payload = {"record_count": 258, "record_ids": selected}
        payload = {"exact_record_count": 258, "record_ids": selected, "groups": summaries}
    elif operation_id == "flex.measurement_quality":
        rows = _quality_rows()
        answer.update({"sampleSize": 274, "dataScope": "quality-summary", "qualityRows": rows})
        selected_payload = {"record_count": 274, "measurement_fields": len(rows)}
        payload = {"measurement_fields": len(rows)}
    elif operation_id == "flex.oxygen_cohort_sensitivity":
        broad_ids = list(range(1, 65))
        fixed_ids = list(range(1, 26))
        comparison = {
            "filters": {"pressureMin": 750, "pressureMax": 770, "coSourceMoleFraction": 0, "heliumMoleFraction": 0},
            "fixedOxygen": 0.21,
            "fixedRecordCount": 25,
            "broadRecordCount": 64,
            "fixed": _compact_slice(25, 15, 10),
            "broad": _compact_slice(64, 35, 29),
            "fixedOrder": ["Extinction", "Disruption", "Completion"],
            "broadOrder": ["Completion", "Extinction", "Disruption"],
            "orderChanged": True,
        }
        answer.update({"sampleSize": 64, "dataScope": "selected-records", "recordIds": broad_ids,
                       "fixedRecordIds": fixed_ids, "oxygenComparison": comparison})
        selected_payload = {"record_count": 64, "fixed_count": 25, "broad_count": 64,
                            "fixed_record_ids": fixed_ids, "broad_record_ids": broad_ids}
        # Match the existing assistant analysis.completed event contract.
        payload = {"fixed_count": 25, "broad_count": 64,
                   "oxygen_comparison": comparison}
    else:
        raise AssertionError(operation_id)

    answer["events"] = [
        {"type": "data.selected", "status": "complete", "payload": selected_payload},
        {"type": "analysis.completed", "status": "complete", "payload": payload},
        {"type": "answer.completed", "status": "completed", "payload": {
            "analysis_id": operation_id, "sample_size": answer["sampleSize"],
            "source_sha256": HASHES["psi69.source_manifest"],
            "records_sha256": HASHES["psi69.records"],
            "quality_sha256": HASHES["psi69.quality_report"],
        }},
    ]
    return answer


class FireLabM43C3Psi69ClaimIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.entry = make_entry()

    def build(self, operation_id):
        spec = OPERATION_SPECS[operation_id]
        plan = FakePlan(operation_id, spec.data_scope)
        answer = make_answer(operation_id)
        ledger = _build_psi69_claim_ledger(self.entry, plan, answer)
        return plan, answer, ledger

    def test_all_five_registered_psi69_operations_build_one_typed_claim(self):
        expected = {
            "flex.dataset.snapshot": "source_table_count",
            "flex.outcomes.by_fuel": "source_table_count",
            "flex.burning_rate.exact_by_fuel": "descriptive_summary",
            "flex.measurement_quality": "measurement_quality_observation",
            "flex.oxygen_cohort_sensitivity": "observed_cohort_comparison",
        }
        for operation, claim_type in expected.items():
            with self.subTest(operation=operation):
                _, _, ledger = self.build(operation)
                self.assertEqual(ledger["schema"], CLAIM_LEDGER_SCHEMA)
                self.assertEqual(ledger["operationId"], operation)
                self.assertEqual(len(ledger["claims"]), 1)
                self.assertEqual(ledger["claims"][0]["claimType"], claim_type)

    def test_snapshot_has_aggregate_source_count_and_reconciled_fuel_outcomes(self):
        _, _, ledger = self.build("flex.dataset.snapshot")
        claim = ledger["claims"][0]
        self.assertEqual(claim["result"]["recordCount"], 274)
        self.assertEqual(claim["result"]["fuelCounts"], {"Methanol": 157, "Heptane": 117})
        self.assertEqual(claim["result"]["outcomeCounts"], {"Extinction": 186, "Disruption": 61, "Completion": 27})
        self.assertEqual(claim["recordLineage"]["supportingCount"], 274)
        self.assertEqual(claim["recordLineage"]["mode"], "registered_selection_scope")

    def test_outcomes_by_fuel_retains_counts_without_effect_or_share_claims(self):
        _, _, ledger = self.build("flex.outcomes.by_fuel")
        claim = ledger["claims"][0]
        self.assertEqual(claim["claimType"], "source_table_count")
        self.assertEqual(len(claim["result"]["fuelOutcomeCounts"]), 2)
        self.assertNotIn("effect", str(claim["result"]).casefold())
        self.assertIn("do not establish a fuel effect", " ".join(claim["limitations"]))

    def test_burning_rate_has_structured_statistics_and_258_16_lineage(self):
        _, _, ledger = self.build("flex.burning_rate.exact_by_fuel")
        claim = ledger["claims"][0]
        lineage = claim["recordLineage"]
        self.assertEqual(claim["result"]["exactRecordCount"], 258)
        self.assertEqual(len(claim["result"]["groups"]), 2)
        self.assertEqual(lineage["supportingCount"], 258)
        self.assertEqual(lineage["excludedCount"], 16)
        self.assertEqual(len(set(lineage["supportingRecordIds"] + lineage["excludedRecordIds"])), 274)

    def test_measurement_quality_carries_nine_reconciled_rows(self):
        _, _, ledger = self.build("flex.measurement_quality")
        claim = ledger["claims"][0]
        self.assertEqual(len(claim["result"]["measurementFields"]), 9)
        self.assertEqual(claim["qualityDimensions"]["statisticalScope"], "quality_count_only")
        self.assertEqual(claim["recordLineage"]["supportingCount"], 274)

    def test_oxygen_sensitivity_carries_64_selected_and_210_excluded_ids(self):
        _, _, ledger = self.build("flex.oxygen_cohort_sensitivity")
        claim = ledger["claims"][0]
        lineage = claim["recordLineage"]
        self.assertEqual(lineage["supportingCount"], 64)
        self.assertEqual(lineage["excludedCount"], 210)
        self.assertEqual(len(set(lineage["supportingRecordIds"] + lineage["excludedRecordIds"])), 274)
        self.assertEqual(claim["result"]["fixedRecordCount"], 25)
        self.assertTrue(set(range(1, 26)).issubset(set(lineage["supportingRecordIds"])))
        self.assertIn("overlap", " ".join(claim["limitations"]).casefold())

    def test_all_three_evidence_hashes_are_bound_to_every_operation(self):
        for operation in tuple(OPERATION_SPECS)[:5]:
            with self.subTest(operation=operation):
                _, _, ledger = self.build(operation)
                refs = {ref["referenceId"]: ref["sha256"] for ref in ledger["claims"][0]["evidenceReferences"]}
                self.assertEqual(refs, HASHES)

    def test_ledgers_are_deterministic_and_do_not_mutate_answer(self):
        operation = "flex.burning_rate.exact_by_fuel"
        plan = FakePlan(operation, "exact-burning-rate")
        answer = make_answer(operation)
        before = deepcopy(answer)
        first = _build_psi69_claim_ledger(self.entry, plan, answer)
        second = _build_psi69_claim_ledger(self.entry, plan, answer)
        self.assertEqual(first, second)
        self.assertEqual(answer, before)

    def test_abstained_answers_do_not_receive_a_ledger(self):
        plan = FakePlan("flex.dataset.snapshot", "all-records")
        answer = make_answer("flex.dataset.snapshot")
        answer["status"] = "abstained"
        self.assertIsNone(_build_psi69_claim_ledger(self.entry, plan, answer))

    def test_existing_ledger_is_never_replaced(self):
        plan = FakePlan("flex.dataset.snapshot", "all-records")
        answer = make_answer("flex.dataset.snapshot")
        answer["claimLedger"] = {"sentinel": True}
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, answer)

    def test_plan_operation_scope_and_investigation_are_bound(self):
        answer = make_answer("flex.dataset.snapshot")
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, FakePlan("flex.outcomes.by_fuel", "all-records"), answer)
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, FakePlan("flex.dataset.snapshot", "selected-records"), answer)
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, FakePlan("flex.dataset.snapshot", "all-records", resolved_investigation="psi25-bass-ii-v4"), answer)

    def test_answer_plan_and_analysis_completion_hashes_are_bound(self):
        plan, answer, _ = self.build("flex.dataset.snapshot")
        bad = deepcopy(answer)
        bad["analysisId"] = "flex.outcomes.by_fuel"
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, bad)
        bad = deepcopy(answer)
        bad["sourceHash"] = "0" * 64
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, bad)
        bad = deepcopy(answer)
        bad["events"][-1]["payload"]["records_sha256"] = "0" * 64
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, bad)

    def test_aggregate_event_counts_must_reconcile(self):
        plan = FakePlan("flex.dataset.snapshot", "all-records")
        answer = make_answer("flex.dataset.snapshot")
        answer["events"][1]["payload"]["record_count"] = 273
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, answer)

    def test_burning_rate_selection_ids_must_match_execution_and_exact_source_rows(self):
        plan = FakePlan("flex.burning_rate.exact_by_fuel", "exact-burning-rate")
        answer = make_answer("flex.burning_rate.exact_by_fuel")
        answer["recordIds"][0] = 274
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, answer)
        answer = make_answer("flex.burning_rate.exact_by_fuel")
        answer["events"][0]["payload"]["record_ids"] = [2] + list(range(2, 259))
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, answer)

    def test_oxygen_selected_ids_and_nested_fixed_cohort_must_match(self):
        plan = FakePlan("flex.oxygen_cohort_sensitivity", "selected-records")
        answer = make_answer("flex.oxygen_cohort_sensitivity")
        answer["fixedRecordIds"] = [274]
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, answer)
        answer = make_answer("flex.oxygen_cohort_sensitivity")
        answer["events"][0]["payload"]["broad_record_ids"] = [2] + list(range(2, 65))
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, answer)

    def test_quality_field_counts_must_sum_to_verified_record_count(self):
        plan = FakePlan("flex.measurement_quality", "quality-summary")
        answer = make_answer("flex.measurement_quality")
        answer["qualityRows"][0]["missing"] = 13
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(self.entry, plan, answer)

    def test_source_record_ids_must_be_unique_and_positive(self):
        plan = FakePlan("flex.dataset.snapshot", "all-records")
        bad_entry = make_entry()
        bad_bundle = dict(bad_entry.payload["bundle"])
        bad_records = list(bad_bundle["records"])
        bad_records[-1] = dict(bad_records[-1], testNumber=1)
        bad_bundle["records"] = bad_records
        bad_entry = InvestigationEvidence(
            investigation_id=bad_entry.investigation_id, title=bad_entry.title, source=bad_entry.source,
            source_url=bad_entry.source_url, version=bad_entry.version, record_count=bad_entry.record_count,
            source_sha256=bad_entry.source_sha256, records_sha256=bad_entry.records_sha256,
            quality_sha256=bad_entry.quality_sha256, payload=MappingProxyType({"bundle": bad_bundle}),
        )
        with self.assertRaises(EvidenceRegistryError):
            _build_psi69_claim_ledger(bad_entry, plan, make_answer("flex.dataset.snapshot"))

    def test_quality_and_operation_scope_are_exact(self):
        for operation in OPERATION_SPECS:
            with self.subTest(operation=operation):
                if not operation.startswith("flex."):
                    continue
                ledger = self.build(operation)[2]
                claim = ledger["claims"][0]
                self.assertEqual(claim["qualityDimensions"]["scientificTruth"], "not_established_by_integrity_checks")
                self.assertEqual(claim["qualityDimensions"]["independentReplication"], "not_performed")
                self.assertEqual(claim["qualityDimensions"]["missionTransferability"], "not_established")
                self.assertEqual(ledger["metric"], "")


class FireLabM43C3VerifiedRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.registry = load_evidence_registry(cls.root)
        cls.assistant = MultiInvestigationEvidenceAssistant(cls.registry)

    def ask(self, question, conversation_id):
        return self.assistant.ask(question, conversation_id=conversation_id, investigation_id=PSI69_ID)

    def test_live_dataset_snapshot_has_claim_ledger(self):
        answer = self.ask("Summarize the FLEX dataset", "m43c3-live-snapshot")
        ledger = answer["claimLedger"]
        self.assertEqual(ledger["schema"], CLAIM_LEDGER_SCHEMA)
        self.assertEqual(ledger["operationId"], "flex.dataset.snapshot")
        self.assertEqual(len(ledger["claims"]), 1)
        self.assertEqual(ledger["claims"][0]["result"]["recordCount"], 274)

    def test_live_outcomes_by_fuel_has_claim_ledger(self):
        answer = self.ask("Show outcome counts by fuel", "m43c3-live-outcomes")
        claim = answer["claimLedger"]["claims"][0]
        self.assertEqual(answer["analysisId"], "flex.outcomes.by_fuel")
        self.assertEqual(claim["claimType"], "source_table_count")
        self.assertEqual(len(claim["result"]["fuelOutcomeCounts"]), 2)

    def test_live_burning_rate_has_structured_summaries_and_complete_lineage(self):
        answer = self.ask("Summarize the burning rate", "m43c3-live-burning")
        claim = answer["claimLedger"]["claims"][0]
        self.assertEqual(answer["analysisId"], "flex.burning_rate.exact_by_fuel")
        self.assertEqual(len(answer["burningRateSummaries"]), 2)
        self.assertEqual(len(answer["recordIds"]), 258)
        self.assertEqual(claim["recordLineage"]["supportingCount"], 258)
        self.assertEqual(claim["recordLineage"]["excludedCount"], 16)

    def test_live_measurement_quality_has_all_nine_fields(self):
        answer = self.ask("What should I know about data quality?", "m43c3-live-quality")
        claim = answer["claimLedger"]["claims"][0]
        self.assertEqual(answer["analysisId"], "flex.measurement_quality")
        self.assertEqual(len(answer["qualityRows"]), 9)
        self.assertEqual(len(claim["result"]["measurementFields"]), 9)

    def test_live_oxygen_sensitivity_has_complete_selected_lineage(self):
        answer = self.ask("Compare oxygen conditions", "m43c3-live-oxygen")
        claim = answer["claimLedger"]["claims"][0]
        self.assertEqual(answer["analysisId"], "flex.oxygen_cohort_sensitivity")
        self.assertEqual(len(answer["recordIds"]), 64)
        self.assertEqual(len(answer["fixedRecordIds"]), 25)
        self.assertTrue(set(answer["fixedRecordIds"]).issubset(set(answer["recordIds"])))
        self.assertEqual(claim["recordLineage"]["supportingCount"], 64)
        self.assertEqual(claim["recordLineage"]["excludedCount"], 210)


if __name__ == "__main__":
    unittest.main()
