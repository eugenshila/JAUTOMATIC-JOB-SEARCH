"""Offscreen GUI boot test: the main window must construct, show and close.

Runs with ``QT_QPA_PLATFORM=offscreen`` so it works headless (CI, containers).
On machines without system Qt libraries, build the stub set first — see the
README's "Headless/CI note"::

    python tools/genstubs.py .stublibs
    LD_LIBRARY_PATH=.stublibs QT_QPA_PLATFORM=offscreen python -m unittest tests.test_gui_boot
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtWidgets import QApplication

    from jautomatic import APP_TITLE, __version__
    from jautomatic.ui.main_window import MainWindow, Worker

    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class GuiBootTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_boot_show_close(self):
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.show()
                self.app.processEvents()
                self.assertIn(APP_TITLE, window.windowTitle())
                self.assertIn(__version__, window.windowTitle())
                self.assertEqual(len(window.tabs), 5)
                self.assertTrue(window.status_label.text())
            finally:
                window.close()
                self.app.processEvents()
            self.assertTrue(window._closing)

    def test_boot_twice_restores_geometry(self):
        # Second boot in the same data dir must not crash (geometry restore
        # reads settings.json written by the first window's closeEvent).
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            first = MainWindow(data_dir=tmp)
            first.show()
            self.app.processEvents()
            first.close()
            self.app.processEvents()
            second = MainWindow(data_dir=tmp)
            try:
                second.show()
                self.app.processEvents()
            finally:
                second.close()
                self.app.processEvents()

    # ------------------------------------------------- geometry (fixed f/up 10)
    def test_geometry_is_stored_in_settings_json_and_restored(self):
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            first = MainWindow(data_dir=tmp)
            first.show()
            self.app.processEvents()
            first.resize(1200, 741)
            first.close()
            self.app.processEvents()

            saved = json.loads((Path(tmp) / "settings.json").read_text("utf-8"))
            blob = saved.get("window_geometry", "")
            self.assertTrue(blob, "closeEvent must persist geometry into settings.json")

            second = MainWindow(data_dir=tmp)
            try:
                second.show()
                self.app.processEvents()
                self.assertEqual(second.settings.window_geometry, blob)
                self.assertTrue(second._geometry_restored)
            finally:
                second.close()
                self.app.processEvents()

    def test_settings_form_save_does_not_drop_geometry(self):
        # The settings tab rebuilds AppSettings from its widgets; ctx.save_settings
        # must carry window_geometry over so a plain "Save" never resets placement.
        from jautomatic.models import AppSettings

        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.settings.window_geometry = "QUJD"  # pretend closeEvent wrote this
                rebuilt = AppSettings(data_dir=tmp, theme="daylight")
                window.save_settings(rebuilt)
                self.assertEqual(window.settings.window_geometry, "QUJD")
                on_disk = json.loads((Path(tmp) / "settings.json").read_text("utf-8"))
                self.assertEqual(on_disk["window_geometry"], "QUJD")
            finally:
                window.close()
                self.app.processEvents()

    # ------------------------------------------------- quit race (fixed f/up 11)
    def test_close_joins_running_workers_and_mutes_late_signals(self):
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            window.show()
            self.app.processEvents()
            completed: list[bool] = []
            handled: list[object] = []
            started = threading.Event()

            def slow() -> int:
                started.set()
                time.sleep(0.25)
                completed.append(True)
                return 42

            worker = window.run_task("slow task", slow, lambda result: handled.append(result))
            self.assertIsNotNone(worker)
            self.assertTrue(started.wait(timeout=2.0), "worker thread must start before close")
            window.close()          # must join the ~250ms task, not race past it
            self.app.processEvents()  # deliver any queued signals
            self.assertEqual(completed, [True], "a running worker is joined, never abandoned")
            self.assertEqual(handled, [], "late results must not touch the UI/workspace")
            with self.assertRaises(sqlite3.ProgrammingError):
                window.workspace.stats()  # closed — and nothing poked it during teardown

    def test_run_task_is_refused_once_closing(self):
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            window.show()
            self.app.processEvents()
            ran: list[int] = []
            window._closing = True  # simulate teardown already underway
            self.assertIsNone(window.run_task("late task", lambda: ran.append(1)))
            window._closing = False
            window.close()
            self.app.processEvents()
            self.assertEqual(ran, [])

    def test_queued_worker_starts_nothing_after_cancel(self):
        # A worker that only gets a CPU *after* the cancel flag is set must
        # refuse to run its fn (this is what pool.clear + the flag buy us when
        # the queue is busy at close time).
        ran: list[int] = []
        cancel = threading.Event()
        cancel.set()
        Worker(lambda: ran.append(1), cancel=cancel).run()
        self.assertEqual(ran, [])
        # ... and without the flag the same worker behaves normally.
        results: list[int] = []
        worker = Worker(lambda: 7)
        worker.signals.finished.connect(lambda value: results.append(value))
        worker.run()
        self.assertEqual(results, [7])


if __name__ == "__main__":
    unittest.main()
