"""Lever postings API.

Endpoints (public):
  GET  https://api.lever.co/v0/postings/{company}?mode=json   -> list
  POST https://api.lever.co/v0/postings/{company}/{id}?key=K  -> apply (EXPERIMENTAL)

The apply endpoint requires a per-board key (visible in the board's web
configuration).  It only covers the basic fields (name / email / phone /
resume / links) — postings with required custom questions should be applied
to manually, which is why Lever apply is marked experimental and disabled
unless apply.lever_apply_key is set.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..models import Job, humanize_slug
from ..text import html_to_text
from .base import ApplicationSpec, Provider, Question, T_FILE, T_TEXT

BASE_URL = "https://api.lever.co/v0/postings"


class LeverProvider(Provider):
    name = "lever"
    supports_detail = False  # list payload already includes the description

    def __init__(self, client, apply_key: str = ""):
        super().__init__(client)
        self.apply_key = apply_key

    @property
    def apply_supported(self) -> bool:  # type: ignore[override]
        return bool(self.apply_key)

    # -- fetch ----------------------------------------------------------
    def fetch_jobs(self, board: str) -> List[Job]:
        payload = self.client.get_json(f"{BASE_URL}/{board}", params={"mode": "json"})
        if not isinstance(payload, list):
            raise ValueError(f"Unexpected Lever response for {board!r}")
        jobs: List[Job] = []
        for item in payload:
            categories = item.get("categories") or {}
            location = categories.get("location") or ""
            workplace = (item.get("workplaceType") or "").lower()
            created = item.get("createdAt")
            published_at = None
            if isinstance(created, (int, float)):
                published_at = datetime.fromtimestamp(
                    created / 1000.0, tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            description = self._description(item)
            jobs.append(
                Job(
                    provider=self.name,
                    provider_board=board,
                    provider_job_id=item.get("id") or "",
                    company=humanize_slug(board),
                    title=item.get("text") or "",
                    location=location,
                    url=item.get("hostedUrl") or "",
                    apply_url=item.get("applyUrl") or item.get("hostedUrl") or "",
                    remote=workplace == "remote" or "remote" in location.lower(),
                    description_html=item.get("description") or "",
                    description_text=description,
                    published_at=published_at,
                )
            )
        return jobs

    @staticmethod
    def _description(item: dict) -> str:
        parts = [item.get("descriptionPlain") or "", item.get("openingPlain") or ""]
        for section in item.get("lists") or []:
            if section.get("contentPlain") or section.get("content"):
                parts.append(
                    f"{section.get('text') or ''}\n{section.get('contentPlain') or html_to_text(section.get('content') or '')}"
                )
        return "\n\n".join(p for p in parts if p.strip())

    # -- apply (experimental) -------------------------------------------
    def get_application_spec(self, job: Job) -> Optional[ApplicationSpec]:
        if not self.apply_key:
            return None
        return ApplicationSpec(
            questions=[
                Question(name="name", label="Name", type=T_TEXT, required=True, kind="standard"),
                Question(name="email", label="Email", type=T_TEXT, required=True, kind="standard"),
                Question(name="phone", label="Phone", type=T_TEXT, required=False, kind="standard"),
                Question(name="resume", label="Resume", type=T_FILE, required=True, kind="standard"),
            ],
            notes=[
                "Lever auto-apply is experimental: only name / email / phone / resume are "
                "covered. Postings with required custom questions must be applied to manually."
            ],
        )

    def submit_application(
        self, job: Job, form: Dict[str, str], files: List[Tuple[str, str, bytes]]
    ) -> Tuple[bool, int, str]:
        if not self.apply_key:
            return False, 0, "No apply key configured (apply.lever_apply_key)"
        url = f"{BASE_URL}/{job.provider_board}/{job.provider_job_id}"
        payload = dict(form)
        payload.pop("resume", None)  # resume goes as a file part
        params = {"key": self.apply_key}
        if files:
            import mimetypes

            multipart = [
                (field, (filename, content, mimetypes.guess_type(filename)[0] or "application/octet-stream"))
                for field, filename, content in files
            ]
            response = self.client.post_multipart(url, data=payload, files=multipart)
        else:
            response = self.client._request("POST", url, params=params, data=payload)
        body = response.text or ""
        ok = 200 <= response.status_code < 300
        return ok, response.status_code, body[:500]
