"""GUI tests. Skipped where tkinter or a display isn't available."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from dualboot_switcher import config
from dualboot_switcher.classify import LINUX, WINDOWS
from dualboot_switcher.model import SwitcherError

from .test_cli import FEDORA, UBUNTU, USB, WINDOWS_ENTRY, FakeBackend

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
        if isinstance(child, (ttk.Label, ttk.Button, tk.Label)):
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

    def test_single_target_shows_command(self):
        app = self.app(FakeBackend(LINUX, [WINDOWS_ENTRY, USB]))
        self.assertIn("Restart into Windows", texts(app.frame))
        self.assertIn("set-boot-next 0000", app.command_box.get("1.0", "end"))
        self.assertFalse(app.restart_button.instate(["disabled"]))

    def test_dry_run_banner(self):
        app = self.app(FakeBackend(LINUX, [WINDOWS_ENTRY]), dry_run=True)
        self.assertTrue(any("DRY RUN" in text for text in texts(app.frame)))
        self.assertIn("dry run", self.root.title())

    def test_picker_when_several_candidates(self):
        app = self.app(FakeBackend(WINDOWS, [UBUNTU, FEDORA]))
        self.assertTrue(app.restart_button.instate(["disabled"]))
        app._choose(FEDORA)
        self.assertFalse(app.restart_button.instate(["disabled"]))
        self.assertIn("set-boot-next {bbbb}", app.command_box.get("1.0", "end"))
        self.assertEqual(config.load_choice(self.config_path), ("{bbbb}", "Fedora"))

    def test_problem_is_shown(self):
        app = self.app(FakeBackend(LINUX, [], error=SwitcherError("legacy BIOS mode")))
        self.assertIn("Can't switch", texts(app.frame))
        self.assertIn("legacy BIOS mode", texts(app.frame))

    def test_no_target_still_offers_entry_list(self):
        app = self.app(FakeBackend(LINUX, [USB]))
        self.assertIn("Can't switch", texts(app.frame))
        self.assertIn("Show all boot entries", texts(app.frame))

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
