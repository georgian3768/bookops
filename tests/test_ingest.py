import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import ingest


class TestMainArgs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmpdir.name, "config.json")
        config = {
            "incoming": os.path.join(self.tmpdir.name, "Incoming"),
            "manual_review": os.path.join(self.tmpdir.name, "Manual_Review"),
            "calibre_library": os.path.join(self.tmpdir.name, "Calibre_Library"),
            "convert_pdfs": False,
        }
        with open(self.config_path, "w") as f:
            json.dump(config, f)
        os.environ["_TEST_CONFIG"] = self.config_path
        self.orig_config = ingest.CONFIG_PATH
        ingest.CONFIG_PATH = self.config_path

    def tearDown(self):
        ingest.CONFIG_PATH = self.orig_config
        self.tmpdir.cleanup()

    def test_no_args_exit_1(self):
        test_args = ["ingest.py"]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as ctx:
                ingest.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_nonexistent_file_exit_1(self):
        test_args = ["ingest.py", "/nonexistent/file.epub"]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as ctx:
                ingest.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_unsupported_extension_exit_1(self):
        book_path = os.path.join(self.tmpdir.name, "test.txt")
        with open(book_path, "w") as f:
            f.write("hello")
        test_args = ["ingest.py", book_path]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as ctx:
                ingest.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_supported_format_calls_calibredb(self):
        incoming = os.path.join(self.tmpdir.name, "Incoming")
        os.makedirs(incoming, exist_ok=True)
        book_path = os.path.join(incoming, "test_book.epub")
        with open(book_path, "w") as f:
            f.write("fake epub")

        test_args = ["ingest.py", book_path]
        with patch.object(sys, "argv", test_args):
            with patch.object(ingest, "run_cmd", return_value=True) as mock_run:
                with patch.object(ingest, "_cleanup_source"):
                    with patch.object(ingest, "os") as mock_os:
                        mock_os.path.isdir = os.path.isdir
                        mock_os.path.isfile.return_value = True
                        mock_os.path.dirname.return_value = incoming
                        mock_os.path.abspath.return_value = book_path
                        mock_os.path.join = os.path.join
                        mock_os.path.splitext.return_value = ("test_book", ".epub")
                        mock_os.expanduser = lambda x: x
                        mock_os.makedirs = os.makedirs
                        mock_os.remove = MagicMock()

                        with self.assertRaises(SystemExit) as ctx:
                            ingest.main()
                        self.assertEqual(ctx.exception.code, 0)
                        mock_run.assert_called_once()
