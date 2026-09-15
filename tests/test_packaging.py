"""Tests for the Windows installer packaging (all platform-neutral).

The real ``wix build`` and MSI install only happen on Windows CI, but every
input to that pipeline is verifiable here: the single-sourced build info, the
WiX version pins, the hand-written installer shell, the file harvester, the
PyInstaller spec, the icon, the frozen-runtime helpers and the CI/workflow
wiring. If any of those drift, this suite fails long before a runner burns
ten minutes discovering it.
"""
import ast
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
sys.path.insert(0, str(ROOT))

from jautomatic import runtime  # noqa: E402


def _load_packaging_module(name):
    # `packaging/` is deliberately not a package (no __init__.py): a top-level
    # `packaging` package would shadow PyPI's `packaging` library for every
    # tool run from the repo root, including pip itself. Load by file instead.
    spec = importlib.util.spec_from_file_location(
        f"jautomatic_packaging_{name}", PACKAGING / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


build_info = _load_packaging_module("build_info")
gen_files_wxs = _load_packaging_module("gen_files_wxs")


def _wxs_tree(path):
    return ET.parse(path)


class BuildInfoTest(unittest.TestCase):
    def test_wix_pin_has_release_shape(self):
        self.assertRegex(build_info.WIX_VERSION, r"^\d+\.\d+\.\d+$")

    def test_dotnet_tool_manifest_matches_pin(self):
        manifest = ROOT / ".config" / "dotnet-tools.json"
        self.assertTrue(manifest.is_file(), ".config/dotnet-tools.json missing")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["tools"]["wix"]["version"], build_info.WIX_VERSION)
        self.assertTrue(build_info.pins_in_sync())

    def test_msi_version(self):
        self.assertEqual(build_info.msi_version("1.0.0"), "1.0.0")
        self.assertEqual(build_info.msi_version("2.3"), "2.3.0")
        self.assertEqual(build_info.msi_version("1.2.0rc1"), "1.2.0")
        self.assertEqual(build_info.msi_version("10.20.30.40"), "10.20.30")
        # MSI fields cap at 65535; the fourth field is ignored by the engine.
        self.assertEqual(build_info.msi_version("1.2.99999"), "1.2.65534")

    def test_msi_filename(self):
        name = build_info.msi_filename("1.0.0", "x64")
        self.assertEqual(name, "JAUTOMATIC-Setup-1.0.0-x64.msi")

    def test_version_resource_contents(self):
        text = build_info.version_info_text("1.0.0")
        self.assertIn("JAUTOMATIC JOB SEARCH", text)
        self.assertIn("jautomatic.exe", text)
        self.assertIn("filevers=(1, 0, 0, 0)", text)
        self.assertIn("040904B0", text)

    def test_write_version_info_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "version_info.txt"
            build_info.write_version_info(target, "1.0.0")
            self.assertIn("JAUTOMATIC", target.read_text(encoding="utf-8"))

    def test_check_cli_passes(self):
        self.assertEqual(build_info.main(["--check"]), 0)

    def test_json_cli_covers_workflow_contract(self):
        values = build_info.as_dict()
        for key in ("APP_VERSION", "MSI_VERSION", "MSI_FILENAME", "WIX_VERSION",
                    "SIGN_VAR_ENDPOINT", "SIGN_VAR_ACCOUNT", "SIGN_VAR_PROFILE"):
            self.assertIn(key, values)


