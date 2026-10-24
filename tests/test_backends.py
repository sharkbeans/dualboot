"""Backend tests. Commands go to a fake runner; nothing is actually executed."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from dualboot_switcher.backend_linux import LinuxBackend
from dualboot_switcher.backend_windows import BCDEDIT, SHUTDOWN, WindowsBackend
from dualboot_switcher.model import (
    BootEntry, NotAdminError, NotUefiError, SwitcherError,
)

from . import fixture

WINDOWS_ENTRY = BootEntry(id="0000", label="Windows Boot Manager",
                          path=r"\EFI\Microsoft\Boot\bootmgfw.efi")
DEBIAN_ENTRY = BootEntry(id="{00000000-0000-0000-0000-000000000001}", label="debian",
                         path=r"\EFI\debian\shimx64.efi")


class FakeRun:
    """Stands in for subprocess.run: records argv, returns canned results."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        returncode, stdout, stderr = self.results.pop(0)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


class LinuxBackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.efi_dir = Path(self.tmp.name)
        self.helper = self.efi_dir / "helper"
        self.helper.touch()

    def tearDown(self):
        self.tmp.cleanup()

    def backend(self, *results, efi_dir=None):
        self.run = FakeRun(*results)
        return LinuxBackend(run=self.run, efi_dir=efi_dir or self.efi_dir, helper=str(self.helper))

    def test_list_entries_parses_efibootmgr(self):
        backend = self.backend((0, fixture("efibootmgr-v_lenovo-lmde.txt"), ""))
        entries = backend.list_entries()
        self.assertEqual(self.run.calls, [["efibootmgr", "-v"]])
        self.assertEqual(entries[0].label, "Windows Boot Manager")

    def test_legacy_bios(self):
        backend = self.backend(efi_dir=self.efi_dir / "missing")
        with self.assertRaises(NotUefiError):
            backend.list_entries()
        self.assertEqual(self.run.calls, [])

    def test_efibootmgr_fails(self):
        backend = self.backend((2, "", "EFI variables are not supported on this system."))
        with self.assertRaisesRegex(SwitcherError, "not supported"):
            backend.list_entries()

    def test_efibootmgr_missing(self):
        def run(argv, **kwargs):
            raise FileNotFoundError(argv[0])
        backend = LinuxBackend(run=run, efi_dir=self.efi_dir)
        with self.assertRaisesRegex(SwitcherError, "efibootmgr is not installed"):
            backend.list_entries()

    def test_command_and_description(self):
        backend = self.backend()
        self.assertEqual(backend.commands(WINDOWS_ENTRY), [["pkexec", str(self.helper), "0000"]])
        description = backend.describe(WINDOWS_ENTRY)
        self.assertEqual(description[0], f"pkexec {self.helper} 0000")
        self.assertIn("efibootmgr --bootnext 0000 && systemctl reboot", description[1])

    def test_switch_runs_helper_through_pkexec(self):
        backend = self.backend((0, "", ""))
        backend.switch(WINDOWS_ENTRY)
        self.assertEqual(self.run.calls, [["pkexec", str(self.helper), "0000"]])

    def test_switch_without_installed_helper(self):
        self.helper.unlink()
        backend = self.backend()
        with self.assertRaisesRegex(SwitcherError, "not installed"):
            backend.switch(WINDOWS_ENTRY)
        self.assertEqual(self.run.calls, [])

    def test_switch_errors(self):
        for code, stderr, message in [
            (126, "", "Cancelled"),
            (127, "Not authorized", "Authorization failed"),
            (1, "Boot entry 0000 not found", "Boot entry 0000 not found"),
        ]:
            with self.subTest(code=code):
                with self.assertRaisesRegex(SwitcherError, message):
                    self.backend((code, "", stderr)).switch(WINDOWS_ENTRY)


class WindowsBackendTest(unittest.TestCase):
    def backend(self, *results, firmware_type=2, is_admin=True):
        self.run = FakeRun(*results)
        return WindowsBackend(run=self.run, firmware_type=lambda: firmware_type,
                              is_admin=lambda: is_admin)

    def test_list_entries_parses_bcdedit(self):
        backend = self.backend((0, fixture("bcdedit-enum-firmware_PLACEHOLDER.txt"), ""))
        entries = backend.list_entries()
        self.assertEqual(self.run.calls, [[BCDEDIT, "/enum", "firmware"]])
        self.assertIn(DEBIAN_ENTRY, entries)

    def test_bcdedit_and_shutdown_are_called_by_full_path(self):
        self.assertTrue(BCDEDIT.lower().endswith(r"\system32\bcdedit.exe"))
        self.assertTrue(SHUTDOWN.lower().endswith(r"\system32\shutdown.exe"))

    def test_legacy_bios(self):
        backend = self.backend(firmware_type=1)
        with self.assertRaises(NotUefiError):
            backend.list_entries()
        self.assertEqual(self.run.calls, [])

    def test_not_admin(self):
        with self.assertRaises(NotAdminError):
            self.backend(is_admin=False).list_entries()

    def test_bcdedit_fails(self):
        backend = self.backend((1, "The boot configuration data store could not be opened.", ""))
        with self.assertRaisesRegex(SwitcherError, "could not be opened"):
            backend.list_entries()

    def test_no_firmware_entries_means_legacy_bios(self):
        with self.assertRaises(NotUefiError):
            self.backend((0, "", "")).list_entries()

    def test_commands(self):
        self.assertEqual(self.backend().commands(DEBIAN_ENTRY), [
            [BCDEDIT, "/set", "{fwbootmgr}", "bootsequence", DEBIAN_ENTRY.id],
            [SHUTDOWN, "/r", "/t", "0"],
        ])
        self.assertEqual(self.backend().describe(DEBIAN_ENTRY), [
            f"{BCDEDIT} /set {{fwbootmgr}} bootsequence {DEBIAN_ENTRY.id}",
            f"{SHUTDOWN} /r /t 0",
        ])

    def test_switch_sets_boot_next_then_restarts(self):
        backend = self.backend((0, "The operation completed successfully.", ""), (0, "", ""))
        backend.switch(DEBIAN_ENTRY)
        self.assertEqual(self.run.calls, backend.commands(DEBIAN_ENTRY))

    def test_no_restart_when_bcdedit_fails(self):
        backend = self.backend((1, "The parameter is incorrect.", ""))
        with self.assertRaisesRegex(SwitcherError, "Nothing was changed"):
            backend.switch(DEBIAN_ENTRY)
        self.assertEqual(len(self.run.calls), 1)

    def test_restart_fails_after_boot_next_was_set(self):
        backend = self.backend((0, "", ""), (1, "", "Access is denied."))
        with self.assertRaisesRegex(SwitcherError, "deletevalue"):
            backend.switch(DEBIAN_ENTRY)


if __name__ == "__main__":
    unittest.main()
