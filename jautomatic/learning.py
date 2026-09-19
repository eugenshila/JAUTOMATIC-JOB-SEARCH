"""Local learning-course and certificate records."""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

CATEGORIES = ("Supply Chain & Logistics", "AI", "Business Management", "Ecommerce", "Customer Care")
STATUSES = ("Planned", "In Progress", "Completed")
ALLOWED_CERTIFICATE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_CERTIFICATE_BYTES = 15 * 1024 * 1024

@dataclass
class LearningCourse:
    title: str
    provider: str
    url: str
    category: str
    description: str = ""
    level: str = ""
    duration: str = ""
    certificate_status: str = "Unknown"
    status: str = "Planned"
    completed_on: str = ""
    certificate_path: str = ""
    certificate_id: str = ""
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"Unsupported learning category: {self.category}")
        if self.status not in STATUSES:
            raise ValueError(f"Unsupported learning status: {self.status}")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Course URL must be an http(s) URL")

    @property
    def completed(self) -> bool:
        return self.status == "Completed"

    def mark_completed(self, completed_on: str | None = None) -> None:
        value = completed_on or date.today().isoformat()
        date.fromisoformat(value)
        self.status = "Completed"
        self.completed_on = value

class LearningStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / "learning.json"
        self.certificates_dir = self.root / "certificates"
        self.courses: list[LearningCourse] = []
        self.load()

    def load(self) -> list[LearningCourse]:
        if not self.path.exists():
            self.courses = []
            return self.courses
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.courses = [LearningCourse(**item) for item in raw if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            self.courses = []
        return self.courses

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps([asdict(c) for c in self.courses], indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def add(self, course: LearningCourse) -> LearningCourse:
        if any(c.url == course.url for c in self.courses):
            raise ValueError("This course is already saved")
        self.courses.append(course)
        self.save()
        return course

    def update(self, course: LearningCourse) -> None:
        for index, existing in enumerate(self.courses):
            if existing.id == course.id:
                self.courses[index] = course
                self.save()
                return
        raise KeyError(course.id)

    def attach_certificate(self, course_id: str, source: str | Path) -> Path:
        course = next((c for c in self.courses if c.id == course_id), None)
        if course is None:
            raise KeyError(course_id)
        source_path = Path(source)
        if source_path.suffix.lower() not in ALLOWED_CERTIFICATE_SUFFIXES:
            raise ValueError("Certificate must be PDF, JPG, JPEG, or PNG")
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if source_path.stat().st_size > MAX_CERTIFICATE_BYTES:
            raise ValueError("Certificate exceeds the 15 MB limit")
        self.certificates_dir.mkdir(parents=True, exist_ok=True)
        destination = self.certificates_dir / f"{course.id}{source_path.suffix.lower()}"
        shutil.copy2(source_path, destination)
        course.certificate_path = str(destination)
        course.mark_completed(course.completed_on or None)
        self.update(course)
        return destination

    def completed_courses(self) -> list[LearningCourse]:
        return [course for course in self.courses if course.completed]
