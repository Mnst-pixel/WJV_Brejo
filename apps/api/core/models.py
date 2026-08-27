import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from pgvector.django import VectorField


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDModel):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    display_name = models.CharField(max_length=180, blank=True)
    email = models.EmailField(blank=True)
    preferences = models.JSONField(default=dict, blank=True)
    mfa_secret_encrypted = models.TextField(blank=True)
    mfa_enabled = models.BooleanField(default=False)
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    session_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name or self.username


class Role(TimeStampedModel):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Permission(TimeStampedModel):
    codename = models.CharField(max_length=128, unique=True)
    description = models.CharField(max_length=255)
    roles = models.ManyToManyField(Role, related_name="kairos_permissions", blank=True)

    def __str__(self):
        return self.codename


class UserRole(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="user_assignments")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="roles_granted")
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="unique_user_role")]


class UserSession(UUIDModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracked_sessions")
    session_key_hash = models.CharField(max_length=64, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)


class LoginEvent(UUIDModel):
    class Outcome(models.TextChoices):
        SUCCESS = "success", "Sucesso"
        FAILED = "failed", "Falha"
        LOCKED = "locked", "Bloqueado"
        MFA_FAILED = "mfa_failed", "MFA inválido"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="login_events")
    username_attempted = models.CharField(max_length=150)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["username_attempted", "occurred_at"])]


class AuditLog(UUIDModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events")
    action = models.CharField(max_length=160)
    target_type = models.CharField(max_length=160, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["action", "occurred_at"]), models.Index(fields=["target_type", "target_id"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Audit logs are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit logs cannot be deleted.")


class AdminAction(UUIDModel):
    audit_log = models.OneToOneField(AuditLog, on_delete=models.PROTECT, related_name="admin_action")
    change_set = models.JSONField(default=dict)
    justification = models.TextField()


class SourceRegistry(TimeStampedModel):
    class Health(models.TextChoices):
        UNKNOWN = "unknown", "Desconhecida"
        HEALTHY = "healthy", "Saudável"
        DEGRADED = "degraded", "Degradada"
        UNAVAILABLE = "unavailable", "Indisponível"

    organization = models.CharField(max_length=200)
    domain = models.CharField(max_length=255)
    source_type = models.CharField(max_length=100)
    jurisdiction = models.CharField(max_length=120)
    authentication = models.CharField(max_length=120, blank=True)
    data_format = models.CharField(max_length=100, blank=True)
    access_method = models.CharField(max_length=120)
    rate_limit = models.CharField(max_length=120, blank=True)
    license = models.CharField(max_length=255, blank=True)
    terms_url = models.URLField(blank=True)
    robots_status = models.CharField(max_length=120, blank=True)
    parser = models.CharField(max_length=160, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    coverage = models.JSONField(default=dict, blank=True)
    health = models.CharField(max_length=20, choices=Health.choices, default=Health.UNKNOWN)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=0)
    copyright_status = models.CharField(max_length=255, blank=True)
    redistribution_basis = models.TextField(blank=True)
    attribution = models.TextField(blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_sources")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "domain", "jurisdiction"], name="unique_source_registry")]


class AssetRegistry(TimeStampedModel):
    file_name = models.CharField(max_length=255)
    source_url = models.URLField(blank=True)
    author = models.CharField(max_length=200, blank=True)
    license = models.CharField(max_length=160)
    accessed_at = models.DateTimeField()
    purpose = models.TextField()
    sha256 = models.CharField(max_length=64, unique=True)
    modifications = models.TextField(blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_assets")


class Subject(TimeStampedModel):
    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Topic(TimeStampedModel):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="topics")
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    slug = models.SlugField(max_length=120)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["subject", "slug"], name="unique_topic_subject_slug")]


class Source(TimeStampedModel):
    registry = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT, related_name="sources")
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=1000)
    retrieved_at = models.DateTimeField()
    sha256 = models.CharField(max_length=64, blank=True)
    raw_metadata = models.JSONField(default=dict, blank=True)


class Content(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        REVIEW = "review", "Em revisão"
        PUBLISHED = "published", "Publicado"
        ARCHIVED = "archived", "Arquivado"

    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="contents")
    topics = models.ManyToManyField(Topic, related_name="contents", blank=True)
    slug = models.SlugField(max_length=180, unique=True)
    kind = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    current_version = models.ForeignKey("ContentVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contents_created")


