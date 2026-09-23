import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from jautomatic.models import AppSettings, Profile
from jautomatic.services.paid_tasks import PaidTask, TaskStore, matches_filters
from jautomatic.ui.tasks_tab import TasksTab
from tests.support import WorkspaceTestCase

class PaidTasksTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp(); self.store=TaskStore(self.workspace)
    def task(self, **kwargs):
        return PaidTask(title='Check product records',url='https://workplace.clickworker.com/task/123',amount=3,**kwargs)
    def test_dedup_preserves_progress(self):
        task,_=self.store.save(self.task())
        self.store.set_stage(task.task_id,'Saved')
        duplicate,created=self.store.save(PaidTask(title='Updated title',url=task.url+'?utm_source=mail'))
        self.assertFalse(created); self.assertEqual(duplicate.status,'Saved')
        duplicate,created=self.store.save(PaidTask(title=task.title.upper(),url='https://other.test/123'))
        self.assertFalse(created); self.assertEqual(len(self.store.tasks()),1)
        self.assertEqual(self.workspace.applications(),[])
    def test_pay_units_and_unknown_pay(self):
        self.assertTrue(matches_filters(self.task()))
        self.assertFalse(matches_filters(self.task(unit='hour')))
        self.assertTrue(matches_filters(self.task(unit='hour'),unit='hour'))
        self.assertFalse(matches_filters(self.task(currency='EUR')))
        self.assertTrue(matches_filters(self.task(currency='EUR'),include_unknown=True))
        self.assertFalse(matches_filters(PaidTask()))
        self.assertTrue(matches_filters(PaidTask(),include_unknown=True))
    def test_expired_and_duration(self):
        task=self.task(deadline=(date.today()-timedelta(days=1)).isoformat())
        self.assertFalse(matches_filters(task)); self.assertTrue(matches_filters(task,view='All records'))
        self.store.save(task)
        with self.assertRaises(ValueError): self.store.set_stage(task.task_id,'Saved')
        self.assertFalse(matches_filters(self.task(),minutes=30))
        self.assertTrue(matches_filters(self.task(minutes=20),minutes=30))
    def test_paid_actual_amount_and_currency_totals(self):
        task,_=self.store.save(self.task())
        with self.assertRaises(ValueError): self.store.set_stage(task.task_id,'Paid')
        self.store.set_stage(task.task_id,'Paid',2.50)
        self.assertEqual(self.store.earnings(),{'USD':2.5})
        self.store.set_stage(task.task_id,'Paid',2.50)
        self.assertEqual(self.store.earnings(),{'USD':2.5})
        self.store.set_stage(task.task_id,'Archived')
        self.assertEqual(self.store.earnings(),{'USD':2.5})
        paid=self.store.tasks()[0]; paid.currency='EUR'
        with self.assertRaises(ValueError): self.store.save(paid)
        other,_=self.store.save(PaidTask(title='Another',url='https://example.org/task/4',currency='EUR'))
        self.store.set_stage(other.task_id,'Paid',5)
        self.assertEqual(self.store.earnings(),{'USD':2.5,'EUR':5})
    def test_validation(self):
        for url in ('file:///c:/secret','javascript:alert(1)','https://user:pass@example.com'):
            with self.assertRaises(ValueError): self.store.save(PaidTask(title='Test',url=url))
        with self.assertRaises(ValueError): self.store.save(self.task(deadline='tomorrow'))
    def test_saved_low_pay_not_hidden(self):
        self.assertTrue(matches_filters(PaidTask(status='Saved',amount=1),view='My tasks'))

class PaidTasksInterfaceTests(WorkspaceTestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def test_manual_selection_persists_without_job_application(self):
        ctx=SimpleNamespace(workspace=self.workspace,settings=AppSettings(),profile=Profile(),save_settings=self.workspace.save_settings,notify=Mock())
        tab=TasksTab(ctx)
        self.addCleanup(tab.close)
        self.assertEqual(tab.table.rowCount(),0)
        first,_=tab.store.save(PaidTask(title='First',url='https://example.org/1',amount=3))
        tab.store.save(PaidTask(title='Second',url='https://example.org/2',amount=4))
        tab.refresh(); self.assertEqual(tab.table.rowCount(),2)
        selected_id=tab.table.item(0,0).data(Qt.UserRole)
        tab.table.item(0,0).setCheckState(Qt.Checked); tab.add_checked()
        tasks=tab.store.tasks()
        self.assertEqual([t.task_id for t in tasks if t.status=='Saved'],[selected_id])
        self.assertEqual(self.workspace.applications(),[])
        tab.view.setCurrentText('My tasks'); self.assertEqual(tab.table.rowCount(),1)
        tab.view.setCurrentText('Available'); tab.min_pay.setValue(100); self.assertEqual(tab.table.rowCount(),0)
        self.assertEqual(tab.details.toPlainText(),'')
        tab.clear_filters(); self.assertEqual(tab.table.rowCount(),1)
