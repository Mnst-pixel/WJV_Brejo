from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.test import RequestFactory
from django.utils import timezone

from core.exceptions import Conflict
from core.models import AuditLog, Role, User, UserRole
from core.subscription_workspace import save_enrollment, save_plan, save_policy, token
from core.upload_models import Enrollment, Plan, UploadPolicy

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != "postgresql", reason="Administrative decision concurrency requires isolated PostgreSQL")]


@pytest.mark.parametrize("kind", ["plan", "enrollment", "policy"])
def test_same_signed_decision_commits_only_once(kind, student):
    actor = User.objects.create_user(username="subscription-racer", mfa_enabled=True)
    UserRole.objects.create(user=actor, role=Role.objects.get(slug="administrador"), granted_by=actor)
    other = User.objects.create_user(username="subscription-other-racer", mfa_enabled=True)
    UserRole.objects.create(user=other, role=Role.objects.get(slug="administrador"), granted_by=other)
    plan = Plan.objects.create(code="race-plan", name="Concurrent plan")
    target = uuid4() if kind == "plan" else student.pk if kind == "enrollment" else "global"
    def request(index):
        req = RequestFactory().post("/")
        req.user = User.objects.get(pk=(actor, other)[index].pk)
        req.session = {"mfa_verified": True, "user_session_version": req.user.session_version}
        return req
    tokens = [token(request(index), kind, target, None) for index in range(2)]
    values = {"justification": "Concurrent administrative decision.",
        "name": "New concurrent plan", "active": True, "enabled": True, "max_upload_mib": 5, "storage_quota_mib": 50,
        "creation_id": target, "plan": plan, "status": "active", "valid_from": timezone.now(), "valid_to": None}
    barrier = Barrier(2)
    def execute(index):
        close_old_connections()
        try:
            req = request(index)
            decision = {**values, "expected_state": tokens[index]}
            barrier.wait(timeout=10)
            try:
                if kind == "plan":
                    save_plan(req, None, decision)
                elif kind == "enrollment":
                    save_enrollment(req, student.pk, decision)
                else:
                    save_policy(req, decision)
                return 200
            except Conflict:
                return 409
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(execute, range(2)))
    assert sorted(results) == [200, 409]
    event = {"plan": "admin.plan.changed", "enrollment": "admin.enrollment.changed", "policy": "admin.upload_settings.changed"}[kind]
    assert AuditLog.objects.filter(action=event).count() == 1
    assert Plan.objects.count() == (2 if kind == "plan" else 1)
    assert Enrollment.objects.count() == (1 if kind == "enrollment" else 0)
    assert UploadPolicy.objects.count() == (1 if kind == "policy" else 0)
