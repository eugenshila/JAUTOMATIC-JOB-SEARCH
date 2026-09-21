"""Role-based selection keeps saved wording consistent across output paths."""
from unittest import TestCase
from jautomatic.models import Profile, JobPosting
from jautomatic.services.cover_letter import select_cover_letter, approved_cover_letter, CoverLetterService
from jautomatic.services.email_drafter import render_email


class LetterSelectionTests(TestCase):
    def setUp(self):
        self.profile = Profile(full_name="Applicant", extra={
            "approved_cover_letter_template": "Old wording",
            "cover_letter_variants": [
                {"id": key, "name": key, "body": f"Dear Hiring Manager,\n\n{key}: [Job Title] at [Company].\n\nGitHub and LinkedIn"}
                for key in ("corporate", "systems", "concise")]})

    def test_representative_jobs(self):
        for title, expected in (("Warehouse Supervisor", "corporate"),
                                ("Logistics Officer", "corporate"),
                                ("Speed Super User", "systems"),
                                ("Warehouse Systems Coordinator", "systems"),
                                ("IT Support Technician", "systems"),
                                ("Customer Service Assistant", "concise")):
            with self.subTest(title=title):
                job = JobPosting(title=title, company="Example")
                selected = select_cover_letter(self.profile, job)
                self.assertEqual(selected["id"], expected)
                body = approved_cover_letter(self.profile, job)
                self.assertEqual(render_email(self.profile, job).body, body.rstrip())
                document = CoverLetterService().generate(self.profile, job)
                self.assertIn(body, document.text)
                self.assertIn("# Applicant", document.text)
                self.assertNotIn("Old wording", document.text)

    def test_description_can_identify_specialist_role(self):
        job = JobPosting(title="Coordinator", description="Provide WMS user support and system testing.")
        self.assertEqual(select_cover_letter(self.profile, job)["id"], "systems")

    def test_title_outweighs_generic_description(self):
        job = JobPosting(title="Logistics Officer", description="Use WMS, ERP, systems and user training.")
        self.assertEqual(select_cover_letter(self.profile, job)["id"], "corporate")

    def test_no_library_preserves_existing_approved_letter(self):
        self.profile.extra.pop("cover_letter_variants")
        self.assertIsNone(select_cover_letter(self.profile, JobPosting()))
        self.assertEqual(approved_cover_letter(self.profile, JobPosting()), "Old wording\n")
