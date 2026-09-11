"""Goals measure canonical account events; reading progress never writes to the database."""
from datetime import timedelta
import hashlib
import json

from django.db import transaction
from django.db.models import Case, Count, DateTimeField, F, FloatField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework import serializers

from core.exceptions import Conflict
from core.models import Attempt, AttemptAnswer, FlashcardReview, Goal
from core.permissions import lock_study_user
from core.second_phase_models import WrittenSubmission
from core.study_models import StudyActivity

FIELDS = ("title", "description", "metric", "target_value", "start_date", "target_date", "subject", "priority")
DEFAULTS = {"description": "", "metric": "manual", "target_value": None, "start_date": None, "target_date": None, "subject": None, "priority": 2}


def measured(query):
    """Correlated aggregates keep query count constant for paginated lists and dashboard."""
    now = timezone.now()

    def window(field):
        return {field + "__date__gte": OuterRef("start_date"), field + "__date__lte": OuterRef("target_date"), field + "__lte": now}

    def total(rows, owner, expression=Count("pk")):
        values = rows.order_by().values(owner).annotate(total=expression).values("total")[:1]
        return Coalesce(Subquery(values, output_field=FloatField()), Value(0.0))

    answers = AttemptAnswer.objects.filter(attempt__owner_id=OuterRef("owner_id"), attempt__status__in=["submitted", "graded"],
        selected_alternative__isnull=False, **window("attempt__submitted_at"))
    minutes = StudyActivity.objects.filter(owner_id=OuterRef("owner_id"), **window("occurred_at"))
    simulations = Attempt.objects.filter(owner_id=OuterRef("owner_id"), status__in=["submitted", "graded"], **window("submitted_at")).exclude(idempotency_key__startswith="practice:")
    written = WrittenSubmission.objects.filter(owner_id=OuterRef("owner_id"), status="submitted", mode="formal", **window("submitted_at"))
    reviews = FlashcardReview.objects.filter(owner_id=OuterRef("owner_id"), **window("reviewed_at"))
    return query.select_related("subject").annotate(measured_at=Value(now, output_field=DateTimeField()), measured_value=Case(
        When(metric="questions", subject__isnull=True, then=total(answers, "attempt__owner_id")),
        When(metric="questions", then=total(answers.filter(question__subject_id=OuterRef("subject_id")), "attempt__owner_id")),
        When(metric="study_minutes", then=total(minutes, "owner_id", Sum("duration_seconds")) / Value(60.0)),
        When(metric="simulations", then=total(simulations, "owner_id") + total(written, "owner_id")),
        When(metric="flashcard_reviews", then=total(reviews, "owner_id")),
        default=Value(0.0), output_field=FloatField()))


def effective_progress(goal):
    if goal.metric == Goal.Metric.MANUAL:
        return goal.progress
    return min(100, int(goal.measured_value * 100 / goal.target_value))


def incomplete(query):
    return query.filter(Q(metric="manual", progress__lt=100) | (~Q(metric="manual") & Q(measured_value__lt=F("target_value"))))


def filter_goals(query, params):
    mode = serializers.ChoiceField(choices=["active", "incomplete", "achieved", "archived", "all"]).run_validation(params.get("mode", "active"))
    if mode == "archived":
        query = query.filter(archived_at__isnull=False)
    elif mode != "all":
        query = query.filter(archived_at__isnull=True)
    if mode == "incomplete":
        query = incomplete(query)
    elif mode == "achieved":
        query = query.exclude(pk__in=incomplete(query).values("pk"))
    if "creation_key" in params:
        query = query.filter(creation_key=serializers.UUIDField().run_validation(params["creation_key"]))
    if "q" in params:
        query = query.filter(title__icontains=serializers.CharField(max_length=150, allow_blank=True).run_validation(params["q"]))
    return query


def normalized(values, current=None):
    result = {key: values.get(key, getattr(current, key, DEFAULTS.get(key))) for key in FIELDS}
    if current and result["metric"] != current.metric:
        raise ValidationError({"metric": "Crie outra meta para acompanhar um tipo diferente de atividade."})
    if result["metric"] != Goal.Metric.MANUAL:
        if not result["target_value"] or not result["start_date"] or not result["target_date"]:
            raise ValidationError("Defina a quantidade, o início e o prazo da meta.")
        if not timedelta(0) <= result["target_date"] - result["start_date"] <= timedelta(days=366):
            raise ValidationError("O prazo deve ser posterior ao início e cobrir no máximo um ano.")
        if "progress" in values:
            raise ValidationError("O progresso desta meta é calculado pela atividade registrada.")
    elif result["target_value"] is not None or result["start_date"] is not None:
        raise ValidationError("Metas manuais usam porcentagem, sem quantidade ou início de contagem.")
    if result["subject"] and result["metric"] != Goal.Metric.QUESTIONS:
        raise ValidationError({"subject": "O filtro de disciplina está disponível para metas de questões."})
    return result


def account(user, values):
    result = dict(values)
    if result.pop("expected_owner", user.pk) != user.pk:
        raise PermissionDenied("A conta mudou. Entre novamente antes de salvar a meta.")
    return result


def digest(values):
    payload = {key: str(getattr(value, "pk", value)) if value is not None else None for key, value in values.items()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@transaction.atomic
def create_goal(user, values):
    lock_study_user(user)
    values = account(user, values)
    if "archived" in values:
        raise ValidationError("Crie a meta antes de arquivá-la.")
    fields = normalized(values)
    fields["progress"] = values.get("progress", 0)
    key = values.get("creation_key")
    fingerprint = digest(fields)
    if key:
        previous = Goal.objects.filter(owner=user, creation_key=key).first()
        if previous:
            if previous.creation_payload_hash != fingerprint:
                raise Conflict("Esta criação já foi confirmada com outros dados.")
            return measured(Goal.objects.filter(pk=previous.pk)).get()
    current = Goal.objects.create(owner=user, creation_key=key, creation_payload_hash=fingerprint if key else "",
        completed_at=timezone.now() if fields["progress"] == 100 else None, **fields)
    return measured(Goal.objects.filter(pk=current.pk)).get()


@transaction.atomic
def update_goal(user, identifier, values):
    lock_study_user(user)
    values = account(user, values)
    if "creation_key" in values:
        raise ValidationError("A identidade de criação da meta não pode mudar.")
    current = get_object_or_404(Goal.objects.select_for_update(), pk=identifier, owner=user)
    if values.get("expected_version") != current.version:
        raise Conflict("A meta mudou. Confira a versão salva antes de continuar.")
    fields = normalized(values, current)
    fields["progress"] = values.get("progress", current.progress)
    fields["completed_at"] = (current.completed_at or timezone.now()) if fields["progress"] == 100 else None
    archived = values.get("archived", current.archived_at is not None)
    fields["archived_at"] = (current.archived_at or timezone.now()) if archived else None
    changed = [key for key, value in fields.items() if getattr(current, key) != value]
    if changed:
        for key in changed:
            setattr(current, key, fields[key])
        current.version += 1
        current.save(update_fields=[*changed, "version", "updated_at"])
    return measured(Goal.objects.filter(pk=current.pk)).get()
