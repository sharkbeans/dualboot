"""Backend tests. Commands go to a fake runner; nothing is actually executed."""

import os
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
        self.root = Path(self.tmp.name)
        (self.root / "sys/firmware/efi").mkdir(parents=True)
        self.helper = self.root / "helper"
        self.helper.touch()

    def tearDown(self):
        self.tmp.cleanup()

    def backend(self, *results):
        self.run = FakeRun(*results)
        return LinuxBackend(run=self.run, root=self.root, helper=str(self.helper))

    def test_list_entries_parses_efibootmgr(self):
        backend = self.backend((0, fixture("efibootmgr-v_lenovo-lmde.txt"), ""))
        entries = backend.list_entries()
        self.assertEqual(self.run.calls, [["efibootmgr", "-v"]])
        self.assertEqual(entries[0].label, "Windows Boot Manager")

    def test_legacy_bios(self):
        (self.root / "sys/firmware/efi").rmdir()
        backend = self.backend()
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
        backend = LinuxBackend(run=run, root=self.root)
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


@unittest.skipIf(os.name == "nt", "builds a fake Linux /sys and /dev with symlinks")
class LinuxDiskLabelTest(unittest.TestCase):
    GUID = "e9843f70-5110-4f0e-9ec2-1e16ba0c3213"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.backend = LinuxBackend(root=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def add_disk(self, model="SKHynix_HFS512GD9TNI-L2B0B   ", sectors="1000215216"):
        """Lay out the files the kernel provides for nvme0n1 and its partition p2."""
        disk = self.root / "sys/devices/pci0000:00/nvme/nvme0n1"
        (disk / "nvme0n1p2").mkdir(parents=True)
        (disk / "device").mkdir()
        (disk / "device/model").write_text(model + "\n")
        (disk / "size").write_text(sectors + "\n")
        (self.root / "sys/class/block").mkdir(parents=True)
        (self.root / "sys/class/block/nvme0n1p2").symlink_to(disk / "nvme0n1p2")
        (self.root / "dev/disk/by-partuuid").mkdir(parents=True)
        (self.root / "dev/nvme0n1p2").touch()
        (self.root / "dev/disk/by-partuuid" / self.GUID).symlink_to(self.root / "dev/nvme0n1p2")

    def label(self, guid=GUID):
        return self.backend.disk_label(BootEntry(id="0000", label="x", partition_guid=guid))

    def test_model_and_size(self):
        self.add_disk()
        self.assertEqual(self.label(), "SKHynix HFS512GD9TNI-L2B0B, 512 GB")

    def test_no_model_uses_device_name(self):
        self.add_disk(model="", sectors="3907029168")
        self.assertEqual(self.label(), "nvme0n1, 2.0 TB")

    def test_partition_no_longer_exists(self):
        self.add_disk()
        self.assertIn("disk not found", self.label("00000000-0000-0000-0000-000000000000"))

    def test_entry_without_partition(self):
        self.assertIsNone(self.label(None))


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
