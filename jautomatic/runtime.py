"""Runtime environment helpers: installed (frozen) build vs. source checkout.

The Windows installer ships a PyInstaller **onedir** build, so the same code has
to work in three quite different situations:

* a git checkout (``python main.py``) - resources live next to the package,
* the frozen ``JAUTOMATIC.exe`` under ``C:\\Program Files`` - read-only, no
  console, resources under ``_internal``, and data *must* go to the user profile,
* CI/headless containers - no GUI at all.

Everything here is stdlib-only and GUI-free on purpose, so ``main.py``, the
tools, the packaging scripts and the test suite can all import it.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

#: Windows AppUserModelID: keeps taskbar entries grouped and shows *our* icon
#: instead of a generic one. Must be set before the first window is created.
APP_USER_MODEL_ID = "JAUTOMATIC.JobSearch.Desktop.1"

#: Registry/settings identity (matches ``QSettings("JAUTOMATIC", "job-search")``).
ORGANIZATION = "JAUTOMATIC"
SETTINGS_APP = "job-search"

LOG_DIR_NAME = "logs"
MAX_CRASH_LOGS = 5


# --------------------------------------------------------------------------- #
# where am I running from?
# --------------------------------------------------------------------------- #
def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle (the installed .exe)."""
    return bool(getattr(sys, "frozen", False))


def is_windows() -> bool:
    return os.name == "nt"


def bundle_dir() -> Path:
    """Directory that holds the bundled resources.

    ``sys._MEIPASS`` is set by PyInstaller in both layouts (``onedir`` points it
    at the ``_internal`` folder), and falls back to the repository root when the
    app runs from source.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if is_frozen():  # pragma: no cover - defensive, _MEIPASS is always set
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Absolute path to a read-only resource shipped with the app."""
    return bundle_dir().joinpath(*parts)


def source_root() -> Path:
    """Root of the source tree (repo root from source, bundle dir when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def describe() -> dict:
    """Small, serialisable snapshot of the runtime - used by ``--report``."""
    import platform

    from . import APP_TITLE, __version__

    return {
        "app": APP_TITLE,
        "version": __version__,
        "frozen": is_frozen(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "arch": platform.machine(),
        "executable": sys.executable,
        "bundle_dir": str(bundle_dir()),
        "console_visible": sys.stdout is not None,
    }


# --------------------------------------------------------------------------- #
# platform setup
# --------------------------------------------------------------------------- #
def freeze_support() -> None:
    """PyInstaller guard so a spawned child process never re-runs the app."""
    if not is_frozen():
        return
    try:  # pragma: no cover - only meaningful inside a bundle
        import multiprocessing

        multiprocessing.freeze_support()
    except Exception:  # noqa: BLE001 - never let this block start-up
        pass


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Windows: claim an AppUserModelID (taskbar grouping + our own icon).

    Returns True when the call succeeded. Safe to call on any platform: it is a
    no-op everywhere except Windows.
    """
    if not is_windows():
        return False
    try:  # pragma: no cover - Windows only
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:  # noqa: BLE001 - cosmetic only, never fatal
        return False
    return True


# --------------------------------------------------------------------------- #
# crash reporting
# --------------------------------------------------------------------------- #
def log_dir(data_dir: str | Path | None = None) -> Path:
    """Where crash reports go: ``<data dir>/logs`` (created on demand)."""
    if data_dir:
        return Path(data_dir).expanduser() / LOG_DIR_NAME
    from .models import default_data_dir  # local import: keeps this module light

    return default_data_dir() / LOG_DIR_NAME


def crash_log_path(data_dir: str | Path | None = None,
                   when: datetime | None = None) -> Path:
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return log_dir(data_dir) / f"crash-{stamp}.log"


def write_crash_report(text: str, data_dir: str | Path | None = None) -> Path | None:
    """Persist a traceback and return its path (None when that is impossible).

    A frozen GUI app has no console, so an unhandled exception would otherwise
    be completely invisible: the window never appears and nothing is left
    behind. This gives support something to look at.
    """
    try:
        path = crash_log_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = (f"JAUTOMATIC crash report\n"
                  f"time   : {datetime.now().isoformat(timespec='seconds')}\n"
                  f"runtime: {describe()}\n"
                  f"argv   : {sys.argv}\n"
                  f"{'-' * 70}\n")
        path.write_text(header + text.rstrip() + "\n", encoding="utf-8")
        prune_logs(path.parent)
        return path
    except (OSError, ValueError):
        return None


def prune_logs(directory: str | Path, keep: int = MAX_CRASH_LOGS) -> list[Path]:
    """Keep only the newest ``keep`` crash reports; return the removed ones."""
    folder = Path(directory)
    try:
        reports = sorted(folder.glob("crash-*.log"),
                         key=lambda p: (p.name, p.stat().st_mtime), reverse=True)
    except OSError:
        return []
    removed: list[Path] = []
    for old in reports[max(1, keep):]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            continue
    return removed


__all__ = [
    "APP_USER_MODEL_ID", "ORGANIZATION", "SETTINGS_APP", "LOG_DIR_NAME", "MAX_CRASH_LOGS",
    "bundle_dir", "crash_log_path", "describe", "freeze_support", "is_frozen", "is_windows",
    "log_dir", "prune_logs", "resource_path", "set_app_user_model_id", "source_root",
    "write_crash_report",
]
