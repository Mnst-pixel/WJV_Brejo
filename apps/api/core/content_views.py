"""Explicit editorial commands; no generic serializer can publish or approve."""
import json

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.content_models import LegacyContentImport
from core.content_workflow import authorize, confirm_legacy, create_revision, preview_legacy, transition_content
from core.models import Content, Subject
from core.permissions import HasKairosPermission
from core.serializers import ContentSerializer, ContentVersionSerializer


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError("Campos não permitidos.")
        return super().to_internal_value(data)


class RevisionInput(StrictInput):
    title = serializers.CharField(max_length=300)
    body = serializers.CharField(max_length=100_000)
    structured_data = serializers.JSONField(default=dict)
    source_url = serializers.URLField(max_length=1000)
    source_hash = serializers.RegexField(regex=r"^[a-f0-9]{64}$")
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)
    reference_date = serializers.DateField(required=False, allow_null=True)
    published_at = serializers.DateTimeField(required=False, allow_null=True)
    changes_summary = serializers.CharField(max_length=5000, required=False, allow_blank=True)

    def validate(self, data):
        if data.get("valid_to") and data.get("valid_from") and data["valid_to"] < data["valid_from"]:
            raise serializers.ValidationError("Período de vigência inválido.")
        if len(json.dumps(data["structured_data"], ensure_ascii=False).encode()) > 128_000:
            raise serializers.ValidationError("Dados estruturados excedem o limite.")
        return data


class ContentInput(StrictInput):
    subject = serializers.PrimaryKeyRelatedField(queryset=Subject.objects.all())
    slug = serializers.SlugField(max_length=180)
    kind = serializers.ChoiceField(choices=["lesson", "summary", "article", "material", "legacy_question", "legacy_summary"])
    revision = RevisionInput()

    def validate_slug(self, value):
        if Content.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Identificador já utilizado.")
        return value


class TransitionInput(StrictInput):
    state = serializers.ChoiceField(choices=["review", "approved", "published", "archived"])
    justification = serializers.CharField(min_length=8, max_length=2000)
    legal_status = serializers.ChoiceField(choices=["current", "historical", "revoked", "superseded"], required=False)


class PreviewInput(StrictInput):
    dataset = serializers.ChoiceField(choices=["questions", "oab"])
    subject_id = serializers.UUIDField()


class ConfirmInput(StrictInput):
    expected_hash = serializers.RegexField(regex=r"^[a-f0-9]{64}$")


def version_response(version):
    workflow = version.workflow
    return {**ContentVersionSerializer(version).data, "content_id": str(version.content_id), "workflow": {
        "state": workflow.state, "author_id": str(workflow.author_id),
        "submitted_by": str(workflow.submitted_by_id) if workflow.submitted_by_id else None,
        "submitted_at": workflow.submitted_at, "approval_id": str(workflow.approval_id) if workflow.approval_id else None,
        "published_by": str(workflow.published_by_id) if workflow.published_by_id else None,
        "published_at": workflow.published_at, "archived_at": workflow.archived_at}}


def batch_response(batch):
    return {"id": str(batch.pk), "dataset": batch.dataset, "source_sha256": batch.source_sha256,
        "preview_sha256": batch.preview_sha256, "item_count": batch.item_count, "status": batch.status,
        "confirmed_at": batch.confirmed_at, "result": batch.result}


class AdminContentListView(APIView):
    permission_classes = [HasKairosPermission]

    def get_permissions(self):
        self.permission_codename = "content.read" if self.request.method == "GET" else "content.create"
        return super().get_permissions()

    def get(self, request):
        # Bounded lists until the administrative product UI adds pagination controls.
        query = Content.objects.select_related("current_version").prefetch_related("topics").order_by("-created_at")[:100]
        return Response(ContentSerializer(query, many=True).data)

    @transaction.atomic
    def post(self, request):
        authorize(request.user, "content.create", request)
        data = ContentInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        revision = values.pop("revision")
        content = Content.objects.create(created_by=request.user, **values)
        version = create_revision(actor=request.user, content_id=content.pk, values=revision, request=request)
        return Response(version_response(version), status=201)


class ContentRevisionView(APIView):
    permission_classes = [HasKairosPermission]

    def get_permissions(self):
        self.permission_codename = "content.read" if self.request.method == "GET" else "content.edit"
        return super().get_permissions()

    def get(self, request, content_id):
        content = get_object_or_404(Content, pk=content_id)
        versions = content.versions.filter(workflow__isnull=False).select_related("workflow").order_by("-version_number")[:100]
        return Response([version_response(version) for version in versions])

    def post(self, request, content_id):
        data = RevisionInput(data=request.data)
        data.is_valid(raise_exception=True)
        version = create_revision(actor=request.user, content_id=content_id, values=data.validated_data, request=request)
        return Response(version_response(version), status=201)


class ContentTransitionView(APIView):
    permission_classes = [HasKairosPermission]
    # Every editorial role can reach the command; the service enforces the specific target action.
    permission_codename = "content.read"

    def post(self, request, version_id):
        data = TransitionInput(data=request.data)
        data.is_valid(raise_exception=True)
        version = transition_content(actor=request.user, version_id=version_id, request=request, **data.validated_data)
        return Response(version_response(version))


class LegacyContentPreviewView(APIView):
    permission_classes = [HasKairosPermission]
    permission_codename = "content.create"

    def post(self, request):
        data = PreviewInput(data=request.data)
        data.is_valid(raise_exception=True)
        batch, preview = preview_legacy(actor=request.user, request=request, **data.validated_data)
        return Response({**batch_response(batch), "preview": preview})


class LegacyContentConfirmView(APIView):
    permission_classes = [HasKairosPermission]
    permission_codename = "content.create"

    def get(self, request, batch_id):
        return Response(batch_response(get_object_or_404(LegacyContentImport, pk=batch_id, actor=request.user)))

    def post(self, request, batch_id):
        data = ConfirmInput(data=request.data)
        data.is_valid(raise_exception=True)
        batch = confirm_legacy(actor=request.user, batch_id=batch_id, request=request, **data.validated_data)
        return Response(batch_response(batch))
