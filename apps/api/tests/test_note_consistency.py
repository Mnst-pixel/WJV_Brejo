import pytest
from core.models import StudyNote

pytestmark = pytest.mark.django_db


def test_note_rejects_stale_editor_without_losing_content(student, other_student, client_for):
    note = StudyNote.objects.create(owner=student, title="Original", body="Preserve")
    url = f"/api/notes/{note.pk}/"
    client = client_for(student)
    assert client.patch(url, {"body": "First", "expected_version": 1}, format="json").status_code == 200
    assert client.patch(url, {"body": "Stale", "expected_version": 1}, format="json").status_code == 409
    assert client.patch(url, {"body": "Missing"}, format="json").status_code == 409
    assert client_for(other_student).patch(url, {"body": "Foreign", "expected_version": 2}, format="json").status_code == 404
    note.refresh_from_db()
    assert note.body == "First" and note.version == 2


def test_goal_percentage_invalid_returns_validation_error(student, client_for):
    response = client_for(student).post("/api/goals/", {"title": "Synthetic", "progress": 101}, format="json")
    assert response.status_code == 400
