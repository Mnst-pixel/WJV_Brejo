from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied as APIForbidden

from core.models import AuditLog, FileAsset, Role, User, UserRole
from core.services.uploads import limits
from core.subscription_workspace import MIB, save_plan, token
from core.upload_models import Enrollment, Plan, UploadPolicy

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(client_for):
    actor = User.objects.create_user(username="plan-operator", password="Synthetic-operator-123", mfa_enabled=True)
    UserRole.objects.create(user=actor, role=Role.objects.get(slug="administrador"), granted_by=actor)
    client = client_for(actor)
    session = client.session
    session["mfa_verified"] = True
    session.save()
    return SimpleNamespace(user=actor, client=client)


def data_from(response, **values):
    form = response.context["form"]
    data = {name: field.value() for name, field in ((name, form[name]) for name in form.fields) if form.fields[name].widget.is_hidden}
    return {**data, "justification": "Decisão sintética para configurar o plano.", **values}


def create_plan(operator):
    url = reverse("editorial:plan-create")
    data = data_from(operator.client.get(url), name="Preparação OAB", active="on", max_upload_mib=5, storage_quota_mib=50)
    assert operator.client.post(url, data).status_code == 302
    return Plan.objects.get(name="Preparação OAB"), data


@pytest.mark.parametrize("role", ["aluno", "editor", "suporte", "administrador-de-conteudo", "conta-de-servico"])
def test_role_denied_for_all_subscription_routes(role, client_for, student):
    actor = User.objects.create_user(username="denied-" + role, mfa_enabled=True, is_staff=True)
    UserRole.objects.create(user=actor, role=Role.objects.get(slug=role), granted_by=actor)
    client = client_for(actor)
    plan = Plan.objects.create(code="one", name="One")
    urls = [reverse("editorial:subscriptions"), reverse("editorial:plan-create"), reverse("editorial:plan-edit", args=[plan.pk]), reverse("editorial:enrollment", args=[student.pk]), reverse("editorial:upload-policy")]
    for url in urls:
        assert client.get(url).status_code == 403
        assert client.post(url, {"name": "forged"}).status_code == 403


def test_plan_form_hides_code_and_replay_cannot_duplicate(operator):
    plan, data = create_plan(operator)
    assert not operator.user.is_staff
    assert plan.max_upload_bytes == 5 * MIB
    assert plan.storage_quota_bytes == 50 * MIB
    assert operator.client.post(reverse("editorial:plan-create"), data).status_code == 409
    assert Plan.objects.count() == 1
    response = operator.client.get(reverse("editorial:plan-edit", args=[plan.pk]))
    assert "code" not in response.context["form"].fields
    assert "expected_state" in response.context["form"].fields
    assert AuditLog.objects.filter(action="admin.plan.changed").count() == 1


def test_stale_and_tampered_plan_decisions_refused(operator):
    plan, _ = create_plan(operator)
    url = reverse("editorial:plan-edit", args=[plan.pk])
    data = data_from(operator.client.get(url), name="Renamed", active="on", max_upload_mib=5, storage_quota_mib=60)
    Plan.objects.filter(pk=plan.pk).update(active=False)
    assert operator.client.post(url, data).status_code == 409
    data["expected_state"] = "forged"
    assert operator.client.post(url, data).status_code == 409
    plan.refresh_from_db()
    assert not plan.active and plan.name == "Preparação OAB"


def test_unsafe_limits_invalid_before_save(operator):
    url = reverse("editorial:plan-create")
    for maximum, quota in [(26, 50), (5, 4), (5, 2**64)]:
        data = data_from(operator.client.get(url), name="Unsafe", active="on", max_upload_mib=maximum, storage_quota_mib=quota)
        response = operator.client.post(url, data)
        assert response.status_code == 200
        assert response.context["form"].errors
    assert not Plan.objects.exists()


def test_enrollment_create_edit_suspend_reactivate_and_ownership(operator, student, other_student):
    plan, _ = create_plan(operator)
    url = reverse("editorial:enrollment", args=[student.pk])
    data = data_from(operator.client.get(url), plan=plan.pk, status="active", valid_from=(timezone.now() - timedelta(days=1)).isoformat(), valid_to="", owner=other_student.pk)
    assert operator.client.post(url, data).status_code == 302
    assert operator.client.post(url, data).status_code == 409
    enrolled = Enrollment.objects.get()
    assert enrolled.owner == student and limits(student) == (5 * MIB, 50 * MIB)
    for status in ("suspended", "expired", "active"):
        data = data_from(operator.client.get(url), plan=plan.pk, status=status, valid_from=(timezone.now() - timedelta(days=1)).isoformat(), valid_to="")
        assert operator.client.post(url, data).status_code == 302
        if status == "active":
            assert limits(student) == (5 * MIB, 50 * MIB)
        else:
            with pytest.raises(APIForbidden):
                limits(student)
    assert not Enrollment.objects.filter(owner=other_student).exists()
    assert AuditLog.objects.filter(action="admin.enrollment.changed").count() == 4


