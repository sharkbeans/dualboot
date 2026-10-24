r"""Parse `bcdedit /enum firmware` output into BootEntry objects.

The output is a series of blocks separated by blank lines:

    Firmware Application (101fffff)
    -------------------------------
    identifier              {00000000-...-000000000001}
    device                  partition=\Device\HarddiskVolume1
    path                    \EFI\debian\shimx64.efi
    description             debian

Windows translates parts of this output: block titles always, and in some
languages key names too (German shows "Bezeichner" for "identifier"). So the
parser relies on structure and on the shape of values wherever it can:

- the identifier is the first line of a block and looks like {...}
- the path is whichever value looks like \EFI\...\something.efi
- the description is the only thing looked up by key name, using the list
  below; if it isn't found the label is left empty and classification still
  works from the path
"""

from __future__ import annotations

import re

from .model import BootEntry

# "description" in the languages we know of. If a bug report shows another
# translation, add it here.
_DESCRIPTION_KEYS = {
    "description",   # English, French
    "beschreibung",  # German
    "descripción",   # Spanish
    "descrizione",   # Italian
    "descrição",     # Portuguese
    "beschrijving",  # Dutch
    "opis",          # Polish
    "popis",         # Czech, Slovak
    "beskrivning",   # Swedish
    "beskrivelse",   # Danish, Norwegian
    "kuvaus",        # Finnish
    "leírás",        # Hungarian
    "açıklama",      # Turkish
    "описание",      # Russian
    "опис",          # Ukrainian
}

_IDENTIFIER = re.compile(r"(\{[^{}\s]+\})\s*$")
_EFI_PATH = re.compile(r"(\\EFI\\.*\.efi)\s*$", re.IGNORECASE)
_KEY_VALUE = re.compile(r"^(\S+)\s+(.*\S)\s*$")


def parse(text: str) -> list[BootEntry]:
    entries = []
    for block in _blocks(text):
        # block[0] is the (translated) title, block[1] the dashes under it.
        # Anything else, like an "Access is denied." message, is skipped.
        if len(block) < 3 or set(block[1].strip()) != {"-"}:
            continue
        # Indented lines continue a multi-value element such as displayorder.
        lines = [line for line in block[2:] if not line[:1].isspace()]
        identifier = _IDENTIFIER.search(lines[0]) if lines else None
        # {fwbootmgr} is the firmware boot manager itself, not a boot entry.
        if not identifier or identifier.group(1).lower() == "{fwbootmgr}":
            continue
        entries.append(BootEntry(
            id=identifier.group(1),
            label=_description(lines),
            path=_path(lines),
        ))
    return entries


def _blocks(text: str):
    block = []
    for line in text.splitlines():
        if line.strip():
            block.append(line)
        elif block:
            yield block
            block = []
    if block:
        yield block


def _description(lines: list[str]) -> str:
    for line in lines:
        match = _KEY_VALUE.match(line)
        if match and match.group(1).lower() in _DESCRIPTION_KEYS:
            return match.group(2)
    return ""


def _path(lines: list[str]) -> str | None:
    for line in lines:
        match = _EFI_PATH.search(line)
        if match:
            return match.group(1)
    return None
