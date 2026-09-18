"""Human review of question, alternatives, key and metadata as one immutable package."""
from urllib.parse import urlsplit

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit
from core.content_workflow import authorize, fingerprint
from core.models import Alternative, AnswerKey, AnswerKeyVersion, ExamPhase, PublicationApproval, Question, QuestionVersion, Subject, Topic, User
from core.question_models import QuestionMetadata, QuestionWorkflow


class AlternativeInput(serializers.Serializer):
    label = serializers.ChoiceField(choices=list("ABCDEFGH"))
    text = serializers.CharField(max_length=10_000)


class QuestionRevisionInput(serializers.Serializer):
    statement = serializers.CharField(max_length=100_000)
    explanation = serializers.CharField(max_length=30_000)
    alternatives = AlternativeInput(many=True, min_length=2, max_length=8)
    correct_label = serializers.ChoiceField(choices=list("ABCDEFGH"))
    source_url = serializers.URLField(max_length=1000)
    reference_date = serializers.DateField(required=False, allow_null=True, default=None)
    valid_from = serializers.DateField(required=False, allow_null=True, default=None)
    valid_to = serializers.DateField(required=False, allow_null=True, default=None)
    difficulty = serializers.ChoiceField(choices=["easy", "medium", "hard"])
    origin = serializers.ChoiceField(choices=["official", "authored", "adapted"])
    legal_basis = serializers.CharField(max_length=20_000, allow_blank=True, default="")
    observations = serializers.CharField(max_length=5000, allow_blank=True, default="")
    changes_summary = serializers.CharField(max_length=5000, allow_blank=True, default="")
    tags = serializers.ListField(child=serializers.CharField(max_length=40), max_length=20, default=list)
    subtopic_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    annulled = serializers.BooleanField(default=False)
    answer_changed = serializers.BooleanField(default=False)

    def validate(self, data):
        if set(self.initial_data) - set(self.fields):
            raise ValidationError("Campos não permitidos na revisão.")
        labels = [row["label"] for row in data["alternatives"]]
        if labels != list("ABCDEFGH"[:len(labels)]) or data["correct_label"] not in labels:
            raise ValidationError("Use alternativas consecutivas e selecione um gabarito existente.")
        if len({row["text"].strip() for row in data["alternatives"]}) != len(labels):
            raise ValidationError("As alternativas devem possuir textos distintos.")
        parsed = urlsplit(data["source_url"])
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValidationError("Informe uma fonte HTTPS sem credenciais.")
        if data["valid_from"] and data["valid_to"] and data["valid_to"] < data["valid_from"]:
            raise ValidationError("Período de vigência inválido.")
        return data


def question_payload(workflow):
    version = workflow.version
    metadata = version.metadata
    return {
        "statement": version.statement, "explanation": version.explanation,
        "alternatives": [{"label": row.label, "text": row.text} for row in version.alternatives.all()],
        "correct_label": workflow.answer_key_version.correct_alternative.label,
        **{name: getattr(version, name) for name in ("source_url", "reference_date", "valid_from", "valid_to", "changes_summary")},
        **{name: getattr(metadata, name) for name in ("difficulty", "origin", "legal_basis", "observations", "tags", "subtopic_id", "annulled", "answer_changed")},
    }


def package_hash(workflow):
    version, key = workflow.version, workflow.answer_key_version
    legal_fields = ("source_hash", "source_url", "legal_status", "valid_from", "valid_to", "reference_date", "approved_by_id", "approval_date", "published_at")
    return fingerprint({"payload": question_payload(workflow), "version_id": str(version.pk), "key_version_id": str(key.pk),
        "question_id": str(version.question_id), "subject_id": str(version.question.subject_id),
        "topic_id": str(version.question.topic_id), "exam_phase_id": str(version.question.exam_phase_id),
        "question_legal": {name: getattr(version, name) for name in legal_fields},
        "key_legal": {name: getattr(key, name) for name in legal_fields}, "key_rationale": key.rationale,
        "key_question_id": str(key.answer_key.question_id), "correct_alternative_id": str(key.correct_alternative_id)})


def verify_question_package(workflow):
    """Fail closed on post-review drift, including INSERTs into child tables."""
    approval = workflow.approval
    if (not approval or approval.decision != "approved" or approval.object_id != workflow.version_id or
            approval.content_type_id != ContentType.objects.get_for_model(QuestionVersion).pk or
            approval.reviewer_id != workflow.version.approved_by_id or
            approval.reviewer_id != workflow.answer_key_version.approved_by_id or
            approval.evidence.get("package_sha256") != package_hash(workflow) or
            approval.evidence.get("answer_key_version") != str(workflow.answer_key_version_id) or
            workflow.version.legal_status == "legacy_unverified"):
        raise PermissionDenied("A aprovação não corresponde ao pacote exato de questão e gabarito.")


