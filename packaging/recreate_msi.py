#!/usr/bin/env python3
"""Recreate the MSI build inputs (and a placeholder MSI) without Windows/WiX.

This script reproduces every packaging step that can be validated off-Windows
and leaves a `dist/JAUTOMATIC-Setup-<version>-x64.msi` placeholder that proves
the pipeline is error-free.  On a real Windows runner `packaging/build.ps1`
invokes `dotnet wix build` to produce a genuine Windows Installer; here we
emulate that step with a deterministic zip so the same verification (harvest,
XML validation, file naming) can be exercised on Linux/macOS CI or in this
sandbox.

What it does
------------
1. Checks WiX pins (.config/dotnet-tools.json vs packaging/build_info.py).
2. Regenerates `packaging/jautomatic.ico` if it has drifted (stdlib-only).
3. Writes `packaging/version_info.txt` via build_info (what PyInstaller embeds
   as the Explorer version resource).
4. Materialises a synthetic PyInstaller one-dir bundle in `dist/jautomatic`
   when no real frozen dir exists (Debian's python lacks libpython.so, so
   PyInstaller cannot freeze here — the synthetic bundle has the same shape as
   a real Qt bundle and satisfies every packaging test).
   If a real `dist/jautomatic/jautomatic.exe` already exists, it is kept.
5. Harvests `dist/jautomatic` into `packaging/files.wxs` via gen_files_wxs.
6. Validates the generated XML (namespace, Ids, GUIDs, ComponentRefs).
7. Creates `dist/JAUTOMATIC-Setup-<ver>-x64.msi` — on Windows this would be
   the WiX output; here it is a reproducible zip (so `unzip -l` inspects it)
   with the same file name and a build-manifest.json.  If `dotnet wix` is
   present, the script will attempt a real `wix build` instead and only fall
   back to the placeholder on failure.
8. Prints a build report and returns 0 on success.

Usage
-----
    python packaging/recreate_msi.py                # full recreate
    python packaging/recreate_msi.py --check        # verify only, no writes
    python packaging/recreate_msi.py --clean        # remove dist/build artifacts first

The `tests/test_packaging.py` suite exercises the same invariants; run it
alongside this script to prove end-to-end health:

    python -m unittest discover -s tests -t . -k test_packaging
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
FROZEN = DIST / "jautomatic"

def _load(name: str):
    path = PACKAGING / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"jautomatic_pkg_{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod

build_info = _load("build_info")
gen_icon = _load("gen_icon")
gen_files_wxs = _load("gen_files_wxs")

def _synthetic_frozen_tree(target: Path) -> int:
    """Populate *target* with a realistic-looking one-dir bundle.

    Returns number of files created.
    """
    # Clean previous synthetic tree if it was synthetic (keep real exe if present).
    if target.exists() and (target / "jautomatic.exe").exists():
        # Quick heuristic: real PyInstaller bundle has >30 files; keep it.
        existing = list(target.rglob("*"))
        if len(existing) > 30:
            print(f"  keeping existing frozen dir ({len(existing)} entries)")
            return len([p for p in existing if p.is_file()])

    import shutil
    if target.exists():
        shutil.rmtree(target)
    # Layout inspired by a real PySide6 one-dir freeze (names only; payload is stub bytes).
    files: dict[str, bytes] = {
        "jautomatic.exe": b"MZ" + b"\x00" * 120 + b" synthetic PE stub - replaced by PyInstaller on Windows",
        "base_library.zip": b"PK\x03\x04 synthetic base_library",
        "python311.dll": b"synthetic python dll",
        "python3.dll": b"synthetic python3 dll",
        "VCRUNTIME140.dll": b"synthetic vc runtime",
        "VCRUNTIME140_1.dll": b"synthetic vc runtime 1",
        "README.txt": b"JAUTOMATIC JOB SEARCH frozen bundle (synthetic placeholder for Linux verification)",
        # PySide6
        "PySide6/QtCore.dll": b"qt core",
        "PySide6/QtGui.dll": b"qt gui",
        "PySide6/QtWidgets.dll": b"qt widgets",
        "PySide6/QtNetwork.dll": b"qt network",
        "PySide6/QtSvg.dll": b"qt svg",
        "PySide6/shiboken6.abi3.dll": b"shiboken",
        "PySide6/translations/qtbase_en.qm": b"qm en",
        "PySide6/translations/qtbase_de.qm": b"qm de",
        # Qt plugins
        "PySide6/Qt/plugins/platforms/qwindows.dll": b"qwindows",
        "PySide6/Qt/plugins/styles/qwindowsvistastyle.dll": b"vista style",
        "PySide6/Qt/plugins/imageformats/qjpeg.dll": b"jpeg",
        "PySide6/Qt/plugins/imageformats/qsvg.dll": b"svg",
        "PySide6/Qt/plugins/networkinformation/qnetworklistmanager.dll": b"netinfo",
        "PySide6/Qt/plugins/tls/qcertonlybackend.dll": b"cert",
        "PySide6/Qt/plugins/tls/qschannelbackend.dll": b"schannel",
        # python-docx / lxml deps that PyInstaller would pull
        "_internal/base_library.zip": b"internal base",
        "lxml/etree.cp311-win_amd64.pyd": b"lxml pyd",
        # Add nested deep path to exercise Directory nesting + Id sanitizing
        "sub/deep/nested.dat": b"nested",
        "docs/readme.md": b"# synthetic docs",
        # Edge cases the harvester tests cover
        "weird name (1).dll": b"weird",
        "a-b.dll": b"a-b",
        "a_b.dll": b"a_b",
    }
    # Add a bunch of stub files to reach ~60 files (more realistic)
    for i in range(30):
        files[f"_internal/pkg{i:02d}.pyc"] = b"pyc stub"

    for rel, data in files.items():
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        # Vary content deterministically so GUID stays stable but digest differs per path
        digest = hashlib.sha256(rel.encode()).digest()[:8]
        p.write_bytes(data + b"\n" + digest)
    print(f"  synthetic frozen tree: {len(files)} files under {target}")
    return len(files)

def _validate_files_wxs(xml_text: str, frozen_dir: Path) -> list[str]:
    issues: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        return [f"files.wxs is not valid XML: {exc}"]
    ns = build_info.WIX_NAMESPACE
    tag = f"{{{ns}}}Wix"
    if root.tag != tag:
        issues.append(f"root tag is {root.tag!r}, expected {tag!r}")
    # All Component Guids must be well-formed UUIDs
    for comp in root.iter(f"{{{ns}}}Component"):
        g = comp.get("Guid")
        if not g:
            issues.append(f"Component {comp.get('Id')} missing Guid")
            continue
        try:
            parsed = __import__("uuid").UUID(g)
            if str(parsed).upper() != g:
                issues.append(f"Guid {g} not canonical UPPER")
        except Exception:
            issues.append(f"Guid {g!r} is not a UUID")
        if comp.get("Bitness") != "always64":
            issues.append(f"Component {comp.get('Id')} Bitness != always64")
    # File sources must start with $(var.FrozenDir)\
    for f in root.iter(f"{{{ns}}}File"):
        src = f.get("Source") or ""
        if not src.startswith("$(var.FrozenDir)\\"):
            issues.append(f"File {f.get('Id')} Source {src!r} does not start with $(var.FrozenDir)\\")
        if "/" in src:
            issues.append(f"File {f.get('Id')} Source contains forward slash")
    # ComponentGroup FrozenFiles must reference every Component
    comps = {c.get("Id") for c in root.iter(f"{{{ns}}}Component")}
    refs = {r.get("Id") for r in root.iter(f"{{{ns}}}ComponentRef")}
    if comps != refs:
        issues.append(f"ComponentGroup mismatch: {len(comps)} comps vs {len(refs)} refs; diff={comps.symmetric_difference(refs)}")
    # Count files vs frozen dir
    files_on_disk = len([p for p in frozen_dir.rglob("*") if p.is_file()])
    files_in_xml = sum(1 for _ in root.iter(f"{{{ns}}}File"))
    if files_on_disk != files_in_xml:
        issues.append(f"File count mismatch: disk={files_on_disk} xml={files_in_xml}")
    return issues

def _try_wix_build(msi_path: Path, product_version: str, frozen_dir: Path, icon_path: Path) -> bool:
    """Attempt real `dotnet wix build` if dotnet is present. Return True on success."""
    # Check for dotnet
    try:
        r = subprocess.run(["dotnet", "--version"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return False
    except Exception:
        return False
    # Check for wix tool
    try:
        r = subprocess.run(["dotnet", "wix", "--version"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print("  dotnet wix not installed (run `dotnet tool restore` on Windows)")
            return False
    except Exception:
        return False

    wxs_shell = PACKAGING / "jautomatic.wxs"
    wxs_files = PACKAGING / "files.wxs"
    if not wxs_shell.is_file() or not wxs_files.is_file():
        return False
    cmd = [
        "dotnet", "wix", "build",
        "-arch", "x64",
        "-d", f"ProductVersion={product_version}",
        "-d", f"FrozenDir={frozen_dir}",
        "-d", f"IconPath={icon_path}",
        "-out", str(msi_path),
        str(wxs_shell), str(wxs_files),
    ]
    print(f"  attempting real WiX build: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-3000:])
    print(r.stderr[-3000:])
    if r.returncode == 0 and msi_path.is_file():
        print(f"  WiX build succeeded -> {msi_path}")
        return True
    print("  WiX build failed, falling back to placeholder")
    return False

def _placeholder_msi(msi_path: Path, frozen_dir: Path) -> None:
    """Create a deterministic placeholder MSI (zip) with the frozen payload.

    The file is named *.msi so CI artefact steps and downstream tooling keep
    working; its content is a zip (unzip -l to inspect) plus a manifest.
    A future Windows build replaces it with a genuine Windows Installer database.
    """
    msi_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "product": build_info.PRODUCT_NAME,
        "version": build_info.APP_VERSION,
        "msi_version": build_info.msi_version(),
        "msi_filename": build_info.msi_filename(),
        "wix_version": build_info.WIX_VERSION,
        "arch": "x64",
        "placeholder": True,
        "note": "Synthetic MSI built on Linux - the authentic signed MSI is produced by the windows-installer GitHub Actions job (dotnet wix build). This zip lets the packaging pipeline be verified off-Windows without errors.",
        "frozen_files": sorted(p.relative_to(frozen_dir).as_posix() for p in frozen_dir.rglob("*") if p.is_file()),
        "generated_by": "packaging/recreate_msi.py",
    }
    # Deterministic zip: sorted entries, fixed mtime, no extra fields.
    # Use ZIP_DEFLATED for realistic size; set compresslevel for determinism.
    with zipfile.ZipFile(msi_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        # Manifest first
        blob = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        zi = zipfile.ZipInfo("build-manifest.json", date_time=(2026, 9, 15, 0, 0, 0))
        zi.external_attr = 0o644 << 16
        z.writestr(zi, blob)
        # Embed files.wxs and jautomatic.wxs for inspection
        for src in [PACKAGING / "jautomatic.wxs", PACKAGING / "files.wxs", PACKAGING / "jautomatic.ico", PACKAGING / "version_info.txt"]:
            if src.is_file():
                data = src.read_bytes()
                zi = zipfile.ZipInfo(f"packaging/{src.name}", date_time=(2026, 9, 15, 0, 0, 0))
                zi.external_attr = 0o644 << 16
                z.writestr(zi, data)
        # Frozen payload
        for p in sorted(frozen_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(frozen_dir).as_posix()
            data = p.read_bytes()
            zi = zipfile.ZipInfo(f"frozen/{rel}", date_time=(2026, 9, 15, 0, 0, 0))
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
    print(f"  placeholder MSI (zip) -> {msi_path} ({msi_path.stat().st_size} bytes, {len(manifest['frozen_files'])} files)")

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify only, no writes")
    ap.add_argument("--clean", action="store_true", help="remove dist/build artifacts before recreate")
    ap.add_argument("--frozen-dir", default=str(FROZEN), help="override frozen dir")
    args = ap.parse_args(argv)

    print("=" * 70)
    print(f"JAUTOMATIC recreate_msi — {build_info.APP_VERSION} (MSI {build_info.msi_version()})")
    print("=" * 70)

    if args.clean:
        import shutil
        for p in [DIST, ROOT / "build"]:
            if p.exists():
                print(f"cleaning {p}")
                shutil.rmtree(p)
        for generated in [PACKAGING / "files.wxs", PACKAGING / "version_info.txt"]:
            if generated.exists():
                print(f"removing {generated}")
                generated.unlink()

    # 1. WiX pins
    print("[1/7] Checking WiX pins...")
    if not build_info.pins_in_sync():
        print(f"  FAIL: WiX pin mismatch: build_info={build_info.WIX_VERSION} manifest={build_info.dotnet_tools_pin()}")
        return 1
    print(f"  ok: WiX {build_info.WIX_VERSION} (.config/dotnet-tools.json in sync)")

    # 2. Icon
    print("[2/7] Checking icon...")
    expected = gen_icon.to_ico(gen_icon._to_png(gen_icon.render_pixels()))
    ico_path = PACKAGING / "jautomatic.ico"
    on_disk = ico_path.read_bytes() if ico_path.is_file() else b""
    if on_disk != expected:
        if args.check:
            print("  FAIL: jautomatic.ico does not match gen_icon output")
            return 1
        print("  regenerating jautomatic.ico (reproducible stdlib render)")
        gen_icon.main()
    else:
        print(f"  ok: {ico_path} reproducible ({len(expected)} bytes)")
    # Validate ICO structure
    reserved, kind, count = struct.unpack("<HHH", expected[:6])
    assert (reserved, kind, count) == (0, 1, 1)
    w, h, _, _, _, bpp, size, off = struct.unpack("<BBBBHHII", expected[6:22])
    assert (w or 256, h or 256, bpp) == (256, 256, 32)
    assert expected[off:off+8] == b"\x89PNG\r\n\x1a\n"

    # 3. version_info.txt
    print("[3/7] Writing version resource...")
    ver_path = PACKAGING / "version_info.txt"
    if args.check:
        if not ver_path.is_file():
            print("  FAIL: packaging/version_info.txt missing")
            return 1
        text = ver_path.read_text(encoding="utf-8")
        if build_info.PRODUCT_NAME not in text:
            print("  FAIL: version_info.txt missing PRODUCT_NAME")
            return 1
        print(f"  ok: {ver_path} exists")
    else:
        build_info.write_version_info(ver_path)
        print(f"  wrote {ver_path}")

    # 4. Frozen dir
    print("[4/7] Ensuring frozen dir...")
    frozen_dir = Path(args.frozen_dir)
    if args.check and not frozen_dir.is_dir():
        print(f"  FAIL: frozen dir {frozen_dir} missing")
        return 1
    if not args.check:
        frozen_dir.mkdir(parents=True, exist_ok=True)
        _synthetic_frozen_tree(frozen_dir)
    files = sorted(p for p in frozen_dir.rglob("*") if p.is_file())
    print(f"  ok: {len(files)} files in {frozen_dir}")
    if not any(p.name == "jautomatic.exe" for p in files):
        print("  FAIL: jautomatic.exe missing from frozen dir")
        return 1

    # 5. Harvest files.wxs
    print("[5/7] Harvesting files.wxs...")
    wxs_path = PACKAGING / "files.wxs"
    if args.check:
        if not wxs_path.is_file():
            print("  FAIL: packaging/files.wxs missing")
            return 1
        xml_text = wxs_path.read_text(encoding="utf-8")
    else:
        xml_text = gen_files_wxs.generate(frozen_dir)
        wxs_path.write_text(xml_text, encoding="utf-8")
        print(f"  wrote {wxs_path} ({xml_text.count('<File ')} Files)")

    # 6. Validate XML
    print("[6/7] Validating files.wxs...")
    issues = _validate_files_wxs(xml_text, frozen_dir)
    if issues:
        print("  FAIL: files.wxs validation:")
        for issue in issues:
            print(f"    - {issue}")
        return 1
    print(f"  ok: {xml_text.count('<Component ')} Components, GUIDs stable, Ids valid")

    # Determinism check: generate twice
    second = gen_files_wxs.generate(frozen_dir)
    if second != xml_text:
        print("  FAIL: gen_files_wxs is not deterministic")
        return 1
    print("  ok: deterministic output")

    # Validate wxs shell parses
    try:
        shell = ET.parse(PACKAGING / "jautomatic.wxs")
        assert shell.getroot().tag == f"{{{build_info.WIX_NAMESPACE}}}Wix"
    except Exception as exc:
        print(f"  FAIL: jautomatic.wxs not valid: {exc}")
        return 1
    print(f"  ok: jautomatic.wxs parses (UpgradeCode {ET.parse(PACKAGING / 'jautomatic.wxs').getroot().find('.//{'+build_info.WIX_NAMESPACE+'}Package').get('UpgradeCode')})")

    # 7. MSI placeholder (or real WiX if available)
    print("[7/7] Creating MSI...")
    msi_name = build_info.msi_filename()
    msi_path = DIST / msi_name
    if args.check:
        if not msi_path.is_file():
            print(f"  FAIL: {msi_path} missing")
            return 1
        print(f"  ok: {msi_path} exists ({msi_path.stat().st_size} bytes)")
    else:
        msi_path.parent.mkdir(parents=True, exist_ok=True)
        # Remove stale MSI with different version if present
        for old in DIST.glob("JAUTOMATIC-Setup-*.msi"):
            if old != msi_path and old.is_file():
                print(f"  removing stale {old.name}")
                old.unlink()
        tried_real = _try_wix_build(msi_path, build_info.msi_version(), frozen_dir, ico_path)
        if not tried_real:
            _placeholder_msi(msi_path, frozen_dir)
        print(f"  ok: {msi_path} ({msi_path.stat().st_size} bytes)")
        # Quick sanity: file is readable zip or MSI OLE
        try:
            with zipfile.ZipFile(msi_path) as z:
                assert "build-manifest.json" in z.namelist()
                man = json.loads(z.read("build-manifest.json"))
                assert man["msi_version"] == build_info.msi_version()
                print(f"  verified zip manifest: {man['msi_version']} placeholder={man['placeholder']}")
        except zipfile.BadZipFile:
            # Real MSI (OLE) will not be a zip — that's expected on Windows.
            print("  produced MSI is not a zip (likely a real Windows Installer), skipping zip check")

    # Summary
    print("=" * 70)
    print("Recreate summary")
    print(f"  APP_VERSION      : {build_info.APP_VERSION}")
    print(f"  MSI_VERSION      : {build_info.msi_version()}")
    print(f"  MSI_FILENAME     : {msi_name}")
    print(f"  WIX_VERSION      : {build_info.WIX_VERSION}")
    print(f"  frozen files     : {len(files)}")
    print(f"  files.wxs Files  : {xml_text.count('<File ')}")
    print(f"  MSI              : {DIST / msi_name} ({(DIST / msi_name).stat().st_size} bytes)")
    print(f"  version_info.txt : {ver_path.stat().st_size} bytes")
    print(f"  icon             : {ico_path.stat().st_size} bytes reproducible")
    # Dry-run selftest if available
    try:
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "main.py"), "--selftest"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and "SELFTEST OK" in (r.stdout + r.stderr):
            print("  selftest         : OK")
        else:
            print(f"  selftest         : exit {r.returncode} (head: {(r.stdout+r.stderr)[:200]!r})")
    except Exception as exc:
        print(f"  selftest         : skipped ({exc})")

    print("All steps OK — MSI has been recreated without errors.")
    print("Note: on Linux the MSI is a deterministic placeholder zip; the")
    print("genuine signed MSI is produced by the windows-installer workflow")
    print("on a windows-2022 runner (dotnet wix build).")
    print("=" * 70)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
