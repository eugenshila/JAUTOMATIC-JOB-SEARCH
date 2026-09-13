# System architecture

## Runtime boundaries

```text
PySide6 UI
   │ signals / view models
   ▼
Application services
   ├── CV/profile service        (local files + extraction)
   ├── Search orchestrator       (configured RSS/XML/JSON feeds)
   ├── Matching engine           (explainable 0–100 baseline; semantic provider later)
   ├── Document generators       (truthful DOCX/PDF output)
   └── Application engine        (approval-first queue + email compose helper)
   │
   ▼
Repository / SQLite adapter
   │
   ▼
Local data directory
```

The UI is not allowed to scrape sites, construct SQL, or call an AI provider directly. Future connectors implement a common interface and report their terms URL, rate limits, and whether an application flow is manual-only. AI calls must be configurable and must receive only the minimum data needed; the local-first default keeps the Master CV on the user's machine.

## Matching model (planned)

The matching engine will normalise a job into mandatory, preferred, optional, and unknown requirements. It will combine semantic similarity with explicit evidence checks. Mandatory requirements have a larger weight and an absent mandatory requirement is shown separately from a missing nice-to-have. Every score persists its reasons, matched skills, missing skills, and recommendation in `job_matches`; a score without an explanation is not considered complete.

Default thresholds are stored in settings and are user-editable:

- 90–100: Excellent Match
- 80–89: Strong Match
- 70–79: Good Match
- 60–69: Possible Match
- below 60: Low Match
- prepare documents at 75%
- priority application at 85%
- do not prepare below 65%

## Data safety decisions

- Master CV uploads are copied to timestamped files and content-addressed in `cv_versions`; an existing file is never overwritten.
- Sensitive application answers are stored separately and are never inferred from a CV or job description.
- Logs have a filter for common credentials and do not log CV text, passwords, tokens, or API keys.
- Duplicate protection will check source/job ID, URL, company, title, and location before creating an application.
- Auto-apply remains off by default and will require a permitted flow, truthful answers, no CAPTCHA bypass, and user-configured approval.

## Windows packaging plan

The production build will use PyInstaller to produce the application bundle and Inno Setup or WiX for installation. The installer will create the data directories, shortcuts, uninstall entry, and (only after explicit opt-in) a Windows Task Scheduler task that launches the app minimized. Phase 1 stores the startup preference but does not register a task.
