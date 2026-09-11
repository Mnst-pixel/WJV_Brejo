"""Opt-in real HTTP/browser workflow; synthetic accounts and disposable test database only."""
import json
import os
from pathlib import Path
import subprocess
import socket
import time
from urllib.request import urlopen
from uuid import uuid4

import pyotp
import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache

from core.content_workflow import published_content
from core.mfa import encrypt_secret
from core.models import AttemptAnswer, Role, User, UserRole
from core.question_workflow import published_questions

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(
    os.environ.get("KAIROS_BROWSER_TESTS") != "1", reason="Opt-in browser run requires local Node, Playwright and isolated Next.js")]


@pytest.fixture
def next_server(live_server):
    """Bounded loopback-only server, disposed with this one test even on failure."""
    web = Path(__file__).resolve().parents[4] / "apps" / "web"
    if not (web / ".next" / "BUILD_ID").is_file():
        pytest.fail("Build the isolated Next.js candidate before the browser test.")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = os.environ | {"INTERNAL_API_URL": live_server.url, "KAIROS_DEMO_MODE": "false"}
    server = subprocess.Popen([os.environ["KAIROS_NODE_BIN"], str(web / "node_modules/next/dist/bin/next"),
        "start", "--hostname", "127.0.0.1", "--port", str(port)], cwd=web, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    origin = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if server.poll() is not None:
                pytest.fail("Isolated Next.js exited before readiness.")
            try:
                with urlopen(origin + "/app/api/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("Isolated Next.js readiness timed out.")
        yield origin
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def test_editorial_browser_full_workflow(live_server, next_server, settings, tmp_path):
    assert not live_server.thread.connections_override, "Browser HTTP threads must not share a SQLite connection."
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
    settings.SESSION_COOKIE_SECURE = False
    settings.CSRF_COOKIE_SECURE = False
    cache.clear()
    principals = {}
    settings.SMTP_URL = ""
    display_names = {"editor": "Autora de teste", "revisor-juridico": "Revisora de teste", "administrador-de-conteudo": "Editora de publicação", "aluno": "Aluno de teste", "administrador": "Administrador de teste"}
    for role in display_names:
        password = uuid4().hex + "-test-Only!"
        secret = pyotp.random_base32()
        user = User.objects.create_user(username="browser-" + uuid4().hex, password=password, display_name=display_names[role],
            mfa_enabled=role != "aluno", mfa_secret_encrypted=encrypt_secret(secret) if role != "aluno" else "")
        UserRole.objects.create(user=user, role=Role.objects.get(slug=role))
        principals[role] = {"username": user.username, "password": password, "secret": secret}
    config = {"api": live_server.url, "next": next_server, "principals": principals,
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
    assert published_questions().count() == 1
    assert AttemptAnswer.objects.filter(is_correct=True).count() == 2
    from core.study_models import StudyProgress
    assert StudyProgress.objects.get(target_kind="content").percent == 100
    assert StudyProgress.objects.get(target_kind="content").content_version_id == published_content().get().current_version_id
    from core.second_phase_models import WrittenSubmission
    written = WrittenSubmission.objects.get(status="submitted")
    assert written.responses.count() == 2 and len(written.final_hash) == 64
    assert written.responses.get(target_code="Q1").text == "Resposta discursiva que permanece na conta."
    assert result["phase2Workflow"].endswith("PASS")
    assert result["readingWorkflow"].endswith("PASS")
    assert result["accountsWorkflow"].endswith("PASS")
    assert result["subscriptionsWorkflow"].endswith("PASS")
    invited = User.objects.get(username="pessoa-nova-browser")
    assert invited.is_active and not invited.has_usable_password()
    assert list(invited.role_assignments.values_list("role__slug", flat=True)) == ["editor"]
    from core.upload_models import Enrollment, UploadPolicy
    enrollment = Enrollment.objects.get(owner=invited)
    assert enrollment.status == "suspended" and enrollment.plan.storage_quota_bytes == 50 * 1024**2
    assert UploadPolicy.objects.get().max_upload_bytes == 10 * 1024**2
    cache.clear()
