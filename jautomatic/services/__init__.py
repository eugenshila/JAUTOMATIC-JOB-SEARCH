"""Service layer - no GUI imports, safe to use from scripts and tests."""
from .application_pipeline import (ApplicationPipeline, MatchResult, PreparedMaterials,
                                   TrackedApplication, match_job, rank_jobs)
from .cover_letter import CoverLetterService, MatchContext, render_cover_letter
from .cv_generator import CVGenerator, GeneratedDocument, render_markdown
from .email_drafter import EmailDrafter, EmailDraft, render_email, render_follow_up
from .job_scraper import (AdzunaSource, ArbeitnowSource, JobScraper, JobSource, RemotiveSource,
                          RemoteOkSource, SampleSource, SearchOutcome, SearchQuery, default_sources)

__all__ = [
    "AdzunaSource", "ApplicationPipeline", "ArbeitnowSource", "CVGenerator", "CoverLetterService",
    "EmailDraft", "EmailDrafter", "GeneratedDocument", "JobScraper", "JobSource", "MatchContext",
    "MatchResult", "PreparedMaterials", "RemoteOkSource", "RemotiveSource", "SampleSource",
    "SearchOutcome", "SearchQuery", "TrackedApplication", "default_sources", "match_job",
    "rank_jobs", "render_cover_letter", "render_email", "render_follow_up", "render_markdown",
]
