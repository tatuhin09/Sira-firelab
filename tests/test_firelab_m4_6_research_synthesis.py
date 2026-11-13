from __future__ import annotations

import copy
import unittest

from firelab_service.research_synthesis import FireLabResearchSynthesisService

PSI69 = "psi69-flex-v5"
PSI25 = "psi25-bass-ii-v4"
LEDGER_SCHEMA = "sira.firelab.claim_ledger.v1"


def answer_for(investigation=PSI69, operation="flex.dataset.snapshot", metric="", scope="all-records"):
    ledger = {
        "schema": LEDGER_SCHEMA,
        "ledgerVersion": 1,
        "investigationId": investigation,
        "sourceRelease": "FLEX v5" if investigation == PSI69 else "BASS-II v4",
        "operationId": operation,
        "metric": metric,
        "dataScope": scope,
        "ledgerStatus": "verified_provenance",
        "claims": [{
            "claimId": operation + ".claim",
            "claimType": "source_table_count",
            "statement": "The registered source contains verified experiment records.",
            "result": {"recordCount": 10},
            "metric": metric,
            "unit": "records",
            "cohort": None,
            "evidenceReferences": [{"referenceId": "psi69.records", "sha256": "a" * 64}],
            "recordLineage": {"mode": "registered_selection_scope", "supportingCount": 10, "excludedCount": 0, "complete": True},
            "qualityDimensions": {"missionTransferability": "not_established"},
            "limitations": ["Descriptive source scope only."],
            "interpretationStatus": "source_reported",
        }],
    }
    return {
        "status": "completed", "investigationId": investigation,
        "analysisId": operation, "metric": metric, "dataScope": scope,
        "sampleSize": 10, "scientificPlan": {
            "operationId": operation, "metric": metric,
            "dataScope": scope, "resolvedInvestigation": investigation,
        },
        "claimLedger": ledger,
    }


class FakeRegistry:
    def __init__(self):
        self.entry = object()
        self.calls = []

    def get(self, investigation_id):
        self.calls.append(investigation_id)
        return self.entry


class FakeAdapter:
    def __init__(self, *, state="fresh", sources=None, partial=False):
        self.state = state
        self.sources = list(sources if sources is not None else [{
            "source_id": "paper-123", "title": "Microgravity combustion paper",
            "abstract": "Metadata abstract only.", "doi": "10.1234/example",
            "url": "https://doi.org/10.1234/example",
            "provider": "crossref", "interpretation_status": "metadata_only_not_independently_verified",
        }])
        self.partial = partial
        self.calls = []

    def retrieve_supporting_literature(self, *, query, completed_answer, refresh=False):
        self.calls.append((query, completed_answer, refresh))
        return {
            "schema": "sira.firelab.research_evidence_packet.v1",
            "dataset_context": {
                "investigation_id": completed_answer["investigationId"],
                "operation_id": completed_answer["analysisId"],
                "metric": completed_answer.get("metric", ""),
                "data_scope": completed_answer["dataScope"],
            },
            "literature": {
                "query": query, "state": self.state, "retrieved_at": "2026-11-11T00:00:00Z",
                "providers": ["crossref"] if self.sources else [], "partial": self.partial,
                "sources": self.sources,
            },
            "limitations": ["Paper metadata is not full-text evidence."],
        }


def verified_report(_entry, _answer):
    return {"status": "verified", "checks": [{"check_id": "integrity", "status": "passed"}], "claim_results": []}


class FireLabResearchSynthesisTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.adapter = FakeAdapter()
        self.service = FireLabResearchSynthesisService(self.registry, self.adapter, verifier=verified_report)

    def test_verified_answer_is_assembled_with_source_separated_evidence(self):
        answer = answer_for()
        original = copy.deepcopy(answer)
        result = self.service.synthesize(literature_query="FLEX microgravity combustion", completed_answer=answer)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["scientific_verification"]["status"], "verified")
        self.assertEqual(result["dataset_context"]["investigation_id"], PSI69)
        self.assertEqual(len(result["dataset_claims"]), 1)
        self.assertEqual(result["literature"]["source_count"], 1)
        self.assertEqual(result["literature"]["sources"][0]["claim_support_status"], "not_assessed")
        self.assertEqual(result["synthesis"]["claim_to_literature_links"], [])
        self.assertFalse(result["synthesis"]["generated_with_model"])
        self.assertFalse(result["synthesis"]["literature_verifies_nasa_measurements"])
        self.assertEqual(answer, original)

    def test_verifier_failure_blocks_retrieval(self):
        service = FireLabResearchSynthesisService(
            self.registry, self.adapter,
            verifier=lambda _entry, _answer: {"status": "failed", "checks": [{"status": "failed"}], "claim_results": []},
        )
        result = service.synthesize(literature_query="microgravity combustion", completed_answer=answer_for())
        self.assertEqual(result["status"], "abstained")
        self.assertEqual(result["reason"], "independent_scientific_verification_not_passed")
        self.assertEqual(self.adapter.calls, [])

    def test_research_question_operation_is_not_a_measurement_synthesis(self):
        answer = answer_for(PSI25, "psi25.bass_ii.v4.research_questions", "", "research-questions")
        result = self.service.synthesize(literature_query="BASS-II research gaps", completed_answer=answer)
        self.assertEqual(result["status"], "abstained")
        self.assertEqual(result["reason"], "operation_not_registered_for_measurement_synthesis")
        self.assertEqual(self.adapter.calls, [])

    def test_missing_claim_ledger_blocks_retrieval(self):
        answer = answer_for()
        answer.pop("claimLedger")
        result = self.service.synthesize(literature_query="microgravity combustion", completed_answer=answer)
        self.assertEqual(result["status"], "abstained")
        self.assertEqual(result["reason"], "verified_claim_ledger_required")
        self.assertEqual(self.adapter.calls, [])

    def test_incomplete_answer_blocks_retrieval(self):
        answer = answer_for()
        answer["status"] = "abstained"
        result = self.service.synthesize(literature_query="microgravity combustion", completed_answer=answer)
        self.assertEqual(result["status"], "abstained")
        self.assertEqual(self.adapter.calls, [])

    def test_registry_operation_context_mismatch_blocks_retrieval(self):
        answer = answer_for()
        answer["analysisId"] = "flex.measurement_quality"
        result = self.service.synthesize(literature_query="microgravity combustion", completed_answer=answer)
        self.assertEqual(result["status"], "abstained")
        self.assertEqual(self.adapter.calls, [])

    def test_offline_cache_miss_returns_limited_brief_without_invented_sources(self):
        self.adapter = FakeAdapter(state="cache_miss_offline", sources=[])
        self.service = FireLabResearchSynthesisService(self.registry, self.adapter, verifier=verified_report)
        result = self.service.synthesize(literature_query="microgravity combustion", completed_answer=answer_for())
        self.assertEqual(result["status"], "limited_no_literature")
        self.assertEqual(result["literature"]["source_count"], 0)
        self.assertEqual(result["literature"]["sources"], [])
        self.assertEqual(result["synthesis"]["claim_to_literature_links"], [])

    def test_stale_cache_is_marked_limited(self):
        self.adapter = FakeAdapter(state="cache_stale")
        self.service = FireLabResearchSynthesisService(self.registry, self.adapter, verifier=verified_report)
        result = self.service.synthesize(literature_query="microgravity combustion", completed_answer=answer_for())
        self.assertEqual(result["status"], "limited_stale_literature")

    def test_partial_literature_is_marked_limited(self):
        self.adapter = FakeAdapter(state="fresh", partial=True)
        self.service = FireLabResearchSynthesisService(self.registry, self.adapter, verifier=verified_report)
        result = self.service.synthesize(literature_query="microgravity combustion", completed_answer=answer_for())
        self.assertEqual(result["status"], "limited_partial_literature")

    def test_psi25_o2_interpretation_preserves_calibration_and_transferability_caveats(self):
        answer = answer_for(PSI25, "psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        result = self.service.synthesize(literature_query="BASS-II oxygen concentration microgravity", completed_answer=answer)
        text = result["mission_interpretation"]["statement"].casefold()
        self.assertIn("calibration", text)
        self.assertEqual(result["mission_interpretation"]["mission_transferability"], "not_established")
        self.assertFalse(result["mission_interpretation"]["operational_safety_conclusion"])

    def test_refresh_is_forwarded_only_after_verification(self):
        self.service.synthesize(literature_query="microgravity combustion", completed_answer=answer_for(), refresh=True)
        self.assertEqual(self.adapter.calls[0][0], "microgravity combustion")
        self.assertTrue(self.adapter.calls[0][2])

    def test_adapter_exception_does_not_get_converted_to_scientific_claim(self):
        from firelab_service.research_adapter import ResearchAdapterError
        class BrokenAdapter:
            def retrieve_supporting_literature(self, **_kwargs):
                raise ResearchAdapterError("bounded adapter refusal")
        service = FireLabResearchSynthesisService(self.registry, BrokenAdapter(), verifier=verified_report)
        with self.assertRaises(ResearchAdapterError):
            service.synthesize(literature_query="microgravity combustion", completed_answer=answer_for())

    def test_only_approved_operation_specs_are_accepted(self):
        answer = answer_for(PSI25, "psi25.bass_ii.v4.o2.ranking", "o2", "cohort-evidence")
        result = self.service.synthesize(literature_query="BASS-II oxygen", completed_answer=answer)
        self.assertEqual(result["dataset_context"]["operation_id"], "psi25.bass_ii.v4.o2.ranking")
        self.assertEqual(result["dataset_context"]["metric"], "o2")


if __name__ == "__main__":
    unittest.main()
