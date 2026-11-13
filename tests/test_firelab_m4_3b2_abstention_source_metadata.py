from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "firelab_site/app.js").read_text(encoding="utf-8")
BACKEND = (ROOT / "firelab_service/multi_investigation.py").read_text(encoding="utf-8")


class FireLabM43B2AbstentionSourceMetadataTests(unittest.TestCase):
    def test_abstained_answers_do_not_receive_psi69_source_default(self):
        self.assertIn(
            'answer.status === "abstained" ? "" : "NASA PSI-69"', APP
        )

    def test_successful_legacy_answers_keep_psi69_source_fallback(self):
        self.assertIn(
            'answer.status === "abstained" ? "" : "NASA PSI-69"', APP
        )
        self.assertIn(
            '(sourceMetadataPresent ? "Source identity unavailable" : "NASA PSI-69")',
            APP,
        )

    def test_empty_abstention_is_identified_as_no_source_access(self):
        self.assertIn(
            'const noSourceAccess = answer.status === "abstained" && !sourceMetadataPresent;',
            APP,
        )
        self.assertIn('noSourceAccess ? "Not accessed"', APP)

    def test_source_provenance_rows_distinguish_not_accessed_from_unavailable(self):
        for field in (
            "Source file", "Source CSV SHA-256", "Records bundle SHA-256",
            "Quality bundle SHA-256", "Release", "License",
        ):
            self.assertIn(f'["{field}",', APP)
        self.assertGreaterEqual(APP.count('noSourceAccess ? "Not accessed"'), 7)

    def test_existing_source_provenance_is_preserved_when_present(self):
        self.assertIn('answer.sourceFile || (noSourceAccess ? "Not accessed" : "Unavailable")', APP)
        self.assertIn('answer.sourceHash || (noSourceAccess ? "Not accessed" : "Unavailable")', APP)
        self.assertIn('answer.recordsHash || (noSourceAccess ? "Not accessed" : "Unavailable")', APP)

    def test_legacy_abstentions_with_only_old_psi69_label_are_not_misidentified(self):
        self.assertIn("const sourceMetadataPresent = Boolean(", APP)
        self.assertIn("answer.sourceFile || answer.sourceVersion || answer.sourceHash", APP)
        self.assertIn("answer.recordsHash || answer.qualityHash || answer.sourceUrl", APP)
        self.assertIn('noSourceAccess ? "Not accessed" : (answer.source ||', APP)

    def test_service_unavailable_fallback_does_not_attach_flex_manifest(self):
        start = APP.index("function assistantUnavailableAnswer()")
        end = APP.index("\nasync function ask(", start)
        block = APP[start:end]
        self.assertIn('source: ""', block)
        self.assertIn('sourceFile: ""', block)
        self.assertIn('sourceVersion: ""', block)
        self.assertIn('sourceHash: ""', block)
        self.assertNotIn("manifest?.source", block)
        self.assertNotIn("PSI-69_Experimental table_FLEX.csv", block)

    def test_backend_abstention_contract_remains_source_empty(self):
        start = BACKEND.index('def _base(')
        end = BACKEND.index('\n    @staticmethod\n    def _finish', start)
        block = BACKEND[start:end]
        for field in ("source", "sourceFile", "sourceVersion", "sourceHash", "sourceUrl"):
            self.assertIn(f'"{field}": ""', block)

    def test_rendering_remains_dom_text_based(self):
        start = APP.index("const sourceMetadataPresent = Boolean(")
        end = APP.index("for (const [term, value] of factRows)", start)
        source_panel = APP[start:end]
        self.assertNotIn("innerHTML", source_panel)
        self.assertIn("dd.textContent = value", APP)


if __name__ == "__main__":
    unittest.main()
