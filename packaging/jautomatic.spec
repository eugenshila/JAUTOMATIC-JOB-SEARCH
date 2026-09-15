# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for JAUTOMATIC JOB SEARCH (Windows, one-dir).

One-dir (``COLLECT``) rather than one-file on purpose: the WiX installer
harvests this folder into per-file components (see ``gen_files_wxs.py``), and
a folder of real files upgrades, repairs and signs far more honestly than a
self-extracting blob.  ``console=False`` because this is a GUI app — the
``--selftest`` / ``--scrape`` CLI still works when launched from a terminal.

Built by ``packaging/build.ps1`` (which generates ``version_info.txt`` next
to this file first); never by hand::

    pyinstaller packaging/jautomatic.spec --distpath dist --workpath build/work

The app loads no data files relative to its own location and uses no dynamic
imports, so ``datas``/``hiddenimports`` stay empty — PyInstaller's stock
PySide6 hooks collect the Qt plugins/translations.  If the app ever gains
bundled assets, list them in ``datas`` here rather than reaching for
``sys._MEIPASS`` at runtime (see ``jautomatic/runtime.py``).
"""
import os

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
REPO_ROOT = os.path.dirname(SPEC_DIR)
VERSION_FILE = os.path.join(SPEC_DIR, "version_info.txt")

block_cipher = None

a = Analysis(
    [os.path.join(REPO_ROOT, "main.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "test", "pydoc"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_kwargs = dict(
    exclude_binaries=True,
    name="jautomatic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX trips over Qt DLLs and alarms antivirus heuristics; leave it off.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
# icon/version are Windows-only build inputs; build.ps1 always provides them,
# but the spec must still *parse* anywhere (tests/test_packaging.py imports it
# as text and the analysis is AST-checked on Linux CI).
if os.name == "nt":
    exe_kwargs["icon"] = os.path.join(SPEC_DIR, "jautomatic.ico")
    if os.path.exists(VERSION_FILE):
        exe_kwargs["version"] = VERSION_FILE

exe = EXE(pyz, a.scripts, [], **exe_kwargs)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="jautomatic",
)
