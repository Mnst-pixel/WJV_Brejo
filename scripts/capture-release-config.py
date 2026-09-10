#!/usr/bin/env python3
"""Add service credentials to the encrypted backup payload."""

import json
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

RUNTIME = Path("/opt/kairos/runtime")
SECRETS = Path("/opt/kairos/secrets")
BACKUPS = Path("/srv/kairos/backups")
SPEC = importlib.util.spec_from_file_location(
    "release_manifest", Path(__file__).with_name("release-manifest.py")
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def protected(path, root):
    return release.protected_file(path, root)


def capture(destination):
    target = release.namespace(destination, BACKUPS)
    info = target.stat()
    if (
        target.name != "payload"
        or os.geteuid() != 0
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Invalid encrypted payload destination owner/mode")
    pointer = RUNTIME / "active-release"
    if not pointer.exists() and not pointer.is_symlink():
        return
    pointer = protected(pointer, RUNTIME)
    descriptor = release.namespace(pointer.read_text().strip(), RUNTIME / "releases")
    manifest = protected(descriptor / "manifest.json", RUNTIME / "releases")
    public_env = protected(descriptor / "release.env", RUNTIME / "releases")
    value = json.loads(manifest.read_text())
    if value.get("schema") != 1 or not release.SHA.fullmatch(value.get("commit", "")):
        raise ValueError("Invalid captured release descriptor")
    secret_dir = release.namespace(value["secrets_dir"], SECRETS)
    expected_env = "".join(
        f"{key}={item}\n"
        for key, item in sorted(release.public_environment(value).items())
    )
    if public_env.read_text() != expected_env:
        raise ValueError("Release public environment mismatch")
    # Validate all inputs before creating a payload containing credentials.
    sources = {"manifest.json": manifest, "release.env": public_env, "pointer": pointer}
    for service in {*value["images"], "recovery"}:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", service):
            raise ValueError("Invalid service name")
        source = secret_dir / f"{service}.env"
        if source.exists() or source.is_symlink():
            sources[source.name] = protected(source, SECRETS)
    if "recovery.env" not in sources:
        raise ValueError("Recovery credentials missing")
    sources["redis.acl"] = protected(secret_dir / "redis.acl", SECRETS)
    output = target / "active-release"
    output.mkdir(mode=0o700)
    for name, source in sources.items():
        descriptor_fd = os.open(
            output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor_fd, "wb") as destination_file:
            destination_file.write(source.read_bytes())
            destination_file.flush()
            os.fsync(destination_file.fileno())


if __name__ == "__main__":
    try:
        capture(sys.argv[1])
    except Exception:
        print(
            "Release configuration capture failed; no credentials emitted",
            file=sys.stderr,
        )
        raise SystemExit(1)
