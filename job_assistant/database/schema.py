"""SQLite schema for the local-first application.

All tables use SQLite-compatible types and timestamps. JSON columns are kept as
TEXT so the same logical model can migrate cleanly to PostgreSQL JSONB later.
"""
SCHEMA_SQL = r'''
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    headline TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    experience TEXT NOT NULL DEFAULT '',
    education TEXT NOT NULL DEFAULT '',
    qualifications TEXT NOT NULL DEFAULT '',
    certifications TEXT NOT NULL DEFAULT '',
    technical_skills_json TEXT NOT NULL DEFAULT '[]',
    software_skills_json TEXT NOT NULL DEFAULT '[]',
    industry_experience_json TEXT NOT NULL DEFAULT '[]',
    management_experience TEXT NOT NULL DEFAULT '',
    achievements TEXT NOT NULL DEFAULT '',
    job_titles_json TEXT NOT NULL DEFAULT '[]',
    years_experience TEXT NOT NULL DEFAULT '',
    preferred_locations_json TEXT NOT NULL DEFAULT '[]',
    languages_json TEXT NOT NULL DEFAULT '[]',
    relocation_willingness TEXT NOT NULL DEFAULT '',
    source_cv_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS cv_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES candidate_profiles(id) ON DELETE SET NULL,
    file_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL,
    extracted_text TEXT NOT NULL DEFAULT '',
    is_master INTEGER NOT NULL DEFAULT 1 CHECK (is_master IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cv_versions_user ON cv_versions(user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cv_versions_sha ON cv_versions(user_id, sha256);

CREATE TABLE IF NOT EXISTS job_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    connector_type TEXT NOT NULL DEFAULT 'manual',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    terms_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES job_sources(id) ON DELETE SET NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    job_url TEXT NOT NULL DEFAULT '',
    application_email TEXT NOT NULL DEFAULT '',
    application_method TEXT NOT NULL DEFAULT 'website',
    application_instructions TEXT NOT NULL DEFAULT '',
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT NOT NULL DEFAULT '',
    job_type TEXT NOT NULL DEFAULT '',
    workplace_type TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    closing_at TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_data_json TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL DEFAULT '',
    UNIQUE(source_id, external_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_url ON jobs(job_url) WHERE job_url <> '';
CREATE INDEX IF NOT EXISTS idx_jobs_discovered ON jobs(discovered_at DESC);

CREATE TABLE IF NOT EXISTS job_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES candidate_profiles(id) ON DELETE CASCADE,
    score REAL NOT NULL DEFAULT 0 CHECK (score >= 0 AND score <= 100),
    category TEXT NOT NULL DEFAULT 'Low Match',
    matched_skills_json TEXT NOT NULL DEFAULT '[]',
    missing_skills_json TEXT NOT NULL DEFAULT '[]',
    preferred_skills_json TEXT NOT NULL DEFAULT '[]',
    reasons_json TEXT NOT NULL DEFAULT '[]',
    recommendation TEXT NOT NULL DEFAULT 'SKIP',
    calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, profile_id)
);
CREATE INDEX IF NOT EXISTS idx_job_matches_score ON job_matches(score DESC);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL REFERENCES candidate_profiles(id) ON DELETE RESTRICT,
    application_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'Discovered',
    match_score REAL NOT NULL DEFAULT 0,
    cv_version_id INTEGER REFERENCES cv_versions(id) ON DELETE SET NULL,
    cover_letter_id INTEGER,
    date_applied TEXT,
    closing_date TEXT,
    recruiter_id INTEGER,
    interview_date TEXT,
    follow_up_date TEXT,
    cv_path TEXT NOT NULL DEFAULT '',
    cover_letter_path TEXT NOT NULL DEFAULT '',
    needs_attention INTEGER NOT NULL DEFAULT 0 CHECK (needs_attention IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS cover_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    file_docx TEXT,
    file_pdf TEXT,
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recruiters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    scheduled_at TEXT,
    interview_type TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS application_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question_key TEXT NOT NULL,
    question_label TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    sensitive INTEGER NOT NULL DEFAULT 0 CHECK (sensitive IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, question_key)
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'started',
    sources_json TEXT NOT NULL DEFAULT '[]',
    query_config_json TEXT NOT NULL DEFAULT '{}',
    jobs_found INTEGER NOT NULL DEFAULT 0,
    new_jobs INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''

SCHEMA_VERSION = "2"
