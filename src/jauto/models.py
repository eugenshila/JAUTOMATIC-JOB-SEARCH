"""Core data model shared by providers, matcher, applier and storage."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse whitespace and lowercase — used for fuzzy comparisons."""
    return _WS.sub(" ", (text or "").strip()).lower()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def humanize_slug(slug: str) -> str:
    """'acme-corp' -> 'Acme Corp' — fallback company name for boards that
    don't return one."""
    return _WS.sub(" ", slug.replace("-", " ").replace("_", " ")).strip().title()


@dataclass
class Job:
    """A single job posting, provider-agnostic."""

    provider: str
    provider_board: str
    provider_job_id: str
    company: str
    title: str
    location: str = ""
    url: str = ""
    apply_url: str = ""
    remote: bool = False
    description_html: str = ""
    description_text: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: str = ""
    published_at: Optional[str] = None  # ISO-8601
    updated_at: Optional[str] = None  # ISO-8601

    @property
    def search_text(self) -> str:
        return f"{self.title}\n{self.description_text}".lower()

    def dedupe_key(self) -> str:
        basis = "|".join(
            normalize(x) for x in (self.company, self.title, self.location)
        )
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Row (database) round-trip
    # ------------------------------------------------------------------
    def to_row(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_board": self.provider_board,
            "provider_job_id": self.provider_job_id,
            "company": self.company,
            "title": self.title,
            "location": self.location,
            "url": self.url,
            "apply_url": self.apply_url,
            "remote": int(self.remote),
            "description_text": self.description_text,
            "description_html": self.description_html,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "currency": self.currency,
            "published_at": self.published_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Job":
        return cls(
            provider=row["provider"],
            provider_board=row["provider_board"],
            provider_job_id=row["provider_job_id"],
            company=row["company"],
            title=row["title"],
            location=row.get("location") or "",
            url=row.get("url") or "",
            apply_url=row.get("apply_url") or "",
            remote=bool(row.get("remote")),
            description_html=row.get("description_html") or "",
            description_text=row.get("description_text") or "",
            salary_min=row.get("salary_min"),
            salary_max=row.get("salary_max"),
            currency=row.get("currency") or "",
            published_at=row.get("published_at"),
            updated_at=row.get("updated_at"),
        )


# Statuses a job moves through.  'matched'/'skipped' are re-computed on each
# search; the rest are user-driven states that searches never overwrite.
JOB_STATUSES = (
    "new",  # inserted but not yet scored
    "matched",  # score >= threshold
    "skipped",  # below threshold or excluded
    "needs_review",  # auto-apply could not answer a required question
    "applied",  # application submitted
    "failed",  # submission attempted but rejected
    "manual",  # user flagged to apply by hand
    "hidden",  # user hid it from listings
)


@dataclass
class SearchStats:
    """Summary of one `search` run."""

    boards: Dict[str, int] = field(default_factory=dict)  # "provider/board" -> fetched
    new_jobs: int = 0
    matched: int = 0
    skipped: int = 0
    descriptions_fetched: int = 0
    errors: Dict[str, str] = field(default_factory=dict)  # "provider/board" -> error
