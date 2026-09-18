from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from core.models import StudyNote, Subject, Topic
from tests.test_learning import editorial as learning_fixture
from tests.test_content_workflow import transition

pytestmark = pytest.mark.django_db


@pytest.fixture
def editorial():
    return learning_fixture.__wrapped__()


def test_creation_retry_preserves_one_note_and_original_receipt(student, other_student, client_for):
    client = client_for(student)
    key = str(uuid4())
    payload = {"title": "Minha leitura", "body": "Texto exato\n\n  ", "creation_key": key, "expected_owner": str(student.pk)}
    first = client.post("/api/notes/", payload, format="json")
    assert first.status_code == 201
    note_id = first.json()["id"]
    assert first.json()["body"] == payload["body"] and first.json()["account_id"] == str(student.pk)
    assert client.post("/api/notes/", payload, format="json").json()["id"] == note_id
    assert StudyNote.objects.filter(owner=student).count() == 1
    assert client.post("/api/notes/", {**payload, "body": "Different creation"}, format="json").status_code == 409
    changed = client.patch(f"/api/notes/{note_id}/", {"body": "Updated", "expected_version": 1}, format="json")
    assert changed.status_code == 200 and changed.json()["version"] == 2
    assert client.delete(f"/api/notes/{note_id}/", {"expected_version": 1}, format="json").status_code == 405
    replay = client.post("/api/notes/", payload, format="json")
    assert replay.status_code == 201 and replay.json()["body"] == "Updated"
    assert client.get("/api/notes/", {"creation_key": key}).json()["results"][0]["id"] == note_id
    assert client_for(other_student).get("/api/notes/", {"creation_key": key}).json()["results"] == []
    wrong_account = client_for(other_student).post("/api/notes/", payload, format="json")
    assert wrong_account.status_code == 403
    assert not StudyNote.objects.filter(owner=other_student).exists()


def test_topic_subject_consistency_and_creation_identity_immutable(student, client_for):
    first = Subject.objects.create(name="Ética", slug="personal-ethics")
    second = Subject.objects.create(name="Civil", slug="personal-civil")
    topic = Topic.objects.create(subject=first, name="Deveres", slug="duties")
    client = client_for(student)
    payload = {"title": "Taxonomia", "body": "Test", "subject": str(second.pk), "topic": str(topic.pk), "creation_key": str(uuid4())}
    assert client.post("/api/notes/", payload, format="json").status_code == 400
    payload["subject"] = str(first.pk)
    result = client.post("/api/notes/", payload, format="json")
    assert result.status_code == 201
    url = f"/api/notes/{result.json()['id']}/"
    assert client.patch(url, {"subject": str(second.pk), "expected_version": 1}, format="json").status_code == 400
    assert client.patch(url, {"creation_key": str(uuid4()), "expected_version": 1}, format="json").status_code == 400
    assert client.patch(url, {"body": "Test", "expected_version": 1}, format="json").json()["version"] == 1
    assert client.get("/api/notes/", {"subject": str(first.pk), "q": "Taxonomia"}).json()["count"] == 1
    assert client.get("/api/notes/", {"subject": str(second.pk)}).json()["count"] == 0
    assert client.get("/api/notes/", {"subject": "invalid"}).status_code == 400
    assert client.get("/api/notes/", {"q": "a" * 151}).status_code == 400


def test_note_creation_key_constraint_and_account_partition(student, other_student):
    key = uuid4()
    StudyNote.objects.create(owner=student, creation_key=key, creation_payload_hash="a" * 64, title="one", body="a")
    with pytest.raises(IntegrityError), transaction.atomic():
        StudyNote.objects.create(owner=student, creation_key=key, creation_payload_hash="b" * 64, title="two", body="b")
    StudyNote.objects.create(owner=other_student, creation_key=key, title="other", body="b")
    StudyNote.objects.create(owner=student, title="legacy", body="c")
    StudyNote.objects.create(owner=student, title="legacy 2", body="d")
    assert StudyNote.objects.count() == 4


def test_account_changed_before_note_update_is_rejected(student, other_student, client_for):
    note = StudyNote.objects.create(owner=student, title="Private", body="Keep")
    response = client_for(student).patch(f"/api/notes/{note.pk}/", {"body": "Wrong account", "expected_version": 1, "expected_owner": str(other_student.pk)}, format="json")
    assert response.status_code == 403
    note.refresh_from_db()
    assert note.body == "Keep" and note.version == 1


def test_note_reference_requires_reviewed_publication_and_preserves_history(editorial, student, client_for):
    client = client_for(student)
    content, version = editorial[3:]
    payload = {"title": "Minha referência", "body": "Conclusão pessoal", "subject": str(content.subject_id), "content_version": str(version.pk), "creation_key": str(uuid4())}
    response = client.post("/api/notes/", payload, format="json")
    assert response.status_code == 201
    note = response.json()
    assert note["content_title"] == version.title
    transition(editorial[2], version, "archived")
    assert client.post("/api/notes/", {**payload, "creation_key": str(uuid4())}, format="json").status_code == 404
    assert client.post("/api/notes/", payload, format="json").json()["id"] == note["id"]
    updated = client.patch(f"/api/notes/{note['id']}/", {"body": "Minha nota histórica", "expected_version": 1, "content_version": str(version.pk)}, format="json")
    assert updated.status_code == 200 and updated.json()["content_version"] == str(version.pk)
    assert client.patch(f"/api/notes/{note['id']}/", {"subject": None, "expected_version": 2}, format="json").status_code == 400


def test_note_rejects_tampered_reference(editorial, student, client_for):
    from core.models import ContentVersion
    content, version = editorial[3:]
    ContentVersion.objects.filter(pk=version.pk).update(body="Unreviewed mutation")
    response = client_for(student).post("/api/notes/", {"title": "Invalid", "body": "Note", "subject": str(content.subject_id), "content_version": str(version.pk)}, format="json")
    assert response.status_code == 403 and not StudyNote.objects.exists()


def test_note_list_related_names_have_bounded_queries(editorial, student, client_for):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    content, version = editorial[3:]
    client = client_for(student)
    def measure():
        with CaptureQueriesContext(connection) as queries:
            response = client.get("/api/notes/")
        assert response.status_code == 200
        return len(queries)
    StudyNote.objects.create(owner=student, title="One", body="a", subject=content.subject, content_version=version)
    first = measure()
    StudyNote.objects.bulk_create([StudyNote(owner=student, title=f"Item {index}", body="b", subject=content.subject, content_version=version) for index in range(10)])
    assert measure() == first
