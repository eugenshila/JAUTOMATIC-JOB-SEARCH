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
                self.assertEqual(len(window.tabs), 7)
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

    def test_search_has_helpful_guidance_when_nothing_qualifies(self):
        from jautomatic.models import Profile

        def run(window, query):
            tab = window.tabs["search"]
            for name, box in tab.source_boxes.items():
                box.setChecked(name == "sample")
            tab.query.setText(query)
            tab.start_search(False)
            deadline = time.time() + 30
            while window._busy and time.time() < deadline:
                self.app.processEvents()
                time.sleep(0.05)
            return tab

        with tempfile.TemporaryDirectory(prefix="jautomatic-search-guidance-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.save_profile(Profile())
                window.settings.enabled_sources = ["sample"]
                window.save_settings(window.settings)
                low = run(window, "python")
                self.assertGreater(len(low.ranked), 0)
                self.assertEqual(window.workspace.applications(), [])
                self.assertIn("qualification bar", low.result_summary.text())
            finally:
                window.close()
                self.app.processEvents()

        with tempfile.TemporaryDirectory(prefix="jautomatic-search-guidance-empty-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.save_profile(Profile())
                window.settings.enabled_sources = ["sample"]
                window.save_settings(window.settings)
                nothing = run(window, "supply chain")
                self.assertEqual(nothing.ranked, [])
                self.assertIn("Adzuna", nothing.result_summary.text())
            finally:
                window.close()
                self.app.processEvents()

    def test_pdf_export_writes_a_valid_reader_pdf(self):
        from jautomatic.services.cv_generator import export
        markdown = "# Alex Doe\n\n- Senior Python Engineer\n- **Data platforms**\n"
        with tempfile.TemporaryDirectory(prefix="jautomatic-pdf-") as tmp:
            path = export(markdown, Path(tmp) / "out.pdf", fmt="pdf", title="CV – Alex Doe")
            self.assertEqual(path.suffix, ".pdf")
            head = path.read_bytes()[:5]
            self.assertEqual(head, b"%PDF-")
            self.assertGreater(path.stat().st_size, 2000)

    def test_search_done_handles_the_qualified_result(self):
        from jautomatic.models import SAMPLE_PROFILE, Profile
        with tempfile.TemporaryDirectory(prefix="jautomatic-search-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.save_profile(Profile.from_dict(SAMPLE_PROFILE))
                window.settings.enabled_sources = ["sample"]
                window.save_settings(window.settings)
                tab = window.tabs["search"]
                for name, box in tab.source_boxes.items():
                    box.setChecked(name == "sample")
                tab.query.setText("python")
                tab.start_search(False)
                deadline = time.time() + 30
                while window._busy and time.time() < deadline:
                    self.app.processEvents()
                    time.sleep(0.05)
                self.assertFalse(window._busy)
                self.assertGreater(len(tab.ranked), 0)
                self.assertGreater(len(window.workspace.applications()), 0)
            finally:
                window.close()
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

    def test_insights_tab_refreshes_with_real_data(self):
        from datetime import date

        from jautomatic.models import ApplicationStatus, JobPosting

        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.show()
                self.app.processEvents()
                job = JobPosting(
                    source="sample", title="Senior Python Engineer", company="Northwind",
                    location="Berlin", remote=True, url="https://example.com/jobs/python",
                    description="FastAPI services, PostgreSQL modelling, Docker, pytest.",
                    tags=["python", "fastapi", "postgresql", "docker", "pytest"],
                    posted_at=date.today().isoformat())
                window.pipeline.import_jobs([job])
                application = window.pipeline.ensure_application(job)
                window.pipeline.set_status(application, ApplicationStatus.SENT)
                window.pipeline.set_status(application, ApplicationStatus.INTERVIEW, "booked")
                window.go_to("insights")
                self.app.processEvents()
                tab = window.tabs["insights"]
                self.assertNotEqual(tab.stat_cards["response"].value_label.text(), "—")
                self.assertEqual(tab.stat_cards["interview"].value_label.text(), "100.0%")
                self.assertEqual(tab.market_table.rowCount(), 5)
                self.assertGreater(tab.reply_table.rowCount(), 0)
                self.assertGreater(tab.source_rows.count(), 0)
            finally:
                window.close()
                self.app.processEvents()

    def _wait_until(self, predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        self.app.processEvents()
        return predicate()

    def test_import_from_url_tracks_via_job_search_tab(self):
        from unittest import mock

        from jautomatic.models import JobPosting

        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.show()
                self.app.processEvents()
                window.go_to("search")
                self.app.processEvents()
                tab = window.tabs["search"]
                posting = JobPosting(
                    source="manual", title="Pastry Engineer", company="Patisserie",
                    location="Lyon", remote=False, salary_min=40000, salary_max=50000,
                    currency="EUR", url="https://patisserie.example/jobs/1",
                    description="Make croissants. Layer butter like you mean it.",
                    tags=["pastry", "butter"], posted_at="2026-09-01")
                with mock.patch("jautomatic.services.job_scraper.posting_from_url",
                                return_value=posting):
                    tab.url_input.setText("patisserie.example/jobs/1")
                    tab.import_url()
                    self.assertTrue(
                        self._wait_until(lambda: len(window.workspace.applications()) == 1),
                        "the background import must store the posting")
                    self.app.processEvents()
                apps = window.workspace.applications()
                self.assertEqual(len(apps), 1)
                stored = window.workspace.get_job(apps[0].job_id)
                self.assertEqual(stored.title, "Pastry Engineer")
                self.assertEqual(stored.source, "manual")
                # the app auto-navigates to applications after importing
                self.assertEqual(window._active_key, "applications")
            finally:
                window.close()
                self.app.processEvents()

    def test_auto_refresh_timer_follows_settings(self):
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.show()
                self.app.processEvents()
                self.assertFalse(window._refresh_timer.isActive())
                settings = window.settings
                settings.auto_refresh_enabled = True
                settings.auto_refresh_minutes = 5
                window.save_settings(settings)
                self.assertTrue(window._refresh_timer.isActive())
                self.assertEqual(window._refresh_timer.interval(), 5 * 60_000)
                settings.auto_refresh_enabled = False
                window.save_settings(settings)
                self.assertFalse(window._refresh_timer.isActive())
            finally:
                window.close()
                self.app.processEvents()

    def test_background_refresh_reports_fresh_postings(self):
        import types
        from unittest import mock

        from jautomatic.models import JobPosting
        from jautomatic.services.job_scraper import JobScraper

        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.show()
                self.app.processEvents()
                posting = JobPosting(
                    source="sample", title="Fresh Role", company="Fresher",
                    location="Remote", remote=True, salary_min=50000, salary_max=70000,
                    currency="USD", url="https://example.com/fresh", description="New band",
                    tags=["python"], posted_at="2026-09-16")
                outcome = types.SimpleNamespace(jobs=[posting], errors=[])
                window.settings.notify_new_matches = False
                with mock.patch.object(JobScraper, "search", return_value=outcome):
                    window.background_refresh()
                    self.assertTrue(
                        self._wait_until(lambda: len(window._background_notes) >= 1),
                        "the background refresh must report its outcome")
                self.assertIn("1 new", window._background_notes[0])
                self.assertNotIn("New roles found", window._background_notes[0])
                # only AFTER the first batch the desktop alert is requested again
                window.settings.notify_new_matches = True
                with mock.patch.object(JobScraper, "search", return_value=outcome):
                    window.background_refresh()
                    self.assertTrue(
                        self._wait_until(lambda: any("New roles found" in note
                                                     for note in window._background_notes)),
                        "the new-match alert must fire")
                self.assertEqual(window.tabs["search"].outcome.jobs, [posting])
            finally:
                window.close()
                self.app.processEvents()

    def test_insights_tab_shows_empty_state_gracefully(self):
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.go_to("insights")
                self.app.processEvents()
                tab = window.tabs["insights"]
                self.assertEqual(tab.market_table.rowCount(), 0)
                self.assertEqual(tab.reply_table.rowCount(), 0)
                self.assertEqual(tab.stat_cards["reply"].value_label.text(), "—")
            finally:
                window.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
