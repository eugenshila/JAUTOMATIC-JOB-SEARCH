"""Job-board scraping.

Sources are pluggable. Public JSON endpoints and regional publisher feeds
are enabled by default; Adzuna and Jooble UAE require credentials in Settings.
``SampleSource`` fabricates
a handful of realistic postings so the app is fully usable offline (or when a
board rate-limits us).

Every source returns ``JobPosting`` objects and never raises: network/JSON
problems are collected per-source into ``FetchResult.error`` so the UI can show
"3 of 4 sources responded" instead of a traceback.
"""
from __future__ import annotations

import json
import random
import re
import time
from concurrent import futures
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import unescape
from typing import ClassVar
from urllib.parse import urlencode, urlparse

import requests

from ..models import JobPosting, keywords, strip_html
from .job_regions import location_matches

USER_AGENT = (
    "JAUTOMATIC-JOB-SEARCH/1.4 (+https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH) "
    "job-search-desktop-app"
)

CURRENCY = r"[$€£]|USD|EUR|GBP|PLN|CHF|SEK|NOK|DKK|CAD|AUD|INR|BRL|KES|AED|ZAR|NGN"
_NUMBER = r"\d[\d.,]*\s*[kK]?"
MONEY_RANGE_RE = re.compile(
    rf"(?:(?P<cur1>{CURRENCY})\s*)?(?P<low>{_NUMBER})\s*(?:-|–|—|to|until)\s*"
    rf"(?:(?P<cur2>{CURRENCY})\s*)?(?P<high>{_NUMBER})",
    re.IGNORECASE)
MONEY_WORD_RE = re.compile(rf"(?P<cur>{CURRENCY})", re.IGNORECASE)

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

# Words that make a number look like pay rather than a year or a head-count.
MONEY_HINTS = ("salary", "pay", "compensation", "package", "rate", "per annum", "p.a.",
               "gross", "net", "usd", "eur", "gbp", "pln", "k/year", "annually", "monthly",
               "kes", "aed", "zar", "ngn")


def _to_int(text: str) -> int:
    """Parse "90,000", "90k", "95.000" (EU thousands) and "1.2k" into an int."""
    value = str(text or "").strip().lower().replace(" ", "").replace("\u00a0", "")
    if not value:
        return 0
    multiplier = 1000 if value.endswith("k") else 1
    value = value.rstrip("k")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", value):
        value = value.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", value):
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", "")
    try:
        return int(round(float(value) * multiplier))
    except ValueError:
        return 0


def _currency_in(text: str) -> str:
    match = MONEY_WORD_RE.search(text or "")
    if not match:
        return ""
    found = match.group("cur").upper()
    return CURRENCY_SYMBOLS.get(found, found)


def _looks_like_pay(window: str, low: int, high: int) -> bool:
    """Reject year ranges ("2016 - 2018") and similar non-salary number pairs."""
    lowered = window.lower()
    if any(hint in lowered for hint in MONEY_HINTS) or _currency_in(window):
        return True
    if "k" in lowered:
        return True
    return low >= 10000 or high >= 10000


# --------------------------------------------------------------------------- #
# small parsing helpers
# --------------------------------------------------------------------------- #
def parse_salary(text: str) -> tuple[int, int, str]:
    """Best-effort salary extraction from free text -> (min, max, currency).

    Handles "$90,000 - $120,000", "€70k – 90k", "EUR 95000 - 75000" and returns
    (0, 0, "") when the text contains no plausible pay band.
    """
    plain = strip_html(text or "")
    if not plain:
        return 0, 0, ""
    for match in MONEY_RANGE_RE.finditer(plain):
        low = _to_int(match.group("low"))
        high = _to_int(match.group("high"))
        if not (low and high):
            continue
        window = plain[max(0, match.start() - 16):match.end() + 16]
        if not _looks_like_pay(window, low, high):
            continue
        if low > high:
            low, high = high, low
        period = plain[match.end():match.end() + 35].lower()
        if re.search(r"(?:per\s+|/\s*|\b)(?:month|monthly|mo\b)", period):
            low, high = low * 12, high * 12
        elif re.search(r"(?:per\s+|/\s*|\b)(?:hour|hourly|hr\b|week|weekly|day|daily)", period):
            # Do not invent working hours/days for an annual salary comparison.
            return 0, 0, _currency_in(plain)
        return low, high, _currency_in(plain)
    return 0, 0, ""


def looks_remote(*texts: str) -> bool:
    haystack = " ".join(t or "" for t in texts).lower()
    return any(word in haystack for word in
               ("remote", "anywhere", "work from home", "wfh", "distributed team",
                "home office", "telecommute", "fully remote"))


def _tagify(*texts: str, limit: int = 8) -> list[str]:
    """Pull a few human-readable tags out of the posting text."""
    stop = {"remote", "job", "jobs", "full", "part", "time", "fulltime", "full-time",
            "contract", "senior", "junior", "mid", "level", "engineering", "developer",
            "engineer", "manager", "specialist", "company", "global", "worldwide"}
    tagged: list[str] = []
    for word in keywords(" ".join(texts), limit=25):
        if word in stop or word.isdigit() or len(word) < 3:
            continue
        tagged.append(word)
        if len(tagged) >= limit:
            break
    return tagged


def _clean(value: object) -> str:
    return strip_html(str(value or "")).strip()


# --------------------------------------------------------------------------- #
# paste-any-URL single-post import
# --------------------------------------------------------------------------- #
def _domain_label(netloc: str) -> str:
    """Best-effort company-ish label from a hostname ("careers.greenhouse.io" -> "Greenhouse")."""
    parts = (netloc or "").lower().split(".")
    parts = [p for p in parts if p and p not in ("www", "jobs", "careers", "hiring")]
    if len(parts) >= 2:
        return parts[-2].title()
    return (parts[0] if parts else "").title()


