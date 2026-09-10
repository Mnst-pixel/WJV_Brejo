"""Historical schema exercise on synthetic data; PostgreSQL is the release gate."""
import uuid

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
        exam = old.get_model("core", "Exam").objects.create(title="Synthetic", edition="test", exam_date=timezone.localdate(), official_source_url="https://example.invalid", created_by_id=user.pk)
        phase = old.get_model("core", "ExamPhase").objects.create(exam_id=exam.pk, phase=1)
        simulation = old.get_model("core", "Simulation").objects.create(owner_id=user.pk, exam_phase_id=phase.pk, title="Synthetic", mode="formal")
        attempt = old.get_model("core", "Attempt").objects.create(owner_id=user.pk, simulation_id=simulation.pk, elapsed_seconds=123, version=2)
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        from core.models import Attempt, User
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
    finally:
        MigrationExecutor(connection).migrate(latest)
