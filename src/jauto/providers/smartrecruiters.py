"""SmartRecruiters public postings API.

  GET https://api.smartrecruiters.com/v1/companies/{company}/postings       -> list
  GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}  -> detail

Applications require SmartRecruiters partner OAuth, so this provider is
fetch + match + deep-link only (https://careers.smartrecruiters.com/{company}/{id}).
"""

from __future__ import annotations

from typing import List

from ..models import Job
from ..text import html_to_text
from .base import Provider

BASE_URL = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 50
MAX_PAGES = 10  # safety cap


class SmartRecruitersProvider(Provider):
    name = "smartrecruiters"
    apply_supported = False
    supports_detail = True  # detail endpoint carries the job ad

    def fetch_jobs(self, board: str) -> List[Job]:
        jobs: List[Job] = []
        offset = 0
        for _ in range(MAX_PAGES):
            payload = self.client.get_json(
                f"{BASE_URL}/{board}/postings",
                params={"limit": PAGE_SIZE, "offset": offset},
            )
            content = payload.get("content") or []
            if not content:
                break
            for item in content:
                loc = item.get("location") or {}
                location = ", ".join(
                    p for p in (loc.get("city"), loc.get("country")) if p
                )
                job_id = item.get("id") or ""
                company = (item.get("company") or {}).get("name") or board
                jobs.append(
                    Job(
                        provider=self.name,
                        provider_board=board,
                        provider_job_id=job_id,
                        company=company,
                        title=item.get("name") or "",
                        location=location,
                        url=f"https://careers.smartrecruiters.com/{board}/{job_id}",
                        apply_url=f"https://careers.smartrecruiters.com/{board}/{job_id}",
                        remote=bool(loc.get("remote")),
                        published_at=item.get("releasedDate"),
                    )
                )
            offset += PAGE_SIZE
            if offset >= int(payload.get("totalFound") or 0):
                break
        return jobs

    def get_job_detail(self, job: Job) -> Job:
        payload = self.client.get_json(
            f"{BASE_URL}/{job.provider_board}/postings/{job.provider_job_id}"
        )
        job_ad = payload.get("jobAd") or {}
        sections = job_ad.get("sections") or {}
        html_parts = [
            (sections.get(key) or {}).get("text") or ""
            for key in ("jobDescription", "qualifications", "aboutTheCompany")
        ]
        html = "\n".join(p for p in html_parts if p)
        if html:
            job.description_html = html
            job.description_text = html_to_text(html)
        return job
