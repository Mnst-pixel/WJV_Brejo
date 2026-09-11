from datetime import timedelta
from smtplib import SMTPException
from uuid import uuid4
from unittest.mock import patch

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from core.account_commands import change_account
from core.models import AuditLog, Role, User, UserRole, UserSession
from core.exceptions import Conflict

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_recovery_limits():
    cache.clear()
    yield
    cache.clear()


def principal(role):
    user = User.objects.create_user(username=uuid4().hex, mfa_enabled=True)
    UserRole.objects.create(user=user, role=Role.objects.get(slug=role))
    return user


@pytest.fixture
def administrator():
    return principal("administrador")


def login(client_for, user):
    client = client_for(user)
    session = client.session
    session["mfa_verified"] = True
    session.save()
    return client


def values(**extra):
    return {"display_name": "Pessoa de teste", "username": "nova-pessoa", "email": "pessoa@example.invalid", "justification": "Cadastro solicitado para teste isolado", **extra}


def test_create_account_is_student_without_password_or_secret(administrator, client_for, settings):
    settings.SMTP_URL = ""
    client = login(client_for, administrator)
    response = client.post("/admin/editorial/usuarios/novo/", values())
    assert response.status_code == 302
    user = User.objects.get(username="nova-pessoa")
    assert list(user.role_assignments.values_list("role__slug", flat=True)) == ["aluno"]
    assert not user.has_usable_password() and not user.is_staff and not user.is_superuser
    page = client.get(response.url)
    assert page.status_code == 200 and "MFA não ativado" in page.content.decode()
    assert user.password not in page.content.decode()
    result = client.post(response.url, {"action": "access", "expected_version": 1, "justification": "Solicitar primeiro acesso à conta"}, follow=True)
    assert "serviço de e-mail ainda não foi configurado" in result.content.decode()
    assert AuditLog.objects.filter(action="admin.user.created").count() == 1


@pytest.mark.parametrize("role", ["aluno", "editor", "suporte", "revisor-juridico", "conta-de-servico"])
def test_unauthorized_roles_cannot_create_or_change_accounts(role, student, client_for):
    client = login(client_for, principal(role))
    for path in ["/admin/editorial/usuarios/novo/", f"/admin/editorial/usuarios/{student.pk}/editar/", f"/admin/editorial/usuarios/{student.pk}/papeis/"]:
        assert client.post(path, values()).status_code == 403
    assert not User.objects.filter(username="nova-pessoa").exists()


def test_support_reads_only_account_metadata_and_own_navigation(student, client_for):
    client = login(client_for, principal("suporte"))
    assert client.get("/admin/editorial/").status_code == 200
    response = client.get(f"/admin/editorial/usuarios/{student.pk}/")
    assert response.status_code == 200
    assert "Aplicar ação de acesso" not in response.content.decode()
    assert "Atividade administrativa recente" not in response.content.decode()
    assert client.get("/admin/editorial/conteudos/").status_code == 403


def test_profile_revocation_roles_and_concurrency(administrator, student, client_for):
    client = login(client_for, administrator)
    student_client = client_for(student)
    session = UserSession.objects.create(user=student, session_key_hash="a" * 64, expires_at=timezone.now() + timedelta(days=1))
    path = f"/admin/editorial/usuarios/{student.pk}/"
    assert client.post(path + "editar/", {"display_name": "Nome atualizado", "email": "novo@example.invalid", "expected_version": 1, "justification": "Correção cadastral autorizada"}).status_code == 302
    student.refresh_from_db()
    assert student.session_version == 2 and student.display_name == "Nome atualizado"
    session.refresh_from_db()
    assert session.revoked_at and student_client.get("/api/auth/me").status_code in [401, 403]
    data = {"roles": ["editor"], "expected_version": 2, "justification": "Autorizada função editorial limitada"}
    assert client.post(path + "papeis/", data).status_code == 302
    assert client.post(path + "papeis/", data).status_code == 409
    student.refresh_from_db()
    assert student.session_version == 3 and list(student.role_assignments.values_list("role__slug", flat=True)) == ["editor"]


