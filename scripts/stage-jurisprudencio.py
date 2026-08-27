#!/usr/bin/env python3
"""Safely stage and harden the private Jurisprudêncio source archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


ARCHIVE_SHA256 = "9ea64f8a04a511ebf569e07ab8c6cee8bcb8202d1fb54f854a1c58d743618800"
ARCHIVE_ENTRIES = 26
PREFIX = PurePosixPath("codigo-projeto-mcp")
COMPONENTS = {"gateway-jurisprudencio", "mcp-server", "mcp-brasil-container"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) != ARCHIVE_ENTRIES:
        raise SystemExit(f"unexpected archive entry count: {len(members)}")
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != str(PREFIX):
            raise SystemExit(f"unsafe or unexpected archive path: {member.filename}")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise SystemExit(f"symbolic links are not allowed: {member.filename}")
    return members


def patch_package(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    dependencies = payload.get("dependencies", {})
    expected = {"adm-zip": "^0.5.16", "fast-xml-parser": "^4.5.1"}
    for package, version in expected.items():
        if dependencies.get(package) != version:
            raise SystemExit(f"unexpected upstream dependency {package}={dependencies.get(package)!r}")
    dependencies["adm-zip"] = "^0.6.0"
    dependencies["fast-xml-parser"] = "^5.11.0"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def disable_url_secret(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    original = 'urlSecret: env("MCP_URL_SECRET", process.env.MCP_API_KEY?.trim() || ""),'
    replacement = 'urlSecret: process.env.MCP_URL_SECRET?.trim() || "",'
    if text.count(original) != 1:
        raise SystemExit("unexpected MCP URL-secret source; refusing blind patch")
    path.write_text(text.replace(original, replacement), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    archive_path = args.archive.resolve(strict=True)
    target = args.target.resolve()
    expected_suffix = Path("services/jurisprudencio/upstream")
    if Path(*target.parts[-3:]) != expected_suffix:
        raise SystemExit("target must end in services/jurisprudencio/upstream")
    if sha256(archive_path) != ARCHIVE_SHA256:
        raise SystemExit("archive SHA-256 mismatch")
    if target.exists() and any(target.iterdir()):
        raise SystemExit("target is not empty; refusing to replace private source")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".jurisprudencio-", dir=target.parent) as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            for member in safe_members(archive):
                archive.extract(member, staging)
        source_root = staging / str(PREFIX)
        observed = {item.name for item in source_root.iterdir() if item.is_dir()}
        if observed != COMPONENTS:
            raise SystemExit(f"unexpected component set: {sorted(observed)}")
        patch_package(source_root / "gateway-jurisprudencio/package.json")
        disable_url_secret(source_root / "mcp-server/src/server.mjs")
        if target.exists():
            target.rmdir()
        os.replace(source_root, target)
    print(f"JURISPRUDENCIO_STAGE=PASS target={target}")


if __name__ == "__main__":
    main()
