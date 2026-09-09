from datetime import timedelta
from unittest.mock import patch

import pyotp
import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from core.mfa import encrypt_secret
from core.models import User

PASSWORD = "Only-a-test-passphrase-123"


@pytest.fixture(autouse=True)
def mfa_configuration(settings):
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.KAIROS_MFA_ENROLLMENT_TTL_SECONDS = 300
    settings.KAIROS_MFA_MAX_ATTEMPTS = 5
    settings.KAIROS_MFA_WINDOW_SECONDS = 300
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def staff():
    return User.objects.create_user(username="staff-mfa", password=PASSWORD, is_staff=True)


def begin(client, staff):
    response = client.post("/api/auth/login", {"username": staff.username, "password": PASSWORD}, format="json")
    assert response.status_code == 428
    assert response.json()["mfa_setup_required"]
    response = client.post("/api/auth/mfa/setup", {}, format="json")
    assert response.status_code == 200
    return response.json()["secret"]


def enable(staff):
    secret = pyotp.random_base32()
    staff.mfa_secret_encrypted = encrypt_secret(secret)
    staff.mfa_enabled = True
    staff.save()
    return secret


@pytest.mark.django_db
def test_enrollment_secret_is_not_active_until_verified(staff):
    client = APIClient()
    secret = begin(client, staff)
    staff.refresh_from_db()
    assert not staff.mfa_enabled
    assert staff.mfa_secret_encrypted == ""
    response = client.post("/api/auth/mfa/verify", {"totp": pyotp.TOTP(secret).now()}, format="json")
    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.mfa_enabled
    assert client.get("/api/auth/me").status_code == 200
    assert client.session["mfa_verified"] is True


@pytest.mark.django_db
def test_enrollment_in_another_browser_invalidates_old_challenge(staff):
    first, second = APIClient(), APIClient()
    first_secret = begin(first, staff)
    second_secret = begin(second, staff)
    assert first_secret != second_secret
    assert second.post("/api/auth/mfa/verify", {"totp": pyotp.TOTP(second_secret).now()}, format="json").status_code == 200
    assert first.post("/api/auth/mfa/setup", {}, format="json").status_code == 403
    assert first.post("/api/auth/mfa/verify", {"totp": pyotp.TOTP(first_secret).now()}, format="json").status_code == 403
    assert first.get("/api/auth/me").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["password", "session_version", "inactive", "non_staff", "expired"])
@pytest.mark.parametrize("operation", ["setup", "verify"])
def test_stale_enrollment_is_rejected(staff, change, operation):
    client = APIClient()
    secret = begin(client, staff)
    if change == "password":
        staff.set_password("A-different-test-passphrase-456")
    elif change == "session_version":
        staff.session_version += 1
    elif change == "inactive":
        staff.is_active = False
    elif change == "non_staff":
        staff.is_staff = False
    staff.save()
    now = timezone.now() + (timedelta(minutes=6) if change == "expired" else timedelta())
    with patch("django.utils.timezone.now", return_value=now):
        response = client.post(f"/api/auth/mfa/{operation}", {"totp": pyotp.TOTP(secret).at(now)}, format="json")
    assert response.status_code == 403
    staff.refresh_from_db()
    assert not staff.mfa_enabled
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_legacy_pre_session_does_not_authorize_enrollment(staff):
    client = APIClient()
    session = client.session
    session["pre_mfa_user_id"] = str(staff.id)
    session["pre_mfa_password_at"] = timezone.now().isoformat()
    session.save()
    assert client.post("/api/auth/mfa/setup", {}, format="json").status_code == 403


@pytest.mark.django_db
def test_restarting_enrollment_replaces_pending_secret(staff):
    client = APIClient()
    old_secret = begin(client, staff)
    new_secret = begin(client, staff)
    assert old_secret != new_secret


@pytest.mark.django_db
def test_login_mfa_limit_is_per_user_across_clients_and_ips(staff, settings):
    secret = enable(staff)
    for index in range(settings.KAIROS_MFA_MAX_ATTEMPTS):
        response = APIClient().post("/api/auth/login", {"username": staff.username, "password": PASSWORD, "totp": "invalid"}, format="json", REMOTE_ADDR=f"192.0.2.{index + 1}")
        assert response.status_code == 428
    response = APIClient().post("/api/auth/login", {"username": staff.username, "password": PASSWORD, "totp": pyotp.TOTP(secret).now()}, format="json")
    assert response.status_code == 429


