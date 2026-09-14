"""SQLite persistence: jobs, applications and run metadata."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from .models import Job, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key       TEXT UNIQUE NOT NULL,
    provider         TEXT NOT NULL,
    provider_board   TEXT NOT NULL,
    provider_job_id  TEXT NOT NULL,
    company          TEXT NOT NULL,
    title            TEXT NOT NULL,
    location         TEXT DEFAULT '',
    url              TEXT DEFAULT '',
    apply_url        TEXT DEFAULT '',
    remote           INTEGER DEFAULT 0,
    description_text TEXT DEFAULT '',
    description_html TEXT DEFAULT '',
    salary_min       REAL,
    salary_max       REAL,
    currency         TEXT DEFAULT '',
    published_at     TEXT,
    updated_at       TEXT,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    seen_count       INTEGER DEFAULT 1,
    score            REAL DEFAULT 0,
    score_reasons    TEXT DEFAULT '[]',
    status           TEXT DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(score);

CREATE TABLE IF NOT EXISTS applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL REFERENCES jobs(id),
    method        TEXT NOT NULL,          -- 'auto' | 'dry'
    endpoint      TEXT DEFAULT '',
    payload       TEXT DEFAULT '{}',      -- JSON of submitted form values
    ok            INTEGER DEFAULT 0,
    http_status   INTEGER,
    response      TEXT DEFAULT '',
    submitted_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applications_job ON applications(job_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------
    def upsert_job(
        self,
        job: Job,
        score: float,
        reasons: List[str],
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert or refresh a job.  Existing user-driven statuses
        (applied/failed/needs_review/manual/hidden) are never overwritten;
        'new' rows adopt the computed status on the next search."""
        now = utcnow_iso()
        row = job.to_row()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    dedupe_key, provider, provider_board, provider_job_id,
                    company, title, location, url, apply_url, remote,
                    description_text, description_html, salary_min, salary_max,
                    currency, published_at, updated_at, first_seen, last_seen,
                    seen_count, score, score_reasons, status
                ) VALUES (
                    :dedupe_key, :provider, :provider_board, :provider_job_id,
                    :company, :title, :location, :url, :apply_url, :remote,
                    :description_text, :description_html, :salary_min, :salary_max,
                    :currency, :published_at, :updated_at, :first_seen, :last_seen,
                    1, :score, :score_reasons, :status
                )
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    last_seen        = excluded.last_seen,
                    seen_count       = jobs.seen_count + 1,
                    url              = COALESCE(NULLIF(excluded.url, ''), jobs.url),
                    apply_url        = COALESCE(NULLIF(excluded.apply_url, ''), jobs.apply_url),
                    description_text = COALESCE(NULLIF(excluded.description_text, ''), jobs.description_text),
                    description_html = COALESCE(NULLIF(excluded.description_html, ''), jobs.description_html),
                    salary_min       = COALESCE(excluded.salary_min, jobs.salary_min),
                    salary_max       = COALESCE(excluded.salary_max, jobs.salary_max),
                    currency         = COALESCE(NULLIF(excluded.currency, ''), jobs.currency),
                    published_at     = COALESCE(excluded.published_at, jobs.published_at),
                    updated_at       = COALESCE(excluded.updated_at, jobs.updated_at),
                    remote           = MAX(jobs.remote, excluded.remote),
                    score            = excluded.score,
                    score_reasons    = excluded.score_reasons
                """,
                {
                    **row,
                    "dedupe_key": job.dedupe_key(),
                    "first_seen": now,
                    "last_seen": now,
                    "score": score,
                    "score_reasons": json.dumps(reasons),
                    "status": status or "new",
                },
            )
        stored = self.get_by_dedupe(job.dedupe_key())
        if stored is None:  # pragma: no cover - insert always yields a row
            raise RuntimeError("upsert failed")
        if status and stored["status"] == "new":
            self.set_status(stored["id"], status)
            stored = self.get(stored["id"])
        return stored

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)

    def get(self, job_id: int) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_dedupe(self, dedupe_key: str) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM jobs WHERE dedupe_key = ?", (dedupe_key,))
        row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def jobs(
        self,
        status: Optional[str] = None,
        statuses: Optional[Iterable[str]] = None,
        min_score: float = 0.0,
        limit: Optional[int] = None,
        order: str = "score",
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM jobs WHERE score >= ?"
        params: List[Any] = [min_score]
        if status:
            query += " AND status = ?"
            params.append(status)
        if statuses:
            query += f" AND status IN ({','.join('?' * len(statuses))})"
            params.extend(statuses)
        order_sql = {
            "score": "score DESC, first_seen DESC",
            "recent": "first_seen DESC",
            "published": "COALESCE(published_at, first_seen) DESC",
        }.get(order, "score DESC")
        query += f" ORDER BY {order_sql}"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        cur = self._conn.execute(query, params)
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def set_status(self, job_id: int, status: str) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?", (status, job_id)
            )
        return cur.rowcount > 0

    def counts(self) -> Dict[str, int]:
        cur = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        )
        return {row["status"]: row["n"] for row in cur.fetchall()}

    # ------------------------------------------------------------------
    # applications
    # ------------------------------------------------------------------
    def record_application(
        self,
        job_id: int,
        method: str,
        endpoint: str,
        payload: Dict[str, Any],
        ok: bool,
        http_status: Optional[int],
        response: str,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO applications
                    (job_id, method, endpoint, payload, ok, http_status, response, submitted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    method,
                    endpoint,
                    json.dumps(payload, ensure_ascii=False),
                    int(ok),
                    http_status,
                    (response or "")[:4000],
                    utcnow_iso(),
                ),
            )

    def recent_applications(self, limit: int = 10) -> List[Dict[str, Any]]:
        cur = self._conn.execute(
            """
            SELECT a.*, j.company, j.title, j.provider
            FROM applications a JOIN jobs j ON j.id = a.job_id
            ORDER BY a.id DESC LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_dict(r) for r in cur.fetchall()]

    def applied_count_since(self, iso_timestamp: str) -> int:
        """Successful auto submissions since a timestamp (daily limit)."""
        cur = self._conn.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE ok = 1 AND method = 'auto' AND submitted_at >= ?",
            (iso_timestamp,),
        )
        return cur.fetchone()["n"]

    # ------------------------------------------------------------------
    # metadata
    # ------------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None