class InstallerShellTest(unittest.TestCase):
    WXS = PACKAGING / "jautomatic.wxs"

    def setUp(self):
        self.tree = _wxs_tree(self.WXS)
        self.root = self.tree.getroot()
        self.ns = {"w": build_info.WIX_NAMESPACE}

    def test_namespace_is_pinned_core_namespace(self):
        self.assertEqual(self.root.tag, f"{{{build_info.WIX_NAMESPACE}}}Wix")

    def test_package_identity(self):
        package = self.root.find("w:Package", self.ns)
        self.assertIsNotNone(package)
        self.assertEqual(package.get("Name"), build_info.PRODUCT_NAME)
        self.assertEqual(package.get("Manufacturer"), build_info.MANUFACTURER)
        self.assertEqual(package.get("Scope"), "perMachine")
        # The version always comes from jautomatic.__version__ via -d.
        self.assertEqual(package.get("Version"), "$(var.ProductVersion)")

    def test_upgrade_code_is_frozen(self):
        # The UpgradeCode is the product's permanent identity: changing it
        # orphans every existing install. This exact-match assertion is the
        # tripwire — if you are here because of the WiX v6 Id migration, read
        # packaging/README.md "Upgrading WiX" before touching anything.
        package = self.root.find("w:Package", self.ns)
        self.assertEqual(package.get("UpgradeCode"), "6723609b-1b49-46f6-ad03-7554cbade5de")
        uuid.UUID(package.get("UpgradeCode"))  # must stay a valid GUID

    def test_major_upgrade_only(self):
        package = self.root.find("w:Package", self.ns)
        upgrades = package.findall("w:MajorUpgrade", self.ns)
        self.assertEqual(len(upgrades), 1)
        self.assertTrue(upgrades[0].get("DowngradeErrorMessage"))

    def _standard_directories(self) -> dict:
        return {element.get("Id"): element
                for element in self.root.findall("w:Package/w:StandardDirectory", self.ns)}

    def test_install_root_is_the_64_bit_program_files_folder(self):
        # ProgramFilesFolder resolves to "Program Files (x86)" on x64 machines
        # even for -arch x64 packages whose components are Bitness="always64";
        # verify-install.ps1 and docs/install-windows.md both expect
        # %ProgramFiles%\JAUTOMATIC, and the app is a 64-bit Qt bundle.
        directories = self._standard_directories()
        self.assertIn("ProgramFiles64Folder", directories)
        children = [child.get("Id")
                    for child in directories["ProgramFiles64Folder"].findall("w:Directory", self.ns)]
        self.assertIn("INSTALLFOLDER", children)

    def test_start_menu_folder_is_machine_wide(self):
        # perMachine install -> ProgramMenuFolder is the shared Start Menu.
        directories = self._standard_directories()
        self.assertIn("ProgramMenuFolder", directories)
        children = [child.get("Id")
                    for child in directories["ProgramMenuFolder"].findall("w:Directory", self.ns)]
        self.assertIn("ApplicationProgramsFolder", children)

    def test_media_is_embedded(self):
        media = self.root.find("w:Package/w:Media", self.ns)
        self.assertEqual(media.get("EmbedCab"), "yes")

    def test_feature_wiring(self):
        feature = self.root.find("w:Package/w:Feature", self.ns)
        groups = [e.get("Id") for e in feature.findall("w:ComponentGroupRef", self.ns)]
        refs = [e.get("Id") for e in feature.findall("w:ComponentRef", self.ns)]
        self.assertIn("FrozenFiles", groups)  # generated by gen_files_wxs.py
        self.assertIn("StartMenuShortcuts", refs)

    def test_shortcut_points_at_installed_exe(self):
        shortcut = self.root.find(".//w:Shortcut", self.ns)
        self.assertIsNotNone(shortcut)
        self.assertIn("jautomatic.exe", shortcut.get("Target"))
        self.assertEqual(shortcut.get("WorkingDirectory"), "INSTALLFOLDER")

    def test_shortcut_keypath_is_machine_wide(self):
        # The component key path lives in HKLM so uninstall removes it. The
        # app's own per-user QSettings key (HKCU) is deliberately NOT managed
        # here — see deferred follow-up 10 in packaging/README.md.
        values = self.root.findall(".//w:RegistryValue", self.ns)
        keyed = [v for v in values if v.get("KeyPath") == "yes"]
        self.assertEqual(len(keyed), 1)
        self.assertEqual(keyed[0].get("Root"), "HKLM")

    def test_icon_is_passed_as_an_absolute_compiler_input(self):
        # WiX resolves relative source paths against its binder input paths and
        # the current working directory - not against the .wxs file - so the
        # icon is handed over by absolute path (build.ps1 knows the directory;
        # the file still lives next to this shell).
        icon = self.root.find("w:Package/w:Icon", self.ns)
        self.assertIsNotNone(icon)
        self.assertEqual(icon.get("SourceFile"), "$(var.IconPath)")
        script = (PACKAGING / "build.ps1").read_text(encoding="utf-8")
        self.assertIn('$IconPath = Join-Path $PackagingDir "jautomatic.ico"', script)
        self.assertIn('-d "IconPath=$IconPath"', script)
        self.assertTrue((PACKAGING / "jautomatic.ico").is_file())


