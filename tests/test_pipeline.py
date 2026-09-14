"""Pipeline integration tests (offline)."""

import pytest
from conftest import FakeClient, make_config, route_greenhouse

from jauto.db import Store
from jauto.pipeline import Pipeline


def _pipeline(tmp_path, client, **config_overrides):
    config = make_config(tmp_path, **config_overrides)
    store = Store(config.db_file)
    return Pipeline(config, store, client=client), store, config


def test_search_fetches_matches_and_fetches_descriptions(tmp_path):
    client = FakeClient()
    route_greenhouse(client)
    pipeline, store, _ = _pipeline(tmp_path, client)

    stats = pipeline.search()
    assert stats.errors == {}
    assert stats.boards == {"greenhouse/acme": 3}
    assert stats.new_jobs == 3
    assert stats.matched == 2  # engineer + backend platform
    assert stats.skipped == 1  # senior product manager (excluded title)
    assert stats.descriptions_fetched >= 1

    rows = store.jobs(status="matched", order="score")
    titles = {r["title"] for r in rows}
    assert titles == {"Software Engineer, Backend", "Backend Engineer (Platform)"}
    top = rows[0]
    assert top["description_text"]  # detail fetched
    assert top["score"] >= 80


def test_search_is_idempotent(tmp_path):
    client = FakeClient()
    route_greenhouse(client)
    pipeline, store, _ = _pipeline(tmp_path, client)
    pipeline.search()
    first_counts = store.counts()
    pipeline.search()
    # no duplicates: same three rows, statuses preserved
    assert store.counts() == first_counts
    assert len(store.jobs()) == 3
    assert store.jobs()[0]["seen_count"] == 2


def test_company_blacklist_skips_everything(tmp_path):
    client = FakeClient()
    route_greenhouse(client)
    pipeline, store, _ = _pipeline(
        tmp_path, client,
    )
    pipeline.config.matching.company_blacklist = ["acme"]
    stats = pipeline.search()
    assert stats.matched == 0
    assert stats.skipped == 3
    assert all(r["status"] == "skipped" for r in store.jobs())


def test_search_records_board_errors_without_crashing(tmp_path):
    client = FakeClient()
    client.add(
        "GET",
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        RuntimeError("board unavailable"),
    )
    pipeline, store, _ = _pipeline(tmp_path, client)
    stats = pipeline.search()
    assert "greenhouse/acme" in stats.errors
    assert store.counts() == {}
    assert store.get_meta("last_search_at")  # still recorded


def test_auto_apply_respects_min_score(tmp_path):
    client = FakeClient()
    route_greenhouse(client)
    pipeline, store, _ = _pipeline(tmp_path, client)
    pipeline.search()
    # job 1 scores ~100, job 3 ~83 -> only job 1 clears 99.5
    results = pipeline.auto_apply(dry_run=True, min_score=99.5)
    assert len(results) == 1
    assert results[0].status == "dry_run"
    # both clear 50
    results = pipeline.auto_apply(dry_run=True, min_score=50)
    assert len(results) == 2


def test_auto_apply_submits_and_marks_status(tmp_path):
    client = FakeClient()
    route_greenhouse(client)
    pipeline, store, _ = _pipeline(tmp_path, client)
    pipeline.search()
    results = pipeline.auto_apply(dry_run=False)
    statuses = [r.status for r in results]
    # job 1: applied; job 3: needs review (unmapped required custom question)
    assert "applied" in statuses
    assert "needs_review" in statuses
    counts = store.counts()
    assert counts["applied"] == 1
    assert counts["needs_review"] == 1
    posts = [r for r in client.requests if r["method"] == "POST"]
    assert len(posts) == 1
