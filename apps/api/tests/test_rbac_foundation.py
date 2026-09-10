from uuid import uuid4
import pytest
from django.contrib import admin
from django.test import RequestFactory
from rest_framework.test import APIRequestFactory, force_authenticate
from core.models import AuditLog, Content, Permission, Role, User, UserRole
from core.permissions import request_has_permission, user_has_permission, user_requires_mfa
from core.rbac_policy import ROLES
from core.rbac_views import UserRolesView

pytestmark = pytest.mark.django_db


def principal(slug):
    user = User.objects.create_user(username=f"{slug}-{uuid4().hex[:8]}", password="Strong-passphrase-123")
    UserRole.objects.create(user=user, role=Role.objects.get(slug=slug))
    return user


def request_for(user, mfa=True):
    request = RequestFactory().get("/admin/")
    request.user = user
    request.session = {"mfa_verified": mfa, "user_session_version": user.session_version}
    return request


def change_roles(actor, target, roles, mfa=True):
    request = APIRequestFactory().put("/api/admin/users/roles/", {"roles": roles, "justification": "Alteração autorizada de acesso"}, format="json")
    request.session = request_for(actor, mfa).session
    force_authenticate(request, user=actor)
    return UserRolesView.as_view()(request, user_id=target.pk)


@pytest.mark.parametrize("slug", list(ROLES))
def test_role_permission_ceiling(slug):
    user = principal(slug)
    for code in ("users.manage", "roles.manage", "publication.publish", "ai.consult", "corpus.read", "service.integrate", "mcp.query"):
        assert user_has_permission(user, code) == (code in ROLES[slug])
    assert not user_has_permission(user, "host.execute")


def test_admin_without_staff_still_requires_mfa():
    user = principal("administrador")
    assert user_requires_mfa(user)
    assert not request_has_permission(request_for(user, False), "users.manage")
    assert request_has_permission(request_for(user), "users.manage")
    stale = request_for(user)
    stale.session["user_session_version"] -= 1
    assert not request_has_permission(stale, "users.manage")


def test_editor_cannot_grant_self_or_publish(student):
    editor = principal("editor")
    assert change_roles(editor, editor, ["superadministrador"]).status_code == 403
    assert change_roles(editor, student, ["editor"]).status_code == 403
    assert not request_has_permission(request_for(editor), "publication.publish")
    assert {"status", "current_version"} <= set(admin.site._registry[Content].get_readonly_fields(request_for(editor)))


def test_support_cannot_read_restricted_legal_resources():
    support = principal("suporte")
    for code in ("corpus.read", "legal.review", "ai.consult", "content.read", "prompt.read", "tool.manage"):
        assert not request_has_permission(request_for(support), code)


def test_service_account_cannot_widen_own_scope():
    service = principal("conta-de-servico")
    UserRole.objects.create(user=service, role=Role.objects.get(slug="administrador"))
    Permission.objects.get(codename="roles.manage").roles.add(Role.objects.get(slug="conta-de-servico"))
    request = request_for(service)
    request.auth = {"principal_type": "service", "scopes": ["service.integrate", "roles.manage"]}
    assert request_has_permission(request, "service.integrate")
    assert not request_has_permission(request, "roles.manage")
    assert not request_has_permission(request, "ai.consult")
    request.auth = {"principal_type": "service", "scopes": []}
    assert not request_has_permission(request, "service.integrate")
    request.auth = None
    assert not request_has_permission(request, "service.integrate")


@pytest.mark.parametrize("role", ["superadministrador", "administrador", "conta-de-servico"])
def test_admin_cannot_assign_privileged_roles(student, role):
    actor = principal("administrador")
    assert change_roles(actor, student, [role]).status_code == 403
    student.refresh_from_db()
    assert student.session_version == 1


def test_admin_cannot_change_self():
    actor = principal("administrador")
    assert change_roles(actor, actor, ["aluno"]).status_code == 403


def test_grant_is_audited_revokes_sessions_and_replay_is_noop(student):
    actor = principal("administrador")
    response = change_roles(actor, student, ["editor"])
    assert response.status_code == 200
    student.refresh_from_db()
    assert student.session_version == 2
    assert user_has_permission(student, "content.edit")
    assert not user_has_permission(student, "study.use")
    assert AuditLog.objects.filter(action="user.roles.changed", target_id=str(student.pk)).count() == 1
    assert change_roles(actor, student, ["editor"]).data["changed"] is False
    student.refresh_from_db()
    assert student.session_version == 2


def test_grants_require_mfa(student):
    actor = principal("administrador")
    assert change_roles(actor, student, ["editor"], False).status_code == 403


def test_generic_admin_cannot_modify_policy_or_legal_versions():
    from core.models import ContentVersion, SourceDocumentVersion
    actor = principal("superadministrador")
    for model in (Role, Permission, UserRole, ContentVersion, SourceDocumentVersion, AuditLog):
        registry = admin.site._registry[model]
        assert registry.has_view_permission(request_for(actor))
        assert not registry.has_add_permission(request_for(actor))
        assert not registry.has_change_permission(request_for(actor))
        assert not registry.has_delete_permission(request_for(actor))


def test_superuser_unknown_permission_denied():
    actor = User.objects.create_superuser(username="root-test", password="Strong-passphrase-123")
    assert not user_has_permission(actor, "host.execute")
    assert not user_has_permission(actor, "service.integrate")
    assert not user_has_permission(actor, "mcp.query")


def test_admin_cannot_edit_privileged_or_sensitive_account_fields():
    actor = principal("administrador")
    target = principal("superadministrador")
    registry = admin.site._registry[User]
    assert not registry.has_change_permission(request_for(actor), target)
    form = registry.get_form(request_for(actor), principal("aluno"))
    assert not {"is_staff", "is_superuser", "user_permissions", "groups", "password", "mfa_enabled", "session_version"} & set(form.base_fields)


def test_django_permissions_do_not_grant_domain_access(student):
    from django.contrib.auth.models import Permission as DjangoPermission
    student.is_staff = True
    student.user_permissions.add(DjangoPermission.objects.get(codename="change_user"))
    assert not admin.site._registry[User].has_change_permission(request_for(student))

