"""Versioned second-phase case, questions and individual rubric criteria."""
from decimal import Decimal
from urllib.parse import urlsplit

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.audit import record_audit
from core.content_workflow import authorize, fingerprint
from core.exceptions import Conflict
from core.models import ExamPhase, PracticalCase, PracticalCaseVersion, PublicationApproval, Rubric, RubricCriterion, User
from core.second_phase_models import DiscursiveQuestion, RubricCriterionDetails, SecondPhaseArea, SecondPhaseCaseMetadata, SecondPhaseWorkflow


class DiscursiveInput(serializers.Serializer):
    code = serializers.RegexField(r"^Q[1-9][0-9]?$", max_length=32)
    prompt = serializers.CharField(max_length=30_000)
    expected_answer = serializers.CharField(max_length=30_000)


class CriterionInput(serializers.Serializer):
    code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,32}$")
    group = serializers.CharField(max_length=120)
    target_code = serializers.CharField(max_length=32)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=10_000)
    max_points = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("100"))
    legal_basis = serializers.CharField(max_length=10_000, allow_blank=True, default="")
    acceptable_answers = serializers.ListField(child=serializers.CharField(max_length=5000), max_length=10, default=list)
    dependencies = serializers.ListField(child=serializers.CharField(max_length=32), max_length=30, default=list)
    required = serializers.BooleanField(default=False)
    severe_error = serializers.BooleanField(default=False)


class CaseInput(serializers.Serializer):
    area_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    piece_name = serializers.CharField(max_length=200)
    duration_minutes = serializers.IntegerField(min_value=1, max_value=1440, default=300)
    prompt = serializers.CharField(max_length=100_000)
    source_url = serializers.URLField(max_length=1000)
    reference_date = serializers.DateField(allow_null=True, default=None)
    valid_from = serializers.DateField(allow_null=True, default=None)
    valid_to = serializers.DateField(allow_null=True, default=None)
    temporal_marker = serializers.CharField(max_length=255, allow_blank=True, default="")
    jurisdiction = serializers.CharField(max_length=255, allow_blank=True, default="")
    addressee = serializers.CharField(max_length=255, allow_blank=True, default="")
    standing = serializers.CharField(max_length=10_000, allow_blank=True, default="")
    deadline = serializers.CharField(max_length=255, allow_blank=True, default="")
    facts = serializers.ListField(child=serializers.CharField(max_length=5000), max_length=30, default=list)
    distractors = serializers.ListField(child=serializers.CharField(max_length=5000), max_length=30, default=list)
    preliminary_matters = serializers.ListField(child=serializers.CharField(max_length=5000), max_length=30, default=list)
    merits = serializers.ListField(child=serializers.CharField(max_length=5000), max_length=30, default=list)
    requests = serializers.ListField(child=serializers.CharField(max_length=5000), max_length=30, default=list)
    changes_summary = serializers.CharField(max_length=5000, allow_blank=True, default="")
    provenance = serializers.ChoiceField(choices=["human_authored", "official", "legacy_unverified"], default="human_authored")
    total_points = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("100"))
    questions = DiscursiveInput(many=True, max_length=10)
    criteria = CriterionInput(many=True, max_length=100)

    def validate(self, values):
        if set(self.initial_data) - set(self.fields):
            raise ValidationError("Campos não permitidos no caso.")
        url = urlsplit(values["source_url"])
        if url.scheme != "https" or url.username or url.password:
            raise ValidationError("Informe uma fonte HTTPS sem credenciais.")
        if values["valid_from"] and values["valid_to"] and values["valid_to"] < values["valid_from"]:
            raise ValidationError("Período de vigência inválido.")
        targets = {row["code"] for row in values["questions"]}
        if len(targets) != len(values["questions"]):
            raise ValidationError("Cada questão discursiva deve possuir código único.")
        targets.add("piece")
        seen = {}
        for row in values["criteria"]:
            if row["code"] in seen or row["target_code"] not in targets:
                raise ValidationError("Cada critério exige código único e uma resposta existente.")
            if any(dependency not in seen or seen[dependency] != row["target_code"] for dependency in row["dependencies"]):
                raise ValidationError("Dependências devem indicar critérios anteriores da mesma resposta.")
            seen[row["code"]] = row["target_code"]
        return values


