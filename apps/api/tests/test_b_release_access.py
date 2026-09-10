"""Independent regressions: authority revoked after request/serializer creation."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from rest_framework.exceptions import PermissionDenied

from core.models import Bookmark, FileAsset, StudyNote, User
from core.serializers import BookmarkSerializer, StudyNoteSerializer
from core.services import uploads
from core.views import BookmarkViewSet

pytestmark = pytest.mark.django_db


def revoke(user):
    User.objects.filter(pk=user.pk).update(session_version=user.session_version + 1)


def test_note_create_rechecks_actor_after_validation(student):
    serializer = StudyNoteSerializer(data={"title": "Private", "body": "Preserve authority"},
                                     context={"request": SimpleNamespace(user=student)})
    assert serializer.is_valid(), serializer.errors
    revoke(student)
    with pytest.raises(PermissionDenied):
        serializer.save()
    assert not StudyNote.objects.exists()


def test_note_update_rechecks_actor_and_preserves_version(student):
    note = StudyNote.objects.create(owner=student, title="Original", body="Untouched")
    serializer = StudyNoteSerializer(note, data={"body": "Forbidden", "expected_version": 1}, partial=True,
                                     context={"request": SimpleNamespace(user=student)})
    assert serializer.is_valid(), serializer.errors
    revoke(student)
    with pytest.raises(PermissionDenied):
        serializer.save()
    note.refresh_from_db()
    assert note.body == "Untouched" and note.version == 1


@pytest.mark.parametrize("read", [uploads.download_upload, uploads.open_download])
def test_private_file_read_rechecks_revocation_before_touching_storage(student, read):
    asset = FileAsset.objects.create(owner=student, original_name="private.txt", size_bytes=4,
                                    sha256="a" * 64, mime_type="text/plain", storage_key="private/test.txt",
                                    scan_status="clean", processing_status="processed_pending_review")
    revoke(student)
    with patch.object(uploads.default_storage, "exists", return_value=True) as exists:
        with pytest.raises(PermissionDenied):
            read(owner=student, asset_id=asset.pk)
        exists.assert_not_called()


@pytest.mark.parametrize("operation", ["create", "update", "destroy"])
def test_owned_view_mutation_rechecks_revocation(student, operation):
    view = BookmarkViewSet()
    view.request = SimpleNamespace(user=student)
    bookmark = Bookmark.objects.create(owner=student, target_type="content", target_id=uuid4(), label="Original")
    serializer = BookmarkSerializer(None if operation == "create" else bookmark,
                                    data={"target_type": "content", "target_id": str(uuid4()), "label": "Forbidden"},
                                    context={"request": view.request}, partial=operation != "create")
    assert serializer.is_valid(), serializer.errors
    revoke(student)
    with pytest.raises(PermissionDenied):
        getattr(view, "perform_" + operation)(bookmark if operation == "destroy" else serializer)
    bookmark.refresh_from_db()
    assert Bookmark.objects.count() == 1 and bookmark.label == "Original"


@pytest.mark.parametrize("operation", ["create", "autosave", "submit", "results"])
def test_attempt_commands_recheck_revocation_before_objects(student, operation):
    from core.services.attempts import create_attempt, autosave_attempt, submit_attempt, attempt_results
    revoke(student)
    with pytest.raises(PermissionDenied):
        if operation == "create":
            create_attempt(owner=student, simulation=SimpleNamespace(pk=uuid4()))
        elif operation == "autosave":
            autosave_attempt(owner=student, attempt_id=uuid4(), expected_version=1, answers=[], elapsed_seconds=0)
        elif operation == "submit":
            submit_attempt(owner=student, attempt_id=uuid4())
        else:
            attempt_results(owner=student, attempt_id=uuid4())


def test_private_download_rejects_size_change_and_closes_source(student):
    from django.core.files.base import ContentFile
    asset = FileAsset.objects.create(owner=student, original_name="private.txt", size_bytes=4,
                                    sha256="a" * 64, mime_type="text/plain", storage_key="private/test.txt",
                                    scan_status="clean", processing_status="processed_pending_review")
    source = ContentFile(b"changed file content")
    with patch.object(uploads.default_storage, "exists", return_value=True), patch.object(uploads.default_storage, "open", return_value=source):
        with pytest.raises(PermissionDenied, match="Integridade"):
            uploads.open_download(owner=student, asset_id=asset.pk)


def test_upload_throttle_applies_to_real_route_and_separates_users_metadata(student, other_student, client_for):
    from django.core.cache import cache
    cache.clear()
    try:
        client = client_for(student)
        for _ in range(12):
            assert client.post("/api/files/upload/", {}, format="multipart").status_code == 400
        assert client.post("/api/files/upload/", {}, format="multipart").status_code == 429
        assert client.get("/api/files/").status_code == 200
        assert client_for(other_student).post("/api/files/upload/", {}, format="multipart").status_code == 400
    finally:
        cache.clear()


def test_file_cache_failure_is_closed_redacted_and_does_not_block_study(student, client_for):
    from core import upload_throttling
    client = client_for(student)
    with patch.object(upload_throttling.cache, "add", side_effect=RuntimeError("synthetic-secret-value")):
        result = client.get("/api/files/")
        assert result.status_code == 503 and "synthetic-secret-value" not in str(result.data)
        assert client.get("/api/goals/").status_code == 200


def test_s3_spool_timeouts_and_parallel_buffers_are_bounded(settings):
    assert settings.AWS_S3_MAX_MEMORY_SIZE == 2 * 1024**2
    assert settings.AWS_S3_CLIENT_CONFIG.connect_timeout == 3
    assert settings.AWS_S3_CLIENT_CONFIG.read_timeout == 10
    assert settings.AWS_S3_TRANSFER_CONFIG.max_concurrency == 2
    assert settings.AWS_S3_TRANSFER_CONFIG.max_io_queue == 8


def test_simulation_title_edit_preserves_concurrent_question_selection(student):
    from django.utils import timezone
    from core.models import Exam, ExamPhase, Question, Simulation, Subject
    from core.serializers import SimulationSerializer
    subject = Subject.objects.create(slug="b-subject", name="Direito")
    exam = Exam.objects.create(title="Teste", edition="b-test", exam_date=timezone.localdate(),
                               official_source_url="https://example.invalid/exam", created_by=student)
    phase = ExamPhase.objects.create(exam=exam, phase=1)
    first = Question.objects.create(exam_phase=phase, subject=subject, number=1)
    second = Question.objects.create(exam_phase=phase, subject=subject, number=2)
    simulation = Simulation.objects.create(owner=student, exam_phase=phase, title="Original", mode="free", question_ids=[str(first.pk)])
    serializer = SimulationSerializer(simulation, data={"title": "Renamed"}, partial=True)
    assert serializer.is_valid(), serializer.errors
    Simulation.objects.filter(pk=simulation.pk).update(question_ids=[str(second.pk)])
    serializer.save()
    simulation.refresh_from_db()
    assert simulation.title == "Renamed" and simulation.question_ids == [str(second.pk)]
