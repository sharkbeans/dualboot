"""Command line: `dualboot-switcher list` and `dualboot-switcher switch`.

Running `dualboot-switcher` with no command opens the window instead (see
__main__.py). The Windows .exe only has the window, since a windowed .exe
has no console to print to.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, config
from .backend import get_backend
from .classify import OS_NAMES, classify, pick_target, target_kind
from .model import BootEntry, EntryNotFoundError, SwitcherError


def main(argv=None, backend=None, config_path=None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args, backend or get_backend(), config_path)
    except SwitcherError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dualboot-switcher",
        description="Reboot a UEFI dual-boot machine straight into the other OS, "
                    "using a one-time boot override.",
        epilog="Run without a command to open the window; add --dry-run to try it "
               "without changing anything.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    list_command = commands.add_parser("list", help="show the boot entries and the target")
    list_command.set_defaults(run=_list)

    switch = commands.add_parser("switch", help="set a one-time boot into the other OS and reboot")
    switch.add_argument("--dry-run", action="store_true",
                        help="print the commands without running them")
    switch.add_argument("--target", metavar="ID",
                        help="entry to switch to when there are several (remembered)")
    switch.add_argument("--yes", "-y", action="store_true", help="don't ask for confirmation")
    switch.set_defaults(run=_switch)
    return parser


def _list(args, backend, config_path) -> int:
    entries = backend.list_entries()
    print(format_table(entries))
    print()
    target, candidates = pick_target(entries, backend.current_os, *config.load_choice(config_path))
    if target is None:
        print("Several possible targets. Pick one with: dualboot-switcher switch --target ID")
        for entry in candidates:
            print(f"  {entry.id}  {entry.label}")
        return 0
    remembered = " (remembered choice)" if len(candidates) > 1 else ""
    print(f"Target: {target.id} {target.label}{remembered}")
    print("Switching would run:")
    for line in backend.describe(target):
        print(f"  {line}")
    return 0


def _switch(args, backend, config_path) -> int:
    entries = backend.list_entries()
    target, candidates = pick_target(entries, backend.current_os, *config.load_choice(config_path))
    if args.target:
        target = _find(candidates, args.target)
        if len(candidates) > 1:
            _remember(target, config_path)
    if target is None:
        raise SwitcherError(
            "Several possible targets: "
            + ", ".join(f"{entry.id} ({entry.label})" for entry in candidates)
            + ".\nPick one with --target ID; the choice is remembered.")

    print(f"Target: {target.id} {target.label}")
    if args.dry_run:
        print("Dry run, nothing was changed. Switching would run:")
        for line in backend.describe(target):
            print(f"  {line}")
        return 0

    print("This will run:")
    for line in backend.describe(target):
        print(f"  {line}")
    os_name = OS_NAMES[target_kind(backend.current_os)]
    question = (f"Restart into {os_name} now? Open programs will be closed, "
                "so save your work first. [y/N] ")
    if not args.yes and not _confirm(question):
        print("Cancelled, nothing was changed.")
        return 1
    backend.switch(target)
    return 0


def format_table(entries: list[BootEntry]) -> str:
    """All boot entries as a text table. The GUI shows this too."""
    id_width = max([len(entry.id) for entry in entries] + [2])
    label_width = max([len(entry.label) for entry in entries] + [5])
    lines = [f"{'ID':<{id_width}}  ACTIVE  {'KIND':<8}  {'LABEL':<{label_width}}  PATH"]
    for entry in entries:
        active = "yes" if entry.active else "no"
        lines.append(f"{entry.id:<{id_width}}  {active:<6}  {classify(entry):<8}  "
                     f"{entry.label:<{label_width}}  {entry.path or '-'}")
    return "\n".join(lines)


def _find(candidates: list[BootEntry], wanted: str) -> BootEntry:
    # Accept Windows GUIDs with or without their braces.
    for entry in candidates:
        if entry.id.strip("{}").lower() == wanted.strip("{}").lower():
            return entry
    raise EntryNotFoundError(
        f"{wanted} is not a possible target. Possible targets: "
        + ", ".join(f"{entry.id} ({entry.label})" for entry in candidates))


def _remember(entry: BootEntry, config_path) -> None:
    try:
        config.save_choice(entry, config_path)
    except OSError as error:
        print(f"Warning: could not remember this choice: {error}", file=sys.stderr)


def _confirm(question: str) -> bool:
    try:
        return input(question).strip().lower() in ("y", "yes")
    except EOFError:
        return False
