# Changelog

All notable changes to JAUTOMATIC JOB SEARCH are documented here.
Format: a relaxed [Keep a Changelog](https://keepachangelog.com/) style —
this project follows [SemVer](https://semver.org/).

## [1.11.0] - 2026-09-23

### Added

- **Tasks tab search and websites**: the Tasks tab now has a real **Search
  tasks** button and a website selection, mirroring the Job search tab. Nine
  paid-task websites ship ticked by default — Clickworker, Amazon MTurk, Appen,
  TELUS Digital AI, OneForma, uTest, Microworkers, Prolific and Upwork — and
  the search opens the ticked ones in your browser with your search words
  (query-aware links where the site supports them, e.g. Upwork, OneForma and
  the Clickworker category pages). Ticked websites persist in Settings. These
  platforms publish no public feeds and need your own account, so nothing is
  scraped and no account is linked: sign in yourself and record real offers
  with **Add task details**, exactly as before.
- Profile task suggestions on the Tasks tab are now clickable links straight
  to the matching Clickworker / uTest pages.

## [1.10.0] - 2026-09-23

### Fixed

- Fixed a crash on startup introduced with the Gulf expansion: the Job Search
  tab referenced the "More websites" helper functions without importing them,
  which broke every GUI boot (`browser_boards` NameError) — surfaced by the
  Windows installer test suite and now covered by the full offscreen GUI run.
- The "posted within N days" spinner on Job Search now restores the saved
  freshness limit when the app starts (previously it silently reset to 0 =
  any age).
- Settings → company career boards and Jooble keys round-trip tests now press
  the real "Save settings" button, and the Outlook draft button test matches
  the shipped behaviour (opening the draft marks the application Sent).
- Cross-platform: the classic-Outlook launcher no longer references the
  Windows-only `CREATE_NO_WINDOW` flag unguarded, so the suite runs on Linux.

### Expanded job sites: Gulf focus

- Added **Jobicy** and **Working Nomads** — key-free remote boards whose APIs
  filter by candidate country, including the UAE and the rest of the Gulf.
- Added **Company career boards**: one source that polls live openings straight
  from the employers you list via their public Greenhouse, Lever or Ashby
  endpoints (no API key, no scraping). Ships with a seeded Gulf + logistics
  list (Careem, Tamara, Flexport, project44, FourKites) and is editable in
  Settings; paste a careers-page URL or write `provider:slug`.
- **Jooble went Gulf-wide**: the UAE source keeps its saved settings and key,
  and Saudi Arabia, Qatar, Kuwait and Bahrain join as separate sources, each
  with its own country API key field in Settings (Oman has no Jooble site and
  stays under More websites). Keys migrate into a per-country map on upgrade.
- **More websites** now covers the whole Gulf: Bayt, GulfTalent, NaukriGulf,
  foundit Gulf, Indeed, Dubizzle and Qatar Living join LinkedIn,
  BrighterMonday and Jobberman, each with its own region dropdown (country or
  emirate/city). The old combined labels ("Bayt UAE") keep working.
- Location matching understands **Gulf / GCC / Middle East / MENA** regions and
  Gulf cities (Riyadh, Jeddah, Doha, Kuwait City, Muscat, Manama…); salary
  parsing reads SAR, QAR, KWD, OMR, BHD and more.
- Added a **Gulf logistics** preset next to Africa + UAE logistics, selecting
  every key-free Gulf-capable source at once.
- Added a **posting-freshness limit** (default: posted within the last 5 days,
  adjustable in Settings / search options, 0 = any age). Older postings are
  hidden, as are postings whose date the board does not disclose; auto-refresh
  and autopilot use the same limit.
- Confirmed de-duplication: the same posting returned by several boards is kept
  once (identity is the posting's link).
- The v2 default source selection expands automatically; custom selections are
  preserved.

## [1.9.1] - 2026-09-18

- Prefer installed New Outlook when opening application emails, using its Windows
  launcher and the prepared email file with attachments. Avoid classic Outlook
  activation when New Outlook is available; retain classic/default-app fallbacks.

## [1.9.0] - 2026-09-18

### Outlook application drafts
- Added Open Outlook draft in Applications: generates missing CV/cover-letter
  attachments, fills in a tailored email body and subject, and leaves recipients blank.
- Existing CV and cover-letter files are reused, preserving manual edits.
- Classic Outlook opens a saved draft directly. Other installations open a portable
  .eml file with both attachments; some clients require Forward to edit the message.
- Draft creation never sends mail or marks an application Sent.

## [1.8.0] - 2026-09-18

### Regional job search
- Added MyJobMag feeds for Kenya, Nigeria and South Africa, and JobWeb feeds
  for Kenya, Uganda and Tanzania. The old three-board default expands on upgrade.
- Africa/UAE location matching now recognizes countries and major cities.
  Logistics searches also match procurement, supply chain, warehouse and freight roles.
- Added an Africa + UAE logistics preset and per-source results reporting.
- Added Jooble UAE integration with a user-supplied UAE API key, browser searches
  for LinkedIn and regional boards, and manual import of copied job details.
- Preserve job identifiers in URL query parameters when detecting duplicates.

## [1.7.0] - 2026-09-18

### Application workflow
- Applications now contains unsent jobs. Marking an application Sent moves it
  to the new Sent tab, alongside interviews and offers.
- Interview preparation, interview scheduling and follow-up actions live in Sent.
- Regret records a rejection and moves the application to Archive, cancelling
  follow-up reminders while keeping documents, notes and history.
- Archive includes existing rejected/archived records, status restoration and
  confirmed permanent deletion from the tracker. Document files stay on disk.

## [1.6.0] - 2026-09-17

### Application documents
- Refreshed CV and cover-letter exports with matching Segoe UI typography,
  clear heading hierarchy, A4 margins, and more compact paragraph spacing.
- Cover letters now include a personal letterhead, date, role, and employer.
- Added PDF + editable Word output in Settings. Both files are saved together;
  the tracker and application email use the PDF as the attachment.
- Repeated headless PDF exports retain their Qt application safely. Packaged
  self-tests now verify both PDF and Word files.
- Windows builds prioritize system libraries during dependency discovery to
  prevent unrelated tools' ICU DLLs from breaking Qt at startup.

## [1.5.0] - 2026-09-17

### Interface and search
- Black-and-green default theme, responsive search layout, visible below-target
  results, 70% match labels, qualification gaps, and saved search results.
- Salary comparisons and filters require matching currencies. Monthly ranges
  are annualised; hourly/daily/weekly rates are left unpriced when annual working
  hours are unknown. Unsupported remote location restrictions require review.

### Data and follow-ups
- Profile/settings saves use atomic replacement, previous-version recovery, and
  visible recovery notices. Unreadable originals are preserved.
- Dated SQLite snapshot backups include checksum and integrity verification.
  Restore creates a separate workspace and repairs generated-document paths.
- Drafting a follow-up no longer advances reminders. Mark follow-up sent records
  delivery manually; repeated confirmations on the same day are idempotent.

### Packaging
- Corrected the earlier ProductCode claim: WiX 6 Package/@Id does not pin it.
  ProductCode is now explicitly derived from each release version; UpgradeCode
  stays unchanged for upgrades from older releases.
- Installer rehearsal refuses to remove an existing installed copy.
- Added an option to build using the existing packaging environment without
  updating dependencies.

## [1.4.0] - 2026-09-17

### Search & scoring
- **Below-bar results now land on your Applications page.** Every posting that
  did not reach the qualification bar is imported as a *Proposed* item (when
  you run a search with tracking on) instead of being silently dropped. Review
  them there and promote the ones worth pursuing; if a Proposed role later
  reaches the bar after a profile edit, it is promoted automatically with a
  history note.
- **The result summary explains itself.** Instead of just showing the count,
  the search line now says why: none of the found postings reached the
  `N/100` qualification bar (and then points you at the Proposed items or to
  lowering the bar); a zero-result search for non-tech categories (e.g.
  supply chain / logistics) now tells you the built-in boards are
  tech/remote-focused and that adding free Adzuna API keys under
  Settings → Job boards covers those categories; and any *skipped* board
  (source enabled but missing its API keys) is called out by name.

### Interface
- **Modernized black & green theme** (and the matching daylight variant):
  rounded corners, subtle hover states on cards/buttons/rows, focus rings on
  inputs, styled scrollbars, tab underlines, richer combo-box and spin-button
  styling — still the same colour identity.

### Packaging
- **MSI ProductCode is now pinned.** Every rebuild of the same version installs
  **in place** (repair semantics) instead of creating a side-by-side install.
  Installs created before this change carry a random per-build code — uninstall
  the old installation once, then the pinned code owns upgrades (see
  `docs/release-guide.md`).

### Fixes
- Fixed a crash that could silently drop the search result summary after a
  search finished (the summary previously stuck at “Contacting job boards…”).

[Unreleased]: https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH
[1.4.0]: https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH/releases/tag/v1.4.0
