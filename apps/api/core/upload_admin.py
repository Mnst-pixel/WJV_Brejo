"""Ordinary forms for upload limits and enrollment; no JSON or shell required."""

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect

from .admin import PolicyAdmin
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
    """Old bookmarks reach the canonical workspace; old POST bodies never mutate."""

    def allows(self, request, action):
        return action == "read" and request_has_permission(request, "settings.read")

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Use o painel de assinaturas para registrar uma decisão atualizada.")

    def _authorize_redirect(self, request):
        if request.method != "GET" or not self.allows(request, "read"):
            raise PermissionDenied("Use o painel de assinaturas com um papel autorizado.")

    def changelist_view(self, request, extra_context=None):
        self._authorize_redirect(request)
        return redirect("editorial:subscriptions")

    def add_view(self, request, form_url="", extra_context=None):
        self._authorize_redirect(request)
        if not request_has_permission(request, "settings.manage"):
            return redirect("editorial:subscriptions")
        return redirect({Plan: "editorial:plan-create", UploadPolicy: "editorial:upload-policy", Enrollment: "editorial:accounts"}[self.model])

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self._authorize_redirect(request)
        if not request_has_permission(request, "settings.manage"):
            return redirect("editorial:subscriptions")
        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404("Registro indisponível.")
        if self.model is Plan:
            return redirect("editorial:plan-edit", plan_id=obj.pk)
        if self.model is Enrollment:
            return redirect("editorial:enrollment", user_id=obj.owner_id)
        return redirect("editorial:upload-policy")


admin.site.register((Plan, UploadPolicy, Enrollment), UploadSettingsAdmin)
