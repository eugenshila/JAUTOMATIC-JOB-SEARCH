"""Source catalog and access-policy metadata.

A name in this catalog is not permission to scrape that site. A connector can
only be enabled when the user supplies an official API, approved feed, or
public endpoint whose terms allow automated access. Otherwise the application
falls back to opening the official job page for manual review.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    automated_route: str
    documentation_url: str = ""
    manual_url: str = ""
    manual_fallback: bool = True


SOURCE_CATALOG = (
    SourceDefinition("LinkedIn", "Official partner API only; no open job-search API found", "https://developer.linkedin.com/", "https://www.linkedin.com/jobs/"),
    SourceDefinition("Indeed", "Official employer/partner APIs; no open read-side search API", "https://docs.indeed.com/", "https://www.indeed.com/"),
    SourceDefinition("Glassdoor", "Approved provider/API only; no open public search API", "https://www.glassdoor.com/about/api/", "https://www.glassdoor.com/Job/"),
    SourceDefinition("Google Jobs", "Use an approved jobs-data provider; Google for Jobs is publisher markup", "https://developers.google.com/search/docs/appearance/structured-data/job-posting", "https://www.google.com/search?q=jobs"),
    SourceDefinition("BrighterMonday", "Official feed/API or explicit permission", "https://www.brightermonday.co.ke/", "https://www.brightermonday.co.ke/jobs"),
    SourceDefinition("MyJobMag", "Official RSS feeds are published by MyJobMag", "https://www.myjobmag.co.ke/feeds/", "https://www.myjobmag.co.ke/jobs"),
    SourceDefinition("Fuzu", "Official feed/API or explicit permission", "https://www.fuzu.com/", "https://www.fuzu.com/kenya/jobs"),
    SourceDefinition("Bayt", "Official feed/API or explicit permission", "https://www.bayt.com/", "https://www.bayt.com/en/international/jobs/"),
    SourceDefinition("GulfTalent", "Official feed/API or explicit permission", "https://www.gulftalent.com/", "https://www.gulftalent.com/jobs"),
    SourceDefinition("Naukrigulf", "Official feed/API or explicit permission", "https://www.naukrigulf.com/", "https://www.naukrigulf.com/jobs"),
    SourceDefinition("Company career websites", "Public ATS feeds such as Greenhouse, Lever, or SmartRecruiters", "https://docs.greenhouse.io/job-board.html", "https://careers.google.com/jobs/results/"),
    SourceDefinition("Recruitment agency websites", "Official feed/API or explicit permission", "", "https://www.google.com/search?q=recruitment+agency+jobs"),
    SourceDefinition("Other public APIs / feeds", "User-approved public API/RSS/XML feed", "https://developer.adzuna.com/docs/search", "https://www.google.com/search?q=jobs"),
)

SOURCE_NAMES = [source.name for source in SOURCE_CATALOG]
SOURCE_BY_NAME = {source.name: source for source in SOURCE_CATALOG}
