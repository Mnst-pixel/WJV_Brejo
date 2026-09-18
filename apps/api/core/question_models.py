"""Editorial facts for objective questions; approved text and keys remain versioned."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel


class QuestionMetadata(TimeStampedModel):
    version = models.OneToOneField("core.QuestionVersion", on_delete=models.PROTECT, related_name="metadata")
    difficulty = models.CharField(max_length=12, choices=[("easy", "Fácil"), ("medium", "Intermediária"), ("hard", "Difícil")])
    origin = models.CharField(max_length=16, choices=[("official", "Oficial"), ("authored", "Autoral"), ("adapted", "Adaptada")])
    subtopic = models.ForeignKey("core.Topic", on_delete=models.PROTECT, null=True, blank=True, related_name="question_subtopics")
    legal_basis = models.TextField(blank=True)
    observations = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    annulled = models.BooleanField(default=False)
    answer_changed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(difficulty__in=["easy", "medium", "hard"]), name="question_metadata_difficulty"),
            models.CheckConstraint(condition=Q(origin__in=["official", "authored", "adapted"]), name="question_metadata_origin"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Metadados publicados são versionados. Crie uma nova revisão.")
        return super().save(*args, **kwargs)


class QuestionWorkflow(TimeStampedModel):
    version = models.OneToOneField("core.QuestionVersion", on_delete=models.PROTECT, related_name="workflow")
    answer_key_version = models.OneToOneField("core.AnswerKeyVersion", on_delete=models.PROTECT, related_name="question_workflow")
    state = models.CharField(max_length=16, default="draft", choices=[("draft", "Rascunho"), ("review", "Em revisão"), ("approved", "Aprovado"), ("published", "Publicado"), ("archived", "Arquivado")])
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_questions")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="submitted_questions")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approval = models.OneToOneField("core.PublicationApproval", on_delete=models.PROTECT, null=True, blank=True, related_name="question_workflow")
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="published_questions")
    published_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="archived_questions")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "approved", "published", "archived"]), name="question_workflow_valid_state"),
            models.CheckConstraint(condition=~Q(state__in=["approved", "published"]) | Q(approval__isnull=False), name="question_workflow_approval_required"),
            models.CheckConstraint(condition=~Q(state="published") | (Q(published_at__isnull=False) & Q(published_by__isnull=False)), name="question_workflow_publisher_required"),
        ]
