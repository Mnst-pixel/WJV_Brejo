"""Transactional attempts with frozen exam context and stable deterministic results."""
import hashlib
import json
from uuid import UUID
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.exceptions import Conflict
from core.models import AnswerKey, Annulment, Attempt, AttemptAnswer, AttemptCheckpoint, Question, Simulation
from core.permissions import lock_study_user


class AnswerInput(serializers.Serializer):
    question = serializers.UUIDField()
    selected_alternative = serializers.UUIDField(required=False, allow_null=True)
    free_text = serializers.CharField(required=False, allow_blank=True, max_length=100_000, trim_whitespace=False)


class AutosaveInput(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    elapsed_seconds = serializers.IntegerField(min_value=0, max_value=86400)
    answers = AnswerInput(many=True, max_length=200)

    def validate_answers(self, value):
        ids = [answer["question"] for answer in value]
        if len(ids) != len(set(ids)):
            raise ValidationError("A mesma questão não pode ocorrer duas vezes no checkpoint.")
        return value


def validate_question_ids(value, exam_phase_id):
    if not isinstance(value, list) or len(value) > 200:
        raise ValidationError("O simulado deve conter uma lista de até 200 questões.")
    try:
        ids = [str(UUID(str(item))) for item in value]
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("Identificador de questão inválido.") from None
    if len(ids) != len(set(ids)):
        raise ValidationError("Questões duplicadas no simulado.")
    if Question.objects.filter(pk__in=ids, exam_phase_id=exam_phase_id).count() != len(ids):
        raise ValidationError("Questões inexistentes ou pertencentes a outra prova.")
    return ids


def _definition(simulation, *, require_approval):
    from core.question_workflow import package_queryset, published_questions, verify_published_question
    ids = validate_question_ids(simulation.question_ids, simulation.exam_phase_id)
    questions = {str(q.pk): q for q in package_queryset(Question.objects.filter(pk__in=ids))}
    published_ids = {str(value) for value in published_questions().filter(pk__in=ids).values_list("pk", flat=True)} if require_approval else set(ids)
    keys = {str(key.question_id): key for key in AnswerKey.objects.filter(question_id__in=ids, kind="final").select_related("current_version").order_by("created_at")}
    annulled = {str(value) for value in Annulment.objects.filter(question_id__in=ids, effective_at__lte=timezone.now()).values_list("question_id", flat=True)}
    items = []
    for question_id in ids:
        question = questions[question_id]
        version = question.current_version
        if not version:
            raise ValidationError("Questão sem versão disponível.")
        if require_approval and question_id not in published_ids:
            raise PermissionDenied("A questão ainda não possui publicação jurídica aprovada.")
        alternatives = [{"id": str(a.pk), "label": a.label, "text": a.text, "order": a.order} for a in version.alternatives.all()]
        key_parent = keys.get(question_id)
        key = key_parent.current_version if key_parent else None
        if key and str(key.correct_alternative_id) not in {a["id"] for a in alternatives}:
            raise ValidationError("Gabarito não corresponde à versão da questão.")
        workflow = getattr(version, "workflow", None)
        if workflow and require_approval:
            verify_published_question(question)
        if key and require_approval:
            approved_key = bool(key.approved_by_id and key.approval_date and key.legal_status != "legacy_unverified")
            published_key = bool(workflow and workflow.state == "published" and workflow.answer_key_version_id == key.pk) if workflow else bool(key.published_at and key.published_at <= timezone.now())
            if not approved_key or not published_key:
                key = None
        metadata = getattr(version, "metadata", None)
        items.append({"question": question_id, "version": str(version.pk), "version_number": version.version_number,
                      "statement": version.statement, "source_hash": version.source_hash, "alternatives": alternatives,
                      "answer_key_version": str(key.pk) if key else None,
                      "correct_alternative": str(key.correct_alternative_id) if key else None,
                      "rationale": key.rationale if key else "Gabarito definitivo aprovado indisponível nesta captura.",
                      "annulled": question_id in annulled or bool(metadata and metadata.annulled),
                      "subject": str(question.subject_id), "subject_name": question.subject.name,
                      "topic": str(question.topic_id) if question.topic_id else None, "topic_name": question.topic.name if question.topic else "",
                      "source_url": version.source_url, "reference_date": str(version.reference_date) if version.reference_date else None,
                      "legal_basis": metadata.legal_basis if metadata else "", "difficulty": metadata.difficulty if metadata else ""})
    definition = {"title": simulation.title, "mode": simulation.mode, "duration_minutes": simulation.duration_minutes, "exam_phase": str(simulation.exam_phase_id), "questions": items}
    definition["sha256"] = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    definition["captured_at"] = timezone.now().isoformat()
    return definition


def ensure_results_unlocked(owner, *, exclude_attempt=None):
    # Inspect immutable captured mode, not a mutable simulation relationship.
    if Attempt.objects.filter(owner=owner, status="active", frozen_definition__mode="formal").exclude(pk=exclude_attempt).exists():
        raise Conflict("Finalize o simulado formal em andamento antes de consultar gabaritos de outras tentativas.")


@transaction.atomic
def create_attempt(*, simulation, owner, idempotency_key=None):
    # Owner lock also serializes the same idempotency key across distinct simulations.
    lock_study_user(owner)
    simulation = get_object_or_404(Simulation.objects.select_for_update(), pk=simulation.pk, owner=owner)
    if idempotency_key is not None:
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 96 or not idempotency_key.isascii():
            raise ValidationError("Chave de idempotência inválida.")
        previous = Attempt.objects.filter(owner=owner, idempotency_key=idempotency_key).first()
        if previous:
            if previous.simulation_id != simulation.pk:
                raise Conflict("Chave de idempotência já utilizada para outro simulado.")
            return previous
    ensure_results_unlocked(owner)
    return Attempt.objects.create(owner=owner, simulation=simulation, frozen_definition=_definition(simulation, require_approval=True), snapshot_origin="creation", idempotency_key=idempotency_key)


def _ensure_definition(attempt):
    if not attempt.frozen_definition:
        if attempt.snapshot_origin == "legacy_unverified":
            raise Conflict("Tentativa anterior sem captura verificável. Preserve o histórico e inicie nova tentativa.")
        attempt.frozen_definition = _definition(attempt.simulation, require_approval=False)
        attempt.snapshot_origin = "deferred"
        attempt.save(update_fields=["frozen_definition", "snapshot_origin", "updated_at"])


@transaction.atomic
def autosave_attempt(*, attempt_id, owner, expected_version, answers, elapsed_seconds):
    lock_study_user(owner)
    attempt_id = serializers.UUIDField().run_validation(attempt_id)
    payload = AutosaveInput(data={"version": expected_version, "answers": answers, "elapsed_seconds": elapsed_seconds})
    payload.is_valid(raise_exception=True)
    values = payload.validated_data
    attempt = get_object_or_404(Attempt.objects.select_for_update().select_related("simulation"), pk=attempt_id, owner=owner)
    if attempt.status != Attempt.Status.ACTIVE:
        raise ValidationError("A tentativa não está ativa.")
    if attempt.version != values["version"]:
        raise Conflict({"detail": "Versão de autosave desatualizada.", "current_version": attempt.version})
    _ensure_definition(attempt)
    if attempt.frozen_definition["mode"] == "formal" and timezone.now() > attempt.started_at + timedelta(minutes=attempt.frozen_definition["duration_minutes"]):
        raise Conflict("Tempo do simulado encerrado. Envie as respostas já salvas.")
    if values["elapsed_seconds"] < attempt.elapsed_seconds:
        raise ValidationError("O tempo decorrido não pode retroceder.")
    max_seconds = attempt.frozen_definition["duration_minutes"] * 60
    if values["elapsed_seconds"] > max_seconds:
        raise ValidationError("O tempo excede a duração do simulado.")
    allowed = {item["question"]: item for item in attempt.frozen_definition["questions"]}
    for answer in values["answers"]:
        question_id = str(answer["question"])
        item = allowed.get(question_id)
        if item is None:
            raise PermissionDenied("A questão não pertence a este simulado.")
        selected = answer.get("selected_alternative")
        if selected and str(selected) not in {alternative["id"] for alternative in item["alternatives"]}:
            raise ValidationError("Alternativa inválida para a versão congelada.")
        existing = AttemptAnswer.objects.filter(attempt=attempt, question_id=question_id).first()
        AttemptAnswer.objects.update_or_create(attempt=attempt, question_id=question_id, defaults={
            "selected_alternative_id": selected, "free_text": answer.get("free_text", ""), "answer_version": existing.answer_version + 1 if existing else 1,
        })
    attempt.version += 1
    attempt.elapsed_seconds = values["elapsed_seconds"]
    attempt.last_autosave_at = timezone.now()
    attempt.save(update_fields=["version", "elapsed_seconds", "last_autosave_at", "updated_at"])
    snapshot_answers = [{"question": str(answer.question_id), "selected_alternative": str(answer.selected_alternative_id) if answer.selected_alternative_id else None, "free_text": answer.free_text} for answer in attempt.answers.order_by("question_id")]
    AttemptCheckpoint.objects.create(attempt=attempt, version=attempt.version, snapshot={"answers": snapshot_answers, "elapsed_seconds": attempt.elapsed_seconds})
    return attempt


def _score(attempt):
    answer_map = {str(answer.question_id): answer for answer in attempt.answers.all()}
    results = []
    correct = annulled = unscored = 0
    for item in attempt.frozen_definition["questions"]:
        answer = answer_map.get(item["question"])
        scorable = bool(item["annulled"] or item["correct_alternative"])
        is_correct = bool(item["annulled"] or (answer and str(answer.selected_alternative_id) == item["correct_alternative"])) if scorable else None
        correct += int(is_correct is True)
        if answer:
            answer.is_correct = is_correct
        annulled += int(item["annulled"])
        unscored += int(not scorable)
        results.append({"question": item["question"], "selected_alternative": str(answer.selected_alternative_id) if answer and answer.selected_alternative_id else None,
                        "correct_alternative": item["correct_alternative"], "correct": is_correct, "annulled": item["annulled"], "rationale": item["rationale"]})
    if answer_map:
        AttemptAnswer.objects.bulk_update(answer_map.values(), ["is_correct"])
    return {"attempt": str(attempt.pk), "correct": correct, "total": len(results), "annulled": annulled, "unscored": unscored,
            "questions": results, "snapshot_origin": attempt.snapshot_origin, "requires_review": attempt.snapshot_origin != "creation" or unscored > 0 or not results,
            "definition_sha256": attempt.frozen_definition["sha256"]}


@transaction.atomic
def submit_attempt(*, attempt_id, owner):
    lock_study_user(owner)
    attempt_id = serializers.UUIDField().run_validation(attempt_id)
    attempt = get_object_or_404(Attempt.objects.select_for_update().select_related("simulation"), pk=attempt_id, owner=owner)
    if attempt.status in {Attempt.Status.SUBMITTED, Attempt.Status.GRADED}:
        return attempt
    if attempt.status != Attempt.Status.ACTIVE:
        raise ValidationError("A tentativa não pode ser submetida.")
    _ensure_definition(attempt)
    if attempt.frozen_definition.get("mode") != "formal":
        ensure_results_unlocked(owner)
    attempt.result_snapshot = _score(attempt)
    attempt.status = Attempt.Status.SUBMITTED
    attempt.submitted_at = timezone.now()
    attempt.version += 1
    attempt.save(update_fields=["status", "submitted_at", "version", "result_snapshot", "updated_at"])
    return attempt


@transaction.atomic
def attempt_results(*, attempt_id, owner):
    lock_study_user(owner)
    attempt_id = serializers.UUIDField().run_validation(attempt_id)
    attempt = get_object_or_404(Attempt, pk=attempt_id, owner=owner)
    ensure_results_unlocked(owner, exclude_attempt=attempt.pk)
    if attempt.status == Attempt.Status.ACTIVE:
        raise PermissionDenied("O gabarito permanece bloqueado até a submissão.")
    if not attempt.result_snapshot:
        return {"attempt": str(attempt.pk), "status": "historical_result_unavailable", "requires_review": True,
                "snapshot_origin": attempt.snapshot_origin, "detail": "Não há pontuação histórica congelada; resultados antigos não serão recalculados silenciosamente."}
    return attempt.result_snapshot


