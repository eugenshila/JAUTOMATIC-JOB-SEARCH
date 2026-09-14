"""Unit tests for the SQLite store."""

import pytest

from jauto.db import Store
from jauto.models import Job


def _job(**kwargs) -> Job:
    defaults = dict(
        provider="greenhouse",
        provider_board="acme",
        provider_job_id="900001",
        company="Acme Corp",
        title="Software Engineer",
        location="Remote - US",
        remote=True,
        published_at="2026-09-12T11:00:00+00:00",
    )
    defaults.update(kwargs)
    return Job(**defaults)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


def test_upsert_new_job(store):
    row = store.upsert_job(_job(), 85.0, ["+ matched"], "matched")
    assert row["status"] == "matched"
    assert row["score"] == 85.0
    assert row["seen_count"] == 1


def test_upsert_is_idempotent_and_counts_sightings(store):
    store.upsert_job(_job(), 85.0, [], "matched")
    row = store.upsert_job(_job(), 90.0, [], "matched")
    assert row["seen_count"] == 2
    assert row["score"] == 90.0


def test_dedupe_key_merges_same_job(store):
    store.upsert_job(_job(), 80.0, [], "matched")
    store.upsert_job(_job(provider="lever", provider_board="acme", provider_job_id="x"), 70.0, [], "matched")
    rows = store.jobs()
    assert len(rows) == 1  # same company+title+location -> one row


def test_user_statuses_survive_research(store):
    row = store.upsert_job(_job(), 80.0, [], "matched")
    store.set_status(row["id"], "applied")
    updated = store.upsert_job(_job(), 10.0, [], "skipped")
    assert updated["status"] == "applied"  # not clobbered


def test_new_status_upgrades_from_new(store):
    row = store.upsert_job(_job(), 80.0, [], None)
    assert row["status"] == "new"
    row = store.upsert_job(_job(), 80.0, [], "matched")
    assert row["status"] == "matched"


def test_filters(store):
    store.upsert_job(_job(), 80.0, [], "matched")
    store.upsert_job(_job(provider_job_id="2", title="Chef"), 20.0, [], "skipped")
    assert len(store.jobs(status="matched")) == 1
    assert len(store.jobs(min_score=50)) == 1
    assert len(store.jobs()) == 2


def test_applications_and_daily_count(store):
    row = store.upsert_job(_job(), 80.0, [], "matched")
    store.record_application(row["id"], "auto", "http://x", {"email": "a@b.c"}, True, 200, "ok")
    store.record_application(row["id"], "dry", "http://x", {}, True, None, "dry run")
    assert store.applied_count_since("2000-01-01T00:00:00Z") == 1  # only auto+ok
    assert store.applied_count_since("2999-01-01T00:00:00Z") == 0
    recent = store.recent_applications()
    assert len(recent) == 2
    assert recent[0]["company"] == "Acme Corp"


def test_meta_roundtrip(store):
    store.set_meta("last_search_at", "2026-09-14T00:00:00Z")
    assert store.get_meta("last_search_at") == "2026-09-14T00:00:00Z"
    assert store.get_meta("missing") is None
    store.set_meta("last_search_at", "later")
    assert store.get_meta("last_search_at") == "later"
