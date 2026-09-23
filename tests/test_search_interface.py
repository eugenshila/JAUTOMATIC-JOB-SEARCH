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

    def test_all_results_visible_and_80_percent_is_inclusive(self):
        self.tab.ranked = [
            (JobPosting(title=f"Role {score}", company="Example"), MatchResult(score=score))
            for score in (79, 80, 85)
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

    def test_gulf_preset_selects_the_key_free_gulf_sources(self):
        self.tab.use_gulf_search()
        settings = self.workspace.load_settings()
        self.assertEqual(settings.last_search_location, "Gulf; UAE")
        self.assertEqual(settings.last_search_query, "logistics")
        for name in ("jobicy", "workingnomads", "company_boards", "himalayas", "uae_ai"):
            self.assertTrue(self.tab.source_boxes[name].isChecked(), name)
        self.assertNotIn("myjobmag_ke", settings.enabled_sources)
        self.assertFalse(self.tab.remote_only.isChecked())

    def test_browser_website_dropdown_follows_the_board(self):
        regions = lambda combo: [combo.itemText(i) for i in range(combo.count())]  # noqa: E731
        self.assertIn("UAE", regions(self.tab.browser_region))
        self.tab.browser_board.setCurrentText("Bayt")
        self.assertIn("Saudi Arabia", regions(self.tab.browser_region))
        self.assertNotIn("Kenya", regions(self.tab.browser_region))
        self.tab.browser_board.setCurrentText("Jobberman")
        self.assertIn("Ghana", regions(self.tab.browser_region))
        self.assertNotIn("Qatar", regions(self.tab.browser_region))

    def test_open_website_uses_the_selected_board_and_region(self):
        from unittest.mock import patch as qt_patch
        self.tab.query.setText("driver")
        self.tab.browser_board.setCurrentText("Bayt")
        self.tab.browser_region.setCurrentText("Saudi Arabia")
        with qt_patch("jautomatic.ui.job_search_tab.th.open_in_browser",
                      return_value=True) as opener:
            self.tab.open_regional_website()
        url = opener.call_args[0][0]
        self.assertEqual(url, "https://www.bayt.com/en/saudi-arabia/jobs/driver-jobs/")
        self.assertIn("Bayt", self.ctx.notify.call_args[0][0])


    def test_move_only_checked_results(self):
        from PySide6.QtCore import Qt
        self.ctx.tabs = {'applications': Mock(), 'dashboard': Mock()}
        jobs = [JobPosting(title=title, company='Example') for title in ('First', 'Second')]
        self.tab.show_result_outcome(SearchOutcome(jobs=jobs))
        self.assertEqual(self.workspace.applications(), [])
        self.tab.table.item(1, 0).setCheckState(Qt.Checked)
        chosen = self.tab._job_for_row(1).job_id
        self.tab._move_checked_to_queue()
        self.assertEqual([a.job_id for a in self.workspace.applications()], [chosen])
        self.tab._move_checked_to_queue()
        self.assertEqual(len(self.workspace.applications()), 1)

    def test_search_does_not_queue_even_with_old_auto_setting(self):
        from threading import Event
        self.ctx.settings.auto_track_qualified = True
        self.ctx.cancel_event = Event()
        self.ctx.tabs = {'applications': Mock(), 'dashboard': Mock()}
        self.ctx.update_meta = Mock()
        self.ctx.run_task = lambda title, work, done, *args: done(work())
        self.ctx.pipeline.scraper.search = Mock(return_value=SearchOutcome(jobs=[
            JobPosting(title='IT support', company='Example')]))
        self.tab.query.setText('IT support')
        self.tab.start_search(True)
        self.assertEqual(self.workspace.applications(), [])
        self.assertEqual(self.workspace.job_count(), 1)

    def test_clear_checked_jobs_hides_them_after_refresh_and_repeat_search(self):
        from PySide6.QtCore import Qt
        self.ctx.tabs = {'applications': Mock(), 'dashboard': Mock()}
        jobs=[JobPosting(title=title,company='Example',url='https://example.org/'+title) for title in ('First','Second','Third')]
        self.tab.show_result_outcome(SearchOutcome(jobs=jobs))
        self.tab.table.item(1,0).setCheckState(Qt.Checked)
        self.tab.table.item(2,0).setCheckState(Qt.Checked)
        self.tab._clear_selected()
        self.assertEqual(self.tab.table.rowCount(),1)
        self.tab.refresh(); self.assertEqual(self.tab.table.rowCount(),1)
        self.tab.show_result_outcome(SearchOutcome(jobs=jobs))
        self.assertEqual(self.tab.table.rowCount(),1)
        self.ctx.settings=self.workspace.load_settings()
        reopened=JobSearchTab(self.ctx)
        try:
            reopened.refresh(); self.assertEqual(reopened.table.rowCount(),1)
        finally: reopened.close()

    def test_clear_highlighted_sent_job_keeps_sent_history(self):
        from jautomatic.models import ApplicationStatus
        self.ctx.tabs = {'applications': Mock(), 'dashboard': Mock()}
        job=JobPosting(title='Already sent',company='Example')
        app=self.ctx.pipeline.ensure_application(job)
        self.ctx.pipeline.set_status(app,ApplicationStatus.SENT)
        self.tab.show_result_outcome(SearchOutcome(jobs=[job]))
        self.tab._clear_selected()
        self.assertEqual(self.tab.table.rowCount(),0)
        self.assertEqual(self.tab.description.toPlainText(),'')
        self.assertEqual(self.workspace.get_application(app.application_id).status_enum,ApplicationStatus.SENT)

    def test_select_all_only_checks_visible_results_and_can_deselect(self):
        from PySide6.QtCore import Qt
        self.tab.ranked=[(JobPosting(title=str(score)),MatchResult(score=score)) for score in (60,80,90)]
        self.tab.eligible_only.setChecked(True)
        self.tab._fill_table()
        self.tab._set_all_checked(True)
        self.assertEqual(self.tab.table.rowCount(),2)
        self.assertTrue(all(self.tab.table.item(row,0).checkState()==Qt.Checked for row in range(2)))
        self.tab._set_all_checked(False)
        self.assertTrue(all(self.tab.table.item(row,0).checkState()==Qt.Unchecked for row in range(2)))

    def test_show_cleared_recovers_results_without_requeuing(self):
        from jautomatic.models import ApplicationStatus
        self.ctx.tabs={'applications':Mock(),'dashboard':Mock()}
        job=JobPosting(title='Repeated vacancy',company='Example')
        self.tab.show_result_outcome(SearchOutcome(jobs=[job]))
        self.tab._clear_selected()
        self.assertEqual(self.tab.table.rowCount(),0)
        self.assertIn('Show cleared jobs',self.tab.empty_results.text())
        self.tab.show_cleared.setChecked(True)
        self.assertEqual(self.tab.table.rowCount(),1)
        self.assertIn('Archived',self.tab.table.item(0,1).text())
        self.assertEqual(self.workspace.application_for_job(job.job_id).status_enum,ApplicationStatus.ARCHIVED)
        self.tab.show_cleared.setChecked(False)
        self.assertEqual(self.tab.table.rowCount(),0)


class SettingsInterfaceTest(WorkspaceTestCase):
    """The Settings controls for the 1.5 sources round-trip through settings."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app, "blackgreen")

    def setUp(self):
        super().setUp()
        from unittest.mock import Mock

        from jautomatic.ui.settings_tab import SettingsTab
        settings = AppSettings()
        self.ctx = SimpleNamespace(
            settings=settings, profile=Profile(), workspace=self.workspace,
            pipeline=ApplicationPipeline(self.workspace, settings),
            add_header_action=Mock(), save_settings=self.workspace.save_settings,
            notify=Mock(), confirm=Mock(return_value=True), update_meta=Mock(),
            refresh_all=Mock(), open_preview=Mock(), run_task=Mock(), busy=False,
        )
        self.tab = SettingsTab(self.ctx)
        self.addCleanup(self.tab.close)

    def test_company_boards_and_jooble_keys_round_trip(self):
        self.tab.boards_edit.setPlainText("greenhouse:careem\njobs.lever.co/kitopi\n\njunk here")
        self.tab.jooble_uae_key.setText("dubai-key")
        self.tab.jooble_gulf_keys["sa"].setText("riyadh-key")
        self.tab.save_button.click()
        settings = self.workspace.load_settings()
        # "junk here" is a bare slug -> an unusable Greenhouse board name, dropped.
        self.assertEqual(settings.company_boards, ["greenhouse:careem", "lever:kitopi"])
        self.assertEqual(settings.jooble_keys, {"ae": "dubai-key", "sa": "riyadh-key"})
        self.assertEqual(settings.jooble_uae_key, "")          # the key lives in the map

    def test_board_list_editor_shows_the_saved_list_and_defaults(self):
        self.ctx.settings.company_boards = ["greenhouse:careem"]
        self.ctx.settings.jooble_keys = {"qa": "doha-key"}
        self.tab.load()
        self.assertEqual(self.tab.boards_edit.toPlainText(), "greenhouse:careem")
        self.assertEqual(self.tab.jooble_uae_key.text(), "")
        self.assertEqual(self.tab.jooble_gulf_keys["qa"].text(), "doha-key")
        self.tab.boards_edit.setPlainText("")                  # empty = the built-in list
        self.tab.save_button.click()
        settings = self.workspace.load_settings()
        self.assertEqual(settings.company_boards, [])

    def test_reset_button_restores_the_builtin_boards(self):
        from PySide6.QtWidgets import QPushButton

        from jautomatic.services.company_boards import DEFAULT_COMPANY_BOARDS
        self.tab.boards_edit.setPlainText("greenhouse:careem")
        reset = next(button for button in self.tab.boards_card.findChildren(QPushButton)
                     if button.text() == "Reset to built-in list")
        reset.click()
        self.assertEqual(self.tab.boards_edit.toPlainText(),
                         "\n".join(DEFAULT_COMPANY_BOARDS))
        self.tab.save_button.click()
        settings = self.workspace.load_settings()
        self.assertEqual(len(settings.company_boards), len(DEFAULT_COMPANY_BOARDS))
