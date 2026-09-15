"""Packaging invariants: versions, identities, WiX source, spec, art, EULA, notices.

These run on every platform in CI (no Windows, no PyInstaller, no network needed):
they pin the decisions that are expensive to discover broken - a regenerated
UpgradeCode, an MSI version with a fourth field, a spec that excludes something
the app imports, a stale installer EULA.
"""
from __future__ import annotations

import ast
import re
import struct
import sys
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))

import build_info  # noqa: E402
import check_notices  # noqa: E402
import make_eula  # noqa: E402

from jautomatic import __version__  # noqa: E402  (path setup above)

WXS = ROOT / "packaging" / "wix" / "JAUTOMATIC.wxs"
SPEC = ROOT / "packaging" / "jautomatic.spec"
ASSETS = ROOT / "packaging" / "assets"

WXS_NS = {"w": "http://wixtoolset.org/schemas/v4/wxs",
          "ui": "http://wixtoolset.org/schemas/v4/wxs/ui",
          "util": "http://wixtoolset.org/schemas/v4/wxs/util"}


def wxs_tree() -> ET.ElementTree:
    return ET.parse(WXS)


def app_imports() -> set[str]:
    """Every module the shipped code imports (static scan, no execution)."""
    found: set[str] = set()
    sources = [ROOT / "main.py", ROOT / "jautomatic" / "runtime.py"]
    sources += sorted((ROOT / "jautomatic").rglob("*.py"))
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
    return found


class TestVersions(unittest.TestCase):
    def test_single_source_of_truth(self):
        self.assertEqual(build_info.read_version(), __version__)

    def test_msi_version_is_three_fields(self):
        self.assertRegex(build_info.msi_version("1.2.3"), r"^\d+\.\d+\.\d+$")
        self.assertRegex(build_info.msi_version("1.2.3.4"), r"^\d+\.\d+\.\d+$")
        self.assertEqual(build_info.msi_version("2.0.0-beta1"), "2.0.0")

    def test_file_version_is_four_fields(self):
        self.assertRegex(build_info.file_version(__version__), r"^\d+\.\d+\.\d+\.\d+$")

    def test_version_info_resource_is_valid_python(self):
        text = build_info.version_info_text(__version__)
        ast.parse(text)                                  # PyInstaller execs this file
        self.assertIn("VSVersionInfo", text)
        self.assertIn(build_info.PRODUCT_NAME, text)
        self.assertIn(build_info.file_version(__version__), text)

    def test_release_name_carries_msi_version(self):
        self.assertIn(build_info.msi_version(__version__), build_info.release_name(__version__))


class TestIdentities(unittest.TestCase):
    def test_upgrade_code_is_a_stable_uuid(self):
        parsed = uuid.UUID(build_info.UPGRADE_CODE)
        self.assertEqual(parsed.version, 5)              # derived, not random
        self.assertEqual(build_info.UPGRADE_CODE,
                         str(uuid.uuid5(uuid.NAMESPACE_URL,
                                        "https://github.com/eugenshila/"
                                        "JAUTOMATIC-JOB-SEARCH#upgrade-code")))

    def test_wxs_uses_the_same_upgrade_code_variable(self):
        package = wxs_tree().find("w:Package", WXS_NS)
        self.assertEqual(package.get("UpgradeCode"), "$(var.UpgradeCode)")
        defines = build_info.wix_defines(__version__)
        self.assertEqual(defines["UpgradeCode"], build_info.UPGRADE_CODE)

    def test_wix_pinning_agrees_between_build_info_and_manifest(self):
        manifest = (ROOT / "packaging" / ".config" / "dotnet-tools.json").read_text(encoding="utf-8")
        self.assertIn(f'"version": "{build_info.WIX_VERSION}"', manifest)
        for extension, version in build_info.WIX_EXTENSIONS.items():
            self.assertIn(f'"{extension}": "{version}"', manifest)


class TestWixSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = wxs_tree()
        cls.root = cls.tree.getroot()
        cls.package = cls.root.find("w:Package", WXS_NS)

    def test_namespaces(self):
        self.assertEqual(self.root.tag, "{http://wixtoolset.org/schemas/v4/wxs}Wix")
        head = WXS.read_text(encoding="utf-8").split("<Wix", 1)[1].split(">", 1)[0]
        for prefix, uri in (("ui", "http://wixtoolset.org/schemas/v4/wxs/ui"),
                            ("util", "http://wixtoolset.org/schemas/v4/wxs/util")):
            self.assertIn(f'xmlns:{prefix}="{uri}"', head)

    def test_per_machine_package(self):
        self.assertEqual(self.package.get("Scope"), "perMachine")
        self.assertEqual(self.package.get("Version"), "$(var.ProductVersion)")

    def test_no_legacy_win64_attributes(self):
        # WiX v4+ removed Component/@Win64; bitness comes from `wix build -arch`.
        for element in self.root.iter():
            self.assertNotIn("Win64", element.attrib)

    def test_no_hardcoded_paths(self):
        for element in self.root.iter():
            for value in element.attrib.values():
                self.assertNotIn("C:\\", value)
                self.assertNotIn("C:/", value)

    def test_major_upgrade_rules(self):
        upgrade = self.package.find("w:MajorUpgrade", WXS_NS)
        self.assertIsNotNone(upgrade)
        self.assertTrue(upgrade.get("DowngradeErrorMessage"))
        self.assertEqual(upgrade.get("Schedule"), "afterInstallExecute")
        self.assertEqual(upgrade.get("AllowSameVersionUpgrades"), "yes")

    def test_launch_condition_uses_build_number(self):
        launch = self.package.find("w:Launch", WXS_NS)
        self.assertIsNotNone(launch)
        self.assertIn("WindowsBuildNumber", launch.get("Condition"))
        self.assertIn("VersionNT64", launch.get("Condition"))

    def test_payload_is_harvested_from_a_bind_path(self):
        files = self.root.find(".//w:Files", WXS_NS)
        self.assertIsNotNone(files)
        self.assertIn("!(bindpath.App)", files.get("Include"))
        self.assertEqual(files.get("Directory"), "INSTALLFOLDER")

    def test_install_layout(self):
        text = WXS.read_text(encoding="utf-8")
        self.assertIn('StandardDirectory Id="ProgramFiles64Folder"', text)
        self.assertIn('StandardDirectory Id="ProgramMenuFolder"', text)
        self.assertIn('Directory Id="INSTALLFOLDER"', text)

    def test_close_application_and_unelevated_launch(self):
        close = self.root.find(".//util:CloseApplication", WXS_NS)
        self.assertIsNotNone(close)
        self.assertEqual(close.get("Target"), "$(var.ExeName)")
        self.assertEqual(close.get("RebootPrompt"), "no")
        text = WXS.read_text(encoding="utf-8")
        self.assertIn("WixUnelevatedShellExec", text)
        self.assertIn('BinaryRef="Wix4UtilCA_$(sys.BUILDARCHSHORT)"', text)

    def test_ui_wiring(self):
        text = WXS.read_text(encoding="utf-8")
        for variable in ("WixUILicenseRtf", "WixUIBannerBmp", "WixUIDialogBmp"):
            self.assertIn(f'WixVariable Id="{variable}"', text)
        self.assertIn('ui:WixUI Id="WixUI_InstallDir"', text)
        self.assertIn('InstallDirectory="INSTALLFOLDER"', text)

    def test_arp_metadata(self):
        for prop in ("ARPPRODUCTICON", "ARPHELPLINK", "ARPNOMODIFY", "ARPINSTALLLOCATION"):
            self.assertIsNotNone(self.package.find(f"w:Property[@Id='{prop}']", WXS_NS), prop)


class TestPyInstallerSpec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SPEC.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(SPEC))

    def test_spec_is_valid_python(self):
        self.assertIsInstance(self.tree, ast.Module)

    def test_onedir_windowed_no_upx(self):
        self.assertIn("console=False", self.source)
        self.assertIn("upx=False", self.source)
        self.assertIn("COLLECT(", self.source)                 # onedir, not onefile

    def test_excludes_do_not_shadow_real_imports(self):
        excludes = set(re.findall(r'"(PySide6\.[A-Za-z0-9_]+|[a-z_][a-z0-9_]*)"',
                                  self.source.split("EXCLUDES = [", 1)[1].split("]", 1)[0]))
        imported = app_imports()
        overlap = excludes & imported
        self.assertEqual(overlap, set(),
                         f"spec excludes modules the app imports: {sorted(overlap)}")
        for needed in ("docx", "requests", "lxml"):
            self.assertNotIn(needed, excludes)

    def test_icon_and_version_come_from_packaging(self):
        self.assertIn("app_icon.ico", self.source)
        self.assertIn("version_info.txt", self.source)


