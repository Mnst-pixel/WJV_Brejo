from uuid import uuid4
from unittest.mock import patch
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Attempt, Simulation
from core.question_workflow import create_question
from tests.test_question_editorial import published, question_setup as setup_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def question_setup():
    return setup_fixture.__wrapped__()


def config(setup):
    return {"exam_phase": str(setup["phase"].pk), "title": "Meu simulado", "mode": "formal", "quantity": 1, "duration_minutes": 60, "request_id": str(uuid4())}


def test_catalog_and_builder_use_only_published_questions(question_setup, student, client_for):
    client = client_for(student)
    assert client.get("/api/simulation-catalog/").json()["results"] == []
    assert client.post("/api/simulation-start/", config(question_setup), format="json").status_code == 400
    published(question_setup)
    assert client.get("/api/simulation-catalog/").json()["results"][0]["available"] == 1
    settings = config(question_setup)
    first = client.post("/api/simulation-start/", settings, format="json")
    assert first.status_code == 201, first.content
    assert len(first.json()["questions"]) == 1
    assert "correct_alternative" not in first.content.decode()
    assert first.json()["title"] == "Meu simulado" and first.json()["duration_minutes"] == 60
    assert client.post("/api/simulation-start/", settings, format="json").json()["id"] == first.json()["id"]
    assert Attempt.objects.count() == Simulation.objects.count() == 1
    assert client.post("/api/simulation-start/", settings | {"title": "Configuração diferente"}, format="json").status_code == 409


def test_builder_filters_capacity_and_ownership(question_setup, student, other_student, client_for):
    published(question_setup)
    client = client_for(student)
    for extra in [{"quantity": 2}, {"quantity": 0}, {"difficulty": "hard"}, {"subjects": [str(uuid4())]}, {"owner": str(other_student.pk)}, {"exam_phase": str(uuid4())}]:
        assert client.post("/api/simulation-start/", config(question_setup) | extra, format="json").status_code == 400
    assert not Attempt.objects.exists() and not Simulation.objects.exists()
    first = client.post("/api/simulation-start/", config(question_setup), format="json").json()
    assert client_for(other_student).get(f"/api/attempts/{first['id']}/").status_code == 404
    assert client_for(other_student).get("/api/attempts/?purpose=simulation").json()["count"] == 0


def test_random_selection_is_frozen_and_resumable(question_setup, student, client_for):
    published(question_setup)
    for number in range(4):
        workflow = create_question(actor=question_setup["author"], exam_phase_id=question_setup["phase"].pk,
            subject_id=question_setup["subject"].pk, topic_id=None, values=question_setup["values"] | {"statement": f"Questão adicional {number}"})
        published(question_setup | {"workflow": workflow})
    client = client_for(student)
    settings = config(question_setup) | {"quantity": 3, "randomize": True}
    first = client.post("/api/simulation-start/", settings, format="json").json()
    ids = [item["question"] for item in first["questions"]]
    assert len(ids) == len(set(ids)) == 3
    question = first["questions"][0]
    route = f"/api/attempts/{first['id']}/"
    saved = client.post(route + "autosave/", {"version": 1, "elapsed_seconds": 15,
        "answers": [{"question": question["question"], "selected_alternative": question["alternatives"][0]["id"]}]}, format="json")
    assert saved.status_code == 200
    resumed = client.get(route).json()
    assert [item["question"] for item in resumed["questions"]] == ids
    assert resumed["answers"][0]["selected_alternative"] == question["alternatives"][0]["id"]
    assert client.post(route + "submit/").status_code == 200
    assert client.get(route + "results/").json()["total"] == 3


def test_formal_blocks_ai_without_optional_context_before_retrieval(question_setup, student, client_for):
    published(question_setup)
    client = client_for(student)
    attempt = client.post("/api/simulation-start/", config(question_setup), format="json").json()
    with patch("core.services.ai.hybrid_retrieve") as retrieval:
        for context in [{}, {"attempt_id": attempt["id"]}]:
            assert client.post("/api/ai/consult", {"question": "Explique a resposta", "action": "consult", "context": context}, format="json").status_code == 403
        retrieval.assert_not_called()


@pytest.mark.parametrize("field,value,status", [("attempt_id", "invalid", 400), ("attempt_id", str(uuid4()), 403),
    ("conversation_id", "invalid", 400), ("conversation_id", str(uuid4()), 404)])
def test_unknown_ai_resources_do_not_return_server_errors(student, client_for, field, value, status):
    data = {"question": "Consulta de teste", "action": "consult", "context": {field: value} if field == "attempt_id" else {}, **({field: value} if field == "conversation_id" else {})}
    with patch("core.services.ai.hybrid_retrieve") as retrieval:
        assert client_for(student).post("/api/ai/consult", data, format="json").status_code == status
        retrieval.assert_not_called()


def test_review_marker_is_owned_persistent_and_frozen_after_submission(question_setup, student, other_student, client_for):
    published(question_setup)
    client = client_for(student)
    record = client.post("/api/simulation-start/", config(question_setup), format="json").json()
    route = f"/api/attempts/{record['id']}/"
    body = {"version": 1, "elapsed_seconds": 10, "answers": [{"question": record["questions"][0]["question"], "selected_alternative": None, "marked_for_review": True}]}
    assert client_for(other_student).post(route + "autosave/", body, format="json").status_code == 404
    assert client.post(route + "autosave/", body, format="json").status_code == 200
    assert client.get(route).json()["answers"][0]["marked_for_review"] is True
    assert Attempt.objects.get(pk=record["id"]).checkpoints.get().snapshot["answers"][0]["marked_for_review"] is True
    assert client.post(route + "submit/").status_code == 200
    assert client.get("/api/study/accuracy/").json()["answered"] == 0
    assert client.get("/api/questions/?mode=unseen").json()["count"] == 1
    assert client.post(route + "autosave/", body | {"version": 3}, format="json").status_code == 400


def test_formal_submission_records_elapsed_server_time(question_setup, student, client_for):
    published(question_setup)
    client = client_for(student)
    record = client.post("/api/simulation-start/", config(question_setup), format="json").json()
    Attempt.objects.filter(pk=record["id"]).update(started_at=timezone.now() - timedelta(seconds=45))
    route = f"/api/attempts/{record['id']}/"
    saved = client.post(route + "autosave/", {"version": 1, "elapsed_seconds": 3600, "answers": []}, format="json")
    assert saved.status_code == 200
    assert 45 <= saved.json()["elapsed_seconds"] < 50
    assert 45 <= Attempt.objects.get(pk=record["id"]).checkpoints.get().snapshot["elapsed_seconds"] < 50
    assert client.post(route + "submit/").status_code == 200
    assert 45 <= client.get(route + "results/").json()["elapsed_seconds"] < 50
