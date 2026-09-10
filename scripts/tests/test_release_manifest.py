import importlib.util
import json
from pathlib import Path
import tempfile
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "release_manifest", Path(__file__).resolve().parents[1] / "release-manifest.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="kairos-release-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.images = {
            service: "sha256:" + "a" * 64
            for service in ("api", "worker", "migrate", "beat")
        }
        for name in release.FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"services": {key: {} for key in self.images}}))
        self.mock = patch.object(
            release,
            "git",
            side_effect=lambda root, *args: "b" * 40 if args[0] == "rev-parse" else "",
        )
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def value(self):
        return release.manifest(
            self.root, self.images, "/opt/kairos/secrets/release-test"
        )

    def test_unchanged_source_verified(self):
        value = self.value()
        release.verify(value, self.root)
        self.assertEqual(
            release.public_environment(value)["KAIROS_IMAGE_API"], self.images["api"]
        )

    def test_configuration_drift_rejected(self):
        value = self.value()
        (self.root / "infra/caddy/Caddyfile").write_text("changed")
        with self.assertRaises(ValueError):
            release.verify(value, self.root)

    def test_dirty_checkout_rejected(self):
        with patch.object(release, "git", return_value="M source.py"):
            with self.assertRaises(ValueError):
                self.value()

    def test_missing_image_rejected(self):
        del self.images["worker"]
        with self.assertRaises(ValueError):
            self.value()

    def test_unpinned_image_rejected(self):
        self.images["api"] = "kairos-api:latest"
        with self.assertRaises(ValueError):
            self.value()

    def test_api_worker_different_sources_rejected(self):
        self.images["worker"] = "sha256:" + "c" * 64
        with self.assertRaises(ValueError):
            self.value()

    def test_old_scheduler_is_rejected(self):
        self.images["beat"] = "sha256:" + "c" * 64
        with self.assertRaises(ValueError):
            self.value()

    def test_namespace_escape_rejected(self):
        with self.assertRaises(ValueError):
            release.namespace(self.root, "/opt/kairos")

    def test_ambient_docker_git_and_compose_cannot_retarget_operations(self):
        injected = {
            "PATH": "safe-path",
            "DOCKER_HOST": "tcp://foreign:2375",
            "DOCKER_CONTEXT": "foreign",
            "DOCKER_TLS_VERIFY": "1",
            "DOCKER_CERT_PATH": "/foreign",
            "DOCKER_CONFIG": "/foreign",
            "DOCKER_API_VERSION": "1.20",
            "GIT_DIR": "/foreign/.git",
            "GIT_WORK_TREE": "/foreign",
            "GIT_CONFIG_COUNT": "1",
            "COMPOSE_FILE": "/foreign.yaml",
            "KAIROS_IMAGE_API": "foreign",
            "KAIROS_SECRETS_DIR": "/foreign",
        }
        self.assertEqual(release.command_environment(injected), {"PATH": "safe-path"})
        self.assertEqual(
            release.DOCKER, ["docker", "--host", "unix:///var/run/docker.sock"]
        )

    @unittest.skipUnless(os.name == "posix", "real Linux symlink checks")
    def test_symlinked_source_directory_and_parent_rejected(self):
        actual = self.root / "actual"
        actual.mkdir()
        (actual / "child").mkdir()
        alias = self.root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        for path in (alias, alias / "child"):
            with self.assertRaises(ValueError):
                release.namespace(path, self.root)


@unittest.skipUnless(shutil.which("git"), "real Git binary required")
class ActualGitReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="kairos-real-git-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.images = {
            name: "sha256:" + "a" * 64 for name in ("api", "worker", "migrate", "beat")
        }
        for filename in release.FILES:
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"services": {name: {} for name in self.images}})
            )

        def git(*args):
            subprocess.run(
                ["git", "-C", str(self.root), *args],
                check=True,
                capture_output=True,
                env=release.command_environment(),
            )

        self.git = git
        git("init", "--quiet")
        git("config", "user.name", "Synthetic Test")
        git("config", "user.email", "synthetic@example.invalid")
        git("add", ".")
        git("commit", "--quiet", "--no-gpg-sign", "-m", "test: synthetic release")

    def test_actual_commit_change_fails_verification(self):
        value = release.manifest(self.root, self.images, "/opt/kairos/secrets/test")
        self.git(
            "commit",
            "--allow-empty",
            "--quiet",
            "--no-gpg-sign",
            "-m",
            "test: different commit",
        )
        with self.assertRaises(ValueError):
            release.verify(value, self.root)

    def test_git_environment_injection_does_not_change_checkout_identity(self):
        expected = release.git(self.root, "rev-parse", "HEAD")
        with patch.dict(
            os.environ,
            {
                "GIT_DIR": str(self.root / "missing"),
                "GIT_WORK_TREE": "/not-kairos",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.worktree",
                "GIT_CONFIG_VALUE_0": "/not-kairos",
            },
        ):
            self.assertEqual(release.git(self.root, "rev-parse", "HEAD"), expected)
            release.manifest(self.root, self.images, "/opt/kairos/secrets/test")

    def test_beat_cannot_reference_another_source_artifact(self):
        self.images["beat"] = "sha256:" + "b" * 64
        with self.assertRaises(ValueError):
            release.manifest(self.root, self.images, "/opt/kairos/secrets/test")


if __name__ == "__main__":
    unittest.main()
