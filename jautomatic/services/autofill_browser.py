"""Assisted browser autofill — the thin Playwright hand-off.

Everything above this module is deterministic and fixture-tested
(``tests/test_autofill.py``).  This file is intentionally the *only* untested
seam: it opens a persistent Chromium profile, hands the rendered page's HTML to
the same tested parser/planner, and types the resulting plan into the page.

Two hard rules, by design:

1. **You log in.**  The profile persists (``<data>/browser-profile``), so you
   type your LinkedIn/Indeed/ATS password once, yourself.  This code has no
   credential handling and never will — automated login is what breaches
   platform terms and gets accounts banned.
2. **You submit.**  ``apply_plan`` only touches the fields in the plan.  There
   is no code path here that clicks a Submit button.  It fills, highlights
   what it typed, and stops.

Requires the optional dependency::

    pip install playwright && playwright install chromium
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["fetch_form_html", "run_assisted"]

_HIGHLIGHT = ("el => { el.style.outline = '2px solid #2e8b57';"
              " el.style.outlineOffset = '1px';"
              " el.style.backgroundColor = 'rgba(46,139,87,0.08)'; }")


def _persistent_context(data_dir: str | None):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "playwright is not installed.  Assisted autofill needs it:\n"
            "    pip install playwright && playwright install chromium\n"
            "(the offline half works without it: tools/autofill.py --form … --plan)"
        ) from exc

    from jautomatic.models import default_data_dir
    root = Path(data_dir) if data_dir else default_data_dir()
    profile_dir = root / "browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return sync_playwright(), profile_dir


def _frame_with_form(page):
    """Return (frame, html) of the frame holding the most form controls.

    ATS forms increasingly live inside cross-origin iframes (Workday in
    particular); the main document is checked first.
    """
    from jautomatic.services.autofill import parse_html
    best_frame, best_html = page.main_frame, page.content()
    best_count = len(parse_html(best_html))
    for frame in page.frames[1:]:
        try:
            html = frame.content()
        except Exception:      # pragma: no cover - cross-origin guards
            continue
        count = len(parse_html(html))
        if count > best_count:
            best_frame, best_html, best_count = frame, html, count
    return best_frame, best_html


def fetch_form_html(url: str, data_dir: str | None = None) -> str:
    """Open the URL in the persistent profile and return the form HTML."""
    playwright, profile_dir = _persistent_context(data_dir)
    with playwright() as active:
        browser = active.chromium.launch_persistent_context(
            str(profile_dir), headless=False,
            viewport={"width": 1280, "height": 900})
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        _, html = _frame_with_form(page)
        browser.close()
    return html


def _locator(frame, anchor: dict):
    """Best CSS locator for a plan anchor, falling back to document order."""
    if anchor.get("id"):
        return frame.locator(f"#{anchor['id']}")
    if anchor.get("name"):
        return frame.locator(
            f"{anchor['tag']}[name={_css_quote(anchor['name'])}]")
    return frame.locator("input, select, textarea").nth(anchor["index"])


def _css_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _apply(frame, action, dry_run: bool) -> str:
    """Type one fill action.  Returns a human-readable result line."""
    anchor = action.anchor
    label = action.label or f"#{anchor['index']}"
    if action.status != "fill":
        return f"     {action.status:<6} {label}"
    if dry_run:
        return f"     fill   {label} → {action.value} (dry run)"

    locator = _locator(frame, anchor)
    try:
        if anchor["kind"] == "file":
            locator.set_input_files(action.value)
        elif anchor["kind"] == "select":
            try:
                locator.select_option(action.value)
            except Exception:
                locator.select_option(label=action.value)
        elif anchor["kind"] == "checkbox":
            locator.set_checked(action.value.lower() in ("yes", "true", "y"))
        elif anchor["kind"] == "radio":
            locator.locator(f"[value={_css_quote(action.value)}]").check()
        else:
            locator.fill(action.value)
        locator.evaluate(_HIGHLIGHT)
        return f"     fill   {label} → {action.value}"
    except Exception as exc:                    # pragma: no cover - live DOM
        return f"     FAILED {label}: {str(exc).splitlines()[0]}"


def run_assisted(url: str, profile, application=None, overrides: dict | None = None,
                 data_dir: str | None = None, dry_run: bool = False) -> int:
    """Open the form, fill the plan, highlight, and stop for your review."""
    from jautomatic.services.autofill import parse_html, ProfileAnswers, build_plan

    playwright, profile_dir = _persistent_context(data_dir)
    print("Opening a browser window with your persistent profile.\n"
          "Log in if the site asks — the tool never handles credentials.\n")
    with playwright() as active:
        browser = active.chromium.launch_persistent_context(
            str(profile_dir), headless=False,
            viewport={"width": 1280, "height": 900})
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        target_frame, html = _frame_with_form(page)
        plan = build_plan(parse_html(html),
                          ProfileAnswers.from_profile(profile,
                                                      application=application,
                                                      overrides=overrides))
        print(plan.to_text())
        if plan.filled:
            print("\nTyping the plan into the form…")
            for action in plan.filled:
                print(_apply(target_frame, action, dry_run))

        print("\nDone filling.  Review the highlighted fields and press Submit\n"
              "yourself — this tool will not do it for you.")
        try:
            input("Press Enter here to close the browser… ")
        except EOFError:                       # pragma: no cover - non-tty
            pass
        browser.close()
    return 0
