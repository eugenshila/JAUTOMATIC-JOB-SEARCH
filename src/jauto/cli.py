"""Command line interface (click + rich)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table as RichTable
from rich.text import Text

from . import __version__
from .config import Config, ConfigError, add_source, load_config
from .db import Store
from .net import Client
from .pipeline import Pipeline
from .providers import detect_from_url
from .text import truncate

console = Console()
err_console = Console(stderr=True)


# ----------------------------------------------------------------------
# setup helpers
# ----------------------------------------------------------------------
class App:
    def __init__(self, config: Config, store: Store, pipeline: Pipeline):
        self.config = config
        self.store = store
        self.pipeline = pipeline


def _build_app(config_path: str, db_override: Optional[str]) -> App:
    config = load_config(config_path)
    db_path = db_override or config.db_file
    store = Store(db_path)
    client = Client(config.network)
    pipeline = Pipeline(config, store, client=client)
    return App(config, store, pipeline)


def _fail(message: str) -> None:
    err_console.print(f"[red]error:[/red] {message}")
    raise SystemExit(1)


def _load(ctx: click.Context) -> App:
    if "app" not in ctx.obj:
        try:
            ctx.obj["app"] = _build_app(ctx.obj["config_path"], ctx.obj["db_path"])
        except ConfigError as exc:
            _fail(str(exc))
    return ctx.obj["app"]


# ----------------------------------------------------------------------
# CLI group
# ----------------------------------------------------------------------
@click.group()
@click.version_option(__version__, prog_name="jauto")
@click.option(
    "--config",
    "config_path",
    envvar="JAUTO_CONFIG",
    default="config.yaml",
    show_default=True,
    help="Path to config.yaml",
)
@click.option("--db", "db_path", default=None, help="Override the database path")
@click.pass_context
def main(ctx: click.Context, config_path: str, db_path: Optional[str]) -> None:
    """jauto — automatic job search & apply for ATS career pages.

    Typical flow:

      jauto init              # create config.yaml + cover letter template

      jauto add <careers-url> # track a company board

      jauto search            # fetch, score & store openings

      jauto apply --auto      # preview (and with --yes, submit) applications
    """
    ctx.obj = {"config_path": config_path, "db_path": db_path}


# ----------------------------------------------------------------------
# init
# ----------------------------------------------------------------------
_CONFIG_TEMPLATE = """\
# jauto configuration
# Everything here is yours — keep this file private (it is gitignored).

sources:
  # Add boards with:  jauto add https://boards.greenhouse.io/acme
  greenhouse: []
  lever: []
  ashby: []
  smartrecruiters: []
  workable: []

profile:
  first_name: ""
  last_name: ""
  email: ""
  phone: ""
  location: "Nairobi, Kenya"
  resume_path: "resume.pdf"          # uploaded where the form accepts files
  resume_text_path: "resume.txt"     # plain-text fallback
  cover_letter_template: "cover_letter_template.txt"
  # cover_letter_path: "cover_letter.pdf"   # attach a file instead of text
  years_experience: "3"
  links:
    linkedin: ""
    github: ""
    portfolio: ""

matching:
  titles: [software engineer, backend engineer]
  skills: [python, sql, aws, docker]
  exclude_titles: [senior, staff, principal, manager, lead]
  # company_blacklist: [acme]
  locations: [remote, nairobi, kenya]
  remote_only: false
  threshold: 50            # 0-100, minimum score to be flagged 'matched'
  weights:
    title: 35
    skills: 35
    location: 20
    freshness: 10

apply:
  min_score: 60            # auto-apply only to jobs scoring at least this
  max_per_run: 10
  daily_limit: 15
  submit_delay: 5          # seconds between real submissions
  auto_submit: false       # if true, `jauto run` submits without --yes
  require_resume: true
  consent_gdpr: false      # auto-answer GDPR consent questions (only if you consent!)
  # Answers for custom form questions, matched by label (substring, case-insensitive)
  answers:
    # "How many years of experience do you have?": "3"
    # "Are you legally authorized to work": "Yes"
    # "Will you now or in the future require sponsorship": "Yes"
  # EEO / demographic answers, matched by question label then option label
  eeo_answers:
    # gender: "Prefer not to say"
    # race: "Prefer not to say"
  lever_apply_key: ""      # required for Lever auto-apply (experimental)

network:
  request_delay: 1.0       # seconds between requests — keep this polite
  timeout: 20
  retries: 2
  max_description_fetches: 60
  contact_email: ""        # goes into the User-Agent; boards can reach you

db_path: jauto.db
"""

_COVER_LETTER_TEMPLATE = """\
Dear {company} hiring team,

