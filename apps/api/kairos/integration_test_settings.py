"""Synthetic tests only: isolated PostgreSQL/Redis, never production endpoints."""

import os
import secrets
from urllib.parse import quote

from django.core.exceptions import ImproperlyConfigured

from kairos.test_settings import *  # noqa: F403,F401


def _test_setting(name, default=None):
    value = os.environ.get(f"KAIROS_TEST_{name}", default)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f"KAIROS_TEST_{name} is required for isolated integration tests")
    return value


def _fixed_target(name, expected):
    value = _test_setting(name, expected)
    if value != expected:
        raise ImproperlyConfigured(f"KAIROS_TEST_{name} must target the isolated test service")
    return value


def _port(name, default):
    value = _test_setting(name, default)
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ImproperlyConfigured(f"KAIROS_TEST_{name} must be a valid port")
    return value


KAIROS_ISOLATED_INTEGRATION_TESTS = True
SECRET_KEY = os.environ.get("KAIROS_TEST_SECRET_KEY") or secrets.token_urlsafe(48)
ALLOWED_HOSTS = ["testserver"]
CSRF_TRUSTED_ORIGINS = []
CORS_ALLOWED_ORIGINS = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _fixed_target("POSTGRES_DB", "kairos_test"),
        "USER": _fixed_target("POSTGRES_USER", "kairos_test"),
        "PASSWORD": _test_setting("POSTGRES_PASSWORD"),
        "HOST": _fixed_target("POSTGRES_HOST", "kairos-test-postgres"),
        "PORT": _port("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "sslmode": "disable",
            "connect_timeout": 5,
            "options": "-c statement_timeout=15000 -c lock_timeout=10000",
        },
        "TEST": {"NAME": "kairos_test_transactions"},
    }
}

_redis_host = _fixed_target("REDIS_HOST", "kairos-test-redis")
_redis_port = _port("REDIS_PORT", "6379")
_redis_password = quote(_test_setting("REDIS_PASSWORD"), safe="")
REDIS_URL = f"redis://:{_redis_password}@{_redis_host}:{_redis_port}/15"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": f"kairos-test:{secrets.token_hex(12)}",
        "OPTIONS": {"socket_connect_timeout": 5, "socket_timeout": 5, "serializer": "core.cache_serialization.StrictJSONSerializer"},
    }
}

# Keep all other test effects in-process even if the shell has live env vars.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SMTP_URL = ""
MFA_ENCRYPTION_KEY = ""  # Every concurrency test generates its own ephemeral key.
