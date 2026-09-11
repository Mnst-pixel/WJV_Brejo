from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from core.exceptions import Conflict
from core.models import Attempt, Simulation, User
from core.services.attempts import create_attempt
from tests.test_question_editorial import published, question_setup as setup_fixture

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != "postgresql", reason="Concurrent formal admission requires isolated PostgreSQL")]


@pytest.fixture
def question_setup():
    return setup_fixture.__wrapped__()


def test_two_formal_starts_admit_exactly_one(question_setup, student):
    workflow = published(question_setup)
    simulation = Simulation.objects.create(owner=student, exam_phase=question_setup["phase"], mode="formal", title="Teste concorrente",
        question_ids=[str(workflow.version.question_id)], duration_minutes=60)
    barrier = Barrier(2)

    def start(index):
        close_old_connections()
        try:
            user = User.objects.get(pk=student.pk)
            local_simulation = Simulation.objects.get(pk=simulation.pk)
            barrier.wait(timeout=10)
            try:
                create_attempt(owner=user, simulation=local_simulation, idempotency_key=f"parallel-formal-{index}")
                return "created"
            except Conflict:
                return "blocked"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(start, range(2)))
    assert sorted(results) == ["blocked", "created"]
    assert Attempt.objects.filter(owner=student, status="active").count() == 1
