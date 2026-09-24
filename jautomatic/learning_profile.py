"""Formatting helpers for completed learning in profile documents."""
from __future__ import annotations

from collections.abc import Iterable

from .learning import LearningCourse


def completed_learning_lines(courses: Iterable[LearningCourse]) -> list[str]:
    """Return stable, human-readable CV lines for completed courses only."""
    lines: list[str] = []
    for course in courses:
        if not course.completed:
            continue
        line = f"{course.title} — {course.provider}"
        if course.completed_on:
            line += f" ({course.completed_on})"
        if course.certificate_id:
            line += f" · Certificate: {course.certificate_id}"
        lines.append(line)
    return lines
