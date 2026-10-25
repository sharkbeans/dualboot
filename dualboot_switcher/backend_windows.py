r"""Windows: read entries with bcdedit, set a one-time boot and restart.

Switching runs, as administrator:

    C:\Windows\System32\bcdedit.exe /set {fwbootmgr} bootsequence {GUID}
    C:\Windows\System32\shutdown.exe /r /t 0

bootsequence is Windows' name for UEFI BootNext: it applies to the next boot
only and leaves the boot order alone.

Both programs are called by full path. Windows looks for programs in the
running .exe's own folder first, so a bare "bcdedit" could pick up a planted
bcdedit.exe sitting next to DualBootSwitcher.exe in Downloads, and run it as
administrator.
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import platform
import subprocess

from .backend import command_output
from .classify import WINDOWS
from .model import BootEntry, NotAdminError, NotUefiError, SwitcherError
from .parse_bcdedit import parse

_SYSTEM32 = ntpath.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
BCDEDIT = ntpath.join(_SYSTEM32, "bcdedit.exe")
SHUTDOWN = ntpath.join(_SYSTEM32, "shutdown.exe")

_FIRMWARE_TYPE_BIOS = 1
# Stops each bcdedit call from flashing a console window in the GUI .exe.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class WindowsBackend:
    current_os = WINDOWS

    def __init__(self, run=subprocess.run, firmware_type=None, is_admin=None):
        self._run = run
        self._firmware_type = firmware_type or _firmware_type
        self._is_admin = is_admin or _is_admin

    def list_entries(self) -> list[BootEntry]:
        if self._firmware_type() == _FIRMWARE_TYPE_BIOS:
            raise NotUefiError("This PC booted in legacy BIOS mode. "
                               "Dual Boot Switcher only works on UEFI systems.")
        if not self._is_admin():
            raise NotAdminError("Dual Boot Switcher needs administrator rights to read "
                                "the boot entries. Run it as administrator.")
        result = self._call([BCDEDIT, "/enum", "firmware"])
        if result.returncode != 0:
            raise SwitcherError("bcdedit could not list the firmware boot entries:\n"
                                + command_output(result))
        entries = parse(result.stdout)
        if not entries:
            raise NotUefiError("bcdedit listed no firmware boot entries. This usually means "
                               "the PC booted in legacy BIOS mode; Dual Boot Switcher only "
                               "works on UEFI systems.")
        return entries

    def commands(self, entry: BootEntry) -> list[list[str]]:
        return [
            [BCDEDIT, "/set", "{fwbootmgr}", "bootsequence", entry.id],
            [SHUTDOWN, "/r", "/t", "0"],
        ]

    def describe(self, entry: BootEntry) -> list[str]:
        return [subprocess.list2cmdline(argv) for argv in self.commands(entry)]

    def disk_label(self, entry: BootEntry) -> str | None:
        # bcdedit only shows "partition=\Device\HarddiskVolumeN" for an entry.
        # Turning that into a disk name takes several Windows API calls, so
        # it's left out until it can be checked against real bcdedit output.
        return None

    def system_info(self) -> str:
        """E.g. "Windows 10.0.22621, UEFI"."""
        firmware = {1: "legacy BIOS", 2: "UEFI"}.get(self._firmware_type(), "firmware unknown")
        return f"Windows {platform.version()}, {firmware}"

    def switch(self, entry: BootEntry) -> None:
        set_boot_next, restart = self.commands(entry)
        result = self._call(set_boot_next)
        if result.returncode != 0:
            raise SwitcherError("bcdedit could not set the one-time boot entry. "
                                "Nothing was changed.\n" + command_output(result))
        result = self._call(restart)
        if result.returncode != 0:
            raise SwitcherError(
                "The one-time boot entry was set, but Windows did not restart:\n"
                + command_output(result)
                + "\nRestart manually to boot into it, or undo it with:\n"
                "bcdedit /deletevalue {fwbootmgr} bootsequence")

    def _call(self, argv: list[str]):
        # bcdedit writes in the console's OEM code page, not UTF-8.
        return self._run(argv, capture_output=True, text=True, encoding="oem",
                         errors="replace", creationflags=_NO_WINDOW)


def _firmware_type() -> int:
    """1 = legacy BIOS, 2 = UEFI, 0 = unknown (then bcdedit decides)."""
    value = ctypes.c_uint(0)
    if not ctypes.windll.kernel32.GetFirmwareType(ctypes.byref(value)):
        return 0
    return value.value


def _is_admin() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())