@pytest.mark.django_db
def test_enrollment_mfa_limit_survives_new_challenge(staff, settings):
    client = APIClient()
    begin(client, staff)
    for _ in range(settings.KAIROS_MFA_MAX_ATTEMPTS):
        assert client.post("/api/auth/mfa/verify", {"totp": "invalid"}, format="json").status_code == 400
    secret = begin(client, staff)
    assert client.post("/api/auth/mfa/verify", {"totp": pyotp.TOTP(secret).now()}, format="json").status_code == 429


@pytest.mark.django_db
def test_mfa_budget_recovers_next_window_even_if_old_counter_loses_ttl(staff, settings):
    secret = enable(staff)
    now = timezone.now()
    window = int(now.timestamp()) // settings.KAIROS_MFA_WINDOW_SECONDS
    cache.set(f"kairos:mfa:attempts:{staff.pk}:{window}", 100, timeout=None)
    credentials = {"username": staff.username, "password": PASSWORD}
    with patch("django.utils.timezone.now", return_value=now):
        assert APIClient().post("/api/auth/login", {**credentials, "totp": pyotp.TOTP(secret).at(now)}, format="json").status_code == 429
    later = now + timedelta(seconds=settings.KAIROS_MFA_WINDOW_SECONDS)
    with patch("django.utils.timezone.now", return_value=later):
        assert APIClient().post("/api/auth/login", {**credentials, "totp": pyotp.TOTP(secret).at(later)}, format="json").status_code == 200


@pytest.mark.django_db
def test_totp_cannot_be_replayed_for_another_session(staff):
    secret = enable(staff)
    credentials = {"username": staff.username, "password": PASSWORD, "totp": pyotp.TOTP(secret).now()}
    first, second = APIClient(), APIClient()
    assert first.post("/api/auth/login", credentials, format="json").status_code == 200
    assert second.post("/api/auth/login", credentials, format="json").status_code == 428
    assert "_auth_user_id" not in second.session


@pytest.mark.django_db
def test_cache_failure_cannot_grant_staff_session(staff):
    secret = enable(staff)
    with patch("django.core.cache.cache.add", side_effect=ConnectionError("cache unavailable")):
        response = APIClient().post("/api/auth/login", {"username": staff.username, "password": PASSWORD, "totp": pyotp.TOTP(secret).now()}, format="json")
    assert response.status_code == 503


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["login", "mfa/setup", "mfa/verify"])
def test_anonymous_session_writes_require_csrf(staff, endpoint):
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf").json()["csrfToken"]
    credentials = {"username": staff.username, "password": PASSWORD}
    if endpoint != "login":
        assert client.post("/api/auth/login", credentials, format="json", HTTP_X_CSRFTOKEN=token).status_code == 428
    secret = None
    if endpoint == "mfa/verify":
        response = client.post("/api/auth/mfa/setup", {}, format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == 200
        secret = response.json()["secret"]
    payload = credentials if endpoint == "login" else {"totp": pyotp.TOTP(secret).now()} if secret else {}
    assert client.post(f"/api/auth/{endpoint}", payload, format="json").status_code == 403


@pytest.mark.django_db
def test_csrf_valid_enrollment_still_works(staff):
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf").json()["csrfToken"]
    headers = {"HTTP_X_CSRFTOKEN": token}
    assert client.post("/api/auth/login", {"username": staff.username, "password": PASSWORD}, format="json", **headers).status_code == 428
    secret = client.post("/api/auth/mfa/setup", {}, format="json", **headers).json()["secret"]
    assert client.post("/api/auth/mfa/verify", {"totp": pyotp.TOTP(secret).now()}, format="json", **headers).status_code == 200


@pytest.mark.django_db
def test_untrusted_origin_rejected_even_with_csrf_token(staff):
    client = APIClient(enforce_csrf_checks=True)
    token = client.get("/api/auth/csrf").json()["csrfToken"]
    response = client.post("/api/auth/login", {"username": staff.username, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="https://untrusted.example")
    assert response.status_code == 403