CASE_FIELDS = ("prompt", "source_url", "reference_date", "valid_from", "valid_to", "temporal_marker", "jurisdiction", "addressee", "standing", "deadline",
               "facts", "distractors", "preliminary_matters", "merits", "requests", "changes_summary")


def case_payload(version):
    metadata, rubric = version.educational_metadata, version.rubric
    return {**{name: getattr(version, name) for name in CASE_FIELDS},
        **{name: getattr(metadata, name) for name in ("area_id", "title", "piece_name", "duration_minutes", "provenance")},
        "total_points": rubric.total_points,
        "questions": [{"code": row.code, "prompt": row.prompt, "expected_answer": row.expected_answer} for row in version.discursive_questions.all()],
        "criteria": [{"code": row.code, "title": row.title, "description": row.description, "max_points": row.max_points, "severe_error": row.severe_error,
            **{name: getattr(row.details, name) for name in ("group", "target_code", "legal_basis", "acceptable_answers", "dependencies", "required")}}
            for row in rubric.criteria.all()]}


def case_hash(version):
    return fingerprint({"payload": case_payload(version), "version": str(version.pk), "case": str(version.practical_case_id),
        "version_number": version.version_number, "rubric_id": str(version.rubric.pk), "rubric_version": version.rubric.version,
        "exam_phase": str(version.practical_case.exam_phase_id), "source_hash": version.source_hash,
        "reviewer": str(version.approved_by_id), "approval_date": version.approval_date, "legal_status": version.legal_status,
        "rubric_reviewer": str(version.rubric.approved_by_id), "rubric_approval_date": version.rubric.approved_at,
        "criterion_ids": [str(row.pk) for row in version.rubric.criteria.all()]})


def loaded_versions():
    return PracticalCaseVersion.objects.select_related("practical_case__exam_phase", "educational_metadata__area", "rubric", "editorial_workflow__approval").prefetch_related("discursive_questions", "rubric__criteria__details")


def verify_case(version):
    try:
        workflow = version.editorial_workflow
        approval = workflow.approval
        digest = case_hash(version)
    except ObjectDoesNotExist:
        raise PermissionDenied("O caso ou o espelho está incompleto. Solicite revisão editorial.") from None
    if (not approval or approval.decision != "approved" or approval.object_id != version.pk or
            approval.content_type_id != ContentType.objects.get_for_model(PracticalCaseVersion).pk or
            approval.reviewer_id != version.approved_by_id or version.rubric.approved_by_id != version.approved_by_id or
            version.legal_status == "legacy_unverified" or approval.evidence.get("package_sha256") != digest):
        raise PermissionDenied("O caso e o espelho não correspondem à versão revisada.")


def _create_package(case, actor, values, *, previous=None, reviewer=None, legal_status="legacy_unverified"):
    area = get_object_or_404(SecondPhaseArea.objects.select_for_update(), pk=values["area_id"])
    now = timezone.now()
    number = (case.versions.aggregate(maximum=Max("version_number"))["maximum"] or 0) + 1
    version = PracticalCaseVersion.objects.create(practical_case=case, version_number=number, original_text=values["prompt"],
        source_hash=fingerprint(values), retrieved_at=now, legal_status=legal_status, approved_by=reviewer, approval_date=now if reviewer else None,
        supersedes=previous, **{name: values[name] for name in CASE_FIELDS})
    SecondPhaseCaseMetadata.objects.create(version=version, area=area, **{name: values[name] for name in ("title", "piece_name", "duration_minutes", "provenance")})
    for order, row in enumerate(values["questions"]):
        DiscursiveQuestion.objects.create(case_version=version, order=order, **row)
    rubric = Rubric.objects.create(case_version=version, version=number, total_points=values["total_points"], approved_by=reviewer, approved_at=now if reviewer else None)
    for order, row in enumerate(values["criteria"]):
        criterion = RubricCriterion.objects.create(rubric=rubric, order=order, **{name: row[name] for name in ("code", "title", "description", "max_points", "severe_error")})
        RubricCriterionDetails.objects.create(criterion=criterion, **{name: row[name] for name in ("group", "target_code", "legal_basis", "acceptable_answers", "dependencies", "required")})
    return SecondPhaseWorkflow.objects.create(version=version, author=actor)


