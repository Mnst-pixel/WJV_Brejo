"""Bounded LocalAI inference transport; no arbitrary hosts, tools or session reuse."""

import json
import time

import httpx
from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import APIException, Throttled


class AIUnavailable(APIException):
    status_code = 503
    default_code = "ai_temporarily_unavailable"
    default_detail = "O assistente está temporariamente indisponível; os demais módulos continuam funcionando."


def _counter(key, *, window, maximum):
    bucket = int(time.time()) // window
    key = f"kairos:ai:{key}:{bucket}"
    try:
        cache.add(key, 0, timeout=window * 2)
        value = cache.incr(key)
    except Exception:
        raise AIUnavailable() from None
    if value > maximum:
        raise Throttled(
            wait=window, detail="Limite temporário de consultas de IA atingido."
        )


def admit_consultation(user):
    _counter(f"user:{user.pk}", window=60, maximum=12)
    _counter("consultations", window=60, maximum=60)


def _breaker_key():
    return f"kairos:ai:upstream-failures:{int(time.time()) // 60}"


def localai_json(path, payload, *, max_bytes=65536):
    if path not in {"/v1/chat/completions", "/v1/embeddings"}:
        raise AIUnavailable()
    # An administrator-controlled URL is still validated, preventing accidental
    # bearer disclosure via redirects, proxies or alternate network destinations.
    if (
        settings.LOCALAI_BASE_URL.rstrip("/") != "http://localai:8080"
        or len(settings.LOCALAI_API_KEY) < 16
    ):
        raise AIUnavailable()
    key = _breaker_key()
    try:
        if cache.get(key, 0) >= 5:
            raise AIUnavailable()
    except Exception:
        raise AIUnavailable() from None
    _counter("upstream", window=60, maximum=120)
    started = time.monotonic()
    try:
        with httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(10, connect=3),
            limits=httpx.Limits(max_connections=1),
        ) as client:
            with client.stream(
                "POST",
                "http://localai:8080" + path,
                headers={
                    "Authorization": f"Bearer {settings.LOCALAI_API_KEY}",
                    "Accept-Encoding": "identity",
                },
                json=payload,
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("compressed response not permitted")
                if (
                    not response.headers.get("content-type", "")
                    .lower()
                    .startswith("application/json")
                ):
                    raise ValueError("content type")
                data = bytearray()
                for block in response.iter_bytes(chunk_size=4096):
                    if (
                        time.monotonic() - started > 45
                        or len(data) + len(block) > max_bytes
                    ):
                        raise ValueError("response budget")
                    data.extend(block)
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ValueError("response schema")
                return result
    except (httpx.HTTPError, ValueError, TypeError):
        try:
            cache.add(key, 0, timeout=120)
            cache.incr(key)
        except Exception:
            pass
        raise AIUnavailable() from None
