from django.urls import path

from core import editorial_views as views
from core import question_editorial as questions
from core import second_phase_editorial as phase2

app_name = "editorial"
urlpatterns = [
    path("segunda-fase/", phase2.case_list, name="phase2"),
    path("segunda-fase/areas/nova/", phase2.area_create, name="phase2-area-create"),
    path("segunda-fase/provas/nova/", phase2.exam_create, name="phase2-exam-create"),
    path("segunda-fase/casos/novo/", phase2.case_edit, name="phase2-create"),
    path("segunda-fase/versoes/<uuid:workflow_id>/", phase2.case_detail, name="phase2-case"),
    path("segunda-fase/versoes/<uuid:workflow_id>/revisar/", phase2.case_edit, name="phase2-revise"),
    path("questoes/", questions.question_list, name="questions"),
    path("questoes/nova/", questions.question_create, name="question-create"),
    path("questoes/versoes/<uuid:workflow_id>/", questions.question_detail, name="question-version"),
    path("questoes/versoes/<uuid:workflow_id>/revisar/", questions.question_revise, name="question-revise"),
    path("provas/nova/", questions.exam_create, name="exam-create"),
    path("", views.dashboard, name="dashboard"),
    path("conteudos/", views.content_list, name="contents"),
    path("conteudos/novo/", views.content_create, name="content-create"),
    path("conteudos/<uuid:content_id>/", views.content_detail, name="content"),
    path("versoes/<uuid:version_id>/", views.version_detail, name="version"),
    path("versoes/<uuid:version_id>/revisar/", views.revision_create, name="revise"),
    path("disciplinas/", views.taxonomy, name="taxonomy"),
    path("disciplinas/nova/", views.taxonomy_create, {"kind": "subject"}, name="subject-create"),
    path("temas/novo/", views.taxonomy_create, {"kind": "topic"}, name="topic-create"),
    path("legado/", views.legacy_import, name="legacy"),
    path("legado/<uuid:batch_id>/", views.legacy_preview, name="legacy-preview"),
]
