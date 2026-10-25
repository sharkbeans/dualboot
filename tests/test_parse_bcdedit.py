"""Tests for the bcdedit parser.

bcdedit_firmware_en_us.txt is real `bcdedit /enum firmware` output from
Windows 11 (en-US) on a Lenovo ThinkPad with LMDE 7, GUIDs replaced.
"""

import unittest

from dualboot_switcher.model import BootEntry
from dualboot_switcher.parse_bcdedit import parse

from . import fixture


def fake(n):
    """The fake GUID that stands in for a real one in the fixtures."""
    return "{00000000-0000-0000-0000-0000000000%02d}" % n


class RealOutputTest(unittest.TestCase):
    def setUp(self):
        self.text = fixture("bcdedit_firmware_en_us.txt")
        self.entries = parse(self.text)
        self.by_id = {entry.id: entry for entry in self.entries}

    def test_every_entry_once_in_order(self):
        # {fwbootmgr} is the firmware boot manager itself, not an entry, and
        # the GUIDs continuing its displayorder line must not become entries.
        self.assertEqual([entry.id for entry in self.entries],
                         ["{bootmgr}"] + [fake(n) for n in range(1, 18)])

    def test_bootmgr_block_has_no_path(self):
        self.assertEqual(self.by_id["{bootmgr}"],
                         BootEntry(id="{bootmgr}", label="Windows Boot Manager"))

    def test_linux_entry(self):
        self.assertEqual(self.by_id[fake(1)],
                         BootEntry(id=fake(1), label="debian", path=r"\EFI\debian\shimx64.efi"))

    def test_windows_firmware_entry_keeps_its_uppercase_path(self):
        self.assertEqual(self.by_id[fake(2)],
                         BootEntry(id=fake(2), label="Windows Boot Manager",
                                   path=r"\EFI\MICROSOFT\BOOT\BOOTMGFW.EFI"))

    def test_device_and_firmware_entries_have_no_path(self):
        for n, label in [(3, "USB HDD"), (4, "PXE BOOT"), (13, "ThinkShield secure wipe")]:
            with self.subTest(label=label):
                self.assertEqual(self.by_id[fake(n)], BootEntry(id=fake(n), label=label))

    def test_active_flag_is_unknown(self):
        # bcdedit doesn't show one, so the parser mustn't make one up.
        self.assertTrue(all(entry.active is None for entry in self.entries))

    def test_windows_line_endings(self):
        self.assertEqual(parse(self.text.replace("\n", "\r\n")), self.entries)

    def test_section_titles_are_not_needed(self):
        # Titles like "Firmware Application (101fffff)" are translated, so
        # the parser must work whatever they say.
        lines = self.text.splitlines()
        garbled = ["Xq7 zzkw (%d)" % i if i + 1 < len(lines) and set(lines[i + 1]) == {"-"}
                   else line for i, line in enumerate(lines)]
        self.assertNotIn("Firmware Application", "\n".join(garbled))
        self.assertEqual(parse("\n".join(garbled)), self.entries)


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
            "Bezeichner              " + fake(1) + "\n"
            "device                  partition=\\Device\\HarddiskVolume1\n"
            "path                    \\EFI\\debian\\shimx64.efi\n"
            "description             debian\n"
        )
        self.assertEqual(parse(text), [
            BootEntry(id=fake(1), label="debian", path=r"\EFI\debian\shimx64.efi"),
        ])

    def test_every_key_translated(self):
        text = (
            "Firmwareanwendung (101fffff)\n"
            "----------------------------\n"
            "Bezeichner              " + fake(1) + "\n"
            "Gerät                   partition=\\Device\\HarddiskVolume1\n"
            "Pfad                    \\EFI\\debian\\shimx64.efi\n"
            "Beschreibung            debian\n"
        )
        self.assertEqual(parse(text), [
            BootEntry(id=fake(1), label="debian", path=r"\EFI\debian\shimx64.efi"),
        ])

    def test_unknown_description_key_still_finds_path(self):
        text = (
            "Application\n"
            "-----------\n"
            "xyz                     " + fake(1) + "\n"
            "abc                     \\EFI\\debian\\shimx64.efi\n"
            "qqq                     debian\n"
        )
        self.assertEqual(parse(text), [
            BootEntry(id=fake(1), label="", path=r"\EFI\debian\shimx64.efi"),
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
