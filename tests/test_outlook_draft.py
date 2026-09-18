"""Draft contents, attachments and human-controlled sending boundaries."""
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock, patch

from jautomatic.models import AppSettings, JobPosting, Profile
from jautomatic.services.application_pipeline import ApplicationPipeline
from jautomatic.services.email_drafter import EmailDraft
from jautomatic.services.outlook_draft import write_message, open_message
from tests.support import WorkspaceTestCase


class OutlookDraftTests(WorkspaceTestCase):
    def test_reuses_documents_and_leaves_recipient_and_sent_status_untouched(self):
        pipeline = ApplicationPipeline(self.workspace, AppSettings(export_format="txt"))
        record = pipeline.ensure_application(JobPosting(title="Logistics Officer", company="Example",
            description="Apply at recruiter@company.test"))
        cv = self.workspace.documents_dir / "Reviewed CV.txt"
        letter = self.workspace.documents_dir / "Reviewed letter.txt"
        cv.write_text("Reviewed CV", encoding="utf-8")
        letter.write_text("Reviewed letter", encoding="utf-8")
        record.cv_path, record.cover_letter_path = str(cv), str(letter)
        self.workspace.save_application(record)
        with patch.object(pipeline.cv_generator, "generate") as generate_cv:
            draft, paths, path = pipeline.prepare_outlook_draft(record, Profile(full_name="Zoë"))
        generate_cv.assert_not_called()
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        self.assertIsNone(message["To"])
        self.assertIsNone(message["Cc"])
        self.assertIsNone(message["Bcc"])
        self.assertEqual(message["X-Unsent"], "1")
        self.assertIn("Zoë", message["Subject"])
        self.assertIn("Logistics Officer", message.get_body().get_content())
        self.assertEqual([p.get_payload(decode=True) for p in message.iter_attachments()],
                         [b"Reviewed CV", b"Reviewed letter"])
        self.assertEqual(self.workspace.get_application(record.application_id).status, record.status)
        self.assertEqual(draft.recipient, "")

    def test_generates_missing_letter_without_overwriting_cv(self):
        pipeline = ApplicationPipeline(self.workspace, AppSettings(export_format="txt", include_cover_letter=False))
        record = pipeline.ensure_application(JobPosting(title="Planner", company="Example"))
        cv = self.workspace.documents_dir / "cv.txt"
        cv.write_text("Manual edits", encoding="utf-8")
        record.cv_path = str(cv)
        self.workspace.save_application(record)
        _, attachments, _ = pipeline.prepare_outlook_draft(record, Profile(full_name="Applicant"))
        self.assertEqual(cv.read_text(), "Manual edits")
        self.assertEqual(len(attachments), 2)
        self.assertTrue(attachments[1].is_file())

    def test_missing_attachment_prevents_message_creation(self):
        path = self.workspace.documents_dir / "draft.eml"
        with self.assertRaises(FileNotFoundError):
            write_message(EmailDraft(), [path.with_suffix(".pdf")], path)
        self.assertFalse(path.exists())

    def test_classic_payload_excludes_recipients_and_contains_attachments(self):
        import base64
        import json
        attachment = self.workspace.documents_dir / "CV.txt"
        attachment.write_text("CV")
        with patch("jautomatic.services.outlook_draft.sys.platform", "win32"), \
             patch("jautomatic.services.outlook_draft.new_outlook_path", return_value=None), \
             patch("jautomatic.services.outlook_draft.classic_outlook_available", return_value=True), \
             patch("jautomatic.services.outlook_draft.subprocess.run", return_value=Mock(returncode=0)) as run:
            result = open_message(EmailDraft(subject="Role", body="Body", recipient="ignored@test.com"),
                                  [attachment], attachment.with_suffix(".eml"))
        self.assertEqual(result, "classic")
        payload = json.loads(base64.b64decode(run.call_args.kwargs["input"]))
        self.assertEqual(set(payload), {"subject", "body", "attachments"})
        self.assertEqual(payload["attachments"], [str(attachment.resolve())])
        script = base64.b64decode(run.call_args.args[0][-1]).decode("utf-16-le")
        self.assertIn("$mail.Display($false)", script)
        self.assertNotIn(".Send(", script)

    def test_no_classic_outlook_opens_portable_message(self):
        path = self.workspace.documents_dir / "draft.eml"
        write_message(EmailDraft(subject="Role", body="Body"), [], path)
        with patch("jautomatic.services.outlook_draft.sys.platform", "win32"), \
             patch("jautomatic.services.outlook_draft.new_outlook_path", return_value=None), \
             patch("jautomatic.services.outlook_draft.classic_outlook_available", return_value=False), \
             patch("jautomatic.services.outlook_draft.os.startfile", create=True) as launch:
            self.assertEqual(open_message(EmailDraft(), [], path), "eml")
        launch.assert_called_once_with(str(path.resolve()))

    def test_new_outlook_is_preferred_over_classic_and_default_mail_app(self):
        from pathlib import Path
        import subprocess
        path = self.workspace.documents_dir / "Prepared email with spaces.eml"
        write_message(EmailDraft(subject="Role", body="Body"), [], path)
        launcher = Path("C:/WindowsApps/olk.exe")
        with patch("jautomatic.services.outlook_draft.sys.platform", "win32"), \
             patch("jautomatic.services.outlook_draft.new_outlook_path", return_value=launcher), \
             patch("jautomatic.services.outlook_draft.classic_outlook_available") as classic, \
             patch("jautomatic.services.outlook_draft.os.startfile", create=True) as launch:
            self.assertEqual(open_message(EmailDraft(), [], path), "new")
        classic.assert_not_called()
        launch.assert_called_once_with(str(launcher), "open", subprocess.list2cmdline([str(path.resolve())]))
