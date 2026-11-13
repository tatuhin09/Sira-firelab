from pathlib import Path
import unittest

from firelab_service.assistant import (
    FireLabEvidenceAssistant,
    normalize_conversation_id,
    normalize_question,
)
from firelab_service.engine import load_bundle

ROOT = Path(__file__).resolve().parents[1]


class FireLabEvidenceAssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assistant = FireLabEvidenceAssistant(load_bundle(ROOT / "firelab_site"))

    def ask(self, question):
        return self.assistant.ask(question, conversation_id="test-conversation-01")

    def test_dataset_summary_is_server_backed_and_provenanced(self):
        answer = self.ask("Summarize the FLEX dataset")
        self.assertEqual(answer["status"], "completed")
        self.assertEqual(answer["dataScope"], "all-records")
        self.assertEqual(answer["sampleSize"], 274)
        self.assertIn("The verified PSI-69 Version 5 bundle", answer["text"])
        self.assertNotIn("PSI-69 PSI-69", answer["text"])
        self.assertIn("PSI-69", answer["source"])
        self.assertEqual(len(answer["sourceHash"]), 64)
        self.assertEqual(len(answer["recordsHash"]), 64)
        self.assertEqual(len(answer["qualityHash"]), 64)
        self.assertEqual(answer["analysisId"], "flex.dataset.snapshot")
        self.assertTrue(answer["sourceUrl"].startswith("https://psi.nasa.gov/"))
        self.assertTrue(answer["reportUrl"].startswith("https://ntrs.nasa.gov/"))
        self.assertTrue(answer["doi"].startswith("10."))
        self.assertIn("Methanol: n=157", answer["bullets"])
        self.assertIn("Heptane: n=117", answer["bullets"])
        self.assertEqual([event["sequence"] for event in answer["events"]], list(range(1, 7)))
        self.assertEqual(answer["events"][-1]["type"], "answer.completed")

    def test_outcome_counts_by_fuel_are_descriptive(self):
        answer = self.ask("Show outcome counts by fuel")
        self.assertEqual(answer["intent"], "outcomes_by_fuel")
        self.assertIn("Methanol (n=157): Extinction 126, Disruption 23, Completion 8", answer["bullets"])
        self.assertIn("Heptane (n=117): Extinction 60, Disruption 38, Completion 19", answer["bullets"])
        self.assertIn("do not establish a fuel effect", answer["text"])

    def test_quality_answer_preserves_all_quality_categories(self):
        answer = self.ask("What should I know about data quality?")
        self.assertEqual(answer["dataScope"], "quality-summary")
        self.assertEqual(len(answer["qualityRows"]), 9)
        self.assertIn("approximate", answer["text"])
        self.assertIn("Source-reported zero-pressure FLEX Test ID(s): 114", answer["bullets"])

    def test_burning_rate_uses_exact_values_and_documented_unit(self):
        answer = self.ask("Summarize the burning rate")
        self.assertEqual(answer["dataScope"], "exact-burning-rate")
        self.assertEqual(answer["sampleSize"], 258)
        self.assertTrue(any("Heptane: mean 0.545 ± 0.161 mm²/s" in item for item in answer["bullets"]))
        self.assertIn("exact finite values only", answer["text"])

    def test_oxygen_comparison_uses_registered_cohorts_and_row_binding(self):
        answer = self.ask("Compare oxygen conditions")
        self.assertEqual(answer["intent"], "oxygen_sensitivity")
        self.assertEqual(answer["sampleSize"], 64)
        self.assertEqual(len(answer["recordIds"]), 64)
        self.assertIn("Fixed O₂ = 0.21: n=25", answer["bullets"][0])
        self.assertTrue(any("44.2 pp" in item for item in answer["bullets"]))
        self.assertIn("cohorts overlap", answer["text"])
        self.assertTrue(any(
            "Order of absolute observed outcome-share gaps changed between cohorts: yes" in item
            for item in answer["bullets"]
        ))

    def test_safety_and_causal_questions_abstain_without_opening_or_filtering_data(self):
        answer = self.ask("Which fuel is safer?")
        self.assertEqual(answer["status"], "abstained")
        self.assertEqual(answer["dataScope"], "none")
        self.assertEqual([event["type"] for event in answer["events"]], ["turn.started", "answer.abstained"])
        self.assertEqual(answer["sampleSize"], 0)

    def test_hazard_and_prescriptive_questions_abstain_without_analysis(self):
        questions = [
            "Is Methanol dangerous for spacecraft fires?",
            "Is Heptane hazardous?",
            "Which fuel is more risky?",
            "Is Methanol unsafe?",
            "Can Methanol be recommended for spacecraft?",
            "Could Methanol prevent a spacecraft fire?",
            "What is the safest fuel for spacecraft?",
            "Should we use Methanol for spacecraft fires?",
            "Is Methanol suitable for spacecraft fires?",
        ]

        for question in questions:
            with self.subTest(question=question):
                answer = self.ask(question)
                self.assertEqual(answer["intent"], "safety_or_causality")
                self.assertEqual(answer["status"], "abstained")
                self.assertEqual(answer["dataScope"], "none")
                self.assertEqual(answer["sampleSize"], 0)
                self.assertEqual(
                    [event["type"] for event in answer["events"]],
                    ["turn.started", "answer.abstained"],
                )

        # Preserve the legitimate data-quality question despite "should".
        quality = self.ask("What should I know about data quality?")
        self.assertEqual(quality["intent"], "data_quality")
        self.assertEqual(quality["status"], "completed")

    def test_unsupported_question_abstains(self):
        answer = self.ask("Tell me a joke")
        self.assertEqual(answer["status"], "abstained")
        self.assertEqual(answer["intent"], "unsupported")
        self.assertEqual(answer["dataScope"], "none")

    def test_conversation_event_ids_are_scoped_and_unique(self):
        answer = self.ask("Summarize the FLEX dataset")
        self.assertTrue(all(e["conversation_id"] == "test-conversation-01" for e in answer["events"]))
        self.assertEqual(len({e["event_id"] for e in answer["events"]}), len(answer["events"]))
        self.assertEqual(len({e["turn_id"] for e in answer["events"]}), 1)

    def test_question_and_conversation_id_validation(self):
        for bad in (None, 12, "x", "a" * 401, "abc\x00def"):
            with self.subTest(value=repr(bad)), self.assertRaises(ValueError):
                normalize_question(bad)
        for bad in (None, "", "contains spaces", "../etc/passwd", "x" * 101):
            with self.subTest(value=repr(bad)), self.assertRaises(ValueError):
                normalize_conversation_id(bad)
        self.assertEqual(normalize_question("  Compare   oxygen conditions "), "Compare oxygen conditions")


if __name__ == "__main__":
    unittest.main()
