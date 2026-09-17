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
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from ..models import (
    DEFAULT_FOLLOW_UP_DAYS,
    GENERIC_TERMS,
    Application,
    ApplicationStatus,
    JobPosting,
    Profile,
    Workspace,
    keywords,
    now_iso,
    parse_date,
    source_label,
    today_iso,
)
from .calendar_export import build_calendar, events_for, parse_when
from .cover_letter import CoverLetterService, MatchContext
from .cv_generator import CVGenerator, GeneratedDocument
from .email_drafter import EmailDrafter, render_follow_up
from .interview_prep import InterviewPrep, export_prep, generate_questions
from .job_scraper import JobScraper, SearchOutcome, SearchQuery

# scoring weights (sum = 100)
W_KEYWORDS, W_TITLE, W_LOCATION, W_SALARY, W_FRESHNESS = 55, 20, 10, 10, 5
# description keywords fill up fast with nice-to-haves; covering 75% of a
# posting's stated terms already shows qualification, so that is full keyword credit
FULL_CREDIT_COVERAGE = 0.75


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


def match_job(profile: Profile, job: JobPosting, settings=None) -> MatchResult:
    """Score how well ``job`` fits ``profile`` (0-100) and explain why.

    A score of 70+ is deliberately a *qualification* bar, not a popularity
    score: it requires your profile to cover the posting's own headline
    requirements (tags), your pay floor and location to fit, and your target
    title to align.  Postings that fail a hard requirement are capped below 70.
    """
    result = MatchResult()
    profile_text = _profile_text(profile)
    profile_tokens = set(keywords(profile_text, limit=400))
    tag_terms = [t.lower() for t in job.tags if t]
    job_terms = list(tag_terms)
    job_terms += [t for t in keywords(f"{job.title} {job.description}", limit=45)
                  if t not in job_terms]
    job_terms = job_terms[:40]

    if job_terms:
        matched = [t for t in job_terms if t in profile_tokens]
        missing = [t for t in job_terms if t not in profile_tokens]
        # tag hits count double: they are the employer's own headline requirements
        tag_set = set(tag_terms)
        weight = sum(2 if t in tag_set else 1 for t in matched)
        total = sum(2 if t in tag_set else 1 for t in job_terms)
        coverage = weight / total if total else 0.0
        result.score += round(W_KEYWORDS * min(1.0, coverage / FULL_CREDIT_COVERAGE))
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
    locations = [l.lower() for l in profile.desired_locations if l.strip()]
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

    cap = 100
    if tag_terms and not any(t in profile_tokens for t in tag_terms):
        cap = 49
        result.reasons.append("none of the posting's headline requirements appear in your profile")
    if not result.location_fit or not result.salary_fit:
        cap = min(cap, 59)
    result.score = max(0, min(cap, result.score))
    return result


def rank_jobs(profile: Profile, jobs: list[JobPosting], settings=None) -> list[tuple[JobPosting, MatchResult]]:
    scored = [(job, match_job(profile, job, settings)) for job in jobs]
    scored.sort(key=lambda pair: (-pair[1].score, pair[0].age_days or 999))
    return scored


def filter_min_score(ranked: list[tuple[JobPosting, MatchResult]],
                     floor: int = 0) -> list[tuple[JobPosting, MatchResult]]:
    """Keep only results at or above ``floor`` (0 or negative = keep everything)."""
    if not ranked or floor <= 0:
        return list(ranked)
    return [(job, match) for job, match in ranked if match.score >= floor]


