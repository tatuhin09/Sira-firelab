from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FireLabM3FrontendTests(unittest.TestCase):
    def test_workspace_identifies_server_evidence_mode_without_claiming_generative_ai(self):
        html = (ROOT / "firelab_site" / "index.html").read_text(encoding="utf-8")
        self.assertIn("SIRA CORE · EVIDENCE MODE", html)
        self.assertIn("SERVER-SIDE EVIDENCE MODE", html)
        self.assertIn("Generative explanations are not enabled in this release", html)

    def test_chat_uses_scoped_assistant_endpoint_and_nonpersistent_session_token(self):
        source = (ROOT / "firelab_site" / "app.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/assistant/ask"', source)
        self.assertIn('"X-FireLab-Session": token', source)
        self.assertNotRegex(source, r"assistantSessionToken[^\n]*(?:localStorage|sessionStorage)")
        self.assertIn('dataScope === "selected-records"', source)
        self.assertIn("Backend activity", source)
        self.assertIn("NASA PSI-69 dataset", source)
        self.assertIn("noopener noreferrer", source)
        self.assertIn("Records bundle SHA-256", source)

    def test_provider_output_is_not_inserted_as_html(self):
        source = (ROOT / "firelab_site" / "app.js").read_text(encoding="utf-8")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
