import os
import re
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import usb_sync


class TestNormalizeName(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(usb_sync.normalize_name("HELLO"), "hello")

    def test_removes_special_chars(self):
        result = usb_sync.normalize_name("Hello, World! (2024)")
        self.assertEqual(result, "hello world 2024")

    def test_collapses_spaces(self):
        result = usb_sync.normalize_name("The   Hobbit")
        self.assertEqual(result, "the hobbit")

    def test_handles_empty(self):
        self.assertEqual(usb_sync.normalize_name(""), "")


class TestExtractCoverFromEpub(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_extracts_cover_jpg(self):
        epub_path = os.path.join(self.tmpdir.name, "test.epub")
        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("META-INF/container.xml", "<xml></xml>")
            zf.writestr("OEBPS/images/" * 20 + "cover.jpg", b"x" * 2000)
        result = usb_sync.extract_cover_from_epub(epub_path, self.tmpdir.name)
        self.assertIsNotNone(result)
        self.assertTrue(os.path.isfile(result))

    def test_extracts_cover_png(self):
        epub_path = os.path.join(self.tmpdir.name, "test.epub")
        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("META-INF/container.xml", "<xml></xml>")
            zf.writestr("OEBPS/Cover.PNG", b"x" * 2000)
        result = usb_sync.extract_cover_from_epub(epub_path, self.tmpdir.name)
        self.assertIsNotNone(result)
        self.assertTrue(os.path.isfile(result))

    def test_no_cover(self):
        epub_path = os.path.join(self.tmpdir.name, "test.epub")
        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("META-INF/container.xml", "<xml></xml>")
            zf.writestr("OEBPS/chapter1.xhtml", "<html></html>")
        result = usb_sync.extract_cover_from_epub(epub_path, self.tmpdir.name)
        self.assertIsNone(result)

    def test_invalid_epub(self):
        epub_path = os.path.join(self.tmpdir.name, "test.epub")
        with open(epub_path, "w") as f:
            f.write("not a zip file")
        result = usb_sync.extract_cover_from_epub(epub_path, self.tmpdir.name)
        self.assertIsNone(result)

    def test_missing_file(self):
        result = usb_sync.extract_cover_from_epub("/nonexistent/file.epub", self.tmpdir.name)
        self.assertIsNone(result)

    def test_small_image_rejected(self):
        epub_path = os.path.join(self.tmpdir.name, "test.epub")
        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("OEBPS/cover.jpg", b"x" * 500)
        result = usb_sync.extract_cover_from_epub(epub_path, self.tmpdir.name)
        self.assertIsNone(result)


class TestFilenameSanitize(unittest.TestCase):
    def test_removes_colon(self):
        result = re.sub(r'[\x00-\x1f\/:*?"<>|]', "_",
                        "Remembrance of Earth's Past: The Three-Body Problem.azw3")
        self.assertNotIn(":", result)
        self.assertIn("_", result)

    def test_removes_angle_brackets(self):
        result = re.sub(r'[\x00-\x1f\/:*?"<>|]', "_", "Book <Title>.azw3")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)

    def test_removes_question_mark(self):
        result = re.sub(r'[\x00-\x1f\/:*?"<>|]', "_", "Who Am I?.azw3")
        self.assertNotIn("?", result)


class TestMatchBooks(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.calibre_books = [
            {"id": 1, "title": "The Hobbit", "authors": "J.R.R. Tolkien"},
            {"id": 2, "title": "Dune", "authors": "Frank Herbert"},
            {"id": 3, "title": "1984", "authors": "George Orwell"},
        ]
        self.kindle_files = {
            "The Hobbit - J.R.R. Tolkien.azw3",
            "Dune - Frank Herbert.mobi",
        }
        self._orig_sent = usb_sync.SENT_FILE

    def tearDown(self):
        usb_sync.SENT_FILE = self._orig_sent
        self.tmpdir.cleanup()

    def test_matches_existing_books(self):
        sent_path = os.path.join(self.tmpdir.name, "sent_ids")
        usb_sync.SENT_FILE = sent_path
        with open(sent_path, "w") as f:
            f.write("")
        to_sync = usb_sync.match_books(self.calibre_books, self.kindle_files)
        ids = [b["id"] for b in to_sync]
        self.assertNotIn(1, ids)
        self.assertNotIn(2, ids)
        self.assertIn(3, ids)

    def test_no_new_books(self):
        sent_path = os.path.join(self.tmpdir.name, "sent_ids")
        usb_sync.SENT_FILE = sent_path
        with open(sent_path, "w") as f:
            f.write("")
        kindle_all = {
            "The Hobbit - J.R.R. Tolkien.azw3",
            "Dune - Frank Herbert.mobi",
            "1984 - George Orwell.epub",
        }
        with self.assertRaises(SystemExit) as ctx:
            usb_sync.match_books(self.calibre_books, kindle_all)
        self.assertEqual(ctx.exception.code, 0)

    def test_sent_ids_are_skipped(self):
        sent_path = os.path.join(self.tmpdir.name, "sent_ids")
        usb_sync.SENT_FILE = sent_path
        with open(sent_path, "w") as f:
            f.write("1\n")
        kindle_no_match = {"Some Other Book.azw3"}
        to_sync = usb_sync.match_books(self.calibre_books, kindle_no_match)
        ids = [b["id"] for b in to_sync]
        self.assertNotIn(1, ids)
        self.assertIn(2, ids)
        self.assertIn(3, ids)

    def test_force_ignores_sent_ids(self):
        sent_path = os.path.join(self.tmpdir.name, "sent_ids")
        usb_sync.SENT_FILE = sent_path
        with open(sent_path, "w") as f:
            f.write("1\n2\n3\n")
        kindle_empty = set()
        to_sync = usb_sync.match_books(self.calibre_books, kindle_empty, force=True)
        self.assertEqual(len(to_sync), 3)

    def test_force_ignores_kindle_match(self):
        sent_path = os.path.join(self.tmpdir.name, "sent_ids")
        usb_sync.SENT_FILE = sent_path
        with open(sent_path, "w") as f:
            f.write("")
        kindle_all = {
            "The Hobbit - J.R.R. Tolkien.azw3",
            "Dune - Frank Herbert.mobi",
            "1984 - George Orwell.epub",
        }
        to_sync = usb_sync.match_books(self.calibre_books, kindle_all, force=True)
        self.assertEqual(len(to_sync), 3)
