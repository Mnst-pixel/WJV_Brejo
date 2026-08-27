import pytest
from core.models import AuditLog, Goal, LoginEvent, User


@pytest.mark.django_db
def test_student_cannot_read_another_students_goal(student, other_student, client_for):
    private_goal = Goal.objects.create(owner=other_student, title="Meta privada")
    response = client_for(student).get(f"/api/goals/{private_goal.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_student_cannot_open_audit(student, client_for):
    response = client_for(student).get("/api/admin/audit/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_wrong_password_is_generic_and_audited(client):
    User.objects.create_user(username="known", password="Strong-passphrase-123")
    response = client.post("/api/auth/login", {"username": "known", "password": "wrong"}, content_type="application/json")
    assert response.status_code == 401
    assert "Credenciais inválidas" in response.json()["detail"]
    assert LoginEvent.objects.filter(username_attempted="known", outcome="failed").exists()


@pytest.mark.django_db
def test_audit_log_is_append_only(student):
    entry = AuditLog.objects.create(actor=student, action="test")
    entry.action = "tampered"
    with pytest.raises(Exception):
        entry.save()
    with pytest.raises(Exception):
        entry.delete()
