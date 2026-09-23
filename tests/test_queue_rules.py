from unittest.mock import patch
from tests.support import WorkspaceTestCase
from jautomatic.models import JobPosting, ApplicationStatus
from jautomatic.services.application_pipeline import ApplicationPipeline

class QueueRulesTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = ApplicationPipeline(self.workspace)

    def test_cross_website_repeat_preserves_sent(self):
        first = JobPosting(title='IT Support', company='Acme Ltd', url='https://one.test/a')
        app = self.pipeline.import_jobs([first])[0]
        self.pipeline.set_status(app, ApplicationStatus.SENT)
        repeat = JobPosting(title='IT SUPPORT', company='Acme Ltd.', url='https://two.test/b')
        self.assertEqual(self.pipeline.import_jobs([repeat]), [])
        self.assertEqual(first.job_id, repeat.job_id)
        self.assertEqual(self.workspace.application_for_job(repeat.job_id).status_enum, ApplicationStatus.SENT)
        self.assertEqual(self.workspace.job_count(), 1)
        other = JobPosting(title='IT Support', company='Other Ltd', url='https://two.test/c')
        self.assertEqual(len(self.pipeline.import_jobs([other])), 1)

    def test_outlook_success_and_failure(self):
        app = self.pipeline.import_jobs([JobPosting(title='Tester', company='Acme')])[0]
        with patch.object(self.pipeline, 'prepare_outlook_draft', return_value=(None, [], None)), patch('jautomatic.services.outlook_draft.open_message', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                self.pipeline.open_outlook_draft(app)
        self.assertEqual(self.workspace.get_application(app.application_id).status_enum, ApplicationStatus.DISCOVERED)
        with patch.object(self.pipeline, 'prepare_outlook_draft', return_value=(None, [], None)), patch('jautomatic.services.outlook_draft.open_message', return_value='new'):
            self.pipeline.open_outlook_draft(app)
        self.assertEqual(self.workspace.get_application(app.application_id).status_enum, ApplicationStatus.SENT)

    def test_uae_added_without_selection(self):
        query = self.pipeline.build_query('IT support', 'Kenya', sources=['jobweb_ke'])
        self.assertEqual(query.location, 'Kenya; UAE')
        self.assertIn('uae_ai', query.sources)
        self.assertEqual(self.pipeline.build_query('IT', 'UAE').location, 'UAE')
