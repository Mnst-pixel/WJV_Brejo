"""Run only with kairos.integration_test_settings and disposable services.

Example: pytest --ds=kairos.integration_test_settings tests/test_mfa_concurrency.py
The isolated PostgreSQL user needs CREATEDB for pytest's synthetic test database.
Redis DB 15 must be disposable; this module clears it between tests.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as datetime_timezone
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pyotp
import pytest
from cryptography.fernet import Fernet
from django.conf import settings as django_settings
from django.core.cache import cache
from django.db import close_old_connections, connections
from rest_framework.test import APIClient

from core.mfa import decrypt_secret, encrypt_secret
from core.models import User


_isolated_backends = (
    getattr(django_settings, "KAIROS_ISOLATED_INTEGRATION_TESTS", False)
    and django_settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    and django_settings.DATABASES["default"]["HOST"] == "kairos-test-postgres"
    and django_settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
)
pytestmark = [
    pytest.mark.skipif(not _isolated_backends, reason="Requires isolated PostgreSQL/Redis integration settings; SQLite/LocMem cannot prove concurrency"),
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture
def staff(settings):
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.KAIROS_MFA_MAX_ATTEMPTS = 5
    settings.KAIROS_MFA_WINDOW_SECONDS = 300
    settings.KAIROS_MFA_ENROLLMENT_TTL_SECONDS = 300
    cache.clear()
    password = f"Synthetic-{uuid4()}-only"
    user = User.objects.create_user(username=f"parallel-{uuid4().hex}", password=password, is_staff=True)
    yield user, password
    cache.clear()


def _concurrent_posts(clients, path, payloads):
    barrier = Barrier(len(clients))

    def request(client, payload):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return client.post(path, payload, format="json").status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(clients)) as executor:
        pending = [executor.submit(request, client, payload) for client, payload in zip(clients, payloads, strict=True)]
        return [future.result(timeout=30) for future in pending]


def _enable(user):
    secret = pyotp.random_base32()
    user.mfa_secret_encrypted = encrypt_secret(secret)
    user.mfa_enabled = True
    user.save(update_fields=["mfa_secret_encrypted", "mfa_enabled"])
    return secret


def test_concurrent_enrollment_has_only_one_winner(staff):
    user, password = staff
    original_session_version = user.session_version
    clients = [APIClient(), APIClient()]
    secrets = []
    frozen = datetime(2026, 9, 9, 12, 1, 10, tzinfo=datetime_timezone.utc)
    with patch("django.utils.timezone.now", return_value=frozen):
        for client in clients:
            response = client.post("/api/auth/login", {"username": user.username, "password": password}, format="json")
            assert response.status_code == 428
            setup = client.post("/api/auth/mfa/setup", {}, format="json")
            assert setup.status_code == 200
            secrets.append(setup.json()["secret"])
        assert clients[0].session.session_key != clients[1].session.session_key
        statuses = _concurrent_posts(clients, "/api/auth/mfa/verify", [{"totp": pyotp.TOTP(secret).at(frozen)} for secret in secrets])
        assert sorted(statuses) == [200, 403]
        winner = statuses.index(200)
        user.refresh_from_db()
        assert user.mfa_enabled
        assert user.session_version == original_session_version + 1
        assert decrypt_secret(user.mfa_secret_encrypted) == secrets[winner]
        assert clients[winner].get("/api/auth/me").status_code == 200
        assert clients[1 - winner].get("/api/auth/me").status_code == 403


def test_concurrent_login_cannot_replay_same_totp(staff):
    user, password = staff
    secret = _enable(user)
    clients = [APIClient(), APIClient()]
    frozen = datetime(2026, 9, 9, 12, 1, 10, tzinfo=datetime_timezone.utc)
    payload = {"username": user.username, "password": password, "totp": pyotp.TOTP(secret).at(frozen)}
    with patch("django.utils.timezone.now", return_value=frozen):
        statuses = _concurrent_posts(clients, "/api/auth/login", [payload.copy(), payload.copy()])
        assert sorted(statuses) == [200, 428]
        assert sum(client.get("/api/auth/me").status_code == 200 for client in clients) == 1


def test_concurrent_invalid_codes_share_exact_user_budget(staff):
    user, password = staff
    _enable(user)
    clients = [APIClient() for _ in range(8)]
    payloads = [{"username": user.username, "password": password, "totp": "invalid"} for _ in clients]
    frozen = datetime(2026, 9, 9, 12, 1, 10, tzinfo=datetime_timezone.utc)
    with patch("django.utils.timezone.now", return_value=frozen):
        statuses = _concurrent_posts(clients, "/api/auth/login", payloads)
        assert statuses.count(428) == 5
        assert statuses.count(429) == 3
        assert all(client.get("/api/auth/me").status_code == 403 for client in clients)
