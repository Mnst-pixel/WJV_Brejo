"""Workflow facts and import receipts are separate from immutable legal text versions."""
from django.conf import settings
from django.db import models
from django.db.models import Q

from .models import TimeStampedModel


class ContentWorkflow(TimeStampedModel):
    version = models.OneToOneField("core.ContentVersion", on_delete=models.PROTECT, related_name="workflow")
    state = models.CharField(max_length=16, default="draft", choices=[(state, state) for state in ("draft", "review", "approved", "published", "archived")])
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_workflows")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="submitted_workflows")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approval = models.OneToOneField("core.PublicationApproval", on_delete=models.PROTECT, null=True, blank=True, related_name="content_workflow")
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="published_workflows")
    published_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="archived_workflows")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(state__in=["draft", "review", "approved", "published", "archived"]), name="content_workflow_valid_state"),
            models.CheckConstraint(condition=~Q(state__in=["approved", "published"]) | Q(approval__isnull=False), name="content_workflow_approval_required"),
            models.CheckConstraint(condition=~Q(state="published") | (Q(published_at__isnull=False) & Q(published_by__isnull=False)), name="content_workflow_publisher_required"),
        ]


class LegacyContentImport(TimeStampedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="legacy_content_imports")
    subject = models.ForeignKey("core.Subject", on_delete=models.PROTECT)
    dataset = models.CharField(max_length=32)
    source_sha256 = models.CharField(max_length=64)
    preview_sha256 = models.CharField(max_length=64)
    item_count = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default="preview", choices=[("preview", "preview"), ("confirmed", "confirmed")])
    confirmed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "preview_sha256"], name="legacy_content_actor_preview_unique")]


class LegacyContentItem(TimeStampedModel):
    batch = models.ForeignKey(LegacyContentImport, on_delete=models.PROTECT, related_name="items")
    source_sha256 = models.CharField(max_length=64)
    item_sha256 = models.CharField(max_length=64)
    locator = models.CharField(max_length=200)
    version = models.OneToOneField("core.ContentVersion", on_delete=models.PROTECT, related_name="legacy_import_item")
    legal_status = models.CharField(max_length=32, default="legacy_unverified", editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_sha256", "item_sha256"], name="legacy_content_source_item_unique")]
