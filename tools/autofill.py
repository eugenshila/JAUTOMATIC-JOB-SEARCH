#!/usr/bin/env python
"""Assisted application-form autofill — plan offline, fill with you watching.

Two modes:

* ``--form FILE.html --plan`` (offline, deterministic): parse a saved HTML
  form, print the fill plan the engine would execute.  This is the mode the
  test suite exercises; use it to preview what would be typed where.

* ``--url https://boards.../jobs/...`` (assisted, needs ``playwright``): opens
  a *persistent* browser profile that stays logged in as you, loads the form,
  types the values from your profile into the fields it recognises, highlights
  them, and stops.  You review and press Submit yourself — the tool never
  logs in for you and never submits for you (that is the line between assisted
  autofill and the account-banning kind of automation).

Examples:
    python tools/autofill.py --form tests/fixtures/forms/greenhouse.html --plan
    python tools/autofill.py --url https://boards.greenhouse.io/acme/jobs/123
    python tools/autofill.py --url … --application 3f9c2a1b  # attach the CV/letter
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jautomatic.models import Profile, Workspace, default_data_dir  # noqa: E402


def load_context(args) -> tuple[Profile, object | None, dict | None]:
    data_dir = args.data_dir or os.environ.get("JAUTOMATIC_DATA_DIR") \
        or str(default_data_dir())
    workspace = Workspace(data_dir)
    profile = workspace.load_profile()
    application = None
    if args.application:
        application = workspace.get_application(args.application)
        if application is None:
            sys.exit(f"no tracked application with id {args.application!r}")
    overrides = dict(profile.extra or {}).get("autofill") or {}
    return profile, application, overrides


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="application-form URL (assisted browser mode)")
    source.add_argument("--form", type=Path,
                        help="saved HTML form file (offline plan mode)")
    parser.add_argument("--data-dir", default=None,
                        help="workspace directory (profile/settings/database)")
    parser.add_argument("--application", default=None, metavar="ID",
                        help="tracked application id whose CV/letter to attach")
    parser.add_argument("--plan", action="store_true",
                        help="with --url: only print the plan, do not type anything")
    parser.add_argument("--json", action="store_true", help="machine-readable plan")
    args = parser.parse_args()

    profile, application, overrides = load_context(args)

    if args.form:
        from jautomatic.services.autofill import plan_for_html
        plan = plan_for_html(args.form.read_text(encoding="utf-8"), profile,
                             application=application, overrides=overrides)
        print(plan.to_json() if args.json else plan.to_text())
        return 0

    if not args.plan and not args.json:
        from jautomatic.services.autofill_browser import run_assisted
        return run_assisted(args.url, profile=profile, application=application,
                            overrides=overrides, data_dir=args.data_dir)

    # --url --plan / --url --json: fetch through the browser, but type nothing
    from jautomatic.services.autofill_browser import fetch_form_html
    html = fetch_form_html(args.url, data_dir=args.data_dir)
    from jautomatic.services.autofill import plan_for_html
    plan = plan_for_html(html, profile, application=application, overrides=overrides)
    print(plan.to_json() if args.json else plan.to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
