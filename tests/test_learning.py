from __future__ import annotations

from pathlib import Path

import pytest

from jautomatic.learning import LearningCourse, LearningStore


def course() -> LearningCourse:
    return LearningCourse(
        title="Introduction to Supply Chain",
        provider="Example provider",
        url="https://example.com/course",
        category="Supply Chain & Logistics",
    )


def test_course_store_round_trip(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    saved = store.add(course())
    reloaded = LearningStore(tmp_path)
    assert reloaded.courses[0].id == saved.id
    assert reloaded.courses[0].title == saved.title


def test_certificate_marks_course_completed_and_copies_file(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    saved = store.add(course())
    source = tmp_path / "certificate.pdf"
    source.write_bytes(b"certificate")

    destination = store.attach_certificate(saved.id, source)

    assert destination.exists()
    assert destination.read_bytes() == b"certificate"
    assert store.courses[0].completed
    assert store.courses[0].certificate_path == str(destination)


def test_certificate_rejects_unsupported_file(tmp_path: Path) -> None:
    store = LearningStore(tmp_path)
    saved = store.add(course())
    source = tmp_path / "certificate.exe"
    source.write_bytes(b"not a certificate")

    with pytest.raises(ValueError, match="PDF"):
        store.attach_certificate(saved.id, source)
