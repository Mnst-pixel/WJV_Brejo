from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.models import Exam, ExamPhase, PracticalCaseVersion, RubricCriterion
from core.second_phase_models import SecondPhaseArea, WrittenCheckpoint, WrittenResponse, WrittenSubmission
from core.second_phase_workflow import case_payload, create_case_revision, transition_case
from core.services.written_submissions import save_written, start_written, submit_written
from tests.test_editorial_workspace import operator

pytestmark = pytest.mark.django_db


@pytest.fixture
def phase2_setup():
    _, author = operator("editor")
    _, legal = operator("revisor-juridico")
    _, publisher = operator("administrador-de-conteudo")
    area = SecondPhaseArea.objects.create(name="Direito Civil")
    exam = Exam.objects.create(title="Caderno de escrita", organizer="Autoria", edition=uuid4().hex, exam_date="2026-09-10",
        official_source_url="https://example.invalid/caderno", created_by=author)
    phase = ExamPhase.objects.create(exam=exam, phase=2)
    values = {"area_id": str(area.pk), "title": "Caso de estudo", "piece_name": "Peça confidencial do espelho", "duration_minutes": 300,
        "prompt": "Redija a peça cabível diante dos fatos narrados.", "source_url": "https://example.invalid/fonte", "total_points": "10.00",
        "questions": [{"code": "Q1", "prompt": "Explique o direito aplicável.", "expected_answer": "Resposta confidencial discursiva."}],
        "criteria": [{"code": "P1", "group": "Estrutura", "target_code": "piece", "title": "Endereçamento", "description": "Critério individual",
            "max_points": "5.00", "legal_basis": "Fundamento do espelho", "acceptable_answers": ["Formulação equivalente"]},
            {"code": "D1", "group": "Discursivas", "target_code": "Q1", "title": "Fundamentação", "description": "Critério da discursiva", "max_points": "5.00"}]}
    workflow = create_case_revision(actor=author, exam_phase_id=phase.pk, values=values)
    return {"author": author, "legal": legal, "publisher": publisher, "phase": phase, "values": values, "workflow": workflow}


def change(setup, actor, state, workflow=None):
    workflow = workflow or setup["workflow"]
    workflow.refresh_from_db()
    return transition_case(actor=setup[actor], workflow_id=workflow.pk, expected_state=workflow.state, state=state,
        justification="Revisão humana de todos os critérios e fontes.", legal_status="current")


def publish(setup):
    change(setup, "author", "review")
    approved = change(setup, "legal", "approved")
    return change(setup, "publisher", "published", approved)


def prepare(setup, student, mode="training", request_id=None):
    return start_written(owner=student, data={"case_id": str(setup["workflow"].version.practical_case_id), "request_id": str(request_id or uuid4()), "mode": mode})


def test_case_review_rubric_then_complete_written_submission(phase2_setup, student, client_for):
    setup = phase2_setup
    client = client_for(student)
    assert client.get("/api/phase2/cases/").json()["count"] == 0
    approved = publish(setup)
    assert approved.version_id != setup["workflow"].version_id
    assert PracticalCaseVersion.objects.get(pk=setup["workflow"].version_id).legal_status == "legacy_unverified"
    catalog = client.get("/api/phase2/cases/")
    assert catalog.status_code == 200 and catalog.json()["count"] == 1
    assert "confidencial" not in catalog.content.decode() and "criteria" not in catalog.content.decode()
    request = {"case_id": str(approved.version.practical_case_id), "request_id": str(uuid4()), "mode": "formal"}
    response = client.post("/api/phase2/submissions/", request, format="json")
    assert response.status_code == 201
    record = response.json()
    assert "confidencial" not in response.content.decode() and "criteria" not in response.content.decode()
    assert client.post("/api/phase2/submissions/", request, format="json").json()["id"] == record["id"]
    route = f"/api/phase2/submissions/{record['id']}/"
    text = "  Texto longo preservado\n\n" + "Fundamento e pedido. " * 4000
    saved = client.post(route + "autosave/", {"version": 1, "responses": [{"target_code": "piece", "text": text}, {"target_code": "Q1", "text": "Minha resposta."}]}, format="json")
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert client.get(route).json()["responses"] == saved.json()["responses"]
    assert WrittenCheckpoint.objects.get(submission_id=record["id"]).snapshot["responses"] == saved.json()["responses"]
    final = client.post(route + "submit/").json()
    assert final["status"] == "submitted" and len(final["final_hash"]) == 64
    assert client.post(route + "submit/").json() == final
    assert client.post(route + "autosave/", {"version": final["version"], "responses": saved.json()["responses"]}, format="json").status_code == 409
    assert client.post(route).status_code == 405