def min_pay_ok(job: JobPosting, floor: int = 0) -> bool:
    """True when the posting advertises a per-task rate of at least ``floor`` USD.

    Used by the Tasks search: microtask gigs quote per-task rates, so a posting
    that is not explicitly priced in USD fails the ``$X+`` check rather than
    silently passing.  A quoted range ("$8-$45") is judged by its lower bound,
    so ``$10+`` really means the task pays $10 or more.
    """
    if not job or floor <= 0:
        return True
    if (job.currency or "").upper() != "USD":
        return False
    rate = job.salary_min or job.salary_max
    return bool(rate) and rate >= floor


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

    def __init__(self, workspace: Workspace, settings=None) -> None:
        self.workspace = workspace
        self.settings = settings or workspace.load_settings()
        self.scraper = JobScraper(self.settings)
        self.cv_generator = CVGenerator(workspace.templates_dir)
        self.cover_letters = CoverLetterService()
        self.emails = EmailDrafter()

    # -- search ------------------------------------------------------------ #
    def build_query(self, text: str, location: str = "", **overrides) -> SearchQuery:
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

    def search(self, text: str, location: str = "", should_cancel=None,
               **overrides) -> SearchOutcome:
        return self.scraper.search(self.build_query(text, location, **overrides),
                                   should_cancel=should_cancel)

    def search_and_import(self, text: str, location: str = "", should_cancel=None,
                          **overrides):
        outcome = self.search(text, location, should_cancel=should_cancel, **overrides)
        if should_cancel is not None and should_cancel():
            # Shutdown began mid-search: importing into a workspace that is about
            # to close would race ``Workspace.close()`` — drop the partial result.
            return outcome, []
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

    def import_qualified(self, jobs: list[JobPosting], profile: Profile | None = None,
                         threshold: int = 0, track: bool = True
                         ) -> tuple[list[tuple[JobPosting, MatchResult]], list[Application]]:
        """Score a batch, transfer the qualified ones to the queue, keep all for display.

        Returns ``(rows, created)`` where ``rows`` is the full scored list (what the
        search table shows) and ``created`` is the tracker entries added.  Only jobs
        scoring at or above ``threshold`` are queued (``threshold <= 0`` keeps
        everything, ``track=False`` waits instead of importing).  Postings tracked
        earlier as *proposed* (below the bar) that now meet it are promoted to the
        queue in place.
        """
        profile = profile or self.workspace.load_profile()
        rows = [(job, match_job(profile, job, self.settings)) for job in jobs]
        selected = [job for job, match in rows if threshold <= 0 or match.score >= threshold]
        created = self.import_jobs(selected) if track else []
        if track and threshold > 0:
            lifted = self._promote_past_reviews([job for job, match in rows
                                                 if match.score >= threshold])
            created = lifted + [entry for entry in created if entry not in lifted]
        return rows, created

    def import_review(self, jobs: list[JobPosting]) -> list[Application]:
        """Track below-the-bar postings as ``Proposed`` so they show on the
        Applications page for a human review (autopilot, auto-clear and the
        follow-up ladder ignore them until the status is changed).
        """
        created = self.import_jobs(jobs)
        for application in created:
            application.set_status(ApplicationStatus.PROPOSED,
                                   "below the qualification bar — added for review")
            self.workspace.save_application(application)
        return created

    def _promote_past_reviews(self, jobs: list[JobPosting]) -> list[Application]:
        lifted: list[Application] = []
        for job in jobs:
            application = self.workspace.application_for_job(job.job_id)
            if application and application.status_enum is ApplicationStatus.PROPOSED:
                application.set_status(ApplicationStatus.DISCOVERED,
                                       "now meets the qualification bar")
                self.workspace.save_application(application)
                lifted.append(application)
        return lifted

    def ensure_application(self, job: JobPosting) -> Application:
        self.workspace.save_jobs([job])
        existing = self.workspace.application_for_job(job.job_id)
        if existing:
            return existing
        application = Application(job_id=job.job_id)
        return self.workspace.save_application(application)

    def import_from_url(self, url: str, timeout: int | None = None) -> tuple[Application, bool]:
        """Track a posting at an arbitrary URL (paste-any-URL importer).

        Returns ``(application, created)``; when the URL was already tracked
        ``created`` is False and just the posting row is refreshed.
        """
        from .job_scraper import (
            posting_from_url,  # local import: keeps scraper optional
        )

        timeout = timeout or int(getattr(self.settings, "request_timeout", 15) or 15)
        job = posting_from_url(url, timeout=timeout)
        fingerprint = job.fingerprint
        already = any(stored.fingerprint == fingerprint for stored in self.workspace.jobs())
        application = self.ensure_application(job)
        return application, not already

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
        elif new_status.is_closed or new_status in (ApplicationStatus.INTERVIEW,
                                                    ApplicationStatus.OFFER):
            # The ladder is over the moment the story moves forward (or ends):
            # no more nudges for a role that reached interview, offer or the bin.
            if record.follow_up_at:
                record.follow_up_at = ""
                record.follow_up_count = 0
                record.log("follow-up cancelled", f"reached {new_status.label.lower()}")
        return self.workspace.save_application(record)

    def update_notes(self, application: Application, notes: str) -> Application:
        application.notes = notes
        application.log("note edited")
        return self.workspace.save_application(application)

    def clear_application(self, application: Application | str,
                          note: str = "cleared — cannot apply") -> Application:
        """Archive a job you can't apply for, keeping it in the database/history."""
        return self.set_status(application, ApplicationStatus.ARCHIVED, note)

    def auto_clear_unacted(self, profile: Profile | None = None,
                           days: int | None = None) -> int:
        """Archive untouched applications whose tracking date is older than ``days``.

        ``days`` comes from ``settings.auto_clear_days`` unless overridden; ``0``
        (or a false value stored in old settings) disables the sweep entirely.
        Returns the number of applications archived.
        """
        resolved, pending = self._auto_clear_plan(days)
        for app in pending:
            self.set_status(app, ApplicationStatus.ARCHIVED,
                            f"auto-cleared after {resolved} day(s) without action")
        return len(pending)

    def pending_auto_clear(self, profile: Profile | None = None,
                           days: int | None = None) -> list[Application]:
        """Dry run: which untouched applications the next sweep would archive.

        Pure read — nothing is changed, so the UI can preview exactly what
        ``auto_clear_unacted`` would do.
        """
        _resolved, pending = self._auto_clear_plan(days)
        return pending

    def _auto_clear_plan(self, days: int | None) -> tuple[int, list[Application]]:
        days = int(days if days is not None else self.settings.auto_clear_days or 0)
        if days <= 0:
            return days, []
        cutoff = date.today() - timedelta(days=days)
        pending: list[Application] = []
        for app in self.workspace.applications():
            if not app.is_unacted:
                continue
            created = parse_date(app.created_at)
            if created is None or created > cutoff:
                continue
            pending.append(app)
        return days, pending

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

        materials.cv = self.cv_generator.generate(profile, job, template, out_dir, fmt, match,
                                                  reuse=record.cv_path or None)
        record.cv_path = str(materials.cv.path) if materials.cv.path else ""
        if materials.cv.warning:
            record.log("template fallback", materials.cv.warning)
        template = materials.cv.template   # what was actually used (after any fallback)

        attachment_names = [materials.cv.filename] if materials.cv.path else []
        if with_cover_letter:
            llm = None
            if settings.llm_provider == "ollama":
                llm = {"base_url": settings.llm_base_url or "http://localhost:11434",
                       "model": settings.llm_model or "llama3.2",
                       "timeout": settings.llm_timeout}
            materials.cover_letter = self.cover_letters.generate(
                profile, job, match.as_context(), tone, out_dir, fmt,
                reuse=record.cover_letter_path or None, llm=llm)
            if materials.cover_letter.warning:
                record.log("cover letter fallback", materials.cover_letter.warning)
            record.cover_letter_path = (str(materials.cover_letter.path)
                                        if materials.cover_letter.path else "")
            if materials.cover_letter.path:
                attachment_names.append(materials.cover_letter.filename)

        if with_email:
            materials.email = self.emails.generate(
                profile, job, match.as_context(), tone, attachment_names, out_dir, fmt,
                reuse=record.email_path or None)
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
                      should_cancel=None, **kwargs) -> list[PreparedMaterials]:
        out: list[PreparedMaterials] = []
        for row in rows:
            if should_cancel is not None and should_cancel():
                break  # closing: finish the batch with whatever is done so far
            try:
                out.append(self.prepare(row.application, profile, **kwargs))
            except KeyError:
                continue
        return out

    def autopilot(self, profile: Profile | None = None, limit: int | None = None,
                  should_cancel=None) -> list[PreparedMaterials]:
        """Prepare materials for the best untouched matches (opt-in in Settings)."""
        profile = profile or self.workspace.load_profile()
        threshold = self.settings.autopilot_min_score
        limit = limit or self.settings.autopilot_max_per_run
        candidates = [row for row in self.tracker(profile)
                      if row.status in (ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED)
                      and row.score >= threshold]
        chosen = candidates[:max(0, limit)]
        prepared = self.prepare_batch(chosen, profile, should_cancel=should_cancel)
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
        """Draft the *next* rung of the follow-up ladder (escalating tone).

        Drafting advances the ladder: the next nudge is scheduled after
        ``follow_up_repeat_days`` (or, once ``follow_up_max_nudges`` was
        reached, the series ends and the application stops being "due").
        """
        record = (self.workspace.get_application(application)
                  if isinstance(application, str) else application)
        if record is None:
            raise KeyError(f"unknown application: {application}")
        job = self.workspace.get_job(record.job_id)
        if job is None:
            raise KeyError(f"job {record.job_id} is not in the workspace")
        profile = self.workspace.load_profile()
        level = record.follow_up_count
        max_nudges = max(0, int(self.settings.follow_up_max_nudges or 0))
        days = record.days_since_sent or self.settings.follow_up_days or DEFAULT_FOLLOW_UP_DAYS
        stage = "interview" if record.status_enum is ApplicationStatus.INTERVIEW else "sent"
        draft = render_follow_up(profile, job, days, stage, level, max_nudges)
        document = self.emails.follow_up(profile, job, days, stage,
                                         output_dir=self.workspace.documents_dir,
                                         fmt=fmt or self.settings.export_format,
                                         level=level, max_nudges=max_nudges)

        rung = level + 1
        record.follow_up_count = rung
        final = bool(max_nudges) and rung >= max_nudges
        if final:
            record.follow_up_at = ""
            record.log("follow-up series complete", f"nudge #{rung} of {max_nudges} drafted")
        else:
            repeat = max(1, int(self.settings.follow_up_repeat_days
                                or self.settings.follow_up_days or 5))
            record.schedule_follow_up(repeat)
            record.log("follow-up drafted", f"nudge #{rung} of the ladder - next in {repeat} day(s)")
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

    # -- interview prep ---------------------------------------------------- #
    def _record(self, application: Application | str) -> Application:
        record = (self.workspace.get_application(application)
                  if isinstance(application, str) else application)
        if record is None:
            raise KeyError(f"unknown application: {application}")
        return record

    def interview_prep(self, application: Application | str) -> InterviewPrep:
        """The stored prep sheet for an application (empty when none yet)."""
        return InterviewPrep.from_dict(self._record(application).prep)

    def save_interview_prep(self, application: Application | str, prep: InterviewPrep,
                            note: str = "") -> Application:
        record = self._record(application)
        record.prep = prep.to_dict()
        if note:
            record.log("interview prep", note)
        else:
            record.updated_at = now_iso()
        return self.workspace.save_application(record)

    def generate_interview_prep(self, application: Application | str,
                                profile: Profile | None = None) -> tuple[InterviewPrep, int]:
        """(Re)build the question bank for one application; keeps existing answers.

        Returns the merged prep and how many questions were newly added.
        """
        record = self._record(application)
        job = self.workspace.get_job(record.job_id)
        if job is None:
            raise KeyError(f"job {record.job_id} is not in the workspace")
        profile = profile or self.workspace.load_profile()
        prep = InterviewPrep.from_dict(record.prep)
        added = prep.merge_generated(generate_questions(profile, job, match_job(profile, job,
                                                                                 self.settings)))
        self.save_interview_prep(record, prep,
                                 f"question bank generated ({added} new, "
                                 f"{len(prep.questions)} total)")
        return prep, added

    def export_interview_prep(self, application: Application | str,
                              profile: Profile | None = None, fmt: str | None = None) -> Path:
        """Write the prep sheet to ``documents/`` and remember its path."""
        record = self._record(application)
        job = self.workspace.get_job(record.job_id)
        if job is None:
            raise KeyError(f"job {record.job_id} is not in the workspace")
        profile = profile or self.workspace.load_profile()
        prep = InterviewPrep.from_dict(record.prep)
        path = export_prep(prep, profile, job, self.workspace.documents_dir, record,
                           fmt or "md")
        record.prep_path = str(path)
        record.log("interview prep exported", path.name)
        self.workspace.save_application(record)
        return path

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
                             "Cover letter", "Email", "Prep", "Notes"])
            for row in rows:
                app = row.application
                writer.writerow([
                    row.job.title, row.job.company, row.job.location, "yes" if row.job.remote else "no",
                    row.job.source, row.score, app.status_enum.label, app.created_at,
                    app.sent_at, app.follow_up_at, app.interview_at, row.job.salary_text, row.job.url,
                    Path(app.cv_path).name if app.cv_path else "",
                    Path(app.cover_letter_path).name if app.cover_letter_path else "",
                    Path(app.email_path).name if app.email_path else "",
                    (f"{app.prep_answered_count}/{app.prep_question_count}"
                     if app.prep_question_count else ""),
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

    # -- analytics -------------------------------------------------------- #
    @staticmethod
    def _response_event(app: Application) -> tuple[date | None, ApplicationStatus | None]:
        """Earliest history event that moved the application to interview/offer/rejected."""
        stop = (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED)
        for event in app.history:
            if event.get("event") == "status" and event.get("to") in (s.value for s in stop):
                when = parse_date(event.get("at"))
                if when:
                    return when, ApplicationStatus(event["to"])
        return None, None

    def analytics(self, profile: Profile | None = None) -> dict:
        """Trend/funnel numbers for the Insights tab (GUI-free, SQLite-backed).

        Returns pipeline counts, a conversion funnel, a weekly series (created /
        sent / responded) for the last 8 ISO weeks, score buckets, response-time
        stats and per-source counts.
        """
        rows = self.tracker(profile)
        apps = self.workspace.applications()
        base = self.workspace.stats()

        response_days: list[tuple[str, str, int, str]] = []
        responded_by_week: Counter[str] = Counter()
        sent_by_week: Counter[str] = Counter()
        created_by_week: Counter[str] = Counter()
        for app in apps:
            created = parse_date(app.created_at)
            if created:
                created_by_week[created.isocalendar()[:2]] += 1
            sent = parse_date(app.sent_at)
            if sent:
                sent_by_week[sent.isocalendar()[:2]] += 1
            reply, status = self._response_event(app)
            if reply:
                responded_by_week[reply.isocalendar()[:2]] += 1
                days = (reply - sent).days if sent else None
                if days is not None:
                    job = self.workspace.get_job(app.job_id)
                    response_days.append((job.title if job else "?", job.company if job else "?",
                                          days, status.label if status else ""))

        now = date.today()
        series: list[dict] = []
        for offset in range(7, -1, -1):
            week_date = now - timedelta(weeks=offset)
            key = week_date.isocalendar()[:2]
            monday = date.fromisocalendar(*key, 1)
            series.append({
                "week": monday.strftime("%d %b"),
                "created": created_by_week.get(key, 0),
                "sent": sent_by_week.get(key, 0),
                "responded": responded_by_week.get(key, 0),
            })

        intervals = [(-1, 50, "weak <50"), (50, 65, "50-64"), (65, 80, "65-79"), (80, 101, "80-100")]
        buckets = [{"label": label, "count": sum(1 for r in rows if max(0, lo) <= r.score < hi)}
                   for lo, hi, label in intervals]

        days_only = sorted(d for _, _, d, _ in response_days)
        avg_reply = (round(sum(days_only) / len(days_only), 1) if days_only else None)
        median = days_only[len(days_only) // 2] if days_only else None

        by_source = Counter(job.source for job in self.workspace.jobs())
        return {
            "statuses": [{"key": s.value, "label": s.label, "count": base["by_status"][s.value]}
                         for s in ApplicationStatus.ordered()],
            "funnel": [
                {"label": "Tracked", "value": base["applications"]},
                {"label": "Sent", "value": base["sent"]},
                {"label": "Interview", "value": base["interviews"]},
                {"label": "Offer", "value": base["offers"]},
            ],
            "rates": {
                "response": base["response_rate"],
                "interview": base["interview_rate"],
                "offer": round(100 * base["offers"] / base["sent"], 1) if base["sent"] else 0.0,
                "avg_reply_days": avg_reply,
                "median_reply_days": median,
            },
            "weekly": series,
            "score_buckets": buckets,
            "response_times": sorted(response_days, key=lambda t: t[2])[:25],
            "by_source": [{"source": source_label(s), "count": c} for s, c in
                          by_source.most_common()],
        }

    def market_intelligence(self, profile: Profile | None = None,
                            limit: int = 50) -> list[dict]:
        """Which skill tags the market actually asks for, across stored postings.

        Each item: tag, how many postings advertise it, whether the candidate's
        profile already covers it, and up to three sample titles.
        """
        profile = profile or self.workspace.load_profile()
        profile_terms = set(keywords(_profile_text(profile), limit=600))
        counts: Counter[str] = Counter()
        titles: dict[str, set[str]] = {}
        for job in self.workspace.jobs():
            for tag in job.tags:
                term = str(tag).strip().lower()
                if not term or term in GENERIC_TERMS or len(term) < 3 or term.isdigit():
                    continue
                counts[term] += 1
                titles.setdefault(term, set()).add(job.title.strip()[:42])
        return [{"tag": term, "count": counts[term], "have": term in profile_terms,
                 "titles": sorted(titles[term])[:3]}
                for term, _ in counts.most_common(limit)]


__all__ = ["ApplicationPipeline", "MatchResult", "PreparedMaterials", "TrackedApplication",
           "match_job", "rank_jobs"]