class HarvesterTest(unittest.TestCase):
    def _fake_frozen_dir(self, tmp):
        root = Path(tmp) / "jautomatic"
        (root / "Qt" / "plugins" / "platforms").mkdir(parents=True)
        (root / "sub" / "deep").mkdir(parents=True)
        blobs = [
            "jautomatic.exe",
            "lib.dll",
            "README.txt",
            "Qt/plugins/platforms/qwindows.dll",
            "sub/deep/nested.dat",
            "weird name (1).dll",  # spaces/parens must survive Id sanitizing
            "a-b.dll",              # sanitize-collides with the next file…
            "a_b.dll",              # …so one of them must get a suffix
        ]
        for blob in blobs:
            (root / blob).write_bytes(b"fake")
        return root

    def _generate(self, frozen_dir):
        return gen_files_wxs.generate(frozen_dir)

    def test_deterministic_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_frozen_dir(tmp)
            first = self._generate(root)
            second = self._generate(root)
            self.assertEqual(first, second)

    def test_output_is_namespaced_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml = self._generate(self._fake_frozen_dir(tmp))
            parsed = ET.fromstring(xml)
            self.assertEqual(parsed.tag, f"{{{build_info.WIX_NAMESPACE}}}Wix")

    def test_one_component_per_file_with_stable_guids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_frozen_dir(tmp)
            xml = self._generate(root)
            before = {c.get("Id"): c.get("Guid")
                      for c in ET.fromstring(xml).iter(f"{{{build_info.WIX_NAMESPACE}}}Component")}
            again = {c.get("Id"): c.get("Guid")
                     for c in ET.fromstring(self._generate(root)).iter(
                         f"{{{build_info.WIX_NAMESPACE}}}Component")}
            self.assertEqual(before, again)  # stable across runs
            self.assertEqual(len(before), 8)  # one per file
            for guid in before.values():
                parsed = uuid.UUID(guid)  # every GUID well-formed…
                self.assertEqual(str(parsed).upper(), guid)  # …and canonical
            self.assertEqual(len(set(before.values())), 8)  # …and unique

    def test_ids_valid_unique_and_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml = self._generate(self._fake_frozen_dir(tmp))
            # *Ref elements deliberately repeat the Id they point at; every
            # *defining* element must own a unique Id.
            ids = [e.get("Id") for e in ET.fromstring(xml).iter()
                   if e.get("Id") is not None and not e.tag.endswith("Ref")]
            self.assertEqual(len(ids), len(set(ids)), "duplicate Ids emitted")
            for ident in ids:
                self.assertRegex(ident, r"^[A-Za-z_][A-Za-z0-9_.]*$")
                self.assertLessEqual(len(ident), 72)

    def test_component_group_covers_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml = self._generate(self._fake_frozen_dir(tmp))
            ns = f"{{{build_info.WIX_NAMESPACE}}}"
            parsed = ET.fromstring(xml)
            components = {c.get("Id") for c in parsed.iter(f"{ns}Component")}
            refs = {r.get("Id") for r in parsed.iter(f"{ns}ComponentRef")}
            group = next(parsed.iter(f"{ns}ComponentGroup"))
            self.assertEqual(group.get("Id"), "FrozenFiles")
            self.assertEqual(components, refs)

    def test_main_exe_gets_stable_file_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml = self._generate(self._fake_frozen_dir(tmp))
            ns = f"{{{build_info.WIX_NAMESPACE}}}"
            files = {f.get("Id"): f.get("Source")
                     for f in ET.fromstring(xml).iter(f"{ns}File")}
            self.assertIn("MainExecutable", files)
            for source in files.values():
                self.assertTrue(source.startswith("$(var.FrozenDir)\\"), source)
                self.assertNotIn("/", source)

    def test_nested_directories_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml = self._generate(self._fake_frozen_dir(tmp))
            ns = f"{{{build_info.WIX_NAMESPACE}}}"
            names = [d.get("Name") for d in ET.fromstring(xml).iter(f"{ns}Directory")]
            for expected in ("Qt", "plugins", "platforms", "sub", "deep"):
                self.assertIn(expected, names)

    def test_missing_or_empty_dir_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                self._generate(Path(tmp) / "nope")
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with self.assertRaises(ValueError):
                self._generate(empty)

    def test_sanitize_id(self):
        self.assertEqual(gen_files_wxs.sanitize_id("plain.dll"), "plain.dll")
        self.assertEqual(gen_files_wxs.sanitize_id("a b(c).dll"), "a_b_c_.dll")
        self.assertEqual(gen_files_wxs.sanitize_id("9lives.dll"), "f_9lives.dll")
        self.assertLessEqual(len(gen_files_wxs.sanitize_id("x" * 200)), 72)


