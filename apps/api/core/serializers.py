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
    mode = serializers.CharField(source="simulation.mode", read_only=True)

    class Meta:
        model = Attempt
        fields = [
            "id", "simulation", "mode", "status", "started_at", "submitted_at", "last_autosave_at",
            "elapsed_seconds", "version", "answers",
        ]
        read_only_fields = ["id", "status", "started_at", "submitted_at", "last_autosave_at", "version", "answers"]


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
