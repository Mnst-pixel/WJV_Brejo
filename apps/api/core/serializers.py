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
        return list(obj.role_assignments.select_related("role").values_list("role__slug", flat=True))


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
    current_version = ContentVersionSerializer(read_only=True)

    class Meta:
        model = Content
        fields = ["id", "subject", "topics", "slug", "kind", "status", "current_version"]


class AlternativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alternative
        fields = ["id", "label", "text", "order"]


class QuestionSerializer(serializers.ModelSerializer):
    statement = serializers.CharField(source="current_version.statement", read_only=True)
    alternatives = AlternativeSerializer(source="current_version.alternatives", many=True, read_only=True)

    class Meta:
        model = Question
        fields = ["id", "exam_phase", "subject", "topic", "number", "statement", "alternatives"]


class SimulationSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        from core.services.attempts import validate_question_ids
        phase = attrs.get("exam_phase", getattr(self.instance, "exam_phase", None))
        ids = attrs.get("question_ids", getattr(self.instance, "question_ids", []))
        if phase:
            attrs["question_ids"] = validate_question_ids(ids, phase.pk)
        duration = attrs.get("duration_minutes", getattr(self.instance, "duration_minutes", 300))
        if not 1 <= duration <= 1440:
            raise serializers.ValidationError("Duração deve estar entre 1 e 1440 minutos.")
        return attrs

    def update(self, instance, validated_data):
        from django.db import transaction
        with transaction.atomic():
            locked = Simulation.objects.select_for_update().get(pk=instance.pk)
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
        fields = ["id", "question", "selected_alternative", "free_text", "answer_version", "answered_at"]
        read_only_fields = ["id", "answer_version", "answered_at"]


class AttemptSerializer(serializers.ModelSerializer):
    answers = AttemptAnswerSerializer(many=True, read_only=True)
    mode = serializers.SerializerMethodField()
    questions = serializers.SerializerMethodField()

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
            "elapsed_seconds", "version", "answers", "questions", "snapshot_origin",
        ]
        read_only_fields = ["id", "status", "started_at", "submitted_at", "last_autosave_at", "elapsed_seconds", "version", "answers", "questions", "snapshot_origin"]


class OwnedSerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        validated_data["owner"] = self.context["request"].user
        return super().create(validated_data)


class GoalSerializer(OwnedSerializer):
    class Meta:
        model = Goal
        fields = ["id", "title", "description", "target_date", "completed_at", "progress", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class StudyNoteSerializer(OwnedSerializer):
    class Meta:
        model = StudyNote
        fields = ["id", "subject", "topic", "title", "body", "version", "created_at", "updated_at"]
        read_only_fields = ["id", "version", "created_at", "updated_at"]

    def update(self, instance, validated_data):
        validated_data["version"] = instance.version + 1
        return super().update(instance, validated_data)


class FlashcardSerializer(OwnedSerializer):
    class Meta:
        model = Flashcard
        fields = ["id", "subject", "topic", "front", "back", "source_reference", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


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
