"""Runtime environment helpers: source checkout vs. frozen (PyInstaller) build.

The Windows installer ships a frozen copy of the app (see ``packaging/``): a
PyInstaller one-dir bundle with ``jautomatic.exe`` as its entry point.  The
application code deliberately loads no data files relative to its own location,
so the frozen build needs no path fix-ups — but the entry point still has to
know which world it runs in:

* frozen executables must call :func:`multiprocessing.freeze_support` early on
  Windows, or spawned child processes re-execute the bundle instead of the
  intended target;
* diagnostics (and the installer's ``verify-install.ps1`` smoke test) want to
  report where the running code actually lives.

``base_dir()`` answers that question: the PyInstaller extraction dir
(``sys._MEIPASS``) when frozen, otherwise the repository root that contains
this package.
"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) frozen executable."""
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    """Directory the running application lives in.

    Frozen builds return the bundle dir (``sys._MEIPASS`` on PyInstaller);
    source checkouts return the repository root (the parent of this package).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if is_frozen() and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def runtime_tag() -> str:
    """Short human-readable tag used by ``--selftest`` and diagnostics."""
    if is_frozen():
        return f"frozen ({base_dir()})"
    return f"source ({base_dir()})"


__all__ = ["base_dir", "is_frozen", "runtime_tag"]
