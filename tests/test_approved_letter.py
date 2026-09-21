"""Exact approved wording reaches both the letter and Outlook's MIME draft."""
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

from jautomatic.models import AppSettings, JobPosting, Profile
from jautomatic.services.application_pipeline import ApplicationPipeline
from jautomatic.services.cover_letter import CoverLetterService, render_cover_letter
from jautomatic.services.email_drafter import render_email
from tests.support import WorkspaceTestCase


TEMPLATE = "Dear Hiring Manager,\n\nI am applying for the [Job Title] position at [Company].\n\nMy approved wording.\n\nYours sincerely,\nEugene Shilachilu"


class ApprovedLetterTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.profile = Profile(full_name="EUGENE SHILACHILU", signature="Extra signature",
            extra={"approved_cover_letter_template": TEMPLATE,
                   "cover_letter_paragraphs": ["Do not append this."]})
        self.job = JobPosting(title="Warehouse Coordinator", company="Example",
                              location="Nairobi", url="https://example.test/job")
        self.expected = TEMPLATE.replace("[Job Title]", self.job.title).replace("[Company]", self.job.company)

    def test_exact_letter_and_email_ignore_tone_signature_and_other_paragraphs(self):
        for tone in ("professional", "friendly", "enthusiastic", "concise"):
            self.assertEqual(render_cover_letter(self.profile, self.job, tone=tone), self.expected + "\n")
            self.assertEqual(render_email(self.profile, self.job, tone=tone).body, self.expected)
        with patch("jautomatic.services.cover_letter.ollama_cover_letter") as llm:
            doc = CoverLetterService().generate(self.profile, self.job, llm={"model": "test"})
        llm.assert_not_called()
        self.assertEqual(doc.text, self.expected + "\n")

    def test_outlook_refreshes_stale_letter_and_preserves_cv_and_status(self):
        pipeline = ApplicationPipeline(self.workspace, AppSettings(export_format="txt"))
        record = pipeline.ensure_application(self.job)
        cv = self.workspace.documents_dir / "Reviewed CV.txt"
        old = self.workspace.documents_dir / "Old letter.txt"
        cv.write_text("Reviewed CV", encoding="utf-8")
        old.write_text("Old unwanted sentences", encoding="utf-8")
        record.cv_path, record.cover_letter_path = str(cv), str(old)
        self.workspace.save_application(record)
        draft, paths, path = pipeline.prepare_outlook_draft(record, self.profile)
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        self.assertEqual(message.get_body().get_content().replace("\r\n", "\n").rstrip("\n"), self.expected)
        self.assertEqual(draft.body, self.expected)
        self.assertEqual(paths[0], cv)
        self.assertNotEqual(paths[1], old)
        self.assertEqual(old.read_text(encoding="utf-8"), "Old unwanted sentences")
        self.assertEqual(paths[1].read_text(encoding="utf-8").strip(), self.expected)
        self.assertEqual(self.workspace.get_application(record.application_id).status, record.status)
        self.assertIsNone(message["To"])
