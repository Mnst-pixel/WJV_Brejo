"""Additional user-owned study state; existing notes/goals/cards remain canonical."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .models import OwnedModel, StudySession

TARGETS = ("content", "question", "topic", "document_version")
MARK_KINDS = ("highlight", "review", "question", "memorize", "exam")
ACTIVITY_KINDS = ("reading", "review", "practice", "pomodoro")


class StudyProgress(OwnedModel):
    target_kind = models.CharField(max_length=32)
    target_id = models.UUIDField()
    percent = models.PositiveSmallIntegerField(default=0)
    position = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "target_kind", "target_id"],
                name="study_progress_owner_target",
            ),
            models.CheckConstraint(
                condition=Q(percent__lte=100), name="study_progress_percent"
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="study_progress_version"
            ),
            models.CheckConstraint(
                condition=Q(target_kind__in=TARGETS), name="study_progress_target_kind"
            ),
        ]


class StudyMark(OwnedModel):
    target_kind = models.CharField(max_length=32)
    target_id = models.UUIDField()
    locator = models.CharField(max_length=512)
    kind = models.CharField(max_length=20)
    annotation = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "target_kind", "target_id", "locator", "kind"],
                name="study_mark_owner_location",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=MARK_KINDS), name="study_mark_kind"
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="study_mark_version"
            ),
            models.CheckConstraint(
                condition=Q(target_kind__in=TARGETS), name="study_mark_target_kind"
            ),
        ]


class StudyActivity(OwnedModel):
    event_key = models.CharField(max_length=96)
    kind = models.CharField(max_length=20)
    occurred_at = models.DateTimeField()
    duration_seconds = models.PositiveIntegerField(default=0)
    payload_hash = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "event_key"], name="study_activity_owner_event"
            ),
            models.CheckConstraint(
                condition=Q(kind__in=ACTIVITY_KINDS), name="study_activity_kind"
            ),
            models.CheckConstraint(
                condition=Q(duration_seconds__lte=86400), name="study_activity_duration"
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner", "-occurred_at"], name="study_activity_owner_time"
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Atividades são imutáveis.")
        return super().save(*args, **kwargs)


class StudyPanelState(OwnedModel):
    # One state per account, independent of device/browser.
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="study_panel_state",
    )
    last_panel = models.CharField(max_length=64, default="dashboard")
    pomodoro_status = models.CharField(max_length=12, default="idle")
    remaining_seconds = models.PositiveIntegerField(default=1500)
    timer_updated_at = models.DateTimeField(null=True, blank=True)
    study_session = models.ForeignKey(
        StudySession, null=True, blank=True, on_delete=models.PROTECT
    )
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(pomodoro_status__in=["idle", "running", "paused"]),
                name="study_panel_timer_state",
            ),
            models.CheckConstraint(
                condition=Q(remaining_seconds__lte=86400),
                name="study_panel_timer_limit",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1), name="study_panel_version"
            ),
        ]


class BrowserImportReceipt(OwnedModel):
    source_key = models.CharField(max_length=64)
    source_hash = models.CharField(max_length=64)
    source_data = models.JSONField()
    status = models.CharField(max_length=32, default="staged_unverified")
    result = models.JSONField(default=dict)
    provenance = models.CharField(max_length=80, default="authenticated_browser_export")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "source_key", "source_hash"],
                name="browser_import_owner_source",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["staged_unverified", "imported_personal"]),
                name="browser_import_status",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Recibos de importação são imutáveis.")
        return super().save(*args, **kwargs)
