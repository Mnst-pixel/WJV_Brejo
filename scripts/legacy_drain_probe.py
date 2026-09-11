"""Bounded legacy Celery observation; never a substitute for stopping producers."""
import json
import re
from urllib.parse import unquote, urlsplit


OPERATIONS = ("active", "reserved", "scheduled")
BINDINGS = {b"_kombu.binding.celery", b"_kombu.binding.celeryev", b"_kombu.binding.celery.pidbox"}


def redis_arguments(url):
    endpoint = urlsplit(url)
    if endpoint.scheme != "redis" or endpoint.hostname != "redis" or endpoint.port not in (None, 6379) or endpoint.path not in ("", "/0") or endpoint.query or endpoint.fragment:
        raise ValueError("unexpected_legacy_broker_endpoint")
    return {"host": "redis", "port": 6379, "db": 0,
            "username": unquote(endpoint.username) if endpoint.username else None,
            "password": unquote(endpoint.password) if endpoint.password else None,
            "socket_timeout": 3, "socket_connect_timeout": 3}


def observe(client, inspector, hostname):
    if not re.fullmatch(r"celery@[a-zA-Z0-9_.-]{1,100}", hostname):
        raise ValueError("invalid_worker_identity")
    counts = {}
    for operation in OPERATIONS:
        replies = getattr(inspector, operation)()
        if not isinstance(replies, dict) or set(replies) != {hostname}:
            raise ValueError("missing_or_ambiguous_worker_reply")
        tasks = replies[hostname]
        if not isinstance(tasks, list) or len(tasks) > 10000:
            raise ValueError("invalid_worker_reply")
        counts[operation] = len(tasks)
    keys = set()
    kinds = {}
    queued = 0
    unknown = 0
    cursor = 0
    for _ in range(512):
        cursor, batch = client.scan(cursor=cursor, count=100)
        if type(cursor) is not int or not 0 <= cursor < 2**64 or not isinstance(batch, list) or len(batch) > 512:
            raise ValueError("invalid_broker_scan_reply")
        for key in batch:
            if not isinstance(key, bytes):
                raise ValueError("invalid_broker_key_encoding")
            if key in keys:
                continue
            keys.add(key)
            if len(keys) > 256:
                raise ValueError("broker_inventory_limit")
            kind = client.type(key)
            if kind == b"none":
                continue  # An expiring monitor reply is not a durable job.
            if kind not in {b"string", b"list", b"set", b"zset", b"hash", b"stream"}:
                raise ValueError("unexpected_broker_key_type")
            expected_kind = b"set" if key in BINDINGS else {b"unacked": b"hash", b"unacked_index": b"zset"}.get(key)
            if expected_kind and kind != expected_kind:
                raise ValueError("reserved_broker_key_type_mismatch")
            kinds[kind.decode()] = kinds.get(kind.decode(), 0) + 1
            if kind == b"list":
                length = client.llen(key)
                if type(length) is not int or length < 0:
                    raise ValueError("invalid_queue_length")
                queued += length
            if expected_kind is None:
                unknown += 1
        if cursor == 0:
            break
    else:
        raise ValueError("broker_scan_iteration_limit")
    unacked = client.hlen(b"unacked")
    indexed = client.zcard(b"unacked_index")
    if any(type(number) is not int or number < 0 for number in [queued, unacked, indexed]):
        raise ValueError("invalid_broker_count")
    empty = not any([queued, unacked, indexed, unknown, *counts.values()])
    return {
        "schema": 1,
        "status": "EMPTY_AT_OBSERVATION" if empty else "NOT_EMPTY",
        "worker_counts": counts,
        "broker_keys": len(keys),
        "broker_types": kinds,
        "queued_entries": queued,
        "unacked": unacked,
        "unacked_index": indexed,
        "unknown_keys": unknown,
        "producers_stopped": False,
        "drain_confirmed": False,
    }


def main():
    import contextlib
    import os
    import signal
    import sys

    try:
        if os.name != "posix":
            raise ValueError("linux_container_required")
        # The caller's Docker CLI timeout alone would leave an exec process alive.
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.alarm(20)
        hostname = sys.stdin.readline(160).strip()
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kairos.settings")
            from django.conf import settings
            from kairos.celery import app
            import redis

            arguments = redis_arguments(settings.CELERY_BROKER_URL)
            if any(value not in (None, settings.CELERY_BROKER_URL) for value in (app.conf.broker_url, app.conf.broker_read_url, app.conf.broker_write_url)):
                raise ValueError("ambiguous_celery_broker_endpoint")
            if getattr(settings, "CELERY_BROKER_TRANSPORT_OPTIONS", {}).get("global_keyprefix", ""):
                raise ValueError("not_the_legacy_broker")
            if not re.fullmatch(r"celery@[a-zA-Z0-9_.-]{1,100}", hostname):
                raise ValueError("invalid_worker_identity")
            client = redis.Redis(**arguments)
            result = observe(client, app.control.inspect(destination=[hostname], timeout=3), hostname)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"schema": 1, "status": "UNAVAILABLE", "drain_confirmed": False}))
        return 1
    finally:
        if os.name == "posix":
            signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
