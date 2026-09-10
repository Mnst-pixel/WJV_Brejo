from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import AuditLog, Role, Subject, User, UserRole
from core.permissions import (
    is_service_account,
    request_has_permission,
    user_has_permission,
)
from core.rbac_policy import PERMISSIONS

pytestmark = pytest.mark.django_db


def admin_request():
    actor = User.objects.create_superuser(
        username="review-admin-" + uuid4().hex[:8],
        password="Strong-test-password-123",
        mfa_enabled=True,
    )
    request = RequestFactory().post("/admin/core/user/")
    request.user = actor
    request.session = {
        "mfa_verified": True,
        "user_session_version": actor.session_version,
    }
    return actor, request


@pytest.mark.parametrize(
    "changed",
    [
        {"is_active": False},
        {"is_superuser": False},
        {"session_version": 2},
        {"mfa_enabled": False},
    ],
)
def test_revoked_actor_cannot_complete_stale_admin_profile_save(student, changed):
    actor, request = admin_request()
    original = student.display_name
    student.display_name = "Unauthorized"
    User.objects.filter(pk=actor.pk).update(**changed)
    with pytest.raises(PermissionDenied):
        admin.site._registry[User].save_model(
            request, student, SimpleNamespace(changed_data=["display_name"]), True
        )
    student.refresh_from_db()
    assert student.display_name == original
    assert student.session_version == 1
    assert not AuditLog.objects.filter(action="admin.user.profile.changed").exists()


def test_current_actor_can_change_only_profile_fields(student):
    _, request = admin_request()
    student.display_name = "Reviewed name"
    student.is_superuser = True
    admin.site._registry[User].save_model(
        request,
        student,
        SimpleNamespace(changed_data=["display_name", "is_superuser"]),
        True,
    )
    student.refresh_from_db()
    assert student.display_name == "Reviewed name"
    assert not student.is_superuser
    assert student.session_version == 2
    assert AuditLog.objects.filter(action="admin.user.profile.changed").count() == 1


def test_admin_save_requires_current_mfa_session_proof(student):
    _, request = admin_request()
    request.session["mfa_verified"] = False
    with pytest.raises(PermissionDenied):
        admin.site._registry[User].save_model(
            request, student, SimpleNamespace(changed_data=[]), True
        )


def test_generic_admin_resource_save_also_rechecks_actor():
    actor, request = admin_request()
    User.objects.filter(pk=actor.pk).update(is_active=False, session_version=2)
    subject = Subject(slug="denied-subject", name="Denied")
    with pytest.raises(PermissionDenied):
        admin.site._registry[Subject].save_model(
            request, subject, SimpleNamespace(changed_data=["name"]), False
        )
    assert not Subject.objects.filter(slug="denied-subject").exists()


@pytest.mark.parametrize("inactive", [False, True])
def test_expired_machine_identity_never_becomes_human_superadmin(inactive):
    service = User.objects.create_user(
        username="expired-machine-" + uuid4().hex[:8],
        password="Strong-test-password-123",
        is_staff=True,
        is_superuser=True,
        is_active=not inactive,
    )
    UserRole.objects.create(
        user=service,
        role=Role.objects.get(slug="conta-de-servico"),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    UserRole.objects.create(
        user=service, role=Role.objects.get(slug="superadministrador")
    )
    assert is_service_account(service)
    for permission in PERMISSIONS:
        assert not user_has_permission(service, permission)
    request = RequestFactory().get("/admin/")
    request.user = service
    request.session = {
        "mfa_verified": True,
        "user_session_version": service.session_version,
    }
    request.auth = {"principal_type": "service", "scopes": list(PERMISSIONS)}
    assert not request_has_permission(request, "mcp.query")
    assert not admin.site._registry[User].has_change_permission(request)
    response = APIClient().post(
        "/api/auth/login",
        {"username": service.username, "password": "Strong-test-password-123"},
        format="json",
    )
    assert response.status_code == 401


def test_active_machine_keeps_only_active_machine_grants():
    service = User.objects.create_user(username="active-machine", is_superuser=True)
    UserRole.objects.create(
        user=service, role=Role.objects.get(slug="conta-de-servico")
    )
    assert user_has_permission(service, "mcp.query")
    assert not user_has_permission(service, "users.manage")
