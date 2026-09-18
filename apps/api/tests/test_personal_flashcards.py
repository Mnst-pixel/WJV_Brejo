from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Flashcard, FlashcardReview, Role, Subject, Topic, UserRole
from core.personal_flashcards import INTERVALS, review_card

pytestmark = pytest.mark.django_db


def create(client, **extra):
    value = client.post('/api/flashcards/', {'front': 'Pergunta pessoal', 'back': 'Minha resposta\n  ', 'creation_key': str(uuid4()), **extra}, format='json')
    assert value.status_code == 201, value.data
    return value.json()


def test_creation_replay_edit_conflict_archive_and_owned_history(student, other_student, client_for):
    client = client_for(student)
    key = str(uuid4())
    card = create(client, creation_key=key, expected_owner=str(student.pk))
    url = f'/api/flashcards/{card["id"]}/'
    payload = {'front': 'Pergunta pessoal', 'back': 'Minha resposta\n  ', 'creation_key': key}
    assert client.post('/api/flashcards/', payload, format='json').json()['id'] == card['id']
    assert client.post('/api/flashcards/', {**payload, 'front': 'Different'}, format='json').status_code == 409
    assert Flashcard.objects.count() == 1
    assert client.patch(url, {'back': 'New', 'expected_version': 1}, format='json').json()['version'] == 2
    assert client.patch(url, {'back': 'Lost update', 'expected_version': 1}, format='json').status_code == 409
    assert client.post('/api/flashcards/', payload, format='json').json()['back'] == 'New'
    assert client.patch(url, {'back': 'New', 'expected_version': 2}, format='json').json()['version'] == 2
    assert client.patch(url, {'archived': True, 'expected_version': 2}, format='json').json()['archived_at']
    assert client.get('/api/flashcards/').json()['count'] == 0
    assert client.get('/api/flashcards/', {'mode': 'archived'}).json()['count'] == 1
    assert client.get(url).status_code == 200
    assert client.delete(url).status_code == 405
    other = client_for(other_student)
    assert other.get(url).status_code == other.get(url + 'history/').status_code == 404
    assert other.patch(url, {'back': 'stolen', 'expected_version': 3}, format='json').status_code == 404
    assert other.get('/api/flashcards/', {'mode': 'all', 'creation_key': key}).json()['count'] == 0
    assert other.post('/api/flashcards/', {**payload, 'expected_owner': str(student.pk)}, format='json').status_code == 403


@pytest.mark.parametrize('rating', [1, 2, 3, 4, 5])
def test_server_schedule_and_immutable_replay_after_edit(student, client_for, rating):
    client = client_for(student)
    card = create(client)
    url = f'/api/flashcards/{card["id"]}/'
    payload = {'rating': rating, 'expected_version': 1, 'idempotency_key': str(uuid4()), 'expected_owner': str(student.pk)}
    before = timezone.now()
    value = client.post(url + 'review/', payload, format='json')
    assert value.status_code == 200
    receipt = FlashcardReview.objects.get(pk=value.json()['id'])
    assert before + INTERVALS[rating] <= receipt.next_review_at <= timezone.now() + INTERVALS[rating]
    assert receipt.snapshot['front'] == card['front'] and receipt.snapshot['back'] == card['back']
    assert receipt.snapshot['reference_status'] == 'personal_unverified'
    assert receipt.snapshot['schedule'] == 'fixed-recall-v1'
    assert client.get(url).json()['version'] == 2
    assert client.get('/api/flashcards/', {'mode': 'due'}).json()['count'] == 0
    assert client.post(url + 'review/', payload, format='json').json() == value.json()
    assert client.post(url + 'review/', {**payload, 'rating': (rating % 5) + 1}, format='json').status_code == 409
    assert client.post(url + 'review/', {**payload, 'idempotency_key': str(uuid4())}, format='json').status_code == 409
    assert client.patch(url, {'front': 'Changed', 'expected_version': 2}, format='json').status_code == 200
    assert client.get(url).json()['next_review_at'] is None
    assert client.get('/api/flashcards/', {'mode': 'due'}).json()['count'] == 1
    assert client.post(url + 'review/', payload, format='json').json() == value.json()
    assert client.get(url + 'history/').json()['results'] == [value.json()]
    assert FlashcardReview.objects.count() == 1


