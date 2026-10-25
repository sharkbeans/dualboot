"""GUI tests. Skipped where tkinter or a display isn't available."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dualboot_switcher import config
from dualboot_switcher.classify import LINUX, WINDOWS
from dualboot_switcher.model import BootEntry, SwitcherError

from .test_cli import FEDORA, UBUNTU, USB, WINDOWS_ENTRY, FakeBackend, windows_backend

USB_FALLBACK = BootEntry(id="0005", label="UEFI: SanDisk", path=r"\EFI\BOOT\BOOTX64.EFI")

try:
    import tkinter as tk
    from tkinter import ttk
    tk.Tk().destroy()
    from dualboot_switcher.gui import App
    HAVE_DISPLAY = True
except Exception:
    HAVE_DISPLAY = False


def texts(widget):
    """The text of every label and button inside widget."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Label, ttk.Button, ttk.Radiobutton, tk.Label)):
            found.append(str(child.cget("text")))
        found.extend(texts(child))
    return found


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter and a display")
class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        self.tmp.cleanup()

    def app(self, backend, dry_run=False):
        return App(self.root, backend, dry_run=dry_run, config_path=self.config_path)

    def test_real_windows_output(self):
        app = self.app(windows_backend("bcdedit_firmware_en_us.txt"))
        self.assertEqual(app.choice.get(), "{00000000-0000-0000-0000-000000000001}")
        self.assertIn("debian", texts(app.frame))
        self.assertIn("bootsequence {00000000-0000-0000-0000-000000000001}",
                      app.command_box.get("1.0", "end"))

    def test_other_entries_only_on_request(self):
        app = self.app(windows_backend("bcdedit_firmware_en_us.txt"))
        self.assertNotIn("{bootmgr}", app.table_box.get("1.0", "end"))
        self.assertIn("ThinkShield secure wipe", app.table_box.get("1.0", "end"))
        app.show_other.set(True)
        app._update_table()
        self.assertIn("{bootmgr}", app.table_box.get("1.0", "end"))

    def test_entries_table_is_capped(self):
        # 18 entries: the box shows 10 rows and scrolls, so the window stays small.
        app = self.app(windows_backend("bcdedit_firmware_en_us.txt"))
        self.assertEqual(int(app.table_box.cget("height")), 10)
        self.assertLessEqual(int(app.table_box.cget("width")), 100)

    def test_copy_has_system_info_and_every_entry(self):
        app = self.app(FakeBackend(LINUX, [WINDOWS_ENTRY, USB, USB_FALLBACK]))
        app._copy(ttk.Button(self.root))
        report = self.root.clipboard_get()
        self.assertTrue(report.startswith("Dual Boot Switcher "))
        self.assertIn(" on TestOS 1.0, UEFI\n", report)
        self.assertIn("UEFI: SanDisk", report)  # an "other" entry, hidden in the window

    def test_single_target_is_selected_with_its_disk(self):
        app = self.app(FakeBackend(LINUX, [WINDOWS_ENTRY, USB]))
        shown = texts(app.frame)
        self.assertIn("Windows", shown)
        self.assertIn("Windows Boot Manager\non Test Disk, 512 GB", shown)
        self.assertEqual(app.choice.get(), "0000")
        self.assertFalse(app.restart_button.instate(["disabled"]))

    def test_command_is_in_hidden_details(self):
        app = self.app(FakeBackend(LINUX, [WINDOWS_ENTRY, USB]))
        self.assertIn("set-boot-next 0000", app.command_box.get("1.0", "end"))
        self.assertEqual(app.details.winfo_manager(), "")  # hidden
        app.details_button.invoke()
        self.assertEqual(app.details.winfo_manager(), "pack")
        self.assertEqual(app.details_button.cget("text"), "Hide details")

    def test_dry_run_banner(self):
        app = self.app(FakeBackend(LINUX, [WINDOWS_ENTRY]), dry_run=True)
        self.assertTrue(any("DRY RUN" in text for text in texts(app.frame)))
        self.assertIn("dry run", self.root.title())

    def test_picker_when_several_candidates(self):
        app = self.app(FakeBackend(WINDOWS, [UBUNTU, FEDORA]))
        self.assertTrue(app.restart_button.instate(["disabled"]))
        app._choose(FEDORA)
        self.assertFalse(app.restart_button.instate(["disabled"]))
        self.assertIn("set-boot-next {bbbb-0002}", app.command_box.get("1.0", "end"))
        self.assertEqual(config.load_choice(self.config_path), ("{bbbb-0002}", "Fedora"))

    def test_problem_is_shown(self):
        app = self.app(FakeBackend(LINUX, [], error=SwitcherError("legacy BIOS mode")))
        self.assertIn("Can't switch", texts(app.frame))
        self.assertIn("legacy BIOS mode", texts(app.frame))

    def test_no_target_still_offers_entry_list(self):
        app = self.app(FakeBackend(LINUX, [USB]))
        self.assertIn("Can't switch", texts(app.frame))
        self.assertIn("Show details", texts(app.frame))

    @mock.patch("tkinter.messagebox.showinfo")
    @mock.patch("tkinter.messagebox.askokcancel", return_value=True)
    def test_dry_run_never_switches(self, asked, informed):
        backend = FakeBackend(LINUX, [WINDOWS_ENTRY])
        self.app(backend, dry_run=True)._confirm_and_switch()
        self.assertIn("save your work", asked.call_args.kwargs["detail"])
        informed.assert_called_once()
        self.assertIsNone(backend.switched)

    @mock.patch("tkinter.messagebox.askokcancel", return_value=False)
    def test_cancel_does_nothing(self, asked):
        backend = FakeBackend(LINUX, [WINDOWS_ENTRY])
        self.app(backend)._confirm_and_switch()
        self.assertIsNone(backend.switched)

    @mock.patch("tkinter.messagebox.askokcancel", return_value=True)
    def test_confirmed_switch(self, asked):
        backend = FakeBackend(LINUX, [WINDOWS_ENTRY])
        app = self.app(backend)
        app._confirm_and_switch()
        deadline = time.monotonic() + 5
        while not app.status.get().startswith("Restarting") and time.monotonic() < deadline:
            self.root.update()
        self.assertEqual(backend.switched, WINDOWS_ENTRY)


if __name__ == "__main__":
    unittest.main()
