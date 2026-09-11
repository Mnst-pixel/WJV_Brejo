from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.http import Http404

from core.exceptions import Conflict
from core.models import Alternative, AnswerKey, AnswerKeyVersion, Attempt, Exam, ExamPhase, Question, QuestionVersion, Simulation, Subject
from core.serializers import AttemptSerializer, SimulationSerializer
from core.services.attempts import attempt_results, autosave_attempt, create_attempt, submit_attempt

pytestmark = pytest.mark.django_db


@pytest.fixture
def approved_simulation(student):
    subject = Subject.objects.create(slug="law", name="Direito")
    exam = Exam.objects.create(title="Prova", edition="new", exam_date=timezone.localdate(), official_source_url="https://example.invalid/exam", created_by=student)
    phase = ExamPhase.objects.create(exam=exam, phase=1)
    question = Question.objects.create(exam_phase=phase, subject=subject, number=1)
    common = {"original_text": "Fonte", "retrieved_at": timezone.now(), "source_url": "https://example.invalid/q", "source_hash": "a" * 64, "approved_by": student, "approval_date": timezone.now(), "published_at": timezone.now(), "legal_status": "current"}
    version = QuestionVersion.objects.create(question=question, version_number=1, statement="Enunciado original", **common)
    question.current_version = version
    question.save()
    correct = Alternative.objects.create(question_version=version, label="A", text="Original A", order=1)
    wrong = Alternative.objects.create(question_version=version, label="B", text="Original B", order=2)
    key_parent = AnswerKey.objects.create(question=question, kind="final")
    key = AnswerKeyVersion.objects.create(answer_key=key_parent, version_number=1, correct_alternative=correct, rationale="Fundamento original", **common)
    key_parent.current_version = key
    key_parent.save()
    simulation = Simulation.objects.create(owner=student, exam_phase=phase, mode="formal", title="Teste", question_ids=[str(question.pk)])
    return simulation, question, correct, wrong, common


def save(attempt, owner, question, alternative, version=1, elapsed=20):
    return autosave_attempt(attempt_id=attempt.pk, owner=owner, expected_version=version, answers=[{"question": str(question.pk), "selected_alternative": str(alternative.pk)}], elapsed_seconds=elapsed)


def test_result_remains_stable_after_current_versions_change(student, approved_simulation):
    simulation, question, correct, wrong, common = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    save(attempt, student, question, correct)
    first = submit_attempt(attempt_id=attempt.pk, owner=student)
    result = deepcopy(attempt_results(attempt_id=attempt.pk, owner=student))
    assert result["correct"] == 1 and not result["requires_review"]
    successor = QuestionVersion.objects.create(question=question, version_number=2, statement="Versão posterior", **common)
    question.current_version = successor
    question.save()
    correct.text = "Texto adulterado depois"
    correct.save()
    key_parent = AnswerKey.objects.get(question=question)
    key_parent.current_version = AnswerKeyVersion.objects.create(answer_key=key_parent, version_number=2, correct_alternative=wrong, rationale="Posterior", **common)
    key_parent.save()
    again = submit_attempt(attempt_id=attempt.pk, owner=student)
    assert again.version == first.version
    assert again.submitted_at == first.submitted_at
    assert attempt_results(attempt_id=attempt.pk, owner=student) == result
    assert again.frozen_definition["questions"][0]["alternatives"][0]["text"] == "Original A"


def test_autosave_uses_frozen_alternatives_after_new_version(student, approved_simulation):
    simulation, question, correct, _, common = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    new = QuestionVersion.objects.create(question=question, version_number=2, statement="Novo", **common)
    question.current_version = new
    question.save()
    save(attempt, student, question, correct)
    assert attempt.answers.get().selected_alternative_id == correct.pk


def test_creation_idempotency_owner_and_request_binding(student, other_student, approved_simulation):
    simulation, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student, idempotency_key="create-001")
    assert create_attempt(simulation=simulation, owner=student, idempotency_key="create-001").pk == attempt.pk
    other_sim = Simulation.objects.create(owner=student, exam_phase=simulation.exam_phase, title="Outro", mode="formal")
    with pytest.raises(Conflict):
        create_attempt(simulation=other_sim, owner=student, idempotency_key="create-001")
    with pytest.raises(Http404):
        create_attempt(simulation=simulation, owner=other_student)


