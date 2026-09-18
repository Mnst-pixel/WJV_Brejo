from uuid import uuid4

import pytest
from django.db import connection

from core.models import Goal
from core.personal_goals import create_goal, update_goal
from tests.test_second_phase_concurrency import parallel

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != 'postgresql', reason='Goal races require isolated PostgreSQL')]


def test_parallel_creation_returns_one_goal(student):
    values = {'title': 'Idempotent', 'creation_key': uuid4()}
    result = parallel(student, [lambda user: create_goal(user, values) for _ in range(2)])
    assert [item[0] for item in result] == ['ok', 'ok'] and result[0][1] == result[1][1]
    assert Goal.objects.filter(owner=student).count() == 1


def test_parallel_edit_and_archive_cannot_overwrite(student):
    goal = Goal.objects.create(owner=student, title='Original')
    result = parallel(student, [lambda user: update_goal(user, goal.pk, {'title': 'Changed', 'expected_version': 1}),
                               lambda user: update_goal(user, goal.pk, {'archived': True, 'expected_version': 1})])
    assert sorted(item[0] for item in result) == ['conflict', 'ok']
    goal.refresh_from_db()
    assert goal.version == 2
    assert (goal.title == 'Changed' and goal.archived_at is None) or (goal.title == 'Original' and goal.archived_at is not None)
