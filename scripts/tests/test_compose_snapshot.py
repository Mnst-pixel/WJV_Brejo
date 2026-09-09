"""Temporary-file tests; no host, Docker or network access."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

TARGET = Path(__file__).resolve().parents[1] / "hash-compose-configs.py"
SPEC = importlib.util.spec_from_file_location("compose_hashes", TARGET)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ComposeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kairos-compose-hashes-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "old override.yaml"
        self.new = self.root / "new.yaml"
        self.old.write_text("old")
        self.new.write_text("new")
        self.identities = self.root / "identities.txt"
        self.active(self.old)
        self.baseline = self.root / "hashes.txt"
        self.baseline.write_text(MODULE.capture(self.identities))

    def active(self, path):
        self.identities.write_text("id|/kairos-api|running|time|0|kairos|api|hash|" + str(path) + "\n")

    def test_retired_override_is_rehashed(self):
        self.active(self.new)
        captured = MODULE.capture(self.identities, self.baseline)
        self.assertIn(self.baseline.read_text().strip(), captured.splitlines())
        self.assertEqual(len(captured.splitlines()), 2)

    def test_retired_change_cannot_reuse_old_hash(self):
        self.active(self.new)
        self.old.write_text("tampered")
        self.assertNotIn(self.baseline.read_text().strip(), MODULE.capture(self.identities, self.baseline).splitlines())

    def test_deleted_retired_file_fails(self):
        self.active(self.new)
        self.old.unlink()
        with self.assertRaises(FileNotFoundError):
            MODULE.capture(self.identities, self.baseline)

    def test_missing_active_file_fails(self):
        self.old.unlink()
        with self.assertRaises(FileNotFoundError):
            MODULE.capture(self.identities)

    def test_malformed_baseline_fails(self):
        self.baseline.write_text("not a hash\n")
        with self.assertRaises(ValueError):
            MODULE.capture(self.identities, self.baseline)

    def test_malformed_identity_fails(self):
        self.identities.write_text("incomplete")
        with self.assertRaises(ValueError):
            MODULE.capture(self.identities)


if __name__ == "__main__":
    unittest.main()
