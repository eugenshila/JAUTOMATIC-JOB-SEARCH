# Installing JAUTOMATIC JOB SEARCH on Windows

The Windows build is a standard **per-machine MSI** (`JAUTOMATIC-JOB-SEARCH-<version>-x64.msi`,
published on the [releases page](https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH/releases)
with its SHA-256 checksum). Requirements: **64-bit Windows 10 or newer**, ~350 MB free
disk space, administrator rights for the install itself (the app then runs as a normal
user).

Nothing talks to a server: the installer only copies files and writes Start menu
shortcuts.

## Install

1. Download the `.msi` (and, if you like, `SHA256SUMS.txt` — see *Verifying a download*).
2. Double-click it and accept the UAC prompt.
3. Read and accept the licence, pick an install folder if you don't want the default,
   and click **Install**.
4. Leave **Launch JAUTOMATIC JOB SEARCH** ticked on the last screen to start right away.

By default the app lands in `C:\Program Files\JAUTOMATIC JOB SEARCH\`:

```
JAUTOMATIC JOB SEARCH\
  JAUTOMATIC.exe        the application (double-clickable, also on the Start menu)
  _internal\            Python runtime, Qt libraries, bundled resources
```

plus a Start menu folder `JAUTOMATIC` (app shortcut + uninstall shortcut) and an entry
in **Settings → Apps → Installed apps** named *JAUTOMATIC JOB SEARCH*.

### Where your data lives

Never in the install folder. Your profile, database, generated documents and exports
live in your own profile directory:

```
%APPDATA%\JAUTOMATIC\          e.g. C:\Users\<you>\AppData\Roaming\JAUTOMATIC
  profile.json  settings.json  jautomatic.sqlite3  documents\  exports\  logs\
```

The folder is created on first run, is plain files you can back up or move, and can be
redirected with `JAUTOMATIC.exe --data-dir D:\somewhere` (or the `JAUTOMATIC_DATA_DIR`
environment variable) — that is also how you run a fully portable copy.

`logs\` holds crash reports if the app ever dies on start-up; send that file with a bug
report.

## First run: SmartScreen and antivirus

* **Signed releases** show the publisher name in the UAC/SmartScreen dialogs. A brand-new
  signing identity can still produce a SmartScreen *"Windows protected your PC"* prompt
  for the first few releases: reputation accrues per publisher over time, and every
  release signed with the same identity inherits it. Click **More info → Run anyway** once
  if you see it; it stops appearing as reputation builds.
* **Unsigned builds** (e.g. one you compiled yourself) will always warn. That is expected;
  see `packaging/README.md` for how releases are signed.
* Some antivirus engines flag freshly-built PyInstaller executables as generic
  *"suspicious"* heuristics. Official releases are signed and timestamped, which resolves
  most false positives; please report persistent ones as an issue with your AV vendor name.

## Updating

Just run the new MSI: it upgrades in place (your data is untouched, the old version is
removed, shortcuts are refreshed). Re-running the *same* version repairs it. Installing an
**older** MSI over a newer one is refused on purpose — uninstall first if you really want
to go back.

If the app is running during an update, the installer asks it to close politely (and, if
it does not react within a few seconds, ends it). Unsaved UI state is not lost: everything
is stored in your data directory continuously.

## Uninstall

**Settings → Apps → JAUTOMATIC JOB SEARCH → Uninstall**, or the Start menu *Uninstall*
shortcut, or `msiexec /x {product-code} /qn`.

Removed: the program folder, Start menu shortcuts and the Add/Remove Programs entry.
**Kept: everything in `%APPDATA%\JAUTOMATIC`** — your profile, tracker and documents
survive uninstall and a later reinstall picks them up. Delete that folder yourself for a
true clean slate.

One honest footnote: the window's size/position is stored in your user settings (on
Windows: `HKCU\Software\JAUTOMATIC\job-search`), because that is where Qt keeps window
geometry. Uninstall does not clear it; it contains no personal data beyond pixel
coordinates. (Moving it into the data directory is tracked as a follow-up in
`packaging/README.md`.)

## Silent and enterprise deployment

Standard MSI, so any deployment tool works:

```powershell
# silent install for all users (needs elevation), logging to a file
msiexec /i JAUTOMATIC-JOB-SEARCH-1.0.0-x64.msi /qn /norestart /l*v install.log ALLUSERS=1

# custom folder
msiexec /i JAUTOMATIC-JOB-SEARCH-1.0.0-x64.msi /qn INSTALLFOLDER="D:\Apps\JAUTOMATIC"

# silent uninstall (product code from Add/Remove Programs, or the log)
msiexec /x {PRODUCT-CODE} /qn
```

* **Group Policy**: assign the MSI in a Computer-configuration software-installation GPO.
* **Intune/SCCM**: wrap the `/qn` line above; detect via the *JAUTOMATIC JOB SEARCH* ARP
  entry; the exit codes are stock MSI (0 = success, 3010 = success, reboot wanted).
* **Per-user installs are intentionally not offered**: the package is machine-wide so that
  every account on a shared workstation gets the same, upgradable copy. Data remains
  per-user either way.
* The MSI never writes to user profiles during install, so it is safe to install while
  users are logged on.

## Verifying a download

```powershell
# checksum
certutil -hashfile JAUTOMATIC-JOB-SEARCH-1.0.0-x64.msi SHA256
Get-FileHash JAUTOMATIC-JOB-SEARCH-1.0.0-x64.msi -Algorithm SHA256   # or this

# signature (signed releases only)
Get-AuthenticodeSignature JAUTOMATIC-JOB-SEARCH-1.0.0-x64.msi | Format-List Status,SignerCertificate
```

Compare the hash against `SHA256SUMS.txt` from the release.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| *"This app can't run on your PC"* | 32-bit Windows or Windows 8.1 or older — the build is x64/Win10+. |
| Installer says a newer version is installed | You are running an older MSI; uninstall first or take the latest release. |
| Nothing happens on first launch | Check `%APPDATA%\JAUTOMATIC\logs\` for a crash report; run `JAUTOMATIC.exe --selftest` in a console to see errors; if the console shows *"PySide6 ... missing DLL"* install the [VC++ 2015–2022 redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) (official builds bundle it — report it if you need this). |
| *"Windows protected your PC"* | Unsigned or very new signing identity; see the SmartScreen section. |
| Upgrade fails with *file in use* | The app ignored the close request; end `JAUTOMATIC.exe` in Task Manager and retry. |
| Documents open in the wrong Word/LibreOffice | `.docx`/`.md`/`.txt` are opened by whatever Windows associates with them; change the association in Settings → Apps → Default apps. |

Still stuck? Open an issue with the installer log (`/l*v` file) or the crash report
attached.

## For maintainers: the clean-VM checklist

The automated version of this list is `packaging/verify-install.ps1` (it also runs in CI
on every build). By hand, on a fresh Windows 10/11 VM with no dev tools:

1. Install the MSI via double-click; note UAC + EULA + progress + finish dialog art.
2. Launch from the finish-dialog checkbox → app must start **without** elevation.
3. Run a search, prepare one application pack, close the app, relaunch → state persisted.
4. Check `%APPDATA%\JAUTOMATIC` has the expected files; check the install folder has none.
5. Check Add/Remove Programs: name, version, publisher, icon; *Modify* must be absent.
6. Install a second (newer) MSI over it → single entry, new version, app still works.
7. Uninstall → folder and shortcuts gone, `%APPDATA%\JAUTOMATIC` intact.
8. Repeat steps 1 and 7 silently (`/qn`) and read `msiexec`'s exit code.
