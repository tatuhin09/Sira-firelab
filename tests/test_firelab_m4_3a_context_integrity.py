from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "firelab_site" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "firelab_site" / "index.html").read_text(encoding="utf-8")


class FireLabM43AContextIntegrityTests(unittest.TestCase):
    def test_auto_context_is_explicit_and_not_mislabelled_as_psi69(self):
        block = APP.split("const INVESTIGATION_CONTEXTS = {", 1)[1].split("  psi69:", 1)[0]
        self.assertIn('name: "Automatic routing"', block)
        self.assertIn('footerLabel: "NASA PSI data"', block)
        self.assertIn('bundleCount: () => "2 approved NASA investigations"', block)

    def test_dedicated_explorer_pages_pin_their_own_investigation(self):
        self.assertIn('if (page === "psi25") return "psi25-bass-ii-v4";', APP)
        self.assertIn('if (page === "data") return "psi69-flex-v5";', APP)

    def test_ask_workspace_uses_active_conversation_before_selector(self):
        start = APP.index("function currentAskInvestigationId()")
        end = APP.index("function workspaceInvestigationId", start)
        helper = APP[start:end]
        self.assertIn("const active = conversations.find", helper)
        self.assertLess(helper.index("if (active)"), helper.index('$("#investigation-select")'))

    def test_context_sync_updates_ask_rail_and_workspace(self):
        start = APP.index("function syncInvestigationContext(")
        end = APP.index("function updateInvestigationContext", start)
        helper = APP[start:end]
        self.assertIn("updateInvestigationContext(page)", helper)
        context_start = APP.index("function updateInvestigationContext(page)")
        context_end = APP.index("function setPage(page)", context_start)
        context = APP[context_start:context_end]
        self.assertIn("updateAskEvidenceContext(currentAskInvestigationId())", context)
        self.assertIn("workspaceInvestigationId(page)", context)

    def test_restored_conversation_renders_through_context_sync(self):
        start = APP.index("function renderActiveConversation()")
        end = APP.index("function startNewConversation()", start)
        self.assertIn("syncInvestigationContext(currentWorkspacePage())", APP[start:end])

    def test_navigation_uses_shared_context_sync(self):
        start = APP.index("function setPage(page)")
        end = APP.index("function closeSidebar()", start)
        self.assertIn("updateInvestigationContext(target)", APP[start:end])

    def test_new_conversation_resets_selector_to_auto(self):
        start = APP.index("function startNewConversation()")
        end = APP.index("function initializeChatHistory()", start)
        helper = APP[start:end]
        self.assertIn('selector.value = "auto"', helper)
        self.assertLess(helper.index('selector.value = "auto"'), helper.index("renderActiveConversation()"))

    def test_auto_route_resolution_updates_saved_conversation_scope(self):
        self.assertIn('target.investigationId = resolvedInvestigationId', APP)
        self.assertIn("if (activeConversationId === targetConversationId) renderActiveConversation()", APP)

    def test_sidebar_context_does_not_mutate_conversation_scope(self):
        start = APP.index("function updateInvestigationContext(page)")
        end = APP.index("function setPage(page)", start)
        helper = APP[start:end]
        self.assertIn("workspaceInvestigationId(page)", helper)
        self.assertNotIn(".investigationId =", helper)

    def test_footer_investigation_label_is_dynamic(self):
        self.assertIn('id="footer-investigation-label"', HTML)
        start = APP.index("function updateInvestigationContext(page)")
        end = APP.index("function setPage(page)", start)
        self.assertIn('$("#footer-investigation-label")', APP[start:end])
        self.assertIn("context.footerLabel", APP[start:end])

    def test_psi25_explorer_footer_and_sidebar_use_psi25_context(self):
        start = APP.index("const INVESTIGATION_CONTEXTS = {")
        end = APP.index("function currentWorkspacePage()", start)
        contexts = APP[start:end]
        psi25 = contexts.split("  psi25:", 1)[1]
        self.assertIn('footerLabel: "NASA PSI-25"', psi25)
        self.assertIn('name: "NASA PSI-25"', psi25)

    def test_psi69_explorer_footer_and_sidebar_use_psi69_context(self):
        start = APP.index("const INVESTIGATION_CONTEXTS = {")
        end = APP.index("function currentWorkspacePage()", start)
        contexts = APP[start:end]
        psi69 = contexts.split("  psi69:", 1)[1].split("  psi25:", 1)[0]
        self.assertIn('footerLabel: "NASA PSI-69"', psi69)
        self.assertIn('name: "NASA PSI-69"', psi69)

    def test_context_helpers_keep_the_registered_selector_allowlist(self):
        self.assertIn('Object.freeze(["auto", "psi69-flex-v5", "psi25-bass-ii-v4"])', APP)
        self.assertIn("normalizeInvestigationId($(\"#investigation-select\")?.value, \"auto\")", APP)

    def test_footer_does_not_claim_psi69_on_every_page(self):
        footer = HTML.split('<footer class="app-footer">', 1)[1].split("</footer>", 1)[0]
        self.assertNotIn("NASA PSI-69", footer)
        self.assertIn('id="footer-investigation-label"', footer)


if __name__ == "__main__":
    unittest.main()
