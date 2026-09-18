"""Conservative multi-source discovery of free learning resources."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html import unescape
import re
from urllib.parse import quote_plus, urlsplit

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
    "AI": ("artificial intelligence", "machine learning", "deep learning", "data science"),
    "Business Management": ("business management", "management", "leadership", "entrepreneurship"),
    "Ecommerce": ("ecommerce", "e-commerce", "online retail", "digital marketing"),
    "Customer Care": ("customer service", "customer care", "customer support", "call center"),
}
SOURCES = (
    ("Class Central", "https://www.classcentral.com/search?q={}"),
    ("OpenLearn", "https://www.open.edu/openlearn/search-results?query={}"),
    ("Saylor Academy", "https://learn.saylor.org/course/search.php?search={}"),
    ("Great Learning", "https://www.mygreatlearning.com/academy/learn-for-free/courses?search={}"),
    ("Alison", "https://alison.com/courses?query={}"),
)

def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()

def _search_source(source, category: str, terms: str, limit: int, timeout: float) -> list[CourseResult]:
    provider, template = source
    response = requests.get(template.format(quote_plus(terms)), timeout=timeout, headers={"User-Agent": "JAUTOMATIC learning search/1.0"})
    response.raise_for_status()
    base = urlsplit(template.split("{}", 1)[0])
    found, seen = [], set()
    for href, raw_title in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', response.text, re.I | re.S):
        title = _clean(raw_title)
        if len(title) < 4 or not any(term in title.casefold() for term in CATEGORY_TERMS[category]):
            continue
        if href.startswith("/"): href = f"{base.scheme}://{base.netloc}{href}"
        if not href.startswith(("http://", "https://")) or href in seen:
            continue
        seen.add(href)
        found.append(CourseResult(title, provider, href, category, certificate_status="Verify provider: free access does not guarantee a free certificate"))
        if len(found) >= limit: break
    return found

def search_courses(category: str, query: str = "", limit: int = 30, timeout: float = 12) -> list[CourseResult]:
    if category not in CATEGORIES: raise ValueError(f"Unsupported learning category: {category}")
    limit = max(1, min(int(limit), 100))
    terms = f"{' '.join(CATEGORY_TERMS[category])} free course {query}".strip()
    output, seen = [], set()
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        jobs = [pool.submit(_search_source, source, category, terms, limit, timeout) for source in SOURCES]
        for job in as_completed(jobs):
            try: results = job.result()
            except (OSError, requests.RequestException, ValueError): continue
            for result in results:
                if result.url not in seen:
                    seen.add(result.url); output.append(result)
                    if len(output) >= limit: return output
    return output
