from __future__ import annotations

from pathlib import Path
import pytest
from jautomatic.learning import LearningCourse, LearningStore

def make_course() -> LearningCourse:
    return LearningCourse("Introduction to Supply Chain", "Example", "https://example.com/course", "Supply Chain & Logistics")

def test_store_round_trip(tmp_path: Path) -> None:
    saved = LearningStore(tmp_path).add(make_course())
    reloaded = LearningStore(tmp_path)
    assert reloaded.courses[0].id == saved.id

def test_certificate_completes_course(tmp_path: Path) -> None:
    store = LearningStore(tmp_path); saved = store.add(make_course()); source = tmp_path / "certificate.pdf"; source.write_bytes(b"certificate")
    destination = store.attach_certificate(saved.id, source)
    assert destination.exists() and store.courses[0].completed

def test_certificate_extension_is_validated(tmp_path: Path) -> None:
    store = LearningStore(tmp_path); saved = store.add(make_course()); source = tmp_path / "certificate.exe"; source.write_bytes(b"bad")
    with pytest.raises(ValueError): store.attach_certificate(saved.id, source)
