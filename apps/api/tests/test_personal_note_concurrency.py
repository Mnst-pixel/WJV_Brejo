from uuid import uuid4

import pytest
from django.db import connection

from core.models import StudyNote
from core.personal_notes import create_note, update_note
from tests.test_second_phase_concurrency import parallel

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != "postgresql", reason="Note concurrency requires isolated PostgreSQL")]


def test_concurrent_creation_keeps_one_receipt(student):
    values = {"title": "Retry", "body": "Canonical", "creation_key": uuid4()}
    result = parallel(student, [lambda owner: create_note(owner, values) for _ in range(2)])
    assert [item[0] for item in result] == ["ok", "ok"]
    assert result[0][1] == result[1][1] and StudyNote.objects.count() == 1


def test_concurrent_note_update_rejects_stale_text(student):
    note = StudyNote.objects.create(owner=student, title="Original", body="Initial")
    result = parallel(student, [lambda owner: update_note(owner, note.pk, {"body": "First", "expected_version": 1}), lambda owner: update_note(owner, note.pk, {"body": "Second", "expected_version": 1})])
    assert sorted(item[0] for item in result) == ["conflict", "ok"]
    note.refresh_from_db()
    assert note.version == 2 and note.body in {"First", "Second"}
