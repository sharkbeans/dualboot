"""Pick the backend for the OS we're running on.

Both backends have the same methods:

    current_os               classify.LINUX or classify.WINDOWS
    list_entries()           -> [BootEntry]; raises SwitcherError subclasses
    commands(entry)          -> the commands switch() runs, as argv lists
    describe(entry)          -> those commands as text, to show the user
    disk_label(entry)        -> which disk the entry is on, or None if unknown
    system_info()            -> OS version and firmware mode, for bug reports
    switch(entry)            sets the one-time boot and reboots
"""

from __future__ import annotations

import sys

from .model import SwitcherError


def get_backend():
    if sys.platform == "win32":
        from .backend_windows import WindowsBackend
        return WindowsBackend()
    if sys.platform.startswith("linux"):
        from .backend_linux import LinuxBackend
        return LinuxBackend()
    raise SwitcherError("Dual Boot Switcher only runs on Linux and Windows.")


def command_output(result) -> str:
    """The most useful text from a finished subprocess, for error messages."""
    text = (result.stderr or "").strip() or (result.stdout or "").strip()
    return text or f"(exit code {result.returncode}, no output)"
