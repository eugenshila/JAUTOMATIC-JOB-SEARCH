# Changelog

All notable changes to JAUTOMATIC JOB SEARCH are documented here.
Format: a relaxed [Keep a Changelog](https://keepachangelog.com/) style —
this project follows [SemVer](https://semver.org/).

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
