r"""Work out which UEFI boot entries belong to which OS, and pick the target.

Each entry gets one kind. The rules are checked in order and the first
match wins:

1. The label names a firmware tool (Setup, Boot Menu,
   Diagnostics, Recovery, secure wipe, ...)               -> FIRMWARE
2. The label names a device (USB CD, PXE BOOT, NVMe0, ...) -> DEVICE
3. The entry has no EFI file path                         -> OTHER
4. The path is \EFI\Microsoft\Boot\bootmgfw.efi           -> WINDOWS
5. The path is \EFI\<folder>\...\<file>.efi, and <file> is a Linux boot
   loader (shim, GRUB, systemd-boot) or <folder> or the label is a known
   distro name                                            -> LINUX
6. Anything else                                          -> OTHER

Only WINDOWS and LINUX entries are ever offered as targets. The path is what
counts most: LMDE registers itself as "debian", not "LMDE", and firmware
tools like "ThinkShield secure wipe" have no EFI file path at all.
"""

from __future__ import annotations

import re

from .model import BootEntry, EntryNotFoundError

# Entry kinds. WINDOWS and LINUX also name the OS we're running on.
WINDOWS = "windows"
LINUX = "linux"
DEVICE = "device"
FIRMWARE = "firmware"
OTHER = "other"

_FIRMWARE_TOOL = re.compile(
    r"\b(setup|boot menu|boot option|diagnos\w*|recovery|rescue|wipe|"
    r"interrupt menu|regulatory|shell|memory test|bios|firmware|app menu)\b",
    re.IGNORECASE,
)
_DEVICE = re.compile(
    r"\b(usb\w*|pxe\w*|nvme\d*|s?ata|hdd\d*|ssd\d*|cd|dvd|fdd|ipv[46]|"
    r"network|lan|nic|emmc|removable|hard (drive|disk))\b",
    re.IGNORECASE,
)
_LINUX_LOADER = re.compile(r"^(shim|grub|systemd-boot)(x64|ia32|aa64|arm|riscv64)?\.efi$")
# MokManager and the shim fallback live next to shim but aren't boot loaders.
_SHIM_HELPER = re.compile(r"^(mm|fb)(x64|ia32|aa64|arm|riscv64)?\.efi$")
_LINUX_NAMES = [
    "almalinux", "arch", "centos", "debian", "elementary", "endeavouros",
    "fedora", "gentoo", "kali", "linux", "linuxmint", "lmde", "manjaro",
    "mint", "neon", "nixos", "opensuse", "pop", "redhat", "rocky", "sles",
    "systemd", "ubuntu", "void", "zorin",
]
_LINUX_NAME_IN_LABEL = re.compile(r"\b(" + "|".join(_LINUX_NAMES) + r")\b", re.IGNORECASE)


def classify(entry: BootEntry) -> str:
    """Return the kind of a boot entry: WINDOWS, LINUX, DEVICE, FIRMWARE or OTHER."""
    if _FIRMWARE_TOOL.search(entry.label):
        return FIRMWARE
    if _DEVICE.search(entry.label):
        return DEVICE
    if not entry.path:
        return OTHER
    parts = entry.path.replace("/", "\\").strip("\\").lower().split("\\")
    if parts == ["efi", "microsoft", "boot", "bootmgfw.efi"]:
        return WINDOWS
    if len(parts) < 3 or parts[0] != "efi":
        return OTHER
    folder, filename = parts[1], parts[-1]
    # \EFI\BOOT\ holds the removable-media fallback loader, not an OS.
    if folder in ("microsoft", "boot") or _SHIM_HELPER.match(filename):
        return OTHER
    if (_LINUX_LOADER.match(filename) or folder in _LINUX_NAMES
            or _LINUX_NAME_IN_LABEL.search(entry.label)):
        return LINUX
    return OTHER


def target_kind(current_os: str) -> str:
    """The kind of entry to switch to when running on current_os."""
    return WINDOWS if current_os == LINUX else LINUX


def find_candidates(entries: list[BootEntry], current_os: str) -> list[BootEntry]:
    """Active entries for the other OS, in the order they were listed."""
    kind = target_kind(current_os)
    return [e for e in entries if e.active and classify(e) == kind]


def pick_target(entries: list[BootEntry], current_os: str,
                cached_id: str | None = None,
                cached_label: str | None = None) -> tuple[BootEntry | None, list[BootEntry]]:
    """Choose the entry to boot next. Returns (target, candidates).

    With one candidate, that's the target. With several, the cached choice
    is used if it's still there; otherwise target is None and the caller
    should ask the user, then cache the answer. A cached choice only counts
    if both its id and its label still match, because firmware updates can
    renumber entries.
    """
    candidates = find_candidates(entries, current_os)
    if not candidates:
        raise EntryNotFoundError(_not_found_message(current_os))
    if len(candidates) == 1:
        return candidates[0], candidates
    for entry in candidates:
        if cached_id and entry.id.lower() == cached_id.lower() and entry.label == cached_label:
            return entry, candidates
    return None, candidates


def _not_found_message(current_os: str) -> str:
    if current_os == LINUX:
        return ("No Windows Boot Manager entry was found among the UEFI boot entries "
                r"(looked for \EFI\Microsoft\Boot\bootmgfw.efi). "
                "Is Windows installed in UEFI mode on this machine?")
    return ("No Linux entry was found among the UEFI boot entries "
            r"(looked for \EFI\<name>\shimx64.efi, grubx64.efi or systemd-boot). "
            "Is Linux installed in UEFI mode on this machine?")
