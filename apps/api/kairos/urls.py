from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/editorial/", include("core.editorial_urls")),
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
]
