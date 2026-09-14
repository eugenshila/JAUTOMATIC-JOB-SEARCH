# AI Job Application Assistant

A privacy-first Windows desktop application for finding and prioritising suitable jobs, comparing them against a factual candidate profile, preparing tailored application documents, and assisting with the final application step. The repository currently contains the Phase 1 foundation plus a first working permitted-feed workflow.

> **Safety boundary:** this build prepares documents and opens an official job page or the user's default email compose application. It does not silently submit applications, bypass CAPTCHAs, defeat anti-bot controls, guess sensitive answers, or send email without the user's action.

## Current capabilities

- PySide6 Windows desktop shell with dark/light themes and navigation for every planned module.
- Local SQLite database bootstrapped on first launch, including jobs, match explanations, applications, documents, and search history.
- Structured candidate profile with contact details, experience, education, qualifications, certifications, skills, industries, management experience, achievements, titles, years, locations, languages, and relocation preference.
- Master CV upload for PDF, DOCX, and DOC. Every upload is copied to a timestamped file; the original Master CV is never overwritten.
- Conservative contact prefill from extracted CV text. The user must review and save the profile; no facts are invented.
- Search configuration for locations, job types, salary preferences, target titles, thresholds, and user-approved RSS/XML or JSON feed URLs.
- Automatic search on startup and at the selected interval while the assistant is running, plus a manual Search Jobs Now button.
- Generic public-feed connector that uses only permitted feeds/APIs supplied by the user; feed lines can be labelled `LinkedIn | URL`, `Indeed | URL`, or another catalogued source. No HTML scraping or login automation.
- Duplicate job protection using URL, source ID, company, title, and location.
- Explainable baseline match scoring with matched skills, missing mandatory evidence, preferred gaps, category, reasons, and recommendation.
- Automatic local preparation of truthful ATS-oriented CVs and cover letters in DOCX and PDF when the configured match threshold is reached.
- Application queue with generated-document folder access, official job-page opening, and an **Open email application** action for vacancies that expose an application email address. The email action opens a compose window and never sends the message.
- Privacy-conscious local logging and an ignored local-data directory.

## What is not automated yet

- LinkedIn, Indeed, Glassdoor, Google Jobs, BrighterMonday, MyJobMag, Fuzu, Bayt, GulfTalent, Naukrigulf, and similar sources are listed in the source catalog. They need an official API, licensed/approved partner feed, or a user-approved public feed URL. The generic connector does not scrape those websites.
- The current matching engine is deterministic and explainable. A configurable semantic AI provider is still a future enhancement.
- Browser application submission and Windows Task Scheduler startup are not enabled. **Auto Apply remains disabled by default**, and the queue remains approval-first.
- Email attachments cannot be reliably inserted through a cross-client `mailto:` link, so the generated document folder is opened for the user to attach the CV and cover letter before sending.

## Architecture

The application follows a layered, connector-friendly design so job retrieval and AI providers can be added without coupling them to the UI:

```text
job_assistant/
  app.py                         Qt entry point and application lifecycle
  config/                        paths and safe defaults
  database/                      SQLite connection, schema, repository
  models/                        typed domain value objects
  services/                      search, matching, CV, profile, documents, email
  ai/                            future provider adapters and semantic matching
  job_sources/                   one connector per permitted source/feed
  cv_generator/                  future template-specific CV generation
  cover_letter_generator/        future provider/template adapters
  application_engine/            future permitted browser submission and approvals
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

The schema already models the later phases. The working feed workflow also writes normalised jobs, match explanations, prepared application records, and document paths.

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

No API key is required when using a public feed URL. Do not put secrets in the SQLite database, source tree, or log files.

## Build the MSI on Windows

The MSI source and build script are in `installer/`. An MSI binary is not checked into Git because it is a generated Windows artifact and this development sandbox is Linux-based.

```powershell
# Install WiX Toolset 3 from an elevated PowerShell once
choco install wixtoolset -y

# From the repository root, after activating the virtual environment
.\installer\build-msi.ps1
```

The generated file is `dist\AI Job Application Assistant.msi`. A manual GitHub Actions workflow is also included under `.github/workflows/windows-installer.yml` to build and upload the MSI on a Windows runner.

## Development phases

1. **Phase 1 — current:** Windows interface, SQLite schema, settings, Master CV upload, candidate profile, and search configuration.
2. **Working MVP additions:** permitted RSS/XML/JSON feed retrieval, duplicate protection, explainable baseline matching, DOCX/PDF CV and cover-letter generation, approval queue, and email compose helper.
3. Semantic AI matching, richer CV parsing, and provider-specific job connectors.
4. Template-specific ATS CV styles and richer cover-letter controls.
5. Permitted browser-assisted applications; human attention for CAPTCHAs and sensitive questions.
6. Application tracking, interviews, recruiter/email monitoring, and analytics.
7. Windows system tray, Task Scheduler registration, backups, Credential Manager integration, signing, and release packaging.

Each phase should add tests before enabling the next integration boundary.
