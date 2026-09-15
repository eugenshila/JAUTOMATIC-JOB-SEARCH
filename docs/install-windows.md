# Installing JAUTOMATIC JOB SEARCH on Windows

Download `JAUTOMATIC-Setup-<version>-x64.msi` from the
[releases page](https://github.com/eugenshila/JAUTOMATIC-JOB-SEARCH/releases),
double-click it, and follow the wizard. It installs to
`%ProgramFiles%\JAUTOMATIC`, adds a **JAUTOMATIC JOB SEARCH** shortcut to the
Start Menu, and registers an Add/Remove Programs entry. No account, no
background services, no telemetry — the app only talks to the network when
*you* run a job search.

Requirements: Windows 10 or 11, 64-bit. The installer needs administrator
rights (it is a per-machine install); the app itself runs as a normal user.

## SmartScreen: what to expect

The first time you run a new release, Windows SmartScreen may show a blue
*"Windows protected your PC"* prompt. **This is expected, even though every
release is signed** — here is the honest version of why:

* The installer and the app carry a real Authenticode signature from our
  Azure Artifact Signing certificate, timestamped so it stays valid. You can
  check it yourself: right-click the `.msi` → Properties → Digital
  Signatures. Signing proves the file is genuinely ours and untampered with,
  and it removes the "unknown publisher" label.
* What signing does *not* do is buy instant trust. Microsoft gives new
  publisher identities no reputation to start with — no certificate type
  skips the first prompt, EV included (since 2024) — and reputation accrues
  as signed releases with a stable publisher identity circulate. So the first
  signed release prompts, and later ones progressively stop.
* If you see the prompt, click **More info → Run anyway**. (If the file shows
  *no* digital signature at all, do **not** install it — get the MSI from the
  releases page linked above instead.)

Upgrades behave the same way: each release is a major upgrade that cleanly
replaces the previous install while leaving your data untouched.

## Uninstalling

Settings → Apps → **JAUTOMATIC JOB SEARCH** → Uninstall, or re-run the MSI
and choose Remove. The uninstaller removes the program files, the shortcut
and the registry entries it created — and deliberately **leaves your data
behind**:

* `%APPDATA%\JAUTOMATIC` — your profile, settings, database and generated
  documents. Delete the folder if you want a full reset.
* `HKCU\Software\JAUTOMATIC\job-search` — a single registry key holding the
  window size/position (a Qt implementation detail we plan to fold into
  `settings.json`; until then it is disclosed here rather than silently kept).
  To remove it, run `reg delete "HKCU\Software\JAUTOMATIC\job-search" /f`.

## Silent install

For scripts and managed machines:

```bat
msiexec /i JAUTOMATIC-Setup-1.0.0-x64.msi /qn /norestart
msiexec /x JAUTOMATIC-Setup-1.0.0-x64.msi /qn /norestart   :: uninstall
```

## FAQ

**My antivirus flags the installer / exe — is it safe?**
Almost certainly a false positive from heuristics (small publishers + PyInstaller
bundles are a classic trigger). Verify the digital signature as described
above and, if in doubt, upload the file to VirusTotal. Tell us if a major
engine flags a release — sustained false positives are something we escalate.

**Can I run it portably, without installing?**
Yes: the app keeps everything under one folder. After installing once, copy
`%ProgramFiles%\JAUTOMATIC` anywhere and run `jautomatic.exe --data-dir .\data`
for a fully self-contained copy — or point `--data-dir` at any folder (and the
`JAUTOMATIC_DATA_DIR` environment variable does the same permanently).

**Where does my data live?**
`%APPDATA%\JAUTOMATIC` unless you override it: `profile.json`, `settings.json`,
`jautomatic.sqlite3`, `documents/` and `exports/`. See the main
[README](../README.md#where-your-data-lives) for the full layout.

**How do I know an upgrade kept my data?**
The installer never touches `%APPDATA%\JAUTOMATIC` — upgrades only replace
program files. Our release pipeline additionally install-tests every MSI and
asserts user data survives the uninstall round-trip (`packaging/`).
