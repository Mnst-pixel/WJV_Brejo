from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.utils import timezone

from .models import TimeStampedModel


class Plan(TimeStampedModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    max_upload_bytes = models.PositiveBigIntegerField(default=25 * 1024**2)
    storage_quota_bytes = models.PositiveBigIntegerField(default=250 * 1024**2)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(max_upload_bytes__gt=0), name="plan_positive_upload"
            ),
            models.CheckConstraint(
                condition=Q(storage_quota_bytes__gte=F("max_upload_bytes")),
                name="plan_quota_covers_upload",
            ),
        ]


class Enrollment(TimeStampedModel):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollment"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    status = models.CharField(
        max_length=16,
        choices=[
            ("active", "Ativa"),
            ("suspended", "Suspensa"),
            ("expired", "Expirada"),
        ],
        default="active",
    )
    valid_from = models.DateTimeField(default=timezone.now)
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")),
                name="enrollment_valid_interval",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "suspended", "expired"]),
                name="enrollment_valid_status",
            ),
        ]


class UploadPolicy(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    max_upload_bytes = models.PositiveBigIntegerField(default=25 * 1024**2)
    default_storage_quota_bytes = models.PositiveBigIntegerField(default=250 * 1024**2)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Limites gerais de arquivos"

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="upload_policy_singleton"),
            models.CheckConstraint(
                condition=Q(max_upload_bytes__gt=0), name="policy_positive_upload"
            ),
            models.CheckConstraint(
                condition=Q(default_storage_quota_bytes__gte=F("max_upload_bytes")),
                name="policy_quota_covers_upload",
            ),
        ]
