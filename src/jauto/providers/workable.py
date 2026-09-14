"""Workable widget API (public, read-only).

  GET https://apply.workable.com/api/v1/widget/accounts/{subdomain}?details=true

Returns the board with full job details in one call.  Applications go through
the web flow, so this provider is fetch + match + deep-link only.
"""

from __future__ import annotations

from typing import List

from ..models import Job
from ..text import html_to_text
from .base import Provider

BASE_URL = "https://apply.workable.com/api/v1/widget/accounts"


class WorkableProvider(Provider):
    name = "workable"
    apply_supported = False
    supports_detail = False  # details=true already includes descriptions

    def fetch_jobs(self, board: str) -> List[Job]:
        payload = self.client.get_json(f"{BASE_URL}/{board}", params={"details": "true"})
        company = payload.get("name") or board
        jobs: List[Job] = []
        for item in payload.get("jobs") or []:
            loc = item.get("location") or {}
            location = ", ".join(
                p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p
            )
            shortcode = item.get("shortcode") or ""
            url = item.get("url") or (
                f"https://apply.workable.com/{board}/j/{shortcode}" if shortcode else ""
            )
            description = item.get("description") or ""
            jobs.append(
                Job(
                    provider=self.name,
                    provider_board=board,
                    provider_job_id=str(item.get("id") or shortcode),
                    company=company,
                    title=item.get("title") or "",
                    location=location,
                    url=url,
                    apply_url=url,
                    remote=bool(loc.get("remote")) or "remote" in location.lower(),
                    description_html=description,
                    description_text=html_to_text(description),
                    published_at=item.get("published_on") or item.get("publishedOn"),
                )
            )
        return jobs
