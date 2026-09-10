"""Ordinary forms for upload limits and enrollment; no JSON or shell required."""

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .admin import PolicyAdmin, locked_admin_principals
from .audit import record_audit
from .models import Permission
from .permissions import request_has_permission
from .upload_models import Enrollment, Plan, UploadPolicy

MIB = 1024**2


class LimitForm(forms.ModelForm):
    max_upload_mib = forms.IntegerField(
        label="Tamanho máximo de cada arquivo (MiB)", min_value=1
    )
    storage_quota_mib = forms.IntegerField(
        label="Espaço por pessoa (MiB)", min_value=1, max_value=(2**63 - 1) // MIB
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["max_upload_mib"].max_value = (
            settings.KAIROS_MAX_UPLOAD_BYTES // MIB
        )
        self.initial["max_upload_mib"] = self.instance.max_upload_bytes // MIB
        self.initial["storage_quota_mib"] = (
            getattr(self.instance, self.quota_field) // MIB
        )

    def clean(self):
        data = super().clean()
        maximum, quota = data.get("max_upload_mib"), data.get("storage_quota_mib")
        if maximum is not None and maximum * MIB > settings.KAIROS_MAX_UPLOAD_BYTES:
            self.add_error(
                "max_upload_mib", "Limite superior ao máximo de segurança da aplicação."
            )
        if maximum is not None and quota is not None:
            if quota < maximum:
                self.add_error(
                    "storage_quota_mib",
                    "O espaço deve comportar pelo menos um arquivo.",
                )
            self.instance.max_upload_bytes = maximum * MIB
            setattr(self.instance, self.quota_field, quota * MIB)
        return data


class PlanForm(LimitForm):
    quota_field = "storage_quota_bytes"

    class Meta:
        model = Plan
        fields = ("code", "name", "active")
        labels = {"code": "Identificador do plano", "name": "Nome", "active": "Ativo"}


class UploadPolicyForm(LimitForm):
    quota_field = "default_storage_quota_bytes"

    class Meta:
        model = UploadPolicy
        fields = ("enabled",)
        labels = {"enabled": "Permitir novos uploads"}


class UploadSettingsAdmin(PolicyAdmin):
    def allows(self, request, action):
        return request_has_permission(
            request, "settings.read" if action == "read" else "settings.manage"
        )

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            locked_admin_principals(request)
            # Low-volume configuration writes share a stable seeded mutex. It
            # also covers missing singleton rows and concurrent plan-code edits.
            Permission.objects.select_for_update().get(codename="settings.manage")
            allowed = (
                self.has_change_permission(request, obj)
                if change
                else self.has_add_permission(request)
            )
            if not allowed:
                raise PermissionDenied
            current = (
                self.model.objects.select_for_update().get(pk=obj.pk) if change else obj
            )
            mapping = {
                "max_upload_mib": "max_upload_bytes",
                "storage_quota_mib": form.quota_field,
            }
            allowed_fields = (
                {"code", "name", "active"} if isinstance(obj, Plan) else {"enabled"}
            )
            changed = set()
            for name in form.changed_data:
                destination = mapping.get(name, name)
                if name in mapping or name in allowed_fields:
                    setattr(current, destination, getattr(obj, destination))
                    changed.add(destination)
            try:
                if current.max_upload_bytes > settings.KAIROS_MAX_UPLOAD_BYTES:
                    raise ValidationError("unsafe upload maximum")
                current.full_clean()
            except ValidationError:
                raise PermissionDenied(
                    "Os limites mudaram ou são incompatíveis; recarregue o formulário."
                ) from None
            if change:
                if changed:
                    current.save(update_fields=[*changed, "updated_at"])
                obj.refresh_from_db()
            else:
                current.save(force_insert=True)
            record_audit(
                "admin.upload_settings.changed",
                actor=request.user,
                request=request,
                target=current,
                metadata={"fields": sorted(changed)},
            )


@admin.register(Plan)
class PlanAdmin(UploadSettingsAdmin):
    form = PlanForm
    list_display = ("name", "active")
    search_fields = ("name", "code")
    fields = ("code", "name", "active", "max_upload_mib", "storage_quota_mib")


@admin.register(UploadPolicy)
class UploadPolicyAdmin(UploadSettingsAdmin):
    form = UploadPolicyForm
    fields = ("enabled", "max_upload_mib", "storage_quota_mib")

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not UploadPolicy.objects.exists()


@admin.register(Enrollment)
class EnrollmentAdmin(UploadSettingsAdmin):
    fields = ("owner", "plan", "status", "valid_from", "valid_to")
    list_display = ("owner", "plan", "status", "valid_to")
    list_filter = ("status", "plan")
    search_fields = ("owner__username", "owner__display_name")

    def get_readonly_fields(self, request, obj=None):
        return ("owner",) if obj else ()

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            locked_admin_principals(request, obj.owner_id)
            if not self.allows(request, "edit"):
                raise PermissionDenied
            if change:
                current = Enrollment.objects.select_for_update().get(pk=obj.pk)
                if obj.owner_id != current.owner_id:
                    raise PermissionDenied("A titularidade da matrícula é permanente.")
                fields = set(form.changed_data) & {
                    "plan",
                    "status",
                    "valid_from",
                    "valid_to",
                }
                for name in fields:
                    setattr(current, name, getattr(obj, name))
                try:
                    current.full_clean()
                except ValidationError:
                    raise PermissionDenied(
                        "Matrícula alterada durante a edição; recarregue o formulário."
                    ) from None
                current.save(update_fields=[*fields, "updated_at"])
                obj.refresh_from_db()
            else:
                if Enrollment.objects.filter(owner_id=obj.owner_id).exists():
                    raise PermissionDenied(
                        "Esta pessoa já possui matrícula; edite a existente."
                    )
                try:
                    obj.full_clean()
                except ValidationError:
                    raise PermissionDenied(
                        "Matrícula inválida; recarregue o formulário."
                    ) from None
                obj.save()
            record_audit(
                "admin.enrollment.changed",
                actor=request.user,
                request=request,
                target=obj,
                metadata={"fields": sorted(form.changed_data)},
            )
