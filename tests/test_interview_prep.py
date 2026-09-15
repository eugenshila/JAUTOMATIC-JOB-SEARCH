"""Interview prep: question bank generation, persistence, export, CSV column."""
from __future__ import annotations

import csv
import sqlite3
import unittest

from jautomatic.models import SAMPLE_PROFILE, Application, Profile, Workspace
from jautomatic.services.application_pipeline import ApplicationPipeline, match_job
from jautomatic.services.interview_prep import (CATEGORIES, CATEGORY_LABELS, InterviewPrep,
                                                PrepQuestion, generate_questions, question_id,
                                                render_prep_markdown)
from tests.support import WorkspaceTestCase
from tests.test_pipeline import python_job, sample_profile, welder_job


def questions_for(job, profile=None):  # noqa: ANN001
    profile = profile or sample_profile()
    return generate_questions(profile, job, match_job(profile, job))


class QuestionGenerationTests(unittest.TestCase):
    def test_every_category_is_populated_for_a_matching_job(self):
        questions = questions_for(python_job())
        categories = {q.category for q in questions}
        self.assertEqual(categories, set(CATEGORIES))
        self.assertGreaterEqual(len(questions), 20)

    def test_technical_questions_come_from_posting_tags_you_cover(self):
        text = " ".join(q.question for q in questions_for(python_job()) if q.category == "technical")
        for tag in ("Python", "FastAPI", "PostgreSQL", "Airflow"):
            self.assertIn(tag, text)
        self.assertNotIn("Welding", text)

    def test_gap_questions_only_use_tags_missing_from_the_profile(self):
        job = python_job(tags=["python", "terraform", "go"])
        gaps = [q for q in questions_for(job) if q.category == "gap"]
        gap_text = " ".join(q.question for q in gaps)
        self.assertIn("Terraform", gap_text)
        self.assertIn("Go", gap_text)
        self.assertNotIn("Python", gap_text)          # covered -> technical, not gap
        # no free-text noise words as "skills"
        welder_gaps = " ".join(q.question for q in questions_for(welder_job()) if q.category == "gap")
        self.assertIn("Welding", welder_gaps)
        for noise in ("Night", "Shift", "Site"):
            self.assertNotIn(noise, welder_gaps)

    def test_fully_covered_posting_gets_a_generic_gap_prompt(self):
        gaps = [q for q in questions_for(python_job()) if q.category == "gap"]
        self.assertEqual(len(gaps), 1)
        self.assertIn("not done before", gaps[0].question)

    def test_behavioural_questions_quote_quantified_achievements_first(self):
        behavioural = [q for q in questions_for(python_job()) if q.category == "behavioural"]
        star = [q for q in behavioural if q.question.startswith("Your CV says")]
        self.assertEqual(len(star), 4)
        # every quantified bullet in the sample profile outranks the unquantified one
        self.assertTrue(all(any(ch.isdigit() for ch in q.question.split("”")[0]) for q in star))
        self.assertNotIn("Mentored three engineers", " ".join(q.question for q in star))
        self.assertIn("(Datawheel GmbH)", " ".join(q.question for q in star))
        self.assertIn("STAR", star[0].hint)

    def test_context_sensitive_questions(self):
        remote = questions_for(python_job(remote=True))
        self.assertTrue(any("remote team" in q.question for q in remote))
        onsite = questions_for(python_job(remote=False, location="Munich, Germany"))
        self.assertTrue(any("based in Munich" in q.question for q in onsite))
        self.assertFalse(any("remote team" in q.question for q in onsite))
        off_target = questions_for(welder_job())
        self.assertTrue(any("how does Welder (night shift) fit" in q.question for q in off_target))

    def test_salary_hint_reflects_posting_band_and_your_floor(self):
        salary = [q for q in questions_for(python_job()) if "salary" in q.question.lower()][0]
        self.assertIn("$90,000", salary.hint)
        self.assertIn("80,000 USD", salary.hint)
        no_band = [q for q in questions_for(python_job(salary_min=0, salary_max=0))
                   if "salary" in q.question.lower()][0]
        self.assertIn("No band advertised", no_band.hint)

    def test_questions_are_deterministic_and_have_stable_ids(self):
        first = questions_for(python_job())
        second = questions_for(python_job())
        self.assertEqual([q.id for q in first], [q.id for q in second])
        self.assertEqual(question_id("Tell me about yourself.", "opening"),
                         question_id("tell  me about YOURSELF.", "opening"))
        self.assertNotEqual(question_id("x", "opening"), question_id("x", "ask"))

    def test_no_duplicate_ids_in_a_bank(self):
        ids = [q.id for q in questions_for(python_job())]
        self.assertEqual(len(ids), len(set(ids)))


