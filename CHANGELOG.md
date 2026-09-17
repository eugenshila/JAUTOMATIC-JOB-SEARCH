# Changelog

All notable changes to JAUTOMATIC JOB SEARCH are documented here.
Format: a relaxed [Keep a Changelog](https://keepachangelog.com/) style —
this project follows [SemVer](https://semver.org/).

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