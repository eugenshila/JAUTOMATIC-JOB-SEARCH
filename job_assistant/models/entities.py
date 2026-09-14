"""Small typed value objects shared by the application layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CandidateProfile:
    full_name: str = ""
    email: str = ""
    phone: str = ""
    headline: str = ""
    summary: str = ""
    experience: str = ""
    education: str = ""
    qualifications: str = ""
    certifications: str = ""
    technical_skills: list[str] = field(default_factory=list)
    software_skills: list[str] = field(default_factory=list)
    industry_experience: list[str] = field(default_factory=list)
    management_experience: str = ""
    achievements: str = ""
    job_titles: list[str] = field(default_factory=list)
    years_experience: str = ""
    preferred_locations: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    relocation_willingness: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "headline": self.headline,
            "summary": self.summary,
            "experience": self.experience,
            "education": self.education,
            "qualifications": self.qualifications,
            "certifications": self.certifications,
            "technical_skills": self.technical_skills,
            "software_skills": self.software_skills,
            "industry_experience": self.industry_experience,
            "management_experience": self.management_experience,
            "achievements": self.achievements,
            "job_titles": self.job_titles,
            "years_experience": self.years_experience,
            "preferred_locations": self.preferred_locations,
            "languages": self.languages,
            "relocation_willingness": self.relocation_willingness,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "CandidateProfile":
        value = value or {}
        result = cls()
        for key in result.as_dict():
            if key in value:
                setattr(result, key, value[key])
        return result
