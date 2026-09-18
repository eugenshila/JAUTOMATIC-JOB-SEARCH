"""Search visibility, qualification boundaries and saved-result regressions."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from jautomatic.models import SAMPLE_PROFILE, AppSettings, JobPosting, Profile
from jautomatic.services.application_pipeline import ApplicationPipeline, MatchResult
from jautomatic.services.job_scraper import SearchOutcome
from jautomatic.ui.job_search_tab import JobSearchTab
from jautomatic.ui.theme import apply_theme
from tests.support import WorkspaceTestCase


class SearchInterfaceTest(WorkspaceTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app, "blackgreen")

    def setUp(self):
        super().setUp()
        settings = AppSettings()
        self.ctx = SimpleNamespace(
            settings=settings, profile=Profile(), workspace=self.workspace,
            pipeline=ApplicationPipeline(self.workspace, settings),
            add_header_action=Mock(), save_settings=self.workspace.save_settings,
            notify=Mock(),
        )
        self.tab = JobSearchTab(self.ctx)
        self.addCleanup(self.tab.close)

    def test_all_results_visible_and_70_percent_is_inclusive(self):
        self.tab.ranked = [
            (JobPosting(title=f"Role {score}", company="Example"), MatchResult(score=score))
            for score in (69, 70, 85)
        ]
        self.tab._fill_table()
        self.assertEqual(self.tab.table.rowCount(), 3)
        self.assertEqual(self.tab.table.item(0, 0).text(), "85%")
        self.assertEqual(self.tab.table.item(1, 7).text(), "Eligible")
        self.assertEqual(self.tab.table.item(2, 7).text(), "Below target")
        self.tab.eligible_only.setChecked(True)
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.tab.eligible_only.setChecked(False)
        self.assertEqual(self.tab.table.rowCount(), 3)

    def test_empty_filter_clears_previous_details(self):
        self.tab.ranked = [(JobPosting(title="Below target"), MatchResult(score=69))]
        self.tab._fill_table()
        self.assertIn("Below target", self.tab.detail_title.text())
        self.tab.eligible_only.setChecked(True)
        self.assertEqual(self.tab.table.rowCount(), 0)
        self.assertEqual(self.tab.detail_title.text(), "Select a posting")
        self.assertEqual(self.tab.description.toPlainText(), "")
        self.assertIn("Turn off", self.tab.empty_results.text())

    def test_search_results_survive_reopening_without_queuing(self):
        job = JobPosting(title="Python engineer", company="Example", tags=["python"])
        self.tab.show_result_outcome(SearchOutcome(jobs=[job]))
        self.assertEqual(self.workspace.applications(), [])
        self.ctx.settings = self.workspace.load_settings()
        reopened = JobSearchTab(self.ctx)
        try:
            reopened.refresh()
            self.assertEqual(reopened.table.rowCount(), 1)
            self.assertEqual(reopened.ranked[0][0].job_id, job.job_id)
        finally:
            reopened.close()

    def test_profile_changes_rescore_visible_results(self):
        job = JobPosting(title="Senior Python Engineer", company="Example",
                         tags=["python", "sql", "docker"], remote=True)
        self.tab.show_result_outcome(SearchOutcome(jobs=[job]))
        before = self.tab.ranked[0][1].score
        self.ctx.profile = Profile.from_dict(SAMPLE_PROFILE)
        self.tab.refresh()
        self.assertGreater(self.tab.ranked[0][1].score, before)

    def test_prepare_top_does_not_fall_back_to_unqualified_jobs(self):
        self.tab.ranked = [(JobPosting(title="Unqualified"), MatchResult(score=69))]
        self.tab._prepare_jobs = Mock()
        self.tab._prepare_top(3)
        self.tab._prepare_jobs.assert_not_called()
        self.ctx.notify.assert_called_once()

    def test_empty_search_replaces_saved_results(self):
        self.tab.show_result_outcome(SearchOutcome(jobs=[JobPosting(title="Old")]))
        self.tab.show_result_outcome(SearchOutcome(jobs=[]))
        self.tab.refresh()
        self.assertEqual(self.tab.table.rowCount(), 0)
        self.assertEqual(self.workspace.load_settings().last_search_job_ids, [])

    def test_regional_preset_persists_location_and_enables_local_feeds(self):
        self.tab.remote_only.setChecked(True)
        self.tab.use_regional_search()
        settings = self.workspace.load_settings()
        self.assertEqual(settings.last_search_location, "Africa; UAE")
        self.assertEqual(settings.last_search_query, "logistics")
        self.assertFalse(settings.remote_only)
        self.assertTrue(self.tab.source_boxes["myjobmag_ke"].isChecked())
        self.assertIn("jobweb_ug", settings.enabled_sources)