def test_editor_cannot_approve_or_publish_and_student_cannot_author(phase2_setup, student):
    setup = phase2_setup
    with pytest.raises(PermissionDenied):
        create_case_revision(actor=student, exam_phase_id=setup["phase"].pk, values=setup["values"])
    change(setup, "author", "review")
    with pytest.raises(PermissionDenied):
        change(setup, "author", "approved")
    with pytest.raises(PermissionDenied):
        change(setup, "author", "published")
    setup["workflow"].author = setup["legal"]
    setup["workflow"].save()
    with pytest.raises(PermissionDenied):
        change(setup, "legal", "approved")


@pytest.mark.parametrize("mutation", ["sum", "missing_target", "cycle", "duplicate", "negative", "credentials"])
def test_rubric_validation_prevents_invalid_publication(phase2_setup, mutation):
    setup = phase2_setup
    values = case_payload(setup["workflow"].version)
    if mutation == "sum":
        values["total_points"] = "9.00"
    elif mutation == "missing_target":
        values["criteria"][1]["target_code"] = "piece"
    elif mutation == "cycle":
        values["criteria"][0]["dependencies"] = ["D1"]
    elif mutation == "duplicate":
        values["questions"].append(values["questions"][0])
    elif mutation == "negative":
        values["criteria"][0]["max_points"] = "-1"
    else:
        values["source_url"] = "https://user:password@example.invalid/source"
    with pytest.raises(ValidationError):
        draft = create_case_revision(actor=setup["author"], case_id=setup["workflow"].version.practical_case_id, values=values)
        reviewed = change(setup, "author", "review", draft)
        change(setup, "legal", "approved", reviewed)


@pytest.mark.parametrize("mutation", ["criterion_update", "criterion_insert", "discursive_update", "missing_details"])
def test_approved_package_tampering_fails_closed(phase2_setup, student, client_for, mutation):
    approved = publish(phase2_setup)
    if mutation == "criterion_update":
        approved.version.rubric.criteria.update(max_points=Decimal("0.01"))
    elif mutation in {"criterion_insert", "missing_details"}:
        # A child inserted after approval must fail closed, including absent details.
        from core.second_phase_models import RubricCriterionDetails
        item = RubricCriterion.objects.create(rubric=approved.version.rubric, code="Injected", title="X", description="X", max_points=1, order=99)
        if mutation == "criterion_insert":
            RubricCriterionDetails.objects.create(criterion=item, group="Injected")
    else:
        approved.version.discursive_questions.update(expected_answer="Alterada após revisão")
    assert client_for(student).get("/api/phase2/cases/").status_code == 403


def test_written_ownership_conflict_replay_and_final_integrity(phase2_setup, student, other_student, client_for):
    publish(phase2_setup)
    submission = prepare(phase2_setup, student)
    route = f"/api/phase2/submissions/{submission.pk}/"
    body = {"version": 1, "responses": [{"target_code": "piece", "text": "Primeira versão"}, {"target_code": "Q1", "text": "Resposta"}]}
    other = client_for(other_student)
    for suffix in ["", "autosave/", "submit/"]:
        response = other.get(route) if not suffix else other.post(route + suffix, body, format="json")
        assert response.status_code == 404
    saved = save_written(owner=student, submission_id=submission.pk, data=body)
    client = client_for(student)
    assert client.post(route + "autosave/", body, format="json").status_code == 409
    assert client.get(route).json()["version"] == saved.version
    assert client.post("/api/phase2/submissions/", {"case_id": str(uuid4()), "request_id": str(submission.request_id)}, format="json").status_code == 409
    submit_written(owner=student, submission_id=submission.pk)
    WrittenResponse.objects.filter(submission=submission, target_code="piece").update(text="Alteração indevida")
    assert client.get(route).status_code == 403


def test_written_formal_blocks_ai_and_first_phase_admission(phase2_setup, student, client_for):
    publish(phase2_setup)
    submission = prepare(phase2_setup, student, mode="formal")
    client = client_for(student)
    with patch("core.services.ai.hybrid_retrieve") as retrieval:
        assert client.post("/api/ai/consult", {"question": "Ajude", "context": {}}, format="json").status_code == 403
        retrieval.assert_not_called()
    assert client.get("/api/study/accuracy/").status_code == 409
    assert client.post("/api/phase2/submissions/", {"case_id": str(submission.case_version.practical_case_id), "request_id": str(uuid4())}, format="json").status_code == 409
    assert client.post("/api/simulation-start/", {"exam_phase": str(uuid4()), "quantity": 1, "duration_minutes": 60, "request_id": str(uuid4())}, format="json").status_code == 409
    WrittenSubmission.objects.filter(pk=submission.pk).update(started_at=timezone.now() - timedelta(days=1))
    route = f"/api/phase2/submissions/{submission.pk}/"
    assert client.post(route + "autosave/", {"version": 1, "responses": [{"target_code": "piece", "text": "Atrasada"}, {"target_code": "Q1", "text": ""}]}, format="json").status_code == 409
    final = client.post(route + "submit/").json()
    assert final["elapsed_seconds"] == 300 * 60
    assert client.get("/api/study/accuracy/").status_code == 200


