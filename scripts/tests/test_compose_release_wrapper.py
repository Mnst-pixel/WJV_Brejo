import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "compose_wrapper", Path(__file__).resolve().parents[1] / "kairos-compose.py"
)
wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wrapper)


class ComposeWrapperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="kairos-wrapper-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.descriptor = self.root / "descriptor"
        self.descriptor.mkdir()
        self.images = {
            name: "sha256:" + "a" * 64 for name in ("api", "worker", "migrate", "beat")
        }
        for name in wrapper.release.FILES:
            path = self.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"services": {key: {} for key in self.images}}))
        self.git = patch.object(
            wrapper.release,
            "git",
            side_effect=lambda checkout, *args: "b" * 40
            if args[0] == "rev-parse"
            else "",
        )
        self.git.start()
        self.addCleanup(self.git.stop)
        self.value = wrapper.release.manifest(
            self.checkout, self.images, "/opt/kairos/secrets/test"
        )
        (self.descriptor / "manifest.json").write_text(json.dumps(self.value))
        (self.descriptor / "release.env").write_text(
            "".join(
                f"{key}={item}\n"
                for key, item in sorted(
                    wrapper.release.public_environment(self.value).items()
                )
            )
        )

        # Only the namespace/filesystem location seam is mapped to this fixture;
        # real manifest/hash validation and command construction run unchanged.
        def namespace(path, root):
            if str(path) == "/opt/kairos/current":
                return self.checkout
            if str(path) == "/opt/kairos/secrets/test":
                return Path(path)
            if Path(path) == self.descriptor:
                return self.descriptor
            raise ValueError("Unknown fixture path")

        self.namespace = patch.object(
            wrapper.release, "namespace", side_effect=namespace
        )
        self.namespace.start()
        self.addCleanup(self.namespace.stop)

    def test_runtime_command_requires_explicit_services_without_build_or_pull(self):
        command = wrapper.command(self.checkout, self.descriptor, "up", ["api"])
        self.assertEqual(
            command[:4], ["docker", "--host", "unix:///var/run/docker.sock", "compose"]
        )
        self.assertEqual(
            command[-7:],
            ["up", "-d", "--no-build", "--pull", "never", "--no-deps", "api"],
        )
        for action, services in (
            ("up", []),
            ("stop", []),
            ("up", ["migrate"]),
            ("migrate", ["api"]),
            ("up", ["--help"]),
            ("up", ["foreign"]),
        ):
            with (
                self.subTest(action=action, services=services),
                self.assertRaises(ValueError),
            ):
                wrapper.command(self.checkout, self.descriptor, action, services)

    def test_env_file_tamper_and_commit_mismatch_prevent_any_docker_call(self):
        (self.descriptor / "release.env").write_text("KAIROS_IMAGE_API=wrong\n")
        with patch.object(wrapper.subprocess, "call") as call:
            with self.assertRaises(ValueError):
                wrapper.execute(
                    SimpleNamespace(
                        release=str(self.descriptor), action="up", services=["api"]
                    )
                )
            call.assert_not_called()

    def test_inherited_environment_cannot_retarget_docker(self):
        with patch.dict(
            os.environ,
            {
                "DOCKER_HOST": "tcp://foreign:2375",
                "DOCKER_CONTEXT": "foreign",
                "DOCKER_TLS_VERIFY": "1",
                "COMPOSE_FILE": "/foreign",
                "KAIROS_IMAGE_API": "foreign",
            },
        ):
            with patch.object(wrapper.subprocess, "call", return_value=0) as call:
                self.assertEqual(
                    wrapper.execute(
                        SimpleNamespace(
                            release=str(self.descriptor), action="config", services=[]
                        )
                    ),
                    0,
                )
        args, kwargs = call.call_args
        self.assertEqual(args[0][:3], wrapper.release.DOCKER)
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS_VERIFY",
            "COMPOSE_FILE",
        ):
            self.assertNotIn(key, kwargs["env"])
        self.assertEqual(kwargs["env"]["KAIROS_IMAGE_API"], self.images["api"])