class LegalVersionMixin(models.Model):
    class LegalStatus(models.TextChoices):
        LEGACY_UNVERIFIED = "legacy_unverified", "Legado não verificado"
        CURRENT = "current", "Vigente"
        HISTORICAL = "historical", "Histórica"
        REVOKED = "revoked", "Revogada"
        SUPERSEDED = "superseded", "Substituída"

    version_number = models.PositiveIntegerField()
    original_text = models.TextField()
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    reference_date = models.DateField(null=True, blank=True)
    retrieved_at = models.DateTimeField()
    published_at = models.DateTimeField(null=True, blank=True)
    source_url = models.URLField(max_length=1000)
    source_hash = models.CharField(max_length=64)
    legal_status = models.CharField(max_length=32, choices=LegalStatus.choices, default=LegalStatus.LEGACY_UNVERIFIED)
    changes_summary = models.TextField(blank=True)
    current_legal_situation = models.TextField(blank=True)
    exam_date_situation = models.TextField(blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    approval_date = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by")

    class Meta:
        abstract = True
        constraints = [models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_from__isnull=True) | Q(valid_to__gte=models.F("valid_from")), name="%(app_label)s_%(class)s_valid_range")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Legal versions are immutable; create a successor version.")
        return super().save(*args, **kwargs)


class ContentVersion(UUIDModel, LegalVersionMixin):
    content = models.ForeignKey(Content, on_delete=models.PROTECT, related_name="versions")
    title = models.CharField(max_length=300)
    body = models.TextField()
    structured_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(LegalVersionMixin.Meta):
        abstract = False
        constraints = LegalVersionMixin.Meta.constraints + [models.UniqueConstraint(fields=["content", "version_number"], name="unique_content_version")]


class ContentSource(UUIDModel):
    content_version = models.ForeignKey(ContentVersion, on_delete=models.PROTECT, related_name="content_sources")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="content_versions")
    locator = models.CharField(max_length=300, blank=True)
    relevance = models.DecimalField(max_digits=4, decimal_places=3, default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["content_version", "source"], name="unique_content_source")]


class ReviewTask(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        IN_REVIEW = "in_review", "Em revisão"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Rejeitada"

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.UUIDField()
    target = GenericForeignKey("content_type", "object_id")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="review_tasks")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)


class PublicationApproval(UUIDModel):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Rejeitado"

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.UUIDField()
    target = GenericForeignKey("content_type", "object_id")
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="publication_decisions")
    justification = models.TextField()
    evidence = models.JSONField(default=dict, blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)


class Exam(TimeStampedModel):
    title = models.CharField(max_length=255)
    organizer = models.CharField(max_length=120, default="FGV")
    edition = models.CharField(max_length=80)
    exam_date = models.DateField()
    official_source_url = models.URLField(max_length=1000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="exams_created")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organizer", "edition"], name="unique_exam_edition")]


class ExamPhase(TimeStampedModel):
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="phases")
    phase = models.PositiveSmallIntegerField(choices=[(1, "Primeira fase"), (2, "Segunda fase")])
    area = models.CharField(max_length=120, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(default=300)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exam", "phase", "area"], name="unique_exam_phase_area")]


class ExamDocument(TimeStampedModel):
    exam_phase = models.ForeignKey(ExamPhase, on_delete=models.PROTECT, related_name="documents")
    document_type = models.CharField(max_length=80)
    file_asset = models.ForeignKey("FileAsset", on_delete=models.PROTECT, related_name="exam_documents")
    source = models.ForeignKey(Source, on_delete=models.PROTECT)
    is_official = models.BooleanField(default=True)


class Question(TimeStampedModel):
    exam_phase = models.ForeignKey(ExamPhase, on_delete=models.PROTECT, related_name="questions")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="questions")
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, null=True, blank=True, related_name="questions")
    number = models.PositiveSmallIntegerField()
    current_version = models.ForeignKey("QuestionVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exam_phase", "number"], name="unique_question_number")]


class QuestionVersion(UUIDModel, LegalVersionMixin):
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="versions")
    statement = models.TextField()
    explanation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(LegalVersionMixin.Meta):
        abstract = False
        constraints = LegalVersionMixin.Meta.constraints + [models.UniqueConstraint(fields=["question", "version_number"], name="unique_question_version")]


class Alternative(TimeStampedModel):
    question_version = models.ForeignKey(QuestionVersion, on_delete=models.PROTECT, related_name="alternatives")
    label = models.CharField(max_length=4)
    text = models.TextField()
    order = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["question_version", "label"], name="unique_question_alternative")]
        ordering = ["order"]


class AnswerKey(TimeStampedModel):
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="answer_keys")
    kind = models.CharField(max_length=40, choices=[("preliminary", "Preliminar"), ("final", "Definitivo")])
    current_version = models.ForeignKey("AnswerKeyVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+")


