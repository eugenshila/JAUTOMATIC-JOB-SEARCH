"""Domain models + persistence for JAUTOMATIC JOB SEARCH.

Everything the app stores lives in one place:

* a SQLite database (``jobs``, ``applications``) inside the user data dir,
* a ``profile.json`` and ``settings.json`` next to it for the human-editable
  bits (personal data, preferences, feature switches).

The module deliberately has no GUI imports so it can be unit-tested and reused
head-less (``python -m jautomatic.models`` prints the resolved data dir).
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

APP_NAME = "JAUTOMATIC"
APP_SLUG = "jautomatic-job-search"
SCHEMA_VERSION = 4
DEFAULT_FOLLOW_UP_DAYS = 7


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    """Local timestamp without microseconds, ISO-8601 - sortable as text."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def today_iso() -> str:
    return date.today().isoformat()


def default_data_dir() -> Path:
    """Per-user writable location, overridable with ``--data-dir``."""
    import os

    if os.environ.get("JAUTOMATIC_DATA_DIR"):
        return Path(os.environ["JAUTOMATIC_DATA_DIR"]).expanduser()
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "JAUTOMATIC"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_SLUG


def slugify(text: str, max_length: int = 60) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return text[:max_length] or "untitled"


def unique_document_path(directory: str | Path, stem: str, suffix: str, *,
                         key: str = "", reuse: str | Path | None = None) -> Path:
    """Pick a path for a generated document that never clobbers an unrelated file.

    ``slugify`` normalises hard (truncation, every non-alphanumeric run becomes
    ``-``), so two *different* (company, title) pairs can produce the same
    ``stem`` — and the second write would silently overwrite the first
    application's CV.  The rules below keep names deterministic without any
    cross-run state:

    * ``reuse`` (the caller's own previously generated path) wins outright:
      regenerating materials for the *same* application updates it in place
      instead of accumulating copies.
    * Otherwise the plain ``<stem><suffix>`` name is used when free — the
      overwhelmingly common case, so file names stay human-readable.
    * If it is taken, a short hash of the *un-slugified* identity (``key``)
      disambiguates: ``<stem>-a3f9<suffix>``.  Identical raw input hashes to
      the same suffix, while different inputs that merely slugify alike get
      distinct names.
    * The (astronomically unlikely) same-digest collision falls back to
      ``-2``, ``-3``, …
    """
    directory = Path(directory)
    if reuse:
        return Path(reuse)
    def occupied(path: Path) -> bool:
        # Word/PDF exports may share a stem as a pair. Reserve both names so
        # an unrelated Word-only document cannot be overwritten by a new pair.
        if path.suffix in (".pdf", ".docx"):
            return any(path.with_suffix(ext).exists() for ext in (".pdf", ".docx"))
        return path.exists()

    candidate = directory / f"{stem}{suffix}"
    if not occupied(candidate):
        return candidate
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:4]
    candidate = directory / f"{stem}-{digest}{suffix}"
    counter = 2
    while occupied(candidate):
        candidate = directory / f"{stem}-{digest}-{counter}{suffix}"
        counter += 1
    return candidate


