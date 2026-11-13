from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "firelab_site/psi25.js").read_text(encoding="utf-8")
CSS = (ROOT / "firelab_site/styles.css").read_text(encoding="utf-8")
BASE = ROOT / "firelab_site/data/derived/psi25_bass_ii_v4"
CSS_MARKER = "/* PSI-25 synthesis question metadata polish */"


class Psi25SynthesisUiPolishTests(unittest.TestCase):
    def test_long_decimal_narrative_formatter_uses_seven_significant_digits(self):
        self.assertIn("function synthesisFormatNarrative(value)", JS)
        self.assertIn(r"\d{8,}", JS)
        self.assertIn("synthesisDisplay(numeric)", JS)

    def test_observation_and_distribution_use_presentation_formatter(self):
        self.assertIn("synthesisFormatNarrative(card.observation", JS)
        self.assertIn("synthesisFormatNarrative(card.distribution)", JS)

    def test_card_and_global_question_metadata_are_separated(self):
        self.assertGreaterEqual(JS.count('node("div", "psi25-synthesis-question-meta")'), 2)
        self.assertIn('metadata.append(node("span", "psi25-synthesis-question-id"', JS)
        self.assertIn('metadata.append(node("span", "psi25-synthesis-question-trigger"', JS)

    def test_question_metadata_has_flex_gap_and_wrap(self):
        self.assertIn(CSS_MARKER, CSS)
        block = CSS.split(CSS_MARKER, 1)[1]
        self.assertIn("display: flex", block)
        self.assertIn("flex-wrap: wrap", block)
        self.assertIn("gap: 0.4rem 0.6rem", block)

    def test_equal_mean_ranks_are_labeled_without_resorting_cards(self):
        self.assertIn("const tiedMean =", JS)
        self.assertIn('" · TIED MEAN"', JS)
        self.assertIn("candidate.rank === card.rank", JS)
        self.assertIn("shared rank only when signed means are exactly equal", JS)

    def test_not_rankable_cards_remain_unranked(self):
        self.assertIn('? "NOT RANKABLE"', JS)
        self.assertIn('card.interpretation_status !== "not_rankable"', JS)

    def test_question_ids_and_question_text_remain_present(self):
        self.assertIn('question.question_id || "Question"', JS)
        self.assertIn('question.question || "Question text unavailable."', JS)

    def test_verified_synthesis_artifact_is_unchanged_and_still_lineaged(self):
        synthesis = json.loads((BASE / "evidence_synthesis_v1/evidence_synthesis.json").read_text(encoding="utf-8"))
        manifest = json.loads((BASE / "evidence_synthesis_v1/synthesis_manifest.json").read_text(encoding="utf-8"))
        findings_manifest = json.loads((BASE / "findings_ranking_v1/findings_manifest.json").read_text(encoding="utf-8"))
        analysis_manifest = json.loads((BASE / "paired_analysis_v1/analysis_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(synthesis["insight_card_count"], 54)
        self.assertEqual(len(synthesis["research_questions"]), 146)
        self.assertEqual(manifest["source_artifacts"]["findings_ranking"]["sha256"], findings_manifest["derived_output"]["sha256"])
        self.assertEqual(manifest["source_artifacts"]["paired_measurement_analysis"]["sha256"], analysis_manifest["derived_output"]["sha256"])


if __name__ == "__main__":
    unittest.main()