class AnswerKeyVersion(UUIDModel, LegalVersionMixin):
    answer_key = models.ForeignKey(AnswerKey, on_delete=models.PROTECT, related_name="versions")
    correct_alternative = models.ForeignKey(Alternative, on_delete=models.PROTECT, related_name="answer_key_versions")
    rationale = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(LegalVersionMixin.Meta):
        abstract = False
        constraints = LegalVersionMixin.Meta.constraints + [models.UniqueConstraint(fields=["answer_key", "version_number"], name="unique_answer_key_version")]


class Annulment(TimeStampedModel):
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="annulments")
    source = models.ForeignKey(Source, on_delete=models.PROTECT)
    reason = models.TextField()
    effective_at = models.DateTimeField()


class Appeal(TimeStampedModel):
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="appeals")
    source = models.ForeignKey(Source, on_delete=models.PROTECT)
    outcome = models.CharField(max_length=80)
    reasoning = models.TextField()


class PieceType(TimeStampedModel):
    area = models.CharField(max_length=120)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)


class PracticalCase(TimeStampedModel):
    exam_phase = models.ForeignKey(ExamPhase, on_delete=models.PROTECT, related_name="practical_cases")
    piece_type = models.ForeignKey(PieceType, on_delete=models.PROTECT, null=True, blank=True, related_name="cases")
    title = models.CharField(max_length=255)
    current_version = models.ForeignKey("PracticalCaseVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+")


class PracticalCaseVersion(UUIDModel, LegalVersionMixin):
    practical_case = models.ForeignKey(PracticalCase, on_delete=models.PROTECT, related_name="versions")
    prompt = models.TextField()
    facts = models.JSONField(default=list)
    distractors = models.JSONField(default=list)
    temporal_marker = models.CharField(max_length=255)
    jurisdiction = models.CharField(max_length=255)
    addressee = models.CharField(max_length=255)
    standing = models.TextField()
    deadline = models.CharField(max_length=255)
    preliminary_matters = models.JSONField(default=list)
    merits = models.JSONField(default=list)
    requests = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(LegalVersionMixin.Meta):
        abstract = False
        constraints = LegalVersionMixin.Meta.constraints + [models.UniqueConstraint(fields=["practical_case", "version_number"], name="unique_practical_case_version")]


class Rubric(TimeStampedModel):
    case_version = models.OneToOneField(PracticalCaseVersion, on_delete=models.PROTECT, related_name="rubric")
    version = models.PositiveIntegerField(default=1)
    total_points = models.DecimalField(max_digits=6, decimal_places=2)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="rubrics_approved")
    approved_at = models.DateTimeField(null=True, blank=True)


class RubricCriterion(TimeStampedModel):
    rubric = models.ForeignKey(Rubric, on_delete=models.PROTECT, related_name="criteria")
    code = models.CharField(max_length=40)
    title = models.CharField(max_length=255)
    description = models.TextField()
    max_points = models.DecimalField(max_digits=6, decimal_places=2)
    order = models.PositiveSmallIntegerField()
    severe_error = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["rubric", "code"], name="unique_rubric_criterion")]
        ordering = ["order"]


class AcceptableAnswer(TimeStampedModel):
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.PROTECT, related_name="acceptable_answers")
    answer = models.TextField()
    legal_basis = models.TextField()
    source = models.ForeignKey(Source, on_delete=models.PROTECT)


class Simulation(TimeStampedModel):
    class Mode(models.TextChoices):
        FORMAL = "formal", "Simulado formal"
        TRAINING = "training", "Treino"
        FREE = "free", "Estudo livre"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="simulations")
    exam_phase = models.ForeignKey(ExamPhase, on_delete=models.PROTECT, related_name="simulations")
    mode = models.CharField(max_length=20, choices=Mode.choices)
    title = models.CharField(max_length=255)
    question_ids = models.JSONField(default=list)
    duration_minutes = models.PositiveSmallIntegerField(default=300)


class Attempt(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        SUBMITTED = "submitted", "Enviada"
        GRADED = "graded", "Corrigida"
        ABANDONED = "abandoned", "Abandonada"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    simulation = models.ForeignKey(Simulation, on_delete=models.PROTECT, related_name="attempts")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    last_autosave_at = models.DateTimeField(null=True, blank=True)
    elapsed_seconds = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)


class AttemptAnswer(TimeStampedModel):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="attempt_answers")
    selected_alternative = models.ForeignKey(Alternative, on_delete=models.PROTECT, null=True, blank=True)
    free_text = models.TextField(blank=True)
    answer_version = models.PositiveIntegerField(default=1)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "question"], name="unique_attempt_question")]


