import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import os
import io
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_secrets", ROOT / "scripts/release-secrets.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ServiceSecretTests(unittest.TestCase):
    def test_projection_never_passes_unlisted_credentials(self):
        mapping = json.loads((ROOT / "config/service-secrets.json").read_text())
        values = {
            key: "synthetic-value"
            for service in mapping.values()
            for key in service.values()
        }
        values.update(
            {
                "WORDPRESS_ADMIN_PASSWORD": "must-not-leak",
                "BACKUP_ENCRYPTION_PASSPHRASE": "must-not-leak",
            }
        )
        result = MODULE.project(values, mapping)
        self.assertEqual(set(result["localai"]), {"LOCALAI_API_KEY"})
        for service in ("api", "worker", "localai"):
            self.assertNotIn("must-not-leak", result[service].values())
        self.assertNotIn("MFA_ENCRYPTION_KEY", result["worker"])
        self.assertNotIn("LOCALAI_API_KEY", result["worker"])

    def test_missing_required_fails_closed(self):
        with self.assertRaises(ValueError):
            MODULE.project({}, {"api": {"KEY": "MISSING"}})

    def test_service_and_variable_injection_refused(self):
        for mapping in (
            {"../outside": {"KEY": "KEY"}},
            {"recovery": {"KEY": "KEY"}},
            {"api": {"KEY\nOTHER": "KEY"}},
            {"api": {"KEY": "KEY\nOTHER"}},
        ):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                MODULE.project({"KEY": "synthetic"}, mapping)

    def test_dotenv_is_not_evaluated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env"
            path.write_text("KEY=$(touch /tmp/not-executed)\n")
            self.assertEqual(MODULE.read_env(path)["KEY"], "$(touch /tmp/not-executed)")

    def test_duplicate_or_malformed_env_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "env"
            for text in ("KEY=one\nKEY=two\n", "export KEY=value\n", "KEY\n"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    MODULE.read_env(path)


@unittest.skipUnless(
    os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0,
    "real root/Linux secret-mode fixture required",
)
class SecretPreparationFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="kairos-secrets-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.master = self.root / "master.env"
        self.master.write_text("SMTP_URL=\n")
        self.master.chmod(0o600)
        self.spec = self.root / "mapping.json"
        self.spec.write_text(
            json.dumps(
                {
                    "api": {"KAIROS_PROXY_TOKEN": "KAIROS_PROXY_TOKEN"},
                    "edge": {"KAIROS_PROXY_TOKEN": "KAIROS_PROXY_TOKEN"},
                }
            )
        )
        self.destination = self.root / "release"
        patcher = patch.object(MODULE, "SECRET_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prepare_generates_protected_values_without_printing_them(self):
        output = io.StringIO()
        with redirect_stdout(output):
            MODULE.prepare(self.master, self.destination, self.spec)
        api = MODULE.read_env(self.destination / "api.env")
        edge = MODULE.read_env(self.destination / "edge.env")
        self.assertEqual(api, edge)
        self.assertRegex(api["KAIROS_PROXY_TOKEN"], r"^[a-f0-9]{96}$")
        self.assertNotIn(api["KAIROS_PROXY_TOKEN"], output.getvalue())
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        for path in self.destination.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            MODULE.prepare(self.master, self.destination, self.spec)

    def test_master_symlink_and_broad_permissions_rejected(self):
        alias = self.root / "alias.env"
        alias.symlink_to(self.master)
        with self.assertRaises(ValueError):
            MODULE.prepare(alias, self.destination, self.spec)
        self.master.chmod(0o644)
        with self.assertRaises(ValueError):
            MODULE.prepare(self.master, self.destination, self.spec)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
