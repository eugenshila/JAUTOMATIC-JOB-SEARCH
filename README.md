# JAUTOMATIC JOB SEARCH

A local-first desktop job-search autopilot. It pulls postings from public job boards,
scores every one against **your** profile, then writes a tailored CV, cover letter and
application e-mail for whichever roles you pick — and keeps track of what you sent, when
to follow up and how the search is going.

No accounts, no cloud, no telemetry: your profile, documents and database live in plain
files on your machine.

```
┌────────────┐   ┌───────────────┐   ┌──────────────────┐   ┌───────────────────┐
│ job boards │ → │ match & rank  │ → │ CV / letter /    │ → │ tracker, follow-  │
│ (multi-site)│  │ (0-100 score) │   │ e-mail generator │   │ ups, CSV + .ics   │
└────────────┘   └───────────────┘   └──────────────────┘   └───────────────────┘
```

## Feature tour

**Dashboard** — postings found, tracked applications, materials ready, applications sent,
interviews and follow-ups that are due; top matches; profile-readiness checklist; a live
activity log; quick actions (search, demo import, autopilot, CSV export, calendar export).

**Profile** — identity, headline, summary, skills, languages, work experience (with
achievement bullets), education, target titles/locations, salary floor, remote-only and
relocation switches, plus letter tone/greeting/signature. Ships with a realistic example
profile to explore the app before filling in your own data.

