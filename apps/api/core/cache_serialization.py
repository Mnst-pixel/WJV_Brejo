"""Bounded JSON cache values; never deserialize Python objects from shared storage."""

import json
import math
import re

MAX_BYTES = 65536
INTEGER = re.compile(rb"-?(?:0|[1-9][0-9]{0,18})\Z")


def _validate(value, depth=0):
    if depth > 16:
        raise ValueError("cache_value_depth")
    if value is None or type(value) in (bool, str):
        return
    if type(value) is int and -(2**63) <= value < 2**63:
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _validate(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _validate(item, depth + 1)
        return
    raise ValueError("cache_value_type")


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("cache_duplicate_key")
        value[key] = item
    return value


class StrictJSONSerializer:
    def dumps(self, value):
        _validate(value)
        # Redis INCR must operate atomically on unadorned decimal integers.
        if type(value) is int:
            return value
        encoded = b"j:" + json.dumps(
            value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode("ascii")
        if len(encoded) > MAX_BYTES:
            raise ValueError("cache_value_size")
        return encoded

    def loads(self, encoded):
        if type(encoded) is not bytes or len(encoded) > MAX_BYTES:
            raise ValueError("cache_value_encoding")
        if INTEGER.fullmatch(encoded):
            value = int(encoded)
        elif encoded.startswith(b"j:"):
            try:
                value = json.loads(encoded[2:], object_pairs_hook=_pairs)
            except (UnicodeError, RecursionError, json.JSONDecodeError):
                raise ValueError("cache_value_json") from None
        else:
            raise ValueError("cache_value_encoding")
        _validate(value)
        return value
