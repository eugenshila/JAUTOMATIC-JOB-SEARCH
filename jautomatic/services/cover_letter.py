"""Cover-letter drafting.

Keeps everything deterministic and template driven (no hidden AI calls): the
letter is assembled from the profile, the posting and the match analysis, so
the output is always explainable and reproducible.  Four tones are supported
and the paragraph about *why this company* is written from the posting text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..models import (JobPosting, Profile, human_join, keywords, pretty_term, slugify,
                      source_label, specific_keywords, tokenize)
from .cv_generator import GeneratedDocument, export

TONES = ("professional", "friendly", "enthusiastic", "concise")
TONE_LABELS = {
    "professional": "Professional",
    "friendly": "Friendly",
    "enthusiastic": "Enthusiastic",
    "concise": "Concise",
}

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class MatchContext:
    """What the matcher found - used to pick which strengths to highlight."""
    score: int = 0
    matched_keywords: list[str] = None  # type: ignore[assignment]
    missing_keywords: list[str] = None  # type: ignore[assignment]
    reasons: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.matched_keywords = self.matched_keywords or []
        self.missing_keywords = self.missing_keywords or []
        self.reasons = self.reasons or []


def block_of(job: JobPosting) -> set[str]:
    """Title/company words that must not be advertised as skills."""
    return {t for t in tokenize(job.title) + tokenize(job.company)}


IRREGULAR_VERBS = {"built", "led", "ran", "drove", "cut", "made", "wrote", "grew", "won",
                   "shipped", "took", "kept", "set", "taught", "brought", "sold", "spoke",
                   "held", "found", "left", "met", "saw", "chose", "paid", "sent", "told"}


def _is_verb_led(text: str) -> bool:
    """True when the bullet starts with a past-tense verb ("Owned the platform…")."""
    first = re.split(r"\s+", text.strip())[0].strip(",.:;").lower() if text.strip() else ""
    return bool(first) and (first in IRREGULAR_VERBS or first.endswith("ed"))


def _third_to_first(text: str) -> str:
    first, _, rest = text.partition(" ")
    return f"{first.lower()} {rest}".strip()


def _company_hook(job: JobPosting) -> str:
    """Derive one concrete sentence about the employer from the posting."""
    if not job.description.strip():
        return (f"I am drawn to {job.company}'s mandate"
                f"{f' in {job.location}' if job.location else ''}"
                f" and the {job.title} brief in particular.")
    sentences = [s.strip() for s in SENTENCE_SPLIT.split(job.description.strip()) if s.strip()]
    candidate = ""
    for sentence in sentences[:6]:
        lowered = sentence.lower()
        if any(word in lowered for word in ("we ", "our ", "you will", "the role", "we're",
                                            "we are", "join")):
            if 40 <= len(sentence) <= 240:
                candidate = sentence
                break
    if not candidate:
        candidate = (sentences[0][:220] if sentences else "")
    candidate = candidate.rstrip(".")
    if not candidate:
        return f"I am drawn to {job.company} and the {job.title} brief in particular."
    return f"What stood out in your posting: “{candidate}.”"


def _strength_sentence(profile: Profile, match: MatchContext, job: JobPosting) -> str:
    block = {t for t in tokenize(job.title) + tokenize(job.company)}
    strengths = specific_keywords(list(match.matched_keywords) or list(job.tags),
                                  extra_block=block, limit=4)
    skills = (human_join([pretty_term(s) for s in strengths])
              if strengths else "the core requirements of the role")
    years = _total_years(profile)
    lead = profile.headline.strip() or "an experienced practitioner"
    head = f"{years}+ years" if years >= 2 else (f"{years} year" if years == 1 else "")
    if head:
        return (f"Across {head} working as {lead}, I have shipped production work using "
                f"{skills} — the exact areas your {job.title} posting calls out.")
    return (f"As {lead}, I have hands-on, production experience with {skills}, which maps "
            f"directly onto your {job.title} posting.")


def _experience_months(profile: Profile) -> int:
    """Career length in months, merging overlapping roles (no double counting)."""
    import datetime as _dt

    today = (_dt.date.today().year, _dt.date.today().month)
    spans: list[tuple[int, int]] = []
    for entry in profile.experience:
        start = _parse_year_month(entry.start)
        if not start:
            continue
        end = _parse_year_month(entry.end) or today
        if end < start:
            continue
        spans.append((start[0] * 12 + start[1], end[0] * 12 + end[1]))
    if not spans:
        return 0
    spans.sort()
    merged = [list(spans[0])]
    for begin, finish in spans[1:]:
        if begin <= merged[-1][1] + 1:            # overlapping or contiguous
            merged[-1][1] = max(merged[-1][1], finish)
        else:
            merged.append([begin, finish])
    return sum(finish - begin for begin, finish in merged)


def _total_years(profile: Profile) -> int:
    """Whole years of (deduplicated) professional experience."""
    return _experience_months(profile) // 12


def _parse_year_month(value: str) -> tuple[int, int] | None:
    if not value:
        return None
    text = value.strip().lower()
    if text in ("present", "now", "current"):
        return None
    match = re.search(r"(\d{4})[-/ ]?(\d{2})?", text)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2) or 12)
    return year, max(1, min(12, month))


def _closing(tone: str, profile: Profile, job: JobPosting) -> str:
    if tone == "enthusiastic":
        return (f"I would love the chance to talk about how I can help {job.company} move faster. "
                f"Thank you for your time and consideration.")
    if tone == "friendly":
        return ("I'd be glad to chat about the role whenever suits you. Thanks so much for "
                "taking the time to read this.")
    if tone == "concise":
        return "Thank you for your consideration; I am available for an interview at short notice."
    return ("I would welcome the opportunity to discuss the position in more detail. "
            "Thank you for your time and consideration.")


def render_cover_letter(profile: Profile, job: JobPosting, match: MatchContext | None = None,
                        tone: str | None = None) -> str:
    tone = (tone or profile.tone or "professional").lower()
    if tone not in TONES:
        tone = "professional"
    match = match or MatchContext()

    greeting = profile.greeting.strip() or "Dear Hiring Team,"
    if job.company and greeting.lower().startswith("dear hiring"):
        greeting = f"Dear {job.company} Hiring Team,"

    paragraphs = [
        f"I am applying for the {job.title} position at {job.company}"
        + (f" in {job.location}" if job.location and not job.remote else " (remote)")
        + (f", which I found via {source_label(job.source)}." if job.source
           else ", which I found on your careers page."),
        _strength_sentence(profile, match, job),
        _company_hook(job),
    ]

    if profile.experience:
        entry = profile.experience[0]
        bullets = entry.as_bullets()
        proof = bullets[0].rstrip(".") if bullets else entry.summary.strip()
        if proof:
            who = (entry.title or "a senior contributor") + (
                f" at {entry.company}" if entry.company else "")
            detail = f"I {_third_to_first(proof)}" if _is_verb_led(proof) else proof
            paragraphs.append(f"Most recently, as {who}, {detail}.")

    if tone != "concise" and profile.skills:
        extra = [s for s in profile.skills
                 if s.lower() not in {k.lower() for k in match.matched_keywords}
                 and s.lower() not in block_of(job)]
        if extra:
            paragraphs.append("Beyond that, I also bring "
                              + human_join([pretty_term(s) for s in extra[:5]]) + " to the team.")

    if profile.salary_floor and job.salary_max:
        if job.salary_max < profile.salary_floor:
            paragraphs.append(
                "For full transparency, my salary expectations start around "
                f"{profile.currency} {profile.salary_floor:,}; I am happy to discuss the "
                "bands you have in mind for this role.")
        else:
            paragraphs.append(
                f"Your advertised range of {job.salary_text} aligns well with my expectations, "
                "so compensation should not be an obstacle.")

    if tone == "concise":
        paragraphs = paragraphs[:3]

    paragraphs.append(_closing(tone, profile, job))

    body = "\n\n".join(p.strip() for p in paragraphs if p and p.strip())
    signature = profile.signature_block().strip()
    letter = f"{greeting}\n\n{body}\n\nBest regards,\n{signature}".strip() + "\n"
    if job.url:
        letter += f"\nRe: {job.title} — {job.url}\n"
    return letter


class CoverLetterService:
    """Writes the letter to disk (docx/md/txt) and returns the rendered text."""

    def generate(self, profile: Profile, job: JobPosting, match: MatchContext | None = None,
                 tone: str | None = None, output_dir: Path | None = None,
                 fmt: str = "docx") -> GeneratedDocument:
        markdown = render_cover_letter(profile, job, match, tone)
        document = GeneratedDocument(
            kind="cover_letter", text=markdown, template=(tone or profile.tone or "professional"),
            used_keywords=list((match.matched_keywords if match else []) or [])[:10])
        if output_dir is not None:
            stem = (f"CoverLetter_{slugify(profile.display_name, 24)}_"
                    f"{slugify(job.company, 18)}_{slugify(job.title, 20)}")
            document.path = export(markdown, Path(output_dir) / f"{stem}.{fmt}", fmt,
                                   title=f"Cover letter – {job.title}")
        return document


def top_keywords_from_job(job: JobPosting, limit: int = 12) -> list[str]:
    """Keywords the matcher/letter can use, tags first."""
    merged = list(job.tags) + keywords(job.description, limit=limit)
    seen, out = set(), []
    for word in merged:
        low = word.lower()
        if low in seen or len(low) < 3:
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= limit:
            break
    return out


__all__ = ["CoverLetterService", "MatchContext", "TONES", "render_cover_letter",
           "top_keywords_from_job", "date"]