I'm applying for the {title} position. With hands-on experience in {skills},
I believe I'd be a strong fit for the role.

I'd love to discuss how I can contribute to your team.

Best regards,
{name}
"""


@main.command()
@click.option("--force", is_flag=True, help="Overwrite existing files")
def init(force: bool) -> None:
    """Create a starter config.yaml and cover letter template."""
    written: List[str] = []
    for filename, content in (
        ("config.yaml", _CONFIG_TEMPLATE),
        ("cover_letter_template.txt", _COVER_LETTER_TEMPLATE),
    ):
        if os.path.exists(filename) and not force:
            err_console.print(f"[yellow]skip[/yellow] {filename} already exists (use --force)")
            continue
        with open(filename, "w", encoding="utf-8") as fh:
            fh.write(content)
        written.append(filename)
    if written:
        console.print(f"[green]Created:[/green] {', '.join(written)}")
    console.print(
        "\nNext steps:\n"
        "  1. Edit [bold]config.yaml[/bold] — fill in your profile, skills and boards\n"
        "  2. [bold]jauto add <careers-url>[/bold] to track companies\n"
        "  3. [bold]jauto search[/bold] to fetch & score jobs\n"
        "  4. [bold]jauto apply --auto[/bold] to preview applications"
    )


# ----------------------------------------------------------------------
# add
# ----------------------------------------------------------------------
@main.command("add")
@click.argument("url")
@click.option("--no-check", is_flag=True, help="Skip the connectivity check")
@click.pass_context
def add(ctx: click.Context, url: str, no_check: bool) -> None:
    """Add a company board from a careers URL.

    Recognises Greenhouse, Lever, Ashby, SmartRecruiters and Workable URLs,
    e.g. https://boards.greenhouse.io/acme
    """
    detected = detect_from_url(url)
    if detected is None:
        _fail(
            "Could not detect the ATS from that URL. Supported patterns:\n"
            "  boards.greenhouse.io/{board}   job-boards.greenhouse.io/{board}\n"
            "  jobs.lever.co/{board}          jobs.ashbyhq.com/{board}\n"
            "  careers.smartrecruiters.com/{board}\n"
            "  {board}.workable.com           apply.workable.com/{board}"
        )
    provider, board = detected
    config_path = ctx.obj["config_path"]
    if not os.path.exists(config_path):
        _fail(f"{config_path} not found — run `jauto init` first")

    app: Optional[App] = None
    if not no_check:
        try:
            app = _load(ctx)
            provider_obj = app.pipeline.providers[provider]
            jobs = provider_obj.fetch_jobs(board)
            count = len(jobs)
            console.print(
                f"[green]OK[/green] {provider}/{board} → {count} open job(s)"
            )
        except Exception as exc:
            _fail(f"Could not reach {provider}/{board}: {exc}")

    added = add_source(config_path, provider, board)
    if added:
        console.print(f"[green]Added[/green] {provider}: {board} to {config_path}")
    else:
        console.print(f"{provider}/{board} is already in {config_path}")


# ----------------------------------------------------------------------
# search
# ----------------------------------------------------------------------
@main.command()
@click.option("--limit", default=25, show_default=True, help="Rows to display")
@click.option("--all", "show_all", is_flag=True, help="Include below-threshold jobs")
@click.pass_context
def search(ctx: click.Context, limit: int, show_all: bool) -> None:
    """Fetch jobs from all boards, score them, and show the best matches."""
    app = _load(ctx)
    stats = app.pipeline.search()

    for key, error in stats.errors.items():
        err_console.print(f"[yellow]warning:[/yellow] {key}: {error}")

    rows = app.store.jobs(
        statuses=None if show_all else ("matched",),
        limit=limit,
        order="score",
    )
    table = RichTable(title=f"Jobs ({stats.new_jobs} new, {stats.matched} matched)")
    for col, kwargs in (
        ("ID", {}),
        ("Score", {"justify": "right"}),
        ("Title", {}),
        ("Company", {}),
        ("Location", {}),
        ("Remote", {}),
        ("Posted", {}),
        ("Status", {}),
    ):
        table.add_column(col, **kwargs)
    for row in rows:
        score = row["score"] or 0
        score_str = f"{score:.0f}"
        style = "green" if score >= app.config.matching.threshold else "yellow"
        table.add_row(
            str(row["id"]),
            Text(score_str, style=style),
            truncate(row["title"], 48),
            truncate(row["company"], 22),
            truncate(row["location"] or "—", 24),
            "✓" if row["remote"] else "",
            _short_date(row["published_at"]),
            row["status"],
        )
    console.print(table)
    fetched = ", ".join(f"{k}={v}" for k, v in stats.boards.items()) or "nothing fetched"
    console.print(f"[dim]{fetched}[/dim]")
    console.print("[dim]Use `jauto show <ID>` for details, `jauto apply <ID>` to apply.[/dim]")


def _short_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    return iso[:10]


# ----------------------------------------------------------------------
# show
# ----------------------------------------------------------------------
@main.command()
@click.argument("job_id", type=int)
@click.pass_context
def show(ctx: click.Context, job_id: int) -> None:
    """Show full details and the score breakdown for one job."""
    app = _load(ctx)
    row = app.store.get(job_id)
    if row is None:
        _fail(f"No job with id {job_id}")
    import json

    reasons = json.loads(row.get("score_reasons") or "[]")
    provider = app.pipeline.providers.get(row["provider"])
    apply_support = "yes" if provider and provider.apply_supported else "link only"

    body = Text()
    body.append(f"{row['title']}\n", style="bold")
    body.append(
        f"{row['company']} · {row['location'] or '—'}"
        f"{' · remote' if row['remote'] else ''}\n"
    )
    if row["salary_min"] or row["salary_max"]:
        salary = "–".join(
            f"{v:,.0f}" for v in (row["salary_min"], row["salary_max"]) if v
        )
        body.append(f"Salary: {salary} {row['currency'] or ''}".rstrip() + "\n")
    body.append(f"Provider: {row['provider']}/{row['provider_board']} ({apply_support} apply)\n")
    body.append(f"Link: {row['url']}\n")
    if row["apply_url"] and row["apply_url"] != row["url"]:
        body.append(f"Apply: {row['apply_url']}\n")
    body.append("\n")
    body.append(f"Score: {row['score']:.0f}", style="bold")
    body.append(f" — status {row['status']}\n")
    body.append("\n".join(f"  {r}" for r in reasons) + "\n")
    body.append("\nDescription preview:\n")
    body.append(truncate(row["description_text"] or "(not fetched)", 1500))
    console.print(Panel(body, title=f"Job #{row['id']}"))


# ----------------------------------------------------------------------
# apply
# ----------------------------------------------------------------------
@main.command()
@click.argument("job_id", type=int, required=False)
@click.option("--auto", is_flag=True, help="Apply to the best matching jobs automatically")
@click.option("--yes", is_flag=True, help="Actually submit (default is a dry run)")
@click.option("--dry-run", "dry_run", is_flag=True, help="Force preview even if auto_submit is on")
@click.option("--force", is_flag=True, help="Submit even with unanswered required questions")
@click.option("--min-score", type=float, default=None, help="Override apply.min_score (with --auto)")
@click.option("--limit", type=int, default=None, help="Override apply.max_per_run (with --auto)")
@click.pass_context
def apply(
    ctx: click.Context,
    job_id: Optional[int],
    auto: bool,
    yes: bool,
    dry_run: bool,
    force: bool,
    min_score: Optional[float],
    limit: Optional[int],
) -> None:
    """Preview (and with --yes, submit) an application.

    \b
    jauto apply 42         preview the application for job 42
    jauto apply 42 --yes   submit it
    jauto apply --auto     preview applications for the best matches
    jauto apply --auto --yes   submit them (respects limits)
    """
    app = _load(ctx)
    if not auto and job_id is None:
        _fail("Give a job ID, or use --auto to apply to the best matches")

    errors, warnings = app.config.validate_for_apply()
    for warning in warnings:
        err_console.print(f"[yellow]note:[/yellow] {warning}")
    if errors and (yes or app.config.apply.auto_submit) and not dry_run:
        for error in errors:
            err_console.print(f"[red]error:[/red] {error}")
        _fail("Fix the profile section of config.yaml before submitting applications")

    submit = (yes or app.config.apply.auto_submit) and not dry_run

    if auto or job_id is None:
        results = app.pipeline.auto_apply(
            dry_run=not submit, min_score=min_score, max_apps=limit, force=force
        )
        _print_results(results, submit)
        return

    try:
        result = app.pipeline.apply_one(job_id, dry_run=not submit, force=force)
    except LookupError as exc:
        _fail(str(exc))
    _print_results([result], submit)


def _print_results(results, submit: bool) -> None:
    mode = "SUBMITTED" if submit else "PREVIEW (dry run — add --yes to submit)"
    counts: Dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        style = {
            "applied": "green",
            "dry_run": "cyan",
            "needs_review": "yellow",
            "failed": "red",
            "manual": "magenta",
        }.get(result.status, "white")
        header = f"[{style}]{result.status.upper()}[/{style}] "
        if result.job_id:
            header += f"#{result.job_id} {result.company} — {result.title}"
        console.print(header)
        if result.built is not None:
            built = result.built
            form = RichTable(show_header=False, box=None, pad_edge=False)
            form.add_column(style="dim")
            form.add_column()
            for key, value in built.form.items():
                display = value if isinstance(value, str) else str(value)
                form.add_row(key, truncate(display, 80))
            for field, filename, content in built.files:
                form.add_row(field, f"{filename} ({len(content)} bytes)")
            console.print(form)
        if result.message:
            console.print(f"  {result.message}")
        if result.apply_url:
            console.print(f"  [dim]link: {result.apply_url}[/dim]")
    summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    console.print(f"\n[bold]{mode}[/bold] — {summary or 'nothing to do'}")


# ----------------------------------------------------------------------
# status
# ----------------------------------------------------------------------
@main.command("status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show pipeline state: job counts and recent applications."""
    app = _load(ctx)
    counts = app.store.counts()
    table = RichTable(title="Jobs by status")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status_name in ("matched", "needs_review", "applied", "failed", "skipped", "manual", "hidden", "new"):
        if status_name in counts:
            table.add_row(status_name, str(counts[status_name]))
    if not table.rows:
        table.add_row("no jobs yet — run `jauto search`", "")
    console.print(table)

    last_search = app.store.get_meta("last_search_at")
    if last_search:
        console.print(f"[dim]Last search: {last_search}[/dim]")

    applications = app.store.recent_applications(10)
    if applications:
        app_table = RichTable(title="Recent applications")
        for col in ("When", "Company", "Title", "Method", "Result"):
            app_table.add_column(col)
        for row in applications:
            app_table.add_row(
                row["submitted_at"][:19].replace("T", " "),
                truncate(row["company"], 20),
                truncate(row["title"], 34),
                row["method"],
                "ok" if row["ok"] else f"FAILED ({row['http_status'] or 'error'})",
            )
        console.print(app_table)


