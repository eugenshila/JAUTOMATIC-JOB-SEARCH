# AI Job Application Assistant

A privacy-first Windows desktop application for finding and prioritising suitable jobs, comparing them against a factual candidate profile, and preparing applications for review. The repository currently implements **Phase 1** of the staged build: local database, desktop shell, dashboard, settings, Master CV upload, structured candidate profile, and job-search configuration.

> **Important:** job-site connectors, AI matching, document generation, browser-assisted applications, Windows Task Scheduler registration, email monitoring, and the installer are deliberately not enabled yet. The application does not submit applications in Phase 1.

## Phase 1 features

- PySide6 Windows desktop shell with dark/light themes and navigation for every planned module.
- Local SQLite database bootstrapped on first launch.
- Structured candidate profile with contact details, experience, education, qualifications, certifications, skills, industries, management experience, achievements, titles, years, locations, languages, and relocation preference.
- Master CV upload for PDF, DOCX, and DOC. Every upload is copied to a timestamped file; the original Master CV is never overwritten.
- Conservative contact prefill from extracted CV text. The user must review and save the profile; no facts are invented.
- Configurable target locations, job types, approved source categories, salary preferences, search frequency, target titles, and application thresholds.
- Dashboard counters ready for jobs, matches, applications, interviews, offers, and outcomes.
- Privacy-conscious local logging and an ignored local-data directory.

## Architecture

The application follows a layered, connector-friendly design so job retrieval and AI providers can be added without coupling them to the UI:

```text
job_assistant/
  app.py                         Qt entry point and application lifecycle
  config/                        paths and safe defaults
  database/                      SQLite connection, schema, repository
  models/                        typed domain value objects
  services/                      CV and profile orchestration
  ai/                            future provider adapters and matching engine
  job_sources/                   one connector per permitted source/feed
  cv_generator/                  future truthful ATS CV generation
  cover_letter_generator/        future cover-letter generation
  application_engine/            future queue and duplicate protection
  browser/                       future permitted browser-assisted flows
  notifications/                 future tray and search-complete notifications
  scheduler/                     future Windows Task Scheduler integration
  security/                      future Credential Manager/secret handling
  ui/                            PySide6 window and feature pages
  templates/                     future document templates
  utils/                         logging and shared utilities
```

The UI depends on the repository rather than SQL. The repository is the seam for moving from SQLite to PostgreSQL later. External job connectors will be required to identify their terms URL and must use official APIs, feeds, or permitted public pages; no CAPTCHA, anti-bot, or access control is bypassed.

## Database schema

`job_assistant/database/schema.py` creates these tables on first launch:

| Table | Purpose |
| --- | --- |
| `users` | Local user identity and profile owner |
| `candidate_profiles` | One structured factual profile per user |
| `cv_versions` | Immutable Master CV uploads and extracted text |
| `job_sources` | Connector names, enabled state, and terms URL |
| `jobs` | Normalised vacancy records and source identifiers |
| `job_matches` | Score, matched/missing/preferred skills, reasons, recommendation |
| `applications` | Application lifecycle, documents, recruiter, interview, follow-up |
| `cover_letters` | Generated letter metadata and body |
| `recruiters` / `interviews` | Contact and interview tracking |
| `application_questions` | Reusable answers; sensitive answers are never guessed |
| `search_history` | Auditable search runs and errors |
| `settings` | JSON-valued local preferences |
| `schema_meta` | Schema version for migrations |

The schema already models the later phases, while Phase 1 only writes the profile, CV, settings, and search-history foundations.

## Local Windows setup

The supported development target is Windows 10/11 with Python 3.11 or newer.

### PowerShell

```powershell
# From the cloned repository
cd JAUTOMATIC-JOB-SEARCH

# If PowerShell blocks activation, this only changes policy for the current shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"

# Start the desktop application
python -m job_assistant.app

# Run the automated tests
python -m pytest
```

### Command Prompt

```bat
cd JAUTOMATIC-JOB-SEARCH
py -3.11 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m job_assistant.app
python -m pytest
```

The first launch creates the database and local files under:

```text
%LOCALAPPDATA%\AI Job Application Assistant\
  job_assistant.sqlite3
  MasterCV\
  Applications\
  Logs\
```

No API key is required for Phase 1. Do not put secrets in the SQLite database, source tree, or log files.

## Development phases

1. **Phase 1 — current:** Windows interface, SQLite schema, settings, Master CV upload, candidate profile, and search configuration.
2. Phase 2 — CV parsing and profile extraction improvements.
3. Phase 3 — permitted job-source connectors and normalisation.
4. Phase 4 — transparent semantic matching and skill-gap analysis.
5. Phase 5 — truthful ATS CV generator (DOCX/PDF).
6. Phase 6 — tailored cover-letter generator.
7. Phase 7 — application approval queue and duplicate protection.
8. Phase 8 — permitted browser-assisted applications; human attention for CAPTCHAs.
9. Phase 9 — application tracking and dashboard analytics.
10. Phase 10 — optional email/recruiter tracking with explicit authorization.
11. Phase 11 — Windows startup/tray and scheduled searches.
12. Phase 12 — signed PyInstaller + Inno Setup/WiX installer.

Each phase should add tests before enabling the next integration boundary.
