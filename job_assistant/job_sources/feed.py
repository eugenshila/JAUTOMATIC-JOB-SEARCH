"""Generic RSS/Atom and JSON feed connector.

This connector does not scrape HTML, bypass a login, or solve anti-bot controls.
It is deliberately limited to URLs supplied by the user or an approved provider.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any

from .base import JobRecord


class PublicFeedConnector:
    name = "Public API / RSS feed"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def search(self, *, feed_url: str, titles: list[str], locations: list[str]) -> list[JobRecord]:
        request = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "AI-Job-Application-Assistant/0.1 (permitted-feed-client)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - user-configured URL
            payload = response.read()
            content_type = response.headers.get("Content-Type", "")
        if "json" in content_type.lower() or payload.lstrip().startswith((b"{", b"[")):
            return self._parse_json(payload, feed_url)
        return self._parse_xml(payload, feed_url)

    def _parse_xml(self, payload: bytes, feed_url: str) -> list[JobRecord]:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError(f"The feed at {feed_url} is not valid RSS or Atom XML: {exc}") from exc
        records: list[JobRecord] = []
        for item in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = self._child_text(item, "title")
            description = self._child_text(item, "description") or self._child_text(item, "summary") or self._child_text(item, "content")
            link = self._child_text(item, "link")
            if not link:
                atom_link = item.find("{http://www.w3.org/2005/Atom}link")
                link = atom_link.get("href", "") if atom_link is not None else ""
            if not title or not link:
                continue
            description = _strip_html(unescape(description))
            email = _find_email(description)
            records.append(JobRecord(
                title=title.strip(), company=self._child_text(item, "company").strip(),
                location=self._child_text(item, "location").strip(), description=description,
                job_url=urllib.parse.urljoin(feed_url, link.strip()),
                external_id=self._child_text(item, "guid") or self._child_text(item, "id"),
                source_name=self.name, application_email=email,
                application_method="email" if email else "website",
                posted_at=self._child_text(item, "pubDate") or self._child_text(item, "published"),
                raw_data={"feed_url": feed_url},
            ))
        return records

    def _parse_json(self, payload: bytes, feed_url: str) -> list[JobRecord]:
        try:
            data: Any = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"The JSON feed at {feed_url} could not be read: {exc}") from exc
        if isinstance(data, dict):
            for key in ("jobs", "results", "data", "items"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            return []
        records = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = str(_value(item, "title", "name") or "").strip()
            url = str(_value(item, "job_url", "url", "link") or "").strip()
            if not title or not url:
                continue
            records.append(JobRecord(
                title=title,
                company=str(_value(item, "company", "employer", "company_name") or "").strip(),
                location=str(_value(item, "location", "city") or "").strip(),
                country=str(item.get("country") or "").strip(),
                description=_strip_html(str(_value(item, "description", "summary") or "")),
                job_url=url,
                external_id=str(_value(item, "id", "job_id", "external_id") or ""),
                source_name=self.name,
                application_email=str(item.get("application_email") or "").strip(),
                application_method=str(item.get("application_method") or "website").strip(),
                application_instructions=str(item.get("application_instructions") or "").strip(),
                job_type=str(item.get("job_type") or "").strip(),
                workplace_type=str(item.get("workplace_type") or "").strip(),
                posted_at=str(_value(item, "posted_at", "date_posted") or ""),
                closing_at=str(_value(item, "closing_at", "deadline") or ""),
                raw_data={"feed_url": feed_url, "source": item},
            ))
        return records

    @staticmethod
    def _child_text(element: ET.Element, name: str) -> str:
        child = element.find(name)
        if child is None:
            child = element.find(f"{{http://www.w3.org/2005/Atom}}{name}")
        return "" if child is None or child.text is None else child.text


def _value(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if item.get(key) is not None:
            return item[key]
    return None


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value).replace("&nbsp;", " ").strip()


def _find_email(value: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
    return match.group(0) if match else ""
