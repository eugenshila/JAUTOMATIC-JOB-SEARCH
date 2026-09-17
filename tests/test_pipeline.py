"""Matching, tracking, materials, follow-ups and persistence."""
from __future__ import annotations

import csv
import hashlib
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from jautomatic.models import (
    SAMPLE_PROFILE,
    Application,
    ApplicationStatus,
    AppSettings,
    JobPosting,
    Profile,
    human_join,
    parse_date,
    pretty_term,
    slugify,
    unique_document_path,
)
from jautomatic.services.application_pipeline import (
    ApplicationPipeline,
    filter_min_score,
    match_job,
    min_pay_ok,
    rank_jobs,
)
from jautomatic.services.cover_letter import (
    CoverLetterService,
    MatchContext,
    OllamaError,
    ollama_chat,
)
from tests.support import WorkspaceTestCase


def sample_profile() -> Profile:
    return Profile.from_dict(SAMPLE_PROFILE)


def python_job(**overrides) -> JobPosting:
    data = {
        "source": "remotive", "title": "Senior Python Engineer", "company": "Northwind Analytics",
        "location": "Berlin, Germany", "remote": True, "salary_min": 90000, "salary_max": 110000,
        "currency": "USD", "url": "https://example.com/jobs/python",
        "description": "FastAPI services, PostgreSQL modelling, Docker, AWS, Airflow pipelines. "
                       "Testing with pytest. Kubernetes is a plus.",
        "tags": ["python", "fastapi", "postgresql", "docker", "aws", "airflow", "pytest"],
        "posted_at": date.today().isoformat(),
    }
    data.update(overrides)
    return JobPosting(**data)


def welder_job() -> JobPosting:
    return JobPosting(source="sample", title="Welder (night shift)", company="Steelworks GmbH",
                      location="Duisburg", remote=False, salary_min=32000, salary_max=38000,
                      currency="EUR", url="https://example.com/jobs/welder",
                      description="MIG welding, safety certification, shift work on site.",
                      tags=["welding", "safety"], posted_at=(date.today() - timedelta(days=40)).isoformat())


class WorkspaceTests(WorkspaceTestCase):
    """Uses the shared temp-dir/workspace scaffolding (see tests/support.py)."""

    def test_creates_data_files(self):
        self.assertTrue(self.workspace.db_path.exists())
        self.assertTrue(self.workspace.documents_dir.is_dir())
        self.assertTrue(self.workspace.exports_dir.is_dir())

    def test_close_releases_the_connection_and_is_idempotent(self):
        # This is the contract that keeps temp-dir teardown Windows-safe: the
        # SQLite handle must be gone before the directory is removed (an open
        # handle blocks deletion on Windows - WinError 32), and closing twice
        # must not raise because cleanup paths can overlap.
        self.workspace.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            self.workspace._conn.execute("SELECT 1")
        self.workspace.close()

    def test_job_upsert_deduplicates(self):
        first = self.workspace.save_jobs([python_job()])
        second = self.workspace.save_jobs([python_job(title="Senior Python Developer")])
        self.assertEqual((first, second), (1, 0))
        stored = self.workspace.jobs()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].title, "Senior Python Developer")

    def test_profile_round_trip(self):
        profile = sample_profile()
        self.workspace.save_profile(profile)
        loaded = self.workspace.load_profile()
        self.assertEqual(loaded.full_name, profile.full_name)
        self.assertEqual(len(loaded.experience), len(profile.experience))
        self.assertEqual(loaded.experience[0].highlights, profile.experience[0].highlights)
        self.assertEqual(loaded.skills, profile.skills)

    def test_settings_round_trip_and_defaults(self):
        settings = self.workspace.load_settings()
        self.assertEqual(settings.cv_template, "modern")
        settings.cv_template = "compact"
        settings.enabled_sources = ["sample"]
        self.workspace.save_settings(settings)
        again = self.workspace.load_settings()
        self.assertEqual(again.cv_template, "compact")
        self.assertEqual(again.enabled_sources, ["sample"])
        self.assertEqual(again.data_dir, str(self.workspace.root))


class ThreadSafetyTests(WorkspaceTestCase):
    """The UI imports/generates on a thread pool, so the workspace must cope."""

    def test_concurrent_writes_from_many_threads(self):
        import concurrent.futures as futures

        def worker(index: int) -> int:
            job = python_job(url=f"https://example.com/jobs/{index}",
                             title=f"Backend Engineer {index}")
            self.workspace.save_jobs([job])
            application = self.workspace.application_for_job(job.job_id)
            if application is None:
                application = Application(job_id=job.job_id)
            self.workspace.save_application(application)
            self.workspace.get_application(application.application_id)
            return len(self.workspace.jobs())

        with futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(worker, range(24)))
        self.assertEqual(self.workspace.job_count(), 24)
        self.assertEqual(len(self.workspace.applications()), 24)
        self.assertEqual(max(results), 24)