def test_reviews_require_ownership_active_card_and_stable_account(student, other_student, client_for):
    client = client_for(student)
    card = create(client)
    url = f'/api/flashcards/{card["id"]}/'
    payload = {'rating': 3, 'expected_version': 1, 'idempotency_key': str(uuid4())}
    assert client.post('/api/flashcards/invalid/review/', payload, format='json').status_code == 404
    assert client_for(other_student).post(url + 'review/', payload, format='json').status_code == 404
    assert client.post(url + 'review/', {**payload, 'expected_owner': str(other_student.pk)}, format='json').status_code == 403
    assert client.patch(url, {'archived': True, 'expected_version': 1}, format='json').status_code == 200
    assert client.post(url + 'review/', {**payload, 'expected_version': 2}, format='json').status_code == 400
    assert client.patch(url, {'archived': False, 'expected_version': 2}, format='json').status_code == 200
    assert client.post(url + 'review/', {**payload, 'expected_version': 3}, format='json').status_code == 200
    second = create(client)
    assert client.post(f'/api/flashcards/{second["id"]}/review/', {**payload, 'expected_version': 3}, format='json').status_code == 409


@pytest.mark.parametrize('values', [{'rating': 0}, {'rating': 6}, {'rating': 'invalid'}, {'next_review_at': '2099-01-01'}, {'snapshot': {}}, {'owner': str(uuid4())}, {'idempotency_key': None}, {'expected_version': 0}])
def test_review_cannot_forge_score_schedule_or_identity(student, client_for, values):
    client = client_for(student)
    card = create(client)
    result = client.post(f'/api/flashcards/{card["id"]}/review/', {'rating': 3, 'expected_version': 1, 'idempotency_key': str(uuid4()), **values}, format='json')
    assert result.status_code == 400
    assert not FlashcardReview.objects.exists()


def test_taxonomy_filters_and_limits(student, client_for):
    client = client_for(student)
    subject = Subject.objects.create(name='Direito', slug='cards-law')
    other = Subject.objects.create(name='Outra', slug='cards-other')
    topic = Topic.objects.create(subject=subject, name='Tema', slug='cards-topic')
    assert client.post('/api/flashcards/', {'front': 'x', 'back': 'y', 'topic': str(topic.pk)}, format='json').status_code == 400
    card = create(client, subject=str(subject.pk), topic=str(topic.pk))
    assert client.patch(f'/api/flashcards/{card["id"]}/', {'subject': str(other.pk), 'expected_version': 1}, format='json').status_code == 400
    for params in [{'mode': 'invalid'}, {'q': 'x' * 151}, {'subject': 'bad'}, {'topic': 'bad'}, {'creation_key': 'bad'}]:
        assert client.get('/api/flashcards/', params).status_code == 400
    assert client.get('/api/flashcards/', {'subject': str(subject.pk), 'q': 'pessoal'}).json()['count'] == 1
    for values in [{'front': ' '}, {'back': '\n'}, {'front': 'x' * 10001}, {'back': 'y' * 20001}, {'source_reference': 'a' * 2001}, {'version': 100}, {'next_review_at': None}]:
        assert client.post('/api/flashcards/', {'front': 'x', 'back': 'y', **values}, format='json').status_code == 400


def test_revoked_study_role_and_machine_cannot_review(student, client_for):
    from rest_framework.exceptions import PermissionDenied
    card = Flashcard.objects.create(owner=student, front='private', back='answer')
    UserRole.objects.filter(user=student).delete()
    with pytest.raises(PermissionDenied):
        review_card(student, card.pk, {'rating': 1, 'expected_version': 1, 'idempotency_key': uuid4()})
    UserRole.objects.create(user=student, role=Role.objects.get(slug='conta-de-servico'), granted_by=student)
    assert client_for(student).get('/api/flashcards/').status_code == 403


def test_database_constraints_and_partitioned_keys(student, other_student):
    key = uuid4()
    card = Flashcard.objects.create(owner=student, front='f', back='b', creation_key=key)
    with pytest.raises(IntegrityError), transaction.atomic():
        Flashcard.objects.create(owner=student, front='f', back='b', creation_key=key)
    Flashcard.objects.create(owner=other_student, front='other', back='private', creation_key=key)
    with pytest.raises(IntegrityError), transaction.atomic():
        Flashcard.objects.filter(pk=card.pk).update(version=0)
    receipt = dict(owner=student, flashcard=card, rating=3, next_review_at=timezone.now() + timedelta(days=3), idempotency_key=key)
    FlashcardReview.objects.create(**receipt)
    with pytest.raises(IntegrityError), transaction.atomic():
        FlashcardReview.objects.create(**receipt)
    with pytest.raises(IntegrityError), transaction.atomic():
        FlashcardReview.objects.create(**{**receipt, 'idempotency_key': uuid4(), 'card_version': 0})
