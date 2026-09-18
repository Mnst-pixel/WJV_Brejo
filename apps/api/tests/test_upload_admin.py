"""Legacy admin bookmarks must not bypass canonical subscription decisions."""
from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from core.models import Role, User, UserRole
from core.upload_admin import PlanForm, UploadPolicyForm
from core.upload_models import Enrollment, Plan, UploadPolicy

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role", ["aluno", "editor", "suporte"])
def test_unprivileged_roles_cannot_manage_upload_settings(role, client_for):
    actor = User.objects.create_user(username=role, is_staff=True, mfa_enabled=True)
    UserRole.objects.create(user=actor, role=Role.objects.get(slug=role), granted_by=actor)
    client = client_for(actor)
    for model in (Plan, Enrollment, UploadPolicy):
        assert client.get(f"/admin/core/{model._meta.model_name}/add/").status_code == 403


def test_legacy_admin_redirects_get_and_refuses_all_writes(client_for, student):
    actor = User.objects.create_superuser(username="upload-admin", password="Synthetic-admin-test-123", mfa_enabled=True)
    client = client_for(actor)
    plan = Plan.objects.create(code="basic", name="Básico")
    enrollment = Enrollment.objects.create(owner=student, plan=plan)
    policy = UploadPolicy.objects.create()
    routes = [(plan, "/admin/editorial/assinaturas/planos/novo/", f"/admin/editorial/assinaturas/planos/{plan.pk}/"),
        (enrollment, "/admin/editorial/usuarios/", f"/admin/editorial/assinaturas/usuarios/{student.pk}/"),
        (policy, "/admin/editorial/configuracoes/arquivos/", "/admin/editorial/configuracoes/arquivos/")]
    for obj, add_target, change_target in routes:
        base = f"/admin/core/{obj._meta.model_name}/"
        for suffix, destination in [("", "/admin/editorial/assinaturas/"), ("add/", add_target), (f"{obj.pk}/change/", change_target)]:
            response = client.get(base + suffix)
            assert response.status_code == 302 and response.url == destination
            assert client.post(base + suffix, {"name": "forged", "owner": actor.pk, "plan": plan.pk}).status_code == 403
        assert client.get(base + "invalid-identifier/change/").status_code == 404
    assert Plan.objects.get().name == "Básico"
    assert Enrollment.objects.count() == 1
    assert UploadPolicy.objects.get().enabled


@pytest.mark.parametrize("target_role", ["superadministrador", "conta-de-servico", "self"])
def test_legacy_enrollment_cannot_bypass_protected_target(client_for, target_role):
    actor = User.objects.create_user(username="legacy-operator", is_staff=True, mfa_enabled=True)
    UserRole.objects.create(user=actor, role=Role.objects.get(slug="administrador"), granted_by=actor)
    target = actor if target_role == "self" else User.objects.create_user(username="protected")
    if target != actor:
        UserRole.objects.create(user=target, role=Role.objects.get(slug=target_role), granted_by=actor)
    plan = Plan.objects.create(code="protected", name="Protected")
    response = client_for(actor).post("/admin/core/enrollment/add/", {"owner": target.pk, "plan": plan.pk, "status": "active", "valid_from_0": "2026-01-01", "valid_from_1": "09:00:00", "_save": "Save"})
    assert response.status_code == 403
    assert not Enrollment.objects.exists()
    request = RequestFactory().post("/admin/")
    request.user = actor
    with pytest.raises(PermissionDenied):
        admin.site._registry[Enrollment].save_model(request, Enrollment(owner=target, plan=plan), SimpleNamespace(changed_data=["owner", "plan"]), False)


@pytest.mark.parametrize("maximum,quota", [(26, 50), (5, 4), (5, 2**64)])
def test_forms_refuse_unsafe_and_overflow_limits(maximum, quota):
    for cls, extra in [(PlanForm, {"code": "bad", "name": "Bad"}), (UploadPolicyForm, {"enabled": True})]:
        form = cls(data={**extra, "max_upload_mib": maximum, "storage_quota_mib": quota})
        assert not form.is_valid()
    assert not Plan.objects.exists() and not UploadPolicy.objects.exists()
