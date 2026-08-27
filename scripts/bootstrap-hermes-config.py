#!/usr/bin/env python3
"""Create the private Hermes profile without writing secrets to the repository."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import yaml


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if len(value) < 16:
        raise SystemExit(f"{name} must be a non-empty high-entropy secret")
    return value


template_path = Path("/bootstrap/config.template.yaml")
soul_path = Path("/bootstrap/SOUL.md")
target_dir = Path("/opt/data")
target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

config = yaml.safe_load(template_path.read_text(encoding="utf-8"))
config["model"]["api_key"] = required("LOCALAI_API_KEY")
config["mcp_servers"]["jurisprudencio"]["headers"]["Authorization"] = (
    f"Bearer {required('MCP_API_KEY')}"
)

target_config = target_dir / "config.yaml"
temporary_config = target_dir / ".config.yaml.tmp"
temporary_config.write_text(
    yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
)
temporary_config.chmod(stat.S_IRUSR | stat.S_IWUSR)
temporary_config.replace(target_config)

target_soul = target_dir / "SOUL.md"
shutil.copyfile(soul_path, target_soul)
target_soul.chmod(stat.S_IRUSR | stat.S_IWUSR)
print("HERMES_CONFIG_BOOTSTRAP=PASS")
