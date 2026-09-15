"""Runtime helpers: frozen detection, crash reports, platform no-ops."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

from jautomatic import runtime


class TestFrozenDetection(unittest.TestCase):
    def test_not_frozen_under_pytest_or_unittest(self):
        self.assertFalse(runtime.is_frozen())
        self.assertFalse(getattr(sys, "frozen", False))

    def test_frozen_flag_is_respected(self):
        original = getattr(sys, "frozen", None)
        try:
            sys.frozen = True
            self.assertTrue(runtime.is_frozen())
        finally:
            if original is None:
                del sys.frozen
            else:
                sys.frozen = original

    def test_bundle_dir_falls_back_to_repo_root(self):
        self.assertTrue((runtime.bundle_dir() / "jautomatic").is_dir())
        self.assertEqual(runtime.resource_path("jautomatic", "models.py"),
                         runtime.bundle_dir() / "jautomatic" / "models.py")

    def test_describe_shape(self):
        info = runtime.describe()
        for key in ("app", "version", "frozen", "python", "platform", "executable"):
            self.assertIn(key, info)
        self.assertIsInstance(info["frozen"], bool)


class TestCrashReports(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.environ.get("JAUTOMATIC_DATA_DIR") or "")
        import tempfile
        self.dir = Path(tempfile.mkdtemp(prefix="jautomatic-runtime-test-"))
        os.environ["JAUTOMATIC_DATA_DIR"] = str(self.dir)

    def tearDown(self):
        if self.tmp:
            os.environ["JAUTOMATIC_DATA_DIR"] = str(self.tmp)
        else:
            os.environ.pop("JAUTOMATIC_DATA_DIR", None)

    def test_log_dir_lives_in_the_data_dir(self):
        self.assertEqual(runtime.log_dir(), self.dir / "logs")

    def test_write_and_read_a_crash_report(self):
        path = runtime.write_crash_report("Traceback: boom")
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("Traceback: boom", text)
        self.assertIn("JAUTOMATIC crash report", text)

    def test_reports_are_pruned(self):
        when = datetime(2026, 9, 15, 12, 0, 0)
        for minute in range(runtime.MAX_CRASH_LOGS + 3):
            path = runtime.crash_log_path(self.dir, when=when.replace(minute=minute))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("old", encoding="utf-8")
        runtime.write_crash_report("newest", self.dir)
        kept = sorted((self.dir / "logs").glob("crash-*.log"))
        self.assertLessEqual(len(kept), runtime.MAX_CRASH_LOGS)

    def test_write_crash_report_survives_unwritable_dirs(self):
        blocker = self.dir / "blocker"
        blocker.write_text("I am a file, not a folder", encoding="utf-8")
        self.assertIsNone(runtime.write_crash_report("x", blocker))


class TestPlatformNoOps(unittest.TestCase):
    def test_set_app_user_model_id_is_a_noop_off_windows(self):
        if runtime.is_windows():
            self.skipTest("windows machine")
        self.assertFalse(runtime.set_app_user_model_id())

    def test_freeze_support_never_raises(self):
        runtime.freeze_support()


if __name__ == "__main__":
    unittest.main()