class InterviewPrepModelTests(unittest.TestCase):
    def test_round_trip_and_defaults(self):
        prep = InterviewPrep(notes="hi")
        prep.add_question("Custom?", "ask")
        prep.questions[0].answer = "yes"
        prep.questions[0].starred = True
        again = InterviewPrep.from_dict(prep.to_dict())
        self.assertEqual(again.notes, "hi")
        self.assertEqual(again.questions[0].question, "Custom?")
        self.assertEqual(again.questions[0].source, "custom")
        self.assertTrue(again.questions[0].starred)
        self.assertEqual(again.progress_text, "1/1 answered")
        self.assertTrue(InterviewPrep.from_dict(None).is_empty)
        self.assertTrue(InterviewPrep.from_dict({"questions": ["junk", {"question": ""}]}).is_empty)

    def test_merge_keeps_answers_and_adds_only_new(self):
        prep = InterviewPrep()
        bank = questions_for(python_job())
        self.assertEqual(prep.merge_generated(bank), len(bank))
        prep.questions[0].answer = "prepared"
        self.assertEqual(prep.merge_generated(bank), 0)
        self.assertEqual(prep.questions[0].answer, "prepared")
        extra = [PrepQuestion(question="Brand new?", category="ask")]
        self.assertEqual(prep.merge_generated(extra), 1)

    def test_add_remove_and_validation(self):
        prep = InterviewPrep()
        item = prep.add_question("  Why   us? ", "opening")
        self.assertEqual(item.question, "Why us?")
        self.assertIs(prep.add_question("Why us?", "opening"), item)   # de-duplicated
        with self.assertRaises(ValueError):
            prep.add_question("   ")
        self.assertTrue(prep.remove_question(item.id))
        self.assertFalse(prep.remove_question(item.id))
        self.assertEqual(PrepQuestion(question="x", category="bogus").category, "technical")

    def test_markdown_rendering_groups_by_category(self):
        prep = InterviewPrep(notes="Interviewer: Jane")
        prep.merge_generated(questions_for(python_job()))
        prep.questions[0].answer = "My answer"
        prep.questions[1].starred = True
        text = render_prep_markdown(prep, sample_profile(), python_job(),
                                    Application(interview_at="2026-10-01 10:00"))
        self.assertTrue(text.startswith("# Interview prep — Senior Python Engineer at Northwind"))
        self.assertIn("interview: 2026-10-01 10:00", text)
        self.assertIn("## Notes\nInterviewer: Jane", text)
        for category in CATEGORIES:
            self.assertIn(f"## {CATEGORY_LABELS[category]}", text)
        self.assertIn("My answer", text)
        self.assertIn("### ★ ", text)
        self.assertIn("_(no answer prepared yet)_", text)


class PipelinePrepTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.profile = sample_profile()
        self.workspace.save_profile(self.profile)
        self.pipeline = ApplicationPipeline(self.workspace)
        self.pipeline.settings.export_format = "md"
        self.pipeline.import_jobs([python_job()])
        self.row = self.pipeline.tracker(self.profile)[0]

    def test_generate_persists_and_regeneration_keeps_answers(self):
        prep, added = self.pipeline.generate_interview_prep(self.row.application, self.profile)
        self.assertGreater(added, 10)
        stored = self.workspace.get_application(self.row.application.application_id)
        self.assertEqual(stored.prep_question_count, added)
        self.assertEqual(stored.prep_answered_count, 0)
        prep.questions[0].answer = "ready"
        self.pipeline.save_interview_prep(stored, prep)
        again, added_again = self.pipeline.generate_interview_prep(stored.application_id)
        self.assertEqual(added_again, 0)
        self.assertEqual(again.questions[0].answer, "ready")
        reloaded = self.workspace.get_application(stored.application_id)
        self.assertEqual(reloaded.prep_answered_count, 1)
        self.assertTrue(any(e["event"] == "interview prep" for e in reloaded.history))

    def test_export_writes_markdown_and_reuses_the_path(self):
        self.pipeline.generate_interview_prep(self.row.application, self.profile)
        path = self.pipeline.export_interview_prep(self.row.application.application_id)
        self.assertTrue(path.exists())
        self.assertTrue(path.name.startswith("PREP_alex-doe_northwind-analytics"))
        self.assertIn("# Interview prep", path.read_text("utf-8"))
        again = self.pipeline.export_interview_prep(self.row.application.application_id)
        self.assertEqual(again, path)
        self.assertEqual(self.workspace.get_application(self.row.application.application_id).prep_path,
                         str(path))

    def test_export_to_docx(self):
        self.pipeline.generate_interview_prep(self.row.application, self.profile)
        path = self.pipeline.export_interview_prep(self.row.application.application_id, fmt="docx")
        self.assertEqual(path.suffix, ".docx")
        self.assertGreater(path.stat().st_size, 1000)

    def test_csv_has_prep_column(self):
        self.pipeline.generate_interview_prep(self.row.application, self.profile)
        with self.pipeline.export_tracker_csv(self.profile).open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertIn("Prep", rows[0])
        value = rows[1][rows[0].index("Prep")]
        self.assertRegex(value, r"^0/\d+$")

    def test_unknown_application_raises(self):
        with self.assertRaises(KeyError):
            self.pipeline.generate_interview_prep("nope")
        with self.assertRaises(KeyError):
            self.pipeline.interview_prep("nope")


