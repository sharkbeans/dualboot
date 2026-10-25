"""PyInstaller entry point for DualBootSwitcher.exe, which only has the window."""

import sys

from dualboot_switcher.gui import main

sys.exit(main())
