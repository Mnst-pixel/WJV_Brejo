from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.exceptions import Conflict
from core.models import Alternative, AnswerKeyVersion, Annulment, Attempt, AttemptAnswer, AttemptCheckpoint, Question


@transaction.atomic
def autosave_attempt(*, attempt_id, owner, expected_version: int, answers: list[dict], elapsed_seconds: int):
    attempt = Attempt.objects.select_for_update().select_related("simulation").get(pk=attempt_id, owner=owner)
    if attempt.status != Attempt.Status.ACTIVE:
        raise ValidationError("A tentativa não está ativa.")
    if attempt.version != expected_version:
        raise Conflict({"detail": "Versão de autosave desatualizada.", "current_version": attempt.version})

    allowed_questions = {str(item) for item in attempt.simulation.question_ids}
    snapshot_answers = []
    for payload in answers:
        question_id = str(payload.get("question"))
        if question_id not in allowed_questions:
            raise PermissionDenied("A questão não pertence a este simulado.")
        question = Question.objects.select_related("current_version").get(pk=question_id)
        alternative_id = payload.get("selected_alternative")
        alternative = None
        if alternative_id:
            alternative = Alternative.objects.filter(pk=alternative_id, question_version=question.current_version).first()
            if not alternative:
                raise ValidationError("Alternativa inválida para a versão da questão.")
        item, _ = AttemptAnswer.objects.update_or_create(
            attempt=attempt,
            question=question,
            defaults={
                "selected_alternative": alternative,
                "free_text": payload.get("free_text", ""),
                "answer_version": models_next_answer_version(attempt, question),
            },
        )
        snapshot_answers.append({
            "question": str(question.id),
            "selected_alternative": str(item.selected_alternative_id) if item.selected_alternative_id else None,
            "free_text": item.free_text,
        })

    attempt.version += 1
    attempt.elapsed_seconds = max(0, elapsed_seconds)
    attempt.last_autosave_at = timezone.now()
    attempt.save(update_fields=["version", "elapsed_seconds", "last_autosave_at", "updated_at"])
    AttemptCheckpoint.objects.create(attempt=attempt, version=attempt.version, snapshot={"answers": snapshot_answers, "elapsed_seconds": attempt.elapsed_seconds})
    return attempt


def models_next_answer_version(attempt, question):
    current = AttemptAnswer.objects.filter(attempt=attempt, question=question).values_list("answer_version", flat=True).first()
    return (current or 0) + 1


@transaction.atomic
def submit_attempt(*, attempt_id, owner):
    attempt = Attempt.objects.select_for_update().select_related("simulation").get(pk=attempt_id, owner=owner)
    if attempt.status != Attempt.Status.ACTIVE:
        raise ValidationError("A tentativa já foi encerrada.")
    attempt.status = Attempt.Status.SUBMITTED
    attempt.submitted_at = timezone.now()
    attempt.version += 1
    attempt.save(update_fields=["status", "submitted_at", "version", "updated_at"])
    return attempt


def attempt_results(*, attempt_id, owner):
    attempt = Attempt.objects.select_related("simulation").prefetch_related("answers").get(pk=attempt_id, owner=owner)
    if attempt.status == Attempt.Status.ACTIVE:
        raise PermissionDenied("O gabarito permanece bloqueado até a submissão.")
    answer_map = {answer.question_id: answer for answer in attempt.answers.all()}
    results = []
    correct = 0
    annulled = 0
    for question_id in attempt.simulation.question_ids:
        question = Question.objects.get(pk=question_id)
        answer = answer_map.get(question.id)
        is_annulled = Annulment.objects.filter(question=question).exists()
        key = AnswerKeyVersion.objects.filter(answer_key__question=question, answer_key__kind="final").order_by("-version_number").first()
        is_correct = bool(is_annulled or (answer and key and answer.selected_alternative_id == key.correct_alternative_id))
        correct += int(is_correct)
        annulled += int(is_annulled)
        results.append({
            "question": str(question.id),
            "selected_alternative": str(answer.selected_alternative_id) if answer and answer.selected_alternative_id else None,
            "correct_alternative": str(key.correct_alternative_id) if key else None,
            "correct": is_correct,
            "annulled": is_annulled,
            "rationale": key.rationale if key else "Gabarito definitivo ainda não disponível.",
        })
    return {"attempt": str(attempt.id), "correct": correct, "total": len(results), "annulled": annulled, "questions": results}
