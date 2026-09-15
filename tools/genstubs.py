#!/usr/bin/env python3
"""Build tiny stub shared libraries for headless/CI runs of the Qt UI.

Why: PySide6 links against ``libGL``, ``libEGL``, ``libxkbcommon`` and
``libdbus-1``.  Slim containers (and the CI image we render screenshots in)
often do not ship those, and you cannot ``apt-get install`` them without root.
Qt's ``offscreen`` platform plugin never calls into a graphics driver, so
no-op symbols are enough to satisfy ``ld.so``.

Usage::

    python tools/genstubs.py .stublibs            # writes stubs + prints count
    LD_LIBRARY_PATH=.stublibs QT_QPA_PLATFORM=offscreen python main.py --selftest

The generated files are throw-away build artifacts (see .gitignore).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TARGETS = {
    "libdbus-1.so.3": re.compile(r"^dbus_[A-Za-z0-9_]+$"),
    "libxkbcommon.so.0": re.compile(r"^xkb_[A-Za-z0-9_]+$"),
    "libEGL.so.1": re.compile(r"^egl[A-Za-z0-9_]+$"),
    "libGL.so.1": re.compile(r"^gl[A-Za-z0-9_]+$"),
}


def qt_lib_dir() -> Path:
    try:
        import PySide6  # noqa: PLC0415  (imported lazily on purpose)
    except ImportError:  # pragma: no cover - depends on env
        sys.exit("PySide6 is not installed - run: pip install -r requirements.txt")
    return Path(PySide6.__file__).parent / "Qt" / "lib"


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".stublibs").resolve()
    lib_dir = qt_lib_dir()

    syms: dict[str, dict[str, str]] = {name: {} for name in TARGETS}
    libraries = sorted(lib_dir.glob("libQt6*.so.6"))
    libraries += sorted((lib_dir.parent / "plugins").rglob("*.so"))
    for lib in libraries:
        dump = subprocess.run(
            ["nm", "-D", "--undefined-only", "--with-symbol-versions", str(lib)],
            capture_output=True, text=True).stdout
        for sym, ver in re.findall(r"\sU\s([A-Za-z_][A-Za-z0-9_]*)@?([A-Za-z0-9_.]*)", dump):
            for name, pattern in TARGETS.items():
                if pattern.match(sym):
                    syms[name].setdefault(sym, ver.lstrip("@"))
                    break

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, entries in syms.items():
        if not entries:
            continue
        c_file, map_file = out_dir / f"{name}.c", out_dir / f"{name}.map"
        c_file.write_text("".join(f"void *{s}(void) {{ return 0; }}\n" for s in entries))

        versions: dict[str, list[str]] = {}
        for sym, ver in entries.items():
            versions.setdefault(ver, []).append(sym)
        if "" in versions:  # fold unversioned symbols into a real version block
            first = next((v for v in versions if v), None)
            if first:
                versions[first].extend(versions.pop(""))
            else:
                versions["STUB_1.0"] = versions.pop("")

        lines = []
        keys = list(versions)
        for i, ver in enumerate(keys):
            body = "  global:\n" + "".join(f"    {s};\n" for s in sorted(set(versions[ver])))
            if i == len(keys) - 1:
                body += "  local: *;\n"
            lines.append(f"{ver} {{\n{body}}};\n")
        map_file.write_text("".join(lines))

        subprocess.run(
            ["gcc", "-shared", "-fPIC", "-Wl,-soname," + name,
             "-Wl,--version-script=" + str(map_file), "-o", str(out_dir / name), str(c_file)],
            check=True)
        print(f"{name}: {len(entries)} symbols stubbed -> {out_dir / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
