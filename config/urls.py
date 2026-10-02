from django.contrib import admin
from django.urls import include, path

from .health import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("", include("accounts.urls")),
    path("clients/", include("clients.urls")),
    path("messages/", include("messaging.urls")),
    path("django-admin/", admin.site.urls),
]
