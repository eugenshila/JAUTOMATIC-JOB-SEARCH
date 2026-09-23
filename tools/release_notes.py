#!/usr/bin/env python3
"""Compose GitHub release notes for a JAUTOMATIC JOB SEARCH version.

Pulls the matching ``CHANGELOG.md`` section and, when an MSI path is given,
adds the install blurb plus a SHA-256 checksum.

Usage::

    python tools/release_notes.py --version 1.10.0
    python tools/release_notes.py --version 1.10.0 --msi dist/JAUTOMATIC-Setup-1.10.0-x64.msi \\
        --run-url https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH/actions/runs/1 \\
        --out release-notes.md
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
REPO_URL = "https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH"
INSTALL_DOC = f"{REPO_URL}/blob/main/docs/install-windows.md"


def changelog_section(text: str, version: str) -> str:
    """Return the ``## [version]`` block from a Keep-a-Changelog file."""
    heading = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n",
        text,
        re.MULTILINE,
    )
    if heading is None:
        raise ValueError(f"CHANGELOG.md has no '## [{version}]' section")
    start = heading.start()
    rest = text[heading.end():]
    nxt = re.search(r"^## \[", rest, re.MULTILINE)
    end = heading.end() + nxt.start() if nxt else len(text)
    return text[start:end].strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compose(
    version: str,
    changelog: str | None = None,
    msi: Path | None = None,
    run_url: str = "",
) -> str:
    body = changelog_section(
        changelog if changelog is not None else CHANGELOG.read_text(encoding="utf-8"),
        version,
    )
    msi_name = msi.name if msi is not None else f"JAUTOMATIC-Setup-{version}-x64.msi"
    lines = [
        f"Windows 10/11 (64-bit): download **{msi_name}**, double-click, and follow the wizard.",
        "Installs to `%ProgramFiles%\\JAUTOMATIC`. No account, no telemetry — the app only",
        "talks to the network when you run a job search.",
        "",
        f"See [Installing on Windows]({INSTALL_DOC}) for SmartScreen notes, silent install,",
        "and uninstall (your profile and documents in `%APPDATA%\\JAUTOMATIC` are kept).",
        "",
    ]
    if run_url:
        lines.append(
            f"This MSI was freeze-tested, packaged, installed and uninstalled by "
            f"[windows-installer]({run_url})."
        )
        lines.append("")
    if msi is not None:
        lines.append(f"**SHA-256:** `{sha256_file(msi)}`")
        lines.append("")
    lines.append(body)
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="app version, e.g. 1.10.0")
    parser.add_argument("--msi", type=Path, default=None, help="MSI path (adds SHA-256)")
    parser.add_argument("--run-url", default="", help="windows-installer run URL")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG)
    parser.add_argument("--out", type=Path, default=None, help="write notes here; else stdout")
    args = parser.parse_args(argv)

    if args.msi is not None and not args.msi.is_file():
        print(f"MSI not found: {args.msi}", file=sys.stderr)
        return 1
    try:
        notes = compose(
            args.version,
            changelog=args.changelog.read_text(encoding="utf-8"),
            msi=args.msi,
            run_url=args.run_url,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.out is None:
        sys.stdout.write(notes)
    else:
        args.out.write_text(notes, encoding="utf-8")
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