class AttemptCheckpoint(UUIDModel):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="checkpoints")
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attempt", "version"], name="unique_attempt_checkpoint")]


class Correction(TimeStampedModel):
    attempt = models.OneToOneField(Attempt, on_delete=models.PROTECT, related_name="correction")
    total_score = models.DecimalField(max_digits=7, decimal_places=2)
    max_score = models.DecimalField(max_digits=7, decimal_places=2)
    educational_disclaimer = models.TextField(default="Correção educacional assistida por inteligência artificial. Não constitui correção oficial da OAB/FGV.")
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=0)
    requires_human_review = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="corrections_reviewed")


class CorrectionScore(TimeStampedModel):
    correction = models.ForeignKey(Correction, on_delete=models.PROTECT, related_name="scores")
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.PROTECT, null=True, blank=True)
    points = models.DecimalField(max_digits=6, decimal_places=2)
    evidence_text = models.TextField(blank=True)
    justification = models.TextField()
    confidence = models.DecimalField(max_digits=4, decimal_places=3, default=0)


class OwnedModel(TimeStampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="%(class)ss")

    class Meta:
        abstract = True


class Goal(OwnedModel):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(progress__lte=100), name="goal_progress_lte_100")]


class StudyNote(OwnedModel):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, null=True, blank=True)
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, null=True, blank=True)
    title = models.CharField(max_length=255)
    body = models.TextField()
    version = models.PositiveIntegerField(default=1)


class Flashcard(OwnedModel):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, null=True, blank=True)
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, null=True, blank=True)
    front = models.TextField()
    back = models.TextField()
    source_reference = models.TextField(blank=True)


class FlashcardReview(UUIDModel):
    flashcard = models.ForeignKey(Flashcard, on_delete=models.CASCADE, related_name="reviews")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="flashcard_reviews")
    rating = models.PositiveSmallIntegerField()
    reviewed_at = models.DateTimeField(auto_now_add=True)
    next_review_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(rating__gte=1) & Q(rating__lte=5), name="flashcard_rating_range")]


class Bookmark(OwnedModel):
    target_type = models.CharField(max_length=100)
    target_id = models.UUIDField()
    label = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "target_type", "target_id"], name="unique_owner_bookmark")]


class StudySession(OwnedModel):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, null=True, blank=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    focus_minutes = models.PositiveSmallIntegerField(default=25)
    break_minutes = models.PositiveSmallIntegerField(default=5)
    completed_cycles = models.PositiveSmallIntegerField(default=0)


class FileAsset(OwnedModel):
    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        CLEAN = "clean", "Limpo"
        INFECTED = "infected", "Infectado"
        ERROR = "error", "Erro"

    original_name = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=512, unique=True)
    quarantine_key = models.CharField(max_length=512, unique=True)
    mime_type = models.CharField(max_length=160)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    scan_status = models.CharField(max_length=20, choices=ScanStatus.choices, default=ScanStatus.PENDING)
    scanned_at = models.DateTimeField(null=True, blank=True)
    processing_status = models.CharField(max_length=40, default="quarantined")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "sha256"])]


class SourceDocument(TimeStampedModel):
    source_registry = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT, related_name="documents")
    canonical_url = models.URLField(max_length=1000)
    title = models.CharField(max_length=500)
    jurisdiction = models.CharField(max_length=120)
    document_type = models.CharField(max_length=120)
    current_version = models.ForeignKey("SourceDocumentVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+")


class SourceDocumentVersion(TimeStampedModel):
    class PipelineState(models.TextChoices):
        DISCOVERED = "discovered", "Descoberto"
        DOWNLOADED = "downloaded", "Baixado"
        QUARANTINED = "quarantined", "Em quarentena"
        PARSED = "parsed", "Processado"
        NORMALIZED = "normalized", "Normalizado"
        CLASSIFIED = "classified", "Classificado"
        VERIFIED = "verified", "Verificado"
        HUMAN_REVIEW = "human_review", "Revisão humana"
        APPROVED = "approved", "Aprovado"
        INDEXED = "indexed", "Indexado"
        PUBLISHED = "published", "Publicado"
        FAILED = "failed", "Falhou"

    document = models.ForeignKey(SourceDocument, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    file_asset = models.ForeignKey(FileAsset, on_delete=models.PROTECT, null=True, blank=True, related_name="source_document_versions")
    state = models.CharField(max_length=24, choices=PipelineState.choices, default=PipelineState.DISCOVERED)
    source_hash = models.CharField(max_length=64)
    source_url = models.URLField(max_length=1000)
    retrieved_at = models.DateTimeField()
    published_at = models.DateTimeField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    reference_date = models.DateField(null=True, blank=True)
    raw_metadata = models.JSONField(default=dict, blank=True)
    parsed_structure = models.JSONField(default=dict, blank=True)
    normalized_text = models.TextField(blank=True)
    previous_version = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="next_versions")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="documents_approved")
    approval_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "version_number"], name="unique_source_document_version")]


