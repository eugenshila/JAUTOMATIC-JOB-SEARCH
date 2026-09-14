"""Search orchestration for user-configured permitted feeds."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from job_assistant.database.repository import Repository
from job_assistant.job_sources import JobRecord, PublicFeedConnector
from job_assistant.models.entities import CandidateProfile
from job_assistant.services.documents import DocumentGenerator
from job_assistant.services.matching import match_job


@dataclass
class SearchSummary:
    jobs_found: int = 0
    new_jobs: int = 0
    excellent_matches: int = 0
    strong_matches: int = 0
    applications_prepared: int = 0
    errors: list[str] = field(default_factory=list)


class SearchOrchestrator:
    def __init__(self, repository: Repository, applications_dir: str):
        self.repository = repository
        self.connector = PublicFeedConnector()
        self.documents = DocumentGenerator(applications_dir)

    def run(self, config: dict[str, Any]) -> SearchSummary:
        summary = SearchSummary()
        search_id = self.repository.create_search_history(config)
        feed_sources = parse_feed_sources(config.get("feed_urls", []))
        if not feed_sources:
            self.repository.complete_search_history(search_id, status="no_sources")
            summary.errors.append("No approved feed URLs are configured. Add a line such as LinkedIn | https://your-approved-feed.xml.")
            return summary
        profile = self.repository.get_profile()
        titles = config.get("target_titles") or profile.job_titles
        locations = config.get("selected_locations", [])
        thresholds = {
            "priority_threshold": int(config.get("priority_threshold", 85)),
            "auto_prepare_threshold": int(config.get("auto_prepare_threshold", 75)),
            "minimum_match_threshold": int(config.get("minimum_match_threshold", 65)),
        }
        try:
            for source_name, feed_url in feed_sources:
                try:
                    records = self.connector.search(feed_url=feed_url, titles=titles, locations=locations, source_name=source_name)
                except Exception as exc:  # noqa: BLE001 - one bad feed should not stop other feeds
                    summary.errors.append(f"{source_name} ({feed_url}): {exc}")
                    continue
                summary.jobs_found += len(records)
                for record in records:
                    job_id, is_new = self.repository.upsert_job(record)
                    summary.new_jobs += int(is_new)
                    analysis = match_job(profile, record, thresholds=thresholds)
                    self.repository.save_job_match(job_id, analysis["score"], analysis["category"], matched=analysis["matched"], missing=analysis["missing"], preferred=analysis["preferred"], reasons=analysis["reasons"], recommendation=analysis["recommendation"])
                    if analysis["score"] >= 90:
                        summary.excellent_matches += 1
                    elif analysis["score"] >= 80:
                        summary.strong_matches += 1
                    if analysis["score"] >= thresholds["auto_prepare_threshold"]:
                        application_id = self.repository.ensure_application(job_id, analysis["score"])
                        try:
                            paths = self.documents.prepare(profile, record.__dict__, analysis)
                            self.repository.save_application_documents(application_id, cv_path=paths["cv_docx"], cover_letter_path=paths["cover_letter_docx"], needs_attention=record.application_method.lower() in {"manual", "email"})
                            summary.applications_prepared += 1
                        except Exception as exc:  # noqa: BLE001 - retain the job even if a document provider is unavailable
                            summary.errors.append(f"Documents for {record.title}: {exc}")
            status = "completed_with_errors" if summary.errors else "completed"
            self.repository.complete_search_history(search_id, status=status, jobs_found=summary.jobs_found, new_jobs=summary.new_jobs, error_message="; ".join(summary.errors)[:2000])
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(str(exc))
            self.repository.complete_search_history(search_id, status="failed", jobs_found=summary.jobs_found, new_jobs=summary.new_jobs, error_message=str(exc))
        return summary


def parse_feed_sources(values: list[str]) -> list[tuple[str, str]]:
    """Parse ``Source name | URL`` lines while accepting plain URLs."""
    result: list[tuple[str, str]] = []
    for value in values:
        line = str(value).strip()
        if not line:
            continue
        if "|" in line:
            label, url = line.split("|", 1)
            label, url = label.strip(), url.strip()
            if label and url:
                result.append((label, url))
                continue
        result.append(("Public API / RSS feed", line))
    return result


def extract_email(value: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
    return match.group(0) if match else ""
