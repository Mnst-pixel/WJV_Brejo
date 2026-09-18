from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Alternative, Attempt, AttemptAnswer, Exam, ExamPhase, Flashcard, FlashcardReview, Goal, Question, QuestionVersion, Simulation, Subject
from core.study_models import StudyActivity

pytestmark = pytest.mark.django_db


def payload(**extra):
    today = timezone.localdate()
    return {"title": "Revisar com constância", "metric": "questions", "target_value": 10,
            "start_date": str(today - timedelta(days=2)), "target_date": str(today), "creation_key": str(uuid4()), **extra}


def create(client, **extra):
    response = client.post('/api/goals/', payload(**extra), format='json')
    assert response.status_code == 201, response.data
    return response.json()


def test_creation_replay_conflict_owned_archive_and_limits(student, other_student, client_for):
    client = client_for(student)
    values = payload(expected_owner=str(student.pk))
    first = client.post('/api/goals/', values, format='json').json()
    path = f'/api/goals/{first["id"]}/'
    assert first['progress'] == 0 and not first['achieved'] and first['completed_at'] is None
    assert client.post('/api/goals/', values, format='json').json()['id'] == first['id']
    assert Goal.objects.count() == 1
    assert client.post('/api/goals/', {**values, 'target_value': 20}, format='json').status_code == 409
    assert client.patch(path, {'title': 'Revisar mais', 'expected_version': 1}, format='json').json()['version'] == 2
    assert client.patch(path, {'title': 'Perdida', 'expected_version': 1}, format='json').status_code == 409
    assert client.patch(path, {'title': 'Sem versão'}, format='json').status_code == 400
    assert client.post('/api/goals/', values, format='json').json()['title'] == 'Revisar mais'
    assert client.patch(path, {'title': 'Revisar mais', 'expected_version': 2}, format='json').json()['version'] == 2
    assert client.patch(path, {'expected_owner': str(other_student.pk), 'expected_version': 2}, format='json').status_code == 403
    assert client.patch(path, {'archived': True, 'expected_version': 2}, format='json').json()['archived_at']
    assert client.get('/api/goals/').json()['count'] == 0
    assert client.get('/api/goals/?mode=archived').json()['count'] == 1
    assert client.delete(path).status_code == 405
    assert client_for(other_student).get(path).status_code == 404
    assert client_for(other_student).patch(path, {'progress': 100}, format='json').status_code == 404
    assert client_for(other_student).get('/api/goals/', {'mode': 'all', 'creation_key': values['creation_key']}).json()['count'] == 0
    assert client_for(other_student).post('/api/goals/', values, format='json').status_code == 403
    for params in [{'mode': 'invalid'}, {'creation_key': 'invalid'}, {'q': 'x' * 151}]:
        assert client.get('/api/goals/', params).status_code == 400
    assert client.get('/api/goals/not-a-uuid/').status_code == 404


@pytest.mark.parametrize('extra', [
    {'target_value': 0}, {'target_value': 100001}, {'start_date': None}, {'target_date': None},
    {'start_date': '2026-12-31', 'target_date': '2026-01-01'}, {'start_date': '2025-01-01', 'target_date': '2027-01-01'},
    {'progress': 100}, {'progress': 0}, {'priority': 0}, {'priority': 4}, {'metric': 'invented'},
    {'measured_value': 1000}, {'version': 2}, {'completed_at': '2026-09-01T00:00:00Z'}, {'archived': True},
    {'description': 'x' * 5001}, {'title': ' '},
])
def test_invalid_quantitative_input_is_rejected(student, client_for, extra):
    assert client_for(student).post('/api/goals/', payload(**extra), format='json').status_code == 400
    assert not Goal.objects.exists()


def fixtures(owner):
    subject = Subject.objects.create(name='Ética', slug='goals-ethics')
    exam = Exam.objects.create(title='Synthetic', edition='test', exam_date=timezone.localdate(), created_by=owner)
    phase = ExamPhase.objects.create(exam=exam, phase=1)
    question = Question.objects.create(exam_phase=phase, subject=subject, number=1)
    version = QuestionVersion.objects.create(question=question, statement='Synthetic', version_number=1, retrieved_at=timezone.now())
    alternative = Alternative.objects.create(question_version=version, label='A', text='Synthetic', order=1)
    simulation = Simulation.objects.create(owner=owner, exam_phase=phase, title='Synthetic', mode='formal')
    return subject, question, alternative, simulation