class MatchingTests(unittest.TestCase):
    def test_strong_match_scores_high(self):
        result = match_job(sample_profile(), python_job())
        self.assertGreaterEqual(result.score, 80)
        self.assertIn(result.grade, ("strong", "excellent"))
        self.assertTrue(result.matched_keywords)
        self.assertTrue(any("keywords" in r for r in result.reasons))

    def test_unrelated_job_scores_low(self):
        result = match_job(sample_profile(), welder_job())
        self.assertLess(result.score, 55)
        self.assertIn(result.grade, ("weak", "possible"))

    def test_salary_below_floor_is_penalised(self):
        cheap = python_job(salary_min=30000, salary_max=40000, currency="USD")
        result = match_job(sample_profile(), cheap)
        self.assertFalse(result.salary_fit)
        self.assertTrue(any("below your floor" in r for r in result.reasons))
        self.assertLess(result.score, match_job(sample_profile(), python_job()).score)

    def test_stale_posting_loses_freshness_points(self):
        fresh = match_job(sample_profile(), python_job())
        old = match_job(sample_profile(), python_job(posted_at=(date.today() -
                                                              timedelta(days=90)).isoformat()))
        self.assertGreater(fresh.score, old.score)

    def test_location_mismatch_is_flagged(self):
        onsite = python_job(remote=False, location="Sydney, Australia")
        result = match_job(sample_profile(), onsite)
        self.assertFalse(result.location_fit)

    def test_ranking_is_sorted(self):
        ranked = rank_jobs(sample_profile(), [welder_job(), python_job()])
        self.assertEqual(ranked[0][0].title, "Senior Python Engineer")
        self.assertGreaterEqual(ranked[0][1].score, ranked[1][1].score)

    def test_min_match_filter_drops_weak_results(self):
        ranked = rank_jobs(sample_profile(), [welder_job(), python_job()])
        kept = filter_min_score(ranked, 70)
        self.assertEqual([job.title for job, _ in kept], ["Senior Python Engineer"])
        self.assertTrue(all(match.score >= 70 for _, match in kept))

    def test_min_match_filter_zero_and_absent_keep_everything(self):
        ranked = rank_jobs(sample_profile(), [welder_job(), python_job()])
        self.assertEqual(filter_min_score(ranked, 0), ranked)
        self.assertEqual(filter_min_score(ranked), ranked)
        self.assertEqual(filter_min_score(ranked, -5), ranked)
        self.assertEqual(filter_min_score([], 70), [])

    def test_empty_profile_does_not_crash(self):
        result = match_job(Profile(), python_job())
        self.assertIsInstance(result.score, int)
        self.assertTrue(0 <= result.score <= 100)

    def test_missed_headline_requirements_cap_below_possible(self):
        # The posting reads like a perfect Python match, but its stated headline
        # requirements (tags) appear nowhere in the profile: 70+ must be out of reach.
        job = python_job(tags=["welding", "carpentry"])
        result = match_job(sample_profile(), job)
        self.assertLessEqual(result.score, 49)
        self.assertTrue(any("headline requirements" in r for r in result.reasons))

    def test_location_mismatch_cap_holds_below_seventy(self):
        # Deal-breaker (can't/ won't commute) means the job can never read as "qualified".
        onsite = python_job(remote=False, location="Sydney, Australia")
        result = match_job(sample_profile(), onsite)
        self.assertFalse(result.location_fit)
        self.assertLess(result.score, 70)

    def test_below_floor_salary_cap_holds_below_seventy(self):
        cheap = python_job(salary_min=30000, salary_max=40000, currency="USD")
        result = match_job(sample_profile(), cheap)
        self.assertFalse(result.salary_fit)
        self.assertLess(result.score, 70)

    def test_single_matching_headline_requirement_clears_gate(self):
        job = python_job(tags=["python", "welding", "carpentry"])
        result = match_job(sample_profile(), job)
        self.assertGreaterEqual(result.score, 70)

    def test_qualified_job_with_partial_coverage_still_crosses_seventy(self):
        # A real posting names skills the profile does not own. Covering the
        # posting's own headline requirements (tags) must still reach 70+.
        noisy = " ".join([
            "atomic habits", "lean startup", "regression sprint", "data modeling",
            "event sourcing", "observability", "chron jobs", "feature flags",
            "canary releases", "blue green deploys", "graceful degradation", "idempotency"])
        job = python_job(description=python_job().description + " " + noisy)
        result = match_job(sample_profile(), job)
        self.assertGreaterEqual(result.score, 70)
        self.assertLess(result.score, match_job(sample_profile(), python_job()).score)


class MinPayFilterTests(unittest.TestCase):
    def _job(self, low: int = 0, high: int = 0, currency: str = "USD") -> JobPosting:
        return JobPosting(source="tasks", title="Audio transcription", company="Board",
                          location="Remote", remote=True, salary_min=low, salary_max=high,
                          currency=currency, url="https://example.com/tasks/1",
                          description="Transcribe short audio clips.", tags=["audio"],
                          posted_at=date.today().isoformat())

    def test_floor_zero_or_absent_accepts_everything(self):
        job = self._job(low=1, high=2)
        self.assertTrue(min_pay_ok(job, 0))
        self.assertTrue(min_pay_ok(job))
        self.assertTrue(min_pay_ok(job, -5))
        self.assertTrue(min_pay_ok(None, 10))
        self.assertTrue(min_pay_ok([], 10))

    def test_usd_at_or_above_floor(self):
        self.assertTrue(min_pay_ok(self._job(low=10, high=25), 10))
        self.assertTrue(min_pay_ok(self._job(low=12, high=18), 10))
        self.assertTrue(min_pay_ok(self._job(low=0, high=12), 10))

    def test_quoted_range_is_judged_by_its_low_end(self):
        self.assertFalse(min_pay_ok(self._job(low=8, high=45), 10))

    def test_below_floor_is_rejected(self):
        self.assertFalse(min_pay_ok(self._job(low=8, high=9), 10))
        self.assertFalse(min_pay_ok(self._job(low=0, high=0), 10))

    def test_non_usd_is_rejected_even_when_high(self):
        self.assertFalse(min_pay_ok(self._job(low=12000, high=15000, currency="EUR"), 10))
        self.assertFalse(min_pay_ok(self._job(low=12000, high=15000, currency=""), 10))


class PipelineTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.workspace.save_profile(sample_profile())
        self.settings = self.workspace.load_settings()
        self.settings.export_format = "docx"
        self.workspace.save_settings(self.settings)
        self.pipeline = ApplicationPipeline(self.workspace, self.settings)
        self.profile = self.workspace.load_profile()

    def _tracked(self, job: JobPosting | None = None):
        job = job or python_job()
        application = self.pipeline.ensure_application(job)
        return self.pipeline.tracker(self.profile)[0] if application else None

    def test_search_and_import_creates_tracker_rows(self):
        outcome, created = self.pipeline.search_and_import("python", sources=["sample"],
                                                           limit_per_source=4)
        self.assertTrue(outcome.jobs)
        self.assertEqual(len(created), len(outcome.jobs))
        self.assertEqual(len(self.pipeline.tracker(self.profile)), len(outcome.jobs))
        # importing again must not duplicate
        again = self.pipeline.import_jobs(outcome.jobs)
        self.assertEqual(again, [])
        self.assertEqual(len(self.pipeline.tracker(self.profile)), len(outcome.jobs))

    def test_import_qualified_queues_only_threshold_hits(self):
        good = python_job(url="https://example.com/jobs/good")
        weak = welder_job()
        rows, created = self.pipeline.import_qualified(
            [good, weak], self.profile, threshold=70)
        self.assertEqual(len(rows), 2)
        self.assertEqual([a.job_id for a in created], [good.job_id])
        tracked = {a.job_id for a in self.workspace.applications()}
        self.assertEqual(tracked, {good.job_id})

    def test_import_qualified_with_track_false_adds_nothing(self):
        rows, created = self.pipeline.import_qualified(
            [python_job(), welder_job()], self.profile, threshold=70, track=False)
        self.assertEqual(len(rows), 2)
        self.assertEqual(created, [])
        self.assertEqual(self.workspace.applications(), [])

    def test_import_qualified_zero_threshold_keeps_everything(self):
        _, created = self.pipeline.import_qualified(
            [python_job(), welder_job()], self.profile, threshold=0)
        self.assertEqual(len(created), 2)

    def test_import_review_tracks_below_bar_as_proposed(self):
        good = python_job(url="https://example.com/jobs/good")
        weak = welder_job()
        rows, created = self.pipeline.import_qualified(
            [good, weak], self.profile, threshold=70)
        self.assertEqual([a.job_id for a in created], [good.job_id])
        reviewed = self.pipeline.import_review([weak])
        self.assertEqual([a.job_id for a in reviewed], [weak.job_id])
        app = self.workspace.application_for_job(weak.job_id)
        self.assertEqual(app.status_enum, ApplicationStatus.PROPOSED)
        self.assertEqual(self.pipeline.import_review([weak]), [])

    def test_qualified_import_promotes_previous_proposals(self):
        job = python_job(url="https://example.com/jobs/promote")
        self.pipeline.import_review([job])
        self.assertEqual(self.workspace.application_for_job(
            job.job_id).status_enum, ApplicationStatus.PROPOSED)
        _, created = self.pipeline.import_qualified([job], self.profile, threshold=70)
        self.assertIn(job.job_id, [a.job_id for a in created])
        self.assertEqual(self.workspace.application_for_job(
            job.job_id).status_enum, ApplicationStatus.DISCOVERED)
        history = self.workspace.application_for_job(job.job_id).history
        notes = [e.get("note", "") for e in history]
        self.assertTrue(any("meets the qualification bar" in n for n in notes))

    def test_prepare_generates_documents_and_moves_status(self):
        row = self._tracked()
        materials = self.pipeline.prepare(row.application, self.profile)
        self.assertTrue(materials.cv.path.exists())
        self.assertTrue(materials.cover_letter.path.exists())
        self.assertTrue(materials.email.path.exists())
        self.assertIn("Alex Doe", materials.cv.text)
        self.assertIn("Northwind Analytics", materials.cover_letter.text)
        self.assertIn("Subject:", materials.email.text)
        refreshed = self.workspace.get_application(materials.application.application_id)
        self.assertEqual(refreshed.status_enum, ApplicationStatus.MATERIALS_READY)
        self.assertGreater(refreshed.match_score, 0)
        statuses = [event.get("to") for event in refreshed.history if event["event"] == "status"]
        self.assertIn("shortlisted", statuses)
        self.assertIn("materials_ready", statuses)

    def test_prepare_can_skip_cover_letter_and_email(self):
        row = self._tracked()
        materials = self.pipeline.prepare(row.application, self.profile,
                                          with_cover_letter=False, with_email=False)
        self.assertIsNone(materials.cover_letter)
        self.assertIsNone(materials.email)
        self.assertTrue(materials.cv.path.exists())
        self.assertEqual(self.workspace.get_application(
            row.application.application_id).cover_letter_path, "")

    def test_colliding_slugs_never_overwrite_each_other(self):
        # "AT&T" and "AT T" both slugify to "at-t" — historically the second
        # application's CV overwrote the first one's.
        job_a = python_job(company="AT&T", title="Platform Engineer",
                           url="https://example.com/jobs/at-and-t")
        job_b = python_job(company="AT T", title="Platform Engineer",
                           url="https://example.com/jobs/at-t")
        app_a = self.pipeline.ensure_application(job_a)
        app_b = self.pipeline.ensure_application(job_b)
        materials_a = self.pipeline.prepare(app_a, self.profile, fmt="md")
        materials_b = self.pipeline.prepare(app_b, self.profile, fmt="md")
        for doc_a, doc_b in ((materials_a.cv, materials_b.cv),
                             (materials_a.cover_letter, materials_b.cover_letter),
                             (materials_a.email, materials_b.email)):
            self.assertNotEqual(doc_a.path, doc_b.path)
            self.assertTrue(doc_a.path.exists(), doc_a.path)
            self.assertTrue(doc_b.path.exists(), doc_b.path)
        # the loser of the tie gets the hash-disambiguated name; both keep their content
        self.assertRegex(materials_b.cv.path.stem, r"-[0-9a-f]{4}$")
        self.assertIn("AT&T", materials_a.cv.path.read_text("utf-8"))
        self.assertIn("AT T", materials_b.cv.path.read_text("utf-8"))
        record_a = self.workspace.get_application(app_a.application_id)
        record_b = self.workspace.get_application(app_b.application_id)
        self.assertEqual(record_a.cv_path, str(materials_a.cv.path))
        self.assertEqual(record_b.cv_path, str(materials_b.cv.path))

    def test_fully_non_latin_names_do_not_all_land_on_untitled(self):
        # CJK company names slugify to "" -> "untitled": the classic mass collision.
        job_a = python_job(company="株式会社アルファ", title="バックエンドエンジニア",
                           url="https://example.com/jobs/alpha")
        job_b = python_job(company="株式会社ベータ", title="バックエンドエンジニア",
                           url="https://example.com/jobs/beta")
        materials_a = self.pipeline.prepare(self.pipeline.ensure_application(job_a),
                                            self.profile, fmt="md")
        materials_b = self.pipeline.prepare(self.pipeline.ensure_application(job_b),
                                            self.profile, fmt="md")
        self.assertIn("untitled", materials_a.cv.path.stem)
        self.assertNotEqual(materials_a.cv.path, materials_b.cv.path)
        self.assertTrue(materials_a.cv.path.exists())
        self.assertTrue(materials_b.cv.path.exists())

    def test_regenerating_materials_updates_the_same_files_in_place(self):
        row = self._tracked()
        first = self.pipeline.prepare(row.application, self.profile, fmt="md")
        before = sorted(path.name for path in self.workspace.documents_dir.iterdir())
        second = self.pipeline.prepare(row.application, self.profile, fmt="md")
        after = sorted(path.name for path in self.workspace.documents_dir.iterdir())
        self.assertEqual(first.cv.path, second.cv.path)
        self.assertEqual(first.cover_letter.path, second.cover_letter.path)
        self.assertEqual(first.email.path, second.email.path)
        self.assertEqual(before, after)  # no hash-suffixed copies of our own files
        refreshed = self.workspace.get_application(row.application.application_id)
        self.assertEqual(refreshed.cv_path, str(second.cv.path))

    def test_search_and_import_drops_the_import_when_cancelled_midway(self):
        # First cancel poll (inside the scraper) says "keep going", the second
        # (after the fetch, before the import) says "closing" — then nothing may
        # be written to a workspace that is about to close.
        answers = iter([False])  # scraper says "go"; the post-fetch check says "closing"
        outcome, created = self.pipeline.search_and_import(
            "python", sources=["sample"], limit_per_source=3,
            should_cancel=lambda: next(answers, True))
        self.assertTrue(outcome.jobs)          # the fetch itself completed
        self.assertEqual(created, [])          # ... but the import was refused
        self.assertEqual(self.pipeline.tracker(self.profile), [])

    def test_prepare_batch_stops_between_rows_when_cancelled(self):
        self.pipeline.ensure_application(python_job(url="https://example.com/jobs/one"))
        self.pipeline.ensure_application(python_job(company="Kestrel Logistics",
                                                    url="https://example.com/jobs/two"))
        rows = self.pipeline.tracker(self.profile)
        self.assertEqual(len(rows), 2)
        answers = iter([False, True])  # first row proceeds, second is skipped
        materials = self.pipeline.prepare_batch(rows, self.profile,
                                                should_cancel=lambda: next(answers, True))
        self.assertEqual(len(materials), 1)

    def test_template_and_format_options_are_honoured(self):
        row = self._tracked()
        materials = self.pipeline.prepare(row.application, self.profile, template="classic",
                                          fmt="md")
        self.assertEqual(materials.cv.path.suffix, ".md")
        self.assertIn("PROFESSIONAL SUMMARY", materials.cv.text)

    def test_status_transitions_log_history_and_schedule_follow_up(self):
        row = self._tracked()
        application = self.pipeline.set_status(row.application, ApplicationStatus.SENT, "applied")
        self.assertEqual(application.status_enum, ApplicationStatus.SENT)
        self.assertTrue(application.sent_at)
        self.assertTrue(application.follow_up_at)
        expected = (date.today() + timedelta(days=self.settings.follow_up_days)).isoformat()
        self.assertEqual(application.follow_up_at, expected)
        status_events = [event for event in application.history if event["event"] == "status"]
        self.assertEqual(status_events[-1]["to"], "sent")
        self.assertIn("follow-up scheduled", application.history[-1]["event"])

    def test_follow_up_due_and_drafting(self):
        row = self._tracked()
        application = self.pipeline.set_status(row.application, ApplicationStatus.SENT)
        application.follow_up_at = (date.today() - timedelta(days=1)).isoformat()
        self.workspace.save_application(application)
        due = self.pipeline.follow_ups_due(self.profile)
        self.assertEqual(len(due), 1)
        path, text = self.pipeline.draft_follow_up(application)
        self.assertTrue(path.exists())
        self.assertIn("Following up", text)
        self.assertIn("Northwind Analytics", text)

    def test_postponing_follow_up_clears_dueness(self):
        row = self._tracked()
        application = self.pipeline.set_status(row.application, ApplicationStatus.SENT)
        application.follow_up_at = (date.today() - timedelta(days=2)).isoformat()
        self.workspace.save_application(application)
        self.pipeline.postpone_follow_up(application, 5)
        self.assertEqual(self.pipeline.follow_ups_due(self.profile), [])

    def test_follow_up_ladder_escalates_and_ends(self):
        self.settings.follow_up_repeat_days = 5
        self.settings.follow_up_max_nudges = 3
        row = self._tracked()
        application = self.pipeline.set_status(row.application, ApplicationStatus.SENT)
        application.follow_up_at = (date.today() - timedelta(days=1)).isoformat()
        self.workspace.save_application(application)

        first_path, first_text = self.pipeline.draft_follow_up(application)
        stored = self.workspace.get_application(application.application_id)
        self.assertEqual(stored.follow_up_count, 1)
        self.assertIn("Following up", first_text)
        self.assertEqual(stored.follow_up_at,
                         (date.today() + timedelta(days=5)).isoformat())

        stored.follow_up_at = (date.today() - timedelta(days=1)).isoformat()
        self.workspace.save_application(stored)
        second_path, second_text = self.pipeline.draft_follow_up(stored)
        self.assertIn("Still interested", second_text)
        self.assertNotEqual(first_path.name, second_path.name)

        stored = self.workspace.get_application(application.application_id)
        stored.follow_up_at = (date.today() - timedelta(days=1)).isoformat()
        self.workspace.save_application(stored)
        third_path, third_text = self.pipeline.draft_follow_up(stored)
        self.assertIn("last follow-up", third_text)
        finished = self.workspace.get_application(application.application_id)
        self.assertEqual(finished.follow_up_count, 3)
        self.assertEqual(finished.follow_up_at, "")          # ladder spent: no more "due"
        self.assertFalse(self.pipeline.follow_ups_due(self.profile))

    def test_interview_offer_or_closed_stops_follow_ups(self):
        row = self._tracked()
        application = self.pipeline.set_status(row.application, ApplicationStatus.SENT)
        application.follow_up_at = (date.today() + timedelta(days=3)).isoformat()
        self.workspace.save_application(application)
        self.pipeline.set_status(application, ApplicationStatus.INTERVIEW, "booked")
        stored = self.workspace.get_application(application.application_id)
        self.assertEqual(stored.follow_up_at, "")
        self.assertFalse(stored.follow_up_due)
        # ... and rejected/archived do the same
        other = self.pipeline.set_status(row.application, ApplicationStatus.SENT)
        other.follow_up_at = (date.today() + timedelta(days=3)).isoformat()
        self.workspace.save_application(other)
        self.pipeline.set_status(other, ApplicationStatus.REJECTED, "not a fit")
        self.assertEqual(self.workspace.get_application(
            other.application_id).follow_up_at, "")

    def test_analytics_shape_and_funnel(self):
        self.pipeline.import_jobs([python_job(), python_job(title="Data Engineer", company="Helio",
                                                            url="https://example.com/jobs/heli"),
                                   welder_job()])
        first, second = self.workspace.applications()[0], self.workspace.applications()[1]
        self.pipeline.set_status(first, ApplicationStatus.SENT)
        self.pipeline.set_status(second, ApplicationStatus.SENT)
        self.pipeline.set_status(second, ApplicationStatus.INTERVIEW, "booked")

        data = self.pipeline.analytics(self.profile)
        self.assertEqual([row["value"] for row in data["funnel"]], [3, 2, 1, 0])
        self.assertEqual([row["label"] for row in data["funnel"]],
                         ["Tracked", "Sent", "Interview", "Offer"])
        self.assertEqual(data["rates"]["response"], 50.0)
        self.assertEqual(data["rates"]["interview"], 50.0)
        self.assertEqual(data["rates"]["offer"], 0.0)
        self.assertEqual(len(data["weekly"]), 8)
        self.assertEqual(sum(row["created"] for row in data["weekly"]), 3)
        self.assertEqual(len(data["score_buckets"]), 4)
        self.assertEqual(sum(row["count"] for row in data["score_buckets"]), 3)
        self.assertEqual(sum(row["count"] for row in data["by_source"]), 3)
        # the only reply so far is today's interview: one row, zero days
        self.assertEqual(len(data["response_times"]), 1)
        title, company, days, outcome = data["response_times"][0]
        self.assertEqual(outcome, "Interview")
        self.assertEqual(days, 0)
        self.assertTrue(company)

    def test_market_intelligence_counts_tags_and_flags_profile_gaps(self):
        self.pipeline.import_jobs([python_job(),
                                   python_job(title="Data Engineer", company="Helio",
                                              url="https://example.com/jobs/heli")])
        data = self.pipeline.market_intelligence(self.profile)
        tags = {row["tag"]: row for row in data}
        self.assertIn("fastapi", tags)
        self.assertEqual(tags["fastapi"]["count"], 2)
        self.assertEqual(tags["fastapi"]["titles"], ["Data Engineer", "Senior Python Engineer"])
        self.assertIsInstance(tags["fastapi"]["have"], bool)
        # every tag advertised by both postings is "most demanded" on top
        self.assertEqual(data[0]["count"], 2)
        # short and generic terms (remote, etc.) never show up
        self.assertEqual(len(data), 7)
        self.assertNotIn("remote", tags)
        self.assertTrue(all(len(row["tag"]) >= 3 for row in data))
        # non-empty search space: market covers only postings already stored
        self.assertEqual(self.pipeline.market_intelligence(self.profile, limit=2),
                         data[:2])

    def test_import_from_url_tracks_once_and_refreshes_duplicates(self):
        from unittest import mock

        expected = python_job(url="https://example.com/jobs/pasted", source="manual")
        with mock.patch("jautomatic.services.job_scraper.posting_from_url",
                        return_value=expected) as scrape:
            application, created = self.pipeline.import_from_url(
                "https://example.com/jobs/pasted")
        scrape.assert_called_once()
        self.assertTrue(created)
        self.assertEqual(self.pipeline.tracker(self.profile)[0].job.url, expected.url)

        # the same URL again must refresh the posting, never add a second entry
        refreshed = python_job(url="https://example.com/jobs/pasted", source="manual",
                               description="Now with a rewritten description.")
        with mock.patch("jautomatic.services.job_scraper.posting_from_url",
                        return_value=refreshed):
            again, was_created = self.pipeline.import_from_url(
                "https://example.com/jobs/pasted")
        self.assertFalse(was_created)
        self.assertEqual(again.application_id, application.application_id)
        self.assertEqual(len(self.workspace.applications()), 1)
        stored = self.workspace.get_job(expected.job_id)
        self.assertIn("rewritten", stored.description)

    def test_notes_and_manual_status_are_persisted(self):
        row = self._tracked()
        self.pipeline.update_notes(row.application, "Recruiter call on Thursday.")
        self.pipeline.set_status(row.application, ApplicationStatus.INTERVIEW, "booked")
        stored = self.workspace.get_application(row.application.application_id)
        self.assertEqual(stored.notes, "Recruiter call on Thursday.")
        self.assertEqual(stored.status_enum, ApplicationStatus.INTERVIEW)

    def test_autopilot_respects_threshold_and_limit(self):
        self.pipeline.import_jobs([python_job(), python_job(title="Data Engineer",
                                                            company="Helio"),
                                   welder_job()])
        self.settings.autopilot_min_score = 60
        self.settings.autopilot_max_per_run = 1
        prepared = self.pipeline.autopilot(self.profile)
        self.assertEqual(len(prepared), 1)
        self.assertGreaterEqual(prepared[0].application.match_score, 60)
        self.assertTrue(prepared[0].cv.path.exists())

    def test_refresh_scores_updates_stored_scores(self):
        target = self.pipeline.ensure_application(
            python_job(url="https://example.com/jobs/other", salary_min=85000, salary_max=120000,
                       title="Junior Support Engineer", company="Helpdesk Co"))
        self.pipeline.prepare(target, self.profile)
        stored_before = {a.application_id: a.match_score for a in self.workspace.applications()}
        # the profile gains every keyword the postings ask for -> scores must rise
        profile = self.profile
        profile.skills += ["kubernetes", "pytest", "airflow", "golang", "grpc"]
        profile.desired_titles += ["Junior Support Engineer"]
        self.workspace.save_profile(profile)
        updated = self.pipeline.refresh_scores(profile)
        stored_after = {a.application_id: a.match_score for a in self.workspace.applications()}
        self.assertGreater(updated, 0)
        self.assertNotEqual(stored_before, stored_after)

    def test_csv_export_contains_rows(self):
        self.pipeline.import_jobs([python_job()])
        path = self.pipeline.export_tracker_csv(self.profile)
        self.assertTrue(path.exists())
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Company"], "Northwind Analytics")
        self.assertIn("Score", rows[0])

    def test_dashboard_stats_shape(self):
        self.pipeline.import_jobs([python_job()])
        stats = self.pipeline.dashboard_stats(self.profile)
        for key in ("jobs", "applications", "by_status", "follow_ups_due", "profile_completeness",
                    "top_matches", "response_rate"):
            self.assertIn(key, stats)
        self.assertEqual(stats["profile_completeness"], 100)

    def test_unknown_application_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.pipeline.prepare("no-such-application", self.profile)

    def test_application_requires_a_stored_job(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.workspace.save_application(Application(job_id="does-not-exist"))

    def test_delete_application_keeps_job(self):
        row = self._tracked()
        self.workspace.delete_application(row.application.application_id)
        self.assertEqual(self.pipeline.tracker(self.profile), [])
        self.assertEqual(self.workspace.job_count(), 1)

    def test_status_is_coerced_from_unknown_value(self):
        application = Application(job_id="x", status="banana")
        self.assertEqual(application.status_enum, ApplicationStatus.DISCOVERED)


class OllamaCoverLetterTests(WorkspaceTestCase):
    """Local LLM drafting: chat plumbing, prompt, and template fallback."""

    def setUp(self):
        super().setUp()
        self.workspace.save_profile(sample_profile())
        self.pipeline = ApplicationPipeline(self.workspace, self.workspace.load_settings())
        self.profile = self.workspace.load_profile()
        self.job = python_job()

    def _mock_post(self, payload_to_return, status=200):
        from unittest import mock

        response = mock.Mock()
        response.status_code = status
        response.json.return_value = payload_to_return
        return mock.patch("requests.post", return_value=response)

    def test_ollama_chat_builds_the_chat_request(self):
        with self._mock_post({"message": {"content": "  A fine letter.  "}}) as post:
            result = ollama_chat("http://localhost:11434", "llama3.2", "Dear team…", 90)
        self.assertEqual(result, "A fine letter.\n")
        url, kwargs = post.call_args
        self.assertTrue(url[0].endswith("/api/chat"))
        self.assertEqual(kwargs["json"]["model"], "llama3.2")
        self.assertEqual(kwargs["json"]["messages"][0]["content"], "Dear team…")
        self.assertEqual(kwargs["json"]["stream"], False)

    def test_ollama_chat_raises_on_an_error_status(self):
        with self.assertRaisesRegex(OllamaError, "HTTP 500"):
            with self._mock_post({}, status=500):
                ollama_chat("http://localhost:11434", "llama3.2", "x")

    def test_ollama_chat_raises_when_unreachable(self):
        from unittest import mock

        import requests

        with mock.patch("requests.post",
                        side_effect=requests.exceptions.ConnectionError("connection refused")):
            with self.assertRaises(OllamaError):
                ollama_chat("http://localhost:11434", "llama3.2", "x")

    def test_generate_uses_ollama_when_enabled(self):
        from unittest import mock

        with mock.patch("jautomatic.services.cover_letter.ollama_cover_letter",
                        return_value="An AI letter.\n") as draft:
            document = CoverLetterService().generate(
                self.profile, self.job, MatchContext(), "professional",
                llm={"model": "llama3.2", "base_url": "http://localhost:11434", "timeout": 60})
        draft.assert_called_once()
        self.assertEqual(document.text, "An AI letter.\n")
        self.assertEqual(document.warning, "")

    def test_generate_falls_back_to_template_on_ollama_error(self):
        from unittest import mock

        with mock.patch("jautomatic.services.cover_letter.ollama_cover_letter",
                        side_effect=OllamaError("offline")):
            document = CoverLetterService().generate(
                self.profile, self.job, MatchContext(), "professional",
                llm={"model": "llama3.2", "base_url": "http://localhost:11434"})
        self.assertIn("I am applying for the Senior Python Engineer position", document.text)
        self.assertIn("template instead", document.warning)

    def test_prepare_uses_ollama_when_provider_configured(self):
        from unittest import mock

        self.pipeline.settings.llm_provider = "ollama"
        self.pipeline.settings.llm_model = "mistral-nemo"
        self.pipeline.scraper.settings = self.pipeline.settings
        row = self._tracked()
        with mock.patch("jautomatic.services.cover_letter.ollama_cover_letter",
                        return_value="Local-model letter body.\n") as draft:
            materials = self.pipeline.prepare(row.application, self.profile)
        draft.assert_called_once()
        self.assertEqual(materials.cover_letter.text, "Local-model letter body.\n")
        self.assertTrue(materials.cover_letter.path.exists())
        self.assertEqual(materials.cover_letter.warning, "")

    def test_prepare_falls_back_when_ollama_is_off(self):
        from unittest import mock

        self.pipeline.settings.llm_provider = "ollama"
        self.pipeline.scraper.settings = self.pipeline.settings
        row = self._tracked()
        with mock.patch("jautomatic.services.cover_letter.ollama_cover_letter",
                        side_effect=OllamaError("offline")):
            materials = self.pipeline.prepare(row.application, self.profile)
        self.assertIn("I am applying for the Senior Python Engineer position",
                      materials.cover_letter.text)
        self.assertIn("template instead", materials.cover_letter.warning)
        self.assertTrue(materials.cover_letter.path.exists())

    def _tracked(self):
        application = self.pipeline.ensure_application(self.job)
        return self.pipeline.tracker(self.profile)[0] if application else None


class ModelHelperTests(unittest.TestCase):
    def test_human_join(self):
        self.assertEqual(human_join(["a", "b"]), "a and b")
        self.assertEqual(human_join(["a", "b", "c"]), "a, b and c")
        self.assertEqual(human_join([]), "")

    def test_pretty_term(self):
        self.assertEqual(pretty_term("fastapi"), "FastAPI")
        self.assertEqual(pretty_term("postgresql"), "PostgreSQL")
        self.assertEqual(pretty_term("customer success"), "Customer Success")
        self.assertEqual(pretty_term("figma"), "Figma")

    def test_slugify(self):
        self.assertEqual(slugify("Senior Python Engineer / Berlin"), "senior-python-engineer-berlin")
        self.assertEqual(slugify(""), "untitled")

    def test_unique_document_path_prefers_the_plain_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = unique_document_path(tmp, "CV_alice_acme_dev", ".docx", key="cv|alice|acme|dev")
            self.assertEqual(path.name, "CV_alice_acme_dev.docx")

    def test_unique_document_path_hashes_on_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            taken = Path(tmp) / "CV_alice_acme_dev.docx"
            taken.write_text("old", encoding="utf-8")
            path = unique_document_path(tmp, "CV_alice_acme_dev", ".docx", key="cv|alice|acme|dev")
            digest = hashlib.sha1(b"cv|alice|acme|dev").hexdigest()[:4]
            self.assertEqual(path.name, f"CV_alice_acme_dev-{digest}.docx")
            self.assertEqual(taken.read_text(encoding="utf-8"), "old")  # never clobbered
            # deterministic: same key again -> same hashed name
            again = unique_document_path(tmp, "CV_alice_acme_dev", ".docx", key="cv|alice|acme|dev")
            self.assertEqual(again, path)
            # different un-slugified identity -> different suffix
            other = unique_document_path(tmp, "CV_alice_acme_dev", ".docx", key="cv|alice|at t|dev")
            self.assertNotEqual(other.name, path.name)

    def test_unique_document_path_counts_past_digest_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = "cv|alice|acme|dev"
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:4]
            stem = "CV_alice_acme_dev"
            for name in (f"{stem}.docx", f"{stem}-{digest}.docx", f"{stem}-{digest}-2.docx"):
                (Path(tmp) / name).write_text("x", encoding="utf-8")
            path = unique_document_path(tmp, stem, ".docx", key=key)
            self.assertEqual(path.name, f"{stem}-{digest}-3.docx")

    def test_unique_document_path_reuse_wins_outright(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path(tmp) / "CV_alice_acme_dev.docx"
            path = unique_document_path(tmp, "CV_alice_acme_dev", ".docx",
                                        key="cv|alice|acme|dev", reuse=previous)
            self.assertEqual(path, previous)  # regenerating updates in place
            # ... even if the file was deleted meanwhile
            path = unique_document_path(tmp, "CV_alice_acme_dev", ".docx",
                                        key="cv|alice|acme|dev", reuse=str(previous))
            self.assertEqual(path, previous)

    def test_parse_date_variants(self):
        self.assertEqual(parse_date("2026-09-09T08:12:44").isoformat(), "2026-09-09")
        self.assertEqual(parse_date(1789000000).year, 2026)
        self.assertEqual(parse_date("09/09/2026").isoformat(), "2026-09-09")
        self.assertIsNone(parse_date(""))

    def test_job_salary_text_and_age(self):
        job = python_job(salary_min=0, salary_max=0)
        self.assertEqual(job.salary_text, "Not disclosed")
        self.assertEqual(python_job().posted_text, "today")
        self.assertEqual(python_job(salary_min=90000, salary_max=0).salary_text, "$90,000 USD")

    def test_experience_entry_bullets_fall_back_to_summary(self):
        from jautomatic.models import ExperienceEntry
        entry = ExperienceEntry(summary="First thing. Second thing.")
        self.assertEqual(entry.as_bullets(), ["First thing.", "Second thing."])
        self.assertEqual(entry.period, "? – present")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class ClearTests(WorkspaceTestCase):
    """Archive/clear and auto-clear of unacted applications."""

    def _make_application(self, job, *, created_at: str, status: str = "discovered") -> Application:
        app = Application(job_id=job.job_id, created_at=created_at, status=status)
        return self.workspace.save_application(app)

    def test_clear_application(self):
        pipeline = ApplicationPipeline(self.workspace, AppSettings())
        job = python_job()
        self.workspace.save_jobs([job])
        app = self._make_application(job, created_at=date.today().isoformat() + " 00:00:00")
        pipeline.clear_application(app)
        loaded = self.workspace.get_application(app.application_id)
        self.assertEqual(loaded.status, ApplicationStatus.ARCHIVED.value)

    def test_auto_clear_archives_stale_unacted(self):
        old_created = (date.today() - timedelta(days=10)).isoformat() + " 00:00:00"
        pipeline = ApplicationPipeline(self.workspace, AppSettings(auto_clear_days=5))
        job = python_job()
        self.workspace.save_jobs([job])
        app = self._make_application(job, created_at=old_created)
        pipeline.auto_clear_unacted()
        loaded = self.workspace.get_application(app.application_id)
        self.assertEqual(loaded.status, ApplicationStatus.ARCHIVED.value)

    def test_auto_clear_keeps_recent(self):
        recent_created = date.today().isoformat() + " 00:00:00"
        pipeline = ApplicationPipeline(self.workspace, AppSettings(auto_clear_days=5))
        job = python_job()
        self.workspace.save_jobs([job])
        app = self._make_application(job, created_at=recent_created)
        pipeline.auto_clear_unacted()
        loaded = self.workspace.get_application(app.application_id)
        self.assertEqual(loaded.status, ApplicationStatus.DISCOVERED.value)

    def test_auto_clear_keeps_acted(self):
        old_created = (date.today() - timedelta(days=20)).isoformat() + " 00:00:00"
        pipeline = ApplicationPipeline(self.workspace, AppSettings(auto_clear_days=5))
        job = python_job()
        self.workspace.save_jobs([job])
        app = self._make_application(job, created_at=old_created, status="materials_ready")
        pipeline.auto_clear_unacted()
        loaded = self.workspace.get_application(app.application_id)
        self.assertEqual(loaded.status, ApplicationStatus.MATERIALS_READY.value)

    def test_auto_clear_disabled_when_zero(self):
        old_created = (date.today() - timedelta(days=30)).isoformat() + " 00:00:00"
        pipeline = ApplicationPipeline(self.workspace, AppSettings(auto_clear_days=0))
        job = python_job()
        self.workspace.save_jobs([job])
        app = self._make_application(job, created_at=old_created)
        self.assertEqual(pipeline.auto_clear_unacted(), 0)
        loaded = self.workspace.get_application(app.application_id)
        self.assertEqual(loaded.status, ApplicationStatus.DISCOVERED.value)

    def test_auto_clear_returns_count(self):
        old_created = (date.today() - timedelta(days=15)).isoformat() + " 00:00:00"
        pipeline = ApplicationPipeline(self.workspace, AppSettings(auto_clear_days=7))
        jobs = [python_job(), welder_job()]
        self.workspace.save_jobs(jobs)
        self._make_application(jobs[0], created_at=old_created)
        self._make_application(jobs[1], created_at=old_created, status="shortlisted")
        self.assertEqual(pipeline.auto_clear_unacted(), 2)

    def test_default_setting_has_clear_days(self):
        self.assertEqual(AppSettings().auto_clear_days, 5)

    def test_default_auto_tracks_qualified_results(self):
        self.assertTrue(AppSettings().auto_track_qualified)
        self.assertFalse(AppSettings.from_dict({"auto_track_qualified": False}).auto_track_qualified)

    def test_pending_auto_clear_previews_without_changing(self):
        old_created = (date.today() - timedelta(days=10)).isoformat() + " 00:00:00"
        pipeline = ApplicationPipeline(self.workspace, AppSettings(auto_clear_days=5))
        job = python_job()
        self.workspace.save_jobs([job])
        app = self._make_application(job, created_at=old_created)
        pending = pipeline.pending_auto_clear()
        self.assertEqual([a.application_id for a in pending], [app.application_id])
        loaded = self.workspace.get_application(app.application_id)
        self.assertEqual(loaded.status, ApplicationStatus.DISCOVERED.value)

    def test_pending_auto_clear_empty_when_off(self):
        old_created = (date.today() - timedelta(days=30)).isoformat() + " 00:00:00"
        pipeline = ApplicationPipeline(self.workspace, AppSettings(auto_clear_days=0))
        job = python_job()
        self.workspace.save_jobs([job])
        self._make_application(job, created_at=old_created)
        self.assertEqual(pipeline.pending_auto_clear(), [])

    def test_settings_default_linkedin_easy_apply_on(self):
        self.assertTrue(AppSettings().linkedin_easy_apply)

    def test_settings_coerce_linkedin_easy_apply_from_dict(self):
        settings = AppSettings.from_dict({"linkedin_easy_apply": False})
        self.assertFalse(settings.linkedin_easy_apply)
