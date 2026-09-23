"""Publisher-provided African feeds, the Gulf browser hand-off and Jooble's API.

Two kinds of regional coverage live here:

* feeds and APIs JAUTOMATIC can read for you (MyJobMag / JobWeb African RSS
  feeds, Jooble's official country APIs), and
* Gulf boards that publish no feed at all (Bayt, GulfTalent, NaukriGulf,
  foundit, Indeed, Dubizzle…), which the app opens in your own browser so you
  can paste a posting back into the tracker.
"""
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote, urlencode
import re
import xml.etree.ElementTree as ET

import requests

from ..models import JobPosting, parse_date
from .job_regions import country_codes, location_matches, region_codes
from .job_scraper import JobSource, USER_AGENT, _clean, _tagify, looks_remote, parse_salary, query_matches

# --------------------------------------------------------------------------- #
# browser hand-off: the "More websites" catalog
# --------------------------------------------------------------------------- #
GULF_REGIONS = ("UAE", "Saudi Arabia", "Qatar", "Kuwait", "Oman", "Bahrain")
GULF_CITIES = ("Dubai", "Abu Dhabi", "Sharjah", "Riyadh", "Jeddah", "Dammam", "Doha",
               "Muscat", "Manama")
#: African regions LinkedIn's hand-off accepts as free-text locations.
AFRICAN_REGIONS = ("Africa", "Kenya", "Uganda", "Tanzania", "Nigeria", "Ghana", "South Africa")

_COUNTRY_SLUGS = {"UAE": "uae", "Saudi Arabia": "saudi-arabia", "Qatar": "qatar",
                  "Kuwait": "kuwait", "Oman": "oman", "Bahrain": "bahrain"}
_CITY_SLUGS = {**_COUNTRY_SLUGS, "Dubai": "dubai", "Abu Dhabi": "abu-dhabi",
               "Sharjah": "sharjah", "Riyadh": "riyadh", "Jeddah": "jeddah",
               "Dammam": "dammam", "Doha": "doha", "Muscat": "muscat",
               "Manama": "manama"}
_INDEED_HOSTS = {"UAE": "ae.indeed.com", "Saudi Arabia": "sa.indeed.com",
                 "Qatar": "qa.indeed.com", "Kuwait": "kw.indeed.com",
                 "Oman": "om.indeed.com", "Bahrain": "bh.indeed.com",
                 "Nigeria": "ng.indeed.com", "South Africa": "za.indeed.com"}
_DUBIZZLE_HOSTS = {"Dubai": "dubai.dubizzle.com", "Abu Dhabi": "abudhabi.dubizzle.com",
                   "Sharjah": "sharjah.dubizzle.com"}
_BRIGHTERMONDAY = {"Kenya": "https://www.brightermonday.co.ke/jobs",
                   "Uganda": "https://www.brightermonday.co.ug/jobs",
                   "Tanzania": "https://www.brightermonday.co.tz/jobs"}
_JOBBERMAN = {"Nigeria": "https://www.jobberman.com/jobs",
              "Ghana": "https://www.jobberman.com.gh/jobs"}
