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


def initialize_database(database_path: str | Path) -> None:
    with connect(database_path) as connection:
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
        connection.commit()
