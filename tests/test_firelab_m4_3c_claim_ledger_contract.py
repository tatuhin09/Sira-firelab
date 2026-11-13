from copy import deepcopy
import unittest

from firelab_service.claim_ledger import (
    CLAIM_LEDGER_SCHEMA,
    CLAIM_TYPES,
    OPERATION_SPECS,
    ClaimLedgerContext,
    ClaimLedgerError,
    build_claim_ledger,
    validate_claim_ledger,
)


HASHES_25 = {
    "psi25-source-csv": "1" * 64,
    "psi25-canonical-records": "2" * 64,
    "psi25-paired-analysis": "3" * 64,
    "psi25-findings": "4" * 64,
    "psi25-synthesis": "5" * 64,
}
HASHES_69 = {
    "psi69.source_manifest": "a" * 64,
    "psi69.records": "b" * 64,
    "psi69.quality_report": "c" * 64,
}


def psi25_context(**overrides):
    values = dict(
        investigation_id="psi25-bass-ii-v4",
        source_release="PSI-25 BASS-II Study Version 4",
        operation_id="psi25.bass_ii.v4.o2.ranking",
        metric="o2",
        data_scope="cohort-evidence",
        evidence_hashes=HASHES_25,
        allowed_record_keys=frozenset(f"rk-{index:03d}" for index in range(1, 130)),
        expected_claim_ids=frozenset({"insight-o2-001"}),
        expected_record_lineage={"insight-o2-001": {
            "supportingRecordKeys": ("rk-001", "rk-002"),
            "excludedRecordKeys": ("rk-003",),
        }},
    )
    values.update(overrides)
    return ClaimLedgerContext(**values)


def psi69_context(**overrides):
    values = dict(
        investigation_id="psi69-flex-v5",
        source_release="PSI-69 Version 5",
        operation_id="flex.dataset.snapshot",
        metric="",
        data_scope="all-records",
        evidence_hashes=HASHES_69,
        allowed_record_ids=frozenset(range(1, 275)),
    )
    values.update(overrides)
    return ClaimLedgerContext(**values)


def quality(lineage="complete", stat_scope="descriptive_only", sample="not_established"):
    return {
        "sourceIntegrity": "verified",
        "artifactIntegrity": "verified",
        "recordLineageIntegrity": lineage,
        "methodReproducibility": "precomputed_deterministic_artifact",
        "statisticalScope": stat_scope,
        "measurementValidity": ["sensor_calibration_limitation"],
        "sampleIndependence": sample,
        "independentReplication": "not_performed",
        "missionTransferability": "not_established",
        "scientificTruth": "not_established_by_integrity_checks",
    }


def psi25_claim():
    return {
        "claimId": "insight-o2-001",
        "claimType": "descriptive_cohort_finding",
        "statement": "The cohort mean paired O2 change was 0.01 % by volume.",
        "result": {
            "rank": 1,
            "eligiblePairs": 2,
            "excludedPairs": 1,
            "mean": "0.01",
            "median": "0",
            "minimum": "-0.10",
            "maximum": "0.10",
        },
        "metric": "o2",
        "unit": "% by volume",
        "cohort": {"pi": "T'ien", "materialClass": "SIBAL fabric", "flowRestrictorCode": "2"},
        "evidenceReferences": [
            {"referenceId": key, "sha256": digest}
            for key, digest in HASHES_25.items()
        ],
        "recordLineage": {
            "mode": "explicit_canonical_record_keys",
            "supportingRecordKeys": ["rk-001", "rk-002"],
            "excludedRecordKeys": ["rk-003"],
            "supportingCount": 2,
            "excludedCount": 1,
            "complete": True,
        },
        "qualityDimensions": quality("complete", "descriptive_only", "potential_dependence_flagged"),
        "limitations": [
            "Descriptive within-metric result only; no causal inference.",
            "Sample reuse may create dependence between experiment records.",
        ],
        "interpretationStatus": "descriptive_only",
    }


def psi69_claim():
    return {
        "claimId": "flex.dataset.snapshot.total-records",
        "claimType": "source_table_count",
        "statement": "The verified PSI-69 FLEX bundle contains 274 retained records.",
        "result": {
            "recordCount": 274,
            "fuelCounts": {"Methanol": 157, "Heptane": 117},
            "outcomeCounts": {"Extinction": 186, "Disruption": 61, "Completion": 27},
        },
        "metric": "",
        "unit": "records",
        "cohort": None,
        "evidenceReferences": [
            {"referenceId": "psi69.source_manifest", "sha256": HASHES_69["psi69.source_manifest"]},
            {"referenceId": "psi69.records", "sha256": HASHES_69["psi69.records"]},
        ],
        "recordLineage": {
            "mode": "registered_selection_scope",
            "supportingRecordIds": [],
            "excludedRecordIds": [],
            "supportingCount": 274,
            "excludedCount": 0,
            "selectionRule": "All retained records from the verified PSI-69 FLEX Version 5 bundle.",
            "complete": True,
        },
        "qualityDimensions": quality("aggregate_scope", "source_count_only", "not_applicable"),
        "limitations": ["Source-table counts only; no adjusted effect or safety conclusion."],
        "interpretationStatus": "source_reported",
    }


