from __future__ import annotations

import copy
import unittest

from firelab_service.research_adapter import (
    FireLabResearchAdapter,
    ResearchAdapterError,
)


PSI69 = "psi69-flex-v5"
PSI25 = "psi25-bass-ii-v4"


def answer_for(investigation=PSI69, operation="flex.dataset.snapshot", scope="all-records", metric=""):
    plan = {
        "operationId": operation,
        "dataScope": scope,
        "metric": metric,
        "resolvedInvestigation": investigation,
    }
    ledger = {
        "schema": "sira.firelab.claim_ledger.v1",
        "ledgerVersion": 1,
        "investigationId": investigation,
        "sourceRelease": "FLEX v5" if investigation == PSI69 else "BASS-II v4",
        "operationId": operation,
        "metric": metric,
        "dataScope": scope,
        "ledgerStatus": "verified_provenance",
        "claims": [{
            "claimId": "snapshot-claim",
            "evidenceReferences": [{"referenceId": "psi69.records", "sha256": "a" * 64}],
        }],
    }
    return {
        "status": "completed",
        "investigationId": investigation,
        "analysisId": operation,
        "dataScope": scope,
        "metric": metric,
        "sampleSize": 274 if investigation == PSI69 else 129,
        "analysisVersion": 1,
        "title": "Verified source snapshot",
        "text": "Descriptive source result only.",
        "bullets": ["Source count retained."],
        "scientificPlan": plan,
        "claimLedger": ledger,
    }


class FakePaperSearchService:
    def __init__(self, result=None):
        self.result = result or {
            "state": "fresh",
            "query": "microgravity combustion",
            "papers": [{
                "paper_id": "record-1",
                "title": "Microgravity combustion study",
                "abstract": "A source abstract.",
                "authors": ["Author One"],
                "year": 2024,
                "doi": "10.example/test",
                "url": "https://doi.org/10.example/test",
                "open_access_pdf_url": None,
                "retrieved_at": "2026-11-11T00:00:00Z",
                "provider": "crossref",
                "published_date": "2024-01-01",
                "providers": ["crossref"],
                "matched_terms": ["microgravity"],
            }],
            "retrieved_at": "2026-11-11T00:00:00Z",
            "providers": ["crossref"],
            "partial": False,
        }
        self.calls = []

    def search(self, query, *, refresh=False):
        self.calls.append((query, refresh))
        return self.result


