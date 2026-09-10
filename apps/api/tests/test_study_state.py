from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, close_old_connections, connections, transaction
from django.urls import path
from django.utils import timezone

from core.models import (
    Content,
    Flashcard,
    Goal,
    StudyNote,
    StudySession,
    Subject,
    Topic,
)
from core.services.study_state import LEGACY_KEYS
from core.study_models import (
    BrowserImportReceipt,
    StudyActivity,
    StudyPanelState,
    StudyProgress,
)
from core.study_views import (
    BrowserImportView,
    StudyActivityView,
    StudyPanelView,
    StudyRecordView,
    StudySummaryView,
)

urlpatterns = [
    path("study/progress", StudyRecordView.as_view(kind="progress")),
    path("study/progress/<uuid:record_id>", StudyRecordView.as_view(kind="progress")),
    path("study/marks", StudyRecordView.as_view(kind="marks")),
    path("study/activities", StudyActivityView.as_view()),
    path("study/panel", StudyPanelView.as_view()),
    path("study/summary", StudySummaryView.as_view()),
    path("study/import", BrowserImportView.as_view()),
    path("study/import/<uuid:receipt_id>", BrowserImportView.as_view()),
]
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def urls(settings):
    settings.ROOT_URLCONF = __name__


@pytest.fixture
def target():
    subject = Subject.objects.create(slug="state-test", name="Estudo")
    return Topic.objects.create(subject=subject, slug="topic", name="Tópico")


def progress(target, **updates):
    return {
        "target_kind": "topic",
        "target_id": str(target.pk),
        "percent": 40,
        "position": 3,
        "expected_version": 0,
        **updates,
    }


def test_progress_is_canonical_cross_client_and_owned(
    student, other_student, client_for, target
):
    first = client_for(student).put("/study/progress", progress(target), format="json")
    assert first.status_code == 200
    assert first.data["version"] == 1
    assert (
        client_for(student).get("/study/progress").data["results"][0]["percent"] == 40
    )
    assert client_for(other_student).get("/study/progress").data["results"] == []
    assert (
        client_for(other_student).get(f"/study/progress/{first.data['id']}").status_code
        == 404
    )
    assert first["Cache-Control"] == "no-store"


def test_progress_optimistic_conflict_preserves_newer_state(
    student, client_for, target
):
    client = client_for(student)
    assert (
        client.put("/study/progress", progress(target), format="json").status_code
        == 200
    )
    assert (
        client.put(
            "/study/progress",
            progress(target, percent=80, expected_version=1),
            format="json",
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/study/progress",
            progress(target, percent=10, expected_version=1),
            format="json",
        ).status_code
        == 409
    )
    assert StudyProgress.objects.get().percent == 80


@pytest.mark.parametrize(
    "extra",
    [{"owner": "other"}, {"percent": 101}, {"position": -1}, {"target_kind": "secret"}],
)
def test_progress_rejects_invalid_or_authority_fields(
    student, client_for, target, extra
):
    assert (
        client_for(student)
        .put("/study/progress", progress(target, **extra), format="json")
        .status_code
        == 400
    )
    assert StudyProgress.objects.count() == 0


def test_marks_preserve_locator_and_annotation_with_version(
    student, client_for, target
):
    client = client_for(student)
    body = {
        "target_kind": "topic",
        "target_id": str(target.pk),
        "locator": "art. 5",
        "kind": "review",
        "annotation": "Rever fundamento",
        "expected_version": 0,
    }
    result = client.put("/study/marks", body, format="json")
    assert result.status_code == 200
    assert result.data["annotation"] == body["annotation"]
    assert (
        client.put(
            "/study/marks", {**body, "annotation": "stale"}, format="json"
        ).status_code
        == 409
    )


def test_activity_idempotency_and_statistics_are_per_user(
    student, other_student, client_for
):
    client = client_for(student)
    body = {
        "event_key": "pomo-event-1",
        "kind": "pomodoro",
        "occurred_at": timezone.now().isoformat(),
        "duration_seconds": 1500,
    }
    first = client.post("/study/activities", body, format="json")
    second = client.post("/study/activities", body, format="json")
    assert first.status_code == second.status_code == 201
    assert first.data["id"] == second.data["id"]
    assert (
        client.post(
            "/study/activities", {**body, "duration_seconds": 3000}, format="json"
        ).status_code
        == 409
    )
    assert StudyActivity.objects.count() == 1
    assert client.get("/study/summary").data["recorded_seconds"] == 1500
    assert client_for(other_student).get("/study/summary").data["recorded_seconds"] == 0


