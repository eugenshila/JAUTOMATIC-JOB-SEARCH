"""Persistent application movement through Applications, Sent and Archive."""
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from jautomatic.models import AppSettings, ApplicationStatus, JobPosting, Profile
from jautomatic.services.application_pipeline import ApplicationPipeline
from jautomatic.ui.applications_tab import ApplicationsTab, VIEW_STATUSES
from tests.support import WorkspaceTestCase


class ApplicationTabsTest(WorkspaceTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        settings = AppSettings()
        self.ctx = SimpleNamespace(
            workspace=self.workspace, settings=settings, profile=Profile(),
            pipeline=ApplicationPipeline(self.workspace, settings),
            add_header_action=Mock(), notify=Mock(), confirm=Mock(return_value=True),
            update_meta=Mock(), open_interview_prep=Mock(), _previews=[],
        )
        self.ctx.tabs = {key: ApplicationsTab(self.ctx, key) for key in VIEW_STATUSES}
        self.ctx.refresh_all = lambda: [tab.refresh() for tab in self.ctx.tabs.values()]
        self.addCleanup(self._dispose_tabs)

    def _dispose_tabs(self):
        for tab in self.ctx.tabs.values():
            tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def _create(self, status=ApplicationStatus.DISCOVERED):
        record = self.ctx.pipeline.ensure_application(
            JobPosting(title=f"Engineer {status.value}", company="Example"))
        return self.ctx.pipeline.set_status(record, status)

    def test_each_status_appears_in_exactly_one_tab(self):
        for status in ApplicationStatus:
            self._create(status)
        self.ctx.refresh_all()
        all_ids = []
        for key, tab in self.ctx.tabs.items():
            self.assertEqual({row.status for row in tab.rows}, set(VIEW_STATUSES[key]))
            all_ids.extend(row.application.application_id for row in tab.rows)
        self.assertEqual(len(all_ids), len(ApplicationStatus))
        self.assertEqual(len(set(all_ids)), len(all_ids))

    def test_outlook_button_runs_draft_work_and_never_marks_sent(self):
        record = self._create()
        self.ctx.refresh_all()
        tab = self.ctx.tabs["applications"]
        tab.table.selectRow(0)
        self.ctx.tabs["dashboard"] = Mock()
        self.ctx.run_task = Mock()
        with patch.object(self.ctx.pipeline, "prepare_outlook_draft", return_value=("draft", [], "path")), \
             patch("jautomatic.services.outlook_draft.open_message", return_value="classic") as launch:
            tab._open_outlook_draft()
            self.assertFalse(tab.outlook_button.isEnabled())
            _, work, done, failed = self.ctx.run_task.call_args.args
            done(work())
        launch.assert_called_once_with("draft", [], "path")
        self.assertTrue(tab.outlook_button.isEnabled())
        self.assertEqual(self.workspace.get_application(record.application_id).status, record.status)
        tab._open_outlook_draft()
        self.ctx.run_task.call_args.args[3]("Outlook unavailable")
        self.assertTrue(tab.outlook_button.isEnabled())
        del self.ctx.tabs["dashboard"]

    def test_sent_regret_restore_and_confirmed_delete(self):
        record = self._create()
        record.notes = "Recruiter notes"
        record.prep = {"notes": "Interview research"}
        document = self.workspace.documents_dir / "cv.txt"
        document.write_text("Saved CV", encoding="utf-8")
        record.cv_path = str(document)
        self.workspace.save_application(record)
        self.ctx.refresh_all()
        queue, sent, archive = [self.ctx.tabs[key] for key in VIEW_STATUSES]
        queue.status_combo.setCurrentIndex(queue.status_combo.findData("sent"))
        queue._apply_status()
        self.assertEqual(queue.table.rowCount(), 0)
        self.assertEqual(sent.table.rowCount(), 1)
        saved = self.workspace.get_application(record.application_id)
        self.assertTrue(saved.sent_at)
        self.assertTrue(saved.follow_up_at)
        sent._interview_prep()
        self.ctx.open_interview_prep.assert_called_once()
        sent._regret()
        self.assertEqual(sent.table.rowCount(), 0)
        self.assertEqual(archive.table.rowCount(), 1)
        saved = self.workspace.get_application(record.application_id)
        self.assertEqual(saved.status_enum, ApplicationStatus.REJECTED)
        self.assertEqual(saved.follow_up_at, "")
        self.assertEqual(saved.notes, "Recruiter notes")
        self.assertEqual(saved.prep["notes"], "Interview research")
        self.assertTrue(any(event.get("to") == "rejected" for event in saved.history))
        archive.status_combo.setCurrentIndex(archive.status_combo.findData("sent"))
        archive._apply_status()
        self.assertEqual(sent.table.rowCount(), 1)
        self.assertEqual(archive.table.rowCount(), 0)
        sent._regret()
        self.ctx.confirm.return_value = False
        archive._delete()
        self.assertIsNotNone(self.workspace.get_application(record.application_id))
        self.ctx.confirm.return_value = True
        archive._delete()
        self.assertIsNone(self.workspace.get_application(record.application_id))
        self.assertEqual(archive.table.rowCount(), 0)
        self.assertTrue(document.exists())

    def test_actions_belong_to_the_correct_tab(self):
        queue, sent, archive = [self.ctx.tabs[key] for key in VIEW_STATUSES]
        self.assertTrue(queue.prep_button.isHidden())
        self.assertFalse(sent.prep_button.isHidden())
        self.assertFalse(sent.regret_button.isHidden())
        self.assertTrue(queue.delete_button.isHidden())
        self.assertTrue(sent.delete_button.isHidden())
        self.assertFalse(archive.delete_button.isHidden())

    def test_filter_and_selection_do_not_leak_other_tabs_or_stale_details(self):
        record = self._create(ApplicationStatus.SENT)
        self.ctx.refresh_all()
        sent = self.ctx.tabs["sent"]
        sent.search_box.setText("no such company")
        self.assertEqual(sent.table.rowCount(), 0)
        self.assertIsNone(sent._selected_row())
        sent._regret()
        self.assertEqual(self.workspace.get_application(record.application_id).status, "sent")
        sent.search_box.clear()
        self.assertEqual(sent._selected_application_id(), record.application_id)
        sent._clear()
        self.assertEqual(self.ctx.tabs["archive"].table.rowCount(), 1)
        self.assertEqual(sent.detail_meta.text(), "")

    def test_delete_is_refused_outside_archive(self):
        record = self._create(ApplicationStatus.SENT)
        self.ctx.refresh_all()
        self.ctx.tabs["sent"]._delete()
        self.assertIsNotNone(self.workspace.get_application(record.application_id))
        self.ctx.confirm.assert_not_called()

    def test_delete_selected_confirmation_scope_and_documents(self):
        first = self._create()
        other = self._create(ApplicationStatus.SHORTLISTED)
        sent = self._create(ApplicationStatus.SENT)
        document = self.workspace.documents_dir / "keep.txt"
        document.write_text("Saved CV", encoding="utf-8")
        first.cv_path = str(document)
        self.workspace.save_application(first)
        self.ctx.refresh_all()
        queue = self.ctx.tabs["applications"]
        queue.search_box.setText("discovered")
        queue.select_all_button.click()
        self.ctx.confirm.return_value = False
        queue.delete_selected_button.click()
        self.assertIsNotNone(self.workspace.get_application(first.application_id))
        self.ctx.confirm.return_value = True
        queue.delete_selected_button.click()
        self.assertIsNone(self.workspace.get_application(first.application_id))
        self.assertIsNotNone(self.workspace.get_application(other.application_id))
        self.assertIsNotNone(self.workspace.get_application(sent.application_id))
        self.assertTrue(document.exists())
        self.assertTrue(self.ctx.confirm.call_args.kwargs["danger"])
        self.ctx.confirm.reset_mock()
        queue._delete_selected()
        self.ctx.tabs["sent"]._delete_selected()
        self.ctx.confirm.assert_not_called()

    def test_delete_multiple_from_archive(self):
        records = [self._create(status) for status in
                   (ApplicationStatus.ARCHIVED, ApplicationStatus.REJECTED)]
        self.ctx.refresh_all()
        archive = self.ctx.tabs["archive"]
        archive.select_all_button.click()
        archive.delete_selected_button.click()
        for record in records:
            self.assertIsNone(self.workspace.get_application(record.application_id))
        self.assertEqual(archive.table.rowCount(), 0)

    def test_archive_all_respects_filters_and_preserves_records(self):
        shown = self._create(ApplicationStatus.DISCOVERED)
        hidden = self._create(ApplicationStatus.SHORTLISTED)
        sent = self._create(ApplicationStatus.SENT)
        shown.notes = "Keep this note"
        self.workspace.save_application(shown)
        self.ctx.refresh_all()
        queue = self.ctx.tabs["applications"]
        queue.search_box.setText("discovered")
        queue._archive_queue(True)
        saved = self.workspace.get_application(shown.application_id)
        self.assertEqual(saved.status_enum, ApplicationStatus.ARCHIVED)
        self.assertEqual(saved.notes, "Keep this note")
        self.assertTrue(saved.history)
        self.assertEqual(self.workspace.get_application(hidden.application_id).status_enum,
                         ApplicationStatus.SHORTLISTED)
        self.assertEqual(self.workspace.get_application(sent.application_id).status_enum,
                         ApplicationStatus.SENT)

    def test_ticks_take_precedence_over_highlighted_row(self):
        self._create(ApplicationStatus.DISCOVERED)
        self._create(ApplicationStatus.SHORTLISTED)
        self.ctx.refresh_all()
        queue = self.ctx.tabs["applications"]
        ticked = queue.table.item(1, 0).data(Qt.UserRole)
        queue.table.item(1, 0).setCheckState(Qt.Checked)
        queue.table.selectRow(0)
        other = queue._selected_application_id()
        queue.refresh()
        queue._archive_queue()
        self.assertEqual(self.workspace.get_application(ticked).status_enum, ApplicationStatus.ARCHIVED)
        self.assertNotEqual(self.workspace.get_application(other).status_enum, ApplicationStatus.ARCHIVED)

    def test_add_matching_saved_jobs_preserves_archived_status(self):
        archived = self._create(ApplicationStatus.ARCHIVED)
        job = JobPosting(title="Warehouse coordinator", company="New employer")
        self.workspace.save_jobs([job])
        self.ctx.settings.min_match_score = 0
        self.ctx.run_task = lambda title, work, done: done(work())
        queue = self.ctx.tabs["applications"]
        queue._add_matching_jobs()
        self.assertIsNotNone(self.workspace.application_for_job(job.job_id))
        self.assertEqual(self.workspace.get_application(archived.application_id).status_enum,
                         ApplicationStatus.ARCHIVED)
        queue._add_matching_jobs()
        self.assertEqual(len(self.workspace.applications()), 2)

    def test_archive_selection_cancel_and_select_all(self):
        first = self._create(ApplicationStatus.DISCOVERED)
        second = self._create(ApplicationStatus.SHORTLISTED)
        self.ctx.refresh_all()
        queue = self.ctx.tabs["applications"]
        queue.table.selectRow(0)
        chosen = queue._selected_application_id()
        self.ctx.confirm.return_value = False
        queue._archive_queue()
        self.assertEqual(queue.table.rowCount(), 2)
        self.ctx.confirm.return_value = True
        queue._archive_queue()
        self.assertEqual(self.workspace.get_application(chosen).status_enum, ApplicationStatus.ARCHIVED)
        self.assertEqual(queue.table.rowCount(), 1)
        queue.select_all_button.click()
        queue.archive_selected_button.click()
        self.assertEqual(queue.table.rowCount(), 0)
        self.assertEqual(self.ctx.tabs['archive'].table.rowCount(), 2)
        self.ctx.confirm.reset_mock()
        queue._archive_queue(True)
        self.ctx.tabs['sent']._archive_queue(True)
        self.ctx.confirm.assert_not_called()
