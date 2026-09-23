# Windows installer packaging

This folder builds the thing users download: a signed MSI that installs a
frozen (PyInstaller) JAUTOMATIC JOB SEARCH into `%ProgramFiles%`, with a Start
Menu shortcut and an Add/Remove Programs entry. Users should start at
[`docs/install-windows.md`](../docs/install-windows.md); this file is for
maintainers.

## Pipeline

```
main.py ──PyInstaller──▶ dist\jautomatic\ ──Artifact Signing──▶ *.exe/*.dll signed
        (jautomatic.spec)   │ gen_files_wxs.py harvests ──▶ files.wxs
                            ▼
jautomatic.wxs + files.wxs ──wix build──▶ dist\JAUTOMATIC-Setup-<ver>-x64.msi
        │                                             │ Artifact Signing
        ▼                                             ▼
                          verify-install.ps1: install → --selftest → uninstall → report
```

| File | Role |
|------|------|
| `build_info.py` | Single source of truth: version, WiX pin, signing input names. Also generates the exe version resource. |
| `jautomatic.spec` | PyInstaller one-dir spec (GUI, no console, no UPX). |
| `jautomatic.wxs` | Hand-written WiX shell: identity, upgrades, folders, shortcut, ARP. |
| `gen_files_wxs.py` | Harvests the frozen dir into `files.wxs` (deterministic Ids + stable GUIDs). |
| `gen_icon.py` | Draws `jautomatic.ico` with stdlib only (reproducible, no Pillow). |
| `build.ps1` | Orchestrates everything: venv → tests → freeze → (sign) → package → (sign MSI). |
| `verify-install.ps1` | Installs the MSI, runs the **installed** exe's `--selftest`, uninstalls, writes `install-report.json`. |

`files.wxs`, `version_info.txt` and everything under `dist/` / `build/` are
generated at build time and intentionally not checked in.

## Quick start (on Windows)

