from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from core.content_workflow import create_revision
from core.models import ContentVersion, Goal, Simulation
from core.services.attempts import create_attempt
from core.study_models import ReadingHistory, StudyProgress
from tests.test_content_workflow import approve, editorial as editorial_fixture, transition
from tests.test_practice import payload
from tests.test_question_editorial import published, question_setup as question_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def editorial():
    values = editorial_fixture.__wrapped__()
    approved = approve(values)
    transition(values[2], approved, "published")
    values[3].refresh_from_db()
    return (*values[:4], approved)


@pytest.fixture
def question_setup():
    return question_fixture.__wrapped__()


def progress(content, version, expected=0, percent=100):
    return {"target_kind": "content", "target_id": str(content.pk), "content_version": str(version.pk), "percent": percent, "position": 0, "expected_version": expected}


def test_reading_version_owned_history_and_new_publication(editorial, student, other_student, client_for):
    author, reviewer, publisher, content, old = editorial
    client = client_for(student)
    path = f"/api/study/reading/{content.pk}/"
    assert client.get(path).json()["progress"]["percent"] == 0
    assert client.put("/api/study/progress/", progress(content, old), format="json").status_code == 200
    assert client.get(path).json()["progress"]["percent"] == 100
    assert client_for(other_student).get(path).json()["progress"]["percent"] == 0
    assert client.get("/api/study/dashboard/").json()["metrics"]["completed_contents"] == 1
    draft = create_revision(actor=author, content_id=content.pk, values={"title": "Revisão", "body": "Nova publicação", "source_url": "https://example.invalid/new", "source_hash": "b" * 64})
    transition(author, draft, "review")
    new = transition(reviewer, draft, "approved", legal_status="current")
    transition(publisher, new, "published")
    state = client.get(path).json()["progress"]
    assert state["needs_review"] and state["percent"] == 0 and state["previous_percent"] == 100
    assert client.get("/api/study/dashboard/").json()["metrics"]["completed_contents"] == 0
    assert client.put("/api/study/progress/", progress(content, old, 1), format="json").status_code == 409
    assert client.put("/api/study/progress/", progress(content, new, 1, 35), format="json").status_code == 200
    assert ReadingHistory.objects.get().content_version_id == old.pk
    assert ReadingHistory.objects.get().percent == 100
    assert client.get(path).json()["history"][0]["percent"] == 100
    assert client_for(other_student).get(path).json()["history"] == []
    assert client.put("/api/study/progress/", progress(content, new, 1, 90), format="json").status_code == 409
    assert StudyProgress.objects.get().percent == 35


def test_legacy_progress_does_not_claim_publication_and_cannot_downgrade(editorial, student, client_for):
    content, version = editorial[3:]
    client = client_for(student)
    data = progress(content, version)
    data.pop("content_version")
    assert client.put("/api/study/progress/", data, format="json").status_code == 200
    assert client.get(f"/api/study/reading/{content.pk}/").json()["progress"]["needs_review"]
    assert client.put("/api/study/progress/", progress(content, version, 1), format="json").status_code == 200
    assert client.put("/api/study/progress/", data | {"expected_version": 2}, format="json").status_code == 409
    assert not ReadingHistory.objects.exists()


@pytest.mark.parametrize("field,value", [("title", "Adulterado"), ("current_legal_situation", "Adulterado"), ("exam_date_situation", "Adulterado"), ("changes_summary", "Adulterado"), ("version_number", 42)])
def test_approved_payload_is_verified_everywhere(editorial, student, client_for, field, value):
    content, version = editorial[3:]
    ContentVersion.objects.filter(pk=version.pk).update(**{field: value})
    client = client_for(student)
    for path in ["/api/contents/", f"/api/study/reading/{content.pk}/", "/api/study/dashboard/"]:
        assert client.get(path).status_code == 403, path
    assert client.put("/api/study/progress/", progress(content, version), format="json").status_code == 403
    assert not StudyProgress.objects.exists()


def test_hidden_publication_search_and_invalid_filters(editorial, student, client_for):
    client = client_for(student)
    content = editorial[3]
    assert client.get(f"/api/contents/?subject={content.subject_id}&q=Aula").json()["count"] == 1
    assert client.get("/api/contents/?q=nonexistent").json()["count"] == 0
    assert client.get("/api/contents/?subject=broken").status_code == 400
    assert client.get("/api/study/dashboard/?days=100000").status_code == 400
    transition(editorial[2], editorial[4], "archived")
    assert client.get(f"/api/study/reading/{content.pk}/").status_code == 404
    assert client.get("/api/contents/").json()["count"] == 0


def test_dashboard_real_metrics_owned_and_period_bounded(question_setup, student, other_student, client_for):
    workflow = published(question_setup)
    client = client_for(student)
    for correct in [True, False, False, False, False]:
        assert client.post("/api/practice/answers/", payload(workflow, correct), format="json").status_code == 200
    data = client.get("/api/study/dashboard/?days=30").json()
    assert data["metrics"]["answered"] == 5 and data["metrics"]["correct"] == 1
    assert data["metrics"]["accuracy"] == 20
    assert len(data["metrics"]["daily"]) == 30
    assert sum(day["answered"] for day in data["metrics"]["daily"]) == 5
    assert data["metrics"]["submitted_simulations"] == 0
    assert data["metrics"]["study_streak_in_period"] == 1
    assert data["next_step"]["href"] == f"/questoes?subject={workflow.version.question.subject_id}&mode=wrong"
    other = client_for(other_student).get("/api/study/dashboard/").json()
    assert other["metrics"]["answered"] == 0 and not other["metrics"]["subjects"]
    Goal.objects.create(owner=student, title="Meta com prazo", target_date=timezone.localdate() - timedelta(days=1))
    assert client.get("/api/study/dashboard/").json()["next_step"]["kind"] == "goal"


def test_formal_dashboard_hides_metrics_and_resumes_formal(question_setup, student, other_student, client_for):
    workflow = published(question_setup)
    fields = {"owner": student, "exam_phase": question_setup["phase"], "title": "Simulado", "question_ids": [str(workflow.version.question_id)], "duration_minutes": 60}
    create_attempt(owner=student, simulation=Simulation.objects.create(mode="training", **fields))
    formal = create_attempt(owner=student, simulation=Simulation.objects.create(mode="formal", **fields))
    data = client_for(student).get("/api/study/dashboard/").json()
    assert data["formal_active"] and data["metrics"] is None
    assert data["next_step"]["href"] == f"/simulados?tentativa={formal.pk}"
    assert client_for(other_student).get("/api/study/dashboard/").json()["formal_active"] is False


def test_reading_auth_and_identity_forgery(editorial, student, other_student, client_for, client):
    content, version = editorial[3:]
    assert client.get("/api/study/dashboard/").status_code in [401, 403]
    assert client_for(student).put("/api/study/progress/", progress(content, version) | {"owner": str(other_student.pk)}, format="json").status_code == 400
    assert client_for(student).get(f"/api/study/reading/{uuid4()}/").status_code == 404
