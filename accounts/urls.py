from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .throttle import ThrottledLoginView

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("team/", views.team_list, name="team"),
    path("team/new/", views.team_member_edit, name="team_create"),
    path("team/<int:pk>/edit/", views.team_member_edit, name="team_edit"),
    # Login, logout and password reset use Django's built-in, well-tested views.
    path("login/", ThrottledLoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password-reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "password-reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(success_url=reverse_lazy("password_reset_complete")),
        name="password_reset_confirm",
    ),
    path("password-reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
