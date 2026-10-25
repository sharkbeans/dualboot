import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dualboot_switcher import cli, config
from dualboot_switcher.backend_windows import WindowsBackend
from dualboot_switcher.classify import LINUX, WINDOWS
from dualboot_switcher.model import BootEntry, SwitcherError

from . import fixture

WINDOWS_ENTRY = BootEntry(id="0000", label="Windows Boot Manager",
                          path=r"\EFI\Microsoft\Boot\bootmgfw.efi", active=True)
UBUNTU = BootEntry(id="{aaaa-0001}", label="ubuntu", path=r"\EFI\ubuntu\shimx64.efi")
FEDORA = BootEntry(id="{bbbb-0002}", label="Fedora", path=r"\EFI\fedora\shimx64.efi")
USB = BootEntry(id="0017", label="USB CD")


class FakeBackend:
    def __init__(self, current_os, entries, error=None):
        self.current_os = current_os
        self.entries = entries
        self.error = error
        self.switched = None

    def list_entries(self):
        if self.error:
            raise self.error
        return self.entries

    def describe(self, entry):
        return [f"set-boot-next {entry.id}", "reboot"]

    def disk_label(self, entry):
        return "Test Disk, 512 GB"

    def system_info(self):
        return "TestOS 1.0, UEFI"

    def switch(self, entry):
        self.switched = entry


def windows_backend(fixture_name):
    """The real Windows backend, with bcdedit printing the given fixture."""
    text = fixture(fixture_name)
    return WindowsBackend(run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, text, ""),
                          firmware_type=lambda: 2, is_admin=lambda: True)


class FormatTableTest(unittest.TestCase):
    def test_active_column_on_linux(self):
        table = cli.format_table([WINDOWS_ENTRY, BootEntry(id="0010", label="Setup", active=False)])
        self.assertEqual(table.splitlines()[0].split()[:3], ["ID", "ACTIVE", "KIND"])
        self.assertEqual(table.splitlines()[2].split()[:3], ["0010", "no", "firmware"])

    def test_no_active_column_when_unknown(self):
        # bcdedit doesn't report the flag, so Windows tables leave it out.
        table = cli.format_table(windows_backend("bcdedit_firmware_en_us.txt").list_entries())
        self.assertNotIn("ACTIVE", table)
        self.assertEqual(table.splitlines()[0].split(), ["ID", "KIND", "LABEL", "PATH"])
        self.assertIn("{bootmgr}", table)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, backend, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv), backend=backend, config_path=self.config_path)
        return code, out.getvalue(), err.getvalue()

    def test_list_shows_entries_target_and_command(self):
        backend = FakeBackend(LINUX, [WINDOWS_ENTRY, USB])
        code, out, _ = self.run_cli(backend, "list")
        self.assertEqual(code, 0)
        self.assertIn("USB CD", out)
        self.assertIn("Target: 0000 Windows Boot Manager", out)
        self.assertIn("set-boot-next 0000", out)

    def test_list_with_several_candidates(self):
        code, out, _ = self.run_cli(FakeBackend(WINDOWS, [UBUNTU, FEDORA]), "list")
        self.assertEqual(code, 0)
        self.assertIn("Several possible targets", out)

    def test_dry_run_prints_commands_and_changes_nothing(self):
        backend = FakeBackend(LINUX, [WINDOWS_ENTRY, USB])
        code, out, _ = self.run_cli(backend, "switch", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Dry run", out)
        self.assertIn("set-boot-next 0000", out)
        self.assertIsNone(backend.switched)

    def test_switch_asks_first(self):
        for answer, switched in [("y", WINDOWS_ENTRY), ("", None), ("no", None)]:
            with self.subTest(answer=answer):
                backend = FakeBackend(LINUX, [WINDOWS_ENTRY])
                with mock.patch("builtins.input", return_value=answer) as asked:
                    self.run_cli(backend, "switch")
                self.assertIn("Restart into Windows now?", asked.call_args[0][0])
                self.assertEqual(backend.switched, switched)

    def test_switch_yes_skips_question(self):
        backend = FakeBackend(LINUX, [WINDOWS_ENTRY])
        with mock.patch("builtins.input") as asked:
            code, _, _ = self.run_cli(backend, "switch", "--yes")
        self.assertEqual(code, 0)
        asked.assert_not_called()
        self.assertEqual(backend.switched, WINDOWS_ENTRY)

    def test_several_candidates_need_target(self):
        backend = FakeBackend(WINDOWS, [UBUNTU, FEDORA])
        code, _, err = self.run_cli(backend, "switch", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("--target", err)

    def test_target_is_remembered(self):
        backend = FakeBackend(WINDOWS, [UBUNTU, FEDORA])
        code, out, _ = self.run_cli(backend, "switch", "--dry-run", "--target", "BBBB-0002")
        self.assertEqual(code, 0)
        self.assertIn("Target: {bbbb-0002} Fedora", out)
        self.assertEqual(config.load_choice(self.config_path), ("{bbbb-0002}", "Fedora"))
        # Next time the remembered choice is used without --target.
        code, out, _ = self.run_cli(backend, "switch", "--dry-run")
        self.assertIn("Target: {bbbb-0002} Fedora", out)

    def test_picker_with_real_windows_output(self):
        ubuntu = "{00000000-0000-0000-0000-000000000018}"
        code, _, err = self.run_cli(windows_backend("bcdedit_firmware_two_linux.txt"),
                                    "switch", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn(f"{ubuntu} (ubuntu)", err)
        # Braces are optional when picking a Windows GUID.
        code, out, _ = self.run_cli(windows_backend("bcdedit_firmware_two_linux.txt"),
                                    "switch", "--dry-run", "--target", ubuntu.strip("{}"))
        self.assertEqual(code, 0)
        self.assertIn(f"bootsequence {ubuntu}", out)
        code, out, _ = self.run_cli(windows_backend("bcdedit_firmware_two_linux.txt"),
                                    "switch", "--dry-run")
        self.assertIn(f"Target: {ubuntu} ubuntu", out)

    def test_target_must_be_a_candidate(self):
        backend = FakeBackend(LINUX, [WINDOWS_ENTRY, USB])
        code, _, err = self.run_cli(backend, "switch", "--dry-run", "--target", "0017")
        self.assertEqual(code, 1)
        self.assertIn("not a possible target", err)

    def test_no_target_found(self):
        code, _, err = self.run_cli(FakeBackend(LINUX, [USB]), "switch", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("No Windows Boot Manager entry", err)

    def test_backend_errors_are_shown(self):
        backend = FakeBackend(LINUX, [], error=SwitcherError("legacy BIOS"))
        code, _, err = self.run_cli(backend, "list")
        self.assertEqual((code, err.strip()), (1, "Error: legacy BIOS"))


if __name__ == "__main__":
    unittest.main()
