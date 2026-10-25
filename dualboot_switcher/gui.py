"""The window: pick what to restart into, then restart.

The main view shows only the choice (OS, boot entry, disk) and the buttons.
The exact command and the full list of boot entries are one click away under
"Show details".

Start it with --dry-run to go through everything without changing anything:
the restart button then only says what would have happened.
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
import traceback
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from . import __version__, config
from .backend import get_backend
from .classify import OS_NAMES, classify, pick_target, target_kind
from .cli import format_table
from .model import SwitcherError

TITLE = "Dual Boot Switcher"
GREY = "#5f5f5f"


def main(argv=None) -> int:
    # Parsed by hand: a windowed .exe has no console for argparse to print to.
    argv = sys.argv[1:] if argv is None else argv
    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        backend = get_backend()
    except SwitcherError as error:
        root.withdraw()
        messagebox.showerror(TITLE, str(error))
        return 1
    App(root, backend, dry_run="--dry-run" in argv)
    root.mainloop()
    return 0


class App:
    def __init__(self, root, backend, dry_run=False, config_path=None):
        self.root = root
        self.backend = backend
        self.dry_run = dry_run
        self.config_path = config_path
        self.os_name = OS_NAMES[target_kind(backend.current_os)]
        self.entries = []
        self.target = None

        root.title(TITLE + (" (dry run)" if dry_run else ""))
        root.resizable(False, False)
        root.report_callback_exception = self._report_unexpected
        default_font = tkfont.nametofont("TkDefaultFont")
        line_height = default_font.metrics("linespace")
        style = ttk.Style(root)
        if sys.platform != "win32" and "clam" in style.theme_names():
            style.theme_use("clam")
            # clam draws radio buttons at a fixed 10px, tiny on HiDPI screens.
            style.configure("TRadiobutton", indicatorsize=max(10, line_height // 2))
        self.heading_font = default_font.copy()
        size = self.heading_font.cget("size")  # negative means pixels
        self.heading_font.configure(size=size + 4 if size > 0 else size - 5, weight="bold")
        self.choice_font = default_font.copy()
        self.choice_font.configure(weight="bold")
        style.configure("Choice.TRadiobutton", font=self.choice_font)
        # Lines under a radio button line up with its text.
        self.indent = max(10, line_height // 2) + line_height // 2
        # Paragraphs are at least 60 characters wide, wider if the window is.
        self.min_wrap = default_font.measure("0") * 60
        self.paragraphs = []

        self.frame = ttk.Frame(root, padding=16)
        self.frame.pack(fill="both", expand=True)
        self.frame.bind("<Configure>", self._rewrap)
        if dry_run:
            tk.Label(self.frame, text="DRY RUN: nothing will be changed and the computer "
                                      "won't restart.",
                     bg="#fff3cd", fg="#664d03", padx=8, pady=6).pack(fill="x", pady=(0, 12))
        self._load()

    # Building the window

    def _load(self):
        try:
            self.entries = self.backend.list_entries()
            self.target, candidates = pick_target(
                self.entries, self.backend.current_os, *config.load_choice(self.config_path))
            disks = {entry.id: self.backend.disk_label(entry) for entry in candidates}
        except SwitcherError as error:
            self._show_problem(str(error))
        except Exception as error:  # the .exe has no console, so show everything
            self._show_problem(f"Unexpected error: {error!r}")
        else:
            self._show_choices(candidates, disks)

    def _show_problem(self, message):
        self._heading("Can't switch")
        self._paragraph(message)
        buttons = self._button_row()
        ttk.Button(buttons, text="Close", command=self.root.destroy).pack(side="right")
        if self.entries:
            self._add_details(buttons, with_command=False)

    def _show_choices(self, candidates, disks):
        self._heading("Restart into")
        self.choice = tk.StringVar(value=self.target.id if self.target else "")
        for entry in candidates:
            self._add_choice(entry, disks[entry.id])
        if len(candidates) > 1:
            self._paragraph(f"More than one {self.os_name} was found. "
                            "Your choice is remembered for next time.", foreground=GREY)

        buttons = self._button_row()
        self.restart_button = ttk.Button(buttons, text=f"Restart into {self.os_name}",
                                         command=self._confirm_and_switch)
        self.restart_button.pack(side="right")
        ttk.Button(buttons, text="Close", command=self.root.destroy).pack(side="right", padx=(0, 8))
        self._add_details(buttons, with_command=True)
        self.status = tk.StringVar()
        ttk.Label(buttons, textvariable=self.status, foreground=GREY).pack(side="left", padx=(12, 0))
        self._update_command()

    def _add_choice(self, entry, disk):
        def select(_event=None):
            self.choice.set(entry.id)
            self._choose(entry)

        ttk.Radiobutton(self.frame, text=OS_NAMES[classify(entry)], value=entry.id,
                        variable=self.choice, command=select, style="Choice.TRadiobutton",
                        ).pack(anchor="w", pady=(6, 0))
        details = entry.label + (f"\non {disk}" if disk else "")
        label = ttk.Label(self.frame, text=details, foreground=GREY, justify="left")
        label.pack(anchor="w", padx=(self.indent, 0))
        label.bind("<Button-1>", select)

    def _add_details(self, buttons, with_command):
        """A "Show details" button and the hidden section it opens."""
        self.details = ttk.Frame(self.frame)
        if with_command:
            ttk.Label(self.details, text="Command that will run:").pack(anchor="w")
            self.command_box = self._text_box(self.details)
        ttk.Label(self.details, text="All boot entries:").pack(anchor="w")
        self._set_text(self._text_box(self.details), format_table(self.entries))
        copy = ttk.Button(self.details, text="Copy boot entries", command=lambda: self._copy(copy))
        copy.pack(anchor="e")

        def toggle():
            if self.details.winfo_manager():
                self.details.pack_forget()
                self.details_button.configure(text="Show details")
            else:
                self.details.pack(fill="x", pady=(16, 0), after=buttons)
                self.details_button.configure(text="Hide details")

        self.details_button = ttk.Button(buttons, text="Show details", command=toggle)
        self.details_button.pack(side="left")

    def _heading(self, text):
        ttk.Label(self.frame, text=text, font=self.heading_font).pack(anchor="w", pady=(0, 4))

    def _paragraph(self, text, **options):
        label = ttk.Label(self.frame, text=text, wraplength=self.min_wrap, justify="left",
                          **options)
        label.pack(anchor="w", pady=(8, 0))
        self.paragraphs.append(label)

    def _rewrap(self, event):
        for label in self.paragraphs:
            label.configure(wraplength=max(event.width - 32, self.min_wrap))

    def _button_row(self):
        row = ttk.Frame(self.frame)
        row.pack(fill="x", pady=(20, 0))
        return row

    @staticmethod
    def _text_box(parent):
        box = tk.Text(parent, font="TkFixedFont", wrap="none", relief="solid",
                      borderwidth=1, padx=6, pady=4, height=1, width=40)
        box.pack(fill="x", pady=(2, 8))
        return box

    @staticmethod
    def _set_text(box, text):
        lines = text.splitlines() or [""]
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled", height=min(len(lines), 20),
                      width=max(len(line) for line in lines) + 1)

    # Actions

    def _choose(self, entry):
        self.target = entry
        try:
            config.save_choice(entry, self.config_path)
        except OSError:
            pass  # only a convenience: the choice is asked again next time
        self._update_command()

    def _update_command(self):
        if self.target:
            self._set_text(self.command_box, "\n".join(self.backend.describe(self.target)))
            self.restart_button.state(["!disabled"])
        else:
            self._set_text(self.command_box, "(choose what to restart into first)")
            self.restart_button.state(["disabled"])

    def _copy(self, button):
        report = (f"Dual Boot Switcher {__version__} on {OS_NAMES[self.backend.current_os]}\n\n"
                  + format_table(self.entries))
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        button.configure(text="Copied")

    def _confirm_and_switch(self):
        if not messagebox.askokcancel(
                TITLE, f"Restart into {self.os_name} now?",
                detail=f"The computer restarts into {self.target.label} right away. "
                       "Open programs will be closed, so save your work first.\n\n"
                       "Only this one restart is affected; your normal boot order "
                       "doesn't change.",
                icon="warning", default="cancel", parent=self.root):
            return
        if self.dry_run:
            messagebox.showinfo(TITLE, "Dry run: nothing was changed.",
                                detail="Without --dry-run, the command under "
                                       "\"Show details\" would have run and the computer "
                                       "would have restarted.",
                                parent=self.root)
            return
        self.restart_button.state(["disabled"])
        self.status.set("Switching...")
        self._error = None
        # A thread keeps the window responsive while polkit asks for a password.
        worker = threading.Thread(target=self._switch, daemon=True)
        worker.start()
        self._wait_for(worker)

    def _switch(self):
        try:
            self.backend.switch(self.target)
        except Exception as error:
            self._error = error

    def _wait_for(self, worker):
        if worker.is_alive():
            self.root.after(100, self._wait_for, worker)
        elif self._error:
            self.status.set("")
            self.restart_button.state(["!disabled"])
            messagebox.showerror(TITLE, str(self._error), parent=self.root)
        else:
            self.status.set(f"Restarting into {self.os_name}...")

    def _report_unexpected(self, exc_type, error, tb):
        if sys.stderr:
            traceback.print_exception(exc_type, error, tb)
        messagebox.showerror(TITLE, f"Unexpected error: {error!r}", parent=self.root)


def _enable_dpi_awareness():
    """Without this, Windows scales the window up and it looks blurry."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