class TestGeneratedArt(unittest.TestCase):
    def test_icon_is_a_multi_resolution_ico(self):
        blob = (ASSETS / "app_icon.ico").read_bytes()
        self.assertEqual(blob[:4], b"\x00\x00\x01\x00")
        count = struct.unpack("<H", blob[4:6])[0]
        sizes = []
        offset = 6
        for _ in range(count):
            width, _h, _, _, _planes, bpp, _size, _off = struct.unpack("<BBBBHHII",
                                                                       blob[offset:offset + 16])
            sizes.append(width or 256)
            self.assertEqual(bpp, 32)
            offset += 16
        self.assertEqual(sizes, sorted(sizes))
        self.assertIn(16, sizes)
        self.assertIn(256, sizes)
        self.assertGreaterEqual(len(sizes), 6)

    def test_master_png(self):
        blob = (ASSETS / "app_icon.png").read_bytes()
        self.assertEqual(blob[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", blob[16:24])
        self.assertEqual((width, height), (512, 512))

    def test_wix_ui_bitmaps(self):
        for name, expected in (("app_banner.bmp", (493, 58)), ("app_dialog.bmp", (499, 312))):
            blob = (ASSETS / name).read_bytes()
            self.assertEqual(blob[:2], b"BM", name)
            self.assertEqual(struct.unpack("<ii", blob[18:26]), expected, name)
            self.assertEqual(struct.unpack("<H", blob[28:30])[0], 24, name)


class TestEula(unittest.TestCase):
    def test_rtf_is_derived_from_license(self):
        generated = make_eula.rtf_from_license((ROOT / "LICENSE").read_text(encoding="utf-8"))
        committed = (ROOT / "packaging" / "wix" / "LICENSE.rtf").read_text(encoding="utf-8")
        self.assertEqual(committed, generated,
                         "packaging/wix/LICENSE.rtf is stale: run packaging/make_eula.py")

    def test_license_is_proprietary_and_mentions_third_parties(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("All rights reserved", text)
        self.assertIn("THIRD-PARTY COMPONENTS", text)
        self.assertIn("LGPL", text)


class TestNotices(unittest.TestCase):
    def test_every_requirement_is_noticed(self):
        declared = check_notices.declared_notices()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if line:
                name = check_notices._norm(re.split(r"[<>=!~;\[]", line)[0])
                self.assertIn(name, declared, f"{name} missing from THIRD-PARTY-NOTICES.md")

    def test_marker_evaluation_is_conservative(self):
        self.assertTrue(check_notices.marker_satisfied(""))
        self.assertTrue(check_notices.marker_satisfied("sys_platform == 'win32'"))
        self.assertFalse(check_notices.marker_satisfied("sys_platform == 'linux'"))
        self.assertTrue(check_notices.marker_satisfied("python_version >= '3.9'"))
        self.assertFalse(check_notices.marker_satisfied("python_version < '3.9'"))
        self.assertTrue(check_notices.marker_satisfied("extra == 'socks' or sys_platform == 'win32'"))
        self.assertTrue(check_notices.marker_satisfied("some_future_marker == 'x'"))

    def test_copyleft_components_are_explained(self):
        text = (ROOT / "packaging" / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
        for phrase in ("LGPL compliance", "dynamically", "MPL-2.0", "Bootloader exception"):
            self.assertIn(phrase, text)


class TestWorkflows(unittest.TestCase):
    def test_release_pipeline_exists_and_signs(self):
        text = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
        for needle in ("artifact-signing-action", "verify-install.ps1", "build.ps1 -Stage freeze",
                       "build.ps1 -Stage package", "SHA256SUMS.txt", "gh release create"):
            self.assertIn(needle, text)

    def test_ci_guards_the_generated_files(self):
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for needle in ("make_assets.py --check", "make_eula.py --check",
                       "check_notices.py", "tests.test_packaging"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