def test_disable_enable_and_self_protection(administrator, student, client_for):
    client = login(client_for, administrator)
    path = f"/admin/editorial/usuarios/{student.pk}/"
    for version, action in [(1, "disable"), (2, "enable"), (3, "revoke")]:
        assert client.post(path, {"action": action, "expected_version": version, "justification": "Alteração administrativa de teste"}).status_code == 302
    student.refresh_from_db()
    assert student.is_active and student.session_version == 4
    assert client.post(f"/admin/editorial/usuarios/{administrator.pk}/", {"action": "disable", "expected_version": 1, "justification": "Não pode alterar próprio acesso"}).status_code == 403


def test_privileged_expired_or_inactive_account_is_protected(administrator, client_for):
    target = principal("superadministrador")
    target.is_active = False
    target.save()
    target.role_assignments.update(expires_at=timezone.now() - timedelta(days=1))
    client = login(client_for, administrator)
    path = f"/admin/editorial/usuarios/{target.pk}/"
    assert client.get(path).status_code == 200
    assert client.post(path, {"action": "enable", "expected_version": 1, "justification": "Tentativa sem autoridade suficiente"}).status_code == 403
    assert client.post(path + "papeis/", {"roles": ["aluno"], "expected_version": 1, "justification": "Tentativa de trocar papel protegido"}).status_code == 403


def test_email_uniqueness_is_case_insensitive_and_blank_compatible(student, other_student, client_for):
    student.email = "Teste@Example.Invalid"
    student.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        other_student.email = "teste@example.invalid"
        other_student.save()
    assert client_for(other_student).patch("/api/auth/me", {"email": "TESTE@example.invalid"}, format="json").status_code == 400
    assert User.objects.filter(email="").exists()


def test_stale_authority_cannot_save_account(administrator, student):
    request = RequestFactory().post("/admin/editorial/usuarios/")
    request.user = administrator
    request.session = {"mfa_verified": True, "user_session_version": 1}
    User.objects.filter(pk=administrator.pk).update(session_version=2)
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        change_account(request, user_id=student.pk, expected_version=1, action="disable", justification="Tentativa com sessão revogada")
    student.refresh_from_db()
    assert student.is_active


def test_access_email_mock_failure_and_no_secret_in_audit(administrator, student, client_for, settings):
    settings.SMTP_URL = "smtp://configured.invalid"
    student.email = "learner@example.invalid"
    student.save()
    client = login(client_for, administrator)
    path = f"/admin/editorial/usuarios/{student.pk}/"
    data = {"action": "access", "expected_version": 1, "justification": "Recuperação de acesso solicitada"}
    with patch("core.account_commands.send_mail", return_value=1) as send:
        response = client.post(path, data, follow=True)
        assert "Instruções enviadas" in response.content.decode()
        assert "token=" in send.call_args.args[1]
        assert "token=" not in response.content.decode()
    with patch("core.account_commands.send_mail", side_effect=SMTPException("synthetic-provider-secret")):
        cache.clear()  # Provider failure is a separate delivery window.
        response = client.post(path, data, follow=True)
        assert "O envio falhou" in response.content.decode()
    events = str(list(AuditLog.objects.values_list("metadata", flat=True)))
    assert "synthetic-provider-secret" not in events and "token=" not in events


def test_password_definition_works_for_invited_user_and_token_cannot_replay(client, settings):
    assert client.post("/api/auth/password-reset/confirm", {"uid": urlsafe_base64_encode(b"not-a-uuid")}, content_type="application/json").status_code == 400
    user = User.objects.create_user(username="invited", email="invite@example.invalid", password=None)
    data = {"uid": urlsafe_base64_encode(force_bytes(user.pk)), "token": default_token_generator.make_token(user), "new_password": "Strong-personal-passphrase-82828!"}
    assert client.post("/api/auth/password-reset/confirm", data, content_type="application/json").status_code == 204
    assert client.post("/api/auth/password-reset/confirm", data, content_type="application/json").status_code == 400
    user.refresh_from_db()
    assert user.check_password(data["new_password"])
    data["token"] = default_token_generator.make_token(user)
    data["new_password"] = "1"
    assert client.post("/api/auth/password-reset/confirm", data, content_type="application/json").status_code == 400
    user.is_active = False
    user.save()
    assert client.post("/api/auth/password-reset/confirm", data, content_type="application/json").status_code == 400


