import tempfile
import unittest
from pathlib import Path

from dualboot_switcher import config
from dualboot_switcher.model import BootEntry


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        config.save_choice(BootEntry(id="0004", label="Fedora"), self.path)
        self.assertEqual(config.load_choice(self.path), ("0004", "Fedora"))

    def test_missing_file(self):
        self.assertEqual(config.load_choice(self.path), (None, None))

    def test_corrupt_file(self):
        self.path.parent.mkdir()
        for content in ["{not json", "[1, 2]"]:
            with self.subTest(content=content):
                self.path.write_text(content)
                self.assertEqual(config.load_choice(self.path), (None, None))


if __name__ == "__main__":
    unittest.main()