def package_queryset(query):
    return query.select_related("subject", "topic", "exam_phase__exam", "current_version__metadata",
        "current_version__workflow__approval", "current_version__workflow__answer_key_version__correct_alternative",
        "current_version__workflow__answer_key_version__answer_key").prefetch_related("current_version__alternatives")


def verify_published_question(question):
    version = question.current_version
    workflow = getattr(version, "workflow", None)
    if workflow:
        # Reuse the exact already-loaded graph; no per-row related-object queries.
        version.question = question
        workflow.version = version
        verify_question_package(workflow)


def _create_package(question, actor, values, *, previous=None, reviewer=None, legal_status="legacy_unverified"):
    subtopic = None
    if values["subtopic_id"]:
        subtopic = get_object_or_404(Topic.objects.select_for_update(), pk=values["subtopic_id"])
        if subtopic.subject_id != question.subject_id or not question.topic_id or subtopic.parent_id != question.topic_id:
            raise ValidationError("O subtema deve pertencer ao tema e à disciplina da questão.")
    now = timezone.now()
    number = (question.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0) + 1
    legal = {name: values[name] for name in ("source_url", "reference_date", "valid_from", "valid_to", "changes_summary")}
    legal.update(source_hash=fingerprint(values), legal_status=legal_status, retrieved_at=now,
                 approved_by=reviewer, approval_date=now if reviewer else None)
    version = QuestionVersion.objects.create(question=question, version_number=number,
        statement=values["statement"], explanation=values["explanation"], original_text=values["statement"],
        supersedes=previous.version if previous else None, **legal)
    alternatives = {row["label"]: Alternative.objects.create(question_version=version, label=row["label"], text=row["text"], order=index)
                    for index, row in enumerate(values["alternatives"])}
    parent = previous.answer_key_version.answer_key if previous else AnswerKey.objects.create(question=question, kind="final")
    key_number = (parent.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0) + 1
    key = AnswerKeyVersion.objects.create(answer_key=parent, version_number=key_number, correct_alternative=alternatives[values["correct_label"]],
        rationale=values["explanation"], original_text=values["explanation"], supersedes=previous.answer_key_version if previous else None, **legal)
    QuestionMetadata.objects.create(version=version, subtopic=subtopic,
        **{name: values[name] for name in ("difficulty", "origin", "legal_basis", "observations", "tags", "annulled", "answer_changed")})
    return QuestionWorkflow.objects.create(version=version, answer_key_version=key, author=actor)


@transaction.atomic
def create_question(*, actor, exam_phase_id, subject_id, topic_id, values, request=None):
    authorize(actor, "question.create", request)
    data = QuestionRevisionInput(data=values)
    data.is_valid(raise_exception=True)
    phase = get_object_or_404(ExamPhase.objects.select_for_update(), pk=exam_phase_id, phase=1)
    subject = get_object_or_404(Subject, pk=subject_id)
    topic = get_object_or_404(Topic.objects.select_for_update(), pk=topic_id, subject=subject, parent=None) if topic_id else None
    number = (phase.questions.aggregate(maximum=Max("number"))["maximum"] or 0) + 1
    if number > 32767:
        raise ValidationError("O caderno atingiu o limite de questões. Cadastre outro caderno.")
    question = Question.objects.create(exam_phase=phase, subject=subject, topic=topic, number=number)
    workflow = _create_package(question, actor, data.validated_data)
    record_audit("question.revision.created", actor=actor, request=request, target=workflow.version, metadata={"package_sha256": package_hash(workflow)})
    return workflow


@transaction.atomic
def revise_question(*, actor, workflow_id, values, request=None):
    authorize(actor, "question.edit", request)
    base = get_object_or_404(QuestionWorkflow.objects.select_related("version", "answer_key_version__answer_key"), pk=workflow_id)
    question = Question.objects.select_for_update().get(pk=base.version.question_id)
    data = QuestionRevisionInput(data=values)
    data.is_valid(raise_exception=True)
    workflow = _create_package(question, actor, data.validated_data, previous=base)
    record_audit("question.revision.created", actor=actor, request=request, target=workflow.version,
                 metadata={"package_sha256": package_hash(workflow), "based_on": str(base.version_id)})
    return workflow


