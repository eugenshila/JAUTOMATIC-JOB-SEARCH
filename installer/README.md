# Windows MSI installer

The repository includes a reproducible MSI build. An MSI binary is not checked into Git because it is a generated Windows artifact and cannot be produced in this Linux development sandbox.

## Build on Windows

Install:

- Python 3.11+
- WiX Toolset 3.14 (`choco install wixtoolset --version=3.14.1 -y` from an elevated PowerShell)

Then from the repository root:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\installer\build-msi.ps1
```

The output is:

```text
dist\AI Job Application Assistant.msi
```

The installer creates Start Menu and optional desktop shortcuts, installs the PyInstaller bundle, and leaves the user's `%LOCALAPPDATA%\AI Job Application Assistant` data untouched during upgrades. Windows Task Scheduler registration remains an explicit in-app preference and is not silently enabled by the MSI.

The MSI does not automatically submit job applications. It installs the approval-first application assistant.
