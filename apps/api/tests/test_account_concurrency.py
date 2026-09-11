from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.db import close_old_connections, connection
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIRequestFactory
from django.test import RequestFactory
from django.core.cache import cache

from core.models import AuditLog
from core.views import PasswordResetConfirmView
from core.recovery_policy import allow_recovery_delivery

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != "postgresql", reason="Recovery replay concurrency requires isolated PostgreSQL")]


def test_same_recovery_token_only_sets_password_once(student):
    barrier = Barrier(2)
    payload = {"uid": urlsafe_base64_encode(force_bytes(student.pk)), "token": default_token_generator.make_token(student)}
    def reset(password):
        close_old_connections()
        try:
            request = APIRequestFactory().post("/api/auth/password-reset/confirm", {**payload, "new_password": password}, format="json")
            barrier.wait(timeout=10)
            return PasswordResetConfirmView.as_view()(request).status_code
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(reset, ["Unique-personal-passphrase-a928!", "Unique-personal-passphrase-b783!"]))
    assert sorted(result) == [204, 400]
    student.refresh_from_db()
    assert student.session_version == 2
    assert AuditLog.objects.filter(action="auth.password_reset.completed").count() == 1


def test_same_recipient_is_limited_across_concurrent_addresses(settings):
    if "redis" not in settings.CACHES["default"]["BACKEND"].lower():
        pytest.skip("Shared delivery limits require isolated Redis")
    cache.clear()
    barrier = Barrier(8)
    def request(index):
        request = RequestFactory().post("/api/auth/password-reset", REMOTE_ADDR=f"192.0.2.{index + 1}")
        barrier.wait(timeout=10)
        return allow_recovery_delivery(request, "synthetic-rate@example.invalid")
    with ThreadPoolExecutor(max_workers=8) as executor:
        result = list(executor.map(request, range(8)))
    assert sum(result) == 1
    cache.clear()
