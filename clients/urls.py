from django.urls import path

from . import views

app_name = "clients"

urlpatterns = [
    path("", views.client_list, name="list"),
    path("new/", views.client_create, name="create"),
    path("assign/", views.bulk_assign, name="bulk_assign"),
    path("import/", views.import_upload, name="import_upload"),
    path("import/columns/", views.import_map, name="import_map"),
    path("import/preview/", views.import_preview, name="import_preview"),
    path("import/cancel/", views.import_cancel, name="import_cancel"),
    path("<int:pk>/", views.client_detail, name="detail"),
    path("<int:pk>/edit/", views.client_edit, name="edit"),
    path("<int:pk>/quick/", views.quick_update, name="quick_update"),
    path("<int:pk>/delete/", views.client_delete, name="delete"),
]
