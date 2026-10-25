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


def fake(n):
    return "{00000000-0000-0000-0000-0000000000%02d}" % n


# The KIND column of the app's own "Copy boot entries" output (v0.1.0-rc2)
# on the machine bcdedit_firmware_en_us.txt comes from, GUIDs replaced.
# Checked by hand against that machine's firmware setup.
WINDOWS_GOLDEN = [
    ("{bootmgr}", "Windows Boot Manager", OTHER),
    (fake(1), "debian", LINUX),
    (fake(2), "Windows Boot Manager", WINDOWS),
    (fake(3), "USB HDD", DEVICE),
    (fake(4), "PXE BOOT", DEVICE),
    (fake(5), "USB CD", DEVICE),
    (fake(6), "USB FDD", DEVICE),
    (fake(7), "NVMe0", DEVICE),
    (fake(8), "ATA HDD0", DEVICE),
    (fake(9), "Setup", FIRMWARE),
    (fake(10), "Boot Menu", FIRMWARE),
    (fake(11), "Diagnostic Splash Screen", FIRMWARE),
    (fake(12), "Lenovo Diagnostics", FIRMWARE),
    (fake(13), "ThinkShield secure wipe", FIRMWARE),
    (fake(14), "Startup Interrupt Menu", FIRMWARE),
    (fake(15), "Rescue and Recovery", FIRMWARE),
    (fake(16), "Regulatory Information", FIRMWARE),
    (fake(17), "Boot Next Boot Option", FIRMWARE),
]


class RealBcdeditOutputTest(unittest.TestCase):
    def setUp(self):
        self.entries = parse_bcdedit.parse(fixture("bcdedit_firmware_en_us.txt"))

    def test_kinds_match_the_golden_table(self):
        self.assertEqual([(e.id, e.label, classify(e)) for e in self.entries], WINDOWS_GOLDEN)

    def test_debian_is_the_only_target(self):
        target, candidates = pick_target(self.entries, WINDOWS)
        self.assertEqual((target.id, target.label), (fake(1), "debian"))
        self.assertEqual(candidates, [target])

    def test_bootmgr_is_excluded_by_its_identifier(self):
        # On some PCs the {bootmgr} block does have the bootmgfw.efi path.
        bootmgr = BootEntry(id="{bootmgr}", label="Windows Boot Manager",
                            path=r"\EFI\Microsoft\Boot\bootmgfw.efi")
        self.assertEqual(classify(bootmgr), OTHER)
        with self.assertRaises(EntryNotFoundError):
            pick_target([bootmgr], LINUX)


class TwoLinuxEntriesTest(unittest.TestCase):
    """bcdedit_firmware_two_linux.txt: the real output plus an ubuntu entry."""

    def setUp(self):
        self.entries = parse_bcdedit.parse(fixture("bcdedit_firmware_two_linux.txt"))

    def test_user_must_choose(self):
        target, candidates = pick_target(self.entries, WINDOWS)
        self.assertIsNone(target)
        self.assertEqual([(e.id, e.label) for e in candidates],
                         [(fake(1), "debian"), (fake(18), "ubuntu")])

    def test_cached_choice(self):
        target, _ = pick_target(self.entries, WINDOWS, cached_id=fake(18), cached_label="ubuntu")
        self.assertEqual(target.path, r"\EFI\ubuntu\grubx64.efi")

    def test_stale_cached_choice(self):
        target, _ = pick_target(self.entries, WINDOWS, cached_id=fake(18), cached_label="Fedora")
        self.assertIsNone(target)


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
        a = entry("ubuntu", r"\EFI\ubuntu\shimx64.efi", id="{AAAA-0001}")
        b = entry("Fedora", r"\EFI\fedora\shimx64.efi", id="{bbbb-0002}")
        target, _ = pick_target([a, b], WINDOWS, cached_id="{BBBB-0002}", cached_label="Fedora")
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