class SpecTest(unittest.TestCase):
    SPEC = PACKAGING / "jautomatic.spec"

    def setUp(self):
        self.text = self.SPEC.read_text(encoding="utf-8")

    def test_spec_parses(self):
        ast.parse(self.text)  # must at least be valid Python

    def test_one_dir_gui_bundle(self):
        self.assertIn('name="jautomatic"', self.text)
        self.assertIn("console=False", self.text)
        self.assertIn("COLLECT(", self.text)
        self.assertIn("exclude_binaries=True", self.text)
        self.assertIn("main.py", self.text)

    def test_windows_inputs_exist_and_are_guarded(self):
        # icon/version only make sense on Windows; the spec must still parse
        # (and the test must still pass) on every other platform.
        self.assertIn('os.name == "nt"', self.text)
        self.assertIn("jautomatic.ico", self.text)
        self.assertIn("version_info.txt", self.text)
        self.assertTrue((PACKAGING / "jautomatic.ico").is_file())

    def test_no_upx(self):
        # UPX breaks Qt DLLs and spooks antivirus heuristics.
        self.assertIn("upx=False", self.text)
        self.assertNotIn("upx=True", self.text)


class IconTest(unittest.TestCase):
    def test_generated_icon_is_valid_ico_with_png_payload(self):
        gen_icon = _load_packaging_module("gen_icon")
        ico = gen_icon.to_ico(gen_icon._to_png(gen_icon.render_pixels()))
        reserved, kind, count = struct.unpack("<HHH", ico[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 1))
        width, height, _, _, _, bpp, size, offset = struct.unpack("<BBBBHHII", ico[6:22])
        self.assertEqual((width or 256, height or 256, bpp), (256, 256, 32))
        self.assertEqual(ico[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(len(ico), offset + size)

    def test_checked_in_icon_is_reproducible(self):
        gen_icon = _load_packaging_module("gen_icon")
        expected = gen_icon.to_ico(gen_icon._to_png(gen_icon.render_pixels()))
        self.assertEqual((PACKAGING / "jautomatic.ico").read_bytes(), expected)


class RuntimeTest(unittest.TestCase):
    def test_source_checkout_by_default(self):
        self.assertFalse(runtime.is_frozen())
        self.assertEqual(runtime.base_dir(), ROOT)
        self.assertTrue(runtime.runtime_tag().startswith("source"))

    def test_frozen_mode_uses_bundle_dir(self):
        had_frozen = hasattr(sys, "frozen")
        had_meipass = hasattr(sys, "_MEIPASS")
        old_frozen = getattr(sys, "frozen", None)
        old_meipass = getattr(sys, "_MEIPASS", None)
        sys.frozen = True  # type: ignore[attr-defined]
        sys._MEIPASS = "/tmp/fake-bundle"  # type: ignore[attr-defined]
        try:
            self.assertTrue(runtime.is_frozen())
            self.assertEqual(runtime.base_dir(), Path("/tmp/fake-bundle"))
            self.assertTrue(runtime.runtime_tag().startswith("frozen"))
        finally:
            if had_frozen:
                sys.frozen = old_frozen  # type: ignore[attr-defined]
            else:
                delattr(sys, "frozen")
            if had_meipass:
                sys._MEIPASS = old_meipass  # type: ignore[attr-defined]
            else:
                delattr(sys, "_MEIPASS")


class WorkflowWiringTest(unittest.TestCase):
    WORKFLOW = ROOT / ".github" / "workflows" / "windows-installer.yml"

    def setUp(self):
        self.text = self.WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_exists_and_runs_pipeline(self):
        self.assertTrue(self.WORKFLOW.is_file())
        for step in ("build.ps1 -SkipPackage", "build.ps1 -SkipFreeze",
                     "verify-install.ps1", "upload-artifact"):
            self.assertIn(step, self.text)

    def test_signing_wiring_matches_build_info_contract(self):
        # The repo variable names are single-sourced in build_info; the
        # workflow must use exactly those (and the documented secrets).
        self.assertIn(build_info.SIGN_VAR_ENDPOINT, self.text)
        self.assertIn(build_info.SIGN_VAR_ACCOUNT, self.text)
        self.assertIn(build_info.SIGN_VAR_PROFILE, self.text)
        self.assertIn("AZURE_CLIENT_ID", self.text)
        self.assertIn("AZURE_TENANT_ID", self.text)
        self.assertIn("AZURE_SUBSCRIPTION_ID", self.text)
        self.assertIn("azure/artifact-signing-action", self.text)
        self.assertIn(build_info.SIGN_TIMESTAMP_URL, self.text)

    def test_if_conditions_never_reference_the_secrets_context(self):
        # GitHub rejects `secrets.*` inside an `if:` condition outright
        # ("Unrecognized named-value: 'secrets'") and the run dies at
        # workflow-file validation with zero jobs — a failure this test suite,
        # running off-Windows, can and must catch. Secrets belong in env:/with:;
        # conditions test the env name instead (see the AZURE_CLIENT_ID env var).
        lines = self.text.splitlines()
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped.startswith("if:"):
                continue
            indent = len(line) - len(stripped)
            block = [stripped[len("if:"):]]
            cursor = index + 1  # folded scalars continue deeper-indented
            while (cursor < len(lines) and lines[cursor].strip()
                   and (len(lines[cursor]) - len(lines[cursor].lstrip())) > indent):
                block.append(lines[cursor].strip())
                cursor += 1
            self.assertNotIn("secrets.", " ".join(block),
                             f"if: at workflow line {index + 1} uses the secrets context")

    def test_dotnet_line_matches_build_info(self):
        self.assertIn(f'"{build_info.DOTNET_VERSION}"', self.text)

    def test_workflow_exposes_failure_diagnostics(self):
        # A red run must explain itself in an annotation (always reachable),
        # not only in the raw log archive: every stage tees its output, the
        # failure step turns the tail into an ::error::, and the logs upload.
        for stage_log in ("build-freeze.log", "build-package.log", "verify-install.log"):
            self.assertIn(stage_log, self.text)
        self.assertIn("Expose build diagnostics", self.text)
        self.assertIn("if: failure()", self.text)
        self.assertIn("::error title=", self.text)
        self.assertIn("Tee-Object", self.text)
        self.assertIn("build-diagnostics", self.text)

    def test_workflow_runs_python_with_utf8_io(self):
        # Runner stdout is a pipe -> Python would pick the ANSI code page and
        # choke on non-ASCII test names/messages, hiding the real failure.
        self.assertIn("PYTHONUTF8", self.text)

    def test_build_script_uses_same_signing_inputs(self):
        script = (PACKAGING / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("AZURE_SIGNING_ENDPOINT", script)
        self.assertIn("AZURE_SIGNING_ACCOUNT", script)
        self.assertIn("AZURE_SIGNING_PROFILE", script)
        self.assertIn("SIGN_TIMESTAMP_URL", script)

    def test_powershell_scripts_stay_pure_ascii(self):
        # CI executes these through the Actions pwsh shell wrapper, whose
        # encoding pipeline once turned an em-dash (UTF-8 E2 80 94; the 0x94
        # tail is a CP1252 smart double-quote) into a real string terminator
        # mid-string and killed the parser with "Missing closing ')'".  ASCII
        # bytes remove the whole failure class, so the tripwire lives here.
        for name in ("build.ps1", "verify-install.ps1"):
            with self.subTest(script=name):
                raw = (PACKAGING / name).read_bytes()
                try:
                    raw.decode("ascii")
                except UnicodeDecodeError as exc:
                    self.fail(f"{name} contains non-ASCII bytes ({exc.start}): "
                              "replace typographic characters with ASCII '-'/'\"'")


class DocsDisclosureTest(unittest.TestCase):
    def test_maintainer_guide_covers_pin_signing_and_followups(self):
        readme = (PACKAGING / "README.md").read_text(encoding="utf-8")
        for phrase in ("WIX_VERSION", "dotnet-tools.json", "Artifact Signing",
                       "Follow-up 9", "Follow-up 10", "Follow-up 11"):
            self.assertIn(phrase, readme)

    def test_install_guide_discloses_reputation_and_data(self):
        guide = (ROOT / "docs" / "install-windows.md").read_text(encoding="utf-8")
        for phrase in ("SmartScreen", "Artifact Signing",
                       r"HKCU\Software\JAUTOMATIC\job-search",
                       "%APPDATA%\\JAUTOMATIC"):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
