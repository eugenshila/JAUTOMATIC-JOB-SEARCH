"""Provider registry and careers-URL detection."""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from ..net import Client
from .ashby import AshbyProvider
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
from .greenhouse import GreenhouseProvider
from .lever import LeverProvider
from .smartrecruiters import SmartRecruitersProvider
from .workable import WorkableProvider

__all__ = [
    "ApplicationSpec",
    "Provider",
    "Question",
    "T_FILE",
    "T_MULTI",
    "T_SINGLE",
    "T_TEXT",
    "T_TEXTAREA",
    "GreenhouseProvider",
    "LeverProvider",
    "AshbyProvider",
    "SmartRecruitersProvider",
    "WorkableProvider",
    "build_providers",
    "detect_from_url",
    "PROVIDER_CLASSES",
]

PROVIDER_CLASSES = {
    "greenhouse": GreenhouseProvider,
    "lever": LeverProvider,
    "ashby": AshbyProvider,
    "smartrecruiters": SmartRecruitersProvider,
    "workable": WorkableProvider,
}


def build_providers(client: Client, lever_apply_key: str = "") -> Dict[str, Provider]:
    providers: Dict[str, Provider] = {}
    for name, cls in PROVIDER_CLASSES.items():
        if name == "lever":
            providers[name] = cls(client, apply_key=lever_apply_key)
        else:
            providers[name] = cls(client)
    return providers


# careers-page URL patterns -> (provider, board token)
_URL_PATTERNS = [
    (re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I), "greenhouse"),
    (re.compile(r"https?://jobs\.lever\.co/([A-Za-z0-9_-]+)", re.I), "lever"),
    (re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)", re.I), "ashby"),
    (re.compile(r"https?://careers\.smartrecruiters\.com/([A-Za-z0-9_.-]+)", re.I), "smartrecruiters"),
    (re.compile(r"https?://(?:apply\.)?([A-Za-z0-9_-]+)\.workable\.com", re.I), "workable"),
]


def detect_from_url(url: str) -> Optional[Tuple[str, str]]:
    """Detect (provider, board) from a careers page or job posting URL."""
    url = (url or "").strip()
    for pattern, provider in _URL_PATTERNS:
        match = pattern.match(url)
        if match:
            board = match.group(1)
            if provider == "workable" and board.lower() == "apply":
                # https://apply.workable.com/{sub} form
                tail = re.match(r"https?://apply\.workable\.com/([A-Za-z0-9_-]+)", url, re.I)
                if tail:
                    return provider, tail.group(1)
                return None
            return provider, board
    return None
