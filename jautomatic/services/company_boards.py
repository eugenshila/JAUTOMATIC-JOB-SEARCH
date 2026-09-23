"""Company career boards: live openings straight from an employer's own ATS.

Greenhouse, Lever and Ashby each publish an unauthenticated JSON endpoint that
their own hosted career pages read.  JAUTOMATIC calls those endpoints instead of
scraping HTML, so there is no login, no API key and no browser involved, and the
data is the employer's source of truth rather than a re-scrape of an aggregator.

Which companies to watch is yours: the list lives in Settings and accepts either
a careers-page URL (``https://jobs.lever.co/kitopi``) or a ``provider:slug``
pair (``greenhouse:careem``).  A board that moves or is renamed is skipped and
reported; it never breaks the rest of the search.
"""
from __future__ import annotations

import re
from concurrent import futures
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from ..models import JobPosting
from .job_regions import location_matches
from .job_scraper import (USER_AGENT, JobSource, SearchQuery, _clean, _tagify, looks_remote,
                          parse_salary, query_matches)

#: Boards are fetched in parallel, but a search must stay inside its timeout.
MAX_BOARDS_PER_SEARCH = 12
MAX_WORKERS = 4

#: Verified public boards, seeded the first time Settings is written: two Gulf
#: employers (Dubai and Riyadh) and three logistics/supply-chain employers whose
#: roles are open to candidates worldwide.
DEFAULT_COMPANY_BOARDS = [
    "greenhouse:careem",
    "greenhouse:tamara",
    "greenhouse:flexport",
    "greenhouse:project44",
    "greenhouse:fourkites",
]

PROVIDERS = ("greenhouse", "lever", "ashby")
PROVIDER_LABELS = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}

_CAREERS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "boards.eu.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.eu.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "api.ashbyhq.com": "ashby",
}

#: ATSs whose public endpoints are not implemented here - say so instead of 404ing.
_UNSUPPORTED_HOSTS = {
    "apply.workable.com": "Workable",
    "jobs.smartrecruiters.com": "SmartRecruiters",
    "careers.smartrecruiters.com": "SmartRecruiters",
    "myworkdayjobs.com": "Workday",
}

_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class BoardError(ValueError):
    """A board reference JAUTOMATIC cannot use - always carries a user-facing reason."""


def parse_board_spec(spec: str) -> tuple[str, str]:
    """``"jobs.lever.co/kitopi"`` / ``"greenhouse:careem"`` / ``"careem"`` -> (provider, slug).

    A bare slug is treated as a Greenhouse board, the most common case.  Raises
    ``BoardError`` with a sentence the user can act on.
    """
    text = (spec or "").strip().strip("/")
    if not text:
        raise BoardError("Enter a careers-page URL or provider:slug.")
    looks_like_url = "://" in text or text.startswith("www.") or "/" in text
    if ":" in text and not looks_like_url:
        provider, _, slug = text.partition(":")
        provider = provider.strip().lower()
        if provider not in PROVIDERS:
            raise BoardError(f"'{provider}' is not a supported board - use greenhouse, lever "
                             "or ashby (or paste the careers-page URL).")
    elif looks_like_url:
        provider, slug = _parse_careers_url(text)
    else:
        provider, slug = "greenhouse", text      # a bare slug is a Greenhouse board
    slug = slug.strip().strip("/").split("/")[0].strip()
    if not _SLUG_RE.fullmatch(slug or ""):
        raise BoardError(f"'{slug}' is not a usable board name.")
    return provider, slug.lower()


def _parse_careers_url(text: str) -> tuple[str, str]:
    url = text if "://" in text else f"https://{text}"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    base = host[4:] if host.startswith("www.") else host
    provider = _CAREERS_HOSTS.get(base) or next(
        (name for suffix, name in _CAREERS_HOSTS.items() if base.endswith("." + suffix)), "")
    if not provider:
        blocked = _UNSUPPORTED_HOSTS.get(base) or next(
            (name for suffix, name in _UNSUPPORTED_HOSTS.items() if suffix in base), "")
        if blocked:
            raise BoardError(f"{blocked} boards are not supported - use a Greenhouse, "
                             "Lever or Ashby careers page.")
        raise BoardError(f"'{host}' is not a Greenhouse, Lever or Ashby careers page.")
    parts = [part for part in parsed.path.split("/") if part]
    if "job-board" in parts:                     # the Ashby API URL works too
        parts = parts[parts.index("job-board") + 1:]
    if not parts:
        raise BoardError(f"That {PROVIDER_LABELS[provider]} URL has no company in it.")
    return provider, parts[0]


def canonical_board(spec: str) -> str:
    provider, slug = parse_board_spec(spec)
    return f"{provider}:{slug}"


def normalise_boards(values) -> list[str]:
    """Clean a user list into unique ``provider:slug`` entries, ignoring bad ones."""
    cleaned: list[str] = []
    for value in values or []:
        try:
            entry = canonical_board(str(value))
        except BoardError:
            continue
        if entry not in cleaned:
            cleaned.append(entry)
    return cleaned


