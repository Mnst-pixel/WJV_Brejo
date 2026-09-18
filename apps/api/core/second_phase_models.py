"""Second-phase editorial packages and private, recoverable written submissions."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel


class ImmutableRow(TimeStampedModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Crie uma nova versão para alterar este registro.")
        return super().save(*args, **kwargs)


class SecondPhaseArea(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class SecondPhaseCaseMetadata(ImmutableRow):
    version = models.OneToOneField("core.PracticalCaseVersion", on_delete=models.PROTECT, related_name="educational_metadata")
    area = models.ForeignKey(SecondPhaseArea, on_delete=models.PROTECT)
    title = models.CharField(max_length=255)
    piece_name = models.CharField(max_length=200)
    duration_minutes = models.PositiveSmallIntegerField(default=300)
    provenance = models.CharField(max_length=32, default="human_authored", choices=[("human_authored", "Autoral"), ("official", "Oficial"), ("legacy_unverified", "Legado não verificado")])

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(duration_minutes__gte=1) & Q(duration_minutes__lte=1440), name="phase2_duration_range"),
            models.CheckConstraint(condition=Q(provenance__in=["human_authored", "official", "legacy_unverified"]), name="phase2_valid_provenance"),
        ]


class DiscursiveQuestion(ImmutableRow):
    case_version = models.ForeignKey("core.PracticalCaseVersion", on_delete=models.PROTECT, related_name="discursive_questions")
    code = models.CharField(max_length=32)
    prompt = models.TextField()
    expected_answer = models.TextField()
    order = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["case_version", "code"], name="phase2_unique_discursive_code"),
            models.UniqueConstraint(fields=["case_version", "order"], name="phase2_unique_discursive_order"),
        ]


class RubricCriterionDetails(ImmutableRow):
    criterion = models.OneToOneField("core.RubricCriterion", on_delete=models.PROTECT, related_name="details")
    group = models.CharField(max_length=120)
    target_code = models.CharField(max_length=32, default="piece")
    legal_basis = models.TextField(blank=True)
    acceptable_answers = models.JSONField(default=list)
    dependencies = models.JSONField(default=list)
    required = models.BooleanField(default=False)


class SecondPhaseWorkflow(TimeStampedModel):
    version = models.OneToOneField("core.PracticalCaseVersion", on_delete=models.PROTECT, related_name="editorial_workflow")
    state = models.CharField(max_length=16, default="draft", choices=[("draft", "Rascunho"), ("review", "Em revisão"), ("approved", "Aprovado"), ("published", "Publicado"), ("archived", "Arquivado")])
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_phase2")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_phase2")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approval = models.OneToOneField("core.PublicationApproval", on_delete=models.PROTECT, null=True, blank=True, related_name="phase2_workflow")
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="published_phase2")
    published_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="archived_phase2")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "approved", "published", "archived"]), name="phase2_workflow_state"),
            models.CheckConstraint(condition=~Q(state__in=["approved", "published"]) | Q(approval__isnull=False), name="phase2_requires_approval"),
            models.CheckConstraint(condition=~Q(state="published") | Q(published_by__isnull=False, published_at__isnull=False), name="phase2_requires_publisher"),
        ]


class WrittenSubmission(TimeStampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="written_submissions")
    case_version = models.ForeignKey("core.PracticalCaseVersion", on_delete=models.PROTECT, related_name="written_submissions")
    mode = models.CharField(max_length=12, choices=[("formal", "Formal"), ("training", "Treino")])
    status = models.CharField(max_length=12, default="active", choices=[("active", "Em andamento"), ("submitted", "Enviada")])
    request_id = models.UUIDField()
    version = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    elapsed_seconds = models.PositiveIntegerField(default=0)
    frozen_definition = models.JSONField()
    final_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "status", "-started_at"], name="phase2_owner_status_started")]
        constraints = [
            models.UniqueConstraint(fields=["owner", "request_id"], name="phase2_owner_request"),
            models.CheckConstraint(condition=Q(version__gte=1), name="phase2_submission_version"),
            models.CheckConstraint(condition=Q(mode__in=["formal", "training"]), name="phase2_submission_mode"),
            models.CheckConstraint(condition=(Q(status="active", submitted_at__isnull=True, final_hash="") | (Q(status="submitted", submitted_at__isnull=False) & ~Q(final_hash=""))), name="phase2_submission_state"),
        ]


class WrittenResponse(TimeStampedModel):
    submission = models.ForeignKey(WrittenSubmission, on_delete=models.PROTECT, related_name="responses")
    target_code = models.CharField(max_length=32)
    text = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["submission", "target_code"], name="phase2_response_target")]


class WrittenCheckpoint(ImmutableRow):
    submission = models.ForeignKey(WrittenSubmission, on_delete=models.PROTECT, related_name="checkpoints")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["submission", "version"], name="phase2_checkpoint_version")]


class WrittenCorrection(ImmutableRow):
    submission = models.ForeignKey(WrittenSubmission, on_delete=models.PROTECT, related_name="corrections")
    version = models.PositiveIntegerField()
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    total_score = models.DecimalField(max_digits=6, decimal_places=2)
    max_score = models.DecimalField(max_digits=6, decimal_places=2)
    provenance = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["submission", "version"], name="phase2_correction_version"),
            models.CheckConstraint(condition=Q(total_score__gte=0, max_score__gt=0, total_score__lte=models.F("max_score")), name="phase2_correction_score_range")]


class WrittenCorrectionItem(ImmutableRow):
    correction = models.ForeignKey(WrittenCorrection, on_delete=models.PROTECT, related_name="items")
    criterion = models.ForeignKey("core.RubricCriterion", on_delete=models.PROTECT)
    max_points = models.DecimalField(max_digits=6, decimal_places=2)
    points = models.DecimalField(max_digits=6, decimal_places=2)
    evidence_text = models.TextField(blank=True)
    justification = models.TextField()
    legal_basis = models.TextField(blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    observation = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["correction", "criterion"], name="phase2_correction_criterion"),
            models.CheckConstraint(condition=Q(points__gte=0, max_points__gte=0, points__lte=models.F("max_points")), name="phase2_correction_item_range"),
            models.CheckConstraint(condition=Q(confidence__isnull=True) | Q(confidence__gte=0, confidence__lte=1), name="phase2_correction_confidence")]


class WrittenCorrectionReview(ImmutableRow):
    correction = models.ForeignKey(WrittenCorrection, on_delete=models.PROTECT, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    comment = models.TextField()
    successor = models.OneToOneField(WrittenCorrection, on_delete=models.PROTECT, null=True, blank=True, related_name="supersedes_review")
