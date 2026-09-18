from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied

from core.models import Alternative, ContentVersion, Exam, ExamPhase, Question, QuestionVersion, Simulation, Subject
from core.question_models import QuestionWorkflow
from core.question_workflow import create_question, package_hash, published_questions, question_payload, revise_question, transition_question
from core.services.attempts import autosave_attempt, create_attempt, submit_attempt
from tests.test_editorial_workspace import operator

pytestmark = pytest.mark.django_db


@pytest.fixture
def question_setup():
    editor, author = operator("editor")
    reviewer, legal = operator("revisor-juridico")
    publisher, publishing = operator("administrador-de-conteudo")
    subject = Subject.objects.create(name="Ética", slug=uuid4().hex)
    exam = Exam.objects.create(title="Caderno de teste", organizer="Autoria", edition=uuid4().hex, exam_date="2026-09-10",
        official_source_url="https://example.invalid/caderno", created_by=author)
    phase = ExamPhase.objects.create(exam=exam, phase=1)
    values = {"statement": "Qual é a alternativa correta?", "explanation": "A alternativa B atende ao fundamento.",
        "alternatives": [{"label": "A", "text": "Primeira alternativa"}, {"label": "B", "text": "Segunda alternativa"}],
        "correct_label": "B", "source_url": "https://example.invalid/fonte", "difficulty": "medium", "origin": "authored", "legal_basis": "Fundamento de teste."}
    workflow = create_question(actor=author, exam_phase_id=phase.pk, subject_id=subject.pk, topic_id=None, values=values)
    return {"editor": editor, "author": author, "reviewer": reviewer, "legal": legal, "publisher": publisher, "publishing": publishing,
            "subject": subject, "phase": phase, "workflow": workflow, "values": values}


def transition(setup, actor, state, workflow=None):
    return transition_question(actor=setup[actor], workflow_id=(workflow or setup["workflow"]).pk, state=state,
        justification="Conferência humana independente de todos os itens.", legal_status="current")


def published(setup):
    transition(setup, "author", "review")
    approved = transition(setup, "legal", "approved")
    transition(setup, "publishing", "published", approved)
    approved.refresh_from_db()
    return approved


def test_question_package_review_publish_then_student_answers(question_setup, student):
    setup = question_setup
    original = setup["workflow"]
    assert published_questions().count() == 0
    published_version = published(setup)
    assert published_questions().get().pk == original.version.question_id
    original.refresh_from_db()
    assert original.state == "archived" and original.version.legal_status == "legacy_unverified"
    assert published_version.version_id != original.version_id
    assert published_version.approval.evidence["package_sha256"] == package_hash(published_version)
    simulation = Simulation.objects.create(owner=student, exam_phase=setup["phase"], mode="training", title="Treino",
        question_ids=[str(original.version.question_id)], duration_minutes=60)
    attempt = create_attempt(owner=student, simulation=simulation)
    saved = autosave_attempt(attempt_id=attempt.pk, owner=student, expected_version=1, elapsed_seconds=10,
        answers=[{"question": str(original.version.question_id), "selected_alternative": str(published_version.answer_key_version.correct_alternative_id)}])
    submitted = submit_attempt(attempt_id=saved.pk, owner=student)
    assert submitted.result_snapshot["correct"] == 1 and submitted.result_snapshot["unscored"] == 0
    assert submitted.frozen_definition["questions"][0]["subject_name"] == "Ética"
    assert submitted.frozen_definition["questions"][0]["legal_basis"] == "Fundamento de teste."


def test_author_cannot_approve_and_published_draft_stays_frozen(question_setup):
    setup = question_setup
    with pytest.raises(PermissionDenied):
        transition(setup, "author", "approved")
    approved = published(setup)
    newer = revise_question(actor=setup["author"], workflow_id=approved.pk, values=setup["values"] | {"statement": "Outro enunciado"})
    assert newer.state == "draft"
    assert published_questions().get().current_version_id == approved.version_id


def test_approval_does_not_make_question_available(question_setup):
    transition(question_setup, "author", "review")
    approved = transition(question_setup, "legal", "approved")
    assert approved.state == "approved" and not published_questions().exists()
    assert Question.objects.get().current_version_id is None


