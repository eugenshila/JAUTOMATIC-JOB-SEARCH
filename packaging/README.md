# Packaging: the Windows installer, end to end

Everything needed to turn this repository into a signed, upgradeable, per-machine
MSI - and the reasoning behind each decision. User-facing install docs live in
[`docs/INSTALL-WINDOWS.md`](../docs/INSTALL-WINDOWS.md).

## The pipeline

```
requirements.txt ──▶ PyInstaller (onedir)  ──▶ sign JAUTOMATIC.exe ──┐
jautomatic/**            packaging/jautomatic.spec                  │
tools/make_assets.py ──▶ packaging/assets/*                         ▼
LICENSE ─────────────▶ packaging/wix/LICENSE.rtf        WiX v5 (Files harvest)
                                                                    │
                                                                    ▼
            GitHub Release ◀── SHA256SUMS.txt ◀── sign MSI ◀── *.msi
                  ▲                                                  │
                  └────────── verify-install.ps1 (install/exercise/uninstall on the runner)
```

Two stages, one hand-off file (`dist/build-info.json`), so CI can sign the payload
*between* freezing and packaging:

```powershell
packaging\build.ps1 -Stage freeze      # tests, notices, art, EULA, PyInstaller
packaging\build.ps1 -Stage package     # WiX v5 MSI + hashes (+ local signtool)
packaging\build.ps1                    # both
```

## Prerequisites

| Tool | Why | Notes |
|---|---|---|
| Python 3.10+ | app + all generators | `pip install -r requirements.txt pyinstaller` |
| .NET SDK 8 | runs the pinned `wix` CLI | `dotnet tool restore --tool-manifest packaging/.config/dotnet-tools.json` pins WiX **5.0.2** + UI/Util extensions; no manual WiX install |
| Windows SDK `signtool.exe` | local signing only | optional; CI signs with Azure instead |
| Azure Artifact Signing account | release signing | optional, see below |

## What each file does

```
packaging/
  jautomatic.spec            PyInstaller onedir spec (windowed, no UPX, Qt trimmed)
  build_info.py              version/identity single source of truth + version resource
  build.ps1                  the pipeline above (freeze / package / all)
  verify-install.ps1         clean-VM install test: install -> exercise -> uninstall
  make_release_notes.ps1     release-notes renderer (checksums included)
  check_notices.py           fails the build if a shipped dependency lacks a notice
  make_eula.py               LICENSE -> packaging/wix/LICENSE.rtf (installer EULA)
  THIRD-PARTY-NOTICES.md     what we redistribute, and the rights you keep
  .config/dotnet-tools.json  pinned wix CLI + extensions
  wix/JAUTOMATIC.wxs         the MSI (per-machine, MajorUpgrade, UI, launch)
  wix/LICENSE.rtf            generated EULA shown by the installer
  assets/app_icon.ico        generated, 7 resolutions
  assets/app_icon.png        generated, 512 px
  assets/app_banner.bmp      generated, WiX banner (493x58)
  assets/app_dialog.bmp      generated, WiX dialog art (499x312)
tools/make_assets.py         deterministic SDF renderer for all of the above
```

Art and EULA are *generated and committed*; `build.ps1` re-checks them every build
(`tools/make_assets.py --check`, `packaging/make_eula.py --check`) and CI fails on drift.

## Decisions, and why

* **PyInstaller onedir, not onefile.** A ~150 MB onefile blob would unpack to `%TEMP%`
  on every launch and re-trigger AV scans; onedir starts immediately and shares one
  `_internal` tree. `console=False` (desktop app): machine-readable CLI output goes
  through `--selftest --report <file>` and exit codes, which is also what
  `verify-install.ps1` consumes.
* **UPX off, forever.** UPX-compressed Qt DLLs are a classic antivirus false-positive
  and have a history of corrupting `vcruntime140.dll`. The MSI cab compresses anyway.
* **Qt trimmed in the spec.** `PySide6` is a metapackage; without the explicit
  `excludes` list the payload grows by ~300 MB of WebEngine/3D/Multimedia nobody
  imports. `tests/test_packaging.py` fails if the app ever imports something the spec
  excludes.
* **Per-machine, `Program Files`.** Chosen for this release: one upgradable copy per
  workstation, correct for shared machines; UAC elevation at install time, none at run
  time. Data stays per-user in `%APPDATA%\JAUTOMATIC`, so the app never needs to write
  to its install folder (the verifier asserts that).
* **`UpgradeCode` is immutable.** `9af86a17-eb3b-5133-abe2-1d58466e83a6`, derived once
  from the repository URL and hard-coded in `build_info.py` and the `.wxs` (a test
  checks they agree). Regenerating it would silently install side-by-side instead of
  upgrading. ProductCode is left to WiX (fresh GUID per build), which is what makes
  every build a valid major upgrade.
* **`MajorUpgrade Schedule="afterInstallExecute"`, `AllowSameVersionUpgrades="yes"`.**
  Fast, rolls back safely on failure, and correct here because harvesting yields strict
  one-file-per-component layout. Same-version upgrades are allowed so CI can re-install
  an identical build; the downgrade error message stays in place for genuinely older
  versions.
* **Payload via the WiX v5 `Files` element** (`Include="!(bindpath.App)\**"`), the
  supported replacement for `heat.exe`: one component per file, stable ids, no
  duplicate-name collisions, ICE-clean for per-machine packages.
