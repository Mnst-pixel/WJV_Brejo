"""Canonical user study commands and non-destructive browser recovery."""

import hashlib
import json
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit
from core.exceptions import Conflict
from core.models import (
    Flashcard,
    Goal,
    Question,
    StudyNote,
    StudySession,
    Topic,
)
from core.permissions import lock_study_user, user_has_permission
from core.study_models import (
    ACTIVITY_KINDS,
    MARK_KINDS,
    TARGETS,
    BrowserImportReceipt,
    StudyActivity,
    StudyMark,
    StudyPanelState,
    StudyProgress,
)

LEGACY_KEYS = frozenset(
    {
        "gaivota_activities",
        "gaivota_flashcards",
        "gaivota_hp_stats",
        "gaivota_last_panel",
        "gaivota_legis",
        "gaivota_marcacoes",
        "gaivota_marcacoes_meta",
        "gaivota_metas",
        "gaivota_notes",
        "gaivota_pomo_log",
        "gaivota_pomo_time_by_subj",
        "gaivota_pomo_times",
        "gaivota_pomo_today",
        "gaivota_soft_theme",
        "gaivota_uploads",
    }
)
PANELS = frozenset(
    {
        "dashboard",
        "homepage",
        "flashcards",
        "legis",
        "marcados",
        "metas",
        "notas",
        "oab-home",
        "pomodoro",
        "uploads",
        "consultor",
        "simulados",
        "materias",
        "dc5-bim",
        "dc5-quiz",
        "dc5-resumo",
        "di-bim",
        "di-quiz",
        "di-resumo",
        "prev-bim",
        "prev-quiz",
        "prev-resumo",
        "prev-silvio",
    }
)


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise ValidationError({"non_field_errors": ["Campos não permitidos."]})
        return super().to_internal_value(data)


class ProgressInput(StrictInput):
    target_kind = serializers.ChoiceField(choices=TARGETS)
    target_id = serializers.UUIDField()
    percent = serializers.IntegerField(min_value=0, max_value=100)
    position = serializers.IntegerField(min_value=0, max_value=10_000_000, default=0)
    expected_version = serializers.IntegerField(min_value=0)


class MarkInput(StrictInput):
    target_kind = serializers.ChoiceField(choices=TARGETS)
    target_id = serializers.UUIDField()
    locator = serializers.CharField(max_length=512)
    kind = serializers.ChoiceField(choices=MARK_KINDS)
    annotation = serializers.CharField(max_length=4000, allow_blank=True, default="")
    expected_version = serializers.IntegerField(min_value=0)


class ActivityInput(StrictInput):
    event_key = serializers.RegexField(r"^[A-Za-z0-9_-]{1,96}$")
    kind = serializers.ChoiceField(choices=ACTIVITY_KINDS)
    occurred_at = serializers.DateTimeField()
    duration_seconds = serializers.IntegerField(min_value=0, max_value=86400)


class PanelInput(StrictInput):
    last_panel = serializers.ChoiceField(choices=sorted(PANELS))
    pomodoro_status = serializers.ChoiceField(choices=["idle", "running", "paused"])
    remaining_seconds = serializers.IntegerField(min_value=0, max_value=86400)
    study_session = serializers.UUIDField(allow_null=True, default=None)
    expected_version = serializers.IntegerField(min_value=0)


