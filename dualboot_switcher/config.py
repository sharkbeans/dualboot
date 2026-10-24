r"""Remember which entry the user picked when there was more than one candidate.

Stored as {"target_id": "0004", "target_label": "Fedora"} in
~/.config/dualboot-switcher/config.json on Linux and
%APPDATA%\dualboot-switcher\config.json on Windows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import BootEntry


def default_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or Path.home()
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "dualboot-switcher" / "config.json"


def load_choice(path: Path | None = None) -> tuple[str | None, str | None]:
    """Return (target_id, target_label), or (None, None) if nothing usable is saved."""
    try:
        data = json.loads((path or default_path()).read_text(encoding="utf-8"))
        return data.get("target_id"), data.get("target_label")
    except (OSError, ValueError, AttributeError):
        return None, None


def save_choice(entry: BootEntry, path: Path | None = None) -> None:
    """Save the choice. Raises OSError if the file can't be written."""
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"target_id": entry.id, "target_label": entry.label}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
