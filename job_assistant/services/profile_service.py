"""Conversions between form values and the structured candidate profile."""
from __future__ import annotations

from job_assistant.models.entities import CandidateProfile


def split_lines(value: str) -> list[str]:
    return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]


def profile_from_form(fields: dict[str, str]) -> CandidateProfile:
    return CandidateProfile(
        full_name=fields.get("full_name", "").strip(), email=fields.get("email", "").strip(),
        phone=fields.get("phone", "").strip(), headline=fields.get("headline", "").strip(),
        summary=fields.get("summary", "").strip(), experience=fields.get("experience", "").strip(),
        education=fields.get("education", "").strip(), qualifications=fields.get("qualifications", "").strip(),
        certifications=fields.get("certifications", "").strip(),
        technical_skills=split_lines(fields.get("technical_skills", "")),
        software_skills=split_lines(fields.get("software_skills", "")),
        industry_experience=split_lines(fields.get("industry_experience", "")),
        management_experience=fields.get("management_experience", "").strip(),
        achievements=fields.get("achievements", "").strip(),
        job_titles=split_lines(fields.get("job_titles", "")),
        years_experience=fields.get("years_experience", "").strip(),
        preferred_locations=split_lines(fields.get("preferred_locations", "")),
        languages=split_lines(fields.get("languages", "")),
        relocation_willingness=fields.get("relocation_willingness", "").strip(),
    )


def form_from_profile(profile: CandidateProfile) -> dict[str, str]:
    values = profile.as_dict()
    for key in ("technical_skills", "software_skills", "industry_experience", "job_titles", "preferred_locations", "languages"):
        values[key] = "\n".join(values[key])
    return {key: str(value) for key, value in values.items()}
