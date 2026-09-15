#!/usr/bin/env python3
"""Pre-flight release validator for JAUTOMATIC JOB SEARCH.

Checks version consistency, WiX tool pins, packaging configurations, PowerShell
script encoding, icon integrity, and documentation references before cutting a release.

Usage::

    python tools/check_release.py
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import jautomatic
from packaging import build_info, gen_icon


def check_version_consistency() -> list[str]:
    issues: list[str] = []
    app_ver = jautomatic.__version__
    msi_ver = build_info.msi_version(app_ver)
    msi_file = build_info.msi_filename(app_ver)

    if not re.match(r"^\d+\.\d+\.\d+$", app_ver):
        issues.append(f"APP_VERSION '{app_ver}' is not valid semantic version (major.minor.patch)")

    info = build_info.as_dict()
    if info["APP_VERSION"] != app_ver:
        issues.append(f"build_info APP_VERSION ({info['APP_VERSION']}) != __version__ ({app_ver})")
    if info["MSI_VERSION"] != msi_ver:
        issues.append(f"build_info MSI_VERSION ({info['MSI_VERSION']}) != expected ({msi_ver})")
    if info["MSI_FILENAME"] != msi_file:
        issues.append(f"build_info MSI_FILENAME ({info['MSI_FILENAME']}) != expected ({msi_file})")

    # Check that documentation references match current version
    install_doc = (ROOT / "docs" / "install-windows.md").read_text(encoding="utf-8")
    if msi_file not in install_doc and f"JAUTOMATIC-Setup-{msi_ver}-x64.msi" not in install_doc:
        issues.append(f"docs/install-windows.md does not reference {msi_file}")

    return issues


def check_wix_pins() -> list[str]:
    issues: list[str] = []
    wix_ver = build_info.WIX_VERSION
    manifest = ROOT / ".config" / "dotnet-tools.json"

    if not manifest.is_file():
        return [f"Dotnet tool manifest missing: {manifest}"]

    data = json.loads(manifest.read_text(encoding="utf-8"))
    tool_ver = data.get("tools", {}).get("wix", {}).get("version")
    if tool_ver != wix_ver:
        issues.append(f"WiX pin mismatch: build_info={wix_ver} vs .config/dotnet-tools.json={tool_ver}")

    if not build_info.pins_in_sync():
        issues.append("build_info.pins_in_sync() returned False")

    return issues


def check_powershell_ascii() -> list[str]:
    issues: list[str] = []
    for ps_script in (ROOT / "packaging").glob("*.ps1"):
        raw = ps_script.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            issues.append(f"{ps_script.name} contains non-ASCII characters at byte {exc.start}")
    return issues


def check_icon() -> list[str]:
    issues: list[str] = []
    ico_path = ROOT / "packaging" / "jautomatic.ico"
    if not ico_path.is_file():
        return ["packaging/jautomatic.ico is missing"]

    raw = ico_path.read_bytes()
    expected = gen_icon.to_ico(gen_icon._to_png(gen_icon.render_pixels()))
    if raw != expected:
        issues.append("packaging/jautomatic.ico does not match reproducible gen_icon output")

    reserved, kind, count = struct.unpack("<HHH", raw[:6])
    if (reserved, kind, count) != (0, 1, 1):
        issues.append(f"Invalid ICO header: {(reserved, kind, count)}")

    return issues


def check_spec_and_wxs() -> list[str]:
    issues: list[str] = []
    spec_path = ROOT / "packaging" / "jautomatic.spec"
    if not spec_path.is_file():
        issues.append("packaging/jautomatic.spec is missing")

    wxs_path = ROOT / "packaging" / "jautomatic.wxs"
    if not wxs_path.is_file():
        issues.append("packaging/jautomatic.wxs is missing")
    else:
        content = wxs_path.read_text(encoding="utf-8")
        if "UpgradeCode" not in content or "6723609b-1b49-46f6-ad03-7554cbade5de" not in content:
            issues.append("jautomatic.wxs missing permanent UpgradeCode GUID")

    return issues


def main() -> int:
    print("=" * 60)
    print(f"JAUTOMATIC JOB SEARCH Release Pre-Flight Check (v{jautomatic.__version__})")
    print("=" * 60)

    checks = [
        ("Version Consistency", check_version_consistency),
        ("WiX Toolchain Pins", check_wix_pins),
        ("PowerShell Encoding (ASCII)", check_powershell_ascii),
        ("Application Icon Integrity", check_icon),
        ("Packaging Spec & WiX Shell", check_spec_and_wxs),
    ]

    all_passed = True
    for name, fn in checks:
        issues = fn()
        if issues:
            all_passed = False
            print(f"[FAIL] {name}:")
            for issue in issues:
                print(f"       - {issue}")
        else:
            print(f"[PASS] {name}")

    print("=" * 60)
    if all_passed:
        print("All pre-flight checks passed successfully.")
        return 0
    else:
        print("Pre-flight checks failed. Please address the issues above.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
