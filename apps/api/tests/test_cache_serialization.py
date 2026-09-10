import pickle

import pytest

from core.cache_serialization import StrictJSONSerializer


def forbidden_deserialization():
    raise AssertionError("Python objects must never be executed")


class PicklePayload:
    def __reduce__(self):
        return forbidden_deserialization, ()


@pytest.mark.parametrize(
    "value",
    [None, True, False, "1", "ação", 1.5, [1, "2"], {"limit": 12}],
    ids=lambda value: type(value).__name__,
)
def test_json_cache_round_trip_preserves_types(value):
    serializer = StrictJSONSerializer()
    restored = serializer.loads(serializer.dumps(value))
    assert restored == value
    assert type(restored) is type(value)


@pytest.mark.parametrize(
    "value", [0, -1, 12, 2**63 - 1, -(2**63)], ids=lambda value: type(value).__name__
)
def test_integer_encoding_remains_compatible_with_atomic_redis_increment(value):
    serializer = StrictJSONSerializer()
    assert type(serializer.dumps(value)) is int
    assert serializer.loads(str(value).encode()) == value


@pytest.mark.parametrize(
    "value",
    [
        pickle.dumps(PicklePayload()),
        b"legacy",
        b'j:{"x":1,"x":2}',
        b"j:NaN",
        b"j:Infinity",
        b"j:1e999",
        b"9223372036854775808",
        b"j:" + b"[" * 1000 + b"]" * 1000,
        b"x" * 65537,
    ],
    ids=lambda value: type(value).__name__,
)
def test_untrusted_or_legacy_value_rejected_without_execution(value):
    with pytest.raises(ValueError):
        StrictJSONSerializer().loads(value)


@pytest.mark.parametrize(
    "value",
    [object(), (1, 2), {1: "key"}, 2**64, float("nan"), "x" * 65537],
    ids=lambda value: type(value).__name__,
)
def test_unsupported_cache_objects_fail_closed(value):
    with pytest.raises(ValueError):
        StrictJSONSerializer().dumps(value)
