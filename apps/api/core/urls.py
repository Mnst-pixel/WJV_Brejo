from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .rbac_views import RoleCatalogView, UserRolesView
from .mcp_views import MCPDelegationView, MCPToolCallView
from .study_views import BrowserImportView, StudyActivityView, StudyPanelView, StudyRecordView, StudySummaryView
from .integration_views import IntegrationStatusView
from .content_views import AdminContentListView, ContentRevisionView, ContentTransitionView, LegacyContentPreviewView, LegacyContentConfirmView

router = DefaultRouter()
router.register("subjects", views.SubjectViewSet, basename="subject")
router.register("contents", views.ContentViewSet, basename="content")
router.register("questions", views.QuestionViewSet, basename="question")
router.register("simulations", views.SimulationViewSet, basename="simulation")
router.register("attempts", views.AttemptViewSet, basename="attempt")
router.register("goals", views.GoalViewSet, basename="goal")
router.register("notes", views.StudyNoteViewSet, basename="note")
router.register("flashcards", views.FlashcardViewSet, basename="flashcard")
router.register("bookmarks", views.BookmarkViewSet, basename="bookmark")
router.register("study-sessions", views.StudySessionViewSet, basename="study-session")
router.register("files", views.FileAssetViewSet, basename="file")
router.register("conversations", views.ConversationViewSet, basename="conversation")
router.register("admin/ingestion-runs", views.IngestionRunViewSet, basename="ingestion-run")
router.register("admin/document-versions", views.SourceDocumentVersionViewSet, basename="document-version")
router.register("coverage", views.CoverageRecordViewSet, basename="coverage")
router.register("admin/audit", views.AuditLogViewSet, basename="audit")

urlpatterns = [
    path("admin/content/", AdminContentListView.as_view()),
    path("admin/content/<uuid:content_id>/versions/", ContentRevisionView.as_view()),
    path("admin/content-versions/<uuid:version_id>/transition/", ContentTransitionView.as_view()),
    path("admin/legacy-content/preview/", LegacyContentPreviewView.as_view()),
    path("admin/legacy-content/<uuid:batch_id>/confirm/", LegacyContentConfirmView.as_view()),
    path("integrations/status/", IntegrationStatusView.as_view()),
    path("study/progress/", StudyRecordView.as_view(kind="progress")),
    path("study/progress/<uuid:record_id>/", StudyRecordView.as_view(kind="progress")),
    path("study/marks/", StudyRecordView.as_view(kind="marks")),
    path("study/marks/<uuid:record_id>/", StudyRecordView.as_view(kind="marks")),
    path("study/activities/", StudyActivityView.as_view()),
    path("study/panel/", StudyPanelView.as_view()),
    path("study/summary/", StudySummaryView.as_view()),
    path("study/browser-imports/", BrowserImportView.as_view()),
    path("study/browser-imports/<uuid:receipt_id>/", BrowserImportView.as_view()),
    path("mcp/delegate", MCPDelegationView.as_view()),
    path("mcp/call", MCPToolCallView.as_view()),
    path("admin/roles/", RoleCatalogView.as_view()),
    path("admin/users/<uuid:user_id>/roles/", UserRolesView.as_view()),
    path("health/live", views.health_live),
    path("health/ready", views.health_ready),
    path("auth/csrf", views.csrf_token),
    path("auth/login", views.SessionLoginView.as_view()),
    path("auth/logout", views.SessionLogoutView.as_view()),
    path("auth/mfa/setup", views.MFASetupView.as_view()),
    path("auth/mfa/verify", views.MFAVerifyView.as_view()),
    path("auth/password-reset", views.PasswordResetRequestView.as_view()),
    path("auth/password-reset/confirm", views.PasswordResetConfirmView.as_view()),
    path("auth/me", views.MeView.as_view()),
    path("ai/consult", views.ConsultView.as_view()),
    path("", include(router.urls)),
]
