"""End-to-end CLI tests with a fake HTTP layer (no network)."""

import json
import os

import pytest
from click.testing import CliRunner
from conftest import FakeClient, route_greenhouse, write_config_file

from jauto import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Config file + fake HTTP client wired into the CLI."""
    config_path = write_config_file(tmp_path)
    fake = FakeClient()
    route_greenhouse(fake)
    monkeypatch.setattr(cli, "Client", lambda cfg=None: fake)
    return {"config_path": config_path, "tmp_path": tmp_path, "fake": fake}


def _db_path(env):
    return str(env["tmp_path"] / "jauto.db")


def test_init_creates_files(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.main, ["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / "cover_letter_template.txt").exists()
    # second run refuses to overwrite
    result = runner.invoke(cli.main, ["init"])
    assert "already exists" in result.output


def test_init_force_overwrites(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("junk: true")
    result = runner.invoke(cli.main, ["init", "--force"])
    assert result.exit_code == 0
    assert "sources" in (tmp_path / "config.yaml").read_text()


def test_search_scores_and_stores_jobs(runner, cli_env):
    result = runner.invoke(
        cli.main, ["--config", cli_env["config_path"], "search"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    assert "Software Engineer, Backend" in result.output
    assert "Senior Product Manager" not in result.output  # excluded (senior/manager)

    from jauto.db import Store

    store = Store(_db_path(cli_env))
    counts = store.counts()
    assert counts.get("matched", 0) == 2
    assert counts.get("skipped", 0) == 1
    rows = store.jobs(status="matched", order="score")
    assert rows[0]["score"] >= 80
    assert "skills matched" in rows[0]["score_reasons"]


def test_search_all_includes_below_threshold(runner, cli_env):
    result = runner.invoke(
        cli.main, ["--config", cli_env["config_path"], "search", "--all"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0
    assert "Senior Product Manager" in result.output


def test_show_displays_score_breakdown(runner, cli_env):
    runner.invoke(cli.main, ["--config", cli_env["config_path"], "search"])
    result = runner.invoke(cli.main, ["--config", cli_env["config_path"], "show", "1"])
    assert result.exit_code == 0, result.output
    assert "Software Engineer, Backend" in result.output
    assert "Acme Corp" in result.output
    assert "exact title match" in result.output


def test_show_missing_job_fails(runner, cli_env):
    result = runner.invoke(cli.main, ["--config", cli_env["config_path"], "show", "999"])
    assert result.exit_code == 1
    assert "No job with id 999" in result.output


def test_apply_single_job_dry_run_default(runner, cli_env):
    runner.invoke(cli.main, ["--config", cli_env["config_path"], "search"])
    result = runner.invoke(
        cli.main, ["--config", cli_env["config_path"], "apply", "1"]
    )
    assert result.exit_code == 0, result.output
    assert "PREVIEW" in result.output
    assert "jane.doe@example.com" in result.output
    # nothing was submitted
    posts = [r for r in cli_env["fake"].requests if r["method"] == "POST"]
    assert posts == []

    from jauto.db import Store

    store = Store(_db_path(cli_env))
    assert "applied" not in store.counts()


def test_apply_single_job_submits_with_yes(runner, cli_env):
    runner.invoke(cli.main, ["--config", cli_env["config_path"], "search"])
    result = runner.invoke(
        cli.main, ["--config", cli_env["config_path"], "apply", "1", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "APPLIED" in result.output

    posts = [r for r in cli_env["fake"].requests if r["method"] == "POST"]
    assert len(posts) == 1, "application POST must happen exactly once (no retries)"
    form = posts[0]["data"]["form"]
    assert form["first_name"] == "Jane"
    assert form["question_3333"] == 1  # 'Yes' -> option value
    assert form["question_5555"] == "https://www.linkedin.com/in/janedoe"
    files = posts[0]["data"]["files"]
    assert any(f[0] == "resume" for f in files)
    assert "cover_letter_text" in form

    from jauto.db import Store

    store = Store(_db_path(cli_env))
    assert store.counts()["applied"] == 1
    apps = store.recent_applications()
    assert apps[0]["ok"] == 1
    assert apps[0]["method"] == "auto"
    assert json.loads(apps[0]["payload"])["form"]["email"] == "jane.doe@example.com"


def test_apply_auto_dry_run_then_submit(runner, cli_env):
    runner.invoke(cli.main, ["--config", cli_env["config_path"], "search"])

    dry = runner.invoke(
        cli.main, ["--config", cli_env["config_path"], "apply", "--auto"]
    )
    assert dry.exit_code == 0, dry.output
    assert "PREVIEW" in dry.output
    assert "APPLIED" not in dry.output
    assert "NEEDS_REVIEW" in dry.output  # job 3 has an unmapped required question

    wet = runner.invoke(
        cli.main, ["--config", cli_env["config_path"], "apply", "--auto", "--yes"]
    )
    assert wet.exit_code == 0, wet.output
    assert "APPLIED" in wet.output
    # job 3 was flagged needs_review by the dry run, so the wet run must NOT
    # retry it — it waits for human attention
    assert "NEEDS_REVIEW" not in wet.output
    assert "1 applied" in wet.output

    from jauto.db import Store

    store = Store(_db_path(cli_env))
    counts = store.counts()
    assert counts["applied"] == 1
    assert counts["needs_review"] == 1


def test_run_previews_without_yes(runner, cli_env):
    result = runner.invoke(cli.main, ["--config", cli_env["config_path"], "run"])
    assert result.exit_code == 0, result.output
    assert "preview only" in result.output
    posts = [r for r in cli_env["fake"].requests if r["method"] == "POST"]
    assert posts == []


def test_status_after_activity(runner, cli_env):
    runner.invoke(cli.main, ["--config", cli_env["config_path"], "search"])
    runner.invoke(cli.main, ["--config", cli_env["config_path"], "apply", "1", "--yes"])
    result = runner.invoke(cli.main, ["--config", cli_env["config_path"], "status"])
    assert result.exit_code == 0, result.output
    assert "applied" in result.output
    assert "Acme Corp" in result.output


def test_check_reports_profile_problems(runner, cli_env, tmp_path):
    # break the resume reference in the config
    with open(cli_env["config_path"], "r", encoding="utf-8") as fh:
        raw = fh.read()
    raw = raw.replace("resume.pdf", "missing.pdf")
    with open(cli_env["config_path"], "w", encoding="utf-8") as fh:
        fh.write(raw)
    result = runner.invoke(cli.main, ["--config", cli_env["config_path"], "check"])
    assert result.exit_code == 1
    assert "Resume not found" in result.output


def test_add_writes_board_to_config(runner, cli_env, monkeypatch):
    monkeypatch.chdir(cli_env["tmp_path"])
    result = runner.invoke(
        cli.main,
        ["--config", cli_env["config_path"], "add",
         "https://boards.greenhouse.io/newco", "--no-check"],
    )
    assert result.exit_code == 0, result.output
    with open(cli_env["config_path"], encoding="utf-8") as fh:
        content = fh.read()
    assert "newco" in content
    # adding again is a no-op
    result = runner.invoke(
        cli.main,
        ["--config", cli_env["config_path"], "add",
         "https://boards.greenhouse.io/newco", "--no-check"],
    )
    assert "already" in result.output


def test_add_unrecognised_url_fails(runner, cli_env):
    result = runner.invoke(
        cli.main,
        ["--config", cli_env["config_path"], "add", "https://example.com", "--no-check"],
    )
    assert result.exit_code == 1
    assert "Could not detect" in result.output
