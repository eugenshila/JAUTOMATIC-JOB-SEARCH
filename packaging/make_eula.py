#!/usr/bin/env python3
"""Derive the installer EULA (``packaging/wix/LICENSE.rtf``) from ``LICENSE``.

The MSI shows the licence in an RTF view; keeping a hand-edited second copy of
the legal text is how EULAs drift. So the RTF is *generated* from the canonical
plain-text licence, deterministically:

    python packaging/make_eula.py            # (re)write packaging/wix/LICENSE.rtf
    python packaging/make_eula.py --check    # fail if the committed RTF drifted

Stdlib only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSE_PATH = ROOT / "LICENSE"
RTF_PATH = ROOT / "packaging" / "wix" / "LICENSE.rtf"

HEADER = (r"{\rtf1\ansi\ansicpg1252\deff0\deflang1033"
          r"{\fonttbl{\f0\fswiss\fprq2\fcharset0 Segoe UI;}{\f1\fswiss\fcharset0 Arial;}}"
          r"{\colortbl;\red0\green0\blue0;}"
          r"\viewkind4\uc1\pard\sa120\sl240\slmult1")


def _escape(text: str) -> str:
    out = []
    for char in text:
        if char in "\\{}":
            out.append("\\" + char)
        elif ord(char) < 128:
            out.append(char)
        else:  # cp1252 best effort for anything exotic
            out.append(f"\\u{ord(char)}?")
    return "".join(out)


def rtf_from_license(text: str) -> str:
    """Plain licence text -> RTF document, one styled block per paragraph."""
    numbered = re.compile(r"^(\d+)\.\s+([A-Z][A-Z /\-]*[A-Z])\s+(.+)$", re.DOTALL)
    blocks: list[str] = []
    for index, raw in enumerate(text.split("\n\n")):
        paragraph = " ".join(line.strip() for line in raw.splitlines() if line.strip())
        if not paragraph:
            continue
        if index == 0:                                   # product name
            blocks.append(rf"\pard\qc\sa60\b\fs32\f0 {_escape(paragraph)}\b0\par")
            continue
        if index == 1:                                   # agreement title
            blocks.append(rf"\pard\qc\sa60\b\fs22\f0 {_escape(paragraph)}\b0\par")
            continue
        if index == 2:                                   # copyright line
            blocks.append(rf"\pard\qc\sa200\fs20\f0 {_escape(paragraph)}\par")
            continue
        match = numbered.match(paragraph)
        if match:                                        # "1. LICENCE GRANT" + body
            head = f"{match.group(1)}. {match.group(2)}"
            body = " ".join(match.group(3).split())
            blocks.append(rf"\pard\sa60\sb160\b\fs20\f0 {_escape(head)}\b0\par")
            blocks.append(rf"\pard\sa120\fs20\f0 {_escape(body)}\par")
            continue
        blocks.append(rf"\pard\sa120\fs20\f0 {_escape(paragraph)}\par")
    return HEADER + "".join(blocks) + "}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the installer EULA (RTF)")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the committed RTF is stale")
    parser.add_argument("--out", default=str(RTF_PATH))
    args = parser.parse_args(argv)

    generated = rtf_from_license(LICENSE_PATH.read_text(encoding="utf-8"))
    out = Path(args.out)
    if args.check:
        if not out.exists():
            print(f"eula drift: {out.name}: missing", file=sys.stderr)
            return 1
        if out.read_text(encoding="utf-8") != generated:
            print(f"eula drift: {out.name} is stale "
                  f"(run: python packaging/make_eula.py)", file=sys.stderr)
            return 1
        print(f"eula OK ({out})")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generated, encoding="utf-8")
    print(f"wrote {out} ({len(generated):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
