"""Linux: read entries with efibootmgr, switch through a root-owned helper.

The app itself never runs as root. Switching runs

    pkexec /usr/libexec/dualboot-switcher/dualboot-switcher-helper <BOOTNUM>

and polkit asks for the user's password. The helper is installed by the .deb
and owned by root. It checks the boot number again, sets BootNext (a one-time
override, BootOrder is never touched) and reboots.
"""

from __future__ import annotations

import os
import platform
import shlex
import subprocess
from pathlib import Path

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

    def __init__(self, run=subprocess.run, root="/", helper=HELPER):
        self._run = run
        self._root = Path(root)  # tests point this at a fake /sys and /dev
        self._helper = helper

    def list_entries(self) -> list[BootEntry]:
        if not (self._root / "sys/firmware/efi").is_dir():
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

    def disk_label(self, entry: BootEntry) -> str | None:
        """The disk an entry boots from, e.g. "SKHynix HFS512GD9TNI-L2B0B, 512 GB".

        Found by following the entry's partition GUID through
        /dev/disk/by-partuuid and /sys/class/block; no root needed.
        """
        if not entry.partition_guid:
            return None
        try:
            link = self._root / "dev/disk/by-partuuid" / entry.partition_guid
            partition = link.resolve(strict=True).name  # e.g. nvme0n1p2
            disk = (self._root / "sys/class/block" / partition).resolve(strict=True).parent
        except OSError:
            return "disk not found (probably left over from an old install)"
        model = _read(disk / "device/model").replace("_", " ")
        sectors = _read(disk / "size")
        size = _format_size(int(sectors) * 512) if sectors.isdigit() else ""
        return ", ".join(part for part in (model or disk.name, size) if part)

    def system_info(self) -> str:
        """E.g. "LMDE 7 (gigi), kernel 6.12.48+deb13-amd64, UEFI"."""
        try:
            name = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        except OSError:
            name = "Linux"
        firmware = "UEFI" if (self._root / "sys/firmware/efi").is_dir() else "legacy BIOS"
        return f"{name}, kernel {platform.release()}, {firmware}"

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


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _format_size(size: int) -> str:
    # Decimal units, like the size printed on the drive.
    if size >= 1e12:
        return f"{size / 1e12:.1f} TB"
    return f"{size / 1e9:.0f} GB"
