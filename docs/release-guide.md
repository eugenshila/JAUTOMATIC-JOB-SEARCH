# Release and Windows MSI Packaging Guide

This guide details the release process, version management, WiX 6 installer creation,
and GitHub Actions automation for **JAUTOMATIC JOB SEARCH**.

---

## 1. Release Process Overview

```
Update Version (jautomatic/__init__.py)
               │
               ▼
Run Pre-Flight Check (tools/check_release.py)
               │
               ▼
Push Branch & Open PR (GitHub Actions triggers windows-installer.yml)
               │
               ▼
Windows CI: PyInstaller Freeze ──▶ WiX 6 MSI Build ──▶ verify-install.ps1
               │
               ▼
Artifacts Uploaded to GitHub (dist/JAUTOMATIC-Setup-<version>-x64.msi)
               │
               ▼
Merge & Tag Release (e.g. v1.1.0)
```

---

## 2. Version Management

The application version is defined in a single authoritative source:
* `jautomatic/__init__.py`: `__version__ = "1.1.0"`

The packaging subsystem (`packaging/build_info.py`) imports this version automatically and formats it for:
* **MSI ProductVersion**: 3-part numeric format (`major.minor.build`, e.g., `1.1.0`).
* **MSI Output Filename**: `JAUTOMATIC-Setup-<version>-x64.msi`.
* **Windows Executable Version Resource**: Embedded into `jautomatic.exe` during PyInstaller freezing.

---

## 3. WiX 6 Installer Setup

The installer uses **WiX Toolset v6** (`6.0.2`), installed and restored automatically via .NET Local Tools:

| Config File | Setting |
|-------------|---------|
| `packaging/build_info.py` | `WIX_VERSION = "6.0.2"` |
| `.config/dotnet-tools.json` | `"tools": { "wix": { "version": "6.0.2" } }` |

Both files must agree. Run `python packaging/build_info.py --check` to verify synchronization.

### Key Installer Characteristics
- **Scope**: Per-machine (`%ProgramFiles%\JAUTOMATIC`).
- **Architecture**: 64-bit (`x64`, `ProgramFiles64Folder`).
- **Upgrade Strategy**: `MajorUpgrade` only — automatically uninstalls previous versions cleanly while preserving user data in `%APPDATA%\JAUTOMATIC`.
- **Permanent Upgrade Code**: `6723609b-1b49-46f6-ad03-7554cbade5de` (never changes).
- **Start Menu & ARP**: Installs Start Menu shortcut and Add/Remove Programs entry.

---

## 4. Local Build (Windows)

To build and verify the MSI locally on a Windows machine:

### Prerequisites
- Windows 10/11 (x64)
- Python 3.10+
- [.NET 8 SDK](https://dotnet.microsoft.com/download)

### Build Commands

```powershell
# 1. Full build: creates venv, runs tests, freezes PyInstaller bundle, builds MSI
packaging\build.ps1

# 2. Acceptance verification (elevated PowerShell prompt):
packaging\verify-install.ps1 -MsiPath dist\JAUTOMATIC-Setup-1.10.0-x64.msi
```

### Useful Switches
- `packaging\build.ps1 -SkipTests` — Skip test suite for faster packaging.
- `packaging\build.ps1 -SkipPackage` — Run freeze only (`dist\jautomatic`).
- `packaging\build.ps1 -SkipFreeze -SkipTests` — Package existing frozen directory.
- `packaging\build.ps1 -Sign` — Sign locally with Azure Artifact Signing.
- `packaging\build.ps1 -UseExistingEnvironment` — Reuse the installed packaging
  environment and pinned WiX tool without upgrading dependencies or restoring tools.

Run install/uninstall verification on a clean test machine. The script refuses
to run when JAUTOMATIC is already installed, so it cannot remove a working installation.
For upgrade acceptance, install the previous MSI in a disposable Windows VM, create
a profile/application/document, install the new MSI, confirm all data and document
links survive, and finally uninstall and verify that the data directory remains.

ProductCode is deterministic per release version (see `build_info.product_code`),
while UpgradeCode remains permanent. WiX 6 `Package/@Id` is a package identity,
not ProductCode. See the [WiX Package schema](https://docs.firegiant.com/wix/schema/wxs/package/)
and [Microsoft major-upgrade requirements](https://learn.microsoft.com/en-us/windows/win32/msi/major-upgrades).

---

## 5. Automated GitHub Actions CI/CD Pipeline

The `.github/workflows/windows-installer.yml` workflow automates the entire packaging and testing pipeline on `windows-2022` runners:

1. **Freeze**: Sets up Python 3.12, installs dependencies, runs test suite and smoke test (`main.py --selftest`), runs PyInstaller.
2. **Artifact Signing (Optional)**: If Azure Artifact Signing OIDC variables and secrets are configured on the repo, signs frozen `.exe`/`.dll` files.
3. **Package**: Restores `dotnet wix` tool (v6.0.2), harvests frozen files into `files.wxs`, builds `JAUTOMATIC-Setup-<version>-x64.msi`.
4. **Sign Installer (Optional)**: Signs the resulting `.msi` file.
5. **Verify Install**: Runs `verify-install.ps1` (silent install, 12 validation checks including `--selftest` of the installed binary, data preservation check, uninstall).
6. **Upload Artifacts**:
   - `JAUTOMATIC-Setup-x64`: Contains the built MSI installer.
   - `install-report`: Contains `install-report.json`, `install.log`, and `uninstall.log`.
   - `build-diagnostics`: Contains freeze/package logs and diagnostics.

---

## 6. Pre-Flight Checklist Before Tagging a Release

Before publishing a new release:

1. **Bump version** in `jautomatic/__init__.py`.
2. **Run tests and pre-flight check**:
   ```bash
   python -m unittest discover -s tests -t .
   python tools/check_release.py
   python main.py --selftest
   ```
3. **Commit & Push** changes to your working branch.
4. **Open a Pull Request** to trigger the CI build.
5. **Download and verify** the MSI artifact `JAUTOMATIC-Setup-x64` generated by GitHub Actions.
6. **Merge the PR** and create a GitHub Release with the MSI attached.
