from __future__ import annotations

from unittest.mock import Mock, patch

from jautomatic.services.learning_search import search_courses


class Response:
    def __init__(self, html: str) -> None:
        self.text = html

    def raise_for_status(self) -> None:
        return None


def test_search_returns_matching_courses_and_never_claims_unknown_certificate_is_free() -> None:
    html = '<a href="/course/supply">Free Supply Chain Course</a>'
    response = Response(html)

    with patch("jautomatic.services.learning_search.requests.get", return_value=response):
        results = search_courses("Supply Chain & Logistics", limit=5)

    assert results
    assert results[0].title == "Free Supply Chain Course"
    assert "does not guarantee" in results[0].certificate_status


def test_search_ignores_source_errors() -> None:
    with patch("jautomatic.services.learning_search.requests.get", side_effect=OSError("offline")):
        assert search_courses("AI", limit=5) == []