def test_account_mutation_rejects_stale_version(administrator, student):
    request = RequestFactory().post("/admin/editorial/usuarios/")
    request.user = administrator
    request.session = {"mfa_verified": True, "user_session_version": 1}
    with pytest.raises(Conflict):
        change_account(request, user_id=student.pk, expected_version=99, action="disable", justification="Edição concorrente precisa de revisão")


def test_role_api_requires_optimistic_version(administrator, student, client_for):
    client = login(client_for, administrator)
    path = f"/api/admin/users/{student.pk}/roles/"
    assert client.get(path).json()["version"] == 1
    data = {"roles": ["editor"], "justification": "Atualização explícita de acesso"}
    assert client.put(path, data, format="json").status_code == 400
    assert client.put(path, data | {"expected_version": 1}, format="json").json()["version"] == 2
    assert client.put(path, data | {"roles": ["aluno"], "expected_version": 1}, format="json").status_code == 409


def test_public_recovery_failure_does_not_reveal_account(client, student, settings):
    student.email = "known@example.invalid"
    student.save()
    settings.SMTP_URL = "smtp://configured.invalid"
    with patch("core.views.send_mail", side_effect=SMTPException("synthetic-provider-secret")):
        known = client.post("/api/auth/password-reset", {"email": student.email}, content_type="application/json")
        absent = client.post("/api/auth/password-reset", {"email": "absent@example.invalid"}, content_type="application/json")
    assert known.status_code == absent.status_code == 202
    assert known.json() == absent.json()
    assert "synthetic-provider-secret" not in known.content.decode()


def test_recovery_limits_delivery_and_fails_closed(client, student, settings):
    student.email = "rate@example.invalid"
    student.save()
    settings.SMTP_URL = "smtp://configured.invalid"
    with patch("core.views.send_mail", return_value=1) as send:
        for index in range(20):
            response = client.post("/api/auth/password-reset", {"email": student.email.upper() if index % 2 else student.email}, content_type="application/json")
            assert response.status_code == 202
        assert send.call_count == 1
    cache.clear()
    with patch("core.views.send_mail", return_value=1) as send, patch("core.recovery_policy.cache.add", side_effect=ConnectionError("synthetic-cache-secret")):
        response = client.post("/api/auth/password-reset", {"email": student.email}, content_type="application/json")
        assert response.status_code == 202 and "synthetic-cache-secret" not in response.content.decode()
        send.assert_not_called()


def test_recovery_ip_limit_applies_even_to_absent_addresses(client, student, settings):
    student.email = "limited@example.invalid"
    student.save()
    settings.SMTP_URL = "smtp://configured.invalid"
    for index in range(15):
        assert client.post("/api/auth/password-reset", {"email": f"absent-{index}@example.invalid"}, content_type="application/json").status_code == 202
    with patch("core.views.send_mail", return_value=1) as send:
        assert client.post("/api/auth/password-reset", {"email": student.email}, content_type="application/json").status_code == 202
        send.assert_not_called()


def test_superadmin_role_decision_removes_hidden_legacy_bypass(client_for):
    actor = principal("superadministrador")
    target = User.objects.create_superuser(username="legacy-root", password=None, mfa_enabled=True)
    client = login(client_for, actor)
    path = f"/api/admin/users/{target.pk}/roles/"
    assert client.get(path).json()["roles"] == ["superadministrador"]
    assert "legacy-root" in client.get("/admin/editorial/usuarios/?role=superadministrador").content.decode()
    page = client.get(f"/admin/editorial/usuarios/{target.pk}/papeis/")
    assert "apenas os papéis selecionados" in page.content.decode()
    result = client.put(path, {"roles": ["aluno"], "expected_version": 1, "justification": "Remover privilégio após revisão autorizada"}, format="json")
    assert result.status_code == 200
    target.refresh_from_db()
    from core.permissions import user_has_permission
    assert not target.is_superuser and not user_has_permission(target, "users.manage")
    assert user_has_permission(target, "study.use")
    assert AuditLog.objects.get(action="user.roles.changed").metadata["legacy_superuser_replaced"] is True
