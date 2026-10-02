from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("", views.message_log, name="log"),
    path("compose/", views.compose, name="compose"),
    path("sends/<int:pk>/", views.campaign_detail, name="campaign_detail"),
    path("actions/", views.message_action, name="message_action"),
    path("templates/", views.template_list, name="templates"),
    path("templates/new/", views.template_edit, name="template_create"),
    path("templates/<int:pk>/edit/", views.template_edit, name="template_edit"),
    path("templates/<int:pk>/delete/", views.template_delete, name="template_delete"),
]
