import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import doctor


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.valid_config = {
            "incoming": "~/Books/Incoming",
            "manual_review": "~/Books/Manual_Review",
            "calibre_library": "~/Calibre Library",
            "gdrive_remote_path": "gdrive:Incoming",
            "kindle_email": "test@kindle.com",
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_loads_valid_json(self):
        path = os.path.join(self.tmpdir.name, "config.json")
        with open(path, "w") as f:
            json.dump(self.valid_config, f)
        result = doctor.load_config(path)
        self.assertEqual(result["kindle_email"], "test@kindle.com")

    def test_missing_file_raises_exit_2(self):
        path = os.path.join(self.tmpdir.name, "nonexistent.json")
        with self.assertRaises(SystemExit) as ctx:
            doctor.load_config(path)
        self.assertEqual(ctx.exception.code, 2)

    def test_malformed_json_raises_exit_2(self):
        path = os.path.join(self.tmpdir.name, "bad.json")
        with open(path, "w") as f:
            f.write("not json")
        with self.assertRaises(SystemExit) as ctx:
            doctor.load_config(path)
        self.assertEqual(ctx.exception.code, 2)


class TestCheckBinaries(unittest.TestCase):
    def setUp(self):
        self.config = {
            "incoming": "~/Books/Incoming",
            "manual_review": "~/Books/Manual_Review",
            "calibre_library": "~/Calibre Library",
        }

    def test_all_found(self):
        with patch.object(shutil, "which", return_value="/usr/bin/msmtp"):
            result = doctor.check_binaries(self.config)
            self.assertTrue(result)

    def test_missing_email_is_optional(self):
        def fake_which(cmd):
            return None if cmd == "msmtp" else "/usr/bin/" + cmd
        with patch.object(shutil, "which", side_effect=fake_which):
            result = doctor.check_binaries(self.config)
            self.assertTrue(result)

    def test_some_required_missing(self):
        def fake_which(cmd):
            return "/usr/bin/" + cmd if cmd == "calibredb" else None
        with patch.object(shutil, "which", side_effect=fake_which):
            result = doctor.check_binaries(self.config)
            self.assertFalse(result)


class TestCheckDirectories(unittest.TestCase):
    def setUp(self):
        self.config = {
            "incoming": "/tmp/bookops_test_incoming",
            "manual_review": "/tmp/bookops_test_manual",
            "calibre_library": "/tmp/bookops_test_library",
        }
        for d in self.config.values():
            os.makedirs(d, exist_ok=True)
        self.orig_dir = doctor.SCRIPT_DIR

    def tearDown(self):
        for d in self.config.values():
            try:
                os.rmdir(d)
            except OSError:
                pass
        doctor.SCRIPT_DIR = self.orig_dir

    def test_all_exist(self):
        doctor.SCRIPT_DIR = "/tmp"
        msmtp_path = os.path.join(doctor.SCRIPT_DIR, "msmtprc.local")
        with open(msmtp_path, "w") as f:
            f.write("dummy")
        try:
            result = doctor.check_directories(self.config)
            self.assertTrue(result)
        finally:
            try:
                os.remove(msmtp_path)
            except OSError:
                pass

    def test_missing_directory(self):
        doctor.SCRIPT_DIR = "/tmp"
        config_bad = dict(self.config)
        config_bad["incoming"] = "/tmp/nonexistent_incoming_xyz"
        result = doctor.check_directories(config_bad)
        self.assertFalse(result)

    def test_msmtprc_missing_is_optional(self):
        doctor.SCRIPT_DIR = tempfile.mkdtemp()
        result = doctor.check_directories(self.config)
        self.assertTrue(result)


class TestCheckRemote(unittest.TestCase):
    def setUp(self):
        self.config = {"gdrive_remote_path": "gdrive:Incoming"}

    def test_remote_reachable(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with patch.object(subprocess, "run", return_value=mock_proc):
            result = doctor.check_remote(self.config)
            self.assertTrue(result)

    def test_remote_unreachable(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "error"
        with patch.object(subprocess, "run", return_value=mock_proc):
            result = doctor.check_remote(self.config)
            self.assertFalse(result)

    def test_remote_not_configured(self):
        result = doctor.check_remote({})
        self.assertFalse(result)


class TestMain(unittest.TestCase):
    @patch.object(doctor, "load_config")
    @patch.object(doctor, "check_binaries", return_value=True)
    @patch.object(doctor, "check_directories", return_value=True)
    @patch.object(doctor, "check_remote", return_value=True)
    def test_all_pass_exit_0(self, *mocks):
        with self.assertRaises(SystemExit) as ctx:
            doctor.main()
        self.assertEqual(ctx.exception.code, 0)

    @patch.object(doctor, "load_config")
    @patch.object(doctor, "check_binaries", return_value=False)
    @patch.object(doctor, "check_directories", return_value=True)
    @patch.object(doctor, "check_remote", return_value=True)
    def test_binaries_fail_exit_3(self, *mocks):
        with self.assertRaises(SystemExit) as ctx:
            doctor.main()
        self.assertEqual(ctx.exception.code, 3)
