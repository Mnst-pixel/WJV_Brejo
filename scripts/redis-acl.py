#!/usr/bin/env python3
"""Render a deterministic Redis >=7 ACL artifact from protected recovery values."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

PRINCIPALS = {
    "kairos_cache": "KAIROS_REDIS_CACHE_PASSWORD",
    "kairos_api_broker": "KAIROS_REDIS_API_BROKER_PASSWORD",
    "kairos_worker_broker": "KAIROS_REDIS_WORKER_BROKER_PASSWORD",
    "kairos_beat_broker": "KAIROS_REDIS_BEAT_BROKER_PASSWORD",
}
CACHE_PREFIX = "kairos:cache:v2:"
BROKER_PREFIX = "kairos:broker:v1:"
COMMON = ("ping", "echo", "select", "hello", "quit", "client|setname")
CACHE_COMMANDS = (
    "get",
    "mget",
    "set",
    "mset",
    "del",
    "exists",
    "expire",
    "pexpire",
    "persist",
    "ttl",
    "pttl",
    "incr",
    "incrby",
    "decr",
    "decrby",
    "multi",
    "exec",
    "discard",
    "watch",
    "unwatch",
)
BROKER_COMMANDS = (
    "get",
    "mget",
    "set",
    "setex",
    "psetex",
    "del",
    "exists",
    "expire",
    "pexpire",
    "ttl",
    "pttl",
    "incr",
    "incrby",
    "hset",
    "hget",
    "hdel",
    "hlen",
    "hgetall",
    "lpush",
    "rpush",
    "lpop",
    "rpop",
    "brpop",
    "llen",
    "lrange",
    "sadd",
    "srem",
    "smembers",
    "zadd",
    "zrem",
    "zrevrangebyscore",
    "zrangebyscore",
    "zcard",
    "multi",
    "exec",
    "discard",
    "watch",
    "unwatch",
    "publish",
    "subscribe",
    "unsubscribe",
    "psubscribe",
    "punsubscribe",
    "script|load",
    "evalsha",
)


def validate(values):
    passwords = []
    for name in PRINCIPALS.values():
        value = values.get(name, "")
        if not re.fullmatch(r"[a-f0-9]{96}", value):
            raise ValueError("invalid_generated_redis_password")
        passwords.append(value)
    admin = values.get("REDIS_PASSWORD", "")
    if len(admin) < 32 or any(ord(char) < 33 for char in admin):
        raise ValueError("invalid_redis_admin_password")
    if len(set(passwords + [admin])) != len(passwords) + 1:
        raise ValueError("shared_redis_password")


def render(values):
    validate(values)

    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    lines = [
        "user default reset on #" + digest(values["REDIS_PASSWORD"]) + " ~* &* +@all"
    ]
    for user, secret_name in PRINCIPALS.items():
        cache = user == "kairos_cache"
        scope = "~" + (CACHE_PREFIX if cache else BROKER_PREFIX) + "*"
        channels = "" if cache else " &" + BROKER_PREFIX + "*"
        commands = COMMON + (CACHE_COMMANDS if cache else BROKER_COMMANDS)
        lines.append(
            "user "
            + user
            + " reset on #"
            + digest(values[secret_name])
            + " "
            + scope
            + channels
            + " "
            + " ".join("+" + command for command in commands)
        )
    return "\n".join(lines) + "\n"


def plan(values):
    content = render(values)
    return {
        "status": "PLAN",
        "minimum_redis_major": 7,
        "acl_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "principals": sorted(PRINCIPALS),
        "cache_prefix": CACHE_PREFIX,
        "broker_prefix": BROKER_PREFIX,
    }


def read_recovery(path):
    candidate = Path(path)
    if candidate.name != "recovery.env" or candidate.is_symlink():
        raise ValueError("protected_recovery_required")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to("/opt/kairos/secrets"):
        raise ValueError("recovery_namespace")
    info = resolved.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != 0
    ):
        raise ValueError("recovery_owner_mode")
    values = {}
    for line in resolved.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in values or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("invalid_recovery_format")
        values[key] = value
    validate(values)
    return values


def write_artifact(destination, values, expected_hash):
    report = plan(values)
    if report["acl_sha256"] != expected_hash:
        raise ValueError("redis_acl_plan_changed")
    destination = Path(destination)
    parent = destination.parent.resolve(strict=True)
    if (
        not parent.is_relative_to("/opt/kairos/secrets")
        or destination.name != "redis.acl"
    ):
        raise ValueError("redis_acl_namespace")
    descriptor = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as stream:
        stream.write(render(values))
        stream.flush()
        os.fsync(stream.fileno())
    return report | {"status": "RENDERED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "render"))
    parser.add_argument("--recovery", required=True)
    parser.add_argument("--destination")
    parser.add_argument("--expected-plan-hash")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError("root_required")
        values = read_recovery(args.recovery)
        report = (
            plan(values)
            if args.mode == "plan"
            else write_artifact(args.destination, values, args.expected_plan_hash)
        )
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as error:
        print(
            json.dumps({"status": "FAIL", "error": type(error).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