def board_display(spec: str) -> str:
    """Human label for one board: ``greenhouse:careem`` -> ``Careem (Greenhouse)``."""
    try:
        provider, slug = parse_board_spec(spec)
    except BoardError:
        return str(spec or "")
    company = slug.replace("-", " ").replace("_", " ").title()
    return f"{company} ({PROVIDER_LABELS[provider]})"


# --------------------------------------------------------------------------- #
# per-provider readers
# --------------------------------------------------------------------------- #
def _get_json(url: str, timeout: int, params: dict | None = None) -> object:
    response = requests.get(url, params=params or {}, timeout=timeout,
                            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def _epoch_text(value: object) -> str:
    """Lever posts millisecond epochs; keep the ISO date the tracker understands."""
    try:
        seconds = float(value) / (1000 if float(value) > 1e11 else 1)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _department(item: dict) -> str:
    for key in ("department", "team"):
        if _clean(item.get(key)):
            return _clean(item.get(key))
    values = item.get("departments") or []
    if isinstance(values, list):
        for value in values:
            name = _clean(value.get("name") if isinstance(value, dict) else value)
            if name:
                return name
    return ""


def _greenhouse_board(slug: str, timeout: int) -> list[JobPosting]:
    company = slug.replace("-", " ").title()
    try:  # the board metadata carries the real company name; the jobs list does not
        meta = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}", timeout)
        company = _clean((meta or {}).get("name")) or company
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass
    payload = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout,
                        {"content": "true"})
    jobs: list[JobPosting] = []
    for item in (payload or {}).get("jobs", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = _clean(item.get("title"))
        location = _clean((item.get("location") or {}).get("name")
                          if isinstance(item.get("location"), dict) else item.get("location"))
        description = _clean(item.get("content") or "")
        department = _department(item)
        salary_min, salary_max, currency = parse_salary(description[:800])
        jobs.append(JobPosting(
            source="company_boards", title=title, company=company,
            location=location or "Location not stated",
            remote=looks_remote(location, title),
            salary_min=salary_min, salary_max=salary_max, currency=currency,
            url=item.get("absolute_url") or "", description=description,
            tags=_tagify(title, department), posted_at=str(item.get("updated_at") or "")))
    return jobs


def _lever_board(slug: str, timeout: int) -> list[JobPosting]:
    payload = _get_json(f"https://api.lever.co/v0/postings/{slug}", timeout, {"mode": "json"})
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise ValueError(payload.get("error") or "board not found")
    company = slug.replace("-", " ").title()
    jobs: list[JobPosting] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        title = _clean(item.get("text"))
        categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
        location = _clean(categories.get("location"))
        country = _clean(item.get("country"))
        workplace = str(item.get("workplaceType") or "").lower()
        remote = workplace == "remote" or looks_remote(location, title)
        description = _clean(item.get("descriptionPlain") or item.get("description") or "")
        band = item.get("salaryRange") if isinstance(item.get("salaryRange"), dict) else {}
        salary_min, salary_max = int(band.get("min") or 0), int(band.get("max") or 0)
        currency = _clean(band.get("currency")).upper()
        if not (salary_min or salary_max):
            salary_min, salary_max, currency = parse_salary(description[:800])
        if country and country.lower() not in location.lower():
            location = ", ".join(part for part in (location, country) if part)
        jobs.append(JobPosting(
            source="company_boards", title=title, company=company,
            location=location or "Location not stated", remote=remote,
            salary_min=salary_min, salary_max=salary_max, currency=currency,
            url=item.get("hostedUrl") or item.get("applyUrl") or "", description=description,
            tags=_tagify(title, _clean(categories.get("team")) or _clean(categories.get("department"))),
            posted_at=_epoch_text(item.get("createdAt"))))
    return jobs


def _ashby_compensation(item: dict) -> tuple[int, int, str]:
    compensation = item.get("compensation")
    if not isinstance(compensation, dict):
        return 0, 0, ""
    for part in compensation.get("summaryComponents") or []:
        if not isinstance(part, dict) or str(part.get("compensationType") or "").lower() != "salary":
            continue
        low, high = int(part.get("minValue") or 0), int(part.get("maxValue") or 0)
        currency = _clean(part.get("currencyCode")).upper()
        interval = str(part.get("interval") or "").upper()
        if low > high:
            low, high = high, low
        if "MONTH" in interval:
            return low * 12, high * 12, currency
        if interval and "YEAR" not in interval and "NONE" not in interval:
            return 0, 0, currency      # hourly or daily rates are not comparable
        if low or high:
            return low, high, currency
    return parse_salary(_clean(compensation.get("scrapeableCompensationSalarySummary")))


def _ashby_board(slug: str, timeout: int) -> list[JobPosting]:
    payload = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout,
                        {"includeCompensation": "true"})
    company = slug.replace("-", " ").title()
    jobs: list[JobPosting] = []
    for item in (payload or {}).get("jobs", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        if item.get("isListed") is False:      # direct-link-only roles are not listed
            continue
        title = _clean(item.get("title"))
        location = _clean(item.get("location"))
        address = (item.get("address") or {}).get("postalAddress") or {}
        country = _clean(address.get("addressCountry") if isinstance(address, dict) else "")
        if country and country.lower() not in location.lower():
            location = ", ".join(part for part in (location, country) if part)
        remote = bool(item.get("isRemote")) or \
            str(item.get("workplaceType") or "").lower() == "remote" or looks_remote(location, title)
        description = _clean(item.get("descriptionPlain") or item.get("descriptionHtml") or "")
        salary_min, salary_max, currency = _ashby_compensation(item)
        if not (salary_min or salary_max):
            salary_min, salary_max, currency = parse_salary(description[:800])
        jobs.append(JobPosting(
            source="company_boards", title=title, company=company,
            location=location or "Location not stated", remote=remote,
            salary_min=salary_min, salary_max=salary_max, currency=currency,
            url=item.get("jobUrl") or item.get("applyUrl") or "", description=description,
            tags=_tagify(title, _department(item)), posted_at=str(item.get("publishedAt") or "")))
    return jobs


_BOARD_READERS = {"greenhouse": _greenhouse_board, "lever": _lever_board, "ashby": _ashby_board}


# --------------------------------------------------------------------------- #
# the source itself
# --------------------------------------------------------------------------- #
class CompanyBoardsSource(JobSource):
    """One source that fans out over every company board the user listed."""

    name = "company_boards"
    label = "Company career boards"
    description = ("Live openings from the companies you list (Greenhouse, Lever, Ashby) "
                   "- no API key.")
    homepage = "https://boards.greenhouse.io"

    # -- configuration ---------------------------------------------------- #
    @staticmethod
    def boards(settings=None) -> list[tuple[str, str]]:
        """Parsed ``(provider, slug)`` pairs, capped so a long list stays fast."""
        values = list(getattr(settings, "company_boards", None) or []) if settings is not None else []
        if not values:
            values = list(DEFAULT_COMPANY_BOARDS)
        return [parse_board_spec(value) for value in normalise_boards(values)][:MAX_BOARDS_PER_SEARCH]

    # -- fetching --------------------------------------------------------- #
    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        return self._collect(self.boards(None), query, timeout)

    def fetch_with(self, query: SearchQuery, settings, timeout: int = 15) -> list[JobPosting]:
        return self._collect(self.boards(settings), query, timeout)

    def _collect(self, specs: list[tuple[str, str]], query: SearchQuery,
                 timeout: int) -> list[JobPosting]:
        if not specs:
            raise ValueError("Add a company career board in Settings (Greenhouse, Lever or Ashby)")
        limit = max(1, query.limit_per_source)
        per_board = max(5, min(limit, 25))
        strict: list[JobPosting] = []
        loose: list[JobPosting] = []
        failed: list[str] = []
        with futures.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(specs))) as pool:
            for hits, misses, error in pool.map(
                    lambda spec: self._read_board(spec, query, timeout, per_board), specs):
                strict.extend(hits)
                loose.extend(misses)
                if error:
                    failed.append(error)
        if failed and not (strict or loose):
            # Nothing at all came back: say which boards and why, in one line.
            raise requests.RequestException(
                f"no company board responded ({'; '.join(failed)})")
        # A board that has moved or died is skipped so the rest of the search
        # keeps working; its name shows up only when *nothing* responds.
        return (strict or loose)[:limit]

    def _read_board(self, spec: tuple[str, str], query: SearchQuery, timeout: int,
                    per_board: int) -> tuple[list[JobPosting], list[JobPosting], str]:
        provider, slug = spec
        try:
            postings = _BOARD_READERS[provider](slug, timeout)
        except requests.RequestException:
            return [], [], f"{slug} unreachable"
        except (ValueError, KeyError, TypeError):
            return [], [], f"{slug} returned no board"
        strict: list[JobPosting] = []
        loose: list[JobPosting] = []
        for job in postings:
            if query.remote_only and not job.remote:
                continue
            if not location_matches(query.location, job.location, job.remote):
                continue
            if not query.terms:
                strict.append(job)
                continue
            haystack = f"{job.title} {job.company} {job.description}".lower()
            if query_matches(haystack, query.terms):
                strict.append(job)
            elif query_matches(haystack, query.terms, require_all=False):
                loose.append(job)
        return strict[:per_board], loose[:per_board], ""


__all__ = [
    "BoardError",
    "CompanyBoardsSource",
    "DEFAULT_COMPANY_BOARDS",
    "MAX_BOARDS_PER_SEARCH",
    "PROVIDERS",
    "board_display",
    "canonical_board",
    "normalise_boards",
    "parse_board_spec",
]
