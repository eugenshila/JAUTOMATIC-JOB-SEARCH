"""Rule-based matching engine: score a Job against the user's profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

from .config import MatchingConfig
from .models import Job, normalize, parse_iso
from .text import token_present

FRESH_WINDOW_DAYS = 7      # full freshness points inside this window
FRESH_DECAY_DAYS = 28      # linear decay to 0.2 floor over this many days
FRESH_FLOOR = 0.2
NEUTRAL = 0.5


@dataclass
class MatchResult:
    score: float  # 0..100
    excluded: bool = False
    excluded_reason: str = ""
    matched_skills: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    @property
    def passed_reasons(self) -> List[str]:
        return self.reasons


class Matcher:
    def __init__(self, cfg: MatchingConfig):
        self.cfg = cfg
        total = sum(cfg.weights.values()) or 1.0
        self.weights = {k: v / total for k, v in cfg.weights.items()}

    # ------------------------------------------------------------------
    def score(self, job: Job) -> MatchResult:
        cfg = self.cfg

        # --- hard exclusions first -------------------------------------
        for token in cfg.exclude_titles:
            if token_present(token, job.title):
                return MatchResult(
                    0.0,
                    excluded=True,
                    excluded_reason=f"title contains excluded term {token!r}",
                    reasons=[f"excluded: title contains {token!r}"],
                )
        for bad in cfg.company_blacklist:
            if normalize(bad) and normalize(bad) in normalize(job.company):
                return MatchResult(
                    0.0,
                    excluded=True,
                    excluded_reason=f"company is blacklisted ({job.company})",
                    reasons=[f"excluded: company {job.company!r} is blacklisted"],
                )
        wanted_locations = [normalize(l) for l in cfg.locations if l and l.strip()]
        if cfg.remote_only and not job.remote and not any(
            w in normalize(job.location) for w in wanted_locations
        ):
            return MatchResult(
                0.0,
                excluded=True,
                excluded_reason="not remote (you asked for remote only)",
                reasons=["excluded: not a remote role (remote_only is set)"],
            )

        reasons: List[str] = []
        title_score = self._title_component(job, reasons)
        skills_score, matched_skills = self._skills_component(job, reasons)
        location_score = self._location_component(job, reasons)
        fresh_score = self._freshness_component(job, reasons)

        total = 100.0 * (
            self.weights.get("title", 0) * title_score
            + self.weights.get("skills", 0) * skills_score
            + self.weights.get("location", 0) * location_score
            + self.weights.get("freshness", 0) * fresh_score
        )
        return MatchResult(round(total, 1), matched_skills=matched_skills, reasons=reasons)

    # ------------------------------------------------------------------
    def _title_component(self, job: Job, reasons: List[str]) -> float:
        titles = [t for t in self.cfg.titles if t and t.strip()]
        if not titles:
            reasons.append("~ no title keywords configured")
            return NEUTRAL
        best, best_phrase = 0.0, ""
        for phrase in titles:
            phrase = phrase.strip()
            if token_present(phrase, job.title):
                best, best_phrase = 1.0, phrase
                break
            words = [w for w in phrase.split() if w]
            if not words:
                continue
            hits = sum(1 for w in words if token_present(w, job.title))
            overlap = hits / len(words)
            if overlap > best:
                best, best_phrase = overlap, phrase
        if best >= 1.0:
            reasons.append(f"+ exact title match: {best_phrase!r}")
        elif best > 0:
            reasons.append(f"~ partial title match: {best_phrase!r} ({int(best * 100)}%)")
        else:
            reasons.append("- title does not match any of your titles")
        return best

    def _skills_component(self, job: Job, reasons: List[str]):
        skills = [s for s in self.cfg.skills if s and s.strip()]
        if not skills:
            reasons.append("~ no skills configured")
            return NEUTRAL, []
        text = job.search_text
        if not job.description_text:
            matched = [s for s in skills if token_present(s, job.title)]
            if matched:
                reasons.append(
                    f"+ skills in title only (no description fetched): {', '.join(matched)}"
                )
            else:
                reasons.append("- no description fetched; no skill matches in title")
            return len(matched) / len(skills), matched
        matched = [s for s in skills if token_present(s, text)]
        if matched:
            reasons.append(
                f"+ skills matched ({len(matched)}/{len(skills)}): {', '.join(matched)}"
            )
        else:
            reasons.append(f"- none of your {len(skills)} skills appear in the posting")
        return len(matched) / len(skills), matched

    def _location_component(self, job: Job, reasons: List[str]) -> float:
        cfg = self.cfg
        wanted = [normalize(l) for l in cfg.locations if l and l.strip()]
        loc = normalize(job.location)
        if cfg.remote_only:
            # non-remote jobs matching a listed location were already allowed
            # by the exclusion step; score them at full location points
            reasons.append(f"+ location match: {job.location}")
            return 1.0
        if not wanted:
            reasons.append("~ no location filter configured")
            return 1.0
        if any(w in loc for w in wanted) or (job.remote and "remote" in wanted):
            reasons.append(f"+ location match: {job.location}")
            return 1.0
        if job.remote:
            reasons.append("~ remote role, but location is outside your list")
            return NEUTRAL + 0.1  # 0.6 — remote is usually still interesting
        reasons.append(f"- location mismatch: {job.location}")
        return 0.0

    def _freshness_component(self, job: Job, reasons: List[str]) -> float:
        published = parse_iso(job.published_at)
        if published is None:
            reasons.append("~ no publish date available")
            return NEUTRAL
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - published).total_seconds() / 86400.0
        if age_days <= FRESH_WINDOW_DAYS:
            reasons.append(f"+ posted {max(int(age_days), 0)} day(s) ago")
            return 1.0
        if age_days <= FRESH_WINDOW_DAYS + FRESH_DECAY_DAYS:
            score = 1.0 - (age_days - FRESH_WINDOW_DAYS) / FRESH_DECAY_DAYS * (
                1.0 - FRESH_FLOOR
            )
            reasons.append(f"~ posted {int(age_days)} days ago")
            return max(score, FRESH_FLOOR)
        reasons.append(f"- posted {int(age_days)} days ago (stale)")
        return FRESH_FLOOR