def test_activity_future_rejected(student, client_for):
    response = client_for(student).post(
        "/study/activities",
        {
            "event_key": "future",
            "kind": "reading",
            "occurred_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "duration_seconds": 60,
        },
        format="json",
    )
    assert response.status_code == 400


def test_panel_timer_uses_server_time_and_session_ownership(
    student, other_student, client_for
):
    foreign = StudySession.objects.create(
        owner=other_student, started_at=timezone.now()
    )
    client = client_for(student)
    body = {
        "last_panel": "pomodoro",
        "pomodoro_status": "running",
        "remaining_seconds": 1500,
        "expected_version": 0,
    }
    assert (
        client.put(
            "/study/panel", {**body, "study_session": str(foreign.pk)}, format="json"
        ).status_code
        == 404
    )
    assert client.put("/study/panel", body, format="json").status_code == 200
    state = StudyPanelState.objects.get()
    with patch(
        "core.study_views.timezone.now",
        return_value=state.timer_updated_at + timedelta(seconds=120),
    ):
        assert (
            client_for(student).get("/study/panel").data["effective_remaining_seconds"]
            == 1380
        )
    assert client.put("/study/panel", body, format="json").status_code == 409
    assert client_for(other_student).get("/study/panel").data["version"] == 0


def test_import_preview_then_confirm_is_non_destructive(student, client_for):
    original = StudyNote.objects.create(
        owner=student, title="Minha nota", body="Original"
    )
    client = client_for(student)
    body = {
        "source_key": "gaivota_notes",
        "data": [{"title": "Minha nota", "body": "Legado"}],
    }
    preview = client.post("/study/import", body, format="json")
    assert preview.status_code == 200 and preview.data["preview"]
    assert BrowserImportReceipt.objects.count() == 0 and StudyNote.objects.count() == 1
    confirmed = client.post("/study/import", {**body, "confirm": True}, format="json")
    assert confirmed.data["status"] == "imported_personal"
    original.refresh_from_db()
    assert original.body == "Original"
    assert StudyNote.objects.count() == 2
    again = client.post("/study/import", {**body, "confirm": True}, format="json")
    assert again.data["replayed"] and again.data["id"] == confirmed.data["id"]
    assert StudyNote.objects.count() == 2


@pytest.mark.parametrize(
    "key,data,model",
    [
        ("gaivota_metas", [{"title": "Meta", "description": "Alcançar"}], Goal),
        ("gaivota_flashcards", [{"front": "Pergunta", "back": "Resposta"}], Flashcard),
    ],
)
def test_personal_legacy_records_reuse_canonical_models(
    student, client_for, key, data, model
):
    response = client_for(student).post(
        "/study/import",
        {"source_key": key, "data": data, "confirm": True},
        format="json",
    )
    assert (
        response.status_code == 200 and response.data["status"] == "imported_personal"
    )
    assert model.objects.filter(owner=student).count() == 1


@pytest.mark.parametrize("key", sorted(LEGACY_KEYS))
def test_all_legacy_keys_preserved_without_automatic_legal_publication(
    student, client_for, key
):
    raw = {
        "unrecognized_shape": "legacy_unverified",
        "url": "file:///etc/passwd",
        "status": "published",
    }
    response = client_for(student).post(
        "/study/import",
        {"source_key": key, "data": raw, "confirm": True},
        format="json",
    )
    assert response.status_code == 200
    assert (
        response.data["status"] == "staged_unverified"
        and not response.data["legal_publication"]
    )
    assert BrowserImportReceipt.objects.get().source_data == raw
    assert Content.objects.count() == 0


def test_legacy_receipt_is_owner_isolated_and_immutable(
    student, other_student, client_for
):
    response = client_for(student).post(
        "/study/import",
        {"source_key": "gaivota_legis", "data": "private law note", "confirm": True},
        format="json",
    )
    receipt = BrowserImportReceipt.objects.get()
    assert (
        client_for(other_student).get(f"/study/import/{receipt.pk}").status_code == 404
    )
    assert (
        client_for(student).get(f"/study/import/{receipt.pk}").data["source_data"]
        == "private law note"
    )
    receipt.source_data = "changed"
    with pytest.raises(ModelValidationError):
        receipt.save()
    assert len(response.data["source_hash"]) == 64