# LinkedIn takes a free-text location, so every region is simply its own name.
_LINKEDIN_LOCATIONS = {"UAE": "United Arab Emirates", "Worldwide": ""}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _linkedin(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    from .job_scraper import linkedin_search_url
    return linkedin_search_url(query, _LINKEDIN_LOCATIONS.get(region, region),
                               easy_apply_only=easy_apply, remote_only=remote_only)


def _bayt(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    path = f"{_slug(query)}-jobs/" if _slug(query) else ""
    return f"https://www.bayt.com/en/{_COUNTRY_SLUGS[region]}/jobs/{path}"


def _gulftalent(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    return (f"https://www.gulftalent.com/{_COUNTRY_SLUGS[region]}/jobs?"
            + urlencode({"keywords": query}))


def _naukrigulf(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    keyword = _slug(query)
    place = _CITY_SLUGS[region]
    return ("https://www.naukrigulf.com/"
            + (f"{keyword}-jobs-in-{place}" if keyword else f"jobs-in-{place}"))


def _foundit(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    keyword = _slug(query)
    place = _CITY_SLUGS[region]
    return ("https://www.founditgulf.com/search/"
            + (f"{keyword}-jobs-in-{place}" if keyword else f"jobs-in-{place}"))


def _indeed(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    # Indeed's own filters (date posted, remote) stay on the site: their query
    # parameters differ per edition and a wrong one silently narrows results.
    return f"https://{_INDEED_HOSTS[region]}/jobs?" + urlencode({"q": query})


def _dubizzle(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    return f"https://{_DUBIZZLE_HOSTS[region]}/jobs/search/?" + urlencode({"keywords": query})


def _qatar_living(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
    return "https://www.qatarliving.com/jobs?" + urlencode({"keys": query})


def _query_param(sites: dict[str, str]) -> Callable[[str, str, bool, bool], str]:
    def build(query: str, region: str, easy_apply: bool, remote_only: bool) -> str:
        return sites[region] + "?" + urlencode({"q": query})
    return build


@dataclass(frozen=True)
class BrowserSite:
    """One job website the app can open in your browser, and the regions it covers."""

    board: str
    regions: tuple[str, ...]
    build: Callable[[str, str, bool, bool], str]
    hint: str = ""


BROWSER_SITES: dict[str, BrowserSite] = {site.board: site for site in (
    BrowserSite("LinkedIn", ("Worldwide", *AFRICAN_REGIONS, *GULF_REGIONS),
                _linkedin, "No public API - opens your own logged-in browser."),
    BrowserSite("Bayt", GULF_REGIONS, _bayt, "The Gulf's largest board; no public feed."),
    BrowserSite("GulfTalent", GULF_REGIONS, _gulftalent, "Professional and managerial Gulf roles."),
    BrowserSite("NaukriGulf", GULF_REGIONS + GULF_CITIES, _naukrigulf,
                "Gulf board with salary and experience filters."),
    BrowserSite("foundit Gulf", GULF_REGIONS + GULF_CITIES, _foundit,
                "Formerly Monster Gulf."),
    BrowserSite("Indeed", tuple(_INDEED_HOSTS), _indeed, "Indeed's Gulf and African editions."),
    BrowserSite("Dubizzle", tuple(_DUBIZZLE_HOSTS), _dubizzle, "UAE classifieds jobs by emirate."),
    BrowserSite("Qatar Living", ("Qatar",), _qatar_living, "Qatar's local jobs portal."),
    BrowserSite("BrighterMonday", ("Kenya", "Uganda", "Tanzania"),
                _query_param(_BRIGHTERMONDAY), "East African board."),
    BrowserSite("Jobberman", ("Nigeria", "Ghana"), _query_param(_JOBBERMAN), "West African board."),
)}

#: The combined labels earlier releases used ("Bayt UAE"), kept working.
LEGACY_BROWSER_LABELS = {
    "LinkedIn Africa": ("LinkedIn", "Africa"),
    "LinkedIn UAE": ("LinkedIn", "UAE"),
    "Bayt UAE": ("Bayt", "UAE"),
    "GulfTalent UAE": ("GulfTalent", "UAE"),
    "BrighterMonday Kenya": ("BrighterMonday", "Kenya"),
    "BrighterMonday Uganda": ("BrighterMonday", "Uganda"),
    "Jobberman Nigeria": ("Jobberman", "Nigeria"),
}


def resolve_board(board: str, region: str = "") -> tuple[BrowserSite, str]:
    """``("Bayt UAE", "")`` and ``("Bayt", "UAE")`` both resolve to the same site."""
    board = (board or "").strip()
    if board in LEGACY_BROWSER_LABELS and not region:
        board, region = LEGACY_BROWSER_LABELS[board]
    site = BROWSER_SITES.get(board)
    if site is None:
        raise ValueError(f"'{board}' is not one of the websites JAUTOMATIC can open.")
    if region not in site.regions:
        region = site.regions[0]
    return site, region


def browser_boards() -> list[str]:
    """Board names for the 'More websites' dropdown, in display order."""
    return list(BROWSER_SITES)


def browser_regions(board: str) -> list[str]:
    """Regions a board covers - the second dropdown follows the first."""
    try:
        site, _ = resolve_board(board)
    except ValueError:
        return []
    return list(site.regions)


def browser_hint(board: str) -> str:
    try:
        site, _ = resolve_board(board)
    except ValueError:
        return ""
    return site.hint


def regional_search_url(board: str, query: str = "", easy_apply: bool = False,
                        remote_only: bool = False, region: str = "") -> str:
    """Search URL for a website the app cannot read itself (opened in a browser)."""
    site, region = resolve_board(board, region)
    return site.build((query or "").strip(), region, easy_apply, remote_only)



def feed_date(value):
    parsed = parse_date(value)
    if parsed:
        return parsed.isoformat()
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (ValueError, TypeError, IndexError):
        return ""


class RegionalFeedSource(JobSource):
    def __init__(self, name, label, homepage, country, feed, search_feed=False):
        self.name, self.label, self.homepage = name, label, homepage
        self.country, self.feed, self.search_feed = country, feed, search_feed
        self.description = f"{country} job feed; local and on-site roles, no API key."

    def fetch(self, query, timeout=15):
        if query.location and not location_matches(query.location, self.country):
            # City searches still need the country's feed.
            targets = country_codes(query.location) | region_codes(query.location)
            if not (targets & country_codes(self.country)):
                return []
        params = {"s": query.text.strip()} if self.search_feed and query.text.strip() else {}
        response = requests.get(self.feed, params=params, timeout=timeout,
                                headers={"User-Agent": USER_AGENT,
                                         "Accept": "application/rss+xml,application/xml,text/xml"})
        response.raise_for_status()
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ValueError("The publisher did not return a readable job feed") from exc
        if root.tag.rsplit("}", 1)[-1] != "rss":
            raise ValueError("The publisher returned a page instead of a job feed")
        jobs = []
        for item in root.findall("./channel/item"):
            def value(name):
                return _clean(item.findtext(name, ""))
            url = value("link")
            if not url.startswith(("https://", "http://")):
                continue
            expiry = feed_date(value("expiryDate"))
            if expiry and expiry < date.today().isoformat():
                continue
            title, company = value("position"), value("company")
            if not title:
                title = value("title")
                parts = re.split(r"\s+(?:job |vacancy )?at\s+", title, maxsplit=1, flags=re.I)
                if len(parts) == 2:
                    title, company = parts
            if not title:
                continue
            description = value("{http://purl.org/rss/1.0/modules/content/}encoded") or value("description")
            # Feeds sometimes include copyright/link boilerplate after the job.
            description = re.split(r"The post .+ appeared first on", description)[0].strip()
            text = f"{title} {description}"
            if any(term.startswith("logistic") for term in query.terms):
                # A legal/admin role at a logistics company is not a logistics vacancy.
                text = title + (" " + description if "operations" in title.lower() else "")
            if not query_matches(text, query.terms, require_all=False):
                continue
            location = value("location") or value("region")
            if not location:
                from .job_regions import CITY_COUNTRIES
                cities = [city.title() for city, code in CITY_COUNTRIES.items()
                          if code in country_codes(self.country) and
                          re.search(r"\b" + re.escape(city) + r"\b", description[:2500], re.I)]
                location = ", ".join(cities[:3])
            location = f"{location}, {self.country}" if location else self.country
            remote = looks_remote(title, location)
            if query.remote_only and not remote:
                continue
            if not location_matches(query.location, location, remote):
                continue
            low, high, currency = parse_salary(value("salary"))
            jobs.append(JobPosting(
                source=self.name, title=title, company=company or "Employer not supplied",
                url=url, location=location, remote=remote, description=description,
                salary_min=low, salary_max=high, currency=currency,
                tags=_tagify(title, value("industry")), posted_at=feed_date(value("pubDate"))))
        # Apply the limit after relevance/location filtering, not before it.
        return jobs[:max(0, query.limit_per_source)]


def regional_sources():
    return [
        RegionalFeedSource("myjobmag_ke", "MyJobMag Kenya", "https://www.myjobmag.co.ke", "Kenya",
                           "https://www.myjobmag.co.ke/aggregate_feed.xml"),
        RegionalFeedSource("myjobmag_ng", "MyJobMag Nigeria", "https://www.myjobmag.com", "Nigeria",
                           "https://www.myjobmag.com/aggregate_feed.xml"),
        RegionalFeedSource("myjobmag_za", "MyJobMag South Africa", "https://www.myjobmag.co.za", "South Africa",
                           "https://www.myjobmag.co.za/aggregate_feed.xml"),
        RegionalFeedSource("jobweb_ke", "JobWeb Kenya", "https://jobwebkenya.com", "Kenya",
                           "https://jobwebkenya.com/feed/", True),
        RegionalFeedSource("jobweb_ug", "JobWeb Uganda", "https://jobwebuganda.com", "Uganda",
                           "https://jobwebuganda.com/feed/", True),
        RegionalFeedSource("jobweb_tz", "JobWeb Tanzania", "https://jobwebtanzania.com", "Tanzania",
                           "https://jobwebtanzania.com/feed/", True),
    ]


#: Jooble runs one website - and one API key - per country. A key from
#: jooble.org (US) returns US jobs only, so each Gulf state is its own source.
#: Oman has no Jooble site (om.jooble.org does not resolve), so it is not listed.
JOBLE_COUNTRIES = {
    "ae": ("Jooble UAE", "United Arab Emirates", "AE"),
    "sa": ("Jooble Saudi Arabia", "Saudi Arabia", "SA"),
    "qa": ("Jooble Qatar", "Qatar", "QA"),
    "kw": ("Jooble Kuwait", "Kuwait", "KW"),
    "bh": ("Jooble Bahrain", "Bahrain", "BH"),
}
#: "ae" keeps its historical source name (``jooble_uae``) so saved settings work.
JOBLE_EXTRA_CODES = ("sa", "qa", "kw", "bh")


def jooble_key(settings, code: str) -> str:
    """The Jooble key for one country; ``jooble_uae_key`` is the legacy UAE field."""
    keys = getattr(settings, "jooble_keys", None)
    key = str(keys.get(code, "") or "").strip() if isinstance(keys, dict) else ""
    if not key and code == "ae":
        key = str(getattr(settings, "jooble_uae_key", "") or "").strip()
    return key


class JoobleSource(JobSource):
    """One Jooble country site, reachable only with that country's own API key."""

    needs_credentials = True

    def __init__(self, code: str, name: str | None = None) -> None:
        self.code = code.lower()
        self.label, self.country, self.iso = JOBLE_COUNTRIES[self.code]
        self.name = name or f"jooble_{self.code}"
        self.description = (f"{self.country} roles across industries; needs its own "
                            f"Jooble API key (free, {self.code}.jooble.org/api/about).")
        self.homepage = f"https://{self.code}.jooble.org/api/about"

    def is_configured(self, settings) -> bool:
        return bool(jooble_key(settings, self.code))

    def fetch(self, query, timeout=15):
        raise ValueError(f"Add a {self.country} Jooble API key in Settings")

    def fetch_with(self, query, settings, timeout=15):
        key = jooble_key(settings, self.code)
        if not key:
            raise ValueError(f"Add a {self.country} Jooble API key in Settings")
        if query.location:
            # "Gulf" and "GCC" name this country too, not just its own name/cities.
            targets = country_codes(query.location) | region_codes(query.location)
            if self.iso not in targets:
                return []
        from .job_regions import CITY_COUNTRIES, contains
        city = next((found for found, country in CITY_COUNTRIES.items()
                     if country == self.iso and contains(query.location, found)), self.country)
        try:
            response = requests.post(f"https://{self.code}.jooble.org/api/" + quote(key, safe=""),
                                     json={"keywords": query.text, "location": city,
                                           "page": 1, "ResultOnPage": min(100, query.limit_per_source)},
                                     headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            # Keys are part of the API URL: never surface a requests exception containing it.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise requests.RequestException(
                f"{self.label} request failed ({status or 'network error'}); "
                f"check the {self.country} key/quota in Settings"
            ) from None
        payload = response.json()
        jobs = []
        for item in payload.get("jobs", []):
            low, high, currency = parse_salary(_clean(item.get("salary")))
            title, description = _clean(item.get("title")), _clean(item.get("snippet"))
            location = _clean(item.get("location"))
            # Keep original geography: a key for another country must not invent
            # jobs in this one.
            jobs.append(JobPosting(
                source=self.name, title=title, company=_clean(item.get("company")),
                description=description, location=location, url=item.get("link") or "",
                remote=looks_remote(location, title), salary_min=low, salary_max=high,
                currency=currency, posted_at=str(item.get("updated") or ""),
                tags=_tagify(title, description)))
        return jobs[:query.limit_per_source]


class JoobleUaeSource(JoobleSource):
    """The UAE site, under the source name earlier releases saved."""

    def __init__(self) -> None:
        super().__init__("ae", name="jooble_uae")


def jooble_gulf_sources() -> list[JobSource]:
    """Jooble sources for the other Gulf states (each needs its own key)."""
    return [JoobleSource(code) for code in JOBLE_EXTRA_CODES]


def jooble_sources() -> list[JobSource]:
    return [JoobleUaeSource(), *jooble_gulf_sources()]
