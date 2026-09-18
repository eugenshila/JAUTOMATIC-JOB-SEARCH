"""Release regressions: data recovery, portable backups and eligibility."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from jautomatic.models import (
    Application,
    ApplicationStatus,
    AppSettings,
    Profile,
    Workspace,
)
from jautomatic.services.application_pipeline import ApplicationPipeline, match_job
from jautomatic.services.data_safety import restore_backup, verify_backup
from jautomatic.services.eligibility import remote_location_fit
from jautomatic.services.job_scraper import JobScraper, SearchQuery, parse_salary
from tests.support import WorkspaceTestCase
from tests.test_pipeline import python_job, sample_profile


class ReleaseSafetyTests(WorkspaceTestCase):
    def test_failed_atomic_replace_preserves_profile(self):
        self.workspace.save_profile(Profile(full_name="Original"))
        import os
        original_replace = os.replace

        def fail_current(source, destination):
            if Path(destination) == self.workspace.profile_path:
                raise OSError("simulated interrupted save")
            return original_replace(source, destination)

        with (patch("jautomatic.services.data_safety.os.replace", side_effect=fail_current),
              self.assertRaises(OSError)):
            self.workspace.save_profile(Profile(full_name="Changed"))
        self.assertEqual(self.workspace.load_profile().full_name, "Original")

    def test_corrupt_profile_recovers_previous_and_keeps_evidence(self):
        self.workspace.save_profile(Profile(full_name="Previous"))
        self.workspace.save_profile(Profile(full_name="Latest"))
        self.workspace.profile_path.write_text("{broken", encoding="utf-8")
        recovered = self.workspace.load_profile()
        self.assertEqual(recovered.full_name, "Previous")
        self.assertTrue(self.workspace.recovery_notices)
        self.workspace.save_profile(recovered)
        preserved = list(self.workspace.root.glob("profile.corrupt-*.json"))
        self.assertEqual(preserved[0].read_text("utf-8"), "{broken")

    def test_settings_recover_and_defaults_still_auto_queue(self):
        self.assertTrue(self.workspace.load_settings().auto_track_qualified)
        self.workspace.save_settings(AppSettings(theme="daylight"))
        self.workspace.save_settings(AppSettings(theme="blackgreen"))
        self.workspace.settings_path.write_text("[]", encoding="utf-8")
        self.assertEqual(self.workspace.load_settings().theme, "daylight")

    def test_live_wal_backup_restores_jobs_and_document_paths(self):
        job = python_job()
        self.workspace.save_jobs([job])
        document = self.workspace.documents_dir / "cv.txt"
        document.write_text("My CV", encoding="utf-8")
        record = Application(job_id=job.job_id, cv_path=str(document))
        self.workspace.save_application(record)
        self.workspace.save_profile(sample_profile())
        self.workspace.save_settings(AppSettings())
        with tempfile.TemporaryDirectory() as folder:
            backup = self.workspace.backup_to(Path(folder))
            second = self.workspace.backup_to(Path(folder))
            self.assertNotEqual(backup, second)
            verify_backup(backup)
            restored_path = restore_backup(backup, Path(folder) / "restored")
            restored = Workspace(restored_path)
            try:
                self.assertEqual(restored.job_count(), 1)
                self.assertEqual(restored.load_profile().full_name, sample_profile().full_name)
                app = restored.get_application(record.application_id)
                self.assertEqual(Path(app.cv_path), restored_path / "documents" / "cv.txt")
                self.assertEqual(Path(app.cv_path).read_text("utf-8"), "My CV")
                self.assertEqual(restored.load_settings().data_dir, str(restored_path))
            finally:
                restored.close()
            with self.assertRaises(ValueError):
                restore_backup(backup, restored_path)
            (backup / "profile.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_backup(backup)

    def test_backup_rejects_nested_destination(self):
        with self.assertRaises(ValueError):
            self.workspace.backup_to(self.workspace.root / "backups")

    def test_mixed_currencies_cannot_qualify_or_get_filtered_numerically(self):
        profile = sample_profile()
        profile.salary_floor = 50000
        result = match_job(profile, python_job(currency="KES", salary_min=60000, salary_max=70000))
        self.assertTrue(result.needs_review)
        self.assertLess(result.score, 70)
        self.assertTrue(any("cannot compare" in reason for reason in result.reasons))
        rows, _ = JobScraper()._post_process(
            [python_job(currency="EUR", salary_min=30000, salary_max=40000)],
            SearchQuery(min_salary=50000, salary_currency="USD"))
        self.assertEqual(len(rows), 1)

    def test_remote_restrictions_use_current_location_not_desired_location(self):
        profile = sample_profile()
        profile.location = "Nairobi, Kenya"
        profile.desired_locations = ["United States"]
        result = match_job(profile, python_job(location="US only", remote=True))
        self.assertFalse(result.location_fit)
        self.assertLess(result.score, 70)
        self.assertTrue(remote_location_fit("Nairobi, Kenya", "Africa"))
        self.assertTrue(remote_location_fit("Nairobi, Kenya", "Worldwide"))
        self.assertIsNone(remote_location_fit("Nairobi", "Remote"))

    def test_pay_periods_are_not_compared_as_annual_without_evidence(self):
        self.assertEqual(parse_salary("USD 5,000 - 6,000 per month"), (60000, 72000, "USD"))
        self.assertEqual(parse_salary("$25 - $40 per hour")[:2], (0, 0))

    def test_follow_up_sent_is_idempotent_and_drafting_does_not_clear_due(self):
        pipeline = ApplicationPipeline(self.workspace)
        job = python_job()
        record = pipeline.import_jobs([job])[0]
        record = pipeline.set_status(record, ApplicationStatus.SENT)
        record.follow_up_at = "2020-01-01"
        self.workspace.save_application(record)
        pipeline.draft_follow_up(record, fmt="txt")
        self.assertEqual(self.workspace.get_application(record.application_id).follow_up_at, "2020-01-01")
        first = pipeline.mark_follow_up_sent(record)
        second = pipeline.mark_follow_up_sent(record)
        self.assertEqual(first.follow_up_count, 1)
        self.assertEqual(second.follow_up_count, 1)
        self.assertEqual(first.follow_up_at, second.follow_up_at)
