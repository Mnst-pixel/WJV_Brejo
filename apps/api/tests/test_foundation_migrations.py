"""Historical schema exercise on synthetic data; PostgreSQL is the release gate."""
import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_legacy_attempt_preserved_and_machine_migration_reversible():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("core", "0001_initial")])
        old = executor.loader.project_state([("core", "0001_initial")]).apps
        user = old.get_model("core", "User").objects.create(username="migration-synthetic", password="!")
        note = old.get_model("core", "StudyNote").objects.create(owner_id=user.pk, title="Historical note", body="Exact text\n\n  ", version=9)
        card = old.get_model("core", "Flashcard").objects.create(owner_id=user.pk, front="Historical question", back="Exact answer\n  ", source_reference="Legacy personal source")
        due = timezone.now() + timedelta(days=14)
        review = old.get_model("core", "FlashcardReview").objects.create(owner_id=user.pk, flashcard_id=card.pk, rating=4, next_review_at=due)
        exam = old.get_model("core", "Exam").objects.create(title="Synthetic", edition="test", exam_date=timezone.localdate(), official_source_url="https://example.invalid", created_by_id=user.pk)
        phase = old.get_model("core", "ExamPhase").objects.create(exam_id=exam.pk, phase=1)
        simulation = old.get_model("core", "Simulation").objects.create(owner_id=user.pk, exam_phase_id=phase.pk, title="Synthetic", mode="formal")
        attempt = old.get_model("core", "Attempt").objects.create(owner_id=user.pk, simulation_id=simulation.pk, elapsed_seconds=123, version=2)
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        from core.models import Attempt, Flashcard, FlashcardReview, StudyNote, User
        def check_note():
            restored_note = StudyNote.objects.get(pk=note.pk)
            assert (restored_note.owner_id, restored_note.title, restored_note.body, restored_note.version, restored_note.created_at, restored_note.updated_at) == (user.pk, note.title, note.body, 9, note.created_at, note.updated_at)
            assert restored_note.content_version_id is None and restored_note.creation_key is None and restored_note.creation_payload_hash == ""
            restored_card = Flashcard.objects.get(pk=card.pk)
            assert (restored_card.owner_id, restored_card.front, restored_card.back, restored_card.source_reference, restored_card.created_at, restored_card.updated_at) == (user.pk, card.front, card.back, card.source_reference, card.created_at, card.updated_at)
            assert restored_card.next_review_at == due and restored_card.version == 1 and restored_card.creation_key is None
            restored_review = FlashcardReview.objects.get(pk=review.pk)
            assert restored_review.reviewed_at == review.reviewed_at and restored_review.next_review_at == due
            assert restored_review.snapshot == {} and restored_review.idempotency_key is None
        check_note()
        restored = Attempt.objects.get(pk=attempt.pk)
        assert restored.snapshot_origin == "legacy_unverified"
        assert restored.elapsed_seconds == 123 and restored.version == 2
        assert restored.result_snapshot == {} and restored.frozen_definition == {}
        identifier = uuid.uuid5(uuid.NAMESPACE_URL, "https://kairos.2-24-215-183.sslip.io/services/tool-client")
        machine = User.objects.get(pk=identifier)
        assert machine.is_active and not machine.is_staff and not machine.is_superuser
        assert not machine.has_usable_password()
        executor = MigrationExecutor(connection)
        executor.migrate([("core", "0002_attempt_foundation")])
        assert User.objects.get(pk=identifier).is_active is False
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        assert User.objects.get(pk=identifier).is_active is True
        assert Attempt.objects.get(pk=attempt.pk).elapsed_seconds == 123
        check_note()
    finally:
        MigrationExecutor(connection).migrate(latest)