def test_enrollment_dates_plan_deactivation_and_concurrent_change(operator, student):
    plan, _ = create_plan(operator)
    url = reverse("editorial:enrollment", args=[student.pk])
    now = timezone.now()
    data = data_from(operator.client.get(url), plan=plan.pk, status="active", valid_from=now.isoformat(), valid_to=(now - timedelta(days=1)).isoformat())
    response = operator.client.post(url, data)
    assert response.status_code == 200 and "valid_to" in response.context["form"].errors
    data["valid_to"] = ""
    Enrollment.objects.create(owner=student, plan=plan, status="suspended")
    assert operator.client.post(url, data).status_code == 409
    Plan.objects.filter(pk=plan.pk).update(active=False)
    assert operator.client.get(url).status_code == 200
    with pytest.raises(APIForbidden):
        limits(student)


def test_policy_disable_stale_replay_and_retained_storage(operator, student):
    asset = FileAsset.objects.create(owner=student, original_name="private.txt", mime_type="text/plain", size_bytes=6 * MIB, processing_status="ready", sha256="a" * 64)
    url = reverse("editorial:upload-policy")
    data = data_from(operator.client.get(url), enabled="on", max_upload_mib=1, storage_quota_mib=5)
    assert operator.client.post(url, data).status_code == 302
    assert operator.client.post(url, data).status_code == 409
    assert limits(student) == (MIB, 5 * MIB)
    assert FileAsset.objects.filter(pk=asset.pk, size_bytes=6 * MIB).exists()
    data = data_from(operator.client.get(url), max_upload_mib=1, storage_quota_mib=5)
    assert operator.client.post(url, data).status_code == 302
    assert not UploadPolicy.objects.get().enabled
    with pytest.raises(APIForbidden):
        limits(student)


def test_cross_account_token_and_protected_accounts(operator, student, other_student):
    plan, _ = create_plan(operator)
    url = reverse("editorial:enrollment", args=[student.pk])
    data = data_from(operator.client.get(url), plan=plan.pk, status="active", valid_from=timezone.now().isoformat(), valid_to="")
    assert operator.client.post(reverse("editorial:enrollment", args=[other_student.pk]), data).status_code == 409
    assert operator.client.get(reverse("editorial:enrollment", args=[operator.user.pk])).status_code == 403
    other_student.is_superuser = True
    other_student.save(update_fields=["is_superuser"])
    assert operator.client.get(reverse("editorial:enrollment", args=[other_student.pk])).status_code == 403
    assert not Enrollment.objects.exists()


def test_authority_revocation_rechecked_inside_command(operator):
    plan, _ = create_plan(operator)
    request = RequestFactory().post("/")
    request.user = operator.user
    request.session = {"mfa_verified": True, "user_session_version": operator.user.session_version}
    values = {"name": "Forbidden", "active": True, "max_upload_mib": 5, "storage_quota_mib": 50, "justification": "A stale administrative decision.", "expected_state": token(request, "plan", plan.pk, plan)}
    User.objects.filter(pk=operator.user.pk).update(session_version=operator.user.session_version + 1)
    with pytest.raises(PermissionDenied):
        save_plan(request, plan.pk, values)
    plan.refresh_from_db()
    assert plan.name == "Preparação OAB"


def test_list_search_no_private_file_name_and_mfa_required(operator, student):
    plan, _ = create_plan(operator)
    Enrollment.objects.create(owner=student, plan=plan)
    FileAsset.objects.create(owner=student, original_name="secret-case-name.txt", mime_type="text/plain", size_bytes=1, processing_status="ready", sha256="a" * 64)
    response = operator.client.get(reverse("editorial:subscriptions"), {"q": "Preparação"})
    assert response.status_code == 200 and response.context["page"].paginator.count == 1
    body = operator.client.get(reverse("editorial:enrollment", args=[student.pk])).content.decode()
    assert "secret-case-name" not in body
    session = operator.client.session
    session["mfa_verified"] = False
    session.save()
    assert operator.client.get(reverse("editorial:subscriptions")).status_code == 403


def test_unavailable_account_and_enrollment_actions_are_hidden(operator, student):
    plan, _ = create_plan(operator)
    Enrollment.objects.create(owner=operator.user, plan=plan)
    Enrollment.objects.create(owner=student, plan=plan)
    own = operator.client.get(reverse("editorial:account", args=[operator.user.pk])).content.decode()
    own_url = reverse("editorial:enrollment", args=[operator.user.pk])
    assert own_url not in own
    body = operator.client.get(reverse("editorial:subscriptions")).content.decode()
    assert own_url not in body
    assert reverse("editorial:enrollment", args=[student.pk]) in body