def test_snapshot_answer_key_never_leaks_through_attempt_serializer(student, approved_simulation):
    simulation, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    data = AttemptSerializer(attempt).data
    assert "correct_alternative" not in str(data)
    assert "rationale" not in str(data)
    assert "frozen_definition" not in data
    assert data["questions"][0]["statement"] == "Enunciado original"


@pytest.mark.parametrize("field,value", [("mode", "free"), ("duration_minutes", 60), ("question_ids", [])])
def test_simulation_structure_is_frozen_after_attempt(student, approved_simulation, field, value):
    simulation, *_ = approved_simulation
    create_attempt(simulation=simulation, owner=student)
    serializer = SimulationSerializer(simulation, data={field: value}, partial=True)
    assert serializer.is_valid(), serializer.errors
    with pytest.raises(ValidationError):
        serializer.save()
    simulation.refresh_from_db()
    assert getattr(simulation, field) != value


@pytest.mark.parametrize("field,value", [("status", "submitted"), ("elapsed_seconds", 0), ("version", 100), ("result_snapshot", {"correct": 100})])
def test_generic_attempt_patch_cannot_change_command_state(student, approved_simulation, field, value):
    simulation, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    serializer = AttemptSerializer(attempt, data={field: value}, partial=True)
    assert not serializer.is_valid()


def test_duplicate_or_foreign_answers_rollback_atomically(student, approved_simulation):
    simulation, question, correct, _, _ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    payload = {"question": str(question.pk), "selected_alternative": str(correct.pk)}
    with pytest.raises(ValidationError):
        autosave_attempt(attempt_id=attempt.pk, owner=student, expected_version=1, answers=[payload, payload], elapsed_seconds=20)
    with pytest.raises(PermissionDenied):
        autosave_attempt(attempt_id=attempt.pk, owner=student, expected_version=1, answers=[payload, {"question": str(uuid4())}], elapsed_seconds=20)
    assert not attempt.answers.exists()
    attempt.refresh_from_db()
    assert attempt.version == 1


@pytest.mark.parametrize("answers,version,elapsed", [("invalid", 1, 1), ([], "wrong", 1), ([], 1, -1), ([], 1, "bad"), ([{"question": "no-uuid"}], 1, 0)])
def test_malformed_autosave_is_validation_error(student, approved_simulation, answers, version, elapsed):
    simulation, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    with pytest.raises(ValidationError):
        autosave_attempt(attempt_id=attempt.pk, owner=student, expected_version=version, answers=answers, elapsed_seconds=elapsed)


def test_elapsed_is_monotonic_and_formal_deadline_is_server_side(student, approved_simulation):
    simulation, question, correct, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    save(attempt, student, question, correct)
    with pytest.raises(ValidationError):
        save(attempt, student, question, correct, version=2, elapsed=10)
    Attempt.objects.filter(pk=attempt.pk).update(started_at=timezone.now() - timedelta(days=1))
    with pytest.raises(Conflict):
        save(attempt, student, question, correct, version=2, elapsed=20)
    assert submit_attempt(attempt_id=attempt.pk, owner=student).status == "submitted"


def test_other_owner_cannot_operate_attempt(student, other_student, approved_simulation):
    simulation, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    with pytest.raises(Http404):
        submit_attempt(attempt_id=attempt.pk, owner=other_student)
    with pytest.raises(Http404):
        attempt_results(attempt_id=attempt.pk, owner=other_student)


def test_legacy_attempt_never_recalculates_historical_score(student, approved_simulation):
    simulation, *_ = approved_simulation
    legacy = Attempt.objects.create(owner=student, simulation=simulation, status="submitted", snapshot_origin="legacy_unverified")
    result = attempt_results(attempt_id=legacy.pk, owner=student)
    assert result["status"] == "historical_result_unavailable"
    assert "correct" not in result
    assert submit_attempt(attempt_id=legacy.pk, owner=student).result_snapshot == {}
    active = Attempt.objects.create(owner=student, simulation=simulation, snapshot_origin="legacy_unverified")
    with pytest.raises(Conflict):
        submit_attempt(attempt_id=active.pk, owner=student)


def test_constraints_prevent_impossible_attempt_state(student, approved_simulation):
    simulation, *_ = approved_simulation
    with pytest.raises(IntegrityError), transaction.atomic():
        Attempt.objects.create(owner=student, simulation=simulation, status="active", submitted_at=timezone.now())
    with pytest.raises(IntegrityError), transaction.atomic():
        Simulation.objects.create(owner=student, exam_phase=simulation.exam_phase, title="Inválido", mode="formal", duration_minutes=0)


