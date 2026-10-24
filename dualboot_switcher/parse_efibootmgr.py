r"""Parse `efibootmgr -v` output into BootEntry objects.

The lines that matter look like this (label and device path are separated
by a tab):

    Boot0001* debian	HD(2,GPT,...)/File(\EFI\debian\shimx64.efi)
    Boot0010  Setup	FvFile(721c8b66-...)

"*" means the entry is active. Everything else is skipped: the header lines
(BootCurrent, BootOrder, Timeout, BootNext) and the indented "dp:" / "data:"
hex dumps that efibootmgr 18 prints under each entry.
"""

from __future__ import annotations

import re

from .model import BootEntry

_ENTRY = re.compile(r"^Boot([0-9A-Fa-f]{4})(\*?)\s+(.*)$")
# (?<!\w) so that firmware volume nodes like FvFile(...) don't count.
_FILE = re.compile(r"(?<!\w)File\(([^)]*)\)")


def parse(text: str) -> list[BootEntry]:
    entries = []
    for line in text.splitlines():
        match = _ENTRY.match(line)
        if not match:
            continue
        number, star, rest = match.groups()
        label, _, device_path = rest.partition("\t")
        # Older efibootmgr versions append optional data right after the
        # device path, so search for File(...) instead of anchoring it.
        file_match = _FILE.search(device_path)
        entries.append(BootEntry(
            id=number.upper(),
            label=label.strip(),
            path=file_match.group(1) if file_match else None,
            active=star == "*",
        ))
    return entries
