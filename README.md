# JAUTOMATIC JOB SEARCH

A local-first desktop job-search autopilot. It pulls postings from public job boards,
scores every one against **your** profile, then writes a tailored CV, cover letter and
application e-mail for whichever roles you pick — and keeps track of what you sent, when
to follow up and how the search is going.

No accounts, no cloud, no telemetry: your profile, documents and database live in plain
files on your machine.

```
┌────────────┐   ┌───────────────┐   ┌──────────────────┐   ┌───────────────────┐
│ job boards │ → │ match & rank  │ → │ CV / letter /    │ → │ tracker + follow- │
│ (4 sources)│   │ (0-100 score) │   │ e-mail generator │   │ ups + CSV export  │
└────────────┘   └───────────────┘   └──────────────────┘   └───────────────────┘
```

## Feature tour

**Dashboard** — postings found, tracked applications, materials ready, applications sent,
interviews and follow-ups that are due; top matches; profile-readiness checklist; a live
activity log; quick actions (search, demo import, autopilot, CSV export).

**Profile** — identity, headline, summary, skills, languages, work experience (with
achievement bullets), education, target titles/locations, salary floor, remote-only and
relocation switches, plus letter tone/greeting/signature. Ships with a realistic example
profile to explore the app before filling in your own data.

**Job search** — query + location + remote/min-salary filters, per-source result limits,
exclude keywords. Results are de-duplicated across boards, ranked by match score and shown
with the reasons behind each score ("pay band clears your floor", "title matches your target
role", …). One click generates the whole application pack.

**Applications** — a real tracker: status pipeline (discovered → shortlisted → materials
ready → sent → interview → offer, plus rejected/archived), score, documents 3/3 indicator,
follow-up date with a due warning, notes, and a full event history per application.

**Settings** — enable/disable sources, Adzuna credentials, search defaults, document
options (template, format, letter/e-mail toggles), autopilot thresholds, follow-up window,
dark/light theme, and data tools (open folder, backup, CSV export, clear cache).

**Autopilot (opt-in)** — after an import, generate materials automatically for postings
above your score threshold, up to a per-run limit.

**Follow-up reminders** — marking an application as *sent* schedules a follow-up (default 7
days). When it comes due it shows up on the dashboard with a one-click politely-worded
follow-up e-mail; reminders can be postponed.

| | |
|---|---|
| ![Dashboard](docs/screenshots/04-dashboard.png) | ![Job search](docs/screenshots/02-job-search.png) |
| ![Applications](docs/screenshots/03-applications.png) | ![Profile](docs/screenshots/01-profile.png) |
| ![Generated CV](docs/screenshots/06-cv-preview.png) | ![Daylight theme](docs/screenshots/07-daylight-theme.png) |

## Install & run

```bash
git clone https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH.git
cd JAUTOMATIC-JOB-SEARCH

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python main.py                       # Windows: .venv\Scripts\python main.py
```

Dependencies: **PySide6** (interface), **requests** (job boards), **python-docx** (Word
export). Python 3.10+.

### Command line

`main.py` is also a small CLI, handy for cron jobs or quick checks:

```bash
python main.py --selftest                  # head-less smoke test: models → scraper → docs → export
python main.py --scrape "data engineer"    # print ranked matches, no GUI
python main.py --scrape "python" --offline --limit 10   # demo data only, no network
python main.py --data-dir ./data           # portable, self-contained data directory
```

## Where your data lives

By default in your user data folder (`%APPDATA%\JAUTOMATIC` on Windows,
`~/.local/share/jautomatic-job-search` on Linux/macOS), overridable with `--data-dir` or
`JAUTOMATIC_DATA_DIR`:

```
profile.json          your details (also editable by hand / exportable / importable)
settings.json         sources, defaults, theme
jautomatic.sqlite3    postings + applications (SQLite, WAL)
documents/            generated CVs, cover letters, e-mail drafts, follow-ups
exports/              CSV tracker exports
```

Deleting the folder is a full reset — there is nothing hidden elsewhere.

## How matching works

Every posting gets a 0-100 score, and the UI always shows *why*:

| Weight | Signal | Notes |
|-------:|--------|-------|
| 55 | Keyword coverage | posting tags/skills vs. your skills, experience, education, summary; tag hits count double |
| 20 | Title alignment | overlap with your target titles (falls back to your headline) |
| 10 | Location / remote | remote-friendly postings and your preferred locations score highest |
| 10 | Salary | your floor vs. the advertised band (undisclosed bands score neutrally) |
| 5  | Freshness | ≤3 days old is full marks, then it decays |

The score drives ranking, the autopilot threshold, and which strengths the cover letter and
e-mail highlight (missing keywords are never invented — the generators only re-use what your
profile actually contains).

## Job sources

| Source | Key needed | Notes |
|--------|-----------|-------|
| [Remotive](https://remotive.com) | no | remote roles, searchable JSON API |
| [Arbeitnow](https://www.arbeitnow.com) | no | European board, JSON API |
| [RemoteOK](https://remoteok.com) | no | remote-first board, JSON API |
| [Adzuna](https://developer.adzuna.com) | free app id + key | aggregated listings, country selectable |
| Demo data | no | offline sample postings so the app is always usable |

Sources are queried in parallel; a failing board is reported in the results line ("issues:
Remotive: timed out") and never blocks the others. If *no* board can be reached, the app
offers clearly-labelled demo postings so the workflow can still be explored.

Adding a board = subclass `JobSource` in `jautomatic/services/job_scraper.py` (set `name`,
`label`, implement `fetch()`), then register it in `default_sources()`.

## Generated documents

* **CV** — three templates: `modern` (impact-first, tailored skills line), `classic`
  (traditional ATS layout) and `compact` (one page). Export as `.docx`, `.md` or `.txt`.
* **Cover letter** — assembled deterministically from your profile, the posting text and the
  match analysis, in one of four tones (`professional`, `friendly`, `enthusiastic`,
  `concise`). It quotes the posting, translates your achievements into first person ("Owned
  the platform…" → "I owned the platform…"), and talks about salary only when a band was
  advertised.
* **Application e-mail** — subject line, recipient (when the posting lists a contact address)
  and an attachment list matching the files that were generated.
* **Follow-up e-mail** — short, polite nudge with the days-since-sent baked in.

Generated files are named after you, the company and the role, e.g.
`CV_alex-doe_northwind-analytics_senior-python-engineer.docx`, so a folder full of them stays
sortable.

## Project layout

```
main.py                              entry point (GUI + --selftest / --scrape)
jautomatic/
  models.py                          dataclasses, scoring helpers, SQLite/JSON workspace
  services/
    job_scraper.py                   sources, query filtering, de-dup, offline fallback
    application_pipeline.py          matching, ranking, tracking, autopilot, CSV export
    cv_generator.py                  templates + docx/md/txt exporters
    cover_letter.py                  tone-driven letter drafting
    email_drafter.py                 application + follow-up e-mails
  ui/
    main_window.py                   window shell, background workers, app state
    theme.py                         dark/light palettes, shared widgets
    dashboard_tab.py  profile_tab.py  job_search_tab.py  applications_tab.py  settings_tab.py
tests/                               stdlib unittest suite (85 tests, no network)
tools/screenshot.py                  head-less UI driver used for the screenshots above
tools/genstubs.py                    stub libs so PySide6 runs in headless/CI containers
```

## Development

```bash
.venv/bin/python -m unittest discover -s tests -t .   # 85 tests, no network needed
.venv/bin/ruff check jautomatic main.py tools tests   # lint
.venv/bin/python main.py --selftest                   # end-to-end smoke test
```

The scraping tests run against realistic canned payloads of every board, so the suite needs
no network. `tests/fixtures.py` holds those payloads — update them when a board changes
shape.

`tools/screenshot.py` additionally drives the real UI offscreen end-to-end (seeds demo data,
runs the search tab through its worker, prepares documents, opens a preview, checks the
follow-up reminder) and writes the PNGs used above — a useful regression check after UI
changes.

Headless/CI note: PySide6 links against `libGL`, `libEGL`, `libxkbcommon` and `libdbus-1`,
which slim containers often lack (and you cannot `apt-get install` without root). Build
no-op stubs once and run the UI offscreen:

```bash
python tools/genstubs.py .stublibs
LD_LIBRARY_PATH=.stublibs QT_QPA_PLATFORM=offscreen python tools/screenshot.py
```

## Privacy

Everything runs locally. The only outbound requests are the job-board queries you trigger
(and, when a posting is opened, your browser). Credentials for Adzuna are stored in
`settings.json` in plain text — treat that file like any other config file.

## Ideas for next steps

* Real job-board scrapers with login (LinkedIn/Indeed) and application-form autofill
* More CV templates / user-supplied template files
* Interview-prep notes and question banks per application
* Calendar (ICS) export for interviews and follow-ups
* Installer packaging (MSI/PyInstaller) — intentionally not part of this repository yet
