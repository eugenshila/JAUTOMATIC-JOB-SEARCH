#!/usr/bin/env python3
"""Head-less UI driver: renders every tab and exercises the main flows.

    LD_LIBRARY_PATH=.stublibs QT_QPA_PLATFORM=offscreen python tools/screenshot.py \
        --out docs/screenshots

It seeds demo data through the real pipeline, then walks the tabs, grabs a PNG
for each and additionally checks that material generation, status changes and
follow-up drafting work through the window's background-worker plumbing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jautomatic.models import SAMPLE_PROFILE, ApplicationStatus, Profile  # noqa: E402
from jautomatic.ui.main_window import MainWindow  # noqa: E402
from jautomatic.ui.theme import MarkdownPreviewDialog, apply_theme  # noqa: E402

# Freeze the clock: seeded history events carry now_iso() stamps that render in
# the activity log / event history, which used to make four of the seven PNGs
# differ between runs by a few pixels of seconds.  (Dates derived from
# date.today() still move across days — that part is inherent.)
import jautomatic.models as _models  # noqa: E402
import jautomatic.services.application_pipeline as _pipeline  # noqa: E402

_FROZEN_NOW = "2026-09-15T12:00:00"
_models.now_iso = lambda: _FROZEN_NOW
_pipeline.now_iso = lambda: _FROZEN_NOW


def pump(app: QApplication, ms: int = 900, until=None) -> None:  # noqa: ANN001
    """Spin the event loop until background work settles."""
    import time

    deadline = time.time() + ms / 1000
    QThreadPool.globalInstance().waitForDone(int(ms))
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            break
        time.sleep(0.02)
    app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "screenshots"))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--theme", default="blackgreen", choices=["midnight", "blackgreen", "daylight"],
                        help="theme used for the captures")
    parser.add_argument("--extra", action="store_true",
                        help="also capture the light theme + a preview dialog")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # a fixed default data dir keeps renders byte-stable: the Settings and
    # CV-preview shots show workspace.root, so a fresh mkdtemp() every run used
    # to change 4 of the 7 PNGs without anything actually moving.  The default
    # dir is wiped on start so reruns always render the canonical seeded state
    # (an explicit --data-dir is left alone — that is the user's workspace).
    import shutil
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        data_dir = ROOT / ".screenshot-data"
        if data_dir.exists():
            shutil.rmtree(data_dir)

    app = QApplication(sys.argv[:1])
    window = MainWindow(data_dir=data_dir)
    apply_theme(app, args.theme)

    # Screenshots must be reproducible, so capture with the bundled offline source
    # (the network boards behave differently depending on where the app runs).
    settings = window.settings
    settings.enabled_sources = ["sample"]
    window.save_settings(settings)
    window.resize(1440, 940)
    window.show()
    pump(app, 400)

    # -- seed a realistic workspace ---------------------------------------- #
    profile = Profile.from_dict(SAMPLE_PROFILE)
    window.save_profile(profile)
    window.tabs["profile"].load()

    outcome, created = window.pipeline.search_and_import("python", sources=["sample"],
                                                         limit_per_source=10)
    print(f"seeded {len(created)} applications from {len(outcome.jobs)} postings")
    for row in window.pipeline.tracker(profile)[:2]:
        materials = window.pipeline.prepare(row.application, profile)
        print(f"prepared: {row.title} -> {materials.cv.filename}")
    top = window.pipeline.tracker(profile)[0]
    window.pipeline.set_status(top.application, ApplicationStatus.SENT, "seeded")
    from datetime import date, timedelta  # noqa: E402

    interview_day = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
    window.pipeline.set_interview(top.application, f"{interview_day} 10:00")
    window.pipeline.update_notes(top.application,
                                 "Recruiter Anna replied — technical interview Thursday 10:00.")
    window.pipeline.tracker(profile)[1].application.notes = "Take-home due next week."
    second = window.pipeline.tracker(profile)[1]
    window.pipeline.update_notes(second.application, "Take-home exercise due next week.")
    window.pipeline.postpone_follow_up(top.application, -6)  # make it due now
    window.refresh_all()
    pump(app, 500)

    # -- screenshots of every tab ------------------------------------------ #
    shots = []
    for key, filename in [("profile", "01-profile.png"), ("search", "02-job-search.png"),
                          ("applications", "03-applications.png"),
                          ("dashboard", "04-dashboard.png"), ("settings", "05-settings.png")]:
        window.go_to(key)
        tab = window.tabs[key]
        if key == "profile":
            tab.fields["full_name"].setFocus()
        if key == "search":
            tab.load_defaults()
            tab.start_search(import_results=False)
            pump(app, 15000, until=lambda t=tab: t.table.rowCount() > 0)
        if key == "applications":
            tab.refresh()
            tab.table.selectRow(0)
        if key == "settings":
            tab.refresh()
        pump(app, 400)
        path = out_dir / filename
        window.grab().save(str(path))
        shots.append(path)
        print(f"shot: {path}")

    # -- verify the dialogs render ----------------------------------------- #
    row = window.pipeline.tracker(profile)[0]
    materials = window.pipeline.prepare(row.application, profile)
    dialog = MarkdownPreviewDialog(f"CV · {row.title}", materials.cv.text, materials.cv.path,
                                   window)
    dialog.resize(820, 700)
    dialog.show()
    pump(app, 400)
    preview_path = out_dir / "06-cv-preview.png"
    dialog.grab().save(str(preview_path))
    shots.append(preview_path)
    print(f"shot: {preview_path}")
    dialog.close()

    if args.extra:
        window.apply_theme("daylight")
        pump(app, 400)
        window.go_to("applications")
        pump(app, 400)
        light_path = out_dir / "07-daylight-theme.png"
        window.grab().save(str(light_path))
        shots.append(light_path)
        print(f"shot: {light_path}")
        window.apply_theme("midnight")
        pump(app, 300)

    # -- background tasks actually run (regression guard) ------------------ #
    flags = []
    window.run_task("Counting", lambda: flags.append("ran"))
    pump(app, 5000, until=lambda: bool(flags))
    assert flags, "run_task() never executed its callable"
    print("background worker: callable executed")

    # -- the in-app search flow (GUI -> worker -> table) ------------------- #
    search_tab = window.tabs["search"]
    window.go_to("search")
    search_tab.load_defaults()
    search_tab.start_search(import_results=False)
    pump(app, 15000, until=lambda: search_tab.table.rowCount() > 0)
    assert search_tab.table.rowCount() > 0, "the search tab never filled its table"
    assert search_tab.ranked and search_tab.ranked[0][1].score >= 0, "results were not ranked"
    print(f"search tab: {search_tab.table.rowCount()} rows, best score "
          f"{search_tab.ranked[0][1].score}")
    selected = search_tab.table.item(0, 1).text()
    assert selected, "the first result row has no role title"
    assert search_tab.description.toPlainText().strip(), "detail pane stayed empty"
    print(f"detail pane: showing “{selected}”")

    # -- document previews are non-modal ---------------------------------- #
    dialog = window.open_preview("CV preview", materials.cv.text, materials.cv.path)
    pump(app, 200)
    assert dialog.isVisible() and window._previews, "preview dialog did not open"
    dialog.close()
    pump(app, 200)
    print("preview dialog: opened and closed without blocking")

    # -- assertions --------------------------------------------------------- #
    assert window.workspace.job_count() >= 6, "demo postings were not stored"
    assert len(window.pipeline.tracker(profile)) >= 6, "tracker rows missing"
    assert materials.cv.path and materials.cv.path.exists(), "CV was not written"
    assert Path(materials.cover_letter.path).exists(), "cover letter was not written"
    assert Path(materials.email.path).exists(), "e-mail draft was not written"
    csv_path = window.pipeline.export_tracker_csv(profile)
    assert csv_path.exists() and csv_path.stat().st_size > 200, "tracker export looks empty"
    ics_path = window.pipeline.export_calendar_ics(profile)
    ics_text = ics_path.read_text(encoding="utf-8")
    assert ics_text.count("BEGIN:VEVENT") >= 2, "calendar export missed follow-up/interview events"
    assert f"UID:{top.application.application_id}-follow-up@jautomatic" in ics_text
    assert f"UID:{top.application.application_id}-interview@jautomatic" in ics_text
    print(f"calendar export: {ics_path.name} ({ics_text.count('BEGIN:VEVENT')} events)")
    due = window.pipeline.follow_ups_due(profile)
    assert due, "follow-up reminder did not trigger"
    document_path, text = window.pipeline.draft_follow_up(due[0].application)
    assert document_path.exists() and "Following up" in text, "follow-up draft failed"
    stats = window.workspace.stats()
    print(f"stats: {stats}")
    print(f"{len(shots)} screenshots, {window.workspace.root}")
    window.close()
    app.processEvents()
    print("UI SMOKE TEST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
