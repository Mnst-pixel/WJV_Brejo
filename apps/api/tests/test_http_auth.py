"""Authentication over real HTTP, with cookie jar and CSRF enforcement."""
from http.cookiejar import CookieJar
import json
import hashlib
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request

from cryptography.fernet import Fernet
import pyotp
import pytest
from django.core.cache import cache

from core.models import User


@pytest.mark.skipif(not os.getenv("KAIROS_TEST_ARTIFACT_MODE"), reason="Requires the built candidate image")
def test_candidate_imports_match_the_git_sources():
    from core import mfa, serializers, views
    from kairos import settings

    for module in (mfa, serializers, views, settings):
        actual = Path(module.__file__).resolve()
        relative = actual.relative_to("/app")
        expected = Path("/candidate") / relative
        assert hashlib.sha256(actual.read_bytes()).digest() == hashlib.sha256(expected.read_bytes()).digest()
    static_root = Path("/app/staticfiles")
    manifest = json.loads((static_root / "staticfiles.json").read_text())
    assert (static_root / manifest["paths"]["admin/css/base.css"]).is_file()


@pytest.mark.django_db(transaction=True)
def test_http_mfa_enrollment_and_protected_session(live_server, settings):
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
    cache.clear()
    user = User.objects.create_user(username="http-synthetic-admin", password="Synthetic-http-only-123", is_staff=True)
    browser = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(path, payload=None, token=None, origin=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-CSRFToken"] = token
        if origin:
            headers["Origin"] = origin
        call = Request(live_server.url + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with browser.open(call, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, {}

    credentials = {"username": user.username, "password": "Synthetic-http-only-123"}
    assert request("/api/auth/login", credentials)[0] == 403
    status, csrf = request("/api/auth/csrf")
    assert status == 200
    token = csrf["csrfToken"]
    assert request("/api/auth/login", credentials, token, "https://untrusted.example")[0] == 403
    assert request("/api/auth/login", credentials, token)[0] == 428
    status, pending = request("/api/auth/mfa/setup", {}, token)
    assert status == 200
    status, account = request("/api/auth/mfa/verify", {"totp": pyotp.TOTP(pending["secret"]).now()}, token)
    assert status == 200
    assert account["username"] == user.username
    assert request("/api/auth/me")[0] == 200
    cache.clear()
