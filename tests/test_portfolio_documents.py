"""Applicant-authored project evidence survives application generation."""
import unittest

from jautomatic.models import Profile, JobPosting, EducationEntry
from jautomatic.services.cv_generator import render_markdown
from jautomatic.services.cover_letter import render_cover_letter


class PortfolioDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(
            full_name="Test Applicant", summary="Warehouse operations professional.",
            skills=["Inventory control"],
            education=[EducationEntry(degree="Business IT", school="University", end="Ongoing")],
            extra={"projects": [{"name": "Parts Warehouse", "period": "2026",
                    "highlights": ["Built with AI-assisted development; batch receiving and FIFO."],
                    "url": "https://example.com/project"}],
                   "cover_letter_paragraphs": [
                       "I trained warehouse teams across five countries.",
                       "I built a warehouse application using AI-assisted development.",
                       "My Business IT degree is ongoing."]})
        self.job = JobPosting(title="Inventory Coordinator", company="Example Co",
                              tags=["SAP", "MBA"], description="Requires SAP and an MBA.")

    def test_cv_preserves_projects_and_ongoing_degree_without_inventing_skills(self):
        text = render_markdown(self.profile, self.job, "portfolio")
        for expected in ("Parts Warehouse", "AI-assisted", "FIFO", "Ongoing", "University"):
            self.assertIn(expected, text)
        for unwanted in ("SAP", "MBA", "Targeting", "Tailored for"):
            self.assertNotIn(unwanted, text)

    def test_letter_uses_same_evidence_and_actual_destination(self):
        text = render_cover_letter(self.profile, self.job)
        for expected in ("Inventory Coordinator", "Example Co", "five countries", "AI-assisted", "ongoing"):
            self.assertIn(expected, text)
        for unwanted in ("SAP", "MBA", "production experience", "(remote)", "careers page"):
            self.assertNotIn(unwanted, text)

    def test_profile_roundtrip_preserves_evidence(self):
        restored = Profile.from_dict(self.profile.to_dict())
        self.assertEqual(restored.extra, self.profile.extra)
        self.assertEqual(render_cover_letter(restored, self.job),
                         render_cover_letter(self.profile, self.job))

    def test_no_projects_is_valid(self):
        self.profile.extra = {}
        self.assertNotIn("Selected digital projects", render_markdown(self.profile, None, "portfolio"))

if __name__ == '__main__':
    unittest.main()
