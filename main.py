#!/usr/bin/env python3
"""JAUTOMATIC JOB SEARCH - desktop entry point.

    python main.py                     # launch the GUI
    python main.py --data-dir ./data   # use a portable data directory
    python main.py --selftest          # head-less smoke test (CI friendly)
    python main.py --scrape "python"   # dump matches to stdout, no GUI
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from jautomatic import APP_TITLE, __version__


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="jautomatic", description=f"{APP_TITLE} {__version__}")
    parser.add_argument("--data-dir", default=None,
                        help="where the database and documents live (default: user data dir)")
    parser.add_argument("--selftest", action="store_true",
                        help="run a head-less smoke test of every subsystem and exit")
    parser.add_argument("--scrape", metavar="QUERY", default=None,
                        help="run a search from the command line and print the results")
    parser.add_argument("--limit", type=int, default=5,
                        help="results per source for --scrape (default: 5)")
    parser.add_argument("--offline", action="store_true",
                        help="with --scrape: use the bundled demo source only")
    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {__version__}")
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- #
# head-less modes
# --------------------------------------------------------------------------- #
def run_selftest(data_dir: str | None = None) -> int:
    """Exercise models, scraper (offline), matcher and every document generator."""
    import tempfile

    from jautomatic.models import Profile, Workspace
    from jautomatic.services.application_pipeline import ApplicationPipeline
    from jautomatic.services.email_drafter import render_email, render_follow_up
    from jautomatic.models import SAMPLE_PROFILE

    root = Path(data_dir) if data_dir else Path(tempfile.mkdtemp(prefix="jautomatic-selftest-"))
    workspace = Workspace(root)
    profile = Profile.from_dict(SAMPLE_PROFILE)
    workspace.save_profile(profile)
    pipeline = ApplicationPipeline(workspace, workspace.load_settings())
    pipeline.settings.export_format = "docx"
    pipeline.workspace.save_settings(pipeline.settings)

    outcome = pipeline.search("python", sources=["sample"], limit_per_source=5)
    assert outcome.jobs, "the demo source returned nothing"
    created = pipeline.import_jobs(outcome.jobs)
    rows = pipeline.tracker(profile)
    assert rows, "no tracked applications"
    best = rows[0]
    assert best.score > 0, "match scoring produced 0"

    materials = pipeline.prepare(best.application, profile)
    for document in (materials.cv, materials.cover_letter, materials.email):
        assert document is not None and document.text.strip(), "a document came out empty"
    assert materials.cv.path and materials.cv.path.exists(), "CV file was not written"

    pipeline.set_status(materials.application, "sent", "selftest")
    draft_path, draft_text = pipeline.draft_follow_up(materials.application)
    assert draft_path.exists() and "Following up" in draft_text

    csv_path = pipeline.export_tracker_csv(profile)
    assert csv_path.exists() and csv_path.stat().st_size > 0

    ics_path = pipeline.export_calendar_ics(profile)
    ics_text = ics_path.read_text(encoding="utf-8")
    assert ics_path.exists() and ics_text.startswith("BEGIN:VCALENDAR"), "ICS export missing header"
    assert "BEGIN:VEVENT" in ics_text and "END:VCALENDAR" in ics_text, "ICS export has no events"

    assert render_email(profile, best.job).subject
    assert render_follow_up(profile, best.job).subject

    stats = workspace.stats()
    from jautomatic import runtime
    print(f"runtime        : {runtime.runtime_tag()}")
    print(f"workspace      : {root}")
    print(f"demo postings  : {len(outcome.jobs)} ({len(created)} tracked)")
    print(f"best match     : {best.title} @ {best.company} — {best.score}/100")
    print(f"documents      : {', '.join(Path(p).name for p in materials.paths)}")
    print(f"follow-up draft: {draft_path.name}")
    print(f"tracker export : {csv_path.name}")
    print(f"calendar export: {ics_path.name} ({ics_text.count('BEGIN:VEVENT')} event(s))")
    print(f"stats          : {json.dumps(stats, default=str)}")
    workspace.close()
    print("SELFTEST OK")
    return 0


def run_scrape(query: str, limit: int, offline: bool, data_dir: str | None) -> int:
    from jautomatic.models import Workspace
    from jautomatic.services.application_pipeline import ApplicationPipeline, rank_jobs

    workspace = Workspace(data_dir)
    pipeline = ApplicationPipeline(workspace, workspace.load_settings())
    sources = ["sample"] if offline else None
    outcome, created = pipeline.search_and_import(query, sources=sources, limit_per_source=limit)
    for job, match in rank_jobs(workspace.load_profile(), outcome.jobs, pipeline.settings):
        print(f"[{match.score:3d}] {job.title} — {job.company} ({job.display_location}, "
              f"{job.salary_text}, {job.posted_text}) [{job.source}]")
        if match.reasons:
            print(f"        {'; '.join(match.reasons[:2])}")
    print(f"\n{outcome.summary()} · {len(created)} new tracker entries in {workspace.root}")
    workspace.close()
    return 0 if outcome.jobs else 1


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
def run_gui(data_dir: str | None = None) -> int:
    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is not installed.\nInstall the dependencies first:\n"
              "    python -m venv .venv && .venv/bin/pip install -r requirements.txt",
              file=sys.stderr)
        return 2

    from jautomatic.ui.main_window import MainWindow
    from jautomatic.ui.theme import apply_theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("JAUTOMATIC")
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)

    window = MainWindow(data_dir=data_dir)
    apply_theme(app, window.settings.theme)
    window.show()
    window.notify("Welcome! Start with the Profile tab, then run a search.", "info")
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    # Frozen Windows builds (packaging/): spawned child processes re-execute
    # the bundle unless freeze_support() runs first.  Harmless everywhere else.
    from jautomatic import runtime
    if runtime.is_frozen():
        import multiprocessing
        multiprocessing.freeze_support()

    args = parse_args(argv)
    try:
        if args.selftest:
            return run_selftest(args.data_dir)
        if args.scrape:
            return run_scrape(args.scrape, args.limit, args.offline, args.data_dir)
        return run_gui(args.data_dir)
    except KeyboardInterrupt:
        return 130
    except Exception:  # noqa: BLE001 - last-resort guard so the window never dies silently
        traceback.print_exc()
        print("\nJAUTOMATIC crashed. Please re-run with --selftest to isolate the problem.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
