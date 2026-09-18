"""Owner-locked written exams; rubric and answers are frozen independently."""
import json
from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit
from core.content_workflow import fingerprint
from core.exceptions import Conflict
from core.models import PracticalCase, PracticalCaseVersion
from core.permissions import lock_study_user
from core.second_phase_models import WrittenCheckpoint, WrittenResponse, WrittenSubmission
from core.second_phase_workflow import case_payload, loaded_versions, verify_case
from core.services.attempts import ensure_results_unlocked


class StartInput(serializers.Serializer):
    case_id = serializers.UUIDField()
    request_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["formal", "training"], default="training")


class ResponseInput(serializers.Serializer):
    target_code = serializers.CharField(max_length=32)
    text = serializers.CharField(max_length=100_000, allow_blank=True, trim_whitespace=False)


class SaveInput(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    responses = ResponseInput(many=True, min_length=1, max_length=11)


def published_cases():
    return loaded_versions().filter(practical_case__current_version_id=F("pk"),
        editorial_workflow__state="published", editorial_workflow__published_at__lte=timezone.now(),
        editorial_workflow__approval__decision="approved").exclude(legal_status="legacy_unverified")


def check_definition(submission):
    values = {key: value for key, value in submission.frozen_definition.items() if key != "sha256"}
    if (submission.frozen_definition.get("sha256") != fingerprint(values) or values.get("mode") != submission.mode or
            values.get("case_version") != str(submission.case_version_id)):
        raise PermissionDenied("A definição congelada da prova não passou na verificação de integridade.")
    expected = {"piece", *(row["code"] for row in values["payload"]["questions"])}
    if {row.target_code for row in submission.responses.all()} != expected:
        raise PermissionDenied("Os campos salvos não correspondem à prova. Solicite recuperação do registro.")
    if submission.status == "submitted" and submission.final_hash != fingerprint({"definition": submission.frozen_definition["sha256"], "responses": response_snapshot(submission)}):
        raise PermissionDenied("O envio final não passou na verificação de integridade.")


def response_snapshot(submission):
    return [{"target_code": row.target_code, "text": row.text} for row in sorted(submission.responses.all(), key=lambda row: row.target_code)]


@transaction.atomic
def start_written(*, owner, data):
    lock_study_user(owner)
    form = StartInput(data=data)
    form.is_valid(raise_exception=True)
    values = form.validated_data
    previous = WrittenSubmission.objects.filter(owner=owner, request_id=values["request_id"]).first()
    if previous:
        if previous.frozen_definition.get("case_id") != str(values["case_id"]) or previous.mode != values["mode"]:
            raise Conflict("Esta confirmação pertence a outra preparação.")
        check_definition(previous)
        return previous
    ensure_results_unlocked(owner)
    # Lock the current case and recheck publication before taking the immutable package.
    case = get_object_or_404(PracticalCase.objects.select_for_update(), pk=values["case_id"])
    version = get_object_or_404(published_cases(), pk=case.current_version_id)
    verify_case(version)
    definition = json.loads(json.dumps({"case_id": str(case.pk), "case_version": str(version.pk), "area": version.educational_metadata.area.name,
        "payload": case_payload(version), "mode": values["mode"], "criterion_ids": [str(row.pk) for row in version.rubric.criteria.all()]}, default=str))
    definition["sha256"] = fingerprint(definition)
    submission = WrittenSubmission.objects.create(owner=owner, case_version=version, request_id=values["request_id"], mode=values["mode"], frozen_definition=definition)
    WrittenResponse.objects.bulk_create([WrittenResponse(submission=submission, target_code=code) for code in ["piece", *(row["code"] for row in definition["payload"]["questions"])]])
    record_audit("phase2.submission.start", actor=owner, target=submission, metadata={"mode": values["mode"], "definition_sha256": definition["sha256"]})
    return submission


@transaction.atomic
def save_written(*, owner, submission_id, data):
    lock_study_user(owner)
    form = SaveInput(data=data)
    form.is_valid(raise_exception=True)
    values = form.validated_data
    submission = get_object_or_404(WrittenSubmission.objects.select_for_update(), pk=submission_id, owner=owner)
    if submission.status != "active":
        raise Conflict("O envio já foi finalizado e não pode ser alterado.")
    if submission.version != values["version"]:
        raise Conflict("Outra versão foi salva. Confira suas respostas antes de continuar.")
    check_definition(submission)
    now = timezone.now()
    duration = submission.frozen_definition["payload"]["duration_minutes"] * 60
    if submission.mode == "formal" and now > submission.started_at + timedelta(seconds=duration):
        raise Conflict("O tempo terminou. Finalize com as respostas confirmadas no servidor.")
    expected = {"piece", *(row["code"] for row in submission.frozen_definition["payload"]["questions"])}
    if {row["target_code"] for row in values["responses"]} != expected or len(values["responses"]) != len(expected):
        raise ValidationError("Envie uma resposta para cada campo da prova, incluindo campos vazios.")
    if sum(len(row["text"].encode("utf-8")) for row in values["responses"]) > 500_000:
        raise ValidationError("A prova ultrapassa o limite de texto permitido.")
    records = {row.target_code: row for row in submission.responses.all()}
    for row in values["responses"]:
        records[row["target_code"]].text = row["text"]
        records[row["target_code"]].updated_at = now
    WrittenResponse.objects.bulk_update(records.values(), ["text", "updated_at"])
    submission.version += 1
    submission.elapsed_seconds = max(0, int((now - submission.started_at).total_seconds()))
    submission.save(update_fields=["version", "elapsed_seconds", "updated_at"])
    WrittenCheckpoint.objects.create(submission=submission, version=submission.version, snapshot={"responses": response_snapshot(submission), "elapsed_seconds": submission.elapsed_seconds})
    return submission


@transaction.atomic
def submit_written(*, owner, submission_id):
    lock_study_user(owner)
    submission = get_object_or_404(WrittenSubmission.objects.select_for_update(), pk=submission_id, owner=owner)
    check_definition(submission)
    if submission.status == "submitted":
        return submission
    now = timezone.now()
    submission.status, submission.submitted_at = "submitted", now
    submission.elapsed_seconds = max(0, int((now - submission.started_at).total_seconds()))
    if submission.mode == "formal":
        submission.elapsed_seconds = min(submission.elapsed_seconds, submission.frozen_definition["payload"]["duration_minutes"] * 60)
    submission.final_hash = fingerprint({"definition": submission.frozen_definition["sha256"], "responses": response_snapshot(submission)})
    submission.version += 1
    submission.save(update_fields=["status", "submitted_at", "elapsed_seconds", "final_hash", "version", "updated_at"])
    record_audit("phase2.submission.finalize", actor=owner, target=submission, metadata={"final_hash": submission.final_hash})
    return submission


def public_case(version: PracticalCaseVersion):
    verify_case(version)
    metadata = version.educational_metadata
    return {"id": str(version.practical_case_id), "version": str(version.pk), "title": metadata.title, "area": metadata.area.name,
        "duration_minutes": metadata.duration_minutes, "prompt": version.prompt,
        "questions": [{"code": row.code, "prompt": row.prompt} for row in version.discursive_questions.all()]}


def public_submission(submission):
    check_definition(submission)
    payload = submission.frozen_definition["payload"]
    return {"id": str(submission.pk), "title": payload["title"], "area": submission.frozen_definition["area"], "mode": submission.mode,
        "status": submission.status, "version": submission.version, "started_at": submission.started_at, "submitted_at": submission.submitted_at,
        "duration_minutes": payload["duration_minutes"], "elapsed_seconds": submission.elapsed_seconds,
        "prompt": payload["prompt"], "questions": [{"code": row["code"], "prompt": row["prompt"]} for row in payload["questions"]],
        "responses": response_snapshot(submission), "final_hash": submission.final_hash,
        "correction_status": "pending_human_review" if submission.status == "submitted" else "not_submitted"}