# ----------------------------------------------------------------------
# run (cron entry point)
# ----------------------------------------------------------------------
@main.command()
@click.option("--yes", is_flag=True, help="Submit applications this run")
@click.option("--dry-run", "dry_run", is_flag=True, help="Never submit this run")
@click.pass_context
def run(ctx: click.Context, yes: bool, dry_run: bool) -> None:
    """One-shot: search all boards, then auto-apply if configured.

    For cron: `jauto run` submits only when apply.auto_submit is true in the
    config; --yes forces submission for this run, --dry-run forbids it.
    """
    app = _load(ctx)
    stats = app.pipeline.search()
    for key, error in stats.errors.items():
        err_console.print(f"[yellow]warning:[/yellow] {key}: {error}")

    submit = (yes or app.config.apply.auto_submit) and not dry_run
    results = app.pipeline.auto_apply(dry_run=not submit)
    counts: Dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    console.print(
        f"run complete — {sum(stats.boards.values())} jobs fetched, "
        f"{stats.matched} matched; applications: {summary or 'none'}"
        + ("" if submit else " (preview only)")
    )


# ----------------------------------------------------------------------
# check
# ----------------------------------------------------------------------
@main.command("check")
@click.option("--online", is_flag=True, help="Also test each board endpoint")
@click.pass_context
def check(ctx: click.Context, online: bool) -> None:
    """Validate configuration and (optionally) board connectivity."""
    app = _load(ctx)
    problems = 0

    total_boards = sum(len(v) for v in app.config.sources.values())
    console.print(f"config: [green]ok[/green] ({total_boards} board(s) tracked)")

    errors, warnings = app.config.validate_for_apply()
    for error in errors:
        console.print(f"  [red]✗[/red] {error}")
        problems += 1
    for warning in warnings:
        console.print(f"  [yellow]![/yellow] {warning}")
    if not errors and not warnings:
        console.print("  apply readiness: [green]all good[/green]")

    jobs = app.store.counts()
    if jobs:
        console.print(f"database: {sum(jobs.values())} job(s) tracked")

    if online:
        for provider_name, boards in app.config.sources.items():
            provider = app.pipeline.providers.get(provider_name)
            for board in boards:
                try:
                    fetched = provider.fetch_jobs(board)
                    console.print(f"  [green]✓[/green] {provider_name}/{board}: {len(fetched)} jobs")
                except Exception as exc:
                    console.print(f"  [red]✗[/red] {provider_name}/{board}: {exc}")
                    problems += 1

    if problems:
        raise SystemExit(1)
    console.print("[green]check passed[/green]")


if __name__ == "__main__":  # pragma: no cover
    main()
