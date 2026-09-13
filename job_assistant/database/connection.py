"""Database connection and schema bootstrap."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .schema import SCHEMA_SQL, SCHEMA_VERSION


def connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    """Apply additive migrations for databases created by an earlier phase."""
    columns = {
        "jobs": {
            "application_email": "TEXT NOT NULL DEFAULT ''",
            "application_method": "TEXT NOT NULL DEFAULT 'website'",
            "application_instructions": "TEXT NOT NULL DEFAULT ''",
        },
        "applications": {
            "cv_path": "TEXT NOT NULL DEFAULT ''",
            "cover_letter_path": "TEXT NOT NULL DEFAULT ''",
            "needs_attention": "INTEGER NOT NULL DEFAULT 0",
        },
    }
    for table, additions in columns.items():
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def initialize_database(database_path: str | Path) -> None:
    with connect(database_path) as connection:
        connection.executescript(SCHEMA_SQL)
        _add_missing_columns(connection)
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
        connection.commit()
