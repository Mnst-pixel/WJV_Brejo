"""Run with python -m unittest discover -s scripts/tests (Bash required)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "compare-vps-snapshots.sh"
FILES = (
    "containers.txt", "container-identities.txt", "networks.txt", "volumes.txt",
    "images.txt", "listeners.txt", "services-running.txt", "nginx-config-hashes.txt",
    "compose-config-hashes.txt", "cron-hashes.txt", "public-certificate-hashes.txt",
    "iptables.txt", "ip6tables.txt", "nft-ruleset.txt",
)


class NoTouchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kairos-no-touch-")
        self.addCleanup(self.temp.cleanup)
        self.before = Path(self.temp.name) / "before"
        self.after = Path(self.temp.name) / "after"
        for folder in (self.before, self.after):
            folder.mkdir()
            for name in FILES:
                (folder / name).write_text("", encoding="utf-8")
            for name in FILES[:3]:
                (folder / name).write_text("id1|kairos-api-1|stable\nid2|other-app|stable\n", encoding="utf-8")

    def compare(self):
        result = subprocess.run(
            [os.environ.get("KAIROS_TEST_BASH", "bash"), str(SCRIPT),
             self.before.as_posix(), self.after.as_posix()],
            capture_output=True, text=True, check=False,
        )
        self.assertNotIn(result.returncode, (126, 127), result.stderr)
        return result.returncode

    def test_existing_kairos_baseline_passes(self):
        self.assertEqual(self.compare(), 0)

    def test_kairos_replacement_is_separate_from_no_touch(self):
        (self.after / "containers.txt").write_text("new|kairos-api-1|changed\nid2|other-app|stable\n")
        self.assertEqual(self.compare(), 0)

    def test_unrelated_identity_change_fails(self):
        (self.after / "container-identities.txt").write_text("new|kairos-api-1|changed\nnew2|other-app|stable\n")
        self.assertNotEqual(self.compare(), 0)

    def test_kairos_in_image_does_not_hide_unrelated_container(self):
        (self.before / "containers.txt").write_text("id|other-app|kairos-custom-image\n")
        (self.after / "containers.txt").write_text("new|other-app|kairos-custom-image\n")
        self.assertNotEqual(self.compare(), 0)

    def test_missing_inventory_fails(self):
        (self.after / "networks.txt").unlink()
        self.assertNotEqual(self.compare(), 0)

    def test_configuration_change_fails(self):
        (self.before / "nginx-config-hashes.txt").write_text("old /etc/nginx/site.conf\n")
        (self.after / "nginx-config-hashes.txt").write_text("new /etc/nginx/site.conf\n")
        self.assertNotEqual(self.compare(), 0)

    def test_missing_configuration_in_both_snapshots_fails(self):
        for folder in (self.before, self.after):
            (folder / "nginx-config-hashes.txt").unlink()
        self.assertNotEqual(self.compare(), 0)


if __name__ == "__main__":
    unittest.main()