def test_import_cannot_supply_owner_or_convert_malformed_notes(
    student, other_student, client_for
):
    client = client_for(student)
    body = {
        "source_key": "gaivota_notes",
        "data": [{"title": "X", "body": "Y", "owner": str(other_student.pk)}],
        "confirm": True,
    }
    assert (
        client.post(
            "/study/import", {**body, "owner": str(other_student.pk)}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.post("/study/import", body, format="json").data["status"]
        == "staged_unverified"
    )
    assert StudyNote.objects.count() == 0


def test_unknown_and_oversized_browser_payloads_rejected(student, client_for):
    client = client_for(student)
    assert (
        client.post(
            "/study/import",
            {"source_key": "DJANGO_SECRET_KEY", "data": {}, "confirm": True},
            format="json",
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/study/import",
            {"source_key": "gaivota_notes", "data": "x" * 300001, "confirm": True},
            format="json",
        ).status_code
        == 400
    )
    assert BrowserImportReceipt.objects.count() == 0


def test_identical_legacy_payload_does_not_cross_accounts(
    student, other_student, client_for
):
    body = {
        "source_key": "gaivota_notes",
        "data": [{"title": "X", "body": "Y"}],
        "confirm": True,
    }
    for user in (student, other_student):
        assert (
            client_for(user).post("/study/import", body, format="json").status_code
            == 200
        )
    assert BrowserImportReceipt.objects.count() == 2 and StudyNote.objects.count() == 2


def test_detail_routes_are_read_only(student, client_for, target):
    client = client_for(student)
    created = client.put("/study/progress", progress(target), format="json")
    assert (
        client.put(
            f"/study/progress/{created.data['id']}", progress(target), format="json"
        ).status_code
        == 405
    )
    receipt = client.post(
        "/study/import",
        {"source_key": "gaivota_legis", "data": {}, "confirm": True},
        format="json",
    )
    assert (
        client.post(
            f"/study/import/{receipt.data['id']}", {}, format="json"
        ).status_code
        == 405
    )


def test_database_rejects_impossible_progress(student, target):
    with pytest.raises(IntegrityError), transaction.atomic():
        StudyProgress.objects.create(
            owner=student, target_kind="topic", target_id=target.pk, percent=101
        )


@pytest.mark.skipif(
    not getattr(django_settings, "KAIROS_ISOLATED_INTEGRATION_TESTS", False),
    reason="Concurrent writes require isolated PostgreSQL",
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_progress_creation_has_one_winner(student, target, client_for):
    clients = [client_for(student), client_for(student)]
    barrier = Barrier(2)

    def save(client):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return client.put(
                "/study/progress", progress(target), format="json"
            ).status_code
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, client) for client in clients]
        assert sorted(future.result(timeout=30) for future in futures) == [200, 409]
    assert StudyProgress.objects.count() == 1


@pytest.mark.parametrize("change", ["session_version", "is_active", "roles", "deleted"])
def test_study_write_rechecks_access_after_lock(student, client_for, change):
    from core.models import User, UserRole
    from core.services import study_state
    client = client_for(student)
    original = study_state._lock

    def revoke_then_lock(user):
        if change == "session_version":
            User.objects.filter(pk=user.pk).update(session_version=user.session_version + 1)
        elif change == "is_active":
            User.objects.filter(pk=user.pk).update(is_active=False)
        elif change == "roles":
            UserRole.objects.filter(user=user).delete()
        else:
            UserRole.objects.filter(user=user).delete()
            User.objects.filter(pk=user.pk).delete()
        return original(user)

    with patch("core.services.study_state._lock", side_effect=revoke_then_lock):
        result = client.post("/study/activities", {"event_key": "revocation-race", "kind": "reading", "occurred_at": timezone.now().isoformat(), "duration_seconds": 60}, format="json")
    assert result.status_code == 403
    assert StudyActivity.objects.count() == 0


@pytest.mark.parametrize("offset", ["²", "١", "-1", "1.0", "", "9" * 9])
def test_study_page_invalid_offset_is_400(student, client_for, offset):
    response = client_for(student).get("/study/activities", {"offset": offset})
    assert response.status_code == 400
