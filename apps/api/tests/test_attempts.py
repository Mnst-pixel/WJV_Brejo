import pytest
from django.utils import timezone

from core.models import Alternative, Attempt, Exam, ExamPhase, Question, QuestionVersion, Simulation, Subject
from core.services.attempts import autosave_attempt


@pytest.fixture
def formal_attempt(student):
    subject = Subject.objects.create(slug="constitucional", name="Constitucional")
    exam = Exam.objects.create(
        title="Exame teste",
        edition="T-1",
        exam_date=timezone.localdate(),
        official_source_url="https://example.invalid/exam",
        created_by=student,
    )
    phase = ExamPhase.objects.create(exam=exam, phase=1)
    question = Question.objects.create(exam_phase=phase, subject=subject, number=1)
    version = QuestionVersion.objects.create(
        question=question,
        version_number=1,
        original_text="Enunciado",
        statement="Enunciado",
        retrieved_at=timezone.now(),
        source_url="https://example.invalid/question",
        source_hash="c" * 64,
    )
    question.current_version = version
    question.save(update_fields=["current_version", "updated_at"])
    alternative = Alternative.objects.create(question_version=version, label="A", text="Alternativa", order=1)
    simulation = Simulation.objects.create(owner=student, exam_phase=phase, mode="formal", title="Formal", question_ids=[str(question.id)])
    return Attempt.objects.create(owner=student, simulation=simulation), question, alternative


@pytest.mark.django_db
def test_autosave_is_persistent_and_optimistic(student, formal_attempt):
    attempt, question, alternative = formal_attempt
    saved = autosave_attempt(
        attempt_id=attempt.id,
        owner=student,
        expected_version=1,
        answers=[{"question": str(question.id), "selected_alternative": str(alternative.id)}],
        elapsed_seconds=45,
    )
    assert saved.version == 2
    assert saved.answers.get(question=question).selected_alternative == alternative
    assert saved.checkpoints.get(version=2).snapshot["elapsed_seconds"] == 45


@pytest.mark.django_db
def test_formal_mode_blocks_ai_before_submission(student, formal_attempt, client_for):
    attempt, _, _ = formal_attempt
    response = client_for(student).post(
        "/api/ai/consult",
        {"question": "Qual é a resposta?", "action": "explain", "context": {"attempt_id": str(attempt.id)}},
        format="json",
    )
    assert response.status_code == 403