@pytest.mark.parametrize("target", ["alternative", "key", "legal_status", "metadata"])
def test_publication_rejects_tampered_package(question_setup, target):
    transition(question_setup, "author", "review")
    approved = transition(question_setup, "legal", "approved")
    if target == "alternative":
        Alternative.objects.filter(question_version=approved.version).update(text="Alteração sem revisão")
    elif target == "key":
        type(approved.answer_key_version).objects.filter(pk=approved.answer_key_version_id).update(rationale="Gabarito adulterado")
    elif target == "legal_status":
        QuestionVersion.objects.filter(pk=approved.version_id).update(legal_status="revoked")
    else:
        type(approved.version.metadata).objects.filter(version=approved.version).update(difficulty="hard")
    with pytest.raises(PermissionDenied):
        transition(question_setup, "publishing", "published", approved)
    assert not published_questions().exists()


def test_archive_blocks_new_attempt_but_preserves_previous_result(question_setup, student):
    approved = published(question_setup)
    simulation = Simulation.objects.create(owner=student, exam_phase=question_setup["phase"], mode="training", title="Treino",
        question_ids=[str(approved.version.question_id)], duration_minutes=60)
    attempt = create_attempt(owner=student, simulation=simulation)
    transition(question_setup, "publishing", "archived", approved)
    assert not published_questions().exists()
    assert submit_attempt(attempt_id=attempt.pk, owner=student).result_snapshot["total"] == 1


def test_html_question_create_review_publish_and_no_student_key(question_setup, client_for, student):
    setup = question_setup
    data = {"exam_phase_id": setup["phase"].pk, "subject_id": setup["subject"].pk,
        "statement": "Questão criada por formulário", "explanation": "Gabarito secreto até a resposta", "source_url": "https://example.invalid/doc",
        "difficulty": "easy", "origin": "authored", "alternative_A": "Resposta A", "alternative_B": "Resposta B", "correct_label": "A"}
    response = setup["editor"].post(reverse("editorial:question-create"), data)
    assert response.status_code == 302
    workflow = QuestionWorkflow.objects.get(version__statement=data["statement"])
    route = reverse("editorial:question-version", args=[workflow.pk])
    assert "Gabarito editorial" in setup["editor"].get(route).content.decode()
    assert setup["editor"].post(route, {"state": "review", "justification": "Conferir todos os itens."}).status_code == 302
    assert setup["reviewer"].post(route, {"state": "approved", "justification": "Itens conferidos e corretos.", "legal_status": "current"}).status_code == 302
    approved = QuestionWorkflow.objects.get(state="approved")
    assert setup["publisher"].post(reverse("editorial:question-version", args=[approved.pk]), {"state": "published", "justification": "Publicação autorizada."}).status_code == 302
    student_client = client_for(student)
    response = student_client.get("/api/questions/")
    assert response.status_code == 200
    text = response.content.decode()
    assert data["statement"] in text and data["explanation"] not in text and "correct_label" not in text
    assert student_client.get(route).status_code == 403


def test_invalid_form_and_unsupported_keys_cannot_publish(question_setup):
    from rest_framework.exceptions import ValidationError
    setup = question_setup
    for invalid in [{"correct_label": "H"}, {"source_url": "https://user:pass@example.invalid/"}, {"state": "published"},
                    {"alternatives": [{"label": "A", "text": "same"}, {"label": "B", "text": "same"}]}]:
        with pytest.raises(ValidationError):
            revise_question(actor=setup["author"], workflow_id=setup["workflow"].pk, values=setup["values"] | invalid)
    assert QuestionVersion.objects.count() == 1 and ContentVersion.objects.count() == 0


def test_question_payload_can_create_successor(question_setup):
    workflow = question_setup["workflow"]
    revised = revise_question(actor=question_setup["author"], workflow_id=workflow.pk, values=question_payload(workflow))
    assert revised.version.version_number == 2
    assert revised.answer_key_version.correct_alternative_id != workflow.answer_key_version.correct_alternative_id


def test_question_integrity_checks_do_not_grow_queries_per_row(question_setup, student, client_for):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    published(question_setup)
    client = client_for(student)
    client.get("/api/questions/")
    with CaptureQueriesContext(connection) as single:
        assert client.get("/api/questions/").json()["count"] == 1
    for index in range(9):
        workflow = create_question(actor=question_setup["author"], exam_phase_id=question_setup["phase"].pk,
            subject_id=question_setup["subject"].pk, topic_id=None, values=question_setup["values"] | {"statement": f"Questão de teste {index}"})
        published(question_setup | {"workflow": workflow})
    with CaptureQueriesContext(connection) as multiple:
        assert client.get("/api/questions/").json()["count"] == 10
    assert len(multiple) <= len(single) + 1
