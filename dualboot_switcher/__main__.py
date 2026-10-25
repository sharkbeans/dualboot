"""`python -m dualboot_switcher`, and the installed `dualboot-switcher` command.

With a command (list, switch) it's the CLI. Otherwise it opens the window,
e.g. `dualboot-switcher` or `dualboot-switcher --dry-run`.
"""

import sys

CLI_ARGS = {"list", "switch", "-h", "--help", "--version"}


def main() -> int:
    args = sys.argv[1:]
    # Imported lazily so the CLI works even where tkinter isn't installed.
    if args and args[0] in CLI_ARGS:
        from .cli import main as cli_main
        return cli_main(args)
    from .gui import main as gui_main
    return gui_main(args)


if __name__ == "__main__":
    sys.exit(main())