* **`util:CloseApplication`** asks the running app to close (WM_CLOSE, then end-session,
  then terminate after 10 s) before upgrade/uninstall touches files.
* **Launch after install is unelevated** (`WixUnelevatedShellExec`): the installer runs
  elevated, the app must not, or it would create the data directory in the admin profile.
* **VC runtime guard.** PyInstaller bundles `vcruntime140*.dll`/`msvcp140*.dll`; the
  build verifies they are present and warns loudly otherwise, because a missing
  redistributable on a clean VM is the classic "worked on my machine" MSI failure.
* **We sign exactly two files**: `JAUTOMATIC.exe` and the MSI. Third-party DLLs in
  `_internal` are *not* ours to sign (and Azure Artifact Signing refuses binaries that
  are not yours).

## Signing and SmartScreen (state of the world, 2026)

* The service formerly called **Azure Trusted Signing** is now **Azure Artifact
  Signing**; the GitHub Action is `azure/artifact-signing-action` (the old
  `azure/trusted-signing-action` still resolves). Cost ~US$9.99/month. Eligibility:
  organisations in US/CA/EU/UK, individuals in US/CA only; identity validation takes a
  few business days.
* Since the 2024 SmartScreen equalisation **no certificate type buys instant
  reputation** - not even EV. What signing buys you: no "unknown publisher" warnings,
  and *publisher* reputation that persists across certificate rotation and accrues over
  consecutive releases. Expect a prompt or two on the very first signed release; that is
  normal and documented in `docs/INSTALL-WINDOWS.md`.
* CI wiring (all optional - the pipeline produces unsigned MSIs without it):
  repository **variables** `AZURE_SIGNING_ENDPOINT`, `AZURE_SIGNING_ACCOUNT`,
  `AZURE_SIGNING_PROFILE`; **secrets** `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
  `AZURE_SUBSCRIPTION_ID` (OIDC, no client secret). Grant the app registration the
  *Artifact Signing Certificate Profile Signer* role.
* Local alternative: `packaging\build.ps1 -SignMode signtool -SignThumbprint <sha1>`
  (or `-SignSubject "<CN>"`), timestamped against `timestamp.acs.microsoft.com`.

## Releasing

1. Bump `__version__` in `jautomatic/__init__.py` (the only version you edit).
2. Tag `v<major>.<minor>.<patch>` and push. The `windows-installer` workflow builds,
   signs (if configured), runs `verify-install.ps1` on the runner, uploads artefacts and
   creates the GitHub Release with the MSI + `SHA256SUMS.txt` + generated notes.
3. For a dry run without a tag: *Actions → Windows installer → Run workflow* with
   `publish=true`.

The version flows one way: `__version__` → exe version resource + MSI `ProductVersion`
(three fields; MSI ignores a fourth when comparing) → asset names → release title.

## WiX version pinning - please read before bumping

WiX **v5** is what this release was decided on and built against. Note that WiX v5 left
community support on **2026-02-05** (v6 and v7 ship today; v7.0.0 since 2026-04).
Nothing here blocks an upgrade: the XML namespace (`http://wixtoolset.org/schemas/v4/wxs`)
is unchanged across v4-v7, and the only v5-ism we rely on is `UpgradeCode` (v6+ prefers
the new `Package/@Id`, which accepts the same value). To move: bump `WIX_VERSION` in
`packaging/build_info.py` **and** `packaging/.config/dotnet-tools.json`, build, run
`verify-install.ps1` against an older MSI to prove the upgrade path survives.

## Deferred follow-ups (deliberately not in this batch)

These were identified during the packaging review and left for a follow-up; each has an
installer-visible consequence, so they are tracked here:

1. **Document filename collisions** (`slugify()` is ASCII-only; non-Latin company/title
   both collapse to `untitled`, so two postings can overwrite each other's CV while both
   tracker rows claim "materials ready 3/3"). Fix: keep Unicode word characters (still
   stripping Windows-illegal ones) and append the 8-char job id. *Installer impact:
   none, but it is the worst user-facing bug an installer will now amplify.*
2. **`QSettings("JAUTOMATIC", "job-search")` keeps window geometry in the registry**
   (`HKCU\Software\JAUTOMATIC\job-search`), contradicting "deleting the folder is a full
   reset". Switch to `QSettings` `IniFormat` inside the data directory. *Installer
   impact: decides whether the uninstaller needs a "remove my data / my settings"
   checkbox; `docs/INSTALL-WINDOWS.md` currently discloses the registry key instead.*
3. **Crash-on-quit race**: `closeEvent` waits only 800 ms for the worker pool before
   closing SQLite, so a scrape still writing can hit a closed connection. Needs a proper
   wait (or a "search still running - wait / cancel" prompt). *Installer impact:
   `util:CloseApplication` can trigger this path during upgrades.*

## Clean-VM testing by hand

* **Windows Sandbox** (`WindowsSandbox` from an elevated prompt, Windows 10/11 Pro):
  copy `dist\` in, run `verify-install.ps1` - it is a genuinely clean image every time.
* **Hyper-V / VirtualBox**: take a snapshot before installing; test the upgrade path by
  installing the previous release first (`verify-install.ps1 -PreviousMsi old.msi`).
* The automated equivalent runs in CI on every build; its JSON report is uploaded as an
  artefact (`dist/verify-report.json`).