def test_unapproved_questions_cannot_enter_new_attempt(student, approved_simulation):
    simulation, question, *_ = approved_simulation
    QuestionVersion.objects.filter(pk=question.current_version_id).update(legal_status="legacy_unverified")
    with pytest.raises(PermissionDenied):
        create_attempt(simulation=simulation, owner=student)

def test_invalid_attempt_identifier_is_validation_error(student):
    with pytest.raises(ValidationError):
        submit_attempt(attempt_id="not-a-uuid", owner=student)
    with pytest.raises(ValidationError):
        attempt_results(attempt_id="not-a-uuid", owner=student)


def test_real_api_autosave_invalid_payload_is_400(student, client_for, approved_simulation):
    simulation, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    response = client_for(student).post(f"/api/attempts/{attempt.pk}/autosave/", {"version": "bad", "answers": "bad", "elapsed_seconds": "bad"}, format="json")
    assert response.status_code == 400


def test_api_create_replay_uses_same_attempt(student, client_for, approved_simulation):
    simulation, *_ = approved_simulation
    client = client_for(student)
    first = client.post("/api/attempts/", {"simulation": str(simulation.pk)}, format="json", HTTP_IDEMPOTENCY_KEY="api-replay-001")
    second = client.post("/api/attempts/", {"simulation": str(simulation.pk)}, format="json", HTTP_IDEMPOTENCY_KEY="api-replay-001")
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert Attempt.objects.filter(owner=student).count() == 1


def test_stale_generic_serializer_cannot_reopen_submitted_attempt(student, approved_simulation):
    simulation, question, correct, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    stale = Attempt.objects.get(pk=attempt.pk)
    serializer = AttemptSerializer(stale, data={}, partial=True)
    assert serializer.is_valid(), serializer.errors
    save(attempt, student, question, correct)
    submitted = submit_attempt(attempt_id=attempt.pk, owner=student)
    expected_result = deepcopy(submitted.result_snapshot)
    with pytest.raises(ValidationError):
        serializer.save()
    attempt.refresh_from_db()
    assert attempt.status == "submitted"
    assert attempt.version == submitted.version
    assert attempt.submitted_at == submitted.submitted_at
    assert attempt.result_snapshot == expected_result
    assert attempt.answers.get().selected_alternative_id == correct.pk


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_api_forbids_generic_writes_and_deletion_of_results(student, client_for, approved_simulation, method):
    simulation, question, correct, *_ = approved_simulation
    attempt = create_attempt(simulation=simulation, owner=student)
    save(attempt, student, question, correct)
    attempt = submit_attempt(attempt_id=attempt.pk, owner=student)
    expected = deepcopy(attempt.result_snapshot)
    response = getattr(client_for(student), method)(f"/api/attempts/{attempt.pk}/", {}, format="json")
    assert response.status_code == 405
    attempt.refresh_from_db()
    assert attempt.status == "submitted"
    assert attempt.result_snapshot == expected
    assert attempt.answers.count() == 1


def test_unpublished_answer_key_is_not_captured(student, approved_simulation):
    simulation, question, *_ = approved_simulation
    AnswerKeyVersion.objects.filter(answer_key__question=question).update(published_at=None)
    attempt = create_attempt(simulation=simulation, owner=student)
    item = attempt.frozen_definition["questions"][0]
    assert item["correct_alternative"] is None
    assert item["answer_key_version"] is None


def test_future_annulment_does_not_change_current_attempt(student, approved_simulation):
    from core.models import Annulment, Source, SourceRegistry
    simulation, question, *_ = approved_simulation
    registry = SourceRegistry.objects.create(organization="Synthetic", domain="example.invalid", source_type="official", jurisdiction="test", data_format="text", access_method="manual")
    source = Source.objects.create(registry=registry, title="Synthetic", url="https://example.invalid", retrieved_at=timezone.now())
    annulment = Annulment.objects.create(question=question, source=source, reason="Synthetic", effective_at=timezone.now() + timedelta(days=1))
    attempt = create_attempt(simulation=simulation, owner=student)
    assert attempt.frozen_definition["questions"][0]["annulled"] is False
    Annulment.objects.filter(pk=annulment.pk).update(effective_at=timezone.now() - timedelta(seconds=1))
    submit_attempt(attempt_id=attempt.pk, owner=student)
    successor = create_attempt(simulation=simulation, owner=student)
    assert successor.frozen_definition["questions"][0]["annulled"] is True
    attempt.refresh_from_db()
    assert attempt.frozen_definition["questions"][0]["annulled"] is False
