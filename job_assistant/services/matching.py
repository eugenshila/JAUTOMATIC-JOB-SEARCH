"""Deterministic, explainable first matching engine.

A future semantic provider can be plugged in beside this baseline. This engine
never claims that a requirement is met unless there is evidence in the saved
candidate profile.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from job_assistant.job_sources.base import JobRecord
from job_assistant.models.entities import CandidateProfile

COMMON_REQUIREMENTS = {
    "sql", "power bi", "excel", "sap", "erp", "python", "tableau", "inventory management",
    "supply chain", "procurement", "logistics", "warehouse", "forecasting", "data analysis",
    "project management", "customer service", "driving licence", "bachelor's degree", "master's degree",
}


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _has_phrase(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()


def match_job(profile: CandidateProfile, job: JobRecord | dict[str, Any], *, thresholds: dict[str, int] | None = None) -> dict[str, Any]:
    if isinstance(job, dict):
        title = str(job.get("title", ""))
        location = str(job.get("location", ""))
        description = str(job.get("description", ""))
    else:
        title, location, description = job.title, job.location, job.description
    text = f"{title}\n{description}"
    candidate_title_text = " ".join(profile.job_titles)
    candidate_skill_values = profile.technical_skills + profile.software_skills + profile.industry_experience
    candidate_skills = [item.strip() for item in candidate_skill_values if item.strip()]
    matched = [skill for skill in candidate_skills if _has_phrase(text, skill)]
    required_phrases = [phrase for phrase in COMMON_REQUIREMENTS if _has_phrase(text, phrase)]
    missing = [phrase for phrase in required_phrases if not _has_phrase(" ".join(candidate_skills + [profile.education, profile.qualifications, profile.certifications]), phrase)]
    preferred = [phrase for phrase in missing if not re.search(rf"(?:required|must|essential|minimum)\W{{0,30}}{re.escape(phrase)}", text, re.I)]
    mandatory_missing = [phrase for phrase in missing if phrase not in preferred]

    title_score = SequenceMatcher(None, " ".join(sorted(_tokens(title))), " ".join(sorted(_tokens(candidate_title_text)))).ratio() * 100 if candidate_title_text else 35
    skill_score = (len(matched) / max(1, len(candidate_skills))) * 100 if candidate_skills else 0
    location_score = 100 if not profile.preferred_locations else (100 if any(_has_phrase(location, item) for item in profile.preferred_locations) else 35)
    experience_score = 75 if profile.years_experience and re.search(r"\d", description) else 45
    evidence_score = 100 if any(_has_phrase(text, item) for item in profile.industry_experience) else 35
    score = round((title_score * 0.20) + (skill_score * 0.35) + (experience_score * 0.15) + (evidence_score * 0.15) + (location_score * 0.15), 1)
    score -= min(20, len(mandatory_missing) * 8)
    score = max(0, min(100, score))
    thresholds = thresholds or {"priority_threshold": 85, "auto_prepare_threshold": 75, "minimum_match_threshold": 65}
    category = "Excellent Match" if score >= 90 else "Strong Match" if score >= 80 else "Good Match" if score >= 70 else "Possible Match" if score >= 60 else "Low Match"
    recommendation = "APPLY" if score >= thresholds["priority_threshold"] and not mandatory_missing else "CONSIDER" if score >= thresholds["minimum_match_threshold"] else "SKIP"
    reasons = []
    if matched:
        reasons.append(f"Matched evidence: {', '.join(matched[:5])}")
    if profile.industry_experience and evidence_score >= 100:
        reasons.append("Industry experience appears in the vacancy description")
    if location_score >= 100:
        reasons.append("Location matches a preferred market")
    if mandatory_missing:
        reasons.append(f"Mandatory requirement not evidenced in the profile: {', '.join(mandatory_missing)}")
    if preferred:
        reasons.append(f"Preferred skill not evidenced: {', '.join(preferred)}")
    if not reasons:
        reasons.append("Limited evidence was found in the current profile")
    return {
        "score": score,
        "category": category,
        "matched": matched,
        "missing": mandatory_missing,
        "preferred": preferred,
        "reasons": reasons,
        "recommendation": recommendation,
    }
