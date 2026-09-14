"""Application paths and safe defaults.

The data directory deliberately lives outside the source tree so uploaded CVs,
application records, and the local database are not accidentally committed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from platformdirs import user_data_dir
except ImportError:  # pragma: no cover - dependency is declared, fallback aids bootstrapping
    user_data_dir = None

APP_NAME = "AI Job Application Assistant"
APP_SLUG = "AIJobApplicationAssistant"
DEFAULT_SEARCH_FREQUENCY = "Every 6 hours"
DEFAULT_LOCATIONS = [
    "Kenya",
    "Nairobi",
    "UAE",
    "Dubai",
    "Abu Dhabi",
    "Qatar",
    "Saudi Arabia",
    "Bahrain",
    "Oman",
    "International",
    "Remote jobs",
]
DEFAULT_JOB_TYPES = ["Full-time", "Permanent", "Contract", "Temporary", "Remote", "Hybrid", "On-site"]
DEFAULT_SOURCES = [
    "LinkedIn",
    "Indeed",
    "Glassdoor",
    "Google Jobs",
    "BrighterMonday",
    "MyJobMag",
    "Fuzu",
    "Bayt",
    "GulfTalent",
    "Naukrigulf",
    "Company career websites",
    "Recruitment agency websites",
    "Other public APIs / feeds",
]
DEFAULT_SETTINGS = {
    "appearance": "Dark",
    "start_with_windows": False,
    "start_minimized": True,
    "search_on_startup": True,
    "auto_apply": False,
    "search_frequency": DEFAULT_SEARCH_FREQUENCY,
    "auto_prepare_threshold": 75,
    "priority_threshold": 85,
    "minimum_match_threshold": 65,
    "selected_locations": ["Kenya", "Nairobi", "Remote jobs"],
    "selected_job_types": ["Full-time", "Permanent", "Remote"],
    "selected_sources": DEFAULT_SOURCES,
    "salary_min": "",
    "salary_max": "",
    "currency": "USD",
    "feed_urls": [],
    "target_titles": [],
}


@dataclass(frozen=True)
class AppPaths:
    """All user-writable paths used by the desktop application."""

    data_dir: Path

    @classmethod
    def default(cls) -> "AppPaths":
        if user_data_dir:
            base = Path(user_data_dir(APP_NAME, "JAUTOMATIC"))
        elif os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_SLUG
        else:
            base = Path.home() / ".local" / "share" / APP_SLUG
        return cls(base)

    @property
    def database(self) -> Path:
        return self.data_dir / "job_assistant.sqlite3"

    @property
    def master_cv_dir(self) -> Path:
        return self.data_dir / "MasterCV"

    @property
    def applications_dir(self) -> Path:
        return self.data_dir / "Applications"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "Logs"

    def ensure(self) -> None:
        for directory in (self.data_dir, self.master_cv_dir, self.applications_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
