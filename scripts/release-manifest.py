#!/usr/bin/env python3
"""A release is a Git commit, its configuration hashes, and immutable image IDs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

FILES = (
    "infra/compose/compose.yaml",
    "infra/caddy/Caddyfile",
    "config/service-secrets.json",
)
SHA = re.compile(r"[a-f0-9]{40}")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]


def command_environment(environ=None):
    """The release belongs to this host; caller context cannot retarget Docker/Git."""
    source = os.environ if environ is None else environ
    return {
        key: value
        for key, value in source.items()
        if not key.upper().startswith(
            ("DOCKER_", "COMPOSE_", "GIT_", "KAIROS_IMAGE_", "KAIROS_SECRETS_")
        )
    }


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(checkout, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(checkout), *arguments],
        text=True,
        env=command_environment(),
        timeout=30,
    ).strip()


def namespace(path, root, *, existing=True):
    path = Path(path)
    resolved = path.resolve(strict=existing)
    if not resolved.is_relative_to(root) or resolved == Path(root) or path.is_symlink():
        raise ValueError("Release path outside its namespace")
    # Parent symlinks are also forbidden, including aliases inside the namespace.
    absolute = path.absolute()
    if any(
        parent.is_symlink()
        for parent in absolute.parents
        if parent.is_relative_to(Path(root))
    ):
        raise ValueError("Release path contains a symlinked parent")
    return resolved


def protected_file(path, root):
    resolved = namespace(path, root)
    info = resolved.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("Protected release file owner/mode invalid")
    return resolved


def manifest(checkout, images, secrets_dir):
    if Path(checkout).is_symlink() or not Path(checkout).is_dir():
        raise ValueError("Release checkout must be a real directory")
    head = git(checkout, "rev-parse", "HEAD")
    if not SHA.fullmatch(head) or git(
        checkout, "status", "--porcelain", "--untracked-files=normal"
    ):
        raise ValueError("Release requires a clean committed checkout")
    compose = json.loads((Path(checkout) / FILES[0]).read_text())
    services = set(compose["services"])
    if set(images) != services or any(
        not IMAGE.fullmatch(value) for value in images.values()
    ):
        raise ValueError("Every Compose service requires exactly one immutable image")
    if any(
        images["api"] != images[name]
        for name in ("worker", "migrate", "beat")
        if name in images
    ):
        raise ValueError(
            "API, worker, scheduler and migrations must share one source artifact"
        )
    return {
        "schema": 1,
        "commit": head,
        "images": images,
        "secrets_dir": str(secrets_dir),
        "configuration": {name: checksum(Path(checkout) / name) for name in FILES},
    }


def verify(value, checkout):
    if value.get("schema") != 1 or value != manifest(
        checkout, value["images"], value["secrets_dir"]
    ):
        raise ValueError(
            "Checkout or deployment configuration differs from the release"
        )


def public_environment(value):
    result = {
        "COMPOSE_PROJECT_NAME": "kairos",
        "KAIROS_SECRETS_DIR": value["secrets_dir"],
    }
    for service, image in value["images"].items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", service) or not IMAGE.fullmatch(image):
            raise ValueError("Invalid service/image")
        result["KAIROS_IMAGE_" + service.upper().replace("-", "_")] = image
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkout")
    parser.add_argument(
        "images", help="JSON mapping service names to locally inspected image IDs"
    )
    parser.add_argument("secrets_dir")
    parser.add_argument("destination")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("Root required")
    checkout = namespace(args.checkout, "/opt/kairos")
    secrets_dir = namespace(args.secrets_dir, "/opt/kairos/secrets")
    destination = namespace(
        args.destination, "/opt/kairos/runtime/releases", existing=False
    )
    if destination.exists():
        raise ValueError("Release descriptor is immutable")
    value = manifest(checkout, json.loads(Path(args.images).read_text()), secrets_dir)
    for service, image in value["images"].items():
        actual = subprocess.check_output(
            DOCKER + ["image", "inspect", "-f", "{{.Id}}", image],
            text=True,
            env=command_environment(),
            timeout=30,
        ).strip()
        if actual != image:
            raise ValueError("Pinned image unavailable")
        if service in {"api", "worker", "migrate", "beat", "parser", "web"}:
            revision = subprocess.check_output(
                DOCKER
                + [
                    "image",
                    "inspect",
                    "-f",
                    '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                    image,
                ],
                text=True,
                env=command_environment(),
                timeout=30,
            ).strip()
            if revision != value["commit"]:
                raise ValueError("First-party image source revision mismatch")
    os.umask(0o077)
    destination.mkdir()
    (destination / "manifest.json").write_text(json.dumps(value, indent=2) + "\n")
    (destination / "release.env").write_text(
        "".join(
            f"{key}={item}\n" for key, item in sorted(public_environment(value).items())
        )
    )
    print("RELEASE_DESCRIPTOR=PASS commit=" + value["commit"])


if __name__ == "__main__":
    main()
