"""Observations must fail closed and must not claim maintenance or expose tasks."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location("legacy_drain", Path(__file__).resolve().parents[1] / "legacy_drain_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
HOST = "celery@synthetic-worker"


def fixture(keys=None):
    client = Mock()
    client.scan.return_value = (0, list(probe.BINDINGS if keys is None else keys))
    client.type.return_value = b"set"
    client.llen.return_value = 0
    client.hlen.return_value = 0
    client.zcard.return_value = 0
    inspector = SimpleNamespace(**{name: Mock(return_value={HOST: []}) for name in probe.OPERATIONS})
    return client, inspector


def test_empty_observation_never_claims_maintenance_or_drain():
    client, inspector = fixture()
    value = probe.observe(client, inspector, HOST)
    assert value["status"] == "EMPTY_AT_OBSERVATION"
    assert value["drain_confirmed"] is False
    assert value["producers_stopped"] is False
    assert value["broker_keys"] == 3
    client.flushdb.assert_not_called()
    client.delete.assert_not_called()


@pytest.mark.parametrize("operation", probe.OPERATIONS)
def test_active_reserved_scheduled_tasks_block_without_disclosing_arguments(operation):
    client, inspector = fixture()
    getattr(inspector, operation).return_value = {HOST: [{"args": "private-content-canary", "kwargs": {"password": "credential-canary"}}]}
    report = probe.observe(client, inspector, HOST)
    assert report["status"] == "NOT_EMPTY"
    assert report["worker_counts"][operation] == 1
    assert "canary" not in json.dumps(report)


@pytest.mark.parametrize("reply", [None, {}, {"other-worker": []}, {HOST: [], "other-worker": []}, {HOST: None}, {HOST: {}}])
def test_missing_ambiguous_or_malformed_worker_reply_is_not_empty(reply):
    client, inspector = fixture()
    inspector.active.return_value = reply
    with pytest.raises(ValueError):
        probe.observe(client, inspector, HOST)


@pytest.mark.parametrize("counter", ["hlen", "zcard"])
def test_unacknowledged_work_blocks(counter):
    client, inspector = fixture()
    getattr(client, counter).return_value = 1
    assert probe.observe(client, inspector, HOST)["status"] == "NOT_EMPTY"


def test_custom_and_priority_queues_are_counted_and_unknown_keys_block():
    key = b"private-queue-name-canary\x06\x163"
    client, inspector = fixture([key])
    client.type.return_value = b"list"
    client.llen.return_value = 2
    report = probe.observe(client, inspector, HOST)
    assert report["status"] == "NOT_EMPTY"
    assert report["queued_entries"] == 2
    assert report["unknown_keys"] == 1
    assert "canary" not in json.dumps(report)


@pytest.mark.parametrize("kind", [b"stream", b"string", b"hash", b"zset", b"set"])
def test_unclassified_durable_keys_fail_closed(kind):
    client, inspector = fixture([b"unknown"])
    client.type.return_value = kind
    assert probe.observe(client, inspector, HOST)["status"] == "NOT_EMPTY"


def test_expired_keys_are_tolerated_but_scan_is_bounded_even_with_duplicates():
    client, inspector = fixture([b"expired"])
    client.type.return_value = b"none"
    assert probe.observe(client, inspector, HOST)["status"] == "EMPTY_AT_OBSERVATION"
    client.scan.return_value = (1, [b"expired"])
    with pytest.raises(ValueError, match="iteration_limit"):
        probe.observe(client, inspector, HOST)
    client.scan.return_value = (0, [str(i).encode() for i in range(257)])
    with pytest.raises(ValueError, match="inventory_limit"):
        probe.observe(client, inspector, HOST)


@pytest.mark.parametrize("bad", [-1, True, None, "1"])
def test_invalid_queue_counts_fail_closed(bad):
    client, inspector = fixture([b"queue"])
    client.type.return_value = b"list"
    client.llen.return_value = bad
    with pytest.raises(ValueError):
        probe.observe(client, inspector, HOST)


def test_destination_cannot_be_wildcard_or_injected():
    for hostname in ["*", "celery@*", "celery@worker\nshutdown", "worker", "celery@" + "x" * 101]:
        client, inspector = fixture()
        with pytest.raises(ValueError):
            probe.observe(client, inspector, hostname)
        inspector.active.assert_not_called()


@pytest.mark.parametrize("suffix", ["?db=1", "?socket_timeout=999", "?socket_connect_timeout=999", "#fragment"])
def test_url_options_cannot_override_database_or_timeouts(suffix):
    with pytest.raises(ValueError):
        probe.redis_arguments("redis://redis/0" + suffix)


@pytest.mark.parametrize("url", ["redis://other/0", "rediss://redis/0", "redis://redis/1", "redis://redis:6380/0", "redis://redis/00"])
def test_only_the_known_legacy_endpoint_is_accepted(url):
    with pytest.raises(ValueError):
        probe.redis_arguments(url)


def test_explicit_connection_arguments_preserve_credentials_and_bound_timeouts():
    assert probe.redis_arguments("redis://user:encoded%3Apw@redis:6379/0") == {
        "host": "redis", "port": 6379, "db": 0, "username": "user", "password": "encoded:pw",
        "socket_timeout": 3, "socket_connect_timeout": 3,
    }


def test_empty_scan_pages_cannot_escape_the_iteration_bound():
    client, inspector = fixture([])
    client.scan.return_value = (1, [])
    with pytest.raises(ValueError, match="iteration_limit"):
        probe.observe(client, inspector, HOST)
    assert client.scan.call_count == 512


def test_duplicate_scan_pages_are_deduplicated():
    client, inspector = fixture()
    client.scan.side_effect = [(1, list(probe.BINDINGS)), (0, list(probe.BINDINGS))]
    report = probe.observe(client, inspector, HOST)
    assert report["broker_keys"] == 3
    assert report["broker_types"] == {"set": 3}


@pytest.mark.parametrize("key,kind", [(b"_kombu.binding.celery", b"stream"), (b"unacked", b"set"), (b"unacked_index", b"hash")])
def test_reserved_key_names_cannot_hide_an_unexpected_data_type(key, kind):
    client, inspector = fixture([key])
    client.type.return_value = kind
    with pytest.raises(ValueError, match="reserved_broker_key_type"):
        probe.observe(client, inspector, HOST)


@pytest.mark.parametrize("reply", [(True, []), (-1, []), (2**64, []), (0, None), (0, {}), (0, [b"key"] * 513), (0, ["string-key"])])
def test_malformed_scan_responses_fail_closed(reply):
    client, inspector = fixture()
    client.scan.return_value = reply
    with pytest.raises(ValueError):
        probe.observe(client, inspector, HOST)
