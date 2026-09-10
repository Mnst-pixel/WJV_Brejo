"""Prepare exclusive service env files. Never evaluate dotenv or print values."""

import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import uuid

SECRET_ROOT = Path("/opt/kairos/secrets")


def reject_symlinks(path):
    candidate = Path(path).absolute()
    if candidate.is_symlink() or any(
        parent.is_symlink() for parent in candidate.parents
    ):
        raise ValueError("Secret paths cannot contain symlinks")


def read_env(path):
    values = {}
    for row in Path(path).read_text().splitlines():
        if not row or row.startswith("#"):
            continue
        key, separator, value = row.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError("Malformed or duplicate secret variable")
        # Existing KairÃ³s secrets use unquoted, single-line dotenv values.
        if any(ord(char) < 32 for char in value) or value.startswith(("'", '"')):
            raise ValueError("Unsupported secret value encoding")
        values[key] = value
    return values


def project(values, specification):
    output = {}
    for service, mapping in specification.items():
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]*", service)
            or service == "recovery"
            or not isinstance(mapping, dict)
        ):
            raise ValueError("Invalid service secret projection")
        projected = {}
        for destination, source in mapping.items():
            if not all(
                isinstance(name, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
                for name in (destination, source)
            ):
                raise ValueError("Invalid secret variable name")
            if source not in values:
                if source == "SMTP_URL":
                    projected[destination] = ""
                    continue
                raise ValueError(f"Required secret name missing: {source}")
            projected[destination] = values[source]
        output[service] = projected
    return output


def prepare(master, destination, spec_path):
    if os.geteuid() != 0:
        raise ValueError("Root required")
    master = Path(master)
    reject_symlinks(master)
    reject_symlinks(destination)
    master = master.resolve(strict=True)
    destination = Path(destination)
    if (
        not master.is_relative_to(SECRET_ROOT)
        or not stat.S_ISREG(master.stat().st_mode)
        or stat.S_IMODE(master.stat().st_mode) != 0o600
    ):
        raise ValueError("Master secret ownership/path/mode invalid")
    if master.stat().st_uid != 0 or destination.exists() or destination.is_symlink():
        raise ValueError("Unsafe existing destination or owner")
    parent = destination.parent.resolve(strict=True)
    if not parent.is_relative_to(SECRET_ROOT):
        raise ValueError("Destination outside secret namespace")
    parent_info = parent.stat()
    if parent_info.st_uid != 0 or stat.S_IMODE(parent_info.st_mode) != 0o700:
        raise ValueError("Secret parent directory owner/mode invalid")
    values = read_env(master)
    additions = {
        "KAIROS_RUNTIME_DB_USER": "kairos_runtime",
        "KAIROS_WORKER_DB_USER": "kairos_worker",
        "KAIROS_MIGRATION_DB_USER": "kairos_migrator",
        "KAIROS_BACKUP_DB_USER": "kairos_backup",
    }
    for key in (
        "KAIROS_RUNTIME_DB_PASSWORD",
        "KAIROS_WORKER_DB_PASSWORD",
        "KAIROS_MIGRATION_DB_PASSWORD",
        "KAIROS_BACKUP_DB_PASSWORD",
        "KAIROS_WORKER_SECRET_KEY",
    ):
        additions[key] = secrets.token_hex(48)
    additions["KAIROS_MCP_DELEGATION_KEY"] = secrets.token_hex(48)
    additions["PARSER_API_TOKEN"] = secrets.token_hex(48)
    additions["KAIROS_PROXY_TOKEN"] = secrets.token_hex(48)
    additions["KAIROS_WORDPRESS_GATE_KEY"] = secrets.token_hex(48)
    for name in ("CACHE", "API_BROKER", "WORKER_BROKER", "BEAT_BROKER"):
        additions[f"KAIROS_REDIS_{name}_PASSWORD"] = secrets.token_hex(48)
    additions.update(
        KAIROS_REDIS_CACHE_USER="kairos_cache",
        KAIROS_REDIS_API_BROKER_USER="kairos_api_broker",
        KAIROS_REDIS_WORKER_BROKER_USER="kairos_worker_broker",
        KAIROS_REDIS_BEAT_BROKER_USER="kairos_beat_broker",
    )
    additions["KAIROS_MCP_PRINCIPALS"] = json.dumps(
        {
            "kairos-tools": {
                "token": secrets.token_hex(48),
                "user_id": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        "https://kairos.2-24-215-183.sslip.io/services/tool-client",
                    )
                ),
                "scopes": ["corpus.search", "study.notes.search"],
            }
        },
        separators=(",", ":"),
    )
    values.update(additions)
    # Internal credentials have no external human dependency. Recovery retains
    # this release's values; the preceding encrypted backup retains the old set.
    for name in ("DJANGO_SECRET_KEY", "LOCALAI_API_KEY", "REDIS_PASSWORD"):
        values[name] = secrets.token_hex(48)
    mapping = json.loads(Path(spec_path).read_text())
    files = project(values, mapping)
    os.umask(0o077)
    destination.mkdir(mode=0o700)
    # Retain a protected recovery input; it is never mounted in application services.
    files["recovery"] = values
    for service, fields in files.items():
        with (destination / f"{service}.env").open("x") as stream:
            for key, value in sorted(fields.items()):
                if any(char in value for char in "\r\n"):
                    raise ValueError("Multiline secret refused")
                # Compose env_file raw mode prevents dollar interpolation.
                stream.write(f"{key}={value}\n")
    print(
        json.dumps(
            {
                "directory": str(destination),
                "services": {
                    name: sorted(fields)
                    for name, fields in files.items()
                    if name != "recovery"
                },
            }
        )
    )


if __name__ == "__main__":
    try:
        prepare(*sys.argv[1:])
    except Exception as error:
        print(f"SECRET_PREPARATION=FAIL class={type(error).__name__}", file=sys.stderr)
        sys.exit(1)
