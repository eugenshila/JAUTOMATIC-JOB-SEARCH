"""Service layer - no GUI imports, safe to use from scripts and tests."""
from .application_pipeline import (ApplicationPipeline, MatchResult, PreparedMaterials,
                                   TrackedApplication, match_job, rank_jobs)
from .calendar_export import (CalendarEvent, build_calendar, escape_text, events_for, fold_line,
                              parse_when, unfold)
from .cover_letter import CoverLetterService, MatchContext, render_cover_letter
from .cv_generator import CVGenerator, GeneratedDocument, render_markdown
from .email_drafter import EmailDrafter, EmailDraft, render_email, render_follow_up
from .job_scraper import (AdzunaSource, ArbeitnowSource, JobScraper, JobSource, RemotiveSource,
                          RemoteOkSource, SampleSource, SearchOutcome, SearchQuery, default_sources)

__all__ = [
    "AdzunaSource", "ApplicationPipeline", "ArbeitnowSource", "CVGenerator", "CalendarEvent",
    "CoverLetterService", "EmailDraft", "EmailDrafter", "GeneratedDocument", "JobScraper",
    "JobSource", "MatchContext", "MatchResult", "PreparedMaterials", "RemoteOkSource",
    "RemotiveSource", "SampleSource", "SearchOutcome", "SearchQuery", "TrackedApplication",
    "build_calendar", "default_sources", "escape_text", "events_for", "fold_line", "match_job",
    "parse_when", "rank_jobs", "render_cover_letter", "render_email", "render_follow_up",
    "render_markdown", "unfold",
]