**Job search** — query + location + remote/min-salary filters, a posting-freshness window
(default: posted within the last 5 days, adjustable or switch off), per-source result limits,
exclude keywords. Results are de-duplicated across boards, ranked by match score and shown
with the reasons behind each score ("pay band clears your floor", "title matches your target
role", …). One click generates the whole application pack.

**Applications** — prepare unsent jobs, review scores and documents, and keep notes.
After applying, choose **Sent** and click **Apply** to move the record to **Sent**.

Use **Select all** to select the rows currently shown, or Ctrl/Shift-click to
select individual rows. **Archive selected** moves those rows to Archive;
**Archive all shown** archives every row matching the current filters after
confirming the count. Notes, history and documents are retained, and records
can be restored from Archive. Hidden and Sent applications are not included.

In Applications or Archive, use **Delete selected** to permanently remove the
selected records, notes and history after confirming the count. Generated
documents stay on disk. Use Ctrl/Shift-click or **Select all** to choose rows.

**Open Outlook draft** — select an application and click this button to fill a
tailored email subject and body and attach its CV and cover letter. Missing documents
are generated automatically; existing files (including your edits) are reused.
The recipient stays blank for you to enter, review and send. Then mark the application
Sent in the tracker. The app does not send email or detect delivery.

When installed, New Outlook is opened directly through its Windows launcher, using
your existing configured account and an `.eml` file with the body and attachments.
Otherwise, classic Outlook opens a saved compose draft and needs a configured mail
account. If neither is detected, Windows opens the `.eml` file through its file
association; choose Outlook when prompted.
New Outlook versions may open it read-only: use **Forward** to make it editable.
The portable draft remains in your workspace's documents folder.

**Sent** — sent applications, interviews and offers, with follow-up reminders,
interview dates and **Interview prep** materials. Click **Regret** when rejected:
the application moves to **Archive** and follow-up reminders stop.

**Archive** — regrets and archived jobs retain their notes, documents and history.
Change the status to restore a record, or choose **Delete permanently** and confirm
to remove it from the tracker. Generated document files remain on disk.

**Interview prep** — every application has its own prep sheet: free-text notes (company
research, interviewer names, logistics) plus a question bank *derived from that posting*:
technical questions for the tags you cover, honest "gap" questions for the ones you don't,
your own achievements turned into STAR prompts ("Your CV says: 'Cut p95 latency 62%' —
take me through it"), salary/logistics questions with hints anchored on the advertised
band, and questions to ask them. Answers are stored per question, starred questions float
up, you can add your own, regenerating never overwrites what you wrote, and the sheet
exports to Markdown/Word next to your CV.

**Settings** — enable/disable sources, company career boards, Adzuna and Jooble keys, the posting-age limit, search defaults, document
options (template, format, letter/e-mail toggles, custom-template helpers), autopilot
thresholds, follow-up window, dark/light theme, and data tools (open folder, backup, CSV
export, calendar export, clear cache).

**Autopilot (opt-in)** — after an import, generate materials automatically for postings
above your score threshold, up to a per-run limit.

**Follow-up reminders** — marking an application as *sent* schedules a follow-up (default 7
days). When it comes due it shows up on the dashboard with a one-click politely-worded
follow-up e-mail; reminders can be postponed.

**Calendar export (.ics)** — interviews and follow-ups become RFC 5545 calendar events you
can drop into Google Calendar, Outlook or Apple Calendar. Interviews carry the date/time
you enter in the tracker (all-day when you only give a day, timed otherwise, defaulting to
one hour); follow-ups become all-day events on their due date. UIDs are stable, so
re-importing a fresh export updates events instead of duplicating them. Available from the
Applications tab, the dashboard quick actions and Settings → Data.

**Assisted application-form autofill** — point `tools/autofill.py` at an application form
(Greenhouse / Lever / Workday / plain HTML5 shapes) and it plans which of your profile
values go into which fields, then types them into a real browser for you to review:
identity, contact details, links, salary expectation, years of experience, the CV from
your application pack, yes/no eligibility questions you have answered, and custom
answers you keep in `profile.json` under `extra.autofill`. Ambiguous or unanswered
fields are listed for you, EEO/disclosure questions are left alone, and password fields
are never touched. The tool deliberately stops there: **you** log in (a persistent
browser profile keeps you signed in) and **you** press Submit — automated login and
auto-submission are the terms-of-service-breaching, account-banning kind of automation
and are out of scope by design.

| | |
|---|---|
| ![Dashboard](docs/screenshots/04-dashboard.png) | ![Job search](docs/screenshots/02-job-search.png) |
| ![Applications](docs/screenshots/03-applications.png) | ![Profile](docs/screenshots/01-profile.png) |
| ![Generated CV](docs/screenshots/06-cv-preview.png) | ![Daylight theme](docs/screenshots/07-daylight-theme.png) |

## Install & run

**Windows users:** grab `JAUTOMATIC-Setup-<version>-x64.msi` from the
[releases page](https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH/releases) and
double-click it — details, SmartScreen notes and uninstall info are in
[`docs/install-windows.md`](docs/install-windows.md). To run from source instead:

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

The assisted autofill driver is a separate tool (the browser half needs the optional
`playwright` dependency; the planning half is pure stdlib):

```bash
python tools/autofill.py --form tests/fixtures/forms/greenhouse.html --plan  # offline plan
python tools/autofill.py --url https://boards.greenhouse.io/acme/jobs/123    # assisted fill
python tools/autofill.py --url … --application <id>   # attach that application's CV/letter
pip install playwright && playwright install chromium # one-off, enables --url
```

## Where your data lives

By default in your user data folder (`%APPDATA%\JAUTOMATIC` on Windows,
`~/.local/share/jautomatic-job-search` on Linux/macOS), overridable with `--data-dir` or
`JAUTOMATIC_DATA_DIR`:

```
profile.json          your details (also editable by hand / exportable / importable)
settings.json         sources, career boards, keys, defaults, theme
jautomatic.sqlite3    postings + applications (SQLite, WAL) incl. interview-prep sheets
documents/            generated CVs, cover letters, e-mail drafts, follow-ups, prep sheets
exports/              CSV tracker exports + .ics calendar exports
templates/            your own CV templates (*.md) — see docs/cv-templates.md
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

**Reading your score:** below **50** the match is *weak*, **50–69** is *possible*, **70+**
is *strong*, **85+** *excellent*. The default qualification bar is **80/100** (adjust it in
Settings → Automatic actions or on the Search tab). Search results that do not reach the bar
are not auto-queued for applications — instead they appear on the **Applications** page as
**Proposed**, where you can review and promote them (promotion is automatic once a profile
edit pushes them over the bar).

**Job Search keeps every returned result visible**, with a percentage match and an
Eligible / Below target label. Use **Eligible only** to filter to the default **70%**
qualification target. Details show matched keywords, gaps, and the reasons for the score;
this is a profile-match estimate, not confirmation of an employer's eligibility rules.
Your latest results are saved even with automatic queuing disabled, and are rescored when
you return after editing your profile. Imported URLs also appear directly in Job Search.

The default appearance is **Black & Green**: near-black surfaces, emerald accents,
roomier navigation, collapsible search options, and a responsive results/detail layout.
Existing saved theme preferences are preserved; change them in **Settings → Appearance**.

## Job sources

| Source | Key needed | Notes |
|--------|-----------|-------|
| [Remotive](https://remotive.com) | no | remote roles, searchable JSON API |
| [Arbeitnow](https://www.arbeitnow.com) | no | European board, JSON API |
| [RemoteOK](https://remoteok.com) | no | remote-first board, JSON API |
| [Himalayas](https://himalayas.app) | no | remote roles worldwide incl. Kenya/Africa/UAE, JSON API |
| [Jobicy](https://jobicy.com) | no | remote roles worldwide incl. UAE/Gulf, JSON API |
| [Working Nomads](https://www.workingnomads.com) | no | curated remote roles, JSON API |
| [UAE AI jobs](https://artificial.ae) | no | UAE AI & tech roles (Dubai, Abu Dhabi), JSON API |
| Company career boards | no | live openings from the employers you list, via public Greenhouse / Lever / Ashby APIs |
| [Adzuna](https://developer.adzuna.com) | free app id + key | aggregated listings, 21 countries incl. South Africa |
| MyJobMag | no | publisher feeds for Kenya, Nigeria and South Africa |
| JobWeb | no | publisher feeds for Kenya, Uganda and Tanzania |
| [Jooble](https://ae.jooble.org/api/about) | one key per country | UAE, Saudi Arabia, Qatar, Kuwait and Bahrain vacancies; enter each country's key in Settings (Oman has no Jooble site) |
| [LinkedIn](https://www.linkedin.com/jobs/search) | browser session | open a search, then import the URL or use **Paste job details** |
| Bayt, GulfTalent, NaukriGulf, foundit Gulf, Indeed, Dubizzle, Qatar Living, BrighterMonday, Jobberman | browser access | open from **More websites** (each with its own region dropdown), then paste the job details to track it |
| Demo data | no | offline sample postings so the app is always usable |

Sources are queried in parallel; a failing board is reported in the results line ("issues:
Remotive: timed out") and never blocks the others. Results are de-duplicated by their
posting link, so the same vacancy returned by several boards appears once. A freshness
limit (default 5 days, Settings or the search options) hides older postings — and any
posting whose date the board does not disclose, because its age cannot be confirmed. If *no* board can be reached, the app
offers clearly-labelled demo postings so the workflow can still be explored.

For regional logistics vacancies, click **Gulf logistics** or **Africa + UAE logistics**,
then **Search jobs**. Both presets include on-site jobs and search related procurement,
warehouse, freight and supply-chain titles. Africa matches individual African countries;
the Gulf matches the UAE, Saudi Arabia, Qatar, Kuwait, Oman and Bahrain — including city
names such as Dubai, Riyadh, Doha or Muscat. Feed coverage varies by publisher.
The previous default source selection is expanded automatically on upgrade; custom
source selections remain intact.

**Company career boards** poll each listed employer's public job board directly
(Greenhouse, Lever or Ashby — the same JSON their careers pages read), so a posting
appears the day the company publishes it. Add boards in Settings by pasting a
careers-page URL (`https://jobs.lever.co/kitopi`) or writing `provider:slug`
(`greenhouse:careem`); a board that has moved is skipped and reported. Boards are
fetched in parallel with a cap of 12 per search.

Jooble runs one website per country and each country needs its own free API key
(a US key will not return UAE jobs, and vice versa). Free keys are limited to 500
lifetime requests; automatic refresh also uses this quota. Without keys, the Gulf
**More websites** menu (Bayt, GulfTalent, NaukriGulf, foundit Gulf, Indeed, Dubizzle,
Qatar Living) opens the same searches in your browser.
**Paste job details** saves a copied posting for matching and application preparation;
it does not connect a LinkedIn account or submit applications.

Adding a board = subclass `JobSource` in `jautomatic/services/job_scraper.py` (set `name`,
`label`, implement `fetch()`), then register it in `default_sources()`. Company ATS
boards live in `jautomatic/services/company_boards.py`.

## Generated documents

* **CV** — six built-in templates: `modern` (impact-first, tailored skills line), `classic`
  (traditional ATS layout), `compact` (one page), `functional` (skills-first, evidence
  grouped under the posting's keywords), `executive` (quantified achievements first) and
  `technical` (relevant/other skills split, a stack line per role). Export as `.docx`, `.md`
  or `.txt`. **Your own templates** are plain `.md` files in `<data dir>/templates/` using a
  small, safe Jinja-like syntax (`{{ name }}`, `{% for role in experience %}`,
  `{% if job %}`); Settings can write an annotated starter file for you. Full variable
  reference in [`docs/cv-templates.md`](docs/cv-templates.md).
* **Cover letter** — assembled deterministically from your profile, the posting text and the
  match analysis, in one of four tones (`professional`, `friendly`, `enthusiastic`,
  `concise`). It quotes the posting, translates your achievements into first person ("Owned
  the platform…" → "I owned the platform…"), and talks about salary only when a band was
  advertised.
* **Application e-mail** — subject line, recipient (when the posting lists a contact address)
  and an attachment list matching the files that were generated.
* **Follow-up e-mail** — short, polite nudge with the days-since-sent baked in.
* **Interview prep sheet** — notes + question bank with your answers, grouped by category
  (`PREP_<you>_<company>_<role>.md`, or `.docx`).

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
    company_boards.py                employer ATS boards (Greenhouse/Lever/Ashby), Gulf browser catalog
    application_pipeline.py          matching, ranking, tracking, autopilot, CSV export
    calendar_export.py               RFC 5545 .ics export (interviews + follow-ups)
    autofill.py                      deterministic form parser, taxonomy, fill planner
    autofill_browser.py              assisted Playwright hand-off (optional dependency)
    cv_generator.py                  6 built-in templates, custom-template registry, exporters
    template_engine.py               safe Jinja-subset renderer for user-supplied templates
    interview_prep.py                per-application notes + derived question bank
    cover_letter.py                  tone-driven letter drafting
    email_drafter.py                 application + follow-up e-mails
  ui/
    main_window.py                   window shell, background workers, app state
    interview_prep_dialog.py         notes + question bank window (from the Sent tab)
    theme.py                         dark/light palettes, shared widgets
    dashboard_tab.py  profile_tab.py  job_search_tab.py  applications_tab.py  settings_tab.py
tests/                               stdlib unittest suite (262 tests, no network)
tests/fixtures/forms/                committed ATS form fixtures for the autofill engine
tools/screenshot.py                  head-less UI driver used for the screenshots above
tools/autofill.py                   autofill CLI (--plan offline, --url assisted)
tools/genstubs.py                    stub libs so PySide6 runs in headless/CI containers
```

## Development

```bash
.venv/bin/python -m unittest discover -s tests -t .   # 262 tests, no network needed
.venv/bin/ruff check jautomatic main.py tools tests   # lint
.venv/bin/python main.py --selftest                   # end-to-end smoke test
```

The scraping tests run against realistic canned payloads of every board, so the suite needs
no network. `tests/fixtures.py` holds those payloads — update them when a board changes
shape.

The autofill engine is tested the same way: `tests/fixtures/forms/` holds committed HTML
captures of Greenhouse / Lever / Workday / generic application-form shapes, and
`tests/test_autofill.py` checks the fill plan they produce (what fills, what is flagged for
review, what is left alone). The only untested seam is the Playwright hand-off in
`autofill_browser.py` — you can exercise everything else offline:

```bash
.venv/bin/python tools/autofill.py --form tests/fixtures/forms/greenhouse.html --plan
```

`tools/screenshot.py` additionally drives the real UI offscreen end-to-end (seeds demo data,
runs the search tab through its worker, prepares documents, opens a preview, checks the
follow-up reminder) and writes the PNGs used above — a useful regression check after UI
changes. Renders are byte-reproducible: the driver uses a fixed data directory (wiped on
start) and a frozen clock, so two runs produce identical PNGs — `sha256sum` them to verify.

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

* ~~Real job-board scrapers with login (LinkedIn/Indeed) and application-form autofill~~ —
  *autofill is done* (assisted scope, see above). Logged-in scraping of LinkedIn/Indeed
  remains deliberately unbuilt: automated login breaches their terms of service and gets
  accounts banned, so unless someone deliberately accepts that risk, public boards remain
  the way in.
* ~~More CV templates / user-supplied template files~~ — done: six built-ins plus
  `templates/*.md` ([reference](docs/cv-templates.md))
* ~~Interview-prep notes and question banks per application~~ — done
* ~~Calendar (ICS) export for interviews and follow-ups~~ — done
* ~~Installer packaging (MSI/PyInstaller)~~ — done: PyInstaller freeze + WiX 6 MSI installer ([docs/install-windows.md](docs/install-windows.md))
