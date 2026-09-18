"""Private cards and append-only review receipts; scheduling never trusts the browser."""
from datetime import timedelta
import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.exceptions import Conflict
from core.models import Flashcard, FlashcardReview, Topic
from core.permissions import lock_study_user

FIELDS = ("front", "back", "source_reference", "subject", "topic")
# A transparent initial schedule. These are recall ratings, never legal correctness scores.
INTERVALS = {1: timedelta(minutes=10), 2: timedelta(days=1), 3: timedelta(days=3), 4: timedelta(days=7), 5: timedelta(days=14)}


def account(user, values):
    values = dict(values)
    if values.pop("expected_owner", user.pk) != user.pk:
        raise PermissionDenied("A conta mudou. Entre novamente antes de salvar este cartão.")
    return values


def fields(values, current=None):
    result = {key: values.get(key, getattr(current, key, "" if key == "source_reference" else None)) for key in FIELDS}
    topic, subject = result["topic"], result["subject"]
    if topic and (not subject or get_object_or_404(Topic, pk=topic.pk).subject_id != subject.pk):
        raise ValidationError({"topic": "Escolha um tema da disciplina selecionada."})
    return result


def fingerprint(values):
    document = {key: str(getattr(value, "pk", value)) if value is not None else None for key, value in values.items()}
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@transaction.atomic
def create_card(user, values):
    lock_study_user(user)
    values = account(user, values)
    if "archived" in values:
        raise ValidationError("Crie o cartão antes de arquivá-lo.")
    values.pop("expected_version", None)
    key = values.pop("creation_key", None)
    normalized = fields(values)
    digest = fingerprint(normalized)
    if key:
        current = Flashcard.objects.filter(owner=user, creation_key=key).first()
        if current:
            if current.creation_payload_hash != digest:
                raise Conflict("Esta criação já foi confirmada com outro texto. Confira seus cartões.")
            return current
    return Flashcard.objects.create(owner=user, creation_key=key, creation_payload_hash=digest if key else "", **normalized)


@transaction.atomic
def update_card(user, identifier, values):
    lock_study_user(user)
    values = account(user, values)
    if "creation_key" in values:
        raise ValidationError("A identidade de criação não pode mudar.")
    current = get_object_or_404(Flashcard.objects.select_for_update(), pk=identifier, owner=user)
    if values.pop("expected_version", None) != current.version:
        raise Conflict("O cartão mudou. Confira a versão salva antes de editar.")
    archived = values.pop("archived", current.archived_at is not None)
    normalized = fields(values, current)
    changed = [key for key, value in normalized.items() if getattr(current, key) != value]
    if changed:
        for key in changed:
            setattr(current, key, normalized[key])
        current.next_review_at = None
        changed.append("next_review_at")
    if archived != (current.archived_at is not None):
        current.archived_at = timezone.now() if archived else None
        changed.append("archived_at")
    if changed:
        current.version += 1
        current.save(update_fields=[*changed, "version", "updated_at"])
    return current


@transaction.atomic
def review_card(user, identifier, values):
    lock_study_user(user)
    values = account(user, values)
    current = get_object_or_404(Flashcard.objects.select_for_update(), pk=identifier, owner=user)
    key, rating, version = values["idempotency_key"], values["rating"], values["expected_version"]
    receipt = FlashcardReview.objects.filter(owner=user, idempotency_key=key).first()
    if receipt:
        if (receipt.flashcard_id, receipt.rating, receipt.card_version) != (current.pk, rating, version):
            raise Conflict("Esta revisão já foi confirmada com outra resposta.")
        return receipt
    if current.version != version:
        raise Conflict("O cartão mudou ou já foi revisado. Confira a versão salva.")
    if current.archived_at is not None:
        raise ValidationError("Reative o cartão antes de revisá-lo.")
    now = timezone.now()
    due = now + INTERVALS[rating]
    receipt = FlashcardReview.objects.create(flashcard=current, owner=user, rating=rating,
        next_review_at=due, idempotency_key=key, card_version=version,
        snapshot={"front": current.front, "back": current.back, "source_reference": current.source_reference,
                  "schedule": "fixed-recall-v1", "interval_seconds": int(INTERVALS[rating].total_seconds()), "reference_status": "personal_unverified"})
    current.next_review_at = due
    current.version += 1
    current.save(update_fields=["next_review_at", "version", "updated_at"])
    return receipt


def filter_cards(query, params):
    for key in ("subject", "topic", "creation_key"):
        if params.get(key):
            try:
                value = UUID(params[key])
            except (ValueError, TypeError, AttributeError):
                raise ValidationError({key: "Filtro inválido."}) from None
            query = query.filter(**{key: value})
    mode = params.get("mode", "active")
    if mode not in {"active", "due", "archived", "all"}:
        raise ValidationError({"mode": "Filtro inválido."})
    if mode != "all":
        query = query.filter(archived_at__isnull=mode != "archived")
    if mode == "due":
        query = query.filter(Q(next_review_at__isnull=True) | Q(next_review_at__lte=timezone.now()))
    search = params.get("q", "").strip()
    if len(search) > 150:
        raise ValidationError({"q": "Busca muito longa."})
    if search:
        query = query.filter(Q(front__icontains=search) | Q(back__icontains=search))
    return query.order_by("next_review_at", "-updated_at", "pk")