class FireLabM43CClaimLedgerContractTests(unittest.TestCase):
    def test_schema_and_version_are_exact(self):
        ledger = build_claim_ledger(psi25_context(), [psi25_claim()])
        self.assertEqual(ledger["schema"], CLAIM_LEDGER_SCHEMA)
        self.assertEqual(ledger["ledgerVersion"], 1)

    def test_all_sixteen_exact_operations_are_registered(self):
        self.assertEqual(len(OPERATION_SPECS), 16)
        self.assertIn("psi25.bass_ii.v4.co.research_questions", OPERATION_SPECS)
        self.assertNotIn("psi25.bass_ii.v4.co.*", OPERATION_SPECS)

    def test_psi25_synthetic_cohort_ledger_is_accepted(self):
        ledger = build_claim_ledger(psi25_context(), [psi25_claim()])
        self.assertEqual(ledger["claims"][0]["recordLineage"]["supportingCount"], 2)
        self.assertEqual(ledger["claims"][0]["qualityDimensions"]["scientificTruth"], "not_established_by_integrity_checks")

    def test_psi69_synthetic_aggregate_ledger_is_accepted(self):
        ledger = build_claim_ledger(psi69_context(), [psi69_claim()])
        self.assertEqual(ledger["claims"][0]["recordLineage"]["supportingCount"], 274)
        self.assertEqual(ledger["claims"][0]["recordLineage"]["mode"], "registered_selection_scope")

    def test_research_questions_allow_empty_claims_but_not_claim_entries(self):
        context = psi25_context(
            operation_id="psi25.bass_ii.v4.o2.research_questions",
            data_scope="research-questions",
            expected_claim_ids=None,
        )
        ledger = build_claim_ledger(context, [])
        self.assertEqual(ledger["claims"], [])
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(context, [psi25_claim()])

    def test_unknown_schema_is_rejected(self):
        ledger = build_claim_ledger(psi25_context(), [psi25_claim()])
        ledger["schema"] = "sira.other.v1"
        with self.assertRaises(ClaimLedgerError):
            validate_claim_ledger(ledger, psi25_context())

    def test_unknown_version_is_rejected(self):
        ledger = build_claim_ledger(psi25_context(), [psi25_claim()])
        ledger["ledgerVersion"] = 2
        with self.assertRaises(ClaimLedgerError):
            validate_claim_ledger(ledger, psi25_context())

    def test_investigation_operation_metric_and_scope_must_match_context(self):
        original = build_claim_ledger(psi25_context(), [psi25_claim()])
        mutations = [
            ("investigationId", "psi69-flex-v5"),
            ("operationId", "psi25.bass_ii.v4.co2.ranking"),
            ("metric", "co2"),
            ("dataScope", "all-records"),
        ]
        for key, changed in mutations:
            with self.subTest(key=key):
                ledger = deepcopy(original)
                ledger[key] = changed
                with self.assertRaises(ClaimLedgerError):
                    validate_claim_ledger(ledger, psi25_context())

    def test_context_itself_must_match_registered_operation(self):
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(data_scope="all-records"), [psi25_claim()])

    def test_unverified_upstream_context_fails_closed(self):
        context = psi25_context(upstream_verification="unavailable")
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(context, [psi25_claim()])

    def test_abstained_or_non_executable_answers_cannot_have_a_ledger(self):
        for changes in ({"answer_status": "abstained"}, {"execution_allowed": False}):
            with self.subTest(changes=changes):
                with self.assertRaises(ClaimLedgerError):
                    build_claim_ledger(psi25_context(**changes), [psi25_claim()])

    def test_duplicate_claim_ids_are_rejected(self):
        claim = psi25_claim()
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim, deepcopy(claim)])

    def test_malformed_claim_id_is_rejected(self):
        claim = psi25_claim()
        claim["claimId"] = "bad claim id"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_psi25_claim_id_must_resolve_to_verified_insight_card(self):
        claim = psi25_claim()
        claim["claimId"] = "fabricated-insight"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_unapproved_claim_type_is_rejected(self):
        claim = psi25_claim()
        claim["claimType"] = "safety_ranking"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_claim_type_must_be_allowed_for_exact_operation(self):
        claim = psi25_claim()
        claim["claimType"] = "source_table_count"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_evidence_reference_must_be_allowlisted(self):
        claim = psi25_claim()
        claim["evidenceReferences"][0]["referenceId"] = "unregistered-artifact"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_evidence_hash_must_match_verified_context(self):
        claim = psi25_claim()
        claim["evidenceReferences"][0]["sha256"] = "f" * 64
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_duplicate_evidence_reference_is_rejected(self):
        claim = psi25_claim()
        claim["evidenceReferences"].append(deepcopy(claim["evidenceReferences"][0]))
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_record_lineage_must_resolve_to_verified_canonical_keys(self):
        claim = psi25_claim()
        claim["recordLineage"]["supportingRecordKeys"][0] = "fabricated-record"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_record_lineage_must_exactly_match_verified_finding_mapping(self):
        claim = psi25_claim()
        claim["recordLineage"]["supportingRecordKeys"] = ["rk-001"]
        claim["recordLineage"]["supportingCount"] = 1
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_record_lineage_counts_must_reconcile(self):
        claim = psi25_claim()
        claim["recordLineage"]["supportingCount"] = 9
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_duplicate_record_keys_are_rejected(self):
        claim = psi25_claim()
        claim["recordLineage"]["excludedRecordKeys"] = ["rk-001"]
        claim["recordLineage"]["excludedCount"] = 1
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_incomplete_record_lineage_is_rejected(self):
        claim = psi25_claim()
        claim["recordLineage"]["complete"] = False
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_record_lineage_limit_is_129_combined_keys(self):
        claim = psi25_claim()
        claim["recordLineage"]["supportingRecordKeys"] = [f"rk-{index:03d}" for index in range(1, 130)]
        claim["recordLineage"]["excludedRecordKeys"] = ["rk-001"]
        claim["recordLineage"]["supportingCount"] = 129
        claim["recordLineage"]["excludedCount"] = 1
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_psi69_ids_must_resolve_when_explicitly_listed(self):
        claim = psi69_claim()
        claim["recordLineage"]["supportingRecordIds"] = [999]
        claim["recordLineage"]["supportingCount"] = 1
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi69_context(), [claim])

    def test_nonfinite_numbers_are_rejected(self):
        claim = psi25_claim()
        claim["result"]["mean"] = float("nan")
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_decimal_text_is_preserved_without_float_conversion(self):
        claim = psi25_claim()
        claim["result"]["mean"] = "0.01111111111111111111111111111"
        ledger = build_claim_ledger(psi25_context(), [claim])
        self.assertEqual(ledger["claims"][0]["result"]["mean"], "0.01111111111111111111111111111")

    def test_claim_count_is_bounded(self):
        context = psi69_context()
        claims = []
        for index in range(31):
            claim = psi69_claim()
            claim["claimId"] = f"flex.dataset.snapshot.claim-{index}"
            claims.append(claim)
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(context, claims)

    def test_evidence_reference_count_is_bounded(self):
        claim = psi25_claim()
        claim["evidenceReferences"] = claim["evidenceReferences"] * 3
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_nested_result_depth_and_size_are_bounded(self):
        claim = psi25_claim()
        claim["result"] = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_forbidden_composite_score_keys_are_rejected(self):
        claim = psi25_claim()
        claim["result"]["confidence_score"] = 0.99
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_statement_and_limitations_are_bounded(self):
        claim = psi25_claim()
        claim["statement"] = "x" * 1201
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])
        claim = psi25_claim()
        claim["limitations"] = ["limitation"] * 25
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_quality_dimensions_cannot_claim_scientific_truth(self):
        claim = psi25_claim()
        claim["qualityDimensions"]["scientificTruth"] = "verified"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_quality_dimensions_must_match_lineage_mode(self):
        claim = psi25_claim()
        claim["qualityDimensions"]["recordLineageIntegrity"] = "aggregate_scope"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_research_question_cannot_be_smuggled_as_a_claim(self):
        claim = psi25_claim()
        claim["claimType"] = "research_question"
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(psi25_context(), [claim])

    def test_unsupported_operation_is_rejected(self):
        context = psi25_context(operation_id="psi25.bass_ii.v4.o2.unknown")
        with self.assertRaises(ClaimLedgerError):
            build_claim_ledger(context, [psi25_claim()])

    def test_builder_returns_detached_data(self):
        claim = psi25_claim()
        ledger = build_claim_ledger(psi25_context(), [claim])
        claim["result"]["mean"] = "tampered-after-build"
        self.assertEqual(ledger["claims"][0]["result"]["mean"], "0.01")


if __name__ == "__main__":
    unittest.main()