def _extract_meta(html: str) -> dict[str, str]:
    """Fetch ``og:*`` / standard meta content for every tag (either attribute order)."""
    meta: dict[str, str] = {}
    for tag in re.findall(r"<meta[^>]+>", html, re.IGNORECASE):
        prop = re.search(r'(?:property|name)=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        content = re.search(r'content=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if prop and content:
            key = prop.group(1).lower()
            if key and key not in meta:
                meta[key] = unescape(content.group(1)).strip()
    return meta


def _first_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return unescape(match.group(1)).strip() if match else ""


def _ld_description(html: str) -> str:
    """Pulled from the first JSON-LD block that carries a real description."""
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)'
                            r'</script>', html, re.IGNORECASE | re.DOTALL):
        try:
            payload = json.loads(block.strip())
        except ValueError:
            continue
        description = (payload.get("description") if isinstance(payload, dict) else "")
        if isinstance(description, str) and description.strip():
            return unescape(description).strip()
    return ""


def _job_schema(html: str) -> dict:
    def walk(value):
        if isinstance(value, list):
            for child in value:
                yield from walk(child)
        elif isinstance(value, dict):
            if "JobPosting" in ([value.get("@type")] if isinstance(value.get("@type"), str)
                                else (value.get("@type") or [])):
                yield value
            yield from walk(value.get("@graph", []))
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)'
                            r'</script>', html, re.I | re.S):
        try:
            for job in walk(json.loads(block)):
                return job
        except (ValueError, TypeError):
            continue
    return {}