def test_submission_database_rejects_impossible_state(phase2_setup, student):
    publish(phase2_setup)
    submission = prepare(phase2_setup, student)
    with pytest.raises(IntegrityError), transaction.atomic():
        WrittenSubmission.objects.filter(pk=submission.pk).update(status="submitted")


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_written_response_targets_cannot_drift(phase2_setup, student, client_for, mutation):
    publish(phase2_setup)
    submission = prepare(phase2_setup, student)
    if mutation == "missing":
        WrittenResponse.objects.filter(submission=submission, target_code="Q1").delete()
    else:
        WrittenResponse.objects.create(submission=submission, target_code="foreign", text="Não pertence")
    client = client_for(student)
    route = f"/api/phase2/submissions/{submission.pk}/"
    assert client.get(route).status_code == 403
    assert client.post(route + "submit/").status_code == 403
    assert client.post(route + "autosave/", {"version": 1, "responses": [{"target_code": "piece", "text": ""}, {"target_code": "Q1", "text": ""}]}, format="json").status_code == 403


def test_phase2_editorial_forms_and_permissions(phase2_setup, student, client_for):
    setup = phase2_setup
    editor, author = operator("editor")
    reviewer, _ = operator("revisor-juridico")
    publisher, _ = operator("administrador-de-conteudo")
    new_url = reverse("editorial:phase2-create")
    assert client_for(student).get(new_url).status_code == 403
    response = editor.get(new_url)
    assert response.status_code == 200 and "Adicionar critério" in response.content.decode()
    body = {"area_id": str(SecondPhaseArea.objects.get().pk), "exam_phase_id": str(setup["phase"].pk), "title": "Caso via formulário", "piece_name": "Peça reservada",
        "prompt": "Enunciado via formulário", "duration_minutes": "300", "total_points": "10.00", "source_url": "https://example.invalid/fonte", "provenance": "human_authored",
        "questions-TOTAL_FORMS": "0", "questions-INITIAL_FORMS": "0", "criteria-TOTAL_FORMS": "1", "criteria-INITIAL_FORMS": "0",
        "criteria-0-code": "P1", "criteria-0-group": "Peça", "criteria-0-target_code": "piece", "criteria-0-title": "Critério integral",
        "criteria-0-description": "Todos os elementos", "criteria-0-max_points": "10.00", "criteria-0-ORDER": "1"}
    created = editor.post(new_url, body)
    assert created.status_code == 302
    page = editor.get(created.url)
    assert page.status_code == 200 and "Espelho reservado" in page.content.decode()
    reviewed = editor.post(created.url, {"target_state": "review", "expected_state": "draft", "justification": "Enviar para conferência independente"})
    assert reviewed.status_code == 302
    assert editor.post(created.url, {"target_state": "published", "expected_state": "review", "justification": "Tentar publicar diretamente"}).status_code == 403
    approved = reviewer.post(created.url, {"target_state": "approved", "expected_state": "review", "justification": "Conferência integral da peça e espelho", "legal_status": "current"})
    assert approved.status_code == 302
    assert publisher.post(approved.url, {"target_state": "published", "expected_state": "approved", "justification": "Publicação após revisão independente"}).status_code == 302
    from core.second_phase_models import SecondPhaseWorkflow
    workflow = SecondPhaseWorkflow.objects.get(version__educational_metadata__title="Caso via formulário", state="published")
    with pytest.raises(PermissionDenied):
        transition_case(actor=author, workflow_id=workflow.pk, expected_state="published", state="archived", justification="Editor sem permissão de publicação")
    assert editor.get(reverse("editorial:phase2-revise", args=[workflow.pk])).status_code == 200


def test_case_reviewer_sees_entire_reserved_package(phase2_setup):
    setup = phase2_setup
    values = case_payload(setup["workflow"].version)
    values.update(jurisdiction="Competência sentinela", deadline="Prazo sentinela", merits=["Tese sentinela"], facts=["Fato sentinela"], distractors=["Distrator sentinela"])
    version = create_case_revision(actor=setup["author"], case_id=setup["workflow"].version.practical_case_id, values=values)
    change(setup, "author", "review", version)
    reviewer, _ = operator("revisor-juridico")
    response = reviewer.get(reverse("editorial:phase2-case", args=[version.pk]))
    assert response.status_code == 200
    for text in ["Competência sentinela", "Prazo sentinela", "Tese sentinela", "Fato sentinela", "Distrator sentinela"]:
        assert text in response.content.decode()


def test_duplicate_phase2_exam_has_friendly_error(phase2_setup):
    editor, _ = operator("editor")
    exam = phase2_setup["phase"].exam
    response = editor.post(reverse("editorial:phase2-exam-create"), {"title": exam.title, "organizer": exam.organizer, "edition": exam.edition,
        "exam_date": "2026-09-10", "official_source_url": "https://example.invalid/caderno", "duration_minutes": "300"})
    assert response.status_code == 200 and "Já existe uma prova" in response.content.decode()
