"""Linux: read entries with efibootmgr, switch through a root-owned helper.

The app itself never runs as root. Switching runs

    pkexec /usr/libexec/dualboot-switcher/dualboot-switcher-helper <BOOTNUM>

and polkit asks for the user's password. The helper is installed by the .deb
and owned by root. It checks the boot number again, sets BootNext (a one-time
override, BootOrder is never touched) and reboots.
"""

from __future__ import annotations

import os
import shlex
import subprocess

from .backend import command_output
from .classify import LINUX
from .model import BootEntry, NotUefiError, SwitcherError
from .parse_efibootmgr import parse

HELPER = "/usr/libexec/dualboot-switcher/dualboot-switcher-helper"

# pkexec's exit codes when it didn't run the helper at all.
_PKEXEC_DISMISSED = 126
_PKEXEC_NOT_AUTHORIZED = 127


class LinuxBackend:
    current_os = LINUX

    def __init__(self, run=subprocess.run, efi_dir="/sys/firmware/efi", helper=HELPER):
        self._run = run
        self._efi_dir = efi_dir
        self._helper = helper

    def list_entries(self) -> list[BootEntry]:
        if not os.path.isdir(self._efi_dir):
            raise NotUefiError(
                "This machine booted in legacy BIOS mode (/sys/firmware/efi is missing). "
                "Dual Boot Switcher only works on UEFI systems.")
        result = self._call(["efibootmgr", "-v"])
        if result.returncode != 0:
            raise SwitcherError("efibootmgr could not read the boot entries:\n"
                                + command_output(result))
        return parse(result.stdout)

    def commands(self, entry: BootEntry) -> list[list[str]]:
        return [["pkexec", self._helper, entry.id]]

    def describe(self, entry: BootEntry) -> list[str]:
        return [shlex.join(argv) for argv in self.commands(entry)] + [
            f"  which runs, as root: efibootmgr --bootnext {entry.id} && systemctl reboot",
        ]

    def switch(self, entry: BootEntry) -> None:
        if not os.path.exists(self._helper):
            raise SwitcherError(
                f"The helper {self._helper} is not installed. "
                "Install the dualboot-switcher .deb package to switch.")
        result = self._call(self.commands(entry)[0])
        if result.returncode == _PKEXEC_DISMISSED:
            raise SwitcherError("Cancelled: the password dialog was closed. Nothing was changed.")
        if result.returncode == _PKEXEC_NOT_AUTHORIZED:
            raise SwitcherError("Authorization failed, nothing was changed:\n"
                                + command_output(result))
        if result.returncode != 0:
            raise SwitcherError("Switching failed:\n" + command_output(result))

    def _call(self, argv: list[str]):
        try:
            return self._run(argv, capture_output=True, text=True)
        except FileNotFoundError:
            raise SwitcherError(f"{argv[0]} is not installed.") from None
