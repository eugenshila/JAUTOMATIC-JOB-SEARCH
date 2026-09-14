"""Provider base classes: fetch jobs, describe application forms, submit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..models import Job

# Normalised question types
T_TEXT = "text"
T_TEXTAREA = "textarea"
T_FILE = "file"
T_SINGLE = "single_select"
T_MULTI = "multi_select"


@dataclass
class Question:
    """One normalised application-form field, provider-agnostic."""

    name: str  # form field name, e.g. 'first_name' or 'question_12345'
    label: str  # human label shown on the form
    type: str  # one of the T_* constants
    required: bool = False
    options: List[Tuple[str, str]] = field(default_factory=list)  # (value, label)
    kind: str = "custom"  # 'standard' | 'custom' | 'eeo' | 'demographic'


@dataclass
class ApplicationSpec:
    """Everything needed to build an application for one job."""

    questions: List[Question] = field(default_factory=list)
    requires_gdpr_consent: bool = False
    notes: List[str] = field(default_factory=list)


class Provider:
    """Base class for ATS integrations."""

    name = "base"
    apply_supported = False  # can submit applications via API
    supports_detail = False  # can fetch full description per job

    def __init__(self, client):
        self.client = client

    # -- fetch ----------------------------------------------------------
    def fetch_jobs(self, board: str) -> List[Job]:
        """List all open jobs for a board/company token."""
        raise NotImplementedError

    def get_job_detail(self, job: Job) -> Job:
        """Return the job with a full description (only if supports_detail)."""
        return job

    # -- apply ----------------------------------------------------------
    def get_application_spec(self, job: Job) -> Optional[ApplicationSpec]:
        """Return the application form definition, or None if unavailable."""
        return None

    def submit_application(
        self, job: Job, form: dict, files: List[Tuple[str, str, bytes]]
    ) -> Tuple[bool, int, str]:
        """Submit an application. Returns (ok, http_status, response_body).

        Implementations MUST NOT retry — a retried POST could duplicate an
        application.
        """
        raise NotImplementedError(
            f"{self.name} does not support automatic applications yet"
        )
