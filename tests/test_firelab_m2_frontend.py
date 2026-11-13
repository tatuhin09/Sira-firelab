from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PaperPanelFrontendTests(unittest.TestCase):
    def test_panel_is_loaded_as_deferred_local_script(self):
        html = (ROOT / "firelab_site" / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<script\s+src="papers\.js"\s+defer></script>')
        self.assertIn('id="paper-search-form"', html)
        self.assertIn('id="paper-search-notice"', html)

    def test_provider_content_has_no_unsafe_html_sink(self):
        source = (ROOT / "firelab_site" / "papers.js").read_text(encoding="utf-8")
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("node.textContent = text", source)
        self.assertIn("resultsNode.replaceChildren()", source)

    def test_session_token_is_not_persisted_in_browser_storage(self):
        source = (ROOT / "firelab_site" / "papers.js").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\b(localStorage|sessionStorage)\b")
        self.assertIn('"X-FireLab-Session": sessionToken', source)

    def test_external_links_are_scheme_checked_and_opened_safely(self):
        source = (ROOT / "firelab_site" / "papers.js").read_text(encoding="utf-8")
        self.assertIn('["http:", "https:"]', source)
        self.assertIn('link.rel = "noopener noreferrer"', source)
        self.assertIn('link.target = "_blank"', source)

    def test_doi_label_uses_doi_resolver_and_validates_doi_shape(self):
        source = (ROOT / "firelab_site" / "papers.js").read_text(encoding="utf-8")
        self.assertIn(r"/^10\.\d{4,9}\/\S+$/i.test(doi)", source)
        self.assertIn('safeExternalUrl(`https://doi.org/${encodedDoi}`)', source)
        self.assertIn('link.textContent = doiUrl ? `DOI: ${doi}` : "Open paper record";', source)

    def test_offline_notice_is_explicit_and_transcript_is_not_sent(self):
        source = (ROOT / "firelab_site" / "papers.js").read_text(encoding="utf-8")
        self.assertIn("results come only from this machine's local cache", source)
        self.assertIn("Retrieved sources: ${sourceCount}", source)
        self.assertIn("Provider(s): ${providers.join", source)
        self.assertIn('body: JSON.stringify({ query })', source)
        self.assertNotIn("conversation", source.casefold())

    def test_existing_app_and_paper_panel_have_no_external_script_or_stylesheet(self):
        html = (ROOT / "firelab_site" / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r'<script[^>]+src="https?://')
        self.assertNotRegex(html, r'<link[^>]+href="https?://')


if __name__ == "__main__":
    unittest.main()
