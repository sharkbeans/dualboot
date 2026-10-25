import unittest

from dualboot_switcher.model import BootEntry
from dualboot_switcher.parse_efibootmgr import parse

from . import fixture


class LenovoLmdeFixtureTest(unittest.TestCase):
    def setUp(self):
        self.entries = parse(fixture("efibootmgr-v_lenovo-lmde.txt"))
        self.by_id = {entry.id: entry for entry in self.entries}

    def test_reads_every_boot_entry_and_skips_header_and_dp_lines(self):
        self.assertEqual(
            [entry.id for entry in self.entries],
            ["0000", "0001", "0010", "0011", "0012", "0013", "0014", "0015",
             "0016", "0017", "0018", "0019", "001A", "001B", "001C", "001D", "001E"],
        )

    def test_windows_entry(self):
        self.assertEqual(self.by_id["0000"], BootEntry(
            id="0000",
            label="Windows Boot Manager",
            path=r"\EFI\MICROSOFT\BOOT\BOOTMGFW.EFI",
            active=True,
        ))

    def test_lmde_registers_as_debian(self):
        self.assertEqual(self.by_id["0001"], BootEntry(
            id="0001", label="debian", path=r"\EFI\debian\shimx64.efi", active=True,
        ))

    def test_inactive_firmware_tool_has_no_path(self):
        self.assertEqual(self.by_id["0010"], BootEntry(
            id="0010", label="Setup", path=None, active=False,
        ))

    def test_device_entry_has_no_path(self):
        self.assertEqual(self.by_id["001C"], BootEntry(
            id="001C", label="PXE BOOT", path=None, active=True,
        ))

    def test_labels_with_spaces(self):
        self.assertEqual(self.by_id["0014"].label, "ThinkShield secure wipe")
        self.assertEqual(self.by_id["001E"].label, "Boot Next Boot Option")


class OtherFormatsTest(unittest.TestCase):
    def test_empty_output(self):
        self.assertEqual(parse(""), [])

    def test_without_verbose_flag(self):
        # Plain `efibootmgr` prints labels without device paths.
        entries = parse("BootCurrent: 0001\nBoot0000* Windows Boot Manager\nBoot0001* debian\n")
        self.assertEqual(entries, [
            BootEntry(id="0000", label="Windows Boot Manager", path=None, active=True),
            BootEntry(id="0001", label="debian", path=None, active=True),
        ])

    def test_optional_data_after_device_path(self):
        # efibootmgr 17 and older run optional data straight on after the path.
        line = ("Boot0000* Windows Boot Manager\tHD(1,GPT,...)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)"
                "WINDOWS.........x...B.C.D.O.B.J.E.C.T.=.{9dea862c-...}...")
        self.assertEqual(parse(line)[0].path, r"\EFI\Microsoft\Boot\bootmgfw.efi")

    def test_lowercase_hex_and_boot_next_header(self):
        entries = parse("BootNext: 0000\nBoot001a* ATA HDD0\tVenMsg(...)\n")
        self.assertEqual([entry.id for entry in entries], ["001A"])

    def test_partition_guid(self):
        line = ("Boot0001* debian\tHD(2,GPT,E9843F70-5110-4F0E-9EC2-1E16BA0C3213,0x40800,0x32000)"
                "/File(\\EFI\\debian\\shimx64.efi)")
        self.assertEqual(parse(line)[0].partition_guid, "e9843f70-5110-4f0e-9ec2-1e16ba0c3213")

    def test_no_partition_guid_for_firmware_entries(self):
        self.assertIsNone(parse("Boot0010  Setup\tFvFile(721c8b66-...)")[0].partition_guid)

    def test_data_lines_are_ignored(self):
        text = "Boot0001* debian\tHD(...)/File(\\EFI\\debian\\shimx64.efi)\n    data: 01 02 03\n"
        self.assertEqual(len(parse(text)), 1)


if __name__ == "__main__":
    unittest.main()
