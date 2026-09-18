"""Publisher-provided African feeds and the official Jooble UAE API."""
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode
import re
import xml.etree.ElementTree as ET

import requests

from ..models import JobPosting, parse_date
from .job_regions import country_codes, location_matches, region_codes
from .job_scraper import JobSource, USER_AGENT, _clean, _tagify, looks_remote, parse_salary, query_matches


def regional_search_url(board, query, easy_apply=False, remote_only=False):
    if board.startswith("LinkedIn"):
        from .job_scraper import linkedin_search_url
        return linkedin_search_url(query, "United Arab Emirates" if board.endswith("UAE") else "Africa",
                                   easy_apply_only=easy_apply, remote_only=remote_only)
    if board == "Bayt UAE":
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
        return "https://www.bayt.com/en/uae/jobs/" + (f"{slug}-jobs/" if slug else "")
    if board == "GulfTalent UAE":
        return "https://www.gulftalent.com/uae/jobs?" + urlencode({"keywords": query})
    sites = {"BrighterMonday Kenya": "https://www.brightermonday.co.ke/jobs",
             "BrighterMonday Uganda": "https://www.brightermonday.co.ug/jobs",
             "Jobberman Nigeria": "https://www.jobberman.com/jobs"}
    return sites[board] + "?" + urlencode({"q": query})


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


class JoobleUaeSource(JobSource):
    name = "jooble_uae"
    label = "Jooble UAE"
    description = "UAE roles across industries; requires a UAE-specific Jooble API key."
    homepage = "https://ae.jooble.org/api/about"
    needs_credentials = True

    def is_configured(self, settings):
        return bool(getattr(settings, "jooble_uae_key", "").strip())

    def fetch(self, query, timeout=15):
        raise ValueError("Add a UAE Jooble API key in Settings")

    def fetch_with(self, query, settings, timeout=15):
        key = getattr(settings, "jooble_uae_key", "").strip()
        if not key:
            raise ValueError("Add a UAE Jooble API key in Settings")
        if query.location and "AE" not in country_codes(query.location):
            return []
        from .job_regions import CITY_COUNTRIES, contains
        city = next((city for city, country in CITY_COUNTRIES.items()
                     if country == "AE" and contains(query.location, city)), "United Arab Emirates")
        try:
            response = requests.post("https://jooble.org/api/" + quote(key, safe=""),
                                     json={"keywords": query.text, "location": city,
                                           "page": 1, "ResultOnPage": min(100, query.limit_per_source)},
                                     headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            # Keys are part of the API URL: never surface a requests exception containing it.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise requests.RequestException(
                f"Jooble UAE request failed ({status or 'network error'}); check UAE key/quota in Settings"
            ) from None
        payload = response.json()
        jobs = []
        for item in payload.get("jobs", []):
            low, high, currency = parse_salary(_clean(item.get("salary")))
            title, description = _clean(item.get("title")), _clean(item.get("snippet"))
            location = _clean(item.get("location"))
            # Keep original geography: a key for another country must not create fake UAE jobs.
            jobs.append(JobPosting(
                source=self.name, title=title, company=_clean(item.get("company")),
                description=description, location=location, url=item.get("link") or "",
                remote=looks_remote(location, title), salary_min=low, salary_max=high,
                currency=currency, posted_at=str(item.get("updated") or ""),
                tags=_tagify(title, description)))
        return jobs[:query.limit_per_source]
