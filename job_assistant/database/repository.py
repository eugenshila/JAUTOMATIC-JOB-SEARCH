"""Repository layer: the UI never needs to know SQLite implementation details."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_assistant.config.settings import DEFAULT_SETTINGS, DEFAULT_SOURCES
from job_assistant.database.connection import connect, initialize_database
from job_assistant.job_sources.base import JobRecord
from job_assistant.models.entities import CandidateProfile


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Repository:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        initialize_database(self.database_path)
        self.user_id = self._ensure_default_user()

    def _connection(self) -> sqlite3.Connection:
        return connect(self.database_path)

    def _ensure_default_user(self) -> int:
        with self._connection() as db:
            row = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            if row:
                user_id = int(row["id"])
                db.execute("INSERT OR IGNORE INTO candidate_profiles(user_id) VALUES(?)", (user_id,))
            else:
                cursor = db.execute("INSERT INTO users(display_name) VALUES('')")
                user_id = int(cursor.lastrowid)
                db.execute("INSERT INTO candidate_profiles(user_id) VALUES(?)", (user_id,))
            for key, value in DEFAULT_SETTINGS.items():
                db.execute(
                    "INSERT OR IGNORE INTO settings(key, value_json) VALUES(?, ?)", (key, _json(value))
                )
            db.executemany(
                "INSERT OR IGNORE INTO job_sources(name, connector_type) VALUES(?, 'public_feed')",
                [(name,) for name in DEFAULT_SOURCES],
            )
            db.commit()
            return user_id

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._connection() as db:
            row = db.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return _loads(row["value_json"], default) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT INTO settings(key, value_json, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=CURRENT_TIMESTAMP",
                (key, _json(value)),
            )
            db.commit()

    def get_settings(self) -> dict[str, Any]:
        with self._connection() as db:
            rows = db.execute("SELECT key, value_json FROM settings").fetchall()
        result = dict(DEFAULT_SETTINGS)
        result.update({row["key"]: _loads(row["value_json"], None) for row in rows})
        return result

    def get_profile(self) -> CandidateProfile:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM candidate_profiles WHERE user_id=?", (self.user_id,)
            ).fetchone()
        if not row:
            return CandidateProfile()
        return CandidateProfile(
            full_name=row["full_name"], email=row["email"], phone=row["phone"],
            headline=row["headline"], summary=row["summary"], experience=row["experience"],
            education=row["education"], qualifications=row["qualifications"],
            certifications=row["certifications"],
            technical_skills=_loads(row["technical_skills_json"], []),
            software_skills=_loads(row["software_skills_json"], []),
            industry_experience=_loads(row["industry_experience_json"], []),
            management_experience=row["management_experience"], achievements=row["achievements"],
            job_titles=_loads(row["job_titles_json"], []), years_experience=row["years_experience"],
            preferred_locations=_loads(row["preferred_locations_json"], []),
            languages=_loads(row["languages_json"], []), relocation_willingness=row["relocation_willingness"],
        )

    def save_profile(self, profile: CandidateProfile | dict[str, Any]) -> None:
        if isinstance(profile, dict):
            profile = CandidateProfile.from_dict(profile)
        values = profile.as_dict()
        with self._connection() as db:
            db.execute(
                """UPDATE candidate_profiles SET full_name=?, email=?, phone=?, headline=?, summary=?,
                experience=?, education=?, qualifications=?, certifications=?, technical_skills_json=?,
                software_skills_json=?, industry_experience_json=?, management_experience=?, achievements=?,
                job_titles_json=?, years_experience=?, preferred_locations_json=?, languages_json=?,
                relocation_willingness=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?""",
                (
                    values["full_name"], values["email"], values["phone"], values["headline"], values["summary"],
                    values["experience"], values["education"], values["qualifications"], values["certifications"],
                    _json(values["technical_skills"]), _json(values["software_skills"]),
                    _json(values["industry_experience"]), values["management_experience"], values["achievements"],
                    _json(values["job_titles"]), values["years_experience"], _json(values["preferred_locations"]),
                    _json(values["languages"]), values["relocation_willingness"], self.user_id,
                ),
            )
            db.execute(
                "UPDATE users SET display_name=?, email=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (values["full_name"], values["email"], self.user_id),
            )
            db.commit()

    def add_master_cv(self, source_path: str | Path, stored_path: str | Path, extracted_text: str) -> int | None:
        source = Path(source_path)
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with self._connection() as db:
            existing = db.execute(
                "SELECT id FROM cv_versions WHERE user_id=? AND sha256=?", (self.user_id, digest)
            ).fetchone()
            if existing:
                return int(existing["id"])
            cursor = db.execute(
                """INSERT INTO cv_versions(user_id, file_name, stored_path, file_type, file_size,
                sha256, extracted_text, is_master) VALUES(?, ?, ?, ?, ?, ?, ?, 1)""",
                (self.user_id, source.name, str(stored_path), source.suffix.lower().lstrip("."),
                 source.stat().st_size, digest, extracted_text),
            )
            cv_id = int(cursor.lastrowid)
            db.execute(
                "UPDATE candidate_profiles SET source_cv_id=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (cv_id, self.user_id),
            )
            db.commit()
            return cv_id

    def latest_master_cv(self) -> sqlite3.Row | None:
        with self._connection() as db:
            return db.execute(
                "SELECT * FROM cv_versions WHERE user_id=? AND is_master=1 ORDER BY created_at DESC LIMIT 1",
                (self.user_id,),
            ).fetchone()

    def dashboard_counts(self) -> dict[str, int]:
        with self._connection() as db:
            counts = {
                "jobs_found": db.execute("SELECT COUNT(*) FROM jobs WHERE date(discovered_at)=date('now')").fetchone()[0],
                "excellent": db.execute("SELECT COUNT(*) FROM job_matches WHERE score >= 90").fetchone()[0],
                "strong": db.execute("SELECT COUNT(*) FROM job_matches WHERE score >= 80 AND score < 90").fetchone()[0],
                "prepared": db.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Documents Prepared','Waiting Approval')").fetchone()[0],
                "submitted": db.execute("SELECT COUNT(*) FROM applications WHERE status='Applied'").fetchone()[0],
                "interviews": db.execute("SELECT COUNT(*) FROM applications WHERE status IN ('Interview','Second Interview')").fetchone()[0],
                "offers": db.execute("SELECT COUNT(*) FROM applications WHERE status='Offer'").fetchone()[0],
                "rejected": db.execute("SELECT COUNT(*) FROM applications WHERE status='Rejected'").fetchone()[0],
            }
        return {key: int(value) for key, value in counts.items()}

    def create_search_history(self, config: dict[str, Any]) -> int:
        with self._connection() as db:
            cursor = db.execute(
                "INSERT INTO search_history(query_config_json, status) VALUES(?, 'started')", (_json(config),)
            )
            db.commit()
            return int(cursor.lastrowid)

    def complete_search_history(self, search_id: int, *, status: str = "completed", jobs_found: int = 0, new_jobs: int = 0, error_message: str = "") -> None:
        with self._connection() as db:
            db.execute(
                """UPDATE search_history SET finished_at=CURRENT_TIMESTAMP, status=?, jobs_found=?,
                new_jobs=?, error_message=? WHERE id=?""",
                (status, jobs_found, new_jobs, error_message, search_id),
            )
            db.commit()

    def seed_sources(self, names: list[str]) -> None:
        with self._connection() as db:
            db.executemany(
                "INSERT OR IGNORE INTO job_sources(name, connector_type) VALUES(?, 'public_feed')",
                [(name,) for name in names],
            )
            db.commit()

    def upsert_job(self, record: JobRecord) -> tuple[int, bool]:
        """Insert a job once, using URL/source ID and then human-readable fields for dedupe."""
        with self._connection() as db:
            source = db.execute("SELECT id FROM job_sources WHERE name=?", (record.source_name,)).fetchone()
            if source is None:
                source_id = int(db.execute(
                    "INSERT INTO job_sources(name, connector_type) VALUES(?, 'public_feed')",
                    (record.source_name,),
                ).lastrowid)
            else:
                source_id = int(source["id"])
            row = None
            if record.job_url:
                row = db.execute("SELECT id FROM jobs WHERE job_url=?", (record.job_url,)).fetchone()
            if row is None and record.external_id:
                row = db.execute(
                    "SELECT id FROM jobs WHERE source_id=? AND external_id=?", (source_id, record.external_id)
                ).fetchone()
            if row is None and record.company and record.title:
                row = db.execute(
                    """SELECT id FROM jobs WHERE lower(company)=lower(?) AND lower(title)=lower(?)
                    AND lower(location)=lower(?)""", (record.company, record.title, record.location)
                ).fetchone()
            values = (
                source_id, record.external_id or None, record.title, record.company, record.location, record.country,
                record.description, record.job_url, record.application_email, record.application_method,
                record.application_instructions, record.salary_min, record.salary_max, record.salary_currency,
                record.job_type, record.workplace_type, record.posted_at or None, record.closing_at or None,
                _json(record.raw_data), hashlib.sha256(record.description.encode("utf-8")).hexdigest(),
            )
            if row is not None:
                db.execute(
                    """UPDATE jobs SET source_id=?, external_id=?, title=?, company=?, location=?, country=?,
                    description=?, job_url=?, application_email=?, application_method=?, application_instructions=?,
                    salary_min=?, salary_max=?, salary_currency=?, job_type=?, workplace_type=?, posted_at=?,
                    closing_at=?, raw_data_json=?, content_hash=? WHERE id=?""", values + (int(row["id"]),)
                )
                db.commit()
                return int(row["id"]), False
            cursor = db.execute(
                """INSERT INTO jobs(source_id, external_id, title, company, location, country, description,
                job_url, application_email, application_method, application_instructions, salary_min, salary_max,
                salary_currency, job_type, workplace_type, posted_at, closing_at, raw_data_json, content_hash)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values
            )
            db.commit()
            return int(cursor.lastrowid), True

    def save_job_match(self, job_id: int, score: float, category: str, *, matched: list[str], missing: list[str], preferred: list[str], reasons: list[str], recommendation: str) -> None:
        with self._connection() as db:
            db.execute(
                """INSERT INTO job_matches(job_id, profile_id, score, category, matched_skills_json,
                missing_skills_json, preferred_skills_json, reasons_json, recommendation, calculated_at)
                VALUES(?, (SELECT id FROM candidate_profiles WHERE user_id=?), ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(job_id, profile_id) DO UPDATE SET score=excluded.score, category=excluded.category,
                matched_skills_json=excluded.matched_skills_json, missing_skills_json=excluded.missing_skills_json,
                preferred_skills_json=excluded.preferred_skills_json, reasons_json=excluded.reasons_json,
                recommendation=excluded.recommendation, calculated_at=CURRENT_TIMESTAMP""",
                (job_id, self.user_id, float(max(0, min(100, score))), category, _json(matched), _json(missing),
                 _json(preferred), _json(reasons), recommendation),
            )
            db.commit()

    def get_job(self, job_id: int) -> sqlite3.Row | None:
        with self._connection() as db:
            return db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def ensure_application(self, job_id: int, match_score: float, *, status: str = "Waiting Approval") -> int:
        with self._connection() as db:
            row = db.execute("SELECT id FROM applications WHERE job_id=?", (job_id,)).fetchone()
            if row:
                db.execute(
                    "UPDATE applications SET match_score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (match_score, row["id"]),
                )
                db.commit()
                return int(row["id"])
            cursor = db.execute(
                """INSERT INTO applications(job_id, profile_id, application_id, status, match_score, closing_date)
                VALUES(?, (SELECT id FROM candidate_profiles WHERE user_id=?), ?, ?, ?,
                (SELECT closing_at FROM jobs WHERE id=?))""",
                (job_id, self.user_id, self.new_application_id(), status, match_score, job_id),
            )
            db.commit()
            return int(cursor.lastrowid)

    def save_application_documents(self, application_id: int, *, cv_path: str, cover_letter_path: str, needs_attention: bool = False) -> None:
        with self._connection() as db:
            db.execute(
                """UPDATE applications SET cv_path=?, cover_letter_path=?, needs_attention=?,
                status='Documents Prepared', updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (cv_path, cover_letter_path, int(needs_attention), application_id),
            )
            db.commit()

    def list_applications(self) -> list[sqlite3.Row]:
        with self._connection() as db:
            return db.execute(
                """SELECT a.*, j.title AS job_title, j.company, j.location, j.job_url,
                j.application_email, j.application_method, j.description, j.source_id
                FROM applications a JOIN jobs j ON j.id=a.job_id
                WHERE a.profile_id=(SELECT id FROM candidate_profiles WHERE user_id=?)
                ORDER BY a.updated_at DESC""", (self.user_id,)
            ).fetchall()

    @staticmethod
    def new_application_id() -> str:
        return f"APP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
