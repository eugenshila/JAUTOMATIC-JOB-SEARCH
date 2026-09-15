"""Application pipeline: match -> rank -> prepare materials -> track.

This is the brain of the app.  It is GUI-free so it can be exercised from a
script or a test:

    from jautomatic.models import Workspace, Profile
    from jautomatic.services.application_pipeline import ApplicationPipeline

    ws = Workspace()
    pipeline = ApplicationPipeline(ws)
    outcome = pipeline.search("python engineer", sources=["sample"])
    pipeline.import_jobs(outcome.jobs)
    seen = pipeline.tracker()          # ranked, with scores
    materials = pipeline.prepare(seen[0].application, ws.load_profile())
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..models import (DEFAULT_FOLLOW_UP_DAYS, Application, ApplicationStatus, JobPosting,
                      Profile, Workspace, keywords, now_iso, parse_date, today_iso)
from .calendar_export import build_calendar, events_for, parse_when
from .cover_letter import CoverLetterService, MatchContext
from .cv_generator import CVGenerator, GeneratedDocument
from .email_drafter import EmailDrafter, render_follow_up
from .job_scraper import JobScraper, SearchOutcome, SearchQuery

# scoring weights (sum = 100)
W_KEYWORDS, W_TITLE, W_LOCATION, W_SALARY, W_FRESHNESS = 55, 20, 10, 10, 5


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
@dataclass
class MatchResult:
    score: int = 0
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    salary_fit: bool = True
    location_fit: bool = True

    @property
    def grade(self) -> str:
        if self.score >= 85:
            return "excellent"
        if self.score >= 70:
            return "strong"
        if self.score >= 50:
            return "possible"
        return "weak"

    def as_context(self) -> MatchContext:
        return MatchContext(score=self.score, matched_keywords=list(self.matched_keywords),
                            missing_keywords=list(self.missing_keywords),
                            reasons=list(self.reasons))


def _profile_text(profile: Profile) -> str:
    chunks = [profile.headline, profile.summary, profile.seniority, " ".join(profile.skills)]
    for entry in profile.experience:
        chunks += [entry.title, entry.company, entry.summary, " ".join(entry.highlights)]
    for entry in profile.education:
        chunks += [entry.degree, entry.school, entry.details]
    chunks.append(profile.languages)
    return " ".join(c for c in chunks if c)


def match_job(profile: Profile, job: JobPosting, settings=None) -> MatchResult:  # noqa: ANN001
    """Score how well ``job`` fits ``profile`` (0-100) and explain why."""
    result = MatchResult()
    profile_text = _profile_text(profile)
    profile_tokens = set(keywords(profile_text, limit=400))
    job_terms = [t.lower() for t in job.tags if t]
    job_terms += [t for t in keywords(f"{job.title} {job.description}", limit=45)
                  if t not in job_terms]
    job_terms = job_terms[:40]

    if job_terms:
        matched = [t for t in job_terms if t in profile_tokens]
        missing = [t for t in job_terms if t not in profile_tokens]
        # tag hits count double: they are the employer's own headline requirements
        weight = sum(2 if t in [x.lower() for x in job.tags] else 1 for t in matched)
        total = sum(2 if t in [x.lower() for x in job.tags] else 1 for t in job_terms)
        coverage = weight / total if total else 0.0
        result.score += round(W_KEYWORDS * min(1.0, coverage * 1.35))
        result.matched_keywords = matched[:12]
        result.missing_keywords = missing[:12]
        result.reasons.append(f"{len(matched)}/{len(job_terms)} posting keywords present in your profile")
    else:
        result.score += round(W_KEYWORDS * 0.4)
        result.reasons.append("posting has little text to match against")

    # title alignment
    wanted = [t.lower() for t in profile.desired_titles if t.strip()]
    title = job.title.lower()
    title_terms = set(re.findall(r"[a-z]+", title))
    if wanted:
        best = max((len(set(re.findall(r"[a-z]+", w)) & title_terms) /
                    max(1, len(set(re.findall(r"[a-z]+", w)))) for w in wanted), default=0.0)
        result.score += round(W_TITLE * best)
        if best >= 0.6:
            result.reasons.append(f"title matches your target role ({job.title})")
        elif best == 0:
            result.reasons.append("title is outside your stated target roles")
    else:
        headline_terms = set(re.findall(r"[a-z]+", (profile.headline or "").lower()))
        overlap = len(headline_terms & title_terms) / max(1, len(title_terms))
        result.score += round(W_TITLE * min(1.0, overlap * 1.5))

    # location / remote
    locations = [loc.lower() for loc in profile.desired_locations if loc.strip()]
    if job.remote and (profile.remote_only or not locations):
        result.score += W_LOCATION
        result.reasons.append("remote-friendly and you are open to remote")
    elif locations:
        hay = f"{job.location} {job.company}".lower()
        if any(loc in hay for loc in locations) or job.remote:
            result.score += W_LOCATION
            result.reasons.append(f"location fits ({job.display_location})")
        else:
            result.location_fit = False
            result.reasons.append(f"location mismatch (posting: {job.display_location or 'n/a'})")
    else:
        result.score += round(W_LOCATION * 0.6)

    # salary
    ceiling = job.salary_max or job.salary_min
    floor = profile.salary_floor or (getattr(settings, "min_salary", 0) or 0)
    if not floor or not ceiling:
        result.score += round(W_SALARY * 0.5)
        if floor and not ceiling:
            result.reasons.append("salary not disclosed - check the range early")
    elif ceiling >= floor:
        result.score += W_SALARY
        if job.salary_min and job.salary_min >= floor:
            result.reasons.append(f"pay band clears your floor ({job.salary_text})")
        else:
            result.reasons.append(f"upper band reaches your floor ({job.salary_text})")
    else:
        result.salary_fit = False
        result.reasons.append(f"pay band ({job.salary_text}) is below your floor")

    # freshness
    age = job.age_days
    if age is None:
        result.score += round(W_FRESHNESS * 0.5)
    elif age <= 3:
        result.score += W_FRESHNESS
        result.reasons.append("posted in the last few days")
    elif age <= 14:
        result.score += round(W_FRESHNESS * 0.7)
    elif age <= 30:
        result.score += round(W_FRESHNESS * 0.4)
    else:
        result.reasons.append(f"posting is {age} days old")

    result.score = max(0, min(100, result.score))
    return result


def rank_jobs(profile: Profile, jobs: list[JobPosting], settings=None) -> list[tuple[JobPosting, MatchResult]]:  # noqa: ANN001
    scored = [(job, match_job(profile, job, settings)) for job in jobs]
    scored.sort(key=lambda pair: (-pair[1].score, pair[0].age_days or 999))
    return scored


# --------------------------------------------------------------------------- #
# tracker rows + pipeline
# --------------------------------------------------------------------------- #
@dataclass
class TrackedApplication:
    """A row of the Applications tab: application + its job + its match."""
    application: Application
    job: JobPosting
    match: MatchResult

    @property
    def status(self) -> ApplicationStatus:
        return self.application.status_enum

    @property
    def score(self) -> int:
        return self.application.match_score or self.match.score

    @property
    def title(self) -> str:
        return self.job.title or "(untitled role)"

    @property
    def company(self) -> str:
        return self.job.company or "(unknown company)"


@dataclass
class PreparedMaterials:
    application: Application
    job: JobPosting
    cv: GeneratedDocument | None = None
    cover_letter: GeneratedDocument | None = None
    email: GeneratedDocument | None = None

    @property
    def paths(self) -> list[Path]:
        return [doc.path for doc in (self.cv, self.cover_letter, self.email)
                if doc is not None and doc.path]

    def summary(self) -> str:
        made = [doc.kind.replace("_", " ") for doc in (self.cv, self.cover_letter, self.email)
                if doc is not None]
        return "Generated: " + ", ".join(made) if made else "Nothing generated"


class ApplicationPipeline:
    """Coordinates scraper, matcher, generators and the SQLite workspace."""

    def __init__(self, workspace: Workspace, settings=None) -> None:  # noqa: ANN001
        self.workspace = workspace
        self.settings = settings or workspace.load_settings()
        self.scraper = JobScraper(self.settings)
        self.cv_generator = CVGenerator()
        self.cover_letters = CoverLetterService()
        self.emails = EmailDrafter()

    # -- search ------------------------------------------------------------ #
    def build_query(self, text: str, location: str = "", **overrides) -> SearchQuery:  # noqa: ANN003
        settings = self.settings
        query = SearchQuery(
            text=text, location=location,
            remote_only=overrides.get("remote_only", settings.remote_only),
            min_salary=overrides.get("min_salary", settings.min_salary),
            limit_per_source=overrides.get("limit_per_source", settings.results_per_source),
            sources=overrides.get("sources", settings.enabled_sources),
            exclude_keywords=settings.excluded_keyword_list,
            include_sample=overrides.get("include_sample", False))
        return query

    def search(self, text: str, location: str = "", **overrides) -> SearchOutcome:  # noqa: ANN003
        return self.scraper.search(self.build_query(text, location, **overrides))

    def search_and_import(self, text: str, location: str = "", **overrides):  # noqa: ANN003, ANN201
        outcome = self.search(text, location, **overrides)
        created = self.import_jobs(outcome.jobs)
        return outcome, created

    # -- importing --------------------------------------------------------- #
    def import_jobs(self, jobs: list[JobPosting]) -> list[Application]:
        """Store postings and create tracker entries for the new ones."""
        self.workspace.save_jobs(jobs)
        created: list[Application] = []
        for job in jobs:
            if self.workspace.application_for_job(job.job_id) is None:
                application = Application(job_id=job.job_id)
                self.workspace.save_application(application)
                created.append(application)
        return created

    def ensure_application(self, job: JobPosting) -> Application:
        self.workspace.save_jobs([job])
        existing = self.workspace.application_for_job(job.job_id)
        if existing:
            return existing
        application = Application(job_id=job.job_id)
        return self.workspace.save_application(application)

    # -- tracking ---------------------------------------------------------- #
    def tracker(self, profile: Profile | None = None,
                statuses: list[ApplicationStatus] | None = None) -> list[TrackedApplication]:
        profile = profile or self.workspace.load_profile()
        rows: list[TrackedApplication] = []
        for application in self.workspace.applications():
            job = self.workspace.get_job(application.job_id)
            if job is None:
                continue
            if statuses and application.status_enum not in statuses:
                continue
            match = match_job(profile, job, self.settings)
            rows.append(TrackedApplication(application, job, match))
        rows.sort(key=lambda r: (-r.score, r.job.age_days if r.job.age_days is not None else 999))
        return rows

    def refresh_scores(self, profile: Profile | None = None) -> int:
        """Recompute match scores for every tracked application (after profile edits)."""
        updated = 0
        for row in self.tracker(profile):
            if row.application.match_score != row.match.score:
                row.application.match_score = row.match.score
                self.workspace.save_application(row.application)
                updated += 1
        return updated

    def set_status(self, application: Application | str, status: ApplicationStatus | str,
                   note: str = "") -> Application:
        record = (self.workspace.get_application(application)
                  if isinstance(application, str) else application)
        if record is None:
            raise KeyError(f"unknown application: {application}")
        new_status = ApplicationStatus(status) if not isinstance(status, ApplicationStatus) \
            else status
        record.set_status(new_status, note)
        if new_status is ApplicationStatus.SENT and not record.follow_up_at:
            record.schedule_follow_up(self.settings.follow_up_days or DEFAULT_FOLLOW_UP_DAYS)
        return self.workspace.save_application(record)

    def update_notes(self, application: Application, notes: str) -> Application:
        application.notes = notes
        application.log("note edited")
        return self.workspace.save_application(application)

    # -- materials --------------------------------------------------------- #
    def prepare(self, application: Application | str, profile: Profile | None = None,
                template: str | None = None, tone: str | None = None,
                fmt: str | None = None, with_cover_letter: bool | None = None,
                with_email: bool | None = None) -> PreparedMaterials:
        """Generate CV (+ cover letter, + e-mail draft) for one application."""
        record = (self.workspace.get_application(application)
                  if isinstance(application, str) else application)
        if record is None:
            raise KeyError(f"unknown application: {application}")
        job = self.workspace.get_job(record.job_id)
        if job is None:
            raise KeyError(f"job {record.job_id} is not in the workspace")
        profile = profile or self.workspace.load_profile()
        settings = self.settings
        template = template or settings.cv_template
        tone = tone or profile.tone
        fmt = fmt or settings.export_format
        with_cover_letter = (settings.include_cover_letter if with_cover_letter is None
                             else with_cover_letter)
        with_email = settings.include_email_draft if with_email is None else with_email

        match = match_job(profile, job, settings)
        out_dir = self.workspace.documents_dir
        materials = PreparedMaterials(application=record, job=job)

        materials.cv = self.cv_generator.generate(profile, job, template, out_dir, fmt, match)
        record.cv_path = str(materials.cv.path) if materials.cv.path else ""

        attachment_names = [materials.cv.filename] if materials.cv.path else []
        if with_cover_letter:
            materials.cover_letter = self.cover_letters.generate(
                profile, job, match.as_context(), tone, out_dir, fmt)
            record.cover_letter_path = (str(materials.cover_letter.path)
                                        if materials.cover_letter.path else "")
            if materials.cover_letter.path:
                attachment_names.append(materials.cover_letter.filename)

        if with_email:
            materials.email = self.emails.generate(
                profile, job, match.as_context(), tone, attachment_names, out_dir, fmt)
            record.email_path = str(materials.email.path) if materials.email.path else ""

        record.match_score = match.score
        record.log("materials generated",
                   f"score {match.score}, {materials.summary()}")
        if record.status_enum in (ApplicationStatus.DISCOVERED,):
            record.set_status(ApplicationStatus.SHORTLISTED, "auto-shortlisted when preparing")
        if record.status_enum in (ApplicationStatus.SHORTLISTED,):
            record.set_status(ApplicationStatus.MATERIALS_READY,
                              f"CV + documents ready (template: {template})")
        else:
            self.workspace.save_application(record)
        materials.application = self.workspace.save_application(record)
        return materials

    def prepare_batch(self, rows: list[TrackedApplication], profile: Profile | None = None,
                      **kwargs) -> list[PreparedMaterials]:  # noqa: ANN003
        out: list[PreparedMaterials] = []
        for row in rows:
            try:
                out.append(self.prepare(row.application, profile, **kwargs))
            except KeyError:
                continue
        return out

    def autopilot(self, profile: Profile | None = None, limit: int | None = None) -> list[PreparedMaterials]:
        """Prepare materials for the best untouched matches (opt-in in Settings)."""
        profile = profile or self.workspace.load_profile()
        threshold = self.settings.autopilot_min_score
        limit = limit or self.settings.autopilot_max_per_run
        candidates = [row for row in self.tracker(profile)
                      if row.status in (ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED)
                      and row.score >= threshold]
        chosen = candidates[:max(0, limit)]
        prepared = self.prepare_batch(chosen, profile)
        for materials in prepared:
            materials.application.log("autopilot",
                                      f"prepared automatically (score {materials.application.match_score})")
            self.workspace.save_application(materials.application)
        return prepared

    # -- follow-ups -------------------------------------------------------- #
    def follow_ups_due(self, profile: Profile | None = None) -> list[TrackedApplication]:
        return [row for row in self.tracker(profile) if row.application.follow_up_due]

    def draft_follow_up(self, application: Application | str,
                        fmt: str | None = None) -> tuple[Path, str]:
        record = (self.workspace.get_application(application)
                  if isinstance(application, str) else application)
        if record is None:
            raise KeyError(f"unknown application: {application}")
        job = self.workspace.get_job(record.job_id)
        if job is None:
            raise KeyError(f"job {record.job_id} is not in the workspace")
        profile = self.workspace.load_profile()
        days = record.days_since_sent or self.settings.follow_up_days or DEFAULT_FOLLOW_UP_DAYS
        stage = "interview" if record.status_enum is ApplicationStatus.INTERVIEW else "sent"
        draft = render_follow_up(profile, job, days, stage)
        document = self.emails.follow_up(profile, job, days, stage,
                                         self.workspace.documents_dir, fmt or self.settings.export_format)
        record.log("follow-up drafted", draft.subject)
        self.workspace.save_application(record)
        return document.path, draft.text

    def postpone_follow_up(self, application: Application, days: int = 5) -> Application:
        application.schedule_follow_up(days)
        return self.workspace.save_application(application)

    def set_interview(self, application: Application | str, when: str,
                      note: str = "") -> Application:
        """Store (or clear, with an empty string) the interview date/time.

        Accepts "YYYY-MM-DD" for all-day and "YYYY-MM-DD HH:MM" for timed
        interviews - the calendar export honours both.
        """
        record = (self.workspace.get_application(application)
                  if isinstance(application, str) else application)
        if record is None:
            raise KeyError(f"unknown application: {application}")
        text = (when or "").strip()
        parsed = parse_when(text)
        if text and parsed is None:
            raise ValueError(f"Unrecognised date/time “{text}” — use e.g. 2026-09-22 14:30.")
        if parsed is None:
            had_value = bool(record.interview_at)
            record.interview_at = ""
            if had_value:
                record.log("interview date cleared")
        else:
            record.interview_at = (parsed.strftime("%Y-%m-%d %H:%M")
                                   if isinstance(parsed, datetime) else parsed.isoformat())
            record.log("interview scheduled",
                       f"{record.interview_at}{f' — {note}' if note else ''}")
        return self.workspace.save_application(record)

    # -- reporting --------------------------------------------------------- #
    def export_tracker_csv(self, profile: Profile | None = None,
                           path: Path | None = None) -> Path:
        rows = self.tracker(profile)
        target = Path(path) if path else self.workspace.exports_dir / f"applications_{today_iso()}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Title", "Company", "Location", "Remote", "Source", "Score", "Status",
                             "Created", "Sent", "Follow-up", "Interview", "Salary", "URL", "CV",
                             "Cover letter", "Email", "Notes"])
            for row in rows:
                app = row.application
                writer.writerow([
                    row.job.title, row.job.company, row.job.location, "yes" if row.job.remote else "no",
                    row.job.source, row.score, app.status_enum.label, app.created_at,
                    app.sent_at, app.follow_up_at, app.interview_at, row.job.salary_text, row.job.url,
                    Path(app.cv_path).name if app.cv_path else "",
                    Path(app.cover_letter_path).name if app.cover_letter_path else "",
                    Path(app.email_path).name if app.email_path else "",
                    re.sub(r"\s+", " ", app.notes).strip()])
        return target

    def export_calendar_ics(self, profile: Profile | None = None, path: Path | None = None,
                            include_follow_ups: bool = True,
                            include_interviews: bool = True) -> Path:
        """Write interviews + follow-ups as an RFC 5545 ``.ics`` calendar file."""
        rows = self.tracker(profile)
        events = events_for(rows, include_follow_ups=include_follow_ups,
                            include_interviews=include_interviews)
        target = Path(path) if path else self.workspace.exports_dir / f"calendar_{today_iso()}.ics"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_calendar(events), encoding="utf-8")
        return target

    def dashboard_stats(self, profile: Profile | None = None) -> dict:
        profile = profile or self.workspace.load_profile()
        stats = self.workspace.stats()
        stats["profile_completeness"] = profile.completeness()
        rows = self.tracker(profile)
        stats["top_matches"] = [row for row in rows if row.score >= 70][:5]
        stats["last_updated"] = now_iso()
        upcoming = [row for row in rows
                    if row.application.follow_up_at and parse_date(row.application.follow_up_at)]
        upcoming.sort(key=lambda r: r.application.follow_up_at)
        stats["next_follow_up"] = upcoming[0] if upcoming else None
        return stats


__all__ = ["ApplicationPipeline", "MatchResult", "PreparedMaterials", "TrackedApplication",
           "match_job", "rank_jobs"]
