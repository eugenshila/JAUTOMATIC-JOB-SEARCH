"""iCalendar export: RFC 5545 mechanics, event derivation, persistence, migration."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jautomatic.models import (Application, ApplicationStatus, JobPosting, Workspace,
                               parse_date)
from jautomatic.services.application_pipeline import ApplicationPipeline, MatchResult, \
    TrackedApplication
from jautomatic.services.calendar_export import (CalendarEvent, build_calendar, escape_text,
                                                 events_for, fold_line, parse_when, unfold)
from tests.support import WorkspaceTestCase


def python_job(**overrides) -> JobPosting:
    data = {
        "source": "remotive", "title": "Senior Python Engineer", "company": "Northwind Analytics",
        "location": "Berlin, Germany", "remote": True, "salary_min": 90000, "salary_max": 110000,
        "currency": "USD", "url": "https://example.com/jobs/python",
        "description": "FastAPI services, PostgreSQL modelling, Docker, AWS.",
        "tags": ["python", "fastapi"], "posted_at": date.today().isoformat(),
    }
    data.update(overrides)
    return JobPosting(**data)


def row(application: Application, job: JobPosting | None = None) -> TrackedApplication:
    return TrackedApplication(application=application, job=job or python_job(),
                              match=MatchResult())


def physical_lines(document: str) -> list[str]:
    return document.split("\r\n")


class ParseWhenTests(unittest.TestCase):
    def test_date_only(self):
        self.assertEqual(parse_when("2026-09-22"), date(2026, 9, 22))

    def test_datetime_with_space(self):
        self.assertEqual(parse_when("2026-09-22 14:30"), datetime(2026, 9, 22, 14, 30))

    def test_datetime_iso_t(self):
        self.assertEqual(parse_when("2026-09-22T09:05"), datetime(2026, 9, 22, 9, 5))

    def test_whitespace_tolerated(self):
        self.assertEqual(parse_when("  2026-09-22  "), date(2026, 9, 22))

    def test_garbage_returns_none(self):
        for value in ("", None, "next tuesday", "22.09.2026 25:99", "2026-13-45"):
            self.assertIsNone(parse_when(value))


class EscapingAndFoldingTests(unittest.TestCase):
    def test_escape_text(self):
        self.assertEqual(escape_text("a\\b"), "a\\\\b")
        self.assertEqual(escape_text("a;b,c"), "a\\;b\\,c")
        self.assertEqual(escape_text("line1\nline2"), "line1\\nline2")
        self.assertEqual(escape_text("crlf\r\nhere"), "crlf\\nhere")

    def test_short_line_unchanged(self):
        self.assertEqual(fold_line("SUMMARY:short"), "SUMMARY:short")

    def test_long_line_folded_at_75_octets(self):
        line = "DESCRIPTION:" + "x" * 300
        folded = fold_line(line)
        for part in physical_lines(folded):
            self.assertLessEqual(len(part.encode("utf-8")), 75)
        self.assertEqual(unfold(folded + "\r\n").rstrip("\r\n"), line)

    def test_fold_never_splits_multibyte_characters(self):
        line = "DESCRIPTION:" + "äöüß😀🚀" * 20          # 2- and 4-byte sequences
        folded = fold_line(line)
        for part in physical_lines(folded):
            self.assertLessEqual(len(part.encode("utf-8")), 75)
            part.encode("utf-8").decode("utf-8")          # raises if a sequence was split
        self.assertEqual(unfold(folded + "\r\n").rstrip("\r\n"), line)


class BuildCalendarTests(unittest.TestCase):
    stamp = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

    def test_header_and_crlf_endings(self):
        event = CalendarEvent(uid="a@x", summary="One event", start=date(2026, 9, 20))
        document = build_calendar([event], dtstamp=self.stamp)
        self.assertTrue(document.endswith("\r\n"))
        lines = document.split("\r\n")
        self.assertEqual(lines[0], "BEGIN:VCALENDAR")
        self.assertEqual(lines[-2], "END:VCALENDAR")
        self.assertIn("VERSION:2.0", lines)
        self.assertIn("DTSTAMP:20260915T120000Z", document)
        self.assertNotIn("\n ", document.replace("\r\n ", "\x00 "))  # only CRLF folds

    def test_all_day_event_uses_value_date_and_exclusive_end(self):
        event = CalendarEvent(uid="a@x", summary="Follow up", start=date(2026, 9, 20))
        document = build_calendar([event], dtstamp=self.stamp)
        self.assertIn("DTSTART;VALUE=DATE:20260920", document)
        self.assertIn("DTEND;VALUE=DATE:20260921", document)

    def test_timed_event_defaults_to_one_hour(self):
        event = CalendarEvent(uid="a@x", summary="Interview",
                              start=datetime(2026, 9, 20, 14, 30))
        document = build_calendar([event], dtstamp=self.stamp)
        self.assertIn("DTSTART:20260920T143000", document)
        self.assertIn("DTEND:20260920T153000", document)
        self.assertNotIn("VALUE=DATE", document)

    def test_events_sorted_by_start(self):
        late = CalendarEvent(uid="b@x", summary="Later", start=date(2026, 10, 2))
        early = CalendarEvent(uid="a@x", summary="Earlier", start=date(2026, 9, 20))
        document = build_calendar([late, early], dtstamp=self.stamp)
        self.assertLess(document.index("Earlier"), document.index("Later"))

    def test_summary_is_escaped(self):
        event = CalendarEvent(uid="a@x", summary="A, B; C\nD", start=date(2026, 9, 20))
        document = build_calendar([event], dtstamp=self.stamp)
        self.assertIn("SUMMARY:A\\, B\\; C\\nD", document)


class EventDerivationTests(unittest.TestCase):
    def test_follow_up_event_for_active_application(self):
        application = Application(status=ApplicationStatus.SENT.value)
        application.follow_up_at = (date.today() + timedelta(days=2)).isoformat()
        application.sent_at = date.today().isoformat() + " 09:00:00"
        events = events_for([row(application)])
        follow_ups = [e for e in events if "follow-up" in e.uid]
        self.assertEqual(len(follow_ups), 1)
        event = follow_ups[0]
        self.assertEqual(event.uid, f"{application.application_id}-follow-up@jautomatic")
        self.assertEqual(event.start, parse_date(application.follow_up_at))
        self.assertIn("Follow up: Senior Python Engineer @ Northwind Analytics", event.summary)
        self.assertEqual(event.url, "https://example.com/jobs/python")

    def test_no_follow_up_event_for_closed_statuses(self):
        for status in (ApplicationStatus.REJECTED, ApplicationStatus.ARCHIVED):
            application = Application(status=status.value)
            application.follow_up_at = date.today().isoformat()
            self.assertEqual([e for e in events_for([row(application)]) if "follow-up" in e.uid], [])

    def test_timed_interview_event(self):
        application = Application(status=ApplicationStatus.INTERVIEW.value,
                                  interview_at="2026-10-05 15:45")
        events = events_for([row(application)])
        interviews = [e for e in events if "interview" in e.uid]
        self.assertEqual(len(interviews), 1)
        self.assertEqual(interviews[0].start, datetime(2026, 10, 5, 15, 45))
        self.assertFalse(interviews[0].is_all_day)

    def test_all_day_interview_event(self):
        application = Application(status=ApplicationStatus.INTERVIEW.value,
                                  interview_at="2026-10-05")
        events = [e for e in events_for([row(application)]) if "interview" in e.uid]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start, date(2026, 10, 5))
        self.assertTrue(events[0].is_all_day)

    def test_interview_status_without_date_falls_back_to_history(self):
        application = Application(status=ApplicationStatus.INTERVIEW.value,
                                  updated_at="2026-09-12 10:00:00")
        application.history.append({"at": "2026-09-12 10:00:00", "event": "status",
                                    "from": "sent", "to": "interview", "note": ""})
        events = [e for e in events_for([row(application)]) if "interview" in e.uid]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start, date(2026, 9, 12))

    def test_interview_date_without_interview_status_still_exports(self):
        application = Application(status=ApplicationStatus.SENT.value,
                                  interview_at="2026-10-05 09:00")
        events = [e for e in events_for([row(application)]) if "interview" in e.uid]
        self.assertEqual(len(events), 1)

    def test_no_events_for_bare_application(self):
        self.assertEqual(events_for([row(Application())]), [])

    def test_include_flags(self):
        application = Application(status=ApplicationStatus.INTERVIEW.value,
                                  interview_at="2026-10-05")
        application.follow_up_at = date.today().isoformat()
        self.assertEqual(len(events_for([row(application)])), 2)
        self.assertEqual(len(events_for([row(application)], include_follow_ups=False)), 1)
        self.assertEqual(len(events_for([row(application)], include_interviews=False)), 1)
        self.assertEqual(events_for([row(application)], include_follow_ups=False,
                                    include_interviews=False), [])

    def test_uids_are_stable_across_exports(self):
        application = Application(status=ApplicationStatus.INTERVIEW.value,
                                  interview_at="2026-10-05")
        first = [e.uid for e in events_for([row(application)])]
        second = [e.uid for e in events_for([row(application)])]
        self.assertEqual(first, second)


class PipelineCalendarTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.pipeline = ApplicationPipeline(self.workspace, self.workspace.load_settings())

    def _tracked_sent_application(self) -> Application:
        job = python_job()
        self.workspace.save_jobs([job])
        application = self.workspace.save_application(Application(job_id=job.job_id))
        return self.pipeline.set_status(application, ApplicationStatus.SENT, "test")

    def test_export_writes_follow_up_event(self):
        application = self._tracked_sent_application()
        path = self.pipeline.export_calendar_ics()
        self.assertTrue(path.exists())
        self.assertEqual(path.parent, self.workspace.exports_dir)
        document = path.read_text(encoding="utf-8")
        self.assertTrue(document.startswith("BEGIN:VCALENDAR"))
        self.assertIn(f"UID:{application.application_id}-follow-up@jautomatic", document)
        self.assertIn("END:VCALENDAR", document)

    def test_export_empty_tracker_still_valid(self):
        document = self.pipeline.export_calendar_ics().read_text(encoding="utf-8")
        self.assertIn("BEGIN:VCALENDAR", document)
        self.assertNotIn("BEGIN:VEVENT", document)

    def test_set_interview_stores_timed_value(self):
        application = self._tracked_sent_application()
        saved = self.pipeline.set_interview(application, "2026-10-01 09:30")
        self.assertEqual(saved.interview_at, "2026-10-01 09:30")
        reloaded = self.workspace.get_application(application.application_id)
        self.assertEqual(reloaded.interview_at, "2026-10-01 09:30")
        self.assertTrue(any(e.get("event") == "interview scheduled" for e in reloaded.history))

    def test_set_interview_date_only(self):
        application = self._tracked_sent_application()
        saved = self.pipeline.set_interview(application, "2026-10-01")
        self.assertEqual(saved.interview_at, "2026-10-01")

    def test_set_interview_rejects_garbage(self):
        application = self._tracked_sent_application()
        with self.assertRaises(ValueError):
            self.pipeline.set_interview(application, "next tuesday")
        self.assertEqual(self.workspace.get_application(
            application.application_id).interview_at, "")

    def test_set_interview_clears_value(self):
        application = self._tracked_sent_application()
        self.pipeline.set_interview(application, "2026-10-01 09:30")
        cleared = self.pipeline.set_interview(application, "  ")
        self.assertEqual(cleared.interview_at, "")
        self.assertTrue(any(e.get("event") == "interview date cleared" for e in cleared.history))

    def test_interview_appears_in_export_after_set(self):
        application = self._tracked_sent_application()
        self.pipeline.set_interview(application, "2026-10-01 09:30")
        document = self.pipeline.export_calendar_ics().read_text(encoding="utf-8")
        self.assertIn(f"UID:{application.application_id}-interview@jautomatic", document)
        self.assertIn("DTSTART:20261001T093000", document)


class SchemaMigrationTests(unittest.TestCase):
    """A v1 database (no interview_at column) must upgrade in place."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "jautomatic.sqlite3"
        self._make_v1_database()

    def _make_v1_database(self) -> None:
        connection = sqlite3.connect(self.db_path)
        connection.executescript(
            """
            CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, source TEXT, title TEXT,
                company TEXT, location TEXT, remote INTEGER DEFAULT 0,
                salary_min INTEGER DEFAULT 0, salary_max INTEGER DEFAULT 0,
                currency TEXT DEFAULT '', url TEXT DEFAULT '', description TEXT DEFAULT '',
                tags TEXT DEFAULT '[]', posted_at TEXT DEFAULT '', fetched_at TEXT DEFAULT ''
            );
            CREATE TABLE applications (
                application_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                status TEXT DEFAULT 'discovered', match_score INTEGER DEFAULT 0,
                created_at TEXT, updated_at TEXT, sent_at TEXT DEFAULT '',
                follow_up_at TEXT DEFAULT '', notes TEXT DEFAULT '', cv_path TEXT DEFAULT '',
                cover_letter_path TEXT DEFAULT '', email_path TEXT DEFAULT '',
                history TEXT DEFAULT '[]'
            );
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta(key, value) VALUES('schema_version', '1');
            INSERT INTO jobs (job_id, fingerprint, title, company)
                VALUES ('job-1', 'fp-1', 'Python Engineer', 'Northwind');
            INSERT INTO applications (application_id, job_id, status, created_at, updated_at)
                VALUES ('app-1', 'job-1', 'sent', '2026-09-01 10:00:00', '2026-09-01 10:00:00');
            """
        )
        connection.commit()
        connection.close()

    def test_workspace_adds_interview_column_and_bumps_version(self):
        workspace = Workspace(self.root)
        try:
            application = workspace.get_application("app-1")
            self.assertIsNotNone(application)
            self.assertEqual(application.interview_at, "")

            application.interview_at = "2026-10-02 11:15"
            workspace.save_application(application)
            reloaded = workspace.get_application("app-1")
            self.assertEqual(reloaded.interview_at, "2026-10-02 11:15")

            connection = sqlite3.connect(self.db_path)
            version = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            connection.close()
            self.assertEqual(version, "2")
        finally:
            workspace.close()

    def test_migration_is_idempotent(self):
        first = Workspace(self.root)
        first.close()
        second = Workspace(self.root)
        application = second.get_application("app-1")
        self.assertEqual(application.interview_at, "")
        second.close()


if __name__ == "__main__":
    unittest.main()
