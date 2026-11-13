from contextlib import redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import patch

from tools.firelab import warm_paper_cache


class WarmPaperCacheCliTests(unittest.TestCase):
    def test_help_exits_before_runtime_or_network_setup(self):
        stdout = io.StringIO()
        with patch.object(warm_paper_cache, "FireLabPaths") as paths:
            with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
                warm_paper_cache.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage:", stdout.getvalue())
        paths.assert_not_called()

    def test_unknown_argument_is_rejected_before_runtime_setup(self):
        stderr = io.StringIO()
        with patch.object(warm_paper_cache, "FireLabPaths") as paths:
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                warm_paper_cache.main(["--unexpected"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments", stderr.getvalue())
        paths.assert_not_called()


if __name__ == "__main__":
    unittest.main()