class SchemaV3MigrationTests(unittest.TestCase):
    def test_v2_database_gains_prep_columns(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="jautomatic-v2-") as tmp:
            db = Path(tmp) / "jautomatic.sqlite3"
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE jobs (job_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, source TEXT,
                    title TEXT, company TEXT, location TEXT, remote INTEGER DEFAULT 0,
                    salary_min INTEGER DEFAULT 0, salary_max INTEGER DEFAULT 0,
                    currency TEXT DEFAULT '', url TEXT DEFAULT '', description TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]', posted_at TEXT DEFAULT '', fetched_at TEXT DEFAULT '');
                CREATE TABLE applications (application_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                    status TEXT DEFAULT 'discovered', match_score INTEGER DEFAULT 0,
                    created_at TEXT, updated_at TEXT, sent_at TEXT DEFAULT '',
                    follow_up_at TEXT DEFAULT '', interview_at TEXT DEFAULT '',
                    notes TEXT DEFAULT '', cv_path TEXT DEFAULT '',
                    cover_letter_path TEXT DEFAULT '', email_path TEXT DEFAULT '',
                    history TEXT DEFAULT '[]');
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO meta(key, value) VALUES('schema_version', '2');
                INSERT INTO jobs (job_id, fingerprint, title, company)
                    VALUES ('job-1', 'fp-1', 'Python Engineer', 'Northwind');
                INSERT INTO applications (application_id, job_id, status, created_at, updated_at)
                    VALUES ('app-1', 'job-1', 'sent', '2026-09-01 10:00:00', '2026-09-01 10:00:00');
                """)
            connection.commit()
            connection.close()

            workspace = Workspace(tmp)
            try:
                application = workspace.get_application("app-1")
                self.assertEqual(application.prep, {})
                self.assertEqual(application.prep_path, "")
                application.prep = {"notes": "hello", "questions": []}
                workspace.save_application(application)
                self.assertEqual(workspace.get_application("app-1").prep["notes"], "hello")
                self.assertTrue(workspace.get_application("app-1").has_prep)
                self.assertTrue(workspace.templates_dir.is_dir())
            finally:
                workspace.close()

    def test_corrupt_prep_json_is_tolerated(self):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="jautomatic-badprep-") as tmp:
            workspace = Workspace(tmp)
            try:
                workspace.save_jobs([python_job()])
                job = workspace.jobs()[0]
                workspace.save_application(Application(job_id=job.job_id, application_id="a1"))
                workspace._conn.execute("UPDATE applications SET prep='not json' WHERE application_id='a1'")
                workspace._conn.commit()
                self.assertEqual(workspace.get_application("a1").prep, {})
            finally:
                workspace.close()


class ProfileDataTests(unittest.TestCase):
    def test_sample_profile_yields_star_prompts(self):
        profile = Profile.from_dict(SAMPLE_PROFILE)
        star = [q for q in questions_for(python_job(), profile) if q.question.startswith("Your CV")]
        self.assertTrue(star)
        self.assertTrue(all(q.question.endswith("Take me through it.") for q in star))


if __name__ == "__main__":
    unittest.main()
