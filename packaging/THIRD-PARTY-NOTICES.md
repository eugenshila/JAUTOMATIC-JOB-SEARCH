# Third-party components shipped inside the installer

The JAUTOMATIC JOB SEARCH MSI redistributes the components below. They remain
under their own licences; this file is the notice required when bundling them,
and it lists the rights those licences give **you**.

Versions are those of the last verified release build; `packaging/check_notices.py`
fails the build if a runtime dependency ever ships without a notice here (it
checks membership, not versions).

| Package | Version | Licence | Role |
|---|---|---|---|
| PySide6 | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | runtime |
| PySide6_Essentials | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | runtime |
| PySide6_Addons | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | runtime |
| shiboken6 | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | runtime |
| Qt (via PySide6) | 6.11.2 | LGPL-3.0-only (parts also GPL/commercial) | runtime |
| requests | 2.34.2 | Apache-2.0 | runtime |
| urllib3 | 2.7.0 | MIT | runtime |
| certifi | 2026.7.22 | MPL-2.0 | runtime |
| charset-normalizer | 3.5.1 | MIT | runtime |
| idna | 3.19 | BSD-3-Clause | runtime |
| python-docx | 1.2.0 | MIT | runtime |
| lxml | 6.1.3 | BSD-3-Clause | runtime |
| typing_extensions | 4.16.0 | PSF-2.0 | runtime |
| PyInstaller | 6.x | GPL-2.0-or-later WITH Bootloader-exception | build-time |
| ruff | 0.x | MIT | build-time |
| pip | any | MIT | build-time |

## LGPL compliance (Qt / PySide6 / shiboken6)

The application links the Qt libraries **dynamically**: every Qt component ships
as its own DLL under `C:\Program Files\JAUTOMATIC JOB SEARCH\_internal\`, and the
frozen `JAUTOMATIC.exe` loads them at start-up. There is no static linking and
no Qt code inside our binaries, so you can:

* replace any Qt DLL with a modified or differently-licensed build of the same
  library (same file name, same ABI),
* re-link the application against another Qt build, and
* obtain the corresponding Qt sources from the Qt Project
  (<https://code.qt.io>, <https://www.qt.io/licensing/>).

The Python-level bindings (PySide6, shiboken6) are used under the same LGPL-3.0
option; their sources are published at <https://code.qt.io/cgit/pyside/pyside-setup.git/>.
A copy of the LGPL-3.0 text is available at <https://www.gnu.org/licenses/lgpl-3.0.txt>.

## MPL-2.0 (certifi)

certifi's root-certificate bundle is a data file distributed unmodified. MPL-2.0
is file-level: the certifi source files remain under MPL-2.0 and their licence
text is available at <https://mozilla.org/MPL/2.0/>.

## Apache-2.0 (requests)

requests is distributed unmodified; a copy of the Apache-2.0 licence is at
<https://www.apache.org/licenses/LICENSE-2.0>. Patent grant and NOTICE terms
apply as published by the project.

## MIT / BSD-3-Clause / PSF-2.0

urllib3, charset-normalizer, python-docx (MIT); idna, lxml (BSD-3-Clause);
typing_extensions (PSF-2.0). Each is distributed unmodified with its copyright
notice intact inside the package metadata shipped in `_internal\`.

## Build-time only (not redistributed)

PyInstaller (GPL-2.0-or-later **with the Bootloader exception**: the exception
states that binaries produced by PyInstaller are not derivative works of the
GPL-covered bootloader, so frozen output carries no GPL obligations), ruff and
pip are used to *build* the installer and are not part of it.

## Trademarks

Qt and the Qt logo are trademarks of The Qt Company. Python and the Python
logos are trademarks of the Python Software Foundation. All other names belong
to their respective owners. Their use here is descriptive only.
