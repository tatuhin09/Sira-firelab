from http.server import ThreadingHTTPServer
from pathlib import Path
import http.client
import tempfile
import threading
import unittest

from tools.firelab.server import ReadOnlyHandler


class StaticPreviewSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "site"
        self.root.mkdir()
        (self.root / "index.html").write_text("<h1>FireLab</h1>")
        backup = self.root / "data_backup_20261030_041648"
        backup.mkdir()
        (backup / "records.json").write_text("[]")
        self.outside = Path(self.temp.name) / "private.json"
        self.outside.write_text("{\\\"private\\\":true}")
        (self.root / "secret.json").symlink_to(self.outside)
        handler = lambda *args, **kwargs: ReadOnlyHandler(*args, directory=self.root, **kwargs)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def request(self, method, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        result = (response.status, body)
        connection.close()
        return result

    def test_backup_directory_is_not_served_by_old_preview(self):
        self.assertEqual(self.request("GET", "/data_backup_20261030_041648/records.json")[0], 404)

    def test_symlink_escape_is_not_served_by_old_preview(self):
        self.assertEqual(self.request("GET", "/secret.json")[0], 404)
        self.assertEqual(self.outside.read_text(), "{\\\"private\\\":true}")

    def test_normal_static_file_remains_available(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"FireLab", body)

    def test_write_method_remains_rejected(self):
        self.assertEqual(self.request("POST", "/")[0], 405)


if __name__ == "__main__":
    unittest.main()
