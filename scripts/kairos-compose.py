#!/usr/bin/env python3
"""Fail closed if Git, image descriptor or configuration drifts. No fallback Compose."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import stat

spec = importlib.util.spec_from_file_location(
    "release_manifest", Path(__file__).with_name("release-manifest.py")
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def command(checkout, descriptor, action, services):
    value = json.loads((descriptor / "manifest.json").read_text())
    release.verify(value, checkout)
    release.namespace(value["secrets_dir"], "/opt/kairos/secrets")
    expected = "".join(
        f"{key}={item}\n"
        for key, item in sorted(release.public_environment(value).items())
    )
    if (descriptor / "release.env").read_text() != expected:
        raise ValueError("Public descriptor was modified")
    if any(service not in value["images"] for service in services):
        raise ValueError("Unknown release service")
    base = release.DOCKER + [
        "compose",
        "--project-name",
        "kairos",
        "--env-file",
        str(descriptor / "release.env"),
        "-f",
        str(checkout / "infra/compose/compose.yaml"),
    ]
    if action == "migrate":
        if services:
            raise ValueError("Migration takes no arbitrary command")
        return base + [
            "--profile",
            "maintenance",
            "run",
            "--rm",
            "--no-deps",
            "migrate",
        ]
    if action in {"up", "stop"} and (not services or "migrate" in services):
        raise ValueError("Select explicit runtime services")
    return (
        base
        + {
            "config": ["config", "--quiet"],
            "ps": ["ps", "--all"],
            "up": ["up", "-d", "--no-build", "--pull", "never", "--no-deps"],
            "stop": ["stop"],
        }[action]
        + services
    )


def execute(args):
    # The pointer contains a path; unlike a symlink it cannot redirect resolution silently.
    descriptor = Path(args.release)
    if descriptor.is_symlink():
        raise ValueError("Release pointer cannot be a symlink")
    if descriptor.is_file():
        descriptor = Path(descriptor.read_text().strip())
    descriptor = release.namespace(descriptor, "/opt/kairos/runtime/releases")
    checkout = release.namespace("/opt/kairos/current", "/opt/kairos")
    cmd = command(checkout, descriptor, args.action, args.services)
    # Explicit public variables beat ambient COMPOSE_* / Docker interpolation inputs.
    env = release.command_environment()
    env.update(
        release.public_environment(
            json.loads((descriptor / "manifest.json").read_text())
        )
    )
    return subprocess.call(cmd, env=env)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["config", "ps", "up", "stop", "migrate"])
    parser.add_argument("services", nargs="*")
    parser.add_argument("--release", default="/opt/kairos/runtime/active-release")
    args = parser.parse_args()
    if args.action in {"up", "stop", "migrate"}:
        import fcntl

        release.namespace("/opt/kairos/runtime", "/opt/kairos")
        descriptor_fd = os.open(
            "/opt/kairos/runtime/.operation.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor_fd).st_mode):
                raise ValueError("Invalid operation lock")
            fcntl.flock(descriptor_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Acquire before reading pointer/checkout, not after building a stale command.
            raise SystemExit(execute(args))
        finally:
            os.close(descriptor_fd)
    raise SystemExit(execute(args))


if __name__ == "__main__":
    main()
