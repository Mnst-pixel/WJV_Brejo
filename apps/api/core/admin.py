from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    Agent,
    AgentRun,
    AssetRegistry,
    AuditLog,
    Content,
    ContentVersion,
    CorpusUpdate,
    CoverageRecord,
    Exam,
    ExamPhase,
    IngestionRun,
    Permission,
    PracticalCase,
    Question,
    Role,
    SourceDocument,
    SourceDocumentVersion,
    SourceRegistry,
    Subject,
    Topic,
    User,
    UserRole,
)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "action", "actor", "target_type", "target_id")
    readonly_fields = [field.name for field in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SourceDocumentVersion)
class SourceDocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "state", "source_hash", "approval_date")
    list_filter = ("state",)
    readonly_fields = [field.name for field in SourceDocumentVersion._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.site_header = "Administração Kairós"
admin.site.site_title = "Kairós"
admin.site.index_title = "Conteúdo, corpus e operações"

@admin.register(User)
class KairosUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Kairós", {"fields": ("display_name", "preferences", "mfa_enabled", "failed_login_count", "locked_until", "session_version")}),
    )
    readonly_fields = ("mfa_secret_encrypted",)


for model in [
    Role,
    Permission,
    UserRole,
    Subject,
    Topic,
    Content,
    ContentVersion,
    SourceRegistry,
    AssetRegistry,
    Exam,
    ExamPhase,
    Question,
    PracticalCase,
    SourceDocument,
    IngestionRun,
    CorpusUpdate,
    CoverageRecord,
    Agent,
    AgentRun,
]:
    admin.site.register(model)
