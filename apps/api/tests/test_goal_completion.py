from types import SimpleNamespace

import pytest
from django.utils import timezone
from core.models import Goal
from core.serializers import GoalSerializer

pytestmark = pytest.mark.django_db


def test_goal_completion_follows_progress_and_reopens(student, client_for):
    client = client_for(student)
    created = client.post("/api/goals/", {"title": "Concluir revisão", "progress": 0}, format="json")
    assert created.status_code == 201 and created.data["completed_at"] is None
    url = f"/api/goals/{created.data['id']}/"
    completed = client.patch(url, {"progress": 100}, format="json")
    assert completed.status_code == 200 and completed.data["completed_at"]
    timestamp = completed.data["completed_at"]
    replay = client.patch(url, {"progress": 100, "title": "Revisão concluída"}, format="json")
    assert replay.data["completed_at"] == timestamp
    reopened = client.patch(url, {"progress": 40}, format="json")
    assert reopened.status_code == 200 and reopened.data["completed_at"] is None
    assert client.patch(url, {"completed_at": timezone.now().isoformat()}, format="json").status_code == 400


def test_goal_created_at_complete_gets_server_timestamp(student, client_for):
    response = client_for(student).post("/api/goals/", {"title": "Meta já concluída", "progress": 100}, format="json")
    assert response.status_code == 201 and response.data["completed_at"]
    assert Goal.objects.get().completed_at is not None


def test_stale_goal_metadata_edit_preserves_newer_completion(student):
    stale = Goal.objects.create(owner=student, title="Meta")
    completed_at = timezone.now()
    Goal.objects.filter(pk=stale.pk).update(progress=100, completed_at=completed_at)
    serializer = GoalSerializer(stale, data={"title": "Título atualizado"}, partial=True, context={"request": SimpleNamespace(user=student)})
    assert serializer.is_valid(), serializer.errors
    result = serializer.save()
    assert result.progress == 100 and result.completed_at == completed_at


def test_other_user_cannot_complete_goal(student, other_student, client_for):
    goal = Goal.objects.create(owner=student, title="Meta privada")
    response = client_for(other_student).patch(f"/api/goals/{goal.pk}/", {"progress": 100}, format="json")
    assert response.status_code == 404
    goal.refresh_from_db()
    assert goal.progress == 0 and goal.completed_at is None
