from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from core.exceptions import Conflict
from core.models import User
from core.second_phase_models import WrittenSubmission
from core.services.written_submissions import save_written, submit_written
from tests.test_second_phase import phase2_setup as setup_fixture, prepare, publish

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != "postgresql", reason="Written exam concurrency requires isolated PostgreSQL")]


@pytest.fixture
def phase2_setup():
    return setup_fixture.__wrapped__()


def parallel(student, actions):
    barrier = Barrier(len(actions))

    def run(action):
        close_old_connections()
        try:
            owner = User.objects.get(pk=student.pk)
            barrier.wait(timeout=10)
            try:
                result = action(owner)
                return "ok", result.pk
            except Conflict:
                return "conflict", None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        return list(executor.map(run, actions))


def test_concurrent_written_formal_admits_one(phase2_setup, student):
    publish(phase2_setup)
    result = parallel(student, [lambda owner: prepare(phase2_setup, owner, mode="formal") for _ in range(2)])
    assert sorted(item[0] for item in result) == ["conflict", "ok"]
    assert WrittenSubmission.objects.filter(owner=student, status="active").count() == 1


def test_concurrent_written_autosave_preserves_one_complete_version(phase2_setup, student):
    publish(phase2_setup)
    submission = prepare(phase2_setup, student)
    def save(owner, text):
        return save_written(owner=owner, submission_id=submission.pk, data={"version": 1, "responses": [{"target_code": "piece", "text": text}, {"target_code": "Q1", "text": text}]})
    result = parallel(student, [lambda owner: save(owner, "Primeira"), lambda owner: save(owner, "Segunda")])
    assert sorted(item[0] for item in result) == ["conflict", "ok"]
    assert len(set(submission.responses.values_list("text", flat=True))) == 1
    assert submission.checkpoints.count() == 1


def test_concurrent_written_finalization_is_idempotent(phase2_setup, student):
    publish(phase2_setup)
    submission = prepare(phase2_setup, student)
    result = parallel(student, [lambda owner: submit_written(owner=owner, submission_id=submission.pk) for _ in range(2)])
    assert [item[0] for item in result] == ["ok", "ok"]
    submission.refresh_from_db()
    assert submission.status == "submitted" and submission.version == 2 and len(submission.final_hash) == 64