def _validated(schema, data):
    serializer = schema(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _authorized(user):
    if not user_has_permission(user, "study.use"):
        raise PermissionDenied("Estudo não autorizado.")


def _target(kind, target_id):
    if kind == "content":
        from core.content_workflow import published_content
        query = published_content()
    elif kind == "question":
        query = Question.objects.filter(
            current_version__published_at__isnull=False,
            current_version__approved_by__isnull=False,
            current_version__approval_date__isnull=False,
        ).exclude(current_version__legal_status="legacy_unverified")
    elif kind == "document_version":
        from core.services.documents import published_document_versions
        query = published_document_versions()
    else:
        query = Topic.objects.all()
    get_object_or_404(query, pk=target_id)


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _lock(user):
    return lock_study_user(user)


@transaction.atomic
def save_record(*, user, kind, data):
    _authorized(user)
    schemas = {
        "progress": (ProgressInput, StudyProgress),
        "marks": (MarkInput, StudyMark),
    }
    if kind not in schemas:
        raise ValidationError("Registro inválido.")
    schema, model = schemas[kind]
    values = _validated(schema, data)
    _target(values["target_kind"], values["target_id"])
    expected = values.pop("expected_version")
    _lock(user)
    lookup = {
        "owner": user,
        "target_kind": values["target_kind"],
        "target_id": values["target_id"],
    }
    if kind == "marks":
        lookup.update(locator=values["locator"], kind=values["kind"])
    existing = model.objects.filter(**lookup).first()
    if expected != (existing.version if existing else 0):
        raise Conflict("Versão de estudo desatualizada.")
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        existing.version += 1
        existing.save()
        return existing
    if model.objects.filter(owner=user).count() >= 5000:
        raise ValidationError("Limite de registros de estudo atingido.")
    return model.objects.create(owner=user, **values)


@transaction.atomic
def record_activity(*, user, data):
    _authorized(user)
    values = _validated(ActivityInput, data)
    if values["occurred_at"] > timezone.now() + timedelta(minutes=5):
        raise ValidationError("Atividade não pode estar no futuro.")
    fingerprint = _fingerprint(
        {**values, "occurred_at": values["occurred_at"].isoformat()}
    )
    _lock(user)
    existing = StudyActivity.objects.filter(
        owner=user, event_key=values["event_key"]
    ).first()
    if existing:
        if existing.payload_hash != fingerprint:
            raise Conflict("Chave de atividade reutilizada com dados diferentes.")
        return existing
    if StudyActivity.objects.filter(owner=user).count() >= 50000:
        raise ValidationError("Limite de atividades atingido.")
    return StudyActivity.objects.create(owner=user, payload_hash=fingerprint, **values)


@transaction.atomic
def save_panel(*, user, data):
    _authorized(user)
    values = _validated(PanelInput, data)
    expected = values.pop("expected_version")
    session_id = values.pop("study_session")
    _lock(user)
    session = (
        get_object_or_404(StudySession, owner=user, pk=session_id)
        if session_id
        else None
    )
    current = StudyPanelState.objects.filter(owner=user).first()
    if expected != (current.version if current else 0):
        raise Conflict("Versão do painel desatualizada.")
    if current is None:
        return StudyPanelState.objects.create(
            owner=user, study_session=session, timer_updated_at=timezone.now(), **values
        )
    for key, value in values.items():
        setattr(current, key, value)
    current.study_session = session
    current.timer_updated_at = timezone.now()
    current.version += 1
    current.save()
    return current


def summary(user):
    _authorized(user)
    aggregate = StudyActivity.objects.filter(owner=user).aggregate(
        duration=Sum("duration_seconds")
    )
    return {
        "activities": StudyActivity.objects.filter(owner=user).count(),
        "recorded_seconds": aggregate["duration"] or 0,
        "notes": StudyNote.objects.filter(owner=user).count(),
        "goals": Goal.objects.filter(owner=user).count(),
        "flashcards": Flashcard.objects.filter(owner=user).count(),
        "sessions": StudySession.objects.filter(owner=user).count(),
        "completed_targets": StudyProgress.objects.filter(
            owner=user, percent=100
        ).count(),
    }


class ImportInput(StrictInput):
    source_key = serializers.ChoiceField(choices=sorted(LEGACY_KEYS))
    data = serializers.JSONField()
    confirm = serializers.BooleanField(default=False)


class PersonalNote(StrictInput):
    title = serializers.CharField(max_length=255)
    body = serializers.CharField(max_length=50000, allow_blank=True)


class PersonalGoal(StrictInput):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=4000, allow_blank=True, default="")


class PersonalCard(StrictInput):
    front = serializers.CharField(max_length=8000)
    back = serializers.CharField(max_length=8000)


def _personal_mapping(key, data):
    mapping = {
        "gaivota_notes": (PersonalNote, StudyNote),
        "gaivota_metas": (PersonalGoal, Goal),
        "gaivota_flashcards": (PersonalCard, Flashcard),
    }
    if key not in mapping or not isinstance(data, list) or not 1 <= len(data) <= 200:
        return None
    schema, model = mapping[key]
    try:
        return model, [_validated(schema, value) for value in data]
    except ValidationError:
        # Unknown legacy shape is retained for review rather than guessed.
        return None


@transaction.atomic
def import_browser(*, user, data, request=None):
    _authorized(user)
    values = _validated(ImportInput, data)
    raw, key = values["data"], values["source_key"]
    try:
        encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise ValidationError("Dados de origem inválidos.") from None
    if len(encoded.encode()) > 262144:
        raise ValidationError("Cada origem deve conter no máximo 256 KiB.")
    fingerprint = _fingerprint(raw)
    mapping = _personal_mapping(key, raw)
    status = "imported_personal" if mapping else "staged_unverified"
    preview = {
        "source_key": key,
        "source_hash": fingerprint,
        "status": status,
        "records": len(mapping[1]) if mapping else 0,
        "legal_publication": False,
    }
    if not values["confirm"]:
        return {**preview, "preview": True}
    _lock(user)
    existing = BrowserImportReceipt.objects.filter(
        owner=user, source_key=key, source_hash=fingerprint
    ).first()
    if existing:
        return {
            **preview,
            "id": str(existing.pk),
            "replayed": True,
            "result": existing.result,
        }
    if BrowserImportReceipt.objects.filter(owner=user).count() >= 200:
        raise ValidationError("Limite de lotes de importação atingido.")
    result = {"ids": [], "requires_review": mapping is None}
    if mapping:
        model, rows = mapping
        for row in rows:
            # Identical existing personal records are reused; never update them.
            obj = model.objects.filter(owner=user, **row).first()
            if obj is None:
                obj = model.objects.create(owner=user, **row)
            result["ids"].append(str(obj.pk))
    receipt = BrowserImportReceipt.objects.create(
        owner=user,
        source_key=key,
        source_hash=fingerprint,
        source_data=raw,
        status=status,
        result=result,
    )
    record_audit(
        "study.browser.imported",
        actor=user,
        request=request,
        target=receipt,
        metadata={
            "key": key,
            "hash": fingerprint,
            "status": status,
            "count": preview["records"],
        },
    )
    return {**preview, "id": str(receipt.pk), "replayed": False, "result": result}
