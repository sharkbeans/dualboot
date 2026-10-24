import unittest

from dualboot_switcher import parse_bcdedit, parse_efibootmgr
from dualboot_switcher.classify import (
    DEVICE, FIRMWARE, LINUX, OTHER, WINDOWS, classify, pick_target,
)
from dualboot_switcher.model import BootEntry, EntryNotFoundError

from . import fixture


def entry(label, path=None, id="0001", active=True):
    return BootEntry(id=id, label=label, path=path, active=active)


class LenovoLmdeFixtureTest(unittest.TestCase):
    def setUp(self):
        self.entries = parse_efibootmgr.parse(fixture("efibootmgr-v_lenovo-lmde.txt"))

    def test_kinds(self):
        kinds = {e.label: classify(e) for e in self.entries}
        self.assertEqual(kinds, {
            "Windows Boot Manager": WINDOWS,
            "debian": LINUX,
            "Setup": FIRMWARE,
            "Boot Menu": FIRMWARE,
            "Diagnostic Splash Screen": FIRMWARE,
            "Lenovo Diagnostics": FIRMWARE,
            "ThinkShield secure wipe": FIRMWARE,
            "Startup Interrupt Menu": FIRMWARE,
            "Rescue and Recovery": FIRMWARE,
            "Regulatory Information": FIRMWARE,
            "Boot Next Boot Option": FIRMWARE,
            "USB CD": DEVICE,
            "USB FDD": DEVICE,
            "NVMe0": DEVICE,
            "ATA HDD0": DEVICE,
            "USB HDD": DEVICE,
            "PXE BOOT": DEVICE,
        })

    def test_from_linux_picks_windows(self):
        target, candidates = pick_target(self.entries, LINUX)
        self.assertEqual(target.id, "0000")
        self.assertEqual(candidates, [target])

    def test_from_windows_picks_debian(self):
        # Same firmware entries as Windows would see them.
        target, _ = pick_target(self.entries, WINDOWS)
        self.assertEqual((target.id, target.label), ("0001", "debian"))


class PlaceholderBcdeditFixtureTest(unittest.TestCase):
    def test_from_windows_picks_debian(self):
        entries = parse_bcdedit.parse(fixture("bcdedit-enum-firmware_PLACEHOLDER.txt"))
        target, _ = pick_target(entries, WINDOWS)
        self.assertEqual(target.id, "{00000000-0000-0000-0000-000000000001}")


class ClassifyTest(unittest.TestCase):
    def test_linux_loaders(self):
        for path in [r"\EFI\debian\shimx64.efi", r"\EFI\ubuntu\grubx64.efi",
                     r"\EFI\fedora\shimx64.efi", r"\EFI\opensuse\shim.efi",
                     r"\EFI\systemd\systemd-bootx64.efi", r"\EFI\mydistro\grubaa64.efi",
                     "/EFI/debian/shimx64.efi"]:
            with self.subTest(path=path):
                self.assertEqual(classify(entry("whatever", path)), LINUX)

    def test_known_distro_folder_or_label_with_unusual_loader(self):
        self.assertEqual(classify(entry("x", r"\EFI\arch\loader.efi")), LINUX)
        self.assertEqual(classify(entry("Linux Mint", r"\EFI\custom\boot.efi")), LINUX)

    def test_windows_path_is_case_insensitive(self):
        self.assertEqual(classify(entry("x", r"\efi\microsoft\boot\BOOTMGFW.efi")), WINDOWS)

    def test_not_operating_systems(self):
        for label, path in [
            ("UEFI: SanDisk", r"\EFI\BOOT\BOOTX64.EFI"),      # removable fallback
            ("rEFInd", r"\EFI\refind\refind_x64.efi"),
            ("MokManager", r"\EFI\debian\mmx64.efi"),
            ("Windows Boot Manager", None),                   # no path: firmware-provided
            ("debian", None),
            ("Windows Boot Manager", r"\EFI\Microsoft\Boot\other.efi"),
        ]:
            with self.subTest(label=label, path=path):
                self.assertEqual(classify(entry(label, path)), OTHER)

    def test_firmware_tool_label_wins_over_path(self):
        self.assertEqual(classify(entry("ThinkShield secure wipe", r"\EFI\debian\shimx64.efi")), FIRMWARE)
        self.assertEqual(classify(entry("Windows Recovery", r"\EFI\Microsoft\Boot\bootmgfw.efi")), FIRMWARE)
        self.assertEqual(classify(entry("HP Diagnostics", r"\EFI\HP\SystemDiags\CpuDiag.efi")), FIRMWARE)

    def test_device_labels(self):
        for label in ["UEFI PXEv4", "IPV6 Network", "CD/DVD Drive", "Hard Drive", "USB: Kingston"]:
            with self.subTest(label=label):
                self.assertEqual(classify(entry(label)), DEVICE)


class PickTargetTest(unittest.TestCase):
    ubuntu = entry("ubuntu", r"\EFI\ubuntu\shimx64.efi", id="0003")
    fedora = entry("Fedora", r"\EFI\fedora\shimx64.efi", id="0004")
    windows = entry("Windows Boot Manager", r"\EFI\Microsoft\Boot\bootmgfw.efi", id="0000")

    def test_several_candidates_without_cache_asks_user(self):
        target, candidates = pick_target([self.windows, self.ubuntu, self.fedora], WINDOWS)
        self.assertIsNone(target)
        self.assertEqual(candidates, [self.ubuntu, self.fedora])

    def test_cached_choice_is_used(self):
        target, _ = pick_target([self.ubuntu, self.fedora], WINDOWS,
                                cached_id="0004", cached_label="Fedora")
        self.assertEqual(target, self.fedora)

    def test_cached_id_is_case_insensitive(self):
        a = entry("ubuntu", r"\EFI\ubuntu\shimx64.efi", id="{AAAA}")
        b = entry("Fedora", r"\EFI\fedora\shimx64.efi", id="{bbbb}")
        target, _ = pick_target([a, b], WINDOWS, cached_id="{BBBB}", cached_label="Fedora")
        self.assertEqual(target, b)

    def test_stale_cache_is_ignored(self):
        # Entry 0004 now belongs to something else, e.g. after a firmware update.
        target, _ = pick_target([self.ubuntu, self.fedora], WINDOWS,
                                cached_id="0004", cached_label="openSUSE")
        self.assertIsNone(target)

    def test_single_candidate_ignores_cache(self):
        target, _ = pick_target([self.windows, self.ubuntu], WINDOWS,
                                cached_id="0004", cached_label="Fedora")
        self.assertEqual(target, self.ubuntu)

    def test_inactive_entries_are_not_candidates(self):
        inactive = entry("ubuntu", r"\EFI\ubuntu\shimx64.efi", active=False)
        with self.assertRaises(EntryNotFoundError):
            pick_target([self.windows, inactive], WINDOWS)

    def test_no_windows_entry(self):
        with self.assertRaises(EntryNotFoundError) as caught:
            pick_target([self.ubuntu], LINUX)
        self.assertIn("Windows Boot Manager", str(caught.exception))

    def test_no_linux_entry(self):
        with self.assertRaises(EntryNotFoundError) as caught:
            pick_target([self.windows, entry("USB CD")], WINDOWS)
        self.assertIn("Linux", str(caught.exception))

    def test_empty_list(self):
        with self.assertRaises(EntryNotFoundError):
            pick_target([], LINUX)


if __name__ == "__main__":
    unittest.main()
