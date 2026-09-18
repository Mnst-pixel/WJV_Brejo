from uuid import uuid4

import pytest

from core.models import Alternative, Attempt, AttemptAnswer, Bookmark, Simulation, StudyMark
from core.services.attempts import create_attempt
from tests.test_question_editorial import published, question_setup as setup_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def question_setup(request):
    return setup_fixture.__wrapped__()


def payload(workflow, correct=True):
    alternatives = workflow.version.alternatives
    alternative = workflow.answer_key_version.correct_alternative if correct else alternatives.exclude(pk=workflow.answer_key_version.correct_alternative_id).first()
    return {"question": str(workflow.version.question_id), "selected_alternative": str(alternative.pk), "request_id": str(uuid4()), "elapsed_seconds": 12}


def test_practice_grade_replay_history_and_accuracy_are_owned(question_setup, student, other_student, client_for):
    workflow = published(question_setup)
    client = client_for(student)
    data = payload(workflow)
    first = client.post("/api/practice/answers/", data, format="json")
    assert first.status_code == 200, first.content
    assert first.json()["correct"] is True
    assert first.json()["legal_basis"] == "Fundamento de teste."
    assert client.post("/api/practice/answers/", data, format="json").json() == first.json()
    assert Attempt.objects.count() == AttemptAnswer.objects.count() == 1
    assert AttemptAnswer.objects.get().is_correct is True
    assert client.get("/api/practice/history/").json()["count"] == 1
    assert client.get("/api/study/accuracy/").json()["accuracy"] == 100
    other = client_for(other_student)
    assert other.get("/api/practice/history/").json()["count"] == 0
    assert other.get("/api/study/accuracy/").json()["answered"] == 0
    assert other.get(f"/api/attempts/{first.json()['attempt']}/results/").status_code == 404
    changed = payload(workflow, False) | {"request_id": data["request_id"]}
    assert client.post("/api/practice/answers/", changed, format="json").status_code == 409
    assert Attempt.objects.count() == 1


def test_filters_do_not_share_answers_favorites_or_marks(question_setup, student, other_student, client_for):
    workflow = published(question_setup)
    question = workflow.version.question
    client = client_for(student)
    assert client.post("/api/practice/answers/", payload(workflow, False), format="json").status_code == 200
    Bookmark.objects.create(owner=student, target_type="question", target_id=question.pk)
    StudyMark.objects.create(owner=student, target_kind="question", target_id=question.pk, locator="question", kind="review")
    for mode in ["answered", "wrong", "favorites", "review"]:
        assert client.get(f"/api/questions/?mode={mode}").json()["count"] == 1
        assert client_for(other_student).get(f"/api/questions/?mode={mode}").json()["count"] == 0
    assert client.get("/api/questions/?mode=unseen").json()["count"] == 0
    assert client_for(other_student).get("/api/questions/?mode=unseen").json()["count"] == 1
    assert client.get("/api/questions/?difficulty=hard").json()["count"] == 0
    assert client.get(f"/api/questions/?difficulty=medium&year=2026&subject={question.subject_id}").json()["count"] == 1
    assert client.get("/api/questions/?mode=invalid").status_code == 400


def test_formal_mode_cannot_be_bypassed_using_generic_training_or_old_history(question_setup, student, client_for):
    workflow = published(question_setup)
    client = client_for(student)
    data = payload(workflow)
    prior = client.post("/api/practice/answers/", data, format="json").json()
    fields = {"owner": student, "exam_phase": question_setup["phase"], "title": "Simulado", "question_ids": [str(workflow.version.question_id)], "duration_minutes": 60}
    training = Simulation.objects.create(mode="training", **fields)
    early_training = create_attempt(owner=student, simulation=training)
    formal = create_attempt(owner=student, simulation=Simulation.objects.create(mode="formal", **fields))
    assert client.post("/api/attempts/", {"simulation": str(formal.simulation_id)}, format="json").status_code == 409
    assert client.get("/api/study/accuracy/").status_code == 409
    assert client.get("/api/questions/?mode=wrong").status_code == 409
    assert client.post("/api/attempts/", {"simulation": str(training.pk)}, format="json").status_code == 409
    assert client.post(f"/api/attempts/{early_training.pk}/submit/").status_code == 409
    assert client.post("/api/practice/answers/", data, format="json").status_code == 409
    assert client.get("/api/practice/history/").status_code == 409
    assert client.get(f"/api/attempts/{prior['attempt']}/results/").status_code == 409
    assert client.post(f"/api/attempts/{formal.pk}/submit/").status_code == 200
    assert client.get(f"/api/attempts/{prior['attempt']}/results/").status_code == 200
    assert client.post(f"/api/attempts/{early_training.pk}/submit/").status_code == 200


@pytest.mark.parametrize("mutation", ["alternative", "metadata", "insert"])
def test_tampering_after_publication_blocks_read_and_capture(question_setup, student, client_for, mutation):
    workflow = published(question_setup)
    data = payload(workflow)
    if mutation == "alternative":
        Alternative.objects.filter(question_version=workflow.version).update(text="Sem revisão")
    elif mutation == "metadata":
        type(workflow.version.metadata).objects.filter(version=workflow.version).update(annulled=True)
    else:
        Alternative.objects.create(question_version=workflow.version, label="C", text="Inserção sem revisão", order=3)
    client = client_for(student)
    assert client.get("/api/questions/").status_code == 403
    assert client.post("/api/practice/answers/", data, format="json").status_code == 403
    assert not Attempt.objects.exists() and not Simulation.objects.exists()


def test_marks_are_idempotent_owned_and_limited_to_question_locator(question_setup, student, other_student, client_for):
    workflow = published(question_setup)
    question_id = workflow.version.question_id
    path = f"/api/practice/questions/{question_id}/marks/"
    client = client_for(student)
    for _ in range(2):
        assert client.put(path, {"favorite": True, "review": True}, format="json").status_code == 200
    assert Bookmark.objects.count() == StudyMark.objects.count() == 1
    assert client_for(other_student).get(path).json() == {"favorite": False, "review": False}
    assert client_for(other_student).put(path, {"favorite": False, "review": False}, format="json").status_code == 200
    assert Bookmark.objects.count() == StudyMark.objects.count() == 1
    assert client.put(path, {"favorite": True, "review": True, "owner": str(other_student.pk)}, format="json").status_code == 400
    assert client.put(path, {"favorite": False, "review": False}, format="json").status_code == 200
    assert Bookmark.objects.count() == StudyMark.objects.count() == 0


def test_answer_rejects_unpublished_question_and_foreign_alternative(question_setup, student, client_for):
    client = client_for(student)
    assert client.post("/api/practice/answers/", payload(question_setup["workflow"]), format="json").status_code == 404
    workflow = published(question_setup)
    assert client.post("/api/practice/answers/", payload(workflow) | {"selected_alternative": str(uuid4())}, format="json").status_code == 400
    assert not Attempt.objects.exists() and not Simulation.objects.exists()
