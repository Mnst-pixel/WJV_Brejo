#!/usr/bin/env python3
"""Stream pg_dump with protected credentials and an explicitly local Docker daemon."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

RUNTIME = Path("/opt/kairos/runtime")
SECRETS = Path("/opt/kairos/secrets")


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("release_manifest", "release-manifest.py")
roles = load("db_roles", "database-roles.py")


def inspected_labels(container, service, runner, environment):
    result = runner(
        release.DOCKER
        + ["container", "inspect", "-f", "{{json .Config.Labels}}", container],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    if result.returncode:
        raise ValueError("Container inspection failed")
    labels = json.loads(result.stdout)
    if (
        labels.get("com.docker.compose.project") != "kairos"
        or labels.get("com.docker.compose.service") != service
    ):
        raise ValueError("Foreign backup container")
    return labels


def backup(stdout, *, runner=subprocess.run):
    environment = release.command_environment()
    inspected_labels("kairos-postgres-1", "postgres", runner, environment)
    pointer = RUNTIME / "active-release"
    if not pointer.exists() and not pointer.is_symlink():
        # Preserve the pre-cutover backup only when the *running API* proves the
        # historical P0 override, never solely because a descriptor is missing.
        labels = inspected_labels("kairos-api-1", "api", runner, environment)
        files = labels.get("com.docker.compose.project.config_files", "").split(",")
        overrides = [
            path
            for path in files
            if path.endswith("/infra/compose/p0-api.override.yaml")
        ]
        if labels.get("com.kairos.managed") == "release" or len(overrides) != 1:
            raise ValueError(
                "Missing release pointer and no verified pre-cutover P0 deployment"
            )
        override = release.namespace(overrides[0], RUNTIME / "p0")
        if not override.is_file():
            raise ValueError("Historical P0 override unavailable")
        result = runner(
            release.DOCKER
            + [
                "exec",
                "kairos-postgres-1",
                "sh",
                "-ec",
                'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
            ],
            stdout=stdout,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=900,
        )
        return result.returncode
    pointer = release.protected_file(pointer, RUNTIME)
    descriptor = release.namespace(pointer.read_text().strip(), RUNTIME / "releases")
    manifest = release.protected_file(
        descriptor / "manifest.json", RUNTIME / "releases"
    )
    value = json.loads(manifest.read_text())
    if value.get("schema") != 1 or not release.SHA.fullmatch(value.get("commit", "")):
        raise ValueError("Invalid backup release descriptor")
    secret_dir = release.namespace(value["secrets_dir"], SECRETS)
    values = roles.recovery_values(secret_dir / "recovery.env")
    payload = (
        values["KAIROS_BACKUP_DB_USER"]
        + "\n"
        + values["KAIROS_BACKUP_DB_PASSWORD"]
        + "\n"
    ).encode()
    result = runner(
        release.DOCKER
        + [
            "exec",
            "-i",
            "kairos-postgres-1",
            "sh",
            "-ec",
            "IFS= read -r PGUSER; IFS= read -r PGPASSWORD; export PGUSER PGPASSWORD; exec pg_dump -h 127.0.0.1 -d kairos -Fc",
        ],
        input=payload,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        env=environment,
        timeout=900,
    )
    return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(backup(sys.stdout.buffer))
    except Exception:
        print("PostgreSQL backup failed; no credentials emitted", file=sys.stderr)
        raise SystemExit(1)
