"""Opt-in real HTTP/browser workflow; synthetic accounts and disposable test database only."""
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pyotp
import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache

from core.content_workflow import published_content
from core.mfa import encrypt_secret
from core.models import Role, User, UserRole

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(
    os.environ.get("KAIROS_BROWSER_TESTS") != "1", reason="Opt-in browser run requires local Node, Playwright and isolated Next.js")]


def test_editorial_browser_full_workflow(live_server, settings, tmp_path):
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
    settings.SESSION_COOKIE_SECURE = False
    settings.CSRF_COOKIE_SECURE = False
    cache.clear()
    principals = {}
    display_names = {"editor": "Autora de teste", "revisor-juridico": "Revisora de teste", "administrador-de-conteudo": "Editora de publicação", "aluno": "Aluno de teste"}
    for role in ("editor", "revisor-juridico", "administrador-de-conteudo", "aluno"):
        password = uuid4().hex + "-test-Only!"
        secret = pyotp.random_base32()
        user = User.objects.create_user(username="browser-" + uuid4().hex, password=password, display_name=display_names[role],
            mfa_enabled=role != "aluno", mfa_secret_encrypted=encrypt_secret(secret) if role != "aluno" else "")
        UserRole.objects.create(user=user, role=Role.objects.get(slug=role))
        principals[role] = {"username": user.username, "password": password, "secret": secret}
    config = {"api": live_server.url, "next": os.environ["KAIROS_E2E_NEXT_URL"], "principals": principals,
              "evidence": os.environ.get("KAIROS_BROWSER_EVIDENCE_DIR", str(tmp_path))}
    script = Path(__file__).with_name("editorial.cjs")
    completed = subprocess.run([os.environ["KAIROS_NODE_BIN"], str(script)], input=json.dumps(config),
        text=True, capture_output=True, timeout=180, check=False)
    diagnostic = completed.stdout + completed.stderr
    for principal in principals.values():
        for value in principal.values():
            diagnostic = diagnostic.replace(value, "[synthetic credential redacted]")
    assert completed.returncode == 0, diagnostic
    result = json.loads(completed.stdout)
    assert result["workflow"] == "PASS" and result["mobileOverflow"] is False
    assert result["browserErrors"] == []
    assert published_content().count() == 1
    cache.clear()
