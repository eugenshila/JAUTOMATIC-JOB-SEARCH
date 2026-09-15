"""Shared test scaffolding.

Temporary directories and the app's SQLite workspace follow a teardown rule
that Windows enforces and POSIX does not: **an open file handle blocks deletion
of that file** (``WinError 32: the process cannot access the file because it is
being used by another process``).  :class:`Workspace` keeps its connection
open - in WAL mode, so the ``-wal``/``-shm`` sidecars too - until ``close()``
runs, so a test that lets ``TemporaryDirectory`` clean up first passes on Linux
and errors on Windows CI (``packaging/build.ps1`` runs this suite on
windows-2022 before freezing the app).

``unittest`` runs cleanups in LIFO order, so this base class registers the
directory cleanup *first* and the workspace close *after* it: the connection is
closed before the directory removal starts.  The final cleanup re-checks that
contract, which turns the ordering rule into a plain Linux-detectable
assertion instead of a Windows-only surprise.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from jautomatic.models import Workspace


class WorkspaceTestCase(unittest.TestCase):
    """Test case owning a temp dir plus a :class:`Workspace` inside it."""

    tmp: tempfile.TemporaryDirectory
    workspace: Workspace

    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="jautomatic-test-")
        # Registration order matters (cleanups run last-registered-first):
        #   tmp.cleanup  -> runs last, after the sqlite handle is gone
        #   closed-check -> runs second, proving the handle really is gone
        #   workspace.close -> runs first
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._assert_workspace_closed)
        self.workspace = Workspace(Path(self.tmp.name))
        self.addCleanup(self.workspace.close)

    def _assert_workspace_closed(self) -> None:
        """Tripwire for the ordering rule above (catches regressions on Linux).

        The temporary directory about to be removed still holds a live sqlite
        file; on Windows that alone makes the removal fail. By the time this
        cleanup runs the workspace must already be closed.
        """
        with self.assertRaises(sqlite3.ProgrammingError):
            self.workspace._conn.execute("SELECT 1")
