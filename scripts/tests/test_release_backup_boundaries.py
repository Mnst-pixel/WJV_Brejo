import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load("backup_pg", "backup-postgres.py")
capture = load("capture_release", "capture-release-config.py")


class BackupGuardTests(unittest.TestCase):
    def test_foreign_container_is_rejected_before_dump(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "com.docker.compose.project": "foreign",
                        "com.docker.compose.service": "postgres",
                    }
                ),
            )

        with self.assertRaises(ValueError):
            backup.backup(io.BytesIO(), runner=runner)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][:3], backup.release.DOCKER)

    def test_missing_pointer_does_not_silently_use_superuser(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            service = "postgres" if command[-1] == "kairos-postgres-1" else "api"
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "com.docker.compose.project": "kairos",
                        "com.docker.compose.service": service,
                        "com.kairos.managed": "release",
                    }
                ),
            )

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(backup, "RUNTIME", Path(directory)),
        ):
            with self.assertRaises(ValueError):
                backup.backup(io.BytesIO(), runner=runner)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("exec" not in call for call in calls))


@unittest.skipUnless(
    os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0,
    "real root/Linux file-mode fixture required",
)
class ProtectedReleaseFilesystemTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="kairos-backup-boundary-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runtime = self.root / "runtime"
        self.descriptor = self.runtime / "releases" / "test"
        self.secret_root = self.root / "secrets"
        self.secrets = self.secret_root / "test"
        self.backups = self.root / "backups"
        self.payload = self.backups / "test" / "payload"
        for directory in (self.descriptor, self.secrets, self.payload):
            directory.mkdir(parents=True, mode=0o700)
        self.value = {
            "schema": 1,
            "commit": "a" * 40,
            "images": {"api": "sha256:" + "a" * 64},
            "secrets_dir": str(self.secrets),
        }
        self.write(self.runtime / "active-release", str(self.descriptor))
        self.write(self.descriptor / "manifest.json", json.dumps(self.value))
        self.write(
            self.descriptor / "release.env",
            "".join(
                f"{key}={value}\n"
                for key, value in sorted(
                    capture.release.public_environment(self.value).items()
                )
            ),
        )
        self.write(self.secrets / "recovery.env", "SYNTHETIC=value\n")
        self.write(self.secrets / "api.env", "SYNTHETIC=value\n")
        self.write(self.secrets / "redis.acl", "user default off\n")
        for module in (capture, backup):
            for name, value in (
                ("RUNTIME", self.runtime),
                ("SECRETS", self.secret_root),
            ):
                patcher = patch.object(module, name, value)
                patcher.start()
                self.addCleanup(patcher.stop)
        patcher = patch.object(capture, "BACKUPS", self.backups)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path, value):
        path.write_text(value)
        path.chmod(0o600)

    def test_capture_produces_private_copies_and_preserves_acl(self):
        capture.capture(self.payload)
        output = self.payload / "active-release"
        self.assertEqual((output.stat().st_mode & 0o777), 0o700)
        self.assertEqual((output / "redis.acl").read_text(), "user default off\n")
        for path in output.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            capture.capture(self.payload)

    def test_capture_rejects_unsafe_source_mode_before_copy(self):
        (self.secrets / "api.env").chmod(0o644)
        with self.assertRaises(ValueError):
            capture.capture(self.payload)
        self.assertFalse((self.payload / "active-release").exists())

    def test_capture_refuses_symlinked_source_and_destination(self):
        (self.secrets / "api.env").unlink()
        (self.secrets / "api.env").symlink_to(self.secrets / "recovery.env")
        with self.assertRaises(ValueError):
            capture.capture(self.payload)
        alias = self.backups / "payload"
        alias.symlink_to(self.payload, target_is_directory=True)
        with self.assertRaises(ValueError):
            capture.capture(alias)

    def test_capture_refuses_world_readable_payload_or_corrupted_env(self):
        self.payload.chmod(0o755)
        with self.assertRaises(ValueError):
            capture.capture(self.payload)
        self.payload.chmod(0o700)
        self.write(self.descriptor / "release.env", "DOCKER_HOST=foreign\n")
        with self.assertRaises(ValueError):
            capture.capture(self.payload)
        self.assertFalse((self.payload / "active-release").exists())

    def test_missing_acl_is_not_reported_as_recoverable_capture(self):
        (self.secrets / "redis.acl").unlink()
        with self.assertRaises(FileNotFoundError):
            capture.capture(self.payload)
        self.assertFalse((self.payload / "active-release").exists())

    def test_backup_credentials_only_flow_over_stdin_and_local_daemon(self):
        calls = []
        password = "synthetic-password-not-in-argv"

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if "inspect" in command:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "com.docker.compose.project": "kairos",
                            "com.docker.compose.service": "postgres",
                        }
                    ),
                )
            return SimpleNamespace(returncode=0)

        with (
            patch.object(
                backup.roles,
                "recovery_values",
                return_value={
                    "KAIROS_BACKUP_DB_USER": "kairos_backup",
                    "KAIROS_BACKUP_DB_PASSWORD": password,
                },
            ),
            patch.dict(
                os.environ, {"DOCKER_HOST": "foreign", "DOCKER_CONTEXT": "foreign"}
            ),
        ):
            self.assertEqual(backup.backup(io.BytesIO(), runner=runner), 0)
        command, kwargs = calls[-1]
        self.assertNotIn(password, " ".join(command))
        self.assertEqual(
            kwargs["input"], ("kairos_backup\n" + password + "\n").encode()
        )
        self.assertNotIn("DOCKER_HOST", kwargs["env"])
        self.assertEqual(command[:3], backup.release.DOCKER)

    def test_legacy_dump_requires_current_p0_override_on_disk(self):
        (self.runtime / "active-release").unlink()
        override = (
            self.runtime
            / "p0"
            / "run"
            / "source"
            / "infra"
            / "compose"
            / "p0-api.override.yaml"
        )
        override.parent.mkdir(parents=True)
        self.write(override, "synthetic-p0")
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if "inspect" in command:
                service = "postgres" if command[-1] == "kairos-postgres-1" else "api"
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "com.docker.compose.project": "kairos",
                            "com.docker.compose.service": service,
                            "com.docker.compose.project.config_files": str(override),
                        }
                    ),
                )
            return SimpleNamespace(returncode=0)

        self.assertEqual(backup.backup(io.BytesIO(), runner=runner), 0)
        self.assertIn("exec", calls[-1])
        override.unlink()
        with self.assertRaises(FileNotFoundError):
            backup.backup(io.BytesIO(), runner=runner)
