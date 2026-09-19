"""Atomic JSON writes and verifiable, portable workspace backups."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path: Path, data: dict) -> None:
    """Keep the last readable version, then replace the file atomically."""
    content = json.dumps(data, indent=2).encode("utf-8")
    if path.exists():
        previous = path.read_bytes()
        try:
            parsed = json.loads(previous)
            if not isinstance(parsed, dict):
                raise TypeError("JSON root must be an object")
        except (ValueError, TypeError, UnicodeError):
            recovery = path.with_name(f"{path.stem}.corrupt-{uuid.uuid4().hex[:8]}.json")
        else:
            recovery = path.with_suffix(path.suffix + ".bak")
        _atomic_bytes(recovery, previous)
    _atomic_bytes(path, content)


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_json(path: Path, factory, notices: list[str]):
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text("utf-8"))
            if not isinstance(data, dict):
                raise TypeError("JSON root must be an object")
            value = factory(data)
        except (ValueError, OSError, TypeError, AttributeError):
            continue
        if candidate != path:
            message = f"Recovered {path.name} from its previous saved copy. Check your recent edits."
            if message not in notices:
                notices.append(message)
        return value
    if path.exists():
        message = f"Could not read {path.name}. Defaults loaded; the original file is retained for recovery."
        if message not in notices:
            notices.append(message)
    return factory({})


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_workspace(workspace, parent: Path) -> Path:
    """Caller holds the workspace lock; never overwrite an earlier backup."""
    parent = Path(parent).resolve()
    root = workspace.root.resolve()
    if parent == root or root in parent.parents:
        raise ValueError("Choose a backup folder outside the active data directory.")
    name = f"jautomatic-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    target = parent / name
    staging = parent / (name + ".partial")
    parent.mkdir(parents=True, exist_ok=True)
    # A partial copy is never presented as a successful backup.
    shutil.copytree(root, staging, ignore=shutil.ignore_patterns(
        "jautomatic.sqlite3", "*-wal", "*-shm", "__pycache__", "*.tmp"))
    with closing(sqlite3.connect(staging / "jautomatic.sqlite3")) as destination:
        workspace._conn.backup(destination)
    manifest = {
        "version": 1,
        # Keep the lexical source path as well as the resolved form. On Windows,
        # tempfile paths can mix 8.3 short names (RUNNER~1) and long names
        # (runneradmin); document paths stored in SQLite must still be rebased.
        "source": str(workspace.root.absolute()),
        "source_resolved": str(root),
        "files": {str(p.relative_to(staging).as_posix()): _digest(p)
                  for p in staging.rglob("*") if p.is_file()},
    }
    atomic_json(staging / "backup-manifest.json", manifest)
    verify_backup(staging)
    staging.rename(target)
    return target


def verify_backup(folder: Path) -> dict:
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "backup-manifest.json").read_text("utf-8"))
    files = manifest.get("files", {})
    if manifest.get("version") != 1 or "jautomatic.sqlite3" not in files:
        raise ValueError("Not a supported JAUTOMATIC backup.")
    for relative, digest in files.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"Invalid backup path: {relative}")
        path = (folder / relative).resolve()
        if folder not in path.parents or not path.is_file() or _digest(path) != digest:
            raise ValueError(f"Backup verification failed: {relative}")
    with closing(sqlite3.connect((folder / "jautomatic.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup database integrity check failed.")
    return manifest


def restore_backup(folder: Path, target: Path) -> Path:
    """Restore to a NEW folder; the current workspace is never overwritten."""
    manifest = verify_backup(folder)
    target = Path(target).resolve()
    if target.exists():
        raise ValueError("Restore destination must be a new folder.")
    target.mkdir(parents=True)
    for relative in manifest["files"]:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(folder) / relative, destination)
    source_roots = [Path(manifest["source"])]
    resolved_source = manifest.get("source_resolved")
    if resolved_source:
        source_roots.append(Path(resolved_source))
    with closing(sqlite3.connect(target / "jautomatic.sqlite3")) as db:
        for column in ("cv_path", "cover_letter_path", "email_path", "prep_path"):
            for app_id, value in db.execute(f"SELECT application_id, {column} FROM applications"):
                if not value:
                    continue
                value_path = Path(value)
                relative = None
                for old_root in source_roots:
                    try:
                        relative = value_path.relative_to(old_root)
                        break
                    except ValueError:
                        continue
                if relative is not None:
                    new_value = str(target / relative)
                    db.execute(f"UPDATE applications SET {column}=? WHERE application_id=?",
                               (new_value, app_id))
        db.commit()
    settings_path = target / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text("utf-8"))
        settings["data_dir"] = str(target)
        atomic_json(settings_path, settings)
    return target