class DocumentChunk(UUIDModel):
    document_version = models.ForeignKey(SourceDocumentVersion, on_delete=models.PROTECT, related_name="chunks")
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    structure_path = models.JSONField(default=list)
    article = models.CharField(max_length=80, blank=True)
    paragraph = models.CharField(max_length=80, blank=True)
    section = models.CharField(max_length=255, blank=True)
    source_locator = models.CharField(max_length=500)
    source_hash = models.CharField(max_length=64)
    token_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document_version", "ordinal"], name="unique_document_chunk")]


class Embedding(UUIDModel):
    chunk = models.OneToOneField(DocumentChunk, on_delete=models.CASCADE, related_name="embedding")
    model = models.CharField(max_length=160)
    dimensions = models.PositiveSmallIntegerField(default=384)
    vector = VectorField(dimensions=384)
    created_at = models.DateTimeField(auto_now_add=True)


class Agent(TimeStampedModel):
    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField()
    tool_allowlist = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)


class PromptTemplate(TimeStampedModel):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="prompt_templates")
    name = models.CharField(max_length=160)
    purpose = models.CharField(max_length=255)
    current_version = models.ForeignKey("PromptVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="+")


class PromptVersion(UUIDModel):
    template = models.ForeignKey(PromptTemplate, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    system_prompt = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["template", "version_number"], name="unique_prompt_version")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Prompt versions are immutable.")
        return super().save(*args, **kwargs)


class Conversation(OwnedModel):
    title = models.CharField(max_length=255)
    context_type = models.CharField(max_length=80, blank=True)
    context_id = models.UUIDField(null=True, blank=True)


class Message(UUIDModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=[("user", "Usuário"), ("assistant", "Assistente"), ("tool", "Ferramenta")])
    content = models.TextField()
    citations = models.JSONField(default=list)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AgentRun(UUIDModel):
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="runs")
    prompt_version = models.ForeignKey(PromptVersion, on_delete=models.PROTECT, related_name="runs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="agent_runs")
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_runs")
    model = models.CharField(max_length=160)
    runtime = models.CharField(max_length=160)
    runtime_version = models.CharField(max_length=80)
    context = models.JSONField(default=dict)
    sources = models.JSONField(default=list)
    input_text = models.TextField()
    output_text = models.TextField(blank=True)
    status = models.CharField(max_length=30, default="started")
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=3, null=True, blank=True)
    human_review_status = models.CharField(max_length=30, default="not_required")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class AIUsage(UUIDModel):
    run = models.OneToOneField(AgentRun, on_delete=models.CASCADE, related_name="usage")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    tool_calls = models.JSONField(default=list)


class IngestionRun(TimeStampedModel):
    class RunType(models.TextChoices):
        PRECHECK = "precheck", "Pré-verificação"
        DRY_RUN = "dry_run", "Simulação"
        INGEST = "ingest", "Ingestão"

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ingestion_runs")
    run_type = models.CharField(max_length=20, choices=RunType.choices)
    scope = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default="queued")
    discovered_count = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    report = models.JSONField(default=dict)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)


class CorpusUpdate(TimeStampedModel):
    ingestion_run = models.OneToOneField(IngestionRun, on_delete=models.PROTECT, related_name="corpus_update")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="corpus_updates_approved")
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict)


class CoverageRecord(TimeStampedModel):
    source_registry = models.ForeignKey(SourceRegistry, on_delete=models.PROTECT, related_name="coverage_records")
    jurisdiction_level = models.CharField(max_length=40)
    jurisdiction = models.CharField(max_length=160)
    authority = models.CharField(max_length=200)
    document_type = models.CharField(max_length=120)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    documents_count = models.PositiveBigIntegerField(default=0)
    expected_count = models.PositiveBigIntegerField(null=True, blank=True)
    verified = models.BooleanField(default=False)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    failures = models.JSONField(default=list)

    @property
    def coverage_percentage(self):
        if not self.expected_count:
            return None
        return min(100, round(self.documents_count * 100 / self.expected_count, 2))
