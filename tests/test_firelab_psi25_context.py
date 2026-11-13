import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FireLabPsi25RouteContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "firelab_site/index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "firelab_site/app.js").read_text(encoding="utf-8")

    def test_sidebar_investigation_and_source_are_dynamic(self):
        for marker in (
            'id="active-investigation-link"',
            'id="active-investigation-name"',
            'id="active-investigation-description"',
            'id="sidebar-source-link"',
            'id="sidebar-source-label"',
        ):
            self.assertIn(marker, self.html)

    def test_psi25_context_identifies_bass_ii_and_nasa_source(self):
        self.assertIn('description: "BASS-II · microgravity combustion"', self.app)
        self.assertIn('NASA PSI-25 · Study version 4', self.app)
        self.assertIn('NASA PSI-25 · BASS-II', self.app)
        self.assertIn('https://psi.nasa.gov/physci/repo/data/investigations/PSI-25', self.app)

    def test_psi69_context_remains_the_default_for_other_pages(self):
        self.assertIn('description: "FLEX · droplet combustion"', self.app)
        self.assertIn('NASA PSI-69 · ${records.length} FLEX tests', self.app)
        self.assertIn('https://psi.nasa.gov/physci/repo/data/investigations/PSI-69', self.app)

    def test_page_router_updates_investigation_context(self):
        self.assertIn('updateInvestigationContext(target);', self.app)

    def test_psi69_dataset_render_cannot_leave_stale_context_on_psi25_route(self):
        header_write = '$("#header-data-state").textContent = bundleStatus;'
        refresh = 'updateInvestigationContext(location.hash.slice(1) || "ask");'
        self.assertIn(header_write + "\n  " + refresh, self.app)


if __name__ == "__main__":
    unittest.main()
