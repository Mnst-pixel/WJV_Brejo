"""Canonical note commands with idempotent creation and reviewed references."""
import hashlib
import json

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.exceptions import Conflict
from core.models import ContentVersion, StudyNote, Topic
from core.permissions import lock_study_user


def references(values, current=None):
    result = dict(values)
    subject = result.get("subject", getattr(current, "subject", None))
    topic = result.get("topic", getattr(current, "topic", None))
    source = result.get("content_version", getattr(current, "content_version", None))
    if topic:
        topic = get_object_or_404(Topic, pk=topic.pk)
        if not subject or topic.subject_id != subject.pk:
            raise ValidationError({"topic": "Escolha um tema da disciplina selecionada."})
    if source:
        source = get_object_or_404(ContentVersion.objects.select_related("content"), pk=source.pk)
        if "content_version" in result and (current is None or source.pk != current.content_version_id):
            from core.content_workflow import published_content
            from core.serializers import ContentSerializer
            published = get_object_or_404(published_content().select_related("current_version__workflow__approval"), pk=source.content_id, current_version=source)
            ContentSerializer(published).data  # Verify the reviewed package before attaching it.
        if not subject or source.content.subject_id != subject.pk:
            raise ValidationError({"content_version": "A leitura deve pertencer à disciplina selecionada."})
    return result


def creation_hash(values):
    payload = {key: str(getattr(values.get(key), "pk", values.get(key))) if values.get(key) is not None else None for key in ("title", "body", "subject", "topic", "content_version")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def account_values(user, values):
    result = dict(values)
    if result.pop("expected_owner", user.pk) != user.pk:
        raise PermissionDenied("A conta da sessão mudou. Entre novamente antes de salvar esta anotação.")
    return result


@transaction.atomic
def create_note(user, values):
    lock_study_user(user)
    values = account_values(user, values)
    values.pop("expected_version", None)
    key = values.pop("creation_key", None)
    digest = creation_hash(values)
    if key:
        current = StudyNote.objects.filter(owner=user, creation_key=key).first()
        if current:
            if current.creation_payload_hash != digest:
                raise Conflict("Esta criação já foi confirmada com outro texto. Confira suas anotações antes de continuar.")
            return current
    values = references(values)
    return StudyNote.objects.create(owner=user, creation_key=key, creation_payload_hash=digest if key else "", **values)


@transaction.atomic
def update_note(user, note_id, values):
    lock_study_user(user)
    values = account_values(user, values)
    if "creation_key" in values:
        raise ValidationError("A identidade de criação da anotação não pode mudar.")
    expected = values.pop("expected_version", None)
    current = get_object_or_404(StudyNote.objects.select_for_update(), pk=note_id, owner=user)
    if expected != current.version:
        raise Conflict({"detail": "A anotação mudou. Confira a versão salva antes de continuar.", "current_version": current.version})
    values = references(values, current)
    changed = [field for field, value in values.items() if getattr(current, field) != value]
    if changed:
        for field in changed:
            setattr(current, field, values[field])
        current.version += 1
        current.save(update_fields=[*changed, "version", "updated_at"])
    return current


def filter_notes(query, params):
    from uuid import UUID
    for key in ("subject", "topic", "content_version", "creation_key"):
        if params.get(key):
            try:
                value = UUID(params[key])
            except (ValueError, TypeError, AttributeError):
                raise ValidationError({key: "Filtro inválido."}) from None
            query = query.filter(**{key: value})
    search = params.get("q", "").strip()
    if len(search) > 150:
        raise ValidationError({"q": "Busca muito longa."})
    if search:
        from django.db.models import Q
        query = query.filter(Q(title__icontains=search) | Q(body__icontains=search))
    return query.order_by("-updated_at", "pk")
