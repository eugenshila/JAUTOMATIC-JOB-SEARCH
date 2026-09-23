"""Websites that advertise real paid micro-tasks, opened in your browser on demand.

Every platform below needs its own account and publishes no public feed
JAUTOMATIC could read, so the Tasks search hands your words to your own
signed-in browser — the same pattern as the job tab's "More websites" row.
Nothing is scraped and no account is linked; the opportunities you accept are
recorded by hand with "Add task details" in the separate task workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote_plus
import re

#: Search words used when the search box is empty, per task-type filter.
CATEGORY_TERMS = {
    'Data entry': 'data entry',
    'Web research': 'web research',
    'Categorisation': 'categorisation',
    'Testing': 'testing',
    'Other': 'micro task',
}
DEFAULT_TERMS = 'micro tasks'


def task_search_terms(query: str = '', category: str = 'All types') -> str:
    """Words sent to the websites: the typed query, else the selected task type."""
    text = re.sub(r'\s+', ' ', (query or '').strip())
    return text or CATEGORY_TERMS.get(category or '', '') or DEFAULT_TERMS


@dataclass(frozen=True)
class TaskPlatform:
    """One paid-task website and how to reach its open work from search words."""

    name: str
    label: str
    homepage: str
    hint: str
    build: Callable[[str], str]

    def search_url(self, terms: str = '') -> str:
        return self.build(terms or DEFAULT_TERMS)


def _static(url: str) -> Callable[[str], str]:
    return lambda terms: url


def _clickworker(terms: str) -> str:
    # Clickworker publishes category landing pages; the workplace feed needs
    # sign-in and has no shareable search link.
    text = terms.casefold()
    if 'categor' in text:
        return 'https://www.clickworker.com/clickworker-categorization-jobs/'
    if any(word in text for word in ('research', 'data entry', 'data-entry', 'record')):
        return 'https://www.clickworker.com/web-research-jobs/'
    return 'https://workplace.clickworker.com/'


def _oneforma(terms: str) -> str:
    return 'https://www.oneforma.com/projects/?s=' + quote_plus(terms)


def _upwork(terms: str) -> str:
    return 'https://www.upwork.com/nx/search/jobs/?q=' + quote_plus(terms)


TASK_PLATFORMS: dict[str, TaskPlatform] = {site.name: site for site in (
    TaskPlatform('clickworker', 'Clickworker', 'https://workplace.clickworker.com/',
                 'Data entry, categorisation and web-research micro-tasks. '
                 'Sign in to the workplace task feed.', _clickworker),
    TaskPlatform('mturk', 'Amazon MTurk', 'https://www.mturk.com/',
                 'Amazon\'s HIT marketplace for small paid tasks. Sign in to the '
                 'worker site and search the HIT list with your words.',
                 _static('https://www.mturk.com/worker/tasks')),
    TaskPlatform('appen', 'Appen', 'https://appen.com/jobs/contributor/',
                 'AI-training micro-tasks through the Appen Contributor Portal '
                 '(longer projects live on Appen Connect). Sign in to see open work.',
                 _static('https://appen.com/jobs/contributor/')),
    TaskPlatform('telus_ai', 'TELUS Digital AI', 'https://www.telusinternational.ai/',
                 'TELUS Digital AI (formerly Lionbridge AI) data and rating projects. '
                 'Sign in to see your active projects.',
                 _static('https://app.telusinternational.ai/contributor/my-projects/active')),
    TaskPlatform('oneforma', 'OneForma', 'https://www.oneforma.com/projects/',
                 'Paid data collection, transcription, judging and annotation '
                 'projects (by Centific). The project board is public and searchable.',
                 _oneforma),
    TaskPlatform('utest', 'uTest', 'https://www.utest.com/projects',
                 'Paid software-testing cycles: find bugs, report issues. '
                 'Sign in to apply for test cycles.', _static('https://www.utest.com/projects')),
    TaskPlatform('microworkers', 'Microworkers', 'https://www.microworkers.com/',
                 'Small online tasks posted by employers. Sign in, then browse '
                 'the Jobs tab for available microjobs.',
                 _static('https://www.microworkers.com/')),
    TaskPlatform('prolific', 'Prolific', 'https://www.prolific.com/',
                 'Paid academic research studies. Sign in to see the studies '
                 'currently open to you.', _static('https://app.prolific.com/studies')),
    TaskPlatform('upwork', 'Upwork', 'https://www.upwork.com/',
                 'Freelance micro-jobs and short contracts. The search is public '
                 'and runs with your words straight away.', _upwork),
)}


def task_platform_names() -> list[str]:
    """Platform keys in display order (matches the settings default)."""
    return list(TASK_PLATFORMS)


def task_platform(name: str) -> TaskPlatform:
    """Look up one platform; raises :class:`KeyError` for unknown names."""
    return TASK_PLATFORMS[name]
