from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from job_assistant.database.repository import Repository
from job_assistant.job_sources import JobRecord
from job_assistant.models.entities import CandidateProfile
from job_assistant.services.matching import match_job
from job_assistant.services.profile_service import form_from_profile, profile_from_form
from job_assistant.services.search_service import parse_feed_sources


class PhaseOneRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "assistant.sqlite3"
        self.repository = Repository(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bootstrap_creates_defaults_and_profile(self) -> None:
        settings = self.repository.get_settings()
        self.assertEqual(settings["search_frequency"], "Every 6 hours")
        self.assertEqual(settings["priority_threshold"], 85)
        self.assertEqual(self.repository.get_profile().full_name, "")
        self.assertTrue(self.database.exists())

    def test_profile_round_trip_is_structured(self) -> None:
        profile = CandidateProfile(
            full_name="Amina Example",
            email="amina@example.com",
            technical_skills=["SQL", "Power BI"],
            preferred_locations=["Nairobi", "Remote jobs"],
            years_experience="7",
        )
        self.repository.save_profile(profile)
        loaded = self.repository.get_profile()
        self.assertEqual(loaded.full_name, "Amina Example")
        self.assertEqual(loaded.technical_skills, ["SQL", "Power BI"])
        self.assertEqual(loaded.preferred_locations, ["Nairobi", "Remote jobs"])
        self.assertEqual(loaded.years_experience, "7")

    def test_settings_are_json_values(self) -> None:
        self.repository.set_setting("selected_locations", ["Dubai", "Remote jobs"])
        self.repository.set_setting("start_with_windows", True)
        self.assertEqual(self.repository.get_setting("selected_locations"), ["Dubai", "Remote jobs"])
        self.assertTrue(self.repository.get_setting("start_with_windows"))

    def test_form_conversion_preserves_multiline_lists(self) -> None:
        profile = profile_from_form({
            "full_name": "Candidate",
            "technical_skills": "SQL\nPower BI",
            "preferred_locations": "Nairobi, Dubai",
        })
        self.assertEqual(profile.technical_skills, ["SQL", "Power BI"])
        self.assertEqual(profile.preferred_locations, ["Nairobi", "Dubai"])
        values = form_from_profile(profile)
        self.assertEqual(values["technical_skills"], "SQL\nPower BI")

    def test_master_cv_uploads_are_immutable_and_deduplicated(self) -> None:
        source = Path(self.temp_dir.name) / "master.doc"
        source.write_bytes(b"A master CV")
        stored = Path(self.temp_dir.name) / "MasterCV" / "Master_CV_1.doc"
        stored.parent.mkdir()
        stored.write_bytes(source.read_bytes())
        first = self.repository.add_master_cv(source, stored, "A master CV")
        second = self.repository.add_master_cv(source, stored, "A master CV")
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(self.repository.latest_master_cv()["file_name"], "master.doc")

    def test_feed_source_labels_are_preserved(self) -> None:
        self.assertEqual(
            parse_feed_sources(["LinkedIn | https://example.test/feed.xml", "https://example.test/jobs.json"]),
            [("LinkedIn", "https://example.test/feed.xml"), ("Public API / RSS feed", "https://example.test/jobs.json")],
        )

    def test_job_dedupe_and_explainable_match(self) -> None:
        profile = CandidateProfile(
            full_name="Candidate", job_titles=["Supply Chain Analyst"],
            technical_skills=["SQL", "Power BI"], industry_experience=["supply chain"],
            preferred_locations=["Nairobi"],
        )
        self.repository.save_profile(profile)
        job = JobRecord(
            title="Supply Chain Analyst", company="Example Co", location="Nairobi",
            description="SQL and Power BI are used in our supply chain team.",
            job_url="https://example.test/jobs/1",
        )
        job_id, is_new = self.repository.upsert_job(job)
        same_id, same_is_new = self.repository.upsert_job(job)
        analysis = match_job(profile, job)
        self.assertTrue(is_new)
        self.assertFalse(same_is_new)
        self.assertEqual(job_id, same_id)
        self.assertGreaterEqual(analysis["score"], 80)
        self.assertIn("SQL", analysis["matched"])
        self.assertTrue(analysis["reasons"])


if __name__ == "__main__":
    unittest.main()
