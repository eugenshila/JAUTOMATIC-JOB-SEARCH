"""Configuration loading & validation (config.yaml)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import yaml

PROVIDER_NAMES = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable")

DEFAULT_WEIGHTS = {"title": 35.0, "skills": 35.0, "location": 20.0, "freshness": 10.0}


class ConfigError(Exception):
    """Raised when the config file is missing, unparseable or invalid."""


@dataclass
class Profile:
    first_name: str = ""
    last_name: str = ""
    preferred_name: str = ""  # falls back to first_name
    email: str = ""
    phone: str = ""
    location: str = ""
    resume_path: str = ""  # file upload (pdf/docx)
    resume_text_path: str = ""  # plain-text fallback for text-only fields
    cover_letter_path: str = ""  # file upload
    cover_letter_template: str = ""  # template rendered per job -> *_text field
    years_experience: str = ""
    links: Dict[str, str] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass
class MatchingConfig:
    titles: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    exclude_titles: List[str] = field(default_factory=list)
    company_blacklist: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    remote_only: bool = False
    threshold: float = 50.0
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class ApplyConfig:
    min_score: float = 60.0
    max_per_run: int = 10
    daily_limit: int = 15
    submit_delay: float = 5.0  # seconds between real submissions
    auto_submit: bool = False  # allow `run`/`apply --auto` to submit without --yes
    require_resume: bool = True
    consent_gdpr: bool = False  # auto-answer GDPR consent questions with "yes"
    answers: Dict[str, str] = field(default_factory=dict)  # label -> answer
    eeo_answers: Dict[str, str] = field(default_factory=dict)  # label -> option label
    lever_apply_key: str = ""  # required for Lever auto-apply


@dataclass
class NetworkConfig:
    request_delay: float = 1.0  # seconds between requests (be polite)
    timeout: float = 20.0
    retries: int = 2  # GET retries with backoff; POSTs are never retried
    max_description_fetches: int = 60  # per search run
    contact_email: str = ""  # goes into the User-Agent


@dataclass
class Config:
    sources: Dict[str, List[str]] = field(default_factory=dict)
    profile: Profile = field(default_factory=Profile)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    apply: ApplyConfig = field(default_factory=ApplyConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    db_path: str = "jauto.db"
    base_dir: str = "."  # directory of the config file; relative paths resolve here

    # ------------------------------------------------------------------
    def resolve_path(self, path: str) -> str:
        if not path:
            return path
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.base_dir, path))

    @property
    def db_file(self) -> str:
        return self.resolve_path(self.db_path)

    @property
    def resume_file(self) -> str:
        return self.resolve_path(self.profile.resume_path)

    # ------------------------------------------------------------------
    @staticmethod
    def load(path: str) -> "Config":
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise ConfigError(
                f"Config file not found: {path}\n"
                "Create one with:  jauto init"
            )
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Could not parse {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"{path} must contain a YAML mapping at top level")

        problems: List[str] = []
        sources = _as_str_list(raw.get("sources"), "sources", problems)
        for name in sources:
            if name not in PROVIDER_NAMES:
                problems.append(f"Unknown provider in sources: {name!r} "
                                f"(expected one of {', '.join(PROVIDER_NAMES)})")

        cfg = Config(
            sources=sources,
            profile=_fill(Profile(), raw.get("profile") or {}),
            matching=_fill(MatchingConfig(), raw.get("matching") or {}),
            apply=_fill(ApplyConfig(), raw.get("apply") or {}),
            network=_fill(NetworkConfig(), raw.get("network") or {}),
            db_path=str(raw.get("db_path") or "jauto.db"),
            base_dir=os.path.dirname(path),
        )
        # normalise matching weights
        weights = dict(DEFAULT_WEIGHTS)
        user_weights = cfg.matching.weights or {}
        if not isinstance(user_weights, dict):
            problems.append("matching.weights must be a mapping")
            user_weights = {}
        for key in user_weights:
            if key not in weights:
                problems.append(f"matching.weights has unknown key {key!r}")
        weights.update({k: float(v) for k, v in user_weights.items() if k in weights})
        cfg.matching.weights = weights

        if problems:
            raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))
        return cfg

    # ------------------------------------------------------------------
    def validate_for_apply(self) -> Tuple[List[str], List[str]]:
        """Return (errors, warnings) about readiness for auto-apply."""
        errors, warnings = [], []
        p = self.profile
        for attr, label in (
            ("first_name", "profile.first_name"),
            ("last_name", "profile.last_name"),
            ("email", "profile.email"),
        ):
            if not getattr(p, attr):
                errors.append(f"Missing {label} — required on every application form")
        if self.apply.require_resume:
            if not p.resume_path:
                errors.append("Missing profile.resume_path — most forms require a resume")
            elif not os.path.isfile(self.resolve_path(p.resume_path)):
                errors.append(f"Resume not found: {self.resolve_path(p.resume_path)}")
            elif p.resume_path and not p.resume_text_path:
                pass
        if p.resume_text_path and not os.path.isfile(self.resolve_path(p.resume_text_path)):
            errors.append(f"Resume text file not found: {self.resolve_path(p.resume_text_path)}")
        if not p.phone:
            warnings.append("profile.phone is empty — some forms require it")
        if not p.location:
            warnings.append("profile.location is empty — some forms require it")
        if not self.network.contact_email:
            warnings.append(
                "network.contact_email is empty — set it so job boards can contact you "
                "about your API usage (good citizenship)"
            )
        if not p.links.get("linkedin"):
            warnings.append("profile.links.linkedin is empty — many forms ask for it")
        return errors, warnings


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _fill(instance: Any, data: Dict[str, Any]) -> Any:
    """Populate a dataclass from a dict, ignoring unknown keys, casting
    where the dataclass declares a non-string type."""
    import dataclasses

    hints = {f.name: f.type for f in dataclasses.fields(instance)}
    for key, value in (data or {}).items():
        if key not in hints or value is None:
            continue
        if isinstance(value, dict):
            current = getattr(instance, key, None)
            if isinstance(current, dict):
                current.update(value)
                continue
        setattr(instance, key, value)
    return instance


def _as_str_list(value: Any, where: str, problems: List[str]) -> Dict[str, List[str]]:
    """sources: {provider: [board, ...]}"""
    if not value:
        return {}
    if not isinstance(value, dict):
        problems.append(f"{where} must be a mapping of provider -> list of boards")
        return {}
    result: Dict[str, List[str]] = {}
    for provider, boards in value.items():
        if boards is None:
            boards = []
        if isinstance(boards, str):
            boards = [boards]
        if not isinstance(boards, list) or not all(isinstance(b, str) for b in boards):
            problems.append(f"sources.{provider} must be a list of board tokens")
            continue
        cleaned: List[str] = []
        for board in boards:
            board = board.strip().strip("/")
            if board and board not in cleaned:
                cleaned.append(board)
        if cleaned:
            result[provider.strip()] = cleaned
    return result


def load_config(path: str) -> Config:
    return Config.load(path)


def add_source(config_path: str, provider: str, board: str) -> bool:
    """Append a board to sources.<provider> in the YAML file.

    Returns True if it was added, False if it was already present.
    Comments in the file are not preserved (plain safe_dump round-trip).
    """
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    sources = raw.get("sources") or {}
    boards = sources.get(provider) or []
    if board in boards:
        return False
    boards.append(board)
    sources[provider] = boards
    raw["sources"] = sources
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return True
