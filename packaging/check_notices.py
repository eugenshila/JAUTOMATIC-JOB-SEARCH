#!/usr/bin/env python3
"""Guard the third-party notice list against dependency drift.

The MSI redistributes everything the app imports at runtime (Qt/PySide6, the
requests stack, python-docx and its lxml dependency...). Bundling a package
whose licence is not in ``packaging/THIRD-PARTY-NOTICES.md`` is both a legal
hole and, for copyleft components, a licence violation - and dependency
versions move under us every time ``pip`` resolves.

This checker computes the *runtime* closure of ``requirements.txt`` (build-time
tools like PyInstaller/ruff are deliberately not shipped and therefore not
required to be listed) and compares it with the notice table:

    python packaging/check_notices.py            # exit 1 on drift
    python packaging/check_notices.py --json     # machine readable
    python packaging/check_notices.py --list     # print the closure + licences

Stdlib only (``importlib.metadata``); markers are evaluated for the Windows
build target with a deliberately small parser - anything it cannot parse is
*treated as included*, so an unknown marker fails safe (more notices, not
fewer).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "packaging" / "THIRD-PARTY-NOTICES.md"
REQUIREMENTS = ROOT / "requirements.txt"

#: never shipped: development/build tooling. Listed in the notices as
#: "build-time" for transparency but not required for the closure to match.
BUILD_TIME_ONLY = {"pyinstaller", "ruff", "pip", "setuptools", "wheel", "pip-licenses"}

#: environment the shipped payload is built for
TARGET = {
    "python_version": "3.12",
    "python_full_version": "3.12.0",
    "sys_platform": "win32",
    "platform_system": "Windows",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "implementation_name": "cpython",
    "extra": "",
}

_MARKER = re.compile(r"([a-zA-Z_][a-zA-Z0-9_.]*)\s*(==|!=|<=|>=|<|>|~=|===)\s*['\"]([^'\"]*)['\"]")


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3]) or (0,)


def _compare(left: str, op: str, right: str) -> bool:
    if op == "==":
        return left.startswith(right.rstrip(".0")) if right.count(".") < left.count(".") else left == right
    if op == "!=":
        return not _compare(left, "==", right)
    lv, rv = _version_tuple(left), _version_tuple(right)
    pad = max(len(lv), len(rv))
    lv += (0,) * (pad - len(lv))
    rv += (0,) * (pad - len(rv))
    return {"<": lv < rv, "<=": lv <= rv, ">": lv > rv, ">=": lv >= rv,
            "~=": lv >= rv, "===": lv == rv}[op]


def marker_satisfied(marker: str) -> bool:
    """Evaluate the subset of PEP 508 markers we actually see; unknown -> True."""
    marker = marker.strip()
    if not marker:
        return True
    for chunk in re.split(r"\s+or\s+", marker):
        clauses = re.split(r"\s+and\s+", chunk)
        if all(_clause_ok(clause.strip()) for clause in clauses if clause.strip()):
            return True
    return False


def _clause_ok(clause: str) -> bool:
    match = _MARKER.fullmatch(clause)
    if not match:
        match = _MARKER.search(clause)
        if not match or match.group(0) != clause:
            return True                      # fail safe: assume it applies
    name, op, value = match.groups()
    if name not in TARGET:
        return True
    return _compare(TARGET[name], op, value)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", (name or "")).strip().lower()


def installed_dists() -> dict[str, tuple[str, metadata.Distribution]]:
    """{normalised distribution name: (version, Distribution)} of this env."""
    out: dict[str, tuple[str, metadata.Distribution]] = {}
    for dist in metadata.distributions():
        name = _norm(dist.metadata["Name"])
        if name and name not in out:
            out[name] = (dist.version or "0", dist)
    return out


def requirements_closure(requirements: Path | None = None) -> dict[str, str]:
    """Transitive runtime dependencies of requirements.txt, with versions."""
    env = installed_dists()
    closure: dict[str, str] = {}
    pending = []
    text = (requirements or REQUIREMENTS).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line:
            pending.append(re.split(r"[<>=!~;\[]", line)[0].strip())
    seen: set[str] = set()
    while pending:
        name = re.sub(r"[-_.]+", "-", pending.pop()).lower()
        if name in seen:
            continue
        seen.add(name)
        if name in BUILD_TIME_ONLY:
            continue
        entry = env.get(name)
        if entry is None:
            print(f"notice check: {name} is not installed here; cannot verify its "
                  f"sub-dependencies (install requirements first)", file=sys.stderr)
            closure[name] = "?"
            continue
        version, dist = entry
        closure[name] = version
        for requirement in (dist.requires or []):
            spec, _, marker = requirement.partition(";")
            if marker and not marker_satisfied(marker):
                continue
            child = re.sub(r"[-_.]+", "-", re.split(r"[<>=!~;\[ ]", spec.strip())[0]).lower()
            if child and child not in seen:
                pending.append(child)
    return closure


def declared_notices(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Parse the notice table rows: | Package | Version | Licence | Role |"""
    out: dict[str, dict[str, str]] = {}
    for line in (path or NOTICES).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] and cells[0][0].isalnum():
            key = re.sub(r"[-_.]+", "-", cells[0]).lower()
            if key in ("package",):
                continue
            out[key] = {"version": cells[1], "licence": cells[2],
                        "role": cells[3] if len(cells) > 3 else "",
                        # rows like "Qt (via PySide6)" are explanatory aliases,
                        # not independently installed distributions
                        "alias": "(" in cells[0]}
    return out


def check() -> tuple[list[str], list[str], dict[str, str]]:
    closure = requirements_closure()
    declared = declared_notices()
    missing = [name for name in sorted(closure) if name not in declared]
    extra = [name for name in sorted(declared)
             if name not in closure and not declared[name].get("alias")
             and declared[name].get("role", "").lower() != "build-time"]
    return missing, extra, closure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list", action="store_true", help="print closure with licences")
    args = parser.parse_args(argv)

    missing, extra, closure = check()
    declared = declared_notices()
    if args.json:
        print(json.dumps({"missing_notices": missing, "undocumented_in_closure": extra,
                          "closure": closure}, indent=2))
    if args.list:
        for name in sorted(closure):
            note = declared.get(name, {})
            print(f"{name:24s} {closure[name]:10s} {note.get('licence', 'NOT LISTED!')}")
    if missing:
        for name in missing:
            print(f"NOTICE DRIFT: runtime dependency '{name}' is missing from "
                  f"packaging/THIRD-PARTY-NOTICES.md", file=sys.stderr)
        return 1
    if extra:
        print(f"notice check: listed but not in the runtime closure (harmless, "
              f"trim if intentional): {', '.join(extra)}", file=sys.stderr)
    print(f"notices OK ({len(closure)} runtime packages, all documented)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