def _json_dict(raw: object) -> dict:
    """Parse a JSON object column defensively (bad/missing -> ``{}``)."""
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_date(value: object) -> date | None:
    """Best-effort date parser for job-board payloads (ISO, RFC-2822, epoch)."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d %b %Y", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            if fmt is None:
                return datetime.fromisoformat(text).date()
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        try:
            return date.fromisoformat(match.group(0))
        except ValueError:
            return None
    return None


def strip_html(raw: str) -> str:
    """Job boards love HTML soup - reduce it to readable plain text."""
    if not raw:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
                .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


GENERIC_TERMS = {
    "senior", "junior", "mid", "lead", "staff", "principal", "head", "chief", "associate",
    "engineer", "engineering", "developer", "manager", "management", "specialist", "analyst",
    "consultant", "architect", "designer", "administrator", "coordinator", "director",
    "data", "role", "team", "teams", "company", "position", "opportunity", "candidate",
    "requirements", "requirement", "responsibilities", "qualifications", "experience",
    "skills", "strong", "excellent", "good", "great", "proven", "solid", "bonus", "nice",
    "remote", "hybrid", "onsite", "office", "location", "salary", "benefits", "apply",
    "full", "part", "time", "fulltime", "contract", "permanent", "freelance", "internship",
    "about", "your", "will", "you", "our", "their", "with", "plus", "years", "year",
    "stack", "product", "products", "service", "services", "platform", "systems",
}

WORDS = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-]*")

# Display names for job sources (the cover letter / e-mail mention where a role was found).
SOURCE_LABELS = {
    "remotive": "Remotive", "arbeitnow": "Arbeitnow", "remoteok": "RemoteOK",
    "himalayas": "Himalayas", "uae_ai": "UAE AI jobs",
    "adzuna": "Adzuna", "sample": "the sample job feed", "manual": "manually pasted link",
    "linkedin": "LinkedIn (browser)",
}

# Terms that look wrong when title-cased naively - used when skills appear in prose.
PRETTY_TERMS = {
    "python": "Python", "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
    "postgresql": "PostgreSQL", "postgres": "Postgres", "mysql": "MySQL", "sqlite": "SQLite",
    "sql": "SQL", "nosql": "NoSQL", "graphql": "GraphQL", "rest": "REST", "rest apis": "REST APIs",
    "api": "API", "apis": "APIs", "aws": "AWS", "gcp": "GCP", "azure": "Azure", "s3": "S3",
    "ec2": "EC2", "k8s": "Kubernetes", "kubernetes": "Kubernetes", "docker": "Docker",
    "terraform": "Terraform", "ansible": "Ansible", "airflow": "Airflow", "dbt": "dbt",
    "snowflake": "Snowflake", "bigquery": "BigQuery", "spark": "Spark", "kafka": "Kafka",
    "redis": "Redis", "celery": "Celery", "pytest": "pytest", "unittest": "unittest",
    "typescript": "TypeScript", "javascript": "JavaScript", "node": "Node.js", "react": "React",
    "vue": "Vue", "svelte": "Svelte", "css": "CSS", "html": "HTML", "sass": "Sass",
    "tailwind": "Tailwind", "jest": "Jest", "playwright": "Playwright", "cypress": "Cypress",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow", "sklearn": "scikit-learn",
    "pandas": "pandas", "numpy": "NumPy", "nlp": "NLP", "llm": "LLM", "llms": "LLMs",
    "mlops": "MLOps", "ci": "CI", "cd": "CD", "ci cd": "CI/CD", "git": "Git", "github": "GitHub",
    "gitlab": "GitLab", "jenkins": "Jenkins", "linux": "Linux", "bash": "Bash",
    "golang": "Go", "go": "Go", "java": "Java", "kotlin": "Kotlin", "scala": "Scala",
    "rust": "Rust", "ruby": "Ruby", "php": "PHP", "c++": "C++", "c#": "C#", "sqlalchemy": "SQLAlchemy",
    "prometheus": "Prometheus", "grafana": "Grafana", "grafana loki": "Grafana Loki",
    "grpc": "gRPC", "microservices": "microservices", "etl": "ETL", "elt": "ELT",
    "tableau": "Tableau", "powerbi": "Power BI", "power bi": "Power BI", "excel": "Excel",
    "accessibility": "accessibility", "agile": "Agile", "scrum": "Scrum", "kanban": "Kanban",
    "statistics": "statistics", "snowflake sql": "Snowflake SQL",
}


def pretty_term(term: str) -> str:
    """`fastapi` -> `FastAPI`, `python` -> `Python`, unknown words -> Title case."""
    text = str(term).strip()
    if not text:
        return ""
    known = PRETTY_TERMS.get(text.lower())
    if known:
        return known
    if " " not in text and any(ch.isdigit() for ch in text):
        return text.upper()
    return " ".join(w if w.isupper() else w.capitalize() for w in text.split())


def human_join(items: list[str], conjunction: str = "and") -> str:
    """`["a","b","c"]` -> `a, b and c` (no Oxford comma for 3+ items)."""
    values = [str(i).strip() for i in items if str(i).strip()]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} {conjunction} {values[1]}"
    return ", ".join(values[:-1]) + f" {conjunction} " + values[-1]


def prettify_terms(items: list[str]) -> list[str]:
    return [pretty_term(i) for i in items]


def source_label(value: str) -> str:
    return SOURCE_LABELS.get((value or "").lower(), (value or "").title())


def tokenize(text: str, min_length: int = 2) -> list[str]:
    return [w.lower() for w in WORDS.findall(text or "") if len(w) >= min_length]


STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "that", "this", "have",
    "has", "from", "not", "but", "all", "any", "can", "who", "how", "why", "was", "were", "been",
    "they", "their", "them", "his", "her", "its", "also", "into", "out", "off", "over", "under",
    "job", "role", "work", "working", "team", "teams", "years", "year", "plus", "must", "should",
    "would", "could", "about", "more", "most", "other", "than", "then", "there", "here", "when",
    "what", "which", "while", "well", "very", "per", "via", "using", "use", "used", "able", "new",
    "one", "two", "three", "day", "days", "week", "weeks", "month", "months", "looking", "join",
    "across", "within", "including", "include", "includes", "etc", "eg", "ie", "we", "us", "it",
    "as", "in", "on", "at", "to", "of", "or", "by", "an", "a", "is", "be", "do", "if", "so",
}


def specific_keywords(words: list[str], extra_block: set[str] | None = None,
                      limit: int = 12, min_length: int = 4) -> list[str]:
    """Drop boilerplate/modifier tokens so only *advertised* skills survive.

    Used by the CV skill line and the cover letter, e.g. "Senior Python Engineer"
    should yield "python", not "senior"/"engineer".
    """
    block = GENERIC_TERMS | (extra_block or set())
    out: list[str] = []
    for word in words:
        low = str(word).strip().lower()
        if (not low or low in block or len(low) < min_length or low.isdigit()
                or low in {w.lower() for w in out}):
            continue
        out.append(low)
        if len(out) >= limit:
            break
    return out


def keywords(text: str, limit: int = 40) -> list[str]:
    """Rank tokens by frequency, dropping stopwords - used for CV tailoring."""
    counts: dict[str, int] = {}
    for token in tokenize(text):
        if token in STOPWORDS or len(token) < 3:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _ in ranked[:limit]]


# --------------------------------------------------------------------------- #
# statuses
# --------------------------------------------------------------------------- #
class ApplicationStatus(str, Enum):
    DISCOVERED = "discovered"        # imported from a search, untouched
    PROPOSED = "proposed"            # below the qualification bar, kept for review
    SHORTLISTED = "shortlisted"      # user (or autopilot) marked it as interesting
    MATERIALS_READY = "materials_ready"  # CV + cover letter + email drafted
    SENT = "sent"                    # application dispatched
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    ARCHIVED = "archived"

    @property
    def label(self) -> str:
        return {
            "discovered": "Discovered",
            "proposed": "Proposed",
            "shortlisted": "Shortlisted",
            "materials_ready": "Materials ready",
            "sent": "Sent",
            "interview": "Interview",
            "offer": "Offer",
            "rejected": "Rejected",
            "archived": "Archived",
        }[self.value]

    @property
    def color(self) -> str:
        return {
            "discovered": "#8b93a7",
            "proposed": "#7f9a8b",
            "shortlisted": "#4f8cff",
            "materials_ready": "#a06bff",
            "sent": "#2fb3b3",
            "interview": "#f2a63b",
            "offer": "#3ecf8e",
            "rejected": "#e0576b",
            "archived": "#6b7280",
        }[self.value]

    @property
    def is_closed(self) -> bool:
        return self in (ApplicationStatus.REJECTED, ApplicationStatus.ARCHIVED)

    @property
    def is_active(self) -> bool:
        return not self.is_closed

    @classmethod
    def ordered(cls) -> list[ApplicationStatus]:
        return [cls.DISCOVERED, cls.PROPOSED, cls.SHORTLISTED, cls.MATERIALS_READY, cls.SENT,
                cls.INTERVIEW, cls.OFFER, cls.REJECTED, cls.ARCHIVED]


def coerce_status(value: object) -> ApplicationStatus:
    if isinstance(value, ApplicationStatus):
        return value
    try:
        return ApplicationStatus(str(value).strip().lower())
    except ValueError:
        return ApplicationStatus.DISCOVERED


# --------------------------------------------------------------------------- #
# job posting
# --------------------------------------------------------------------------- #
@dataclass
class JobPosting:
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    remote: bool = False
    salary_min: int = 0
    salary_max: int = 0
    currency: str = ""
    url: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    posted_at: str = ""
    fetched_at: str = field(default_factory=now_iso)

    # -- derived ---------------------------------------------------------- #
    @property
    def fingerprint(self) -> str:
        """Stable identity of a posting: its URL when we have one, else company+title.

        Boards reuse one URL for a posting while tweaking the title, so URL-first
        keeps a tracker entry (and its documents) attached to the same job.
        """
        url = self.url.strip().lower().split("?")[0].rstrip("/")
        identifiers = sorted((key.lower(), value) for key, value in parse_qsl(urlsplit(self.url).query)
                             if key.lower() in {"id", "jobid", "job_id", "jk", "gh_jid",
                                                "requisitionid", "requisition_id", "job"})
        if identifiers:
            url += "?" + urlencode(identifiers)
        if url:
            raw = url
        else:
            raw = "|".join([self.company.strip().lower(),
                            re.sub(r"\W+", " ", self.title.lower()).strip(),
                            self.location.strip().lower()])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @property
    def salary_text(self) -> str:
        if not (self.salary_min or self.salary_max):
            return "Not disclosed"
        symbol = {"USD": "$", "EUR": "€", "GBP": "£", "PLN": "zł"}.get(self.currency, "")
        low = f"{self.salary_min:,}" if self.salary_min else ""
        high = f"{self.salary_max:,}" if self.salary_max else ""
        span = f"{low} - {high}" if low and high else (low or high)
        return f"{symbol}{span} {self.currency}".strip()

    @staticmethod
    def _short_amount(value: int) -> str:
        if not value:
            return ""
        thousands = value / 1000
        text = f"{thousands:.0f}k" if abs(thousands - round(thousands)) < 0.05 else f"{thousands:.1f}k"
        return text if value >= 1000 else str(value)

    @property
    def salary_short(self) -> str:
        """Compact band for dense tables: "$110k–140k" instead of "$110,000 - 140,000 USD"."""
        if not (self.salary_min or self.salary_max):
            return "—"
        low = self._short_amount(self.salary_min)
        high = self._short_amount(self.salary_max)
        span = f"{low}–{high}" if low and high and low != high else (low or high)
        symbol = {"USD": "$", "EUR": "€", "GBP": "£", "PLN": "zł"}.get(self.currency, "")
        suffix = "" if symbol else (f" {self.currency}" if self.currency else "")
        return f"{symbol}{span}{suffix}"

    @property
    def short_location(self) -> str:
        """Location without the redundant "· Remote" suffix used in tables."""
        if self.location:
            return re.sub(r"\s*[·|]\s*remote\s*$", "", self.location, flags=re.IGNORECASE).strip()
        return "Remote" if self.remote else "—"

    @property
    def age_days(self) -> int | None:
        posted = parse_date(self.posted_at)
        return (date.today() - posted).days if posted else None

    @property
    def posted_text(self) -> str:
        posted = parse_date(self.posted_at)
        if not posted:
            return "unknown"
        days = (date.today() - posted).days
        if days <= 0:
            return "today"
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days} days ago"
        return posted.isoformat()

    def searchable_text(self) -> str:
        return " ".join([self.title, self.company, self.location,
                         " ".join(self.tags), self.description])

    @property
    def display_location(self) -> str:
        if self.remote and self.location:
            return f"{self.location} · Remote"
        return "Remote" if self.remote else (self.location or "—")

    # -- serialisation ---------------------------------------------------- #
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> JobPosting:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in (data or {}).items() if k in known}
        payload["tags"] = list(payload.get("tags") or [])
        payload["remote"] = bool(payload.get("remote"))
        for key in ("salary_min", "salary_max"):
            try:
                payload[key] = int(payload.get(key) or 0)
            except (TypeError, ValueError):
                payload[key] = 0
        return cls(**payload)


# --------------------------------------------------------------------------- #
# profile
# --------------------------------------------------------------------------- #
@dataclass
class ExperienceEntry:
    title: str = ""
    company: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    summary: str = ""
    highlights: list[str] = field(default_factory=list)

    @property
    def period(self) -> str:
        start, end = self.start or "?", self.end or "present"
        return f"{start} – {end}"

    def as_bullets(self) -> list[str]:
        bullets = [b.strip() for b in self.highlights if b and b.strip()]
        if not bullets and self.summary.strip():
            bullets = [s.strip() for s in re.split(r"(?<=[.!?])\s+", self.summary.strip()) if s.strip()]
        return bullets


@dataclass
class EducationEntry:
    degree: str = ""
    school: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    details: str = ""

    @property
    def period(self) -> str:
        return " – ".join(p for p in (self.start, self.end) if p)


@dataclass
class Profile:
    full_name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: str = ""                       # "LinkedIn: ... | GitHub: ..."
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    languages: str = ""
    experience: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    desired_titles: list[str] = field(default_factory=list)
    desired_locations: list[str] = field(default_factory=list)
    remote_only: bool = False
    willing_to_relocate: bool = False
    salary_floor: int = 0
    currency: str = "USD"
    seniority: str = ""
    # job-search specific
    tone: str = "professional"            # professional | friendly | enthusiastic | concise
    greeting: str = "Dear Hiring Team,"
    signature: str = ""
    extra: dict = field(default_factory=dict)

    # -- derived ---------------------------------------------------------- #
    @property
    def display_name(self) -> str:
        return self.full_name.strip() or "Unnamed candidate"

    @property
    def skill_set(self) -> set[str]:
        return {s.strip().lower() for s in self.skills if s.strip()}

    def signature_block(self) -> str:
        if self.signature.strip():
            return self.signature.strip()
        parts = [self.full_name, self.headline, self.email, self.phone, self.links]
        return "\n".join(p for p in parts if p)

    def completeness(self) -> int:
        """0-100 gauge shown on the profile tab / dashboard."""
        checks = [
            bool(self.full_name), bool(self.headline), bool(self.email), bool(self.phone),
            bool(self.location), bool(self.summary), len(self.skills) >= 5,
            bool(self.experience), bool(self.education), bool(self.desired_titles),
            bool(self.links), self.salary_floor > 0, bool(self.languages),
        ]
        return round(100 * sum(checks) / len(checks))

    def to_dict(self) -> dict:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict | None) -> Profile:
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        payload["skills"] = [str(s) for s in payload.get("skills") or []]
        payload["desired_titles"] = [str(s) for s in payload.get("desired_titles") or []]
        payload["desired_locations"] = [str(s) for s in payload.get("desired_locations") or []]
        payload["experience"] = [
            e if isinstance(e, ExperienceEntry) else ExperienceEntry(**{
                k: v for k, v in (e or {}).items()
                if k in ExperienceEntry.__dataclass_fields__})  # type: ignore[attr-defined]
            for e in payload.get("experience") or []]
        payload["education"] = [
            e if isinstance(e, EducationEntry) else EducationEntry(**{
                k: v for k, v in (e or {}).items()
                if k in EducationEntry.__dataclass_fields__})  # type: ignore[attr-defined]
            for e in payload.get("education") or []]
        try:
            payload["salary_floor"] = int(payload.get("salary_floor") or 0)
        except (TypeError, ValueError):
            payload["salary_floor"] = 0
        return cls(**payload)


"""A realistic example profile used by *Load example profile* and the head-less
``--selftest`` run.  Kept GUI-free so it can be imported from scripts."""
SAMPLE_PROFILE: dict = {
    "full_name": "Alex Doe",
    "headline": "Senior Python Engineer · data platforms & APIs",
    "email": "alex.doe@example.com",
    "phone": "+49 30 1234 5678",
    "location": "Berlin, Germany",
    "links": "LinkedIn: linkedin.com/in/alexdoe | GitHub: github.com/alexdoe",
    "summary": ("Backend engineer with eight years building data-heavy products. I turn vague "
                "requirements into small services, measurable SLOs and pipelines the team can "
                "actually maintain. Happiest when shipping, measuring and iterating."),
    "skills": ["python", "fastapi", "postgresql", "sql", "docker", "aws", "airflow", "pytest",
               "git", "rest apis", "dbt", "kubernetes"],
    "languages": "English (C1), German (B2), Polish (native)",
    "desired_titles": ["Python Engineer", "Backend Engineer", "Data Engineer"],
    "desired_locations": ["Berlin", "Remote"],
    "remote_only": False,
    "salary_floor": 80000,
    "currency": "USD",
    "seniority": "senior",
    "tone": "professional",
    "greeting": "Dear Hiring Team,",
    "signature": "Alex Doe\nSenior Python Engineer\nalex.doe@example.com · +49 30 1234 5678",
    "experience": [
        {"title": "Senior Backend Engineer", "company": "Datawheel GmbH", "location": "Berlin",
         "start": "2021-04", "end": "", "summary": "",
         "highlights": [
             "Owned the ingestion platform (Python, FastAPI, PostgreSQL) serving 40M events/day.",
             "Cut p95 API latency 62% by adding query caching and connection pooling.",
             "Introduced pytest + contract tests, taking release regressions from 6/quarter to 1.",
             "Mentored three engineers; ran the internal Python guild."]},
        {"title": "Backend Engineer", "company": "Fintrail", "location": "Warsaw", "start": "2018-07",
         "end": "2021-03", "summary": "",
         "highlights": [
             "Built the payments reconciliation service (Django, Celery, Redis).",
             "Automated reporting with Airflow + dbt, saving ~15 analyst hours a week.",
             "Migrated a monolith job queue to SQS, improving throughput 3x."]},
    ],
    "education": [
        {"degree": "MSc Computer Science", "school": "Warsaw University of Technology",
         "location": "Warsaw", "start": "2016", "end": "2018",
         "details": "Thesis: streaming anomaly detection in event pipelines."},
        {"degree": "BSc Software Engineering", "school": "AGH University", "location": "Kraków",
         "start": "2013", "end": "2016", "details": ""},
    ],
}


# --------------------------------------------------------------------------- #
# application
# --------------------------------------------------------------------------- #
@dataclass
class Application:
    application_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    job_id: str = ""
    status: str = ApplicationStatus.DISCOVERED.value
    match_score: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    sent_at: str = ""
    follow_up_at: str = ""
    follow_up_count: int = 0             # nudges already drafted for this application
    interview_at: str = ""               # "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
    notes: str = ""
    cv_path: str = ""
    cover_letter_path: str = ""
    email_path: str = ""
    history: list[dict] = field(default_factory=list)
    # interview preparation: notes + question bank (see services/interview_prep.py)
    prep: dict = field(default_factory=dict)
    prep_path: str = ""                  # exported prep sheet, if any

    # -- status helpers ---------------------------------------------------- #
    @property
    def status_enum(self) -> ApplicationStatus:
        return coerce_status(self.status)

    def set_status(self, status: ApplicationStatus | str, note: str = "") -> None:
        new = coerce_status(status)
        if new.value != self.status:
            self.history.append({"at": now_iso(), "event": "status",
                                 "from": self.status, "to": new.value, "note": note})
            self.status = new.value
            if new is ApplicationStatus.SENT and not self.sent_at:
                self.sent_at = now_iso()
        elif note:
            self.history.append({"at": now_iso(), "event": "note", "note": note})
        self.updated_at = now_iso()

    def log(self, event: str, note: str = "") -> None:
        self.history.append({"at": now_iso(), "event": event, "note": note})
        self.updated_at = now_iso()

    @property
    def follow_up_due(self) -> bool:
        when = parse_date(self.follow_up_at)
        return bool(when and when <= date.today() and self.status_enum.is_active)

    @property
    def is_unacted(self) -> bool:
        """Discovered/shortlisted — never prepared, sent or otherwise moved on."""
        return self.status_enum in (ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED)

    @property
    def days_since_sent(self) -> int | None:
        when = parse_date(self.sent_at)
        return (date.today() - when).days if when else None

    def schedule_follow_up(self, days: int = DEFAULT_FOLLOW_UP_DAYS) -> None:
        self.follow_up_at = (date.today() + timedelta(days=days)).isoformat()
        self.log("follow-up scheduled", f"in {days} day(s)")

    def rung_label(self, max_nudges: int = 0) -> str:
        """Human label for the next follow-up rung ("First"/"Second"/"Final"…)."""
        rug = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]
        if max_nudges and self.follow_up_count >= max_nudges - 1:
            return "Final"
        return rug[self.follow_up_count] if self.follow_up_count < len(rug) else f"#{self.follow_up_count + 1}"

    @property
    def interview_scheduled(self) -> bool:
        return bool(parse_date(self.interview_at))

    def interview_fallback_date(self) -> date | None:
        """Best-known interview day when no explicit date/time was entered.

        Used by the calendar export: the day the status moved to *interview*
        (from the history log) or, failing that, the last update day.
        """
        for event in self.history:
            if event.get("event") == "status" and event.get("to") == ApplicationStatus.INTERVIEW.value:
                return parse_date(event.get("at")) or parse_date(self.updated_at)
        return parse_date(self.updated_at)

    @property
    def documents(self) -> list[tuple[str, str]]:
        return [("CV", self.cv_path), ("Cover letter", self.cover_letter_path),
                ("Email", self.email_path)]

    @property
    def prep_question_count(self) -> int:
        return len(self.prep.get("questions") or []) if isinstance(self.prep, dict) else 0

    @property
    def prep_answered_count(self) -> int:
        if not isinstance(self.prep, dict):
            return 0
        return sum(1 for q in (self.prep.get("questions") or [])
                   if isinstance(q, dict) and str(q.get("answer") or "").strip())

    @property
    def has_prep(self) -> bool:
        return bool(self.prep_question_count
                    or (isinstance(self.prep, dict) and str(self.prep.get("notes") or "").strip()))

    @property
    def has_documents(self) -> bool:
        return any(path and Path(path).exists() for _, path in self.documents)

    # -- serialisation ----------------------------------------------------- #
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Application:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in (data or {}).items() if k in known}
        payload["history"] = list(payload.get("history") or [])
        payload["prep"] = dict(payload.get("prep") or {}) if isinstance(payload.get("prep"), dict) else {}
        payload["status"] = coerce_status(payload.get("status")).value
        try:
            payload["match_score"] = int(payload.get("match_score") or 0)
        except (TypeError, ValueError):
            payload["match_score"] = 0
        try:
            payload["follow_up_count"] = int(payload.get("follow_up_count") or 0)
        except (TypeError, ValueError):
            payload["follow_up_count"] = 0
        return cls(**payload)


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
REGIONAL_SOURCE_NAMES = ["myjobmag_ke", "myjobmag_ng", "myjobmag_za",
                         "jobweb_ke", "jobweb_ug", "jobweb_tz", "jooble_uae"]
DEFAULT_SOURCE_NAMES = ["remotive", "arbeitnow", "remoteok", "himalayas", *REGIONAL_SOURCE_NAMES]


@dataclass
class AppSettings:
    data_dir: str = ""
    enabled_sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCE_NAMES))
    source_catalog_version: int = 2
    qualification_policy_version: int = 2
    jooble_uae_key: str = ""
    last_search_location: str | None = None
    results_per_source: int = 25
    request_timeout: int = 15
    autopilot: bool = False               # auto-prepare materials for top matches
    autopilot_min_score: int = 80
    autopilot_max_per_run: int = 5
    follow_up_days: int = DEFAULT_FOLLOW_UP_DAYS
    follow_up_repeat_days: int = 5       # interval between later nudges in the ladder
    follow_up_max_nudges: int = 3        # total follow-ups before the series stops
    auto_clear_days: int = 5             # archive untouched (never prepared/sent) apps older than this (0 = off)
    include_cover_letter: bool = True
    include_email_draft: bool = True
    cv_template: str = "modern"           # modern | classic | compact
    export_format: str = "docx"           # docx | pdf | docx_pdf | md | txt
    min_salary: int = 0
    min_match_score: int = 80               # qualification bar; results stay visible for review
    auto_track_qualified: bool = True       # search results at/above min_match_score go to the queue
    min_pay_usd: int = 10                   # Tasks search: only gigs advertising >= this per task (0 = off)
    remote_only: bool = False
    exclude_keywords: str = ""            # comma separated, filters out postings
    theme: str = "blackgreen"
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "gb"
    last_search_query: str = ""
    last_search_job_ids: list[str] | None = None  # None means no saved search yet
    auto_refresh_enabled: bool = False    # timed re-scrape of the enabled boards
    auto_refresh_minutes: int = 30        # every N minutes when enabled
    notify_new_matches: bool = True       # tray/desktop alert when a refresh finds fresh roles
    linkedin_easy_apply: bool = True      # LinkedIn hand-off pre-filters Easy Apply (f_AL=true)
    llm_provider: str = "none"            # none | ollama (local LLM, fully opt-in)
    llm_model: str = "llama3.2"           # Ollama model used for draft letters
    llm_base_url: str = "http://localhost:11434"
    llm_timeout: int = 90                 # generous: local generation is slow
    # Base64-encoded QMainWindow geometry, written by the window on close.
    # Lives here (not in QSettings) so the data dir really is the whole story:
    # deleting it *is* a full reset, with no stray HKCU registry key behind.
    window_geometry: str = ""

    # -- helpers ----------------------------------------------------------- #
    @property
    def excluded_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.exclude_keywords.split(",") if k.strip()]

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).expanduser() if self.data_dir else default_data_dir()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> AppSettings:
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        if "last_search_job_ids" in payload:
            ids = payload["last_search_job_ids"]
            payload["last_search_job_ids"] = ([str(job_id) for job_id in ids]
                                               if isinstance(ids, list) else None)
        selected = payload.get("enabled_sources", DEFAULT_SOURCE_NAMES)
        payload["enabled_sources"] = [str(s) for s in selected] if isinstance(selected, list) else list(DEFAULT_SOURCE_NAMES)
        if data.get("source_catalog_version") != 2:
            # Expand the old three-board default once; preserve custom/offline selections.
            if set(payload["enabled_sources"]) == {"remotive", "arbeitnow", "remoteok"}:
                payload["enabled_sources"] = list(DEFAULT_SOURCE_NAMES)
        payload["source_catalog_version"] = 2
        # v2 raises JAUTOMATIC's default qualification standard from 70% to 80%.
        # Only migrate legacy default values; preserve deliberate custom thresholds.
        if int(data.get("qualification_policy_version") or 0) < 2:
            if int(payload.get("min_match_score") or 70) == 70:
                payload["min_match_score"] = 80
            if int(payload.get("autopilot_min_score") or 70) == 70:
                payload["autopilot_min_score"] = 80
        payload["qualification_policy_version"] = 2
        for key in ("results_per_source", "request_timeout", "autopilot_min_score",
                    "autopilot_max_per_run", "follow_up_days", "follow_up_repeat_days",
                    "follow_up_max_nudges", "auto_clear_days",
                    "min_salary", "min_match_score", "min_pay_usd",
                    "auto_refresh_minutes", "llm_timeout"):
            if key not in data:
                continue  # absent keys keep the dataclass default (settings migrate cleanly)
            try:
                payload[key] = int(payload.get(key) or 0)
            except (TypeError, ValueError):
                payload[key] = getattr(cls(), key)
        for key in ("autopilot", "include_cover_letter", "include_email_draft", "remote_only",
                    "auto_refresh_enabled", "notify_new_matches", "linkedin_easy_apply",
                    "auto_track_qualified"):
            payload[key] = bool(payload.get(key))
        return cls(**payload)


# --------------------------------------------------------------------------- #
# workspace (JSON files + SQLite)
# --------------------------------------------------------------------------- #
def synchronized(method):
    """Serialise access to the shared SQLite connection.

    The UI runs scraping/import/generation on a thread pool, so the same
    connection is touched from several threads.  ``check_same_thread=False``
    plus this lock is the simplest correct pattern for our access pattern
    (SQLite is in WAL mode, so readers never block writers).
    """

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class Workspace:
    """Owns the data directory: paths, profile/settings JSON, SQLite tables."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.root = Path(data_dir).expanduser() if data_dir else default_data_dir()
        self.documents_dir = self.root / "documents"
        self.exports_dir = self.root / "exports"
        self.templates_dir = self.root / "templates"      # user-supplied CV templates
        self.db_path = self.root / "jautomatic.sqlite3"
        self.profile_path = self.root / "profile.json"
        self.settings_path = self.root / "settings.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.recovery_notices: list[str] = []
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # -- schema ------------------------------------------------------------ #
    @synchronized
    def _migrate(self) -> None:
        cur = self._conn
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id      TEXT PRIMARY KEY,
                fingerprint TEXT UNIQUE,
                source      TEXT,
                title       TEXT,
                company     TEXT,
                location    TEXT,
                remote      INTEGER DEFAULT 0,
                salary_min  INTEGER DEFAULT 0,
                salary_max  INTEGER DEFAULT 0,
                currency    TEXT DEFAULT '',
                url         TEXT DEFAULT '',
                description TEXT DEFAULT '',
                tags        TEXT DEFAULT '[]',
                posted_at   TEXT DEFAULT '',
                fetched_at  TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS applications (
                application_id    TEXT PRIMARY KEY,
                job_id            TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                status            TEXT DEFAULT 'discovered',
                match_score       INTEGER DEFAULT 0,
                created_at        TEXT,
                updated_at        TEXT,
                sent_at           TEXT DEFAULT '',
                follow_up_at      TEXT DEFAULT '',
                interview_at      TEXT DEFAULT '',
                notes             TEXT DEFAULT '',
                cv_path           TEXT DEFAULT '',
                cover_letter_path TEXT DEFAULT '',
                email_path        TEXT DEFAULT '',
                history           TEXT DEFAULT '[]',
                prep              TEXT DEFAULT '{}',
                prep_path         TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);
            CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        # v1 -> v2: the interview date/time column did not exist yet.
        columns = {row["name"] for row in cur.execute("PRAGMA table_info(applications)")}
        if "interview_at" not in columns:
            cur.execute("ALTER TABLE applications ADD COLUMN interview_at TEXT DEFAULT ''")
        # v2 -> v3: interview-prep notes/question bank + exported sheet path.
        if "prep" not in columns:
            cur.execute("ALTER TABLE applications ADD COLUMN prep TEXT DEFAULT '{}'")
        if "prep_path" not in columns:
            cur.execute("ALTER TABLE applications ADD COLUMN prep_path TEXT DEFAULT ''")
        # v3 -> v4: the escalating follow-up ladder tracks how many nudges went out.
        if "follow_up_count" not in columns:
            cur.execute("ALTER TABLE applications ADD COLUMN follow_up_count INTEGER DEFAULT 0")
        row = cur.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            cur.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),))
        elif row["value"] != str(SCHEMA_VERSION):
            cur.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
        cur.commit()

    # -- jobs -------------------------------------------------------------- #
    @synchronized
    def save_jobs(self, jobs: list[JobPosting]) -> int:
        """Insert new postings, refresh the ones we already know. Returns #new."""
        new = 0
        cursor = self._conn
        for job in jobs:
            existing = cursor.execute("SELECT job_id FROM jobs WHERE fingerprint=?",
                                      (job.fingerprint,)).fetchone()
            if not existing and "?" in job.url:
                old_url = job.url.strip().lower().split("?")[0].rstrip("/")
                old_hash = hashlib.sha1(old_url.encode("utf-8")).hexdigest()
                legacy = cursor.execute("SELECT * FROM jobs WHERE fingerprint=?", (old_hash,)).fetchone()
                if legacy and self._row_to_job(legacy).fingerprint == job.fingerprint:
                    cursor.execute("UPDATE jobs SET fingerprint=? WHERE job_id=?",
                                   (job.fingerprint, legacy["job_id"]))
                    existing = legacy
            if existing:
                cursor.execute(
                    """UPDATE jobs SET title=?, company=?, location=?, remote=?, salary_min=?,
                       salary_max=?, currency=?, url=?, description=?, tags=?, posted_at=?,
                       fetched_at=? WHERE job_id=?""",
                    (job.title, job.company, job.location, int(job.remote), job.salary_min,
                     job.salary_max, job.currency, job.url, job.description,
                     json.dumps(job.tags), job.posted_at, job.fetched_at, existing["job_id"]))
                job.job_id = existing["job_id"]
                continue
            cursor.execute(
                """INSERT INTO jobs (job_id, fingerprint, source, title, company, location, remote,
                   salary_min, salary_max, currency, url, description, tags, posted_at, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job.job_id, job.fingerprint, job.source, job.title, job.company, job.location,
                 int(job.remote), job.salary_min, job.salary_max, job.currency, job.url,
                 job.description, json.dumps(job.tags), job.posted_at, job.fetched_at))
            new += 1
        self._conn.commit()
        return new

    @synchronized
    def _row_to_job(self, row: sqlite3.Row) -> JobPosting:
        return JobPosting(
            job_id=row["job_id"], source=row["source"] or "", title=row["title"] or "",
            company=row["company"] or "", location=row["location"] or "",
            remote=bool(row["remote"]), salary_min=row["salary_min"] or 0,
            salary_max=row["salary_max"] or 0, currency=row["currency"] or "",
            url=row["url"] or "", description=row["description"] or "",
            tags=json.loads(row["tags"] or "[]"), posted_at=row["posted_at"] or "",
            fetched_at=row["fetched_at"] or "")

    @synchronized
    def jobs(self, limit: int = 500) -> list[JobPosting]:
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY fetched_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_job(r) for r in rows]

    @synchronized
    def get_job(self, job_id: str) -> JobPosting | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    @synchronized
    def job_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"])

    # -- applications ------------------------------------------------------ #
    @synchronized
    def save_application(self, application: Application) -> Application:
        application.updated_at = now_iso()
        self._conn.execute(
            """INSERT INTO applications (application_id, job_id, status, match_score, created_at,
               updated_at, sent_at, follow_up_at, follow_up_count, interview_at, notes, cv_path,
               cover_letter_path, email_path, history, prep, prep_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(application_id) DO UPDATE SET
                 status=excluded.status, match_score=excluded.match_score,
                 updated_at=excluded.updated_at, sent_at=excluded.sent_at,
                 follow_up_at=excluded.follow_up_at, follow_up_count=excluded.follow_up_count,
                 interview_at=excluded.interview_at,
                 notes=excluded.notes,
                 cv_path=excluded.cv_path, cover_letter_path=excluded.cover_letter_path,
                 email_path=excluded.email_path, history=excluded.history,
                 prep=excluded.prep, prep_path=excluded.prep_path""",
            (application.application_id, application.job_id, application.status,
             application.match_score, application.created_at, application.updated_at,
             application.sent_at, application.follow_up_at, application.follow_up_count,
             application.interview_at,
             application.notes, application.cv_path, application.cover_letter_path,
             application.email_path, json.dumps(application.history),
             json.dumps(application.prep or {}), application.prep_path))
        self._conn.commit()
        return application

    @synchronized
    def _row_to_application(self, row: sqlite3.Row) -> Application:
        return Application(
            application_id=row["application_id"], job_id=row["job_id"], status=row["status"],
            match_score=row["match_score"] or 0, created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "", sent_at=row["sent_at"] or "",
            follow_up_at=row["follow_up_at"] or "", interview_at=row["interview_at"] or "",
            notes=row["notes"] or "",
            cv_path=row["cv_path"] or "", cover_letter_path=row["cover_letter_path"] or "",
            email_path=row["email_path"] or "", history=json.loads(row["history"] or "[]"),
            prep=_json_dict(row["prep"] if "prep" in row.keys() else None),
            prep_path=(row["prep_path"] if "prep_path" in row.keys() else "") or "",
            follow_up_count=int(row["follow_up_count"] or 0) if "follow_up_count" in row.keys() else 0)

    @synchronized
    def applications(self) -> list[Application]:
        rows = self._conn.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC, rowid DESC").fetchall()
        return [self._row_to_application(r) for r in rows]

    @synchronized
    def get_application(self, application_id: str) -> Application | None:
        row = self._conn.execute("SELECT * FROM applications WHERE application_id=?",
                                 (application_id,)).fetchone()
        return self._row_to_application(row) if row else None

    @synchronized
    def application_for_job(self, job_id: str) -> Application | None:
        row = self._conn.execute(
            "SELECT * FROM applications WHERE job_id=? ORDER BY rowid DESC LIMIT 1",
            (job_id,)).fetchone()
        return self._row_to_application(row) if row else None

    @synchronized
    def delete_application(self, application_id: str) -> None:
        self._conn.execute("DELETE FROM applications WHERE application_id=?", (application_id,))
        self._conn.commit()

    @synchronized
    def delete_job(self, job_id: str) -> None:
        self._conn.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
        self._conn.commit()

    @synchronized
    def clear_jobs(self) -> None:
        self._conn.execute("DELETE FROM applications")
        self._conn.execute("DELETE FROM jobs")
        self._conn.commit()

    # -- stats ------------------------------------------------------------- #
    @synchronized
    def stats(self) -> dict:
        apps = self.applications()
        by_status: dict[str, int] = {s.value: 0 for s in ApplicationStatus}
        for app in apps:
            by_status[app.status_enum.value] += 1
        sent = sum(1 for a in apps if parse_date(a.sent_at))
        interviews = by_status[ApplicationStatus.INTERVIEW.value]
        offers = by_status[ApplicationStatus.OFFER.value]
        rejected = by_status[ApplicationStatus.REJECTED.value]
        responded = interviews + offers + rejected
        return {
            "jobs": self.job_count(),
            "applications": len(apps),
            "by_status": by_status,
            "sent": sent,
            "responses": responded,
            "interviews": interviews,
            "offers": offers,
            "follow_ups_due": sum(1 for a in apps if a.follow_up_due),
            "materials_ready": by_status[ApplicationStatus.MATERIALS_READY.value],
            "response_rate": round(100 * responded / sent, 1) if sent else 0.0,
            "interview_rate": round(100 * interviews / sent, 1) if sent else 0.0,
        }

    # -- profile & settings ------------------------------------------------ #
    @synchronized
    def load_profile(self) -> Profile:
        from .services.data_safety import load_json
        return load_json(self.profile_path, Profile.from_dict, self.recovery_notices)

    @synchronized
    def save_profile(self, profile: Profile) -> None:
        from .services.data_safety import atomic_json
        atomic_json(self.profile_path, profile.to_dict())

    @synchronized
    def load_settings(self) -> AppSettings:
        from .services.data_safety import load_json
        settings = load_json(self.settings_path,
                             lambda data: AppSettings.from_dict(data) if data else AppSettings(),
                             self.recovery_notices)
        if not settings.data_dir:
            settings.data_dir = str(self.root)
        return settings

    @synchronized
    def save_settings(self, settings: AppSettings) -> None:
        from .services.data_safety import atomic_json
        settings.data_dir = settings.data_dir or str(self.root)
        atomic_json(self.settings_path, settings.to_dict())

    @synchronized
    def backup_to(self, parent: Path) -> Path:
        from .services.data_safety import backup_workspace
        return backup_workspace(self, parent)

    @synchronized
    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


if __name__ == "__main__":  # pragma: no cover - tiny CLI convenience
    workspace = Workspace()
    print(f"data dir: {workspace.root}")
    print(f"jobs: {workspace.job_count()}  applications: {len(workspace.applications())}")
