from rest_framework import serializers

from .models import (
    Alternative,
    Attempt,
    AttemptAnswer,
    AuditLog,
    Bookmark,
    Content,
    ContentVersion,
    Conversation,
    CoverageRecord,
    FileAsset,
    Flashcard,
    Goal,
    IngestionRun,
    Message,
    Question,
    Simulation,
    SourceDocumentVersion,
    StudyNote,
    StudySession,
    Subject,
    Topic,
    User,
)


class UserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "email", "preferences", "mfa_enabled", "roles"]
        read_only_fields = ["id", "username", "mfa_enabled", "roles"]

    def get_roles(self, obj):
        from .permissions import active_role_slugs
        return sorted(active_role_slugs(obj))

    def validate_email(self, value):
        value = value.strip().lower()
        if value and User.objects.filter(email__iexact=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("Este e-mail não está disponível para a conta.")
        return value

    def validate_preferences(self, value):
        allowed = {"reduced_motion", "reduced_density", "comfortable_reading", "focus_mode", "text_scale"}
        if not isinstance(value, dict) or set(value) - allowed or any((type(item) is not int or not 90 <= item <= 125) if key == "text_scale" else type(item) is not bool for key, item in value.items()):
            raise serializers.ValidationError("Preferências devem conter somente os controles de leitura suportados.")
        return value

    def update(self, instance, validated_data):
        from django.db import transaction
        from .exceptions import Conflict
        with transaction.atomic():
            current = User.objects.select_for_update().get(pk=instance.pk)
            if current.session_version != instance.session_version or not current.is_active:
                raise Conflict("O acesso foi alterado durante a edição.")
            for field, value in validated_data.items():
                if field == "preferences":
                    value = {**current.preferences, **value}
                setattr(current, field, value)
            if validated_data:
                from django.db import IntegrityError
                try:
                    with transaction.atomic():
                        current.save(update_fields=[*validated_data, "updated_at"])
                except IntegrityError:
                    raise Conflict("Os dados da conta foram alterados. Confira o e-mail antes de tentar novamente.") from None
            return current


class TopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = ["id", "subject", "parent", "slug", "name", "description"]


class SubjectSerializer(serializers.ModelSerializer):
    topics = TopicSerializer(many=True, read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "slug", "name", "description", "order", "topics"]


class ContentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentVersion
        fields = [
            "id", "version_number", "title", "body", "structured_data", "valid_from", "valid_to",
            "reference_date", "retrieved_at", "published_at", "source_url", "source_hash", "legal_status",
            "changes_summary", "current_legal_situation", "exam_date_situation", "approval_date", "created_at",
        ]


class ContentSerializer(serializers.ModelSerializer):
    current_version = serializers.SerializerMethodField()

    def get_current_version(self, obj):
        from django.core.exceptions import ObjectDoesNotExist
        from core.content_workflow import version_fingerprint
        from rest_framework.exceptions import PermissionDenied
        version = obj.current_version
        try:
            approved = bool(version and version.workflow.approval and version.workflow.approval.evidence.get("version_sha256") == version_fingerprint(version))
        except ObjectDoesNotExist:
            approved = False
        if not approved:
            raise PermissionDenied("O conteúdo não corresponde à versão revisada.")
        return ContentVersionSerializer(version).data

    class Meta:
        model = Content
        fields = ["id", "subject", "topics", "slug", "kind", "status", "current_version"]


class AlternativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alternative
        fields = ["id", "label", "text", "order"]


class QuestionSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        from core.question_workflow import verify_published_question
        verify_published_question(instance)
        return super().to_representation(instance)

    statement = serializers.CharField(source="current_version.statement", read_only=True)
    alternatives = AlternativeSerializer(source="current_version.alternatives", many=True, read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    topic_name = serializers.CharField(source="topic.name", read_only=True, default="")
    exam_title = serializers.CharField(source="exam_phase.exam.title", read_only=True)
    edition = serializers.CharField(source="exam_phase.exam.edition", read_only=True)
    year = serializers.IntegerField(source="exam_phase.exam.exam_date.year", read_only=True)
    difficulty = serializers.CharField(source="current_version.metadata.difficulty", read_only=True, default="")

    class Meta:
        model = Question
        fields = ["id", "exam_phase", "subject", "topic", "number", "statement", "alternatives", "subject_name", "topic_name", "exam_title", "edition", "year", "difficulty"]


class SimulationSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        if "selection_config" in self.initial_data:
            raise serializers.ValidationError("A configuração de preparação é registrada pelo servidor.")
        from core.services.attempts import validate_question_ids
        phase = attrs.get("exam_phase", getattr(self.instance, "exam_phase", None))
        ids = attrs.get("question_ids", getattr(self.instance, "question_ids", []))
        if phase and (self.instance is None or "question_ids" in attrs or "exam_phase" in attrs):
            attrs["question_ids"] = validate_question_ids(ids, phase.pk)
        duration = attrs.get("duration_minutes", getattr(self.instance, "duration_minutes", 300))
        if not 1 <= duration <= 1440:
            raise serializers.ValidationError("Duração deve estar entre 1 e 1440 minutos.")
        return attrs

    def update(self, instance, validated_data):
        from django.db import transaction
        from core.services.attempts import validate_question_ids
        with transaction.atomic():
            locked = Simulation.objects.select_for_update().get(pk=instance.pk)
            validate_question_ids(validated_data.get("question_ids", locked.question_ids),
                                  getattr(validated_data.get("exam_phase", locked.exam_phase), "pk"))
            structural = ("exam_phase", "mode", "question_ids", "duration_minutes")
            if locked.attempts.exists() and any(key in validated_data and validated_data[key] != getattr(locked, key) for key in structural):
                raise serializers.ValidationError("A estrutura do simulado não pode mudar após iniciar uma tentativa.")
            return super().update(locked, validated_data)

    class Meta:
        model = Simulation
        fields = ["id", "exam_phase", "mode", "title", "question_ids", "duration_minutes", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class AttemptAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttemptAnswer
        fields = ["id", "question", "selected_alternative", "marked_for_review", "free_text", "answer_version", "answered_at"]
        read_only_fields = ["id", "answer_version", "answered_at"]


class AttemptSerializer(serializers.ModelSerializer):
    answers = AttemptAnswerSerializer(many=True, read_only=True)
    mode = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    duration_minutes = serializers.SerializerMethodField()

    def get_title(self, obj):
        return obj.frozen_definition.get("title", obj.simulation.title)

    def get_duration_minutes(self, obj):
        return obj.frozen_definition.get("duration_minutes", obj.simulation.duration_minutes)

    def get_mode(self, obj):
        return obj.frozen_definition.get("mode", obj.simulation.mode)

    def get_questions(self, obj):
        # The frozen answer key is never serialized before submission.
        visible = ("question", "version", "version_number", "statement", "source_hash", "alternatives")
        return [{key: item[key] for key in visible} for item in obj.frozen_definition.get("questions", [])]

    def validate_simulation(self, simulation):
        if simulation.owner_id != self.context["request"].user.pk:
            raise serializers.ValidationError("Simulado indisponível para esta conta.")
        if self.instance and simulation.pk != self.instance.simulation_id:
            raise serializers.ValidationError("O simulado de uma tentativa não pode ser alterado.")
        return simulation

    def validate(self, attrs):
        protected = {"status", "elapsed_seconds", "version", "answers", "frozen_definition", "result_snapshot", "snapshot_origin", "idempotency_key", "submitted_at", "started_at"}
        if protected & set(self.initial_data):
            raise serializers.ValidationError("Estado, tempo e respostas só podem mudar pelos comandos da tentativa.")
        return attrs

    def create(self, validated_data):
        from core.services.attempts import create_attempt
        request = self.context["request"]
        return create_attempt(simulation=validated_data["simulation"], owner=request.user, idempotency_key=request.headers.get("Idempotency-Key"))

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Tentativas só podem mudar pelos comandos transacionais de autosave e submissão.")

    class Meta:
        model = Attempt
        fields = [
            "id", "simulation", "mode", "status", "started_at", "submitted_at", "last_autosave_at",
            "elapsed_seconds", "version", "answers", "questions", "snapshot_origin", "title", "duration_minutes",
        ]
        read_only_fields = ["id", "status", "started_at", "submitted_at", "last_autosave_at", "elapsed_seconds", "version", "answers", "questions", "snapshot_origin"]


class OwnedSerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)


class GoalSerializer(OwnedSerializer):
    progress = serializers.IntegerField(min_value=0, max_value=100, required=False)

    def validate(self, attrs):
        if "completed_at" in self.initial_data:
            raise serializers.ValidationError("A conclusão é registrada automaticamente pelo progresso.")
        return attrs

    def create(self, validated_data):
        from django.db import transaction
        from django.utils import timezone
        from core.services.study_state import _lock
        with transaction.atomic():
            _lock(self.context["request"].user)
            validated_data["completed_at"] = timezone.now() if validated_data.get("progress", 0) == 100 else None
            return super().create(validated_data)

    def update(self, instance, validated_data):
        from django.db import transaction
        from django.shortcuts import get_object_or_404
        from django.utils import timezone
        from core.services.study_state import _lock
        user = self.context["request"].user
        with transaction.atomic():
            _lock(user)
            current = get_object_or_404(Goal.objects.select_for_update(), pk=instance.pk, owner=user)
            progress = validated_data.get("progress", current.progress)
            validated_data["completed_at"] = (current.completed_at or timezone.now()) if progress == 100 else None
            return super().update(current, validated_data)

    class Meta:
        model = Goal
        fields = ["id", "title", "description", "target_date", "completed_at", "progress", "created_at", "updated_at"]
        read_only_fields = ["id", "completed_at", "created_at", "updated_at"]


class StudyNoteSerializer(OwnedSerializer):
    expected_version = serializers.IntegerField(min_value=1, write_only=True, required=False)
    creation_key = serializers.UUIDField(write_only=True, required=False)
    expected_owner = serializers.UUIDField(write_only=True, required=False)
    account_id = serializers.UUIDField(source="owner_id", read_only=True)
    body = serializers.CharField(max_length=100000, allow_blank=True, trim_whitespace=False)
    subject_name = serializers.CharField(source="subject.name", read_only=True, default=None)
    content_title = serializers.CharField(source="content_version.title", read_only=True, default=None)

    class Meta:
        model = StudyNote
        fields = ["id", "account_id", "subject", "subject_name", "topic", "content_version", "content_title", "title", "body", "version", "creation_key", "expected_owner", "expected_version", "created_at", "updated_at"]
        read_only_fields = ["id", "version", "created_at", "updated_at"]

    def create(self, validated_data):
        from core.personal_notes import create_note
        validated_data.pop("owner", None)
        return create_note(self.context["request"].user, validated_data)

    def update(self, instance, validated_data):
        from core.personal_notes import update_note
        return update_note(self.context["request"].user, instance.pk, validated_data)


class FlashcardSerializer(OwnedSerializer):
    front = serializers.CharField(max_length=10000, trim_whitespace=False)
    back = serializers.CharField(max_length=20000, trim_whitespace=False)
    source_reference = serializers.CharField(max_length=2000, allow_blank=True, required=False, trim_whitespace=False)
    expected_version = serializers.IntegerField(min_value=1, write_only=True, required=False)
    expected_owner = serializers.UUIDField(write_only=True, required=False)
    creation_key = serializers.UUIDField(write_only=True, required=False)
    archived = serializers.BooleanField(write_only=True, required=False)
    account_id = serializers.UUIDField(source="owner_id", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True, default=None)

    def validate(self, attrs):
        if {"owner", "account_id", "version", "next_review_at", "archived_at", "creation_payload_hash"} & set(self.initial_data):
            raise serializers.ValidationError("Conta, versão e agenda são controladas pelo servidor.")
        for key in ("front", "back"):
            if key in attrs and not attrs[key].strip():
                raise serializers.ValidationError({key: "Preencha o texto do cartão."})
        return attrs

    def create(self, validated_data):
        from core.personal_flashcards import create_card
        validated_data.pop("owner", None)
        return create_card(self.context["request"].user, validated_data)

    def update(self, instance, validated_data):
        from core.personal_flashcards import update_card
        return update_card(self.context["request"].user, instance.pk, validated_data)

    class Meta:
        model = Flashcard
        fields = ["id", "account_id", "subject", "subject_name", "topic", "front", "back", "source_reference", "version", "next_review_at", "archived_at", "expected_version", "expected_owner", "creation_key", "archived", "created_at", "updated_at"]
        read_only_fields = ["id", "version", "next_review_at", "archived_at", "created_at", "updated_at"]


class FlashcardReviewCommand(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    expected_version = serializers.IntegerField(min_value=1)
    expected_owner = serializers.UUIDField(required=False)
    idempotency_key = serializers.UUIDField()

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError("A agenda e o histórico são calculados pelo servidor.")
        return attrs


class BookmarkSerializer(OwnedSerializer):
    class Meta:
        model = Bookmark
        fields = ["id", "target_type", "target_id", "label", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class StudySessionSerializer(OwnedSerializer):
    class Meta:
        model = StudySession
        fields = [
            "id", "subject", "started_at", "ended_at", "focus_minutes", "break_minutes", "completed_cycles",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class FileAssetSerializer(serializers.ModelSerializer):
    metadata = serializers.SerializerMethodField()

    def get_metadata(self, obj):
        value = obj.metadata.get("extracted_characters")
        return {"extracted_characters": value} if isinstance(value, int) else {}

    class Meta:
        model = FileAsset
        fields = [
            "id", "original_name", "mime_type", "size_bytes", "sha256", "scan_status", "processing_status",
            "metadata", "created_at", "updated_at",
        ]
        read_only_fields = fields


class IngestionRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngestionRun
        fields = [
            "id", "run_type", "scope", "status", "discovered_count", "changed_count", "failed_count", "report",
            "started_at", "finished_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "discovered_count", "changed_count", "failed_count", "report", "started_at",
            "finished_at", "created_at", "updated_at",
        ]


class SourceDocumentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceDocumentVersion
        fields = [
            "id", "document", "version_number", "file_asset", "state", "source_hash", "source_url", "retrieved_at",
            "published_at", "valid_from", "valid_to", "reference_date", "raw_metadata", "parsed_structure",
            "approved_by", "approval_date", "created_at", "updated_at",
        ]
        read_only_fields = fields


class CoverageRecordSerializer(serializers.ModelSerializer):
    coverage_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = CoverageRecord
        fields = [
            "id", "source_registry", "jurisdiction_level", "jurisdiction", "authority", "document_type",
            "period_start", "period_end", "documents_count", "expected_count", "coverage_percentage", "verified",
            "last_verified_at", "failures",
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.StringRelatedField()

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "action", "target_type", "target_id", "ip_address", "request_id", "metadata", "occurred_at"]


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "citations", "confidence", "created_at"]


class ConversationSerializer(OwnedSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "title", "context_type", "context_id", "messages", "created_at", "updated_at"]
        read_only_fields = ["id", "messages", "created_at", "updated_at"]