class FireLabResearchAdapterTests(unittest.TestCase):
    def setUp(self):
        self.service = FakePaperSearchService()
        self.adapter = FireLabResearchAdapter(self.service)

    def test_attaches_literature_to_completed_psi69_context(self):
        packet = self.adapter.retrieve_supporting_literature(
            query="microgravity combustion", completed_answer=answer_for()
        )
        self.assertEqual(packet["schema"], "sira.firelab.research_evidence_packet.v1")
        self.assertEqual(packet["dataset_context"]["investigation_id"], PSI69)
        self.assertEqual(packet["literature"]["state"], "fresh")
        self.assertEqual(packet["literature"]["source_count"], 1)
        self.assertEqual(packet["literature"]["sources"][0]["source_type"], "scholarly_record_metadata")

    def test_supports_metric_specific_psi25_context(self):
        answer = answer_for(PSI25, "psi25.bass_ii.v4.o2.ranking", "cohort-evidence", "o2")
        packet = self.adapter.retrieve_supporting_literature(
            query="BASS-II oxygen measurements", completed_answer=answer
        )
        self.assertEqual(packet["dataset_context"]["investigation_id"], PSI25)
        self.assertEqual(packet["dataset_context"]["metric"], "o2")

    def test_preserves_provenance_only_not_scientific_verification_boundary(self):
        packet = self.adapter.retrieve_supporting_literature(
            query="microgravity combustion", completed_answer=answer_for()
        )
        boundary = packet["verification_boundary"]
        self.assertEqual(boundary["status"], "not_performed")
        self.assertFalse(boundary["dataset_claims_verified_by_literature"])
        self.assertFalse(boundary["cross_investigation_pooling_performed"])

    def test_explicit_refresh_is_forwarded(self):
        self.adapter.retrieve_supporting_literature(
            query="microgravity combustion", completed_answer=answer_for(), refresh=True
        )
        self.assertEqual(self.service.calls, [("microgravity combustion", True)])

    def test_invalid_answer_is_rejected_before_service_call(self):
        bad = answer_for()
        bad["status"] = "abstained"
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=bad)
        self.assertEqual(self.service.calls, [])

    def test_plan_operation_mismatch_fails_closed(self):
        bad = answer_for()
        bad["scientificPlan"]["operationId"] = "flex.measurement_quality"
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=bad)
        self.assertEqual(self.service.calls, [])

    def test_plan_scope_mismatch_fails_closed(self):
        bad = answer_for()
        bad["scientificPlan"]["dataScope"] = "selected-records"
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=bad)
        self.assertEqual(self.service.calls, [])

    def test_claim_ledger_context_mismatch_fails_closed(self):
        bad = answer_for()
        bad["claimLedger"]["operationId"] = "flex.measurement_quality"
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=bad)
        self.assertEqual(self.service.calls, [])

    def test_unknown_operation_fails_before_retrieval(self):
        bad = answer_for()
        bad["analysisId"] = "flex.unregistered.operation"
        bad["scientificPlan"]["operationId"] = "flex.unregistered.operation"
        bad["claimLedger"] = None
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=bad)
        self.assertEqual(self.service.calls, [])

    def test_unregistered_investigation_fails_closed(self):
        bad = answer_for()
        bad["investigationId"] = "psi98-saффire"
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=bad)
        self.assertEqual(self.service.calls, [])

    def test_research_question_context_can_have_no_claim_ledger(self):
        answer = answer_for(PSI25, "psi25.bass_ii.v4.research_questions", "research-questions", "")
        answer["claimLedger"] = None
        packet = self.adapter.retrieve_supporting_literature(
            query="BASS-II evidence gaps", completed_answer=answer
        )
        self.assertEqual(packet["dataset_context"]["claim_ledger_status"], "not_present")
        self.assertIsNone(packet["dataset_context"]["claim_ledger"])

    def test_invalid_search_state_is_rejected(self):
        self.service.result = {"state": "invented", "papers": []}
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=answer_for())

    def test_more_than_three_papers_is_rejected(self):
        self.service.result = {"state": "fresh", "papers": [{"title": "x"}] * 4}
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=answer_for())

    def test_non_https_paper_url_is_not_emitted(self):
        self.service.result["papers"][0]["url"] = "http://example.org/paper"
        packet = self.adapter.retrieve_supporting_literature(
            query="microgravity combustion", completed_answer=answer_for()
        )
        self.assertIsNone(packet["literature"]["sources"][0]["url"])

    def test_does_not_mutate_source_answer(self):
        answer = answer_for()
        original = copy.deepcopy(answer)
        self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=answer)
        self.assertEqual(answer, original)

    def test_query_bounds_are_enforced_before_search(self):
        for query in ("ab", "x" * 201, "\x00bad"):
            with self.subTest(query=query[:8]), self.assertRaises(ResearchAdapterError):
                self.adapter.retrieve_supporting_literature(query=query, completed_answer=answer_for())
        self.assertEqual(self.service.calls, [])

    def test_refresh_must_be_boolean(self):
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(
                query="microgravity", completed_answer=answer_for(), refresh=1
            )

    def test_non_object_search_response_fails_closed(self):
        self.service.result = ["not", "an", "object"]
        with self.assertRaises(ResearchAdapterError):
            self.adapter.retrieve_supporting_literature(query="microgravity", completed_answer=answer_for())


if __name__ == "__main__":
    unittest.main()
