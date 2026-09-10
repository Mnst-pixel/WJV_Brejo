from django.urls import path

from core import editorial_views as views

app_name = "editorial"
urlpatterns = [
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
