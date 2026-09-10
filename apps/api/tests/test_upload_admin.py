import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from datetime import timedelta
from types import SimpleNamespace

from core.models import Role, User, UserRole
from core.upload_admin import PlanForm, UploadPolicyForm
from core.upload_models import Enrollment, Plan, UploadPolicy

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role", ["aluno", "editor", "suporte"])
def test_unprivileged_roles_cannot_manage_upload_settings(role, client_for):
    actor = User.objects.create_user(
        username=role,
        password="Synthetic-admin-test-123",
        is_staff=True,
        mfa_enabled=True,
    )
    UserRole.objects.create(
        user=actor, role=Role.objects.get(slug=role), granted_by=actor
    )
    client = client_for(actor)
    for model in (Plan, Enrollment, UploadPolicy):
        assert (
            client.get(f"/admin/core/{model._meta.model_name}/add/").status_code == 403
        )


def test_admin_can_configure_quota_using_plain_form(client_for):
    actor = User.objects.create_superuser(
        username="upload-admin", password="Synthetic-admin-test-123", mfa_enabled=True
    )
    client = client_for(actor)
    response = client.post(
        "/admin/core/plan/add/",
        {
            "code": "basic",
            "name": "Básico",
            "active": "on",
            "max_upload_mib": "5",
            "storage_quota_mib": "50",
            "_save": "Salvar",
        },
    )
    assert response.status_code == 302
    plan = Plan.objects.get(code="basic")
    assert (plan.max_upload_bytes, plan.storage_quota_bytes) == (
        5 * 1024**2,
        50 * 1024**2,
    )
    response = client.post(
        "/admin/core/uploadpolicy/add/",
        {
            "enabled": "on",
            "max_upload_mib": "10",
            "storage_quota_mib": "100",
            "_save": "Salvar",
        },
    )
    assert response.status_code == 302
    assert UploadPolicy.objects.get().max_upload_bytes == 10 * 1024**2
    request = RequestFactory().get("/")
    request.user = actor
    request.session = {
        "mfa_verified": True,
        "user_session_version": actor.session_version,
    }
    assert not admin.site._registry[UploadPolicy].has_add_permission(request)


def test_forms_refuse_quota_smaller_than_file_and_unsafe_maximum():
    form = PlanForm(
        data={
            "code": "bad",
            "name": "Bad",
            "max_upload_mib": 26,
            "storage_quota_mib": 50,
        }
    )
    assert not form.is_valid()
    form = UploadPolicyForm(
        data={"enabled": True, "max_upload_mib": 5, "storage_quota_mib": 4}
    )
    assert not form.is_valid()


def admin_request():
    actor = User.objects.create_superuser(
        username="quota-reviewer", password="Synthetic-admin-test-123", mfa_enabled=True
    )
    request = RequestFactory().post("/admin/")
    request.user = actor
    request.session = {
        "mfa_verified": True,
        "user_session_version": actor.session_version,
    }
    return actor, request


def test_overflow_quota_rejected_as_form_error_before_database_write():
    form = PlanForm(
        data={
            "code": "overflow",
            "name": "Overflow",
            "max_upload_mib": 5,
            "storage_quota_mib": 2**64,
        }
    )
    assert not form.is_valid()
    assert "storage_quota_mib" in form.errors
    assert not Plan.objects.filter(code="overflow").exists()


def test_stale_plan_name_edit_cannot_reactivate_plan():
    _, request = admin_request()
    plan = Plan.objects.create(code="test-plan", name="Original")
    form = PlanForm(
        instance=plan,
        data={
            "code": plan.code,
            "name": "Reviewed",
            "active": True,
            "max_upload_mib": 25,
            "storage_quota_mib": 250,
        },
    )
    assert form.is_valid()
    Plan.objects.filter(pk=plan.pk).update(active=False)
    admin.site._registry[Plan].save_model(request, form.save(commit=False), form, True)
    plan.refresh_from_db()
    assert not plan.active
    assert plan.name == "Reviewed"