@transaction.atomic
def transition_question(*, actor, workflow_id, state, justification, legal_status=None, request=None):
    permission = {"review": "question.edit", "approved": "question.approve", "published": "publication.publish", "archived": "publication.publish"}.get(state)
    if not permission:
        raise ValidationError("Decisão inválida.")
    base = get_object_or_404(QuestionWorkflow.objects.select_related("version"), pk=workflow_id)
    # Cross-review inserts author/reviewer FKs. Acquire all principal locks in the RBAC order.
    list(User.objects.select_for_update().filter(pk__in={actor.pk, base.author_id, base.submitted_by_id}).order_by("pk"))
    authorize(actor, permission, request)
    if state in {"published", "archived"}:
        authorize(actor, "question.read", request)
    if not isinstance(justification, str) or not 8 <= len(justification.strip()) <= 2000:
        raise ValidationError("Registre um comentário de 8 a 2000 caracteres.")
    question = Question.objects.select_for_update().get(pk=base.version.question_id)
    workflow = QuestionWorkflow.objects.select_for_update(of=("self",)).select_related("version", "answer_key_version__correct_alternative", "approval").get(pk=base.pk)
    expected = {"draft": "review", "review": "approved", "approved": "published", "published": "archived"}.get(workflow.state)
    if state != expected:
        raise ValidationError("A decisão não corresponde à situação atual. Atualize a página.")
    now = timezone.now()
    if state == "review":
        workflow.submitted_by = actor
        workflow.submitted_at = now
    elif state == "approved":
        if actor.pk in {workflow.author_id, workflow.submitted_by_id}:
            raise PermissionDenied("O autor e quem encaminhou não podem aprovar a própria questão.")
        if legal_status not in {"current", "historical", "revoked", "superseded"}:
            raise ValidationError("Declare a situação jurídica verificada.")
        values = QuestionRevisionInput(data=question_payload(workflow))
        values.is_valid(raise_exception=True)
        approved = _create_package(question, workflow.author, values.validated_data, previous=workflow, reviewer=actor, legal_status=legal_status)
        approved.submitted_by = workflow.submitted_by
        approved.submitted_at = workflow.submitted_at
        approved.approval = PublicationApproval.objects.create(content_type=ContentType.objects.get_for_model(QuestionVersion), object_id=approved.version_id,
            reviewer=actor, decision="approved", justification=justification,
            evidence={"reviewed_version": str(workflow.version_id), "package_sha256": package_hash(approved), "answer_key_version": str(approved.answer_key_version_id)})
        workflow.state = "archived"
        workflow.archived_by = actor
        workflow.archived_at = now
        workflow.save(update_fields=["state", "archived_by", "archived_at", "updated_at"])
        workflow = approved
    elif state == "published":
        verify_question_package(workflow)
        QuestionWorkflow.objects.filter(version__question=question, state="published").exclude(pk=workflow.pk).update(state="archived", archived_by=actor, archived_at=now)
        question.current_version = workflow.version
        question.save(update_fields=["current_version", "updated_at"])
        AnswerKey.objects.filter(pk=workflow.answer_key_version.answer_key_id).update(current_version=workflow.answer_key_version, updated_at=now)
        workflow.published_by = actor
        workflow.published_at = now
    else:
        workflow.archived_by = actor
        workflow.archived_at = now
        if question.current_version_id == workflow.version_id:
            question.current_version = None
            question.save(update_fields=["current_version", "updated_at"])
    workflow.state = state
    workflow.save()
    record_audit("question.workflow.transition", actor=actor, request=request, target=workflow.version,
        metadata={"state": state, "justification": justification, "package_sha256": package_hash(workflow)})
    return workflow


def published_questions():
    now = timezone.now()
    human_approval = Q(current_version__approved_by__isnull=False, current_version__approval_date__lte=now,
                       current_version__question_id=F("id"))
    editorial = Q(current_version__workflow__state="published", current_version__workflow__published_at__lte=now,
        current_version__workflow__published_by__isnull=False,
        current_version__workflow__approval__decision="approved",
        current_version__workflow__approval__content_type=ContentType.objects.get_for_model(QuestionVersion),
        current_version__workflow__approval__object_id=F("current_version_id"),
        current_version__workflow__approval__reviewer_id=F("current_version__approved_by_id"))
    # Preserve explicitly approved pre-workflow publications; never auto-publish legacy_unverified.
    historical = Q(current_version__workflow__isnull=True, current_version__published_at__lte=now)
    return Question.objects.filter(human_approval & (editorial | historical)).exclude(current_version__legal_status="legacy_unverified")
