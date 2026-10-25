"""The window: shows the target and the exact command, restarts on request.

Start it with --dry-run to go through everything without changing anything:
the restart button then only shows what it would have run.
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
from .classify import OS_NAMES, pick_target, target_kind
from .cli import format_table
from .model import SwitcherError

TITLE = "Dual Boot Switcher"


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
        style = ttk.Style(root)
        if sys.platform != "win32" and "clam" in style.theme_names():
            style.theme_use("clam")
            # clam draws radio buttons at a fixed 10px, tiny on HiDPI screens.
            line_height = tkfont.nametofont("TkDefaultFont").metrics("linespace")
            style.configure("TRadiobutton", indicatorsize=max(10, line_height // 2))
        self.heading_font = tkfont.nametofont("TkDefaultFont").copy()
        size = self.heading_font.cget("size")  # negative means pixels
        self.heading_font.configure(size=size + 4 if size > 0 else size - 5, weight="bold")
        # Paragraphs are at least 60 characters wide, wider if the command or
        # the entries table make the window wider.
        self.min_wrap = tkfont.nametofont("TkDefaultFont").measure("0") * 60
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
        except SwitcherError as error:
            self._show_problem(str(error))
        except Exception as error:  # the .exe has no console, so show everything
            self._show_problem(f"Unexpected error: {error!r}")
        else:
            self._show_target(candidates)

    def _show_problem(self, message):
        self._heading("Can't switch")
        self._paragraph(message)
        buttons = ttk.Frame(self.frame)
        buttons.pack(fill="x", pady=(16, 0))
        ttk.Button(buttons, text="Close", command=self.root.destroy).pack(side="right")
        if self.entries:
            self._add_entries_section()

    def _show_target(self, candidates):
        self._heading(f"Restart into {self.os_name}")
        if len(candidates) == 1:
            self._paragraph(f"Boot entry: {self.target.label} ({self.target.id})\n"
                            f"{self.target.path}")
        else:
            self._paragraph(f"Several {self.os_name} boot entries were found. "
                            "Choose one; your choice is remembered.")
            self.choice = tk.StringVar(value=self.target.id if self.target else "")
            for entry in candidates:
                ttk.Radiobutton(self.frame, text=f"{entry.label}    {entry.path}",
                                value=entry.id, variable=self.choice,
                                command=lambda entry=entry: self._choose(entry),
                                ).pack(anchor="w", padx=(12, 0))

        ttk.Label(self.frame, text="Command that will run:").pack(anchor="w", pady=(12, 4))
        self.command_box = self._text_box(self.frame)
        self._paragraph(f"This is a one-time boot override: only the next restart goes to "
                        f"{self.os_name}, and your normal boot order stays the same.")

        buttons = ttk.Frame(self.frame)
        buttons.pack(fill="x", pady=(16, 0))
        self.restart_button = ttk.Button(buttons, text=f"Restart into {self.os_name}",
                                         command=self._confirm_and_switch)
        self.restart_button.pack(side="right")
        ttk.Button(buttons, text="Close", command=self.root.destroy).pack(side="right", padx=(0, 8))
        self.status = tk.StringVar()
        ttk.Label(buttons, textvariable=self.status).pack(side="left")

        self._add_entries_section()
        self._update_command()

    def _add_entries_section(self):
        details = ttk.Frame(self.frame)
        self._set_text(self._text_box(details), format_table(self.entries))
        copy = ttk.Button(details, text="Copy", command=lambda: self._copy(copy))
        copy.pack(anchor="e", pady=(4, 0))

        def toggle():
            if details.winfo_manager():
                details.pack_forget()
                show.configure(text="Show all boot entries")
            else:
                details.pack(fill="x", pady=(8, 0))
                show.configure(text="Hide boot entries")

        show = ttk.Button(self.frame, text="Show all boot entries", command=toggle)
        show.pack(anchor="w", pady=(16, 0))

    def _heading(self, text):
        ttk.Label(self.frame, text=text, font=self.heading_font).pack(anchor="w", pady=(0, 8))

    def _paragraph(self, text):
        label = ttk.Label(self.frame, text=text, wraplength=self.min_wrap, justify="left")
        label.pack(anchor="w", pady=(0, 4))
        self.paragraphs.append(label)

    def _rewrap(self, event):
        for label in self.paragraphs:
            label.configure(wraplength=max(event.width - 32, self.min_wrap))

    @staticmethod
    def _text_box(parent):
        box = tk.Text(parent, font="TkFixedFont", wrap="none", relief="solid",
                      borderwidth=1, padx=6, pady=4, height=1, width=40)
        box.pack(fill="x", pady=(0, 8))
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
            pass  # only a convenience: the picker shows again next time
        self._update_command()

    def _update_command(self):
        if self.target:
            self._set_text(self.command_box, "\n".join(self.backend.describe(self.target)))
            self.restart_button.state(["!disabled"])
        else:
            self._set_text(self.command_box, "(choose a boot entry above)")
            self.restart_button.state(["disabled"])

    def _copy(self, button):
        report = (f"Dual Boot Switcher {__version__} on {OS_NAMES[self.backend.current_os]}\n\n"
                  + format_table(self.entries))
        self.root.clipboard_clear()
        self.root.clipboard_append(report)
        button.configure(text="Copied")

    def _confirm_and_switch(self):
        # The commands are already on show in the window, so the dialog stays short.
        if not messagebox.askokcancel(
                TITLE, f"Restart into {self.os_name} now?",
                detail=f"The computer restarts into {self.target.label} right away. "
                       "Open programs will be closed, so save your work first.",
                icon="warning", default="cancel", parent=self.root):
            return
        if self.dry_run:
            messagebox.showinfo(TITLE, "Dry run: nothing was changed.",
                                detail="Without --dry-run, the command shown in the window "
                                       "would have run and the computer would have restarted.",
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
