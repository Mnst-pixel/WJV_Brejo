from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

from . import models
from .permissions import active_role_slugs, request_has_permission
from .rbac_policy import MODEL_RESOURCES, PRIVILEGED_ROLES


class PolicyAdmin(admin.ModelAdmin):
    """Django permissions and is_staff never independently grant domain access."""
    actions = None

    def allows(self, request, action):
        resource = MODEL_RESOURCES.get(self.model._meta.model_name)
        return bool(resource and request_has_permission(request, f"{resource}.{action}"))

    def has_module_permission(self, request):
        return self.allows(request, "read")

    def has_view_permission(self, request, obj=None):
        return self.allows(request, "read")

    def has_add_permission(self, request):
        return self.allows(request, "create")

    def has_change_permission(self, request, obj=None):
        return self.allows(request, "edit")

    def has_delete_permission(self, request, obj=None):
        return False  # Destructive transitions require dedicated audited commands.

    def get_readonly_fields(self, request, obj=None):
        guarded = {"status", "state", "current_version", "approved_by", "approved_at", "approval_date", "published_at", "created_by", "previous_version"}
        return tuple(field.name for field in self.model._meta.fields if field.name in guarded)

    def save_model(self, request, obj, form, change):
        from .audit import record_audit
        if not (self.has_change_permission(request, obj) if change else self.has_add_permission(request)):
            raise PermissionDenied
        if not change and hasattr(obj, "created_by_id"):
            obj.created_by = request.user
        if change and isinstance(obj, models.Content) and obj.status in {"approved", "published", "archived"}:
            raise PermissionDenied("Conteúdo aprovado exige nova versão no workflow.")
        super().save_model(request, obj, form, change)
        record_audit("admin.resource.changed", actor=request.user, request=request, target=obj,
                     metadata={"fields": sorted(form.changed_data)})

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # A cross-resource relation must not become a read side channel or escalation.
        for field in form.base_fields.values():
            if hasattr(field, "queryset") and field.queryset is not None:
                related = MODEL_RESOURCES.get(field.queryset.model._meta.model_name)
                if not related or not request_has_permission(request, f"{related}.read"):
                    field.queryset = field.queryset.none()
        return form


class ReadOnlyPolicyAdmin(PolicyAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


class AccountProfileForm(forms.ModelForm):
    class Meta:
        model = models.User
        fields = ("username", "display_name", "email", "is_active")

@admin.register(models.User)
class KairosUserAdmin(PolicyAdmin, UserAdmin):
    form = AccountProfileForm
    fieldsets = ((None, {"fields": ("username", "display_name", "email", "is_active")}),)
    readonly_fields = ("username",)
    list_display = ("username", "display_name", "is_active")
    list_filter = ("is_active",)

    def get_readonly_fields(self, request, obj=None):
        return ("username",)

    def has_add_permission(self, request):
        return False  # Dedicated provisioning must establish role and MFA safely.

    def has_change_permission(self, request, obj=None):
        if not self.allows(request, "manage"):
            return False
        if obj is None:
            return True
        if obj.pk == request.user.pk:
            return False
        actor_super = request.user.is_superuser or "superadministrador" in active_role_slugs(request.user)
        protected_assignment = obj.role_assignments.filter(role__slug__in=PRIVILEGED_ROLES).exists()
        return actor_super or not (obj.is_superuser or protected_assignment)

    def save_model(self, request, obj, form, change):
        # Profile edits can invalidate authorization; invalidate every existing session.
        obj.session_version += 1
        super().save_model(request, obj, form, change)

    def user_change_password(self, request, id, form_url=""):
        # The inherited password route must not bypass the dedicated reset flow.
        raise PermissionDenied("Use o fluxo de recuperação de senha.")


admin.site.site_header = "Administração Kairós"
admin.site.site_title = "Kairós"
admin.site.index_title = "Conteúdo, corpus e operações"
if admin.site.is_registered(Group):
    admin.site.unregister(Group)

for model in (models.Role, models.Permission, models.UserRole, models.AuditLog,
              models.ContentVersion, models.SourceDocumentVersion, models.AgentRun,
              models.Agent, models.IngestionRun, models.CorpusUpdate):
    admin.site.register(model, ReadOnlyPolicyAdmin)

for model in (models.Subject, models.Topic, models.Content, models.SourceRegistry, models.AssetRegistry,
              models.Exam, models.ExamPhase, models.Question, models.PracticalCase,
              models.SourceDocument, models.CoverageRecord):
    admin.site.register(model, PolicyAdmin)