Prerequisites: Windows 10+, Python 3.10+, [.NET 8 SDK](https://dotnet.microsoft.com/download)
(WiX itself arrives via `dotnet tool restore` — no separate install).

```powershell
packaging\build.ps1
packaging\verify-install.ps1 -MsiPath dist\*.msi   # needs an elevated prompt
```

The first command prints the MSI path when it succeeds; the second installs
it, smoke-tests the installed exe, uninstalls it and writes
`dist\install-report.json`. CI runs exactly these two commands (plus signing —
see below), so a green local run means a green `windows-installer` run.

Useful switches: `build.ps1 -SkipTests`, `-SkipPackage` (freeze only),
`-SkipFreeze -SkipTests` (package an existing `dist\jautomatic`), `-Sign`
(sign locally — needs the signing environment from the next section).

## Signing

Releases are signed with **Azure Artifact Signing** (Microsoft's managed
signing service — called *Trusted Signing* until the January 2026 rebrand;
older docs and blog posts use the old name for the same service). There are
two signing rounds per build: the frozen `.exe`/`.dll` files *before* `wix
build`, and the `.msi` itself after it. Everything is RFC 3161-timestamped —
Artifact Signing certificates live ~72 hours, so without a timestamp the
signature would read as expired within days.

**CI (releases).** The workflow uses the official
[`azure/artifact-signing-action`](https://github.com/Azure/artifact-signing-action)
with OIDC — no certificates or tokens in secrets. Setup, once per repo:

1. In Azure, create an Artifact Signing account + a *Public Trust* certificate
   profile (any region; note the account's **Account URI**).
2. Register an Entra app, add a federated credential for this repo
   (`repo:eugenshila/JAUTOMATIC-JOB-SEARCH:ref:refs/heads/main`), and grant it
   the **Artifact Signing Certificate Profile Signer** role on the profile.
3. Set repo **variables** `AZURE_SIGNING_ENDPOINT` (= the Account URI, e.g.
   `https://eus.codesigning.azure.net/`), `AZURE_SIGNING_ACCOUNT`,
   `AZURE_SIGNING_PROFILE`, and repo **secrets** `AZURE_CLIENT_ID`,
   `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.

   The variable names are single-sourced in `build_info.py`
   (`SIGN_VAR_*`) and asserted against the workflow by
   `tests/test_packaging.py` — rename them in one place or not at all.

Without that configuration the workflow still builds and verifies the MSI; it
just skips both signing rounds, so pull-request builds stay green and only
release builds from `main` come out signed.

**Local (`build.ps1 -Sign`).** Reads the same three values from
`AZURE_SIGNING_*` environment variables and signs via `signtool` + the
Artifact Signing dlib (downloaded from NuGet on first use, using whatever
Azure identity your machine already has — `az login`, Visual Studio, or an
interactive browser prompt). If Microsoft has renamed the client package since
this was written and the download fails, set `ARTIFACT_SIGNING_DLIB` to the
dlib path from the current Microsoft quickstart and re-run.

**Eligibility (for contributors).** Microsoft currently limits Artifact
Signing to organizations in the US, Canada, the EU and the UK, and to
individual developers in the US and Canada. Outside those regions the
fallback is a traditional OV/EV code-signing certificate from a CA — either
way, `verify-install.ps1` records the Authenticode status of the MSI and the
exe in its report. Those entries are informational, not gating: pull-request
builds are unsigned by design, and a release engineer confirms they read
`Valid` on signed builds.

**SmartScreen, honestly.** Signing removes the "unknown publisher" label and
lets *publisher* reputation accrue across releases — it does **not** buy
instant trust. Per Microsoft's current guidance no certificate type skips the
initial SmartScreen prompt, EV included (since 2024). Expect a prompt on the
first signed release; keep the publisher identity stable and later releases
inherit the reputation. The user-facing wording lives in
[`docs/install-windows.md`](../docs/install-windows.md) — keep the two in sync.

## Upgrading WiX

The WiX Toolset version is pinned in exactly two places that must agree
(`build.ps1` fails otherwise, and so does `test_packaging.py`):

1. `WIX_VERSION` in `packaging/build_info.py`
2. the `wix` entry in `.config/dotnet-tools.json`

We currently build against **6.0.2** (WiX v6 servicing line). Note
that WiX v5 left community support on **2026-02-05** (v6 went supported in
its place; v6.0.2 and v7.0.0 are the current servicing lines). The bump
is a deliberate two-line change plus a verify run:

1. Set both pins above to the target version (e.g. `6.0.2`).
2. Know the deltas (both small for this package):
   - The core authoring namespace, `http://wixtoolset.org/schemas/v4/wxs`,
     is unchanged from v4 through v7 — neither `.wxs` file needs a
     namespace edit.
   - WiX v6 *prefers* a human-readable `Package/@Id` (e.g.
     `Id="JAUTOMATIC.JobSearch"`) over the `UpgradeCode` GUID — you may use
     one or the other, not both. Our `jautomatic.wxs` keeps the GUID form,
     which v6 still accepts; migrating the Id is optional. If you do
     migrate it, update the `test_upgrade_code_is_frozen` tripwire in
     `tests/test_packaging.py` in the same commit, and confirm on a VM that
     the new package still major-upgrades an install from the previous
     release (the Id string hashes to the same upgrade family — verify,
     don't assume).
3. Run the full loop on Windows and confirm every check passes:
   `packaging\build.ps1` then `packaging\verify-install.ps1 -MsiPath dist\*.msi`.

## CI

`.github/workflows/windows-installer.yml` runs on pushes to `main`, pull
requests and manual dispatch: freeze (venv + full test suite + PyInstaller)
→ sign frozen binaries (only when signing is configured) → package (`wix
build`) → sign MSI (ditto) → `verify-install.ps1` → upload the MSI and the
install report + logs as artefacts. The actual `wix build` and MSI install
happen **only** here and on a dev's Windows box — the Linux sandbox this repo
is often edited from cannot run either, so treat a red `windows-installer`
run as the installer test suite failing and fix it before merging.

Publishing a GitHub Release is a separate, manual workflow
(`.github/workflows/publish-release.yml`): it downloads the MSI from a green
`windows-installer` run and attaches it to `v<version>`. That download has to
happen on a GitHub runner — Azure blob storage for Actions artefacts is not
reachable from every authoring environment. See
[`docs/release-guide.md`](../docs/release-guide.md).

## Troubleshooting

* `WiX pin mismatch` — `build_info.WIX_VERSION` and `.config/dotnet-tools.json`
  disagree; see "Upgrading WiX" above.
* `wix build` errors about `$(var.FrozenDir)` — you invoked `dotnet wix build`
  by hand; use `build.ps1`, which passes `-d FrozenDir=` (with no trailing
  backslash — it would escape the closing quote).
* `signtool.exe not found` — install the Windows SDK (or the VS "Desktop
  development with C++" workload); CI runners already have it.
* Signing hangs at "Submitting digest" — usually the Azure identity: run
  `az login` first, or check the federated credential / role assignment.
* `verify-install` fails at `--selftest` — the *installed* exe is broken
  (missing Qt plugin, frozen-path bug…); reproduce with
  `dist\jautomatic\jautomatic.exe --selftest` and read the traceback.
* SmartScreen still prompts on a signed build — expected until publisher
  reputation accrues; see "SmartScreen, honestly" above, not a bug.

## Follow-ups 9–11 — fixed

During installer hardening, eleven findings came up; 1–8 were fixed in the
release this ships with. The remaining three were fixed in the follow-up
change that also lands this note — they are recorded here because they shaped
installer decisions, and to document what the fixes guarantee:

**Follow-up 9 — `slugify` collisions (fixed).** Document stems are built from
`slugify` output, which normalises hard (truncation, punctuation loss, the
`"untitled"` fallback for non-Latin names), so two applications could share a
stem and overwrite each other's files in `documents/`. Generation now goes
through `models.unique_document_path`: the application's *own* recorded path
is regenerated in place; a taken name gets a short hash of the un-slugified
identity (`stem-a3f9`); the same-identity re-application keeps one file.
Covered by the pipeline tests (`test_colliding_slugs_never_overwrite_each_other`,
`test_fully_non_latin_names_do_not_all_land_on_untitled`,
`test_regenerating_materials_updates_the_same_files_in_place`) and the
`unique_document_path` unit tests.

**Follow-up 10 — `QSettings` registry location (fixed).** Window geometry
moved out of `QSettings` (`HKCU\Software\JAUTOMATIC\job-search` on Windows)
into `settings.json` inside the data dir — deleting `%APPDATA%\JAUTOMATIC`
now really is a full reset, and the app writes nothing outside its install
folder and data folder. The MSI's uninstaller story (leave user data behind,
no hidden registry residue) is exactly as documented in
[`docs/install-windows.md`](../docs/install-windows.md); the legacy 1.0 key,
if it exists, is disclosed there with removal steps. A "remove my data"
checkbox in the MSI remains an optional future nicety, not a correctness gap.

**Follow-up 11 — quit race (fixed).** `closeEvent` used to give workers an
800 ms grace period and then close the workspace anyway, so a surviving worker
could touch dead UI or a closed SQLite handle. Shutdown is now cooperative and
race-free: `closeEvent` flips `_closing` + a `threading.Event` cancel flag,
`run_task` refuses new work, queued workers check the flag before touching
their fn, long loops (job search, batch prepare, autopilot) poll it between
units of work, the pool is joined with **no timeout**, and late signal
deliveries are muted before `Workspace.close()`. Covered by the offscreen GUI
tests (`test_close_joins_running_workers_and_mutes_late_signals`,
`test_run_task_is_refused_once_closing`,
`test_queued_worker_starts_nothing_after_cancel`) plus pipeline/scraper
cancellation tests. *Installer relevance:* the app exits promptly and cleanly
on upgrades — no Restart Manager surprises from a worker outliving the window.
