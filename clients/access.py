"""The single place that decides which clients a user may see and act on.

Every page and every send action goes through these functions, so access is
always enforced on the server and never only by hiding things in the UI.
"""

from django.shortcuts import get_object_or_404

from .models import Client


def visible_clients(user):
    if not user.is_authenticated or not user.is_active:
        return Client.objects.none()
    if user.is_admin:
        return Client.objects.all()
    return Client.objects.filter(owner=user)


def get_visible_client_or_404(user, pk):
    # 404 rather than 403 so a member cannot probe which client IDs exist.
    return get_object_or_404(visible_clients(user), pk=pk)