def test_questions_count_only_owned_final_answers_in_window(student, other_student, client_for):
    subject, question, alternative, simulation = fixtures(student)
    today = timezone.now()
    for owner, status, when, selected in [(student, 'graded', today, True), (student, 'submitted', today, True),
            (student, 'active', None, True), (student, 'graded', today, False), (other_student, 'graded', today, True),
            (student, 'graded', today - timedelta(days=5), True), (student, 'graded', today + timedelta(days=1), True)]:
        attempt = Attempt.objects.create(owner=owner, simulation=simulation, status=status, submitted_at=when)
        AttemptAnswer.objects.create(attempt=attempt, question=question, selected_alternative=alternative if selected else None)
    client = client_for(student)
    goal = create(client, subject=str(subject.pk), target_value=2)
    assert goal['measured_value'] == 2 and goal['progress'] == 100 and goal['achieved']
    assert goal['subject_name'] == 'Ética' and goal['completed_at'] is None
    other = Subject.objects.create(name='Civil', slug='goals-civil')
    assert create(client, subject=str(other.pk))['measured_value'] == 0
    assert create(client)['measured_value'] == 2
    assert client.get('/api/goals/?mode=achieved').json()['count'] == 1
    assert client.get('/api/goals/?mode=incomplete').json()['count'] == 2
    stored = Goal.objects.get(pk=goal['id'])
    assert stored.progress == 0 and stored.completed_at is None and stored.version == 1


def test_minutes_and_reviews_are_derived_without_get_writes(student, other_student, client_for):
    now = timezone.now()
    for owner, seconds, when in [(student, 90, now), (student, 60, now), (other_student, 999, now), (student, 1000, now - timedelta(days=5))]:
        StudyActivity.objects.create(owner=owner, event_key=str(uuid4()), kind='reading', duration_seconds=seconds, occurred_at=when, payload_hash='a' * 64)
    client = client_for(student)
    value = create(client, metric='study_minutes', target_value=5)
    assert value['measured_value'] == 2.5 and value['progress'] == 50
    card = Flashcard.objects.create(owner=student, front='A', back='B')
    FlashcardReview.objects.create(owner=student, flashcard=card, rating=3, next_review_at=now)
    foreign = Flashcard.objects.create(owner=other_student, front='C', back='D')
    FlashcardReview.objects.create(owner=other_student, flashcard=foreign, rating=3, next_review_at=now)
    review_goal = create(client, metric='flashcard_reviews', target_value=1)
    assert review_goal['measured_value'] == 1 and review_goal['achieved']
    before = list(Goal.objects.values())
    assert client.get('/api/goals/').status_code == 200
    assert list(Goal.objects.values()) == before


def test_simulations_exclude_practice_and_include_formal_written(student, client_for):
    from core.models import PracticalCase, PracticalCaseVersion
    from core.second_phase_models import WrittenSubmission
    _, _, _, simulation = fixtures(student)
    for key, status in [(None, 'submitted'), ('practice:synthetic', 'graded'), (None, 'active')]:
        Attempt.objects.create(owner=student, simulation=simulation, status=status, submitted_at=timezone.now() if status != 'active' else None, idempotency_key=key)
    case = PracticalCase.objects.create(exam_phase=simulation.exam_phase, title='Synthetic')
    version = PracticalCaseVersion.objects.create(practical_case=case, version_number=1, prompt='Synthetic', retrieved_at=timezone.now())
    for mode in ['formal', 'training']:
        WrittenSubmission.objects.create(owner=student, case_version=version, mode=mode, status='submitted', submitted_at=timezone.now(), final_hash='a' * 64, request_id=uuid4(), frozen_definition={})
    assert create(client_for(student), metric='simulations')['measured_value'] == 2


def test_goal_constraints_and_manual_transition(student, client_for):
    base = dict(owner=student, title='Synthetic', metric='questions', target_value=1, start_date=timezone.localdate(), target_date=timezone.localdate())
    for extra in [{'target_value': 0}, {'target_value': None}, {'progress': 1}, {'completed_at': timezone.now()}, {'priority': 0}, {'version': 0}, {'metric': 'fake'}]:
        with pytest.raises(IntegrityError), transaction.atomic():
            Goal.objects.create(**(base | extra))
    client = client_for(student)
    manual = client.post('/api/goals/', {'title': 'Manual antiga', 'progress': 65}, format='json').json()
    path = f'/api/goals/{manual["id"]}/'
    assert client.patch(path, {'metric': 'questions', 'expected_version': 1}, format='json').status_code == 400
    assert client.patch(path, {'progress': 100, 'expected_version': 1}, format='json').json()['achieved']


def test_dashboard_ignores_achieved_and_archived_goals(student, client_for):
    client = client_for(student)
    value = create(client, metric='study_minutes', target_value=1)
    assert client.get('/api/study/dashboard/').json()['next_step']['kind'] == 'goal'
    StudyActivity.objects.create(owner=student, event_key=str(uuid4()), kind='reading', duration_seconds=60, occurred_at=timezone.now(), payload_hash='a' * 64)
    assert client.get('/api/study/dashboard/').json()['next_step']['kind'] != 'goal'
    client.patch(f'/api/goals/{value["id"]}/', {'target_value': 2, 'archived': True, 'expected_version': 1}, format='json')
    assert client.get('/api/study/dashboard/').json()['next_step']['kind'] != 'goal'