def test_stale_quota_form_cannot_enable_globally_disabled_uploads():
    _, request = admin_request()
    policy = UploadPolicy.objects.create()
    form = UploadPolicyForm(
        instance=policy,
        data={"enabled": True, "max_upload_mib": 25, "storage_quota_mib": 300},
    )
    assert form.is_valid()
    UploadPolicy.objects.filter(pk=policy.pk).update(enabled=False)
    admin.site._registry[UploadPolicy].save_model(
        request, form.save(commit=False), form, True
    )
    policy.refresh_from_db()
    assert not policy.enabled
    assert policy.default_storage_quota_bytes == 300 * 1024**2


def test_second_singleton_creation_does_not_overwrite_current_limits():
    _, request = admin_request()
    form = UploadPolicyForm(
        data={"enabled": True, "max_upload_mib": 5, "storage_quota_mib": 50}
    )
    assert form.is_valid()
    UploadPolicy.objects.create(enabled=False)
    with pytest.raises(PermissionDenied):
        admin.site._registry[UploadPolicy].save_model(
            request, form.save(commit=False), form, False
        )
    assert not UploadPolicy.objects.get().enabled


def test_enrollment_owner_is_immutable_and_duplicate_creation_refused(
    student, other_student
):
    _, request = admin_request()
    plan = Plan.objects.create(code="enrollment", name="Matrícula")
    enrollment = Enrollment.objects.create(owner=student, plan=plan)
    enrollment.owner = other_student
    with pytest.raises(PermissionDenied):
        admin.site._registry[Enrollment].save_model(
            request, enrollment, SimpleNamespace(changed_data=["owner"]), True
        )
    enrollment.refresh_from_db()
    assert enrollment.owner_id == student.pk
    duplicate = Enrollment(owner=student, plan=plan)
    with pytest.raises(PermissionDenied):
        admin.site._registry[Enrollment].save_model(
            request, duplicate, SimpleNamespace(changed_data=["owner", "plan"]), False
        )
    assert Enrollment.objects.filter(owner=student).count() == 1


def test_enrollment_stale_plan_change_preserves_suspension(student):
    _, request = admin_request()
    original = Plan.objects.create(code="original", name="Original")
    successor = Plan.objects.create(code="successor", name="Successor")
    enrollment = Enrollment.objects.create(owner=student, plan=original)
    Enrollment.objects.filter(pk=enrollment.pk).update(status="suspended")
    enrollment.plan = successor
    admin.site._registry[Enrollment].save_model(
        request, enrollment, SimpleNamespace(changed_data=["plan"]), True
    )
    enrollment.refresh_from_db()
    assert enrollment.status == "suspended"
    assert enrollment.plan == successor


def test_enrollment_form_invalid_interval_is_visible_validation_error(student):
    _, request = admin_request()
    plan = Plan.objects.create(code="dates", name="Dates")
    form_class = admin.site._registry[Enrollment].get_form(request)
    now = timezone.now()
    form = form_class(
        data={
            "owner": student.pk,
            "plan": plan.pk,
            "status": "active",
            "valid_from_0": now.strftime("%Y-%m-%d"),
            "valid_from_1": now.strftime("%H:%M:%S"),
            "valid_to_0": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "valid_to_1": now.strftime("%H:%M:%S"),
        }
    )
    assert not form.is_valid()
    assert set(form.errors) == {"__all__"}


def test_upload_settings_save_rechecks_actor_revocation():
    actor, request = admin_request()
    form = PlanForm(
        data={
            "code": "revoked",
            "name": "Revoked",
            "active": True,
            "max_upload_mib": 5,
            "storage_quota_mib": 50,
        }
    )
    assert form.is_valid()
    User.objects.filter(pk=actor.pk).update(session_version=actor.session_version + 1)
    with pytest.raises(PermissionDenied):
        admin.site._registry[Plan].save_model(
            request, form.save(commit=False), form, False
        )
    assert not Plan.objects.filter(code="revoked").exists()
