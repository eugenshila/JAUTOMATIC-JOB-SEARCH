"""Search adapters for free learning resources.

The service searches several public discovery indexes and labels certificate
claims conservatively. Free learning access and a free certificate are separate
facts; the UI never presents an unknown certificate as free.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "Supply Chain & Logistics": ("supply chain", "logistics", "procurement", "inventory", "warehouse"),
    "AI": ("artificial intelligence", "machine learning", "deep learning", "data science", " AI "),
    "Business Management": ("business management", "management", "leadership", "entrepreneurship"),
    "Ecommerce": ("ecommerce", "e-commerce", "online retail", "digital marketing", "shopify"),
    "Customer Care": ("customer service", "customer care", "customer support", "call center", "communication"),
}

# Discovery sources. They are indexes, not certificate issuers; the original
# provider link is retained and the learner is told to verify final terms.
SOURCE_SEARCH_URLS = (
    ("Class Central", "https://www.classcentral.com/search?q={}"),
    ("OpenLearn", "https://www.open.edu/openlearn/search-results?query={}"),
    ("Saylor Academy", "https://learn.saylor.org/course/search.php?search={}"),
    ("Great Learning", "https://www.mygreatlearning.com/academy/learn-for-free/courses?search={}"),
    ("Alison", "https://alison.com/courses?query={}"),
)


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _matches_category(title: str, category: str) -> bool:
    lowered = f" {title.casefold()} "
    return any(term.casefold() in lowered for term in CATEGORY_TERMS[category])


def _search_source(source: tuple[str, str], category: str, terms: str, limit: int, timeout: float) -> list[CourseResult]:
    provider, template = source
    response = requests.get(template.format(quote_plus(terms)), timeout=timeout,
                            headers={"User-Agent": "JAUTOMATIC learning search/1.0"})
    response.raise_for_status()
    results: list[CourseResult] = []
    seen: set[str] = set()
    pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
    for href, raw_title in pattern.findall(response.text):
        title = _clean(raw_title)
        if len(title) < 4 or not _matches_category(title, category):
            continue
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        if href.startswith("/"):
            from urllib.parse import urlsplit
            base = urlsplit(template.split("{}", 1)[0])
            href = f"{base.scheme}://{base.netloc}{href}"
        if not href.startswith(("http://", "https://")) or href in seen:
            continue
        seen.add(href)
        results.append(CourseResult(
            title=title,
            provider=provider,
            url=href,
            category=category,
            certificate_status="Verify provider: free access does not guarantee a free certificate",
        ))
        if len(results) >= limit:
            break
    return results


def search_courses(category: str, query: str = "", limit: int = 30, timeout: float = 12) -> list[CourseResult]:
    if category not in CATEGORIES:
        raise ValueError(f"Unsupported learning category: {category}")
    limit = max(1, min(int(limit), 100))
    terms = f"{' '.join(CATEGORY_TERMS[category])} free course no cost {query}".strip()
    results: list[CourseResult] = []
    seen_urls: set[str] = set()
    with ThreadPoolExecutor(max_workers=len(SOURCE_SEARCH_URLS)) as executor:
        futures = [executor.submit(_search_source, source, category, terms, limit, timeout)
                   for source in SOURCE_SEARCH_URLS]
        for future in as_completed(futures):
            try:
                source_results = future.result()
            except (OSError, requests.RequestException, ValueError):
                continue
            for result in source_results:
                if result.url not in seen_urls:
                    seen_urls.add(result.url)
                    results.append(result)
                    if len(results) >= limit:
                        return results
    return results
