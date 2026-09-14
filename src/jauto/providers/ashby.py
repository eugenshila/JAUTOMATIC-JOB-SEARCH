"""Ashby job board posting API (public, read-only).

  GET https://api.ashbyhq.com/posting-api/job-board/{org}  -> jobs w/ descriptions

Applications go through the web flow (https://jobs.ashbyhq.com/{org}/{id}/application),
so Ashby is fetch + match + deep-link only.
"""

from __future__ import annotations

from typing import List

from ..models import Job, humanize_slug
from ..text import html_to_text
from .base import Provider

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyProvider(Provider):
    name = "ashby"
    apply_supported = False
    supports_detail = False  # list payload includes descriptionHtml

    def fetch_jobs(self, board: str) -> List[Job]:
        payload = self.client.get_json(f"{BASE_URL}/{board}")
        jobs: List[Job] = []
        for item in payload.get("jobs") or []:
            location = item.get("location") or ""
            html = item.get("descriptionHtml") or ""
            jobs.append(
                Job(
                    provider=self.name,
                    provider_board=board,
                    provider_job_id=item.get("id") or "",
                    company=humanize_slug(board),
                    title=item.get("title") or "",
                    location=location,
                    url=item.get("jobUrl") or "",
                    apply_url=item.get("applyUrl") or item.get("jobUrl") or "",
                    remote=bool(item.get("isRemote")) or "remote" in location.lower(),
                    description_html=html,
                    description_text=html_to_text(html),
                    published_at=item.get("publishedAt"),
                )
            )
        return jobs
