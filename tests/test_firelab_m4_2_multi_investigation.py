from pathlib import Path
import unittest
import json
import threading
from http.client import HTTPConnection
from firelab_service.evidence_registry import load_evidence_registry
from firelab_service.http_app import create_server
from firelab_service.multi_investigation import AUTO_ID, PSI25_ID, PSI69_ID, MultiInvestigationEvidenceAssistant

ROOT = Path(__file__).resolve().parents[1]

class FireLabM42MultiInvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_evidence_registry(ROOT)
        cls.assistant = MultiInvestigationEvidenceAssistant(cls.registry)

    def ask(self, q, iid=PSI69_ID):
        return self.assistant.ask(q, conversation_id="m42-test-conversation", investigation_id=iid)

    def test_default_request_preserves_psi69_answer_contract(self):
        a = self.assistant.ask("Summarize the FLEX dataset", conversation_id="m42-default")
        self.assertEqual((a["status"], a["sampleSize"], a["analysisId"], a["investigationId"]), ("completed",274,"flex.dataset.snapshot",PSI69_ID))

    def test_explicit_psi69_delegates_to_existing_assistant(self):
        a=self.ask("Show outcome counts by fuel")
        self.assertEqual(a["sampleSize"],274)
        self.assertIn("do not establish a fuel effect",a["text"])

    def test_auto_routing_detects_psi25(self):
        a=self.ask("Summarize PSI-25 BASS-II",AUTO_ID)
        self.assertEqual((a["investigationId"],a["sampleSize"]),(PSI25_ID,129))

    def test_psi25_snapshot_keeps_three_metrics_separate(self):
        a=self.ask("Summarize BASS-II dataset",PSI25_ID)
        self.assertEqual(a["status"],"completed")
        self.assertEqual(a["dataScope"],"all-records")
        self.assertEqual(set(a["metricSummary"]),{"o2","co2","co"})
        self.assertIn("not pooled",a["text"])

    def test_o2_ranking_is_specific_and_has_caveats(self):
        a=self.ask("Show O2 ranking in BASS-II",PSI25_ID)
        self.assertEqual((a["metric"],a["eligiblePairCount"],a["excludedPairCount"],a["rankableCohortCount"]),("o2",127,2,17))
        self.assertTrue(a["claimReferences"])
        self.assertTrue(any("calibration" in x.casefold() for x in a["bullets"]))

    def test_co2_has_its_own_unit_and_counts(self):
        a=self.ask("Show CO2 findings in BASS-II",PSI25_ID)
        self.assertEqual((a["metric"],a["eligiblePairCount"],a["excludedPairCount"]),("co2",121,8))
        self.assertTrue(any("% by volume" in x for x in a["bullets"]))

    def test_co_has_its_own_counts_and_not_rankable_cohorts(self):
        a=self.ask("Show CO ranking in BASS-II",PSI25_ID)
        self.assertEqual((a["metric"],a["eligiblePairCount"],a["excludedPairCount"],a["notRankableCohortCount"]),("co",106,23,3))

    def test_metric_research_questions_are_filtered(self):
        a=self.ask("List oxygen research questions for BASS-II",PSI25_ID)
        self.assertEqual(a["dataScope"],"research-questions")
        self.assertTrue(a["researchQuestions"])
        self.assertTrue(all(x["question_id"].startswith("RQ-O2-") for x in a["researchQuestions"]))

    def test_all_research_questions_count_is_preserved(self):
        a=self.ask("List BASS-II research questions",PSI25_ID)
        self.assertEqual(a["sampleSize"],146)
        self.assertLessEqual(len(a["researchQuestions"]),12)

    def test_cross_metric_request_abstains_before_analysis(self):
        a=self.ask("Compare oxygen and CO2 changes in BASS-II",PSI25_ID)
        self.assertEqual(a["status"],"abstained")
        self.assertEqual([x["type"] for x in a["events"]],["turn.started","answer.abstained"])

    def test_cross_investigation_request_abstains_before_analysis(self):
        a=self.ask("Compare PSI-69 FLEX with PSI-25 BASS-II",AUTO_ID)
        self.assertEqual(a["status"],"abstained")
        self.assertEqual([x["type"] for x in a["events"]],["turn.started","answer.abstained"])

    def test_selector_question_conflict_abstains(self):
        a=self.ask("Summarize PSI-25 BASS-II",PSI69_ID)
        self.assertEqual((a["status"],a["dataScope"]),("abstained","none"))

    def test_safety_or_prescriptive_question_abstains(self):
        a=self.ask("Which BASS-II fuel is safest for spacecraft fires?",PSI25_ID)
        self.assertEqual((a["status"],a["dataScope"]),("abstained","none"))
        self.assertEqual([x["type"] for x in a["events"]],["turn.started","answer.abstained"])

    def test_unsupported_question_abstains(self):
        a=self.ask("Tell me a joke about BASS-II",PSI25_ID)
        self.assertEqual(a["status"],"abstained")

    def test_hashes_and_citation_references_are_returned(self):
        a=self.ask("Show O2 findings in BASS-II",PSI25_ID)
        self.assertTrue(all(len(a[k])==64 for k in ("sourceHash","recordsHash","qualityHash")))
        self.assertEqual(len(a["artifactHashes"]),9)
        self.assertEqual({x["reference_id"] for x in a["citations"]},{"psi25-source-csv","psi25-canonical-records","psi25-paired-analysis","psi25-findings","psi25-synthesis"})

    def test_record_refs_resolve_to_verified_canonical_keys(self):
        a=self.ask("Show O2 findings in BASS-II",PSI25_ID)
        allowed=set(self.registry.get(PSI25_ID).payload["record_keys"])
        self.assertTrue(a["recordRefs"])
        self.assertLessEqual(len(a["recordRefs"]),60)
        self.assertTrue(set(a["recordRefs"]).issubset(allowed))

    def test_o2_sample_reuse_flag_is_retained(self):
        a=self.ask("Show oxygen findings in BASS-II",PSI25_ID)
        self.assertTrue(any("sample_id_reuse_possible_dependence" in str(x.get("flags",[])) for x in a["claimReferences"]))

    def test_unknown_investigation_fails_closed(self):
        a=self.ask("Summarize BASS-II","private-sira-core")
        self.assertEqual((a["status"],a["dataScope"]),("abstained","none"))

    def test_event_sequence_and_conversation_scope(self):
        a=self.ask("Summarize BASS-II",PSI25_ID)
        self.assertEqual([x["sequence"] for x in a["events"]],list(range(1,len(a["events"])+1)))
        self.assertTrue(all(x["conversation_id"]=="m42-test-conversation" for x in a["events"]))

    def _http_post(self, payload):
        server = create_server(ROOT, port=0, offline=True, service=object(), assistant_service=self.assistant)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            conn.request("GET", "/api/session")
            session_response = conn.getresponse()
            session = json.loads(session_response.read().decode("utf-8"))
            headers = {"Content-Type": "application/json", "X-FireLab-Session": session["token"]}
            conn.request("POST", "/api/assistant/ask", body=json.dumps(payload), headers=headers)
            response = conn.getresponse()
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_api_accepts_approved_psi25_investigation_selector(self):
        status, body = self._http_post({"question":"Show O2 ranking in BASS-II",
            "conversation_id":"m42-http-test", "investigation_id":PSI25_ID})
        self.assertEqual(status, 200)
        self.assertEqual(body["investigationId"], PSI25_ID)
        self.assertEqual(body["eligiblePairCount"], 127)

    def test_http_api_rejects_unapproved_investigation_selector(self):
        status, body = self._http_post({"question":"Summarize BASS-II",
            "conversation_id":"m42-http-test", "investigation_id":"../../private"})
        self.assertEqual(status, 400)
        self.assertEqual(body.get("error"), "invalid_request")

if __name__ == "__main__":
    unittest.main()
