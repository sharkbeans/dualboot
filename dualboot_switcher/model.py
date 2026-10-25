"""Data types shared by the parsers, the classifier and the front ends."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BootEntry:
    r"""One UEFI boot entry, as reported by efibootmgr or bcdedit.

    id:     what the OS tool uses to address the entry: "0001" for
            efibootmgr, "{00000000-...-000000000001}" or "{bootmgr}" for bcdedit.
    label:  the entry's description, e.g. "debian" or "Windows Boot Manager".
    path:   the EFI file it boots, e.g. "\EFI\debian\shimx64.efi", or None
            for firmware-provided entries (USB CD, PXE BOOT, Setup, ...).
    active: efibootmgr's "*" flag. None when unknown: bcdedit doesn't show
            it, so entries parsed on Windows have None.
    partition_guid: the GPT partition holding path, from efibootmgr's
            HD(...) node; used to show which disk the entry is on. None on
            Windows, where bcdedit doesn't show it.
    """

    id: str
    label: str
    path: str | None = None
    active: bool | None = None
    partition_guid: str | None = None


class SwitcherError(Exception):
    """An error whose message is meant to be shown to the user as-is."""


class EntryNotFoundError(SwitcherError):
    """No boot entry for the other OS was found."""


class NotUefiError(SwitcherError):
    """The machine booted in legacy BIOS mode, so there are no UEFI entries."""


class NotAdminError(SwitcherError):
    """Windows only: bcdedit needs administrator rights."""
