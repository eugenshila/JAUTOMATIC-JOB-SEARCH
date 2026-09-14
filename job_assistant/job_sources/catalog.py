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
    manual_fallback: bool = True


SOURCE_CATALOG = (
    SourceDefinition("LinkedIn", "Official API or approved partner feed"),
    SourceDefinition("Indeed", "Official API, approved feed, or permitted endpoint"),
    SourceDefinition("Glassdoor", "Official API, approved feed, or permitted endpoint"),
    SourceDefinition("Google Jobs", "Licensed/approved provider feed"),
    SourceDefinition("BrighterMonday", "Official API/feed or explicit permission"),
    SourceDefinition("MyJobMag", "Official API/feed or explicit permission"),
    SourceDefinition("Fuzu", "Official API/feed or explicit permission"),
    SourceDefinition("Bayt", "Official API/feed or explicit permission"),
    SourceDefinition("GulfTalent", "Official API/feed or explicit permission"),
    SourceDefinition("Naukrigulf", "Official API/feed or explicit permission"),
    SourceDefinition("Company career websites", "Official careers API/RSS/XML feed"),
    SourceDefinition("Recruitment agency websites", "Official API/RSS/XML feed"),
    SourceDefinition("Other public APIs / feeds", "User-approved public API/RSS/XML feed"),
)

SOURCE_NAMES = [source.name for source in SOURCE_CATALOG]
