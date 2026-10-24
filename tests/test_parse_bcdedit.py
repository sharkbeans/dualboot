"""Tests for the bcdedit parser.

PLACEHOLDER: the fixture used here is hand-written, not real bcdedit output.
Once real output from the Windows side is available it will be added as a
second fixture and these tests will run against both.
"""

import unittest

from dualboot_switcher.model import BootEntry
from dualboot_switcher.parse_bcdedit import parse

from . import fixture

DEBIAN_ID = "{00000000-0000-0000-0000-000000000001}"


class PlaceholderFixtureTest(unittest.TestCase):
    def setUp(self):
        self.text = fixture("bcdedit-enum-firmware_PLACEHOLDER.txt")
        self.entries = parse(self.text)
        self.by_id = {entry.id: entry for entry in self.entries}

    def test_skips_firmware_boot_manager_and_displayorder_lines(self):
        self.assertEqual(
            [entry.id for entry in self.entries],
            ["{bootmgr}"] + ["{00000000-0000-0000-0000-00000000000%d}" % n for n in range(1, 7)],
        )

    def test_windows_boot_manager(self):
        self.assertEqual(self.by_id["{bootmgr}"], BootEntry(
            id="{bootmgr}",
            label="Windows Boot Manager",
            path=r"\EFI\Microsoft\Boot\bootmgfw.efi",
        ))

    def test_linux_entry(self):
        self.assertEqual(self.by_id[DEBIAN_ID], BootEntry(
            id=DEBIAN_ID, label="debian", path=r"\EFI\debian\shimx64.efi",
        ))

    def test_device_entry_has_no_path(self):
        entry = self.by_id["{00000000-0000-0000-0000-000000000004}"]
        self.assertEqual((entry.label, entry.path), ("USB CD", None))

    def test_windows_line_endings(self):
        self.assertEqual(parse(self.text.replace("\n", "\r\n")), self.entries)


class LocalizedOutputTest(unittest.TestCase):
    def test_translated_titles_and_identifier_key(self):
        text = (
            "Firmware-Start-Manager\n"
            "----------------------\n"
            "Bezeichner              {fwbootmgr}\n"
            "displayorder            {bootmgr}\n"
            "\n"
            "Firmwareanwendung (101fffff)\n"
            "----------------------------\n"
            "Bezeichner              " + DEBIAN_ID + "\n"
            "device                  partition=\\Device\\HarddiskVolume1\n"
            "path                    \\EFI\\debian\\shimx64.efi\n"
            "description             debian\n"
        )
        self.assertEqual(parse(text), [
            BootEntry(id=DEBIAN_ID, label="debian", path=r"\EFI\debian\shimx64.efi"),
        ])

    def test_every_key_translated(self):
        text = (
            "Firmwareanwendung (101fffff)\n"
            "----------------------------\n"
            "Bezeichner              " + DEBIAN_ID + "\n"
            "Gerät                   partition=\\Device\\HarddiskVolume1\n"
            "Pfad                    \\EFI\\debian\\shimx64.efi\n"
            "Beschreibung            debian\n"
        )
        self.assertEqual(parse(text), [
            BootEntry(id=DEBIAN_ID, label="debian", path=r"\EFI\debian\shimx64.efi"),
        ])

    def test_unknown_description_key_still_finds_path(self):
        text = (
            "Application\n"
            "-----------\n"
            "xyz                     " + DEBIAN_ID + "\n"
            "abc                     \\EFI\\debian\\shimx64.efi\n"
            "qqq                     debian\n"
        )
        self.assertEqual(parse(text), [
            BootEntry(id=DEBIAN_ID, label="", path=r"\EFI\debian\shimx64.efi"),
        ])


class BadOutputTest(unittest.TestCase):
    def test_empty_output(self):
        self.assertEqual(parse(""), [])

    def test_access_denied_message(self):
        text = ("The boot configuration data store could not be opened.\n"
                "Access is denied.\n")
        self.assertEqual(parse(text), [])

    def test_block_without_identifier_is_skipped(self):
        self.assertEqual(parse("Title\n-----\ndescription   something\n"), [])


if __name__ == "__main__":
    unittest.main()
