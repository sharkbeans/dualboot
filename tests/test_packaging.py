"""Tests for the Linux packaging files, above all the root helper.

The helper tests run the real script, with efibootmgr and systemctl
replaced by fakes that only log how they were called.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from dualboot_switcher.backend_linux import HELPER

from . import FIXTURES

LINUX = Path(__file__).parent.parent / "packaging" / "linux"
REAL_PATH = "export PATH=/usr/sbin:/usr/bin:/sbin:/bin"


@unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "needs bash")
class HelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.log = tmp / "calls.log"
        self.efi_dir = tmp / "efi"
        self.efi_dir.mkdir()
        fake_bin = tmp / "bin"
        fake_bin.mkdir()
        fixture = FIXTURES / "efibootmgr-v_lenovo-lmde.txt"
        self.fake(fake_bin / "efibootmgr",
                  f'if [ "$1" = "-v" ]; then cat "{fixture}"; exit 0; fi\n'
                  f'echo "efibootmgr $*" >> "{self.log}"')
        self.fake(fake_bin / "systemctl", f'echo "systemctl $*" >> "{self.log}"')

        script = (LINUX / "dualboot-switcher-helper").read_text()
        self.assertEqual(script.count(REAL_PATH), 1)
        self.assertEqual(script.count("/sys/firmware/efi"), 1)
        script = script.replace(REAL_PATH, f"export PATH={fake_bin}:/usr/bin:/bin")
        script = script.replace("/sys/firmware/efi", str(self.efi_dir))
        self.helper = tmp / "helper"
        self.helper.write_text(script)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def fake(path, body):
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def run_helper(self, *args):
        result = subprocess.run(["bash", str(self.helper), *args], capture_output=True, text=True)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result.returncode, result.stderr, calls

    def test_sets_boot_next_and_reboots(self):
        code, _, calls = self.run_helper("0000")
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["efibootmgr --bootnext 0000", "systemctl reboot"])

    def test_lowercase_boot_number_is_uppercased(self):
        # 001A is "ATA HDD0", a device entry, so it's refused, by its uppercase name.
        code, stderr, calls = self.run_helper("001a")
        self.assertEqual((code, calls), (1, []))
        self.assertIn("Boot entry 001A", stderr)

    def test_rejects_malformed_arguments(self):
        for args in [(), ("",), ("1",), ("00000",), ("zzzz",), ("0000; reboot",),
                     ("--help",), ("../0000",)]:
            with self.subTest(args=args):
                code, _, calls = self.run_helper(*args)
                self.assertEqual(code, 2)
                self.assertEqual(calls, [])

    def test_entry_not_found(self):
        code, stderr, calls = self.run_helper("0099")
        self.assertEqual((code, calls), (1, []))
        self.assertIn("not found", stderr)

    def test_refuses_firmware_and_device_entries(self):
        # 0014 ThinkShield secure wipe, 0010 Setup, 001C PXE BOOT, 0017 USB CD
        for number in ["0014", "0010", "001C", "0017"]:
            with self.subTest(number=number):
                code, stderr, calls = self.run_helper(number)
                self.assertEqual((code, calls), (1, []))
                self.assertIn("refusing", stderr)

    def test_legacy_bios(self):
        self.efi_dir.rmdir()
        code, stderr, calls = self.run_helper("0000")
        self.assertEqual((code, calls), (1, []))
        self.assertIn("legacy BIOS", stderr)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        tree = ElementTree.parse(LINUX / "io.github.sharkbeans.dualboot.policy")
        self.action = tree.getroot().find("action")

    def test_action_runs_the_installed_helper(self):
        self.assertEqual(self.action.get("id"), "io.github.sharkbeans.dualboot.switch")
        annotation = self.action.find("annotate[@key='org.freedesktop.policykit.exec.path']")
        self.assertEqual(annotation.text, HELPER)

    def test_asks_for_admin_password(self):
        defaults = self.action.find("defaults")
        self.assertEqual(defaults.find("allow_active").text, "auth_admin_keep")
        self.assertEqual(defaults.find("allow_any").text, "auth_admin")
        self.assertEqual(defaults.find("allow_inactive").text, "auth_admin")


if __name__ == "__main__":
    unittest.main()
