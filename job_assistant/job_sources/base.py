"""Contracts for legally accessible job-source connectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class JobRecord:
    title: str
    company: str = ""
    location: str = ""
    country: str = ""
    description: str = ""
    job_url: str = ""
    external_id: str = ""
    source_name: str = "Public feed"
    application_email: str = ""
    application_method: str = "website"
    application_instructions: str = ""
    job_type: str = ""
    workplace_type: str = ""
    posted_at: str = ""
    closing_at: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)


class JobSourceConnector(Protocol):
    name: str

    def search(self, *, feed_url: str, titles: list[str], locations: list[str]) -> list[JobRecord]:
        """Return normalised jobs from a permitted feed or public API."""
