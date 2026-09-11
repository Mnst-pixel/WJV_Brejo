from uuid import uuid4

import pytest
from django.db import connection

from core.models import Flashcard, FlashcardReview
from core.personal_flashcards import create_card, review_card, update_card
from tests.test_second_phase_concurrency import parallel

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != 'postgresql', reason='Flashcard concurrency requires isolated PostgreSQL')]


def test_concurrent_creation_and_review_replay(student):
    values = {'front': 'Question', 'back': 'Answer', 'creation_key': uuid4()}
    result = parallel(student, [lambda user: create_card(user, values) for _ in range(2)])
    assert [item[0] for item in result] == ['ok', 'ok'] and result[0][1] == result[1][1]
    card = Flashcard.objects.get(owner=student)
    review = {'rating': 3, 'expected_version': 1, 'idempotency_key': uuid4()}
    result = parallel(student, [lambda user: review_card(user, card.pk, review) for _ in range(2)])
    assert [item[0] for item in result] == ['ok', 'ok'] and result[0][1] == result[1][1]
    assert FlashcardReview.objects.count() == 1


def test_concurrent_review_and_edit_never_grade_unseen_text(student):
    card = Flashcard.objects.create(owner=student, front='Original', back='Answer')
    result = parallel(student, [lambda user: review_card(user, card.pk, {'rating': 3, 'expected_version': 1, 'idempotency_key': uuid4()}),
                               lambda user: update_card(user, card.pk, {'front': 'Changed', 'expected_version': 1})])
    assert sorted(item[0] for item in result) == ['conflict', 'ok']
    card.refresh_from_db()
    assert card.version == 2
    assert not FlashcardReview.objects.exists() if card.front == 'Changed' else FlashcardReview.objects.get().snapshot['front'] == 'Original'