@transaction.atomic
def create_case_revision(*, actor, values, exam_phase_id=None, case_id=None, request=None):
    authorize(actor, "case.edit" if case_id else "case.create", request)
    authorize(actor, "rubric.create", request)
    form = CaseInput(data=values)
    form.is_valid(raise_exception=True)
    if case_id:
        case = get_object_or_404(PracticalCase.objects.select_for_update(), pk=case_id)
    else:
        phase = get_object_or_404(ExamPhase.objects.select_for_update(), pk=exam_phase_id, phase=2)
        case = PracticalCase.objects.create(exam_phase=phase, title=form.validated_data["title"])
    workflow = _create_package(case, actor, form.validated_data, previous=case.current_version)
    record_audit("phase2.revision.create", actor=actor, request=request, target=workflow.version, metadata={"version": workflow.version.version_number})
    return workflow


@transaction.atomic
def transition_case(*, actor, workflow_id, expected_state, state, justification, legal_status=None, request=None):
    permission = {"review": "case.edit", "approved": "case.approve", "published": "publication.publish", "archived": "publication.publish"}.get(state)
    if not permission:
        raise ValidationError("Transição desconhecida.")
    identity = get_object_or_404(SecondPhaseWorkflow.objects.select_related("version"), pk=workflow_id)
    list(User.objects.select_for_update().filter(pk__in={actor.pk, identity.author_id, identity.submitted_by_id}).order_by("pk"))
    authorize(actor, permission, request)
    if state in {"published", "archived"}:
        authorize(actor, "case.read", request)
    if state == "approved":
        authorize(actor, "rubric.approve", request)
    case = get_object_or_404(PracticalCase.objects.select_for_update(), pk=identity.version.practical_case_id)
    workflow = get_object_or_404(SecondPhaseWorkflow.objects.select_for_update(of=("self",)), pk=workflow_id)
    if workflow.state != expected_state:
        raise Conflict("A situação mudou. Reabra o caso antes de continuar.")
    if (workflow.state, state) not in {("draft", "review"), ("review", "approved"), ("approved", "published"), ("draft", "archived"), ("review", "archived"), ("approved", "archived"), ("published", "archived")}:
        raise ValidationError("Transição editorial não permitida.")
    justification = serializers.CharField(max_length=5000).run_validation(justification)
    now = timezone.now()
    if state == "review":
        workflow.submitted_by, workflow.submitted_at = actor, now
    elif state == "approved":
        if actor.pk in {workflow.author_id, workflow.submitted_by_id}:
            raise PermissionDenied("A revisão exige uma pessoa independente da autoria e do encaminhamento.")
        if legal_status not in {"current", "historical"}:
            raise ValidationError("Declare a situação jurídica verificada.")
        form = CaseInput(data=case_payload(workflow.version))
        form.is_valid(raise_exception=True)
        values = form.validated_data
        targets = {"piece", *(row["code"] for row in values["questions"])}
        if (not values["criteria"] or {row["target_code"] for row in values["criteria"]} != targets or
                sum((row["max_points"] for row in values["criteria"]), Decimal("0")) != values["total_points"]):
            raise ValidationError("Cada resposta precisa de critérios e a soma deve ser igual à pontuação total.")
        approved = _create_package(case, workflow.author, values, previous=workflow.version, reviewer=actor, legal_status=legal_status)
        approved.submitted_by, approved.submitted_at = workflow.submitted_by, workflow.submitted_at
        approved.approval = PublicationApproval.objects.create(content_type=ContentType.objects.get_for_model(PracticalCaseVersion), object_id=approved.version_id,
            reviewer=actor, decision="approved", justification=justification, evidence={"reviewed_version": str(workflow.version_id), "package_sha256": case_hash(approved.version)})
        workflow.state, workflow.archived_by, workflow.archived_at = "archived", actor, now
        workflow.save()
        workflow = approved
    elif state == "published":
        verify_case(workflow.version)
        SecondPhaseWorkflow.objects.filter(version__practical_case=case, state="published").exclude(pk=workflow.pk).update(state="archived", archived_by=actor, archived_at=now)
        case.current_version = workflow.version
        case.save(update_fields=["current_version", "updated_at"])
        workflow.published_by, workflow.published_at = actor, now
    else:
        workflow.archived_by, workflow.archived_at = actor, now
        if case.current_version_id == workflow.version_id:
            case.current_version = None
            case.save(update_fields=["current_version", "updated_at"])
    workflow.state = state
    workflow.save()
    record_audit("phase2.workflow.transition", actor=actor, request=request, target=workflow.version, metadata={"state": state, "justification": justification})
    return workflow