def posting_from_details(url: str, title: str, company: str, location: str,
                         description: str, remote: bool = False) -> JobPosting:
    """Import the user's copied job text without fetching or logging into a website."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter the job's http(s) URL.")
    if not all(value.strip() for value in (title, company, description)):
        raise ValueError("Enter the job title, employer and copied job description.")
    host = parsed.hostname.lower()
    source = "linkedin" if host == "linkedin.com" or host.endswith(".linkedin.com") else "manual"
    low, high, currency = parse_salary(description)
    return JobPosting(source=source, title=title.strip(), company=company.strip(),
                      location=location.strip(), description=description.strip(), url=url,
                      remote=remote, salary_min=low, salary_max=high, currency=currency,
                      tags=_tagify(title, description), posted_at="")


def posting_from_url(url: str, timeout: int = 15) -> JobPosting:
    """Best-effort single-post import from any public job-posting URL.

    Fetches the page and pulls title / company / description out of HTML meta
    tags and JSON-LD, falling back to the page ``<title>`` and the site's
    domain name.  Salary and remote status are parsed from the description the
    same way as the board sources.  Raises the underlying network/parsing
    error and leaves it to the caller to turn it into a friendly message.
    """
    url = (url or "").strip()
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"'{url}' is not a usable http(s) address.")

    response = requests.get(url, timeout=timeout,
                            headers={"User-Agent": USER_AGENT,
                                     "Accept": "text/html,application/xhtml+xml,*/*"})
    response.raise_for_status()
    html = response.text or ""

    meta = _extract_meta(html)
    schema = _job_schema(html)
    title = _clean(schema.get("title") or meta.get("og:title") or _first_title(html))
    description = (schema.get("description") or meta.get("og:description") or meta.get("description")
                   or _ld_description(html) or "").strip()
    company = (meta.get("og:site_name") or _domain_label(parsed.netloc)).strip()
    location = (meta.get("og:location") or meta.get("location") or "").strip()
    hiring = schema.get("hiringOrganization") or {}
    if isinstance(hiring, dict) and hiring.get("name"):
        company = _clean(hiring["name"])
    locations = schema.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    labels = []
    for place in locations if isinstance(locations, list) else []:
        address = place.get("address", {}) if isinstance(place, dict) else {}
        if isinstance(address, dict):
            country = address.get("addressCountry") or ""
            if isinstance(country, dict):
                country = country.get("name", "")
            labels.append(", ".join(_clean(v) for v in
                                   (address.get("addressLocality"), address.get("addressRegion"), country) if v))
    location = "; ".join(filter(None, labels)) or location
    salary_min, salary_max, currency = parse_salary(description[:600])
    remote = looks_remote(location, description)
    host = (parsed.hostname or "").lower()
    source = "linkedin" if host == "linkedin.com" or host.endswith(".linkedin.com") else "manual"
    if source == "linkedin":
        if not description or title.lower() in ("linkedin", "linkedin login, sign in") or "sign in" in title.lower():
            raise ValueError("LinkedIn did not provide the posting. Use Paste job details with text from your browser.")
        # LinkedIn posts "Title - Company | LinkedIn" into og:title; strip that.
        title = re.sub(r"\s*-\s*[^|]*\|\s*LinkedIn\s*$", "", title).strip()
    return JobPosting(
        source=source, title=title or "Job posting", company=company or parsed.netloc,
        location=location, remote=remote, salary_min=salary_min, salary_max=salary_max,
        currency=currency, url=url, description=description,
        tags=_tagify(title, description, limit=8), posted_at=str(schema.get("datePosted") or ""))


def linkedin_search_url(query_text: str, location: str = "",
                        easy_apply_only: bool = True, remote_only: bool = False) -> str:
    """Build a ready-to-open LinkedIn Jobs search URL.

    LinkedIn has no public job API and does not allow third-party scraping, so
    the app hands the search to the user's browser instead.  "Easy Apply" is
    not derivable from any feed either — it is applied as LinkedIn's own search
    parameter ``f_AL=true``, so only Easy Apply postings are returned.
    ``f_WT=2`` restricts results to remote roles when requested.
    """
    params = {"keywords": (query_text or "").strip(), "location": (location or "").strip()}
    if easy_apply_only:
        params["f_AL"] = "true"
    if remote_only:
        params["f_WT"] = "2"
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


# --------------------------------------------------------------------------- #
# query/result containers
# --------------------------------------------------------------------------- #
QUERY_STOPWORDS = {"a", "an", "and", "or", "the", "of", "for", "in", "on", "at", "to", "with",
                   "job", "jobs", "role", "roles", "position", "work", "working", "any",
                   "remote", "hybrid", "onsite", "full", "part", "time", "senior", "junior"}


def query_matches(text: str, terms: list[str], require_all: bool = True) -> bool:
    """Term matching for a posting: ``require_all`` = AND, otherwise OR."""
    if not terms:
        return True
    haystack = (text or "").lower()
    def matches(term):
        if term in ("logistics", "logistic"):
            return any(re.search(r"\b" + word + r"\b", haystack) for word in
                       ("logistics?", "supply chain", "procurement", "warehous(?:e|ing)",
                        "freight", "shipping", "transport(?:ation)?", "inventory", "distribution"))
        return term in haystack
    return all(matches(term) for term in terms) if require_all else any(matches(term) for term in terms)


@dataclass
class SearchQuery:
    text: str = ""
    location: str = ""
    remote_only: bool = False
    min_salary: int = 0
    salary_currency: str = "USD"
    limit_per_source: int = 25
    sources: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    include_sample: bool = False

    @property
    def terms(self) -> list[str]:
        """Query words: "python, django" / "data engineer" -> ["python", "django"] etc.

        Filler words ("senior", "remote", "role"…) are dropped so a normal job
        title does not filter out every result.
        """
        raw = [w for w in re.split(r"[^0-9A-Za-z+#.]+", (self.text or "").lower()) if w]
        words = [w for w in raw if len(w) > 1 and w not in QUERY_STOPWORDS]
        return words or raw


@dataclass
class FetchResult:
    source: str
    label: str
    jobs: list[JobPosting] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0
    fallback: bool = False      # injected demo data, not a real board response

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class SearchOutcome:
    jobs: list[JobPosting] = field(default_factory=list)
    results: list[FetchResult] = field(default_factory=list)
    elapsed: float = 0.0
    filtered_out: int = 0
    used_fallback: bool = False

    @property
    def sources_ok(self) -> list[str]:
        return [r.label for r in self.results if r.ok and not r.fallback]

    @property
    def sources_failed(self) -> list[str]:
        return [r.label for r in self.results if not r.ok]

    @property
    def errors(self) -> list[str]:
        return [f"{r.label}: {r.error}" for r in self.results if r.error]

    def summary(self) -> str:
        if self.used_fallback:
            parts = [f"No job board could be reached — showing {len(self.jobs)} demo posting(s) "
                     f"instead so you can still try the workflow."]
        else:
            contributing = len({job.source for job in self.jobs})
            parts = [f"{len(self.jobs)} matches from {contributing} source(s); "
                     f"{self.results_ok_count} board(s) responded"]
        if self.filtered_out:
            parts.append(f"{self.filtered_out} filtered out")
        if self.errors:
            parts.append("issues: " + "; ".join(self.errors))
        return " · ".join(parts)

    def source_summary(self) -> str:
        counts = {}
        for job in self.jobs:
            counts[job.source] = counts.get(job.source, 0) + 1
        return " | ".join(
            f"{result.label}: {result.error}" if result.error else
            f"{result.label}: {counts.get(result.source, 0)} shown / {len(result.jobs)} fetched"
            for result in self.results)

    @property
    def results_ok_count(self) -> int:
        """How many *real* job boards answered (the offline fallback does not count)."""
        return sum(1 for r in self.results if r.ok and not r.fallback)


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
class JobSource:
    name = "base"
    label = "Base"
    description = ""
    homepage = ""
    needs_credentials = False

    def is_configured(self, settings) -> bool:
        return True

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        raise NotImplementedError


def _request_json(url: str, timeout: int, params: dict | None = None) -> object:
    response = requests.get(url, params=params or {}, timeout=timeout,
                            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    response.raise_for_status()
    return response.json()


class RemotiveSource(JobSource):
    name = "remotive"
    label = "Remotive"
    description = "Curated remote roles, public JSON API (no key)."
    homepage = "https://remotive.com"

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        params = {"limit": max(query.limit_per_source, 5)}
        if query.text.strip():
            params["search"] = query.text.strip()
        payload = _request_json("https://remotive.com/api/remote-jobs", timeout, params)
        jobs: list[JobPosting] = []
        for item in (payload or {}).get("jobs", [])[: query.limit_per_source]:
            description = _clean(item.get("description"))
            salary_min, salary_max, currency = parse_salary(item.get("salary") or description[:400])
            jobs.append(JobPosting(
                source=self.name, title=_clean(item.get("title")),
                company=_clean(item.get("company_name")),
                location=_clean(item.get("candidate_required_location")) or "Remote",
                remote=True, salary_min=salary_min, salary_max=salary_max, currency=currency,
                url=item.get("url") or "", description=description,
                tags=[_clean(t) for t in (item.get("tags") or [])][:8],
                posted_at=str(item.get("publication_date") or "")))
        return jobs


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    label = "Arbeitnow"
    description = "European job board with a free JSON API (no key)."
    homepage = "https://www.arbeitnow.com"

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        payload = _request_json("https://www.arbeitnow.com/api/job-board-api", timeout)
        terms = query.terms
        jobs: list[JobPosting] = []
        loose: list[JobPosting] = []
        for item in (payload or {}).get("data", []):
            title = _clean(item.get("title"))
            description = _clean(item.get("description"))
            haystack = f"{title} {description} {' '.join(item.get('tags') or [])}".lower()
            if terms and not query_matches(haystack, terms):
                if not query_matches(haystack, terms, require_all=False):
                    continue
                strict_match = False
            else:
                strict_match = True
            remote = bool(item.get("remote")) or looks_remote(item.get("location", ""), description)
            salary_min, salary_max, currency = parse_salary(description[:600])
            posting = JobPosting(
                source=self.name, title=title, company=_clean(item.get("company_name")),
                location=_clean(item.get("location")) or ("Remote" if remote else ""),
                remote=remote, salary_min=salary_min, salary_max=salary_max, currency=currency,
                url=item.get("url") or "", description=description,
                tags=[_clean(t) for t in (item.get("tags") or [])][:8],
                posted_at=str(item.get("created_at") or ""))
            (jobs if strict_match else loose).append(posting)
            if len(jobs) >= query.limit_per_source:
                break
        return jobs[:query.limit_per_source] or loose[:query.limit_per_source]


class RemoteOkSource(JobSource):
    name = "remoteok"
    label = "RemoteOK"
    description = "Remote-first board, public JSON API (no key)."
    homepage = "https://remoteok.com"

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        payload = _request_json("https://remoteok.com/api", timeout)
        terms = query.terms
        jobs: list[JobPosting] = []
        loose: list[JobPosting] = []
        for item in (payload or []):
            if not isinstance(item, dict) or not item.get("position"):
                continue
            title = _clean(item.get("position"))
            description = _clean(item.get("description"))
            haystack = f"{title} {description} {' '.join(item.get('tags') or [])}".lower()
            if terms:
                if query_matches(haystack, terms):
                    strict_match = True
                elif query_matches(haystack, terms, require_all=False):
                    strict_match = False
                else:
                    continue
            else:
                strict_match = True
            salary_min = int(item.get("salary_min") or 0)
            salary_max = int(item.get("salary_max") or 0)
            posting = JobPosting(
                source=self.name, title=title, company=_clean(item.get("company")),
                location=_clean(item.get("location")) or "Remote", remote=True,
                salary_min=salary_min, salary_max=salary_max,
                currency="USD" if (salary_min or salary_max) else "",
                url=item.get("url") or item.get("apply_url") or "", description=description,
                tags=[_clean(t) for t in (item.get("tags") or [])][:8],
                posted_at=str(item.get("date") or ""))
            (jobs if strict_match else loose).append(posting)
            if len(jobs) >= query.limit_per_source:
                break
        return jobs[:query.limit_per_source] or loose[:query.limit_per_source]


class AdzunaSource(JobSource):
    name = "adzuna"
    label = "Adzuna"
    description = "Aggregated listings worldwide - needs a free API id + key."
    homepage = "https://developer.adzuna.com"
    needs_credentials = True

    def is_configured(self, settings) -> bool:
        return bool(settings.adzuna_app_id and settings.adzuna_app_key)

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        from ..models import AppSettings  # local import: avoids a cycle at import time

        settings = AppSettings()
        return self.fetch_with(query, settings, timeout)

    def fetch_with(self, query: SearchQuery, settings, timeout: int = 15) -> list[JobPosting]:
        country = (settings.adzuna_country or "gb").lower()
        params = {
            "app_id": settings.adzuna_app_id, "app_key": settings.adzuna_app_key,
            "results_per_page": query.limit_per_source, "what": query.text.strip(),
            "content-type": "application/json",
        }
        if query.location.strip():
            params["where"] = query.location.strip()
        from .eligibility import ADZUNA_CURRENCIES, currencies_match
        if query.min_salary and currencies_match(query.salary_currency, ADZUNA_CURRENCIES.get(country, "")):
            params["salary_min"] = query.min_salary
        payload = _request_json(
            f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", timeout, params)
        jobs: list[JobPosting] = []
        for item in (payload or {}).get("results", []):
            description = _clean(item.get("description"))
            salary_min = int(item.get("salary_min") or 0)
            salary_max = int(item.get("salary_max") or 0)
            location = _clean((item.get("location") or {}).get("display_name"))
            remote = looks_remote(location, description)
            jobs.append(JobPosting(
                source=self.name, title=_clean(item.get("title")),
                company=_clean((item.get("company") or {}).get("display_name")),
                location=location, remote=remote, salary_min=salary_min, salary_max=salary_max,
                currency=ADZUNA_CURRENCIES.get(country, ""),
                url=item.get("redirect_url") or "", description=description,
                tags=_tagify(description, limit=6), posted_at=str(item.get("created") or "")))
        return jobs


# Country aliases accepted in the location box, mapped to Himalayas' ISO codes.
_COUNTRY_ALIASES = {
    "ke": "KE", "kenya": "KE", "nairobi": "KE", "mombasa": "KE",
    "ae": "AE", "uae": "AE", "emirates": "AE", "dubai": "AE", "abu dhabi": "AE",
    "za": "ZA", "south africa": "ZA", "johannesburg": "ZA", "cape town": "ZA",
    "ng": "NG", "nigeria": "NG", "lagos": "NG",
    "gh": "GH", "ghana": "GH", "eg": "EG", "egypt": "EG", "ma": "MA", "morocco": "MA",
    "ke,ug,tz": "KE",
}


class HimalayasSource(JobSource):
    """Remote roles from Himalayas.app - free public API, no key. Covers Kenya,
    South Africa, UAE and every other country via the ``country`` filter when
    the location box names a place; otherwise returns worldwide remote roles."""

    name = "himalayas"
    label = "Himalayas"
    description = "Remote roles worldwide incl. Kenya/Africa/UAE - free JSON API (no key)."
    homepage = "https://himalayas.app"

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        params: dict[str, object] = {}
        if query.text.strip():
            params["q"] = query.text.strip()
        location_lookups = [query.location.lower().strip()]
        if "," in query.location:
            location_lookups += [part.strip() for part in query.location.lower().split(",")]
        country = next((_COUNTRY_ALIASES[part] for part in location_lookups
                        if part in _COUNTRY_ALIASES), "")
        if country:
            params["country"] = country
        payload = _request_json("https://himalayas.app/jobs/api/search", timeout, params)
        jobs: list[JobPosting] = []
        for item in (payload or {}).get("jobs", [])[: query.limit_per_source]:
            location = "Remote (Worldwide)"
            location_restrictions = item.get("locationRestrictions") or []
            if location_restrictions:
                names = [r.get("name") if isinstance(r, dict) else str(r)
                         for r in location_restrictions]
                if any(names):
                    location = ", ".join(n for n in names if n)
            remote = True
            salary_min = int(item.get("minSalary") or 0)
            salary_max = int(item.get("maxSalary") or 0)
            period = (item.get("salaryPeriod") or "annual").lower()
            if period == "monthly":
                salary_min *= 12
                salary_max *= 12
            elif period not in ("annual", "annually", "yearly", "year"):
                salary_min = salary_max = 0  # hours and working weeks are unknown
            currency = item.get("currency") or ""
            description = _clean(item.get("description") or item.get("excerpt") or "")
            jobs.append(JobPosting(
                source=self.name, title=_clean(item.get("title")),
                company=_clean(item.get("companyName")),
                location=location, remote=remote, salary_min=salary_min, salary_max=salary_max,
                currency=currency, url=item.get("applicationLink") or item.get("guid") or "",
                description=description,
                tags=[_clean(t) for t in (item.get("categories") or [])][:8],
                posted_at=str(item.get("pubDate") or "")))
        return jobs


class ArtificialAeSource(JobSource):
    """UAE AI / tech roles from artificial.ae - free public JSON API (no key),
    refreshed hourly. Filters by emirate when the location box names one."""

    name = "uae_ai"
    label = "UAE AI jobs"
    description = "UAE AI & tech roles (Dubai, Abu Dhabi…) - free JSON API (no key)."
    homepage = "https://artificial.ae"
    needs_credentials = False

    _EMIRATES: ClassVar[dict[str, str]] = {
        "dubai": "dubai", "dubai, uae": "dubai", "abu dhabi": "abu dhabi",
        "sharjah": "sharjah", "ajman": "ajman", "fujairah": "fujairah",
        "ras al khaimah": "ras al khaimah", "umm al quwain": "umm al quwain",
        "uae": "", "emirates": "", "ae": "",
    }

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        params: dict[str, object] = {}
        location = query.location.strip().lower()
        emirate = self._EMIRATES.get(location, "")
        if emirate:
            params["emirate"] = emirate
        payload = _request_json("https://artificial.ae/api/v1/jobs", timeout, params)
        jobs: list[JobPosting] = []
        for item in (payload or {}).get("data", [])[: query.limit_per_source]:
            title = _clean(item.get("title"))
            if query.terms and not query_matches(
                    f"{title} {item.get('role') or ''} {item.get('company') or ''}".lower(),
                    query.terms):
                continue
            emirate_value = _clean(item.get("emirate"))
            remote = emirate_value.lower() == "remote"
            location = "Remote (UAE)" if remote else f"{emirate_value.title()}, UAE"
            jobs.append(JobPosting(
                source=self.name, title=title, company=_clean(item.get("company")),
                location=location, remote=remote, salary_min=0, salary_max=0, currency="",
                url=item.get("canonical") or item.get("url") or "", description="",
                tags=_tagify(title, limit=8), posted_at=str(item.get("posted_ts") or "")))
        return jobs


class SampleSource(JobSource):
    """Offline demo data - keeps the whole pipeline usable without a network."""

    name = "sample"
    label = "Demo data"
    description = "Locally generated postings so the app works offline."
    homepage = ""

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        terms = query.terms or ["python"]
        random.seed(7)
        jobs: list[JobPosting] = []
        strict: list[dict] = []
        loose: list[dict] = []
        for template in SAMPLE_TEMPLATES:
            title = template["title"]
            haystack = f"{title} {' '.join(template['tags'])} {template['description']}".lower()
            if not terms or query_matches(haystack, terms):
                strict.append(template)
            elif query_matches(haystack, terms, require_all=False):
                loose.append(template)
        for template in (strict or loose):
            posted = date.today() - timedelta(days=random.randint(0, 21))
            jobs.append(JobPosting(
                source=self.name, title=template["title"], company=template["company"],
                location=template["location"], remote=template["remote"],
                salary_min=template["salary_min"], salary_max=template["salary_max"],
                currency="USD", url=f"https://example.com/jobs/{template['slug']}",
                description=template["description"], tags=list(template["tags"]),
                posted_at=posted.isoformat()))
            if len(jobs) >= query.limit_per_source:
                break
        return jobs


SAMPLE_TEMPLATES: list[dict] = [
    {
        "slug": "senior-python-engineer", "title": "Senior Python Engineer",
        "company": "Northwind Analytics", "location": "Berlin, Germany", "remote": True,
        "salary_min": 85000, "salary_max": 105000,
        "tags": ["python", "fastapi", "postgresql", "aws", "docker", "sql"],
        "description": (
            "We are looking for a Senior Python Engineer to own our data platform. "
            "You will build FastAPI services, model data in PostgreSQL, ship containers to AWS "
            "and mentor two mid-level engineers. Requirements: 5+ years with Python, solid SQL, "
            "experience with Docker, CI/CD and testing. Nice to have: Kubernetes, Airflow, dbt."),
    },
    {
        "slug": "backend-engineer-go", "title": "Backend Engineer (Go)",
        "company": "Kestrel Logistics", "location": "Remote (EU)", "remote": True,
        "salary_min": 70000, "salary_max": 90000,
        "tags": ["golang", "grpc", "kubernetes", "postgresql", "microservices"],
        "description": (
            "Join a distributed team building real-time shipment tracking. Stack: Go, gRPC, "
            "Kubernetes, PostgreSQL, Kafka. You will design microservices, improve p99 latency "
            "and work closely with product. 3+ years of backend experience required."),
    },
    {
        "slug": "data-engineer-airflow", "title": "Data Engineer",
        "company": "Helio Health", "location": "Amsterdam, Netherlands", "remote": False,
        "salary_min": 65000, "salary_max": 80000,
        "tags": ["python", "airflow", "sql", "dbt", "snowflake", "etl"],
        "description": (
            "Design and maintain batch and streaming pipelines (Airflow, dbt, Snowflake). "
            "You will partner with analysts, enforce data quality checks and document datasets. "
            "Strong Python and advanced SQL skills are essential; healthcare data experience is a plus."),
    },
    {
        "slug": "ml-engineer-nlp", "title": "Machine Learning Engineer, NLP",
        "company": "Lingua Labs", "location": "Remote (Worldwide)", "remote": True,
        "salary_min": 90000, "salary_max": 125000,
        "tags": ["python", "pytorch", "nlp", "transformers", "mlops", "llm"],
        "description": (
            "Ship NLP features end to end: data curation, transformer fine-tuning, evaluation "
            "and production serving. You will own model quality metrics and work on LLM retrieval "
            "pipelines. Required: Python, PyTorch, strong software engineering habits."),
    },
    {
        "slug": "product-manager-platform", "title": "Product Manager, Platform",
        "company": "Arcadia Software", "location": "London, UK", "remote": True,
        "salary_min": 75000, "salary_max": 95000,
        "tags": ["product", "roadmap", "stakeholders", "agile", "analytics", "api"],
        "description": (
            "Own the platform roadmap for a B2B SaaS product. You will run discovery interviews, "
            "write specs with engineering, track adoption metrics and prioritise the backlog. "
            "Experience with developer-facing API products is a strong plus."),
    },
    {
        "slug": "frontend-engineer-react", "title": "Frontend Engineer (React)",
        "company": "Bluebird Studio", "location": "Lisbon, Portugal", "remote": True,
        "salary_min": 55000, "salary_max": 72000,
        "tags": ["typescript", "react", "css", "jest", "accessibility", "vite"],
        "description": (
            "Build accessible, fast product surfaces in TypeScript and React. You will work with "
            "designers on a component library, keep bundle size in check and write tests with Jest "
            "and Playwright. 3+ years of modern frontend experience."),
    },
    {
        "slug": "devops-sre", "title": "Site Reliability Engineer",
        "company": "Corelight Cloud", "location": "Remote (US/EU)", "remote": True,
        "salary_min": 95000, "salary_max": 120000,
        "tags": ["terraform", "kubernetes", "prometheus", "gcp", "linux", "on-call"],
        "description": (
            "Keep a multi-region platform healthy: Terraform infrastructure, Kubernetes workloads, "
            "Prometheus/Grafana observability and blameless incident reviews. You will automate "
            "toil, improve deployment safety and share on-call rotation."),
    },
    {
        "slug": "junior-data-analyst", "title": "Data Analyst",
        "company": "Meridian Retail", "location": "Warsaw, Poland", "remote": False,
        "salary_min": 32000, "salary_max": 45000,
        "tags": ["sql", "python", "tableau", "excel", "statistics", "reporting"],
        "description": (
            "Turn retail data into decisions: write SQL against our warehouse, build Tableau "
            "dashboards, automate recurring reports in Python and present findings to category "
            "managers. 1-3 years of analytical experience."),
    },
    {
        "slug": "qa-automation", "title": "QA Automation Engineer",
        "company": "Vantage Payments", "location": "Remote (EU)", "remote": True,
        "salary_min": 52000, "salary_max": 68000,
        "tags": ["python", "pytest", "playwright", "ci", "api", "testing"],
        "description": (
            "Own automated test coverage for a payments API: pytest suites, Playwright end-to-end "
            "flows, contract tests in CI and quality gates in the release pipeline. You will shape "
            "how the team tests and release."),
    },
    {
        "slug": "engineering-manager", "title": "Engineering Manager, Backend",
        "company": "Orbit Commerce", "location": "Remote (EU)", "remote": True,
        "salary_min": 110000, "salary_max": 140000,
        "tags": ["leadership", "hiring", "coaching", "python", "architecture", "delivery"],
        "description": (
            "Lead a team of eight backend engineers across two squads. Responsibilities: hiring, "
            "coaching, delivery planning, technical direction and stakeholder communication. "
            "You stay close to the code without being the primary implementer."),
    },
]


class TaskSource(JobSource):
    """Offline demo feed of microtask-style remote gigs (pay per task in USD).

    Live microtask portals (Remotasks, Clickworker, Outlier, Appen…) only show
    tasks after signing in and have no public API, so the Tasks search works on
    this bundled feed plus postings the user tracks by pasting a link.
    """

    name = "tasks"
    label = "Task feed (demo)"
    description = "Locally generated microtask gigs with per-task USD pay."
    homepage = ""

    def fetch(self, query: SearchQuery, timeout: int = 15) -> list[JobPosting]:
        if query.limit_per_source <= 0:
            return []
        terms = query.terms
        random.seed(11)
        jobs: list[JobPosting] = []
        strict: list[dict] = []
        loose: list[dict] = []
        for template in TASK_TEMPLATES:
            title = template["title"]
            haystack = f"{title} {' '.join(template['tags'])} {template['description']}".lower()
            if not terms or query_matches(haystack, terms):
                strict.append(template)
            elif query_matches(haystack, terms, require_all=False):
                loose.append(template)
        for template in (strict or loose):
            posted = date.today() - timedelta(days=random.randint(0, 9))
            jobs.append(JobPosting(
                source=self.name, title=template["title"],
                company="Remote microtask platform",
                location="Remote", remote=True,
                salary_min=template["pay_min"], salary_max=template["pay_max"],
                currency="USD", url=f"https://example.com/tasks/{template['slug']}",
                description=template["description"], tags=list(template["tags"]),
                posted_at=posted.isoformat()))
            if len(jobs) >= query.limit_per_source:
                break
        return jobs


TASK_TEMPLATES: list[dict] = [
    {
        "slug": "audio-transcription", "title": "Audio transcription - English audio",
        "pay_min": 12, "pay_max": 25,
        "tags": ["transcription", "typing", "english", "audio", "writing"],
        "description": (
            "Transcribe short English audio clips (2-10 minutes) with accurate spelling and "
            "punctuation. Each task quotes a per-audio rate paid in USD. Requirements: fluent "
            "English, a quiet workspace while listening, and attention to speaker overlap."),
    },
    {
        "slug": "image-data-labeling", "title": "Image data labeling - object tagging",
        "pay_min": 8, "pay_max": 18,
        "tags": ["data-labeling", "computer-vision", "tagging", "online", "remote"],
        "description": (
            "Label objects in photos: draw boxes around vehicles, people and signs to train "
            "computer-vision models. Per-image pay, batches of 20-50 images, quality checked "
            "by the client. Good for detail-oriented workers with steady hands."),
    },
    {
        "slug": "text-annotation", "title": "Text annotation - sentiment & intent",
        "pay_min": 10, "pay_max": 22,
        "tags": ["annotation", "nlp", "writing", "english", "data"],
        "description": (
            "Read short customer messages and tag sentiment and intent to train language "
            "models. Each text pays between $10 and $22 for a batch of 10. Requires excellent "
            "written English and consistent judgement across similar examples."),
    },
    {
        "slug": "content-moderation", "title": "Content moderation - chat & forum review",
        "pay_min": 12, "pay_max": 20,
        "tags": ["content-moderation", "review", "community", "english", "typing"],
        "description": (
            "Review flagged chat messages and forum posts against a moderation policy and "
            "decide keep/remove with a short note. Paid per reviewed submission. "
            "Requires careful reading and tolerance for repetitive content."),
    },
    {
        "slug": "web-goodness-testing", "title": "Website QA testing - functional checks",
        "pay_min": 15, "pay_max": 45,
        "tags": ["qa", "testing", "web", "reports", "remote"],
        "description": (
            "Work through test scenarios on live websites (checkout, sign-up, search) and "
            "report bugs with screenshots. Per-test-suite pay between $15 and $45. A "
            "second screen helps when comparing expected vs actual behaviour."),
    },
    {
        "slug": "search-result-comparison", "title": "Search quality - result relevance",
        "pay_min": 6, "pay_max": 15,
        "tags": ["search", "evaluation", "research", "english", "online"],
        "description": (
            "Compare two sets of search results for the same query and judge which is more "
            "relevant. Per-batch pay of $6-$15. Requires good web research skills and "
            "consistent application of the rating rubric."),
    },
    {
        "slug": "photo-tagging-catalog", "title": "Product photo tagging - e-commerce",
        "pay_min": 7, "pay_max": 14,
        "tags": ["tagging", "ecommerce", "catalog", "typing", "online"],
        "description": (
            "Tag product photos with category, colour, material and angle. Per-image pay, "
            "large batches available. Simple, repetitive work for fast typists; quality "
            "review catches inconsistent tags."),
    },
    {
        "slug": "translation-review", "title": "Translation review - EN/ES/FR",
        "pay_min": 14, "pay_max": 30,
        "tags": ["translation", "review", "writing", "english", "spanish", "french"],
        "description": (
            "Review machine translations of short UI strings and fix mistranslations. Paid "
            "per string batch in USD. Native or near-native speakers of English with working "
            "Spanish or French preferred."),
    },
    {
        "slug": "audio-verification", "title": "Audio verification - transcription QC",
        "pay_min": 9, "pay_max": 19,
        "tags": ["audio", "verification", "qc", "english", "typing"],
        "description": (
            "Listen to a transcription and correct errors against the recording. Per-clip "
            "pay of $9-$19. Comparable to transcription work but with an emphasis on "
            "spotting automated mistakes quickly."),
    },
    {
        "slug": "survey-taxonomy", "title": "Survey classification - response coding",
        "pay_min": 8, "pay_max": 16,
        "tags": ["surveys", "classification", "data", "english", "typing"],
        "description": (
            "Classify free-text survey answers into pre-defined categories using a rubric. "
            "Paid per batch of 25 responses. Methodical workers who can apply a category "
            "tree consistently do best."),
    },
]


def default_task_sources() -> list[JobSource]:
    return [TaskSource()]


def default_sources() -> list[JobSource]:
    from .regional_job_sources import regional_sources, JoobleUaeSource
    return [RemotiveSource(), ArbeitnowSource(), RemoteOkSource(), HimalayasSource(),
            ArtificialAeSource(), *regional_sources(), JoobleUaeSource(), AdzunaSource(), SampleSource()]


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
class JobScraper:
    """Runs the enabled sources concurrently and de-duplicates their results."""

    def __init__(self, settings=None, sources: list[JobSource] | None = None) -> None:
        self.settings = settings
        self.sources = {s.name: s for s in (sources if sources is not None else default_sources())}

    # -- public API -------------------------------------------------------- #
    def search(self, query: SearchQuery, progress=None, should_cancel=None) -> SearchOutcome:
        started = time.perf_counter()
        selected = self._select_sources(query)
        results: list[FetchResult] = []
        collected: list[JobPosting] = []
        cancelled = False

        def run(source: JobSource) -> FetchResult:
            begin = time.perf_counter()
            try:
                jobs = self._fetch_source(source, query)
                return FetchResult(source.name, source.label, jobs, "", time.perf_counter() - begin)
            except requests.exceptions.RequestException as exc:
                return FetchResult(source.name, source.label, [], self._friendly_error(exc),
                                   time.perf_counter() - begin)
            except (ValueError, KeyError, TypeError) as exc:
                return FetchResult(source.name, source.label, [],
                                   f"unexpected response ({exc.__class__.__name__})",
                                   time.perf_counter() - begin)

        if selected:
            pool = futures.ThreadPoolExecutor(max_workers=min(6, len(selected)))
            try:
                for result in pool.map(run, selected):
                    if should_cancel is not None and should_cancel():
                        # App closing: stop consuming, drop queued fetches and let
                        # the in-flight ones (bounded by the request timeout) end
                        # on their own instead of holding shutdown hostage.
                        cancelled = True
                        break
                    results.append(result)
                    collected.extend(result.jobs)
                    if progress:
                        progress(result)
            finally:
                pool.shutdown(wait=not cancelled, cancel_futures=True)

        fallback = False
        # Nothing came back and something went wrong on the wire -> keep the app useful
        # by falling back to the offline demo source (clearly flagged in the summary).
        if not cancelled and not collected and results and all(not r.ok for r in results):
            sample = self.sources.get(SampleSource.name)
            if sample is not None and not any(r.source == sample.name for r in results):
                try:
                    demo = sample.fetch(query, timeout=self._timeout())
                except Exception:  # noqa: BLE001 - the fallback must never raise
                    demo = []
                if demo:
                    results.append(FetchResult(sample.name, "Demo data (offline fallback)", demo,
                                               fallback=True))
                    collected.extend(demo)
                    fallback = True

        jobs, filtered_out = self._post_process(collected, query)
        return SearchOutcome(jobs=jobs, results=results, elapsed=time.perf_counter() - started,
                             filtered_out=filtered_out, used_fallback=fallback)

    # -- internals --------------------------------------------------------- #
    def _select_sources(self, query: SearchQuery) -> list[JobSource]:
        names = query.sources or (self.settings.enabled_sources if self.settings else [])
        chosen: list[JobSource] = []
        for name in names:
            source = self.sources.get(name)
            if not source:
                continue
            if source.needs_credentials and self.settings and not source.is_configured(self.settings):
                continue
            chosen.append(source)
        if query.include_sample or not chosen:
            sample = self.sources.get(SampleSource.name)
            if sample and sample not in chosen:
                chosen.append(sample)
        return chosen

    def _fetch_source(self, source: JobSource, query: SearchQuery) -> list[JobPosting]:
        if source.needs_credentials and self.settings is not None:
            return source.fetch_with(query, self.settings, self._timeout())
        return source.fetch(query, timeout=self._timeout())

    def _timeout(self) -> int:
        return int(getattr(self.settings, "request_timeout", 15) or 15)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        text = str(exc) or exc.__class__.__name__
        lowered = text.lower()
        if isinstance(exc, requests.exceptions.Timeout) or "timed out" in lowered or "timeout" in lowered:
            return "timed out"
        if "429" in text:
            return "rate limited (429) - try again in a few minutes"
        if "403" in text:
            return "blocked by the site (403)"
        if "404" in text:
            return "endpoint moved (404) - check for an app update"
        if isinstance(exc, requests.exceptions.SSLError) or "ssl" in lowered:
            return "TLS handshake failed - check your network or VPN"
        if isinstance(exc, requests.exceptions.ProxyError):
            return "proxy refused the connection"
        if isinstance(exc, requests.exceptions.ConnectionError) or "connection" in lowered \
                or "unreachable" in lowered or "resolve" in lowered:
            return "no connection to the job board (offline or blocked?)"
        return text[:160]

    def _post_process(self, jobs: list[JobPosting],
                      query: SearchQuery) -> tuple[list[JobPosting], int]:
        seen: set[str] = set()
        unique: list[JobPosting] = []
        for job in jobs:
            fingerprint = job.fingerprint
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique.append(job)

        terms = query.terms
        excluded = [k.lower() for k in (query.exclude_keywords or [])]
        kept: list[JobPosting] = []
        strict_hits = 0
        dropped = 0
        for job in unique:
            haystack = job.searchable_text().lower()
            if terms:
                strict = query_matches(haystack, terms)
                if not strict and not query_matches(haystack, terms, require_all=False):
                    dropped += 1
                    continue
                strict_hits += int(strict)
            if excluded and any(bad in haystack for bad in excluded):
                dropped += 1
                continue
            if query.remote_only and not job.remote:
                dropped += 1
                continue
            if not location_matches(query.location, job.location, job.remote):
                dropped += 1
                continue
            if query.min_salary:
                from .eligibility import currencies_match
                ceiling = job.salary_max or job.salary_min
                if (ceiling and currencies_match(job.currency, query.salary_currency)
                        and ceiling < query.min_salary):
                    dropped += 1
                    continue
            kept.append(job)

        kept.sort(key=lambda j: (j.age_days if j.age_days is not None else 999,
                                -int(bool(j.salary_max))))
        if terms and strict_hits == 0:
            # nothing matched every word: keep the looser (single-word) matches
            kept = [job for job in kept if query_matches(job.searchable_text().lower(), terms,
                                                         require_all=False)]
            dropped = len(unique) - len(kept)
        return kept, dropped


__all__ = [
    "AdzunaSource",
    "ArbeitnowSource",
    "FetchResult",
    "JobScraper",
    "JobSource",
    "RemoteOkSource",
    "RemotiveSource",
    "SampleSource",
    "SearchOutcome",
    "SearchQuery",
    "default_sources",
    "linkedin_search_url",
    "looks_remote",
    "parse_salary",
    "posting_from_url",
]
