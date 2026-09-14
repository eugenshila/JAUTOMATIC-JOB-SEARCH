"""Greenhouse job board API.

Endpoints (public, no auth):
  GET /v1/boards/{token}/jobs                      -> list (light)
  GET /v1/boards/{token}/jobs/{id}?content=true    -> detail w/ description
  GET /v1/boards/{token}/jobs/{id}?questions=true  -> detail w/ form schema
  POST /v1/boards/{token}/jobs/{id}                -> submit application (multipart)

Docs: https://developers.greenhouse.io/job-board.html
"""

from __future__ import annotations

import mimetypes
from typing import Any, Dict, List, Optional, Tuple

from ..models import Job, humanize_slug
from ..text import html_to_text
from .base import (
    ApplicationSpec,
    Provider,
    Question,
    T_FILE,
    T_MULTI,
    T_SINGLE,
    T_TEXT,
    T_TEXTAREA,
)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

_TYPE_MAP = {
    "input_text": T_TEXT,
    "input_hidden": T_TEXT,
    "textarea": T_TEXTAREA,
    "input_file": T_FILE,
    "multi_value_single_select": T_SINGLE,
    "multi_value_multi_select": T_MULTI,
}


class GreenhouseProvider(Provider):
    name = "greenhouse"
    apply_supported = True
    supports_detail = True

    # -- fetch ----------------------------------------------------------
    def fetch_jobs(self, board: str) -> List[Job]:
        payload = self.client.get_json(f"{BASE_URL}/{board}/jobs")
        jobs: List[Job] = []
        for item in payload.get("jobs", []):
            location = (item.get("location") or {}).get("name") or ""
            jobs.append(
                Job(
                    provider=self.name,
                    provider_board=board,
                    provider_job_id=str(item.get("id") or ""),
                    company=item.get("company_name") or humanize_slug(board),
                    title=item.get("title") or "",
                    location=location,
                    url=item.get("absolute_url") or "",
                    apply_url=item.get("absolute_url") or "",
                    remote="remote" in location.lower(),
                    published_at=item.get("first_published"),
                    updated_at=item.get("updated_at"),
                )
            )
        return jobs

    def get_job_detail(self, job: Job) -> Job:
        payload = self.client.get_json(
            f"{BASE_URL}/{job.provider_board}/jobs/{job.provider_job_id}",
            params={"content": "true", "pay_transparency": "true"},
        )
        content = payload.get("content") or ""
        job.description_html = content
        job.description_text = html_to_text(content)
        pay = payload.get("pay_input_ranges") or []
        if pay:
            first = pay[0]
            if first.get("min_cents") is not None:
                job.salary_min = first["min_cents"] / 100.0
            if first.get("max_cents") is not None:
                job.salary_max = first["max_cents"] / 100.0
            job.currency = first.get("currency_type") or ""
        return job

    # -- apply ----------------------------------------------------------
    def get_application_spec(self, job: Job) -> Optional[ApplicationSpec]:
        payload = self.client.get_json(
            f"{BASE_URL}/{job.provider_board}/jobs/{job.provider_job_id}",
            params={"questions": "true"},
        )
        questions: List[Question] = []
        for group_key, kind in (
            ("questions", "custom"),
            ("location_questions", "custom"),
            ("compliance", "eeo"),
        ):
            for q in payload.get(group_key) or []:
                for f in q.get("fields") or []:
                    questions.append(
                        Question(
                            name=f.get("name") or "",
                            label=q.get("label") or f.get("name") or "",
                            type=_TYPE_MAP.get(f.get("type") or "", T_TEXT),
                            required=bool(q.get("required")),
                            options=[
                                (v.get("value"), v.get("label"))
                                for v in (f.get("values") or [])
                                if v.get("value") is not None
                            ],
                            kind=kind,
                        )
                    )
        # demographic questions (Greenhouse Inclusion) are always optional
        for q in (payload.get("demographic_questions") or {}).get("questions") or []:
            for f in q.get("fields") or []:
                questions.append(
                    Question(
                        name=f.get("name") or f"demographic_{q.get('id')}",
                        label=q.get("label") or "",
                        type=_TYPE_MAP.get(f.get("type") or "", T_MULTI),
                        required=False,
                        options=[
                            (v.get("id"), v.get("label"))
                            for v in (q.get("answer_options") or [])
                        ],
                        kind="demographic",
                    )
                )
        gdpr = any(
            dc.get("requires_consent")
            or dc.get("requires_processing_consent")
            or dc.get("requires_retention_consent")
            for dc in payload.get("data_compliance") or []
        )
        return ApplicationSpec(questions=questions, requires_gdpr_consent=gdpr)

    def submit_application(
        self, job: Job, form: Dict[str, Any], files: List[Tuple[str, str, bytes]]
    ) -> Tuple[bool, int, str]:
        url = f"{BASE_URL}/{job.provider_board}/jobs/{job.provider_job_id}"
        multipart_files = [
            (field, (filename, content, mimetypes.guess_type(filename)[0] or "application/octet-stream"))
            for field, filename, content in files
        ]
        response = self.client.post_multipart(url, data=form, files=multipart_files)
        body = response.text or ""
        ok = 200 <= response.status_code < 300
        if ok:
            # Greenhouse returns an empty body or a JSON status on success
            return True, response.status_code, body or "OK"
        return False, response.status_code, body[:500]
