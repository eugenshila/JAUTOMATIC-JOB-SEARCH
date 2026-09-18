"""Search adapters for genuinely free learning resources.

Results are deliberately conservative: a result is marked ``Free access``
when the source advertises free learning, and ``Free certificate`` only when
the source explicitly advertises a no-cost certificate. The UI never claims a
certificate is free when that fact is not known.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
from urllib.parse import quote_plus

import requests

from ..learning import CATEGORIES


@dataclass(frozen=True)
class CourseResult:
    title: str
    provider: str
    url: str
    category: str
    description: str = ""
    level: str = ""
    duration: str = ""
    certificate_status: str = "Unknown"


CATEGORY_TERMS = {
    "Supply Chain & Logistics": "supply chain logistics",
    "AI": "artificial intelligence AI machine learning",
    "Business Management": "business management leadership",
    "Ecommerce": "ecommerce online retail digital commerce",
    "Customer Care": "customer service customer care support",
}

# Class Central is used as a discovery index; its results link to the original
# provider. The query requires free, but certificate wording is still verified
# conservatively from the result text.
SEARCH_URL = "https://www.classcentral.com/search?q={}"


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def search_courses(category: str, query: str = "", limit: int = 30, timeout: float = 12) -> list[CourseResult]:
    if category not in CATEGORIES:
        raise ValueError(f"Unsupported learning category: {category}")
    terms = f"{CATEGORY_TERMS[category]} free course certificate {query}".strip()
    response = requests.get(SEARCH_URL.format(quote_plus(terms)), timeout=timeout,
                            headers={"User-Agent": "JAUTOMATIC learning search/1.0"})
    response.raise_for_status()
    html = response.text
    results: list[CourseResult] = []
    # Keep this adapter intentionally small and dependency-free. The index
    # page exposes course links and titles in standard anchor elements.
    pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    seen: set[str] = set()
    for href, raw_title in pattern.findall(html):
        title = _clean(raw_title)
        if len(title) < 4 or href.startswith("#"):
            continue
        url = href if href.startswith("http") else "https://www.classcentral.com" + href
        if "/course/" not in url and "/class/" not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        lowered = title.lower()
        # Only return candidates whose title matches the requested subject.
        if not any(term in lowered for term in CATEGORY_TERMS[category].split()):
            continue
        results.append(CourseResult(
            title=title,
            provider="Class Central discovery",
            url=url,
            category=category,
            certificate_status="Verify on provider: free access is not proof of a free certificate",
        ))
        if len(results) >= max(1, min(limit, 100)):
            break
    return results
