"""Unit tests for the matching engine."""

from datetime import datetime, timedelta, timezone

from jauto.config import MatchingConfig
from jauto.matcher import Matcher
from jauto.models import Job


def _job(**kwargs) -> Job:
    defaults = dict(
        provider="greenhouse",
        provider_board="acme",
        provider_job_id="1",
        company="Acme Corp",
        title="Software Engineer",
        location="Remote - US",
        remote=True,
        description_text="We use Python, AWS and Docker.",
        published_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    defaults.update(kwargs)
    return Job(**defaults)


def _cfg(**kwargs) -> MatchingConfig:
    defaults = dict(
        titles=["software engineer"],
        skills=["python", "aws"],
        exclude_titles=["senior", "manager"],
        locations=["remote"],
        threshold=50.0,
    )
    defaults.update(kwargs)
    return MatchingConfig(**defaults)


def test_perfect_match_scores_100():
    result = Matcher(_cfg()).score(_job())
    assert result.score == 100.0
    assert not result.excluded
    assert set(result.matched_skills) == {"python", "aws"}


def test_exclude_title():
    result = Matcher(_cfg()).score(_job(title="Senior Software Engineer"))
    assert result.excluded
    assert "senior" in result.excluded_reason
    assert result.score == 0.0


def test_exclude_company_blacklist():
    result = Matcher(_cfg(company_blacklist=["evil corp"])).score(_job(company="Evil Corp Inc"))
    assert result.excluded
    assert "blacklisted" in result.excluded_reason


def test_partial_title_match_scores_lower():
    result = Matcher(_cfg()).score(_job(title="Engineer, Site Reliability"))
    assert result.score < 100.0
    assert any("partial title" in r for r in result.reasons)


def test_skills_partial():
    result = Matcher(_cfg()).score(_job(description_text="We use Python."))
    assert result.matched_skills == ["python"]
    assert result.score < 100.0


def test_special_skill_tokens():
    cfg = _cfg(skills=["c++", "python"])
    result = Matcher(cfg).score(_job(description_text="Requires C++ and python."))
    assert set(result.matched_skills) == {"c++", "python"}


def test_remote_only_rejects_onsite():
    result = Matcher(_cfg(remote_only=True)).score(
        _job(remote=False, location="Berlin, Germany")
    )
    assert result.excluded
    assert result.score == 0.0
    assert any("remote_only" in r for r in result.reasons)


def test_remote_only_accepts_listed_location():
    cfg = _cfg(remote_only=True, locations=["nairobi", "remote"])
    result = Matcher(cfg).score(_job(remote=False, location="Nairobi, Kenya"))
    assert not result.excluded
    assert result.score == 100.0  # location override + perfect everything else


def test_location_mismatch_penalises():
    result = Matcher(_cfg(locations=["nairobi"])).score(
        _job(remote=False, location="Berlin, Germany")
    )
    # location component is zeroed, but the job is not hard-excluded
    assert not result.excluded
    assert result.score < 100.0
    assert any("location mismatch" in r for r in result.reasons)


def test_freshness_decay():
    old = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh = _job(published_at=old)
    result = Matcher(_cfg()).score(fresh)
    assert result.score < 100.0
    assert any("days ago" in r for r in result.reasons)


def test_no_publish_date_is_neutral():
    result = Matcher(_cfg()).score(_job(published_at=None))
    assert 50.0 <= result.score < 100.0
    assert any("no publish date" in r for r in result.reasons)


def test_no_filters_are_neutral():
    cfg = _cfg(titles=[], skills=[], locations=[])
    result = Matcher(cfg).score(_job())
    # title/skills neutral = 0.5 of their weight; location unfiltered = full
    assert result.score == 65.0


def test_threshold_classification_is_callers_job():
    # scores below threshold still return the score; pipeline decides status
    result = Matcher(_cfg()).score(
        _job(title="Chef", location="Paris, France", remote=False, description_text="")
    )
    assert result.score < 50.0
