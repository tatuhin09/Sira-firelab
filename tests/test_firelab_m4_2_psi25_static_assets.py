from __future__ import annotations

import hashlib
import http.client
import json
from pathlib import Path
import threading
import unittest
from urllib.parse import quote

from firelab_service.http_app import STATIC_FILES, create_server

ROOT = Path(__file__).resolve().parents[1]
PSI25_ASSETS = (
    "psi25.js",
    "data/derived/psi25_bass_ii_v4/canonical_records.json",
    "data/derived/psi25_bass_ii_v4/quality_report.json",
    "data/derived/psi25_bass_ii_v4/canonical_manifest.json",
    "data/derived/psi25_bass_ii_v4/paired_analysis_v1/paired_measurement_analysis.json",
    "data/derived/psi25_bass_ii_v4/paired_analysis_v1/analysis_manifest.json",
    "data/derived/psi25_bass_ii_v4/findings_ranking_v1/findings_ranking.json",
    "data/derived/psi25_bass_ii_v4/findings_ranking_v1/findings_manifest.json",
    "data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/evidence_synthesis.json",
    "data/derived/psi25_bass_ii_v4/evidence_synthesis_v1/synthesis_manifest.json",
)


class FireLabM42Psi25StaticAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(ROOT, port=0, offline=True)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path: str):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            connection.request("GET", "/" + quote(path, safe="/"))
            response = connection.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            connection.close()

    def test_exact_psi25_assets_are_in_allowlist(self):
        for path in PSI25_ASSETS:
            with self.subTest(path=path):
                self.assertIn(path, STATIC_FILES)

    def test_all_psi25_browser_assets_are_served_byte_for_byte(self):
        for relative in PSI25_ASSETS:
            with self.subTest(path=relative):
                expected_path = ROOT / "firelab_site" / relative
                expected = expected_path.read_bytes()
                status, headers, body = self.request(relative)
                self.assertEqual(status, 200)
                self.assertEqual(body, expected)
                self.assertEqual(
                    hashlib.sha256(body).hexdigest(),
                    hashlib.sha256(expected).hexdigest(),
                )
                self.assertIn("Content-Security-Policy", headers)
                if relative.endswith(".json"):
                    parsed = json.loads(body.decode("utf-8"))
                    self.assertIsInstance(parsed, dict)

    def test_raw_psi25_source_assets_are_not_publicly_served(self):
        raw_source = (
            "data/source/PSI-25_BASS-II_v4_selected/"
            "PSI-25_Experimental table_BASS-II.csv"
        )
        status, _headers, _body = self.request(raw_source)
        self.assertEqual(status, 404)
        self.assertNotIn(raw_source, STATIC_FILES)

    def test_unlisted_derived_paths_are_not_publicly_served(self):
        for path in (
            "data/derived/psi25_bass_ii_v4/unlisted.json",
            "data/derived/psi25_bass_ii_v4/source/provenance.json",
            "data/derived/psi25_bass_ii_v4/../../source/secret.json",
        ):
            with self.subTest(path=path):
                status, _headers, _body = self.request(path)
                self.assertEqual(status, 404)

    def test_static_allowlist_does_not_enable_a_directory_prefix(self):
        self.assertFalse(any(path.endswith("/") for path in STATIC_FILES))
        self.assertNotIn("data/derived/psi25_bass_ii_v4/", STATIC_FILES)
        self.assertNotIn("data/source/", STATIC_FILES)

    def test_psi25_script_is_served_as_local_javascript(self):
        status, headers, body = self.request("psi25.js")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"(() =>") or b"DATA_ROOT" in body)
        content_type = headers.get("Content-Type", "").lower()
        self.assertTrue("javascript" in content_type or "text/plain" in content_type)

    def test_existing_psi69_static_assets_remain_served(self):
        for path in ("index.html", "app.js", "styles.css", "data/manifest.json", "data/records.json", "data/quality.json"):
            with self.subTest(path=path):
                status, _headers, _body = self.request(path)
                self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
