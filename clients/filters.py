from django.db.models import Q

from .access import visible_clients
from .models import Client

FILTER_PARAMS = ("q", "profession", "language", "owner", "status")


def filter_clients(user, params):
    """Visible clients for ``user`` narrowed by the list-page filters in ``params``.

    Used by the client list and by "send to all matching clients", so both
    always agree on exactly which clients are meant.
    """
    qs = visible_clients(user).select_related("owner")

    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(business_id__icontains=q)
            | Q(email__icontains=q)
            | Q(phone__icontains=q.replace(" ", ""))
        )

    profession = params.get("profession")
    if profession in Client.Profession.values:
        qs = qs.filter(profession=profession)

    language = params.get("language")
    if language in ("fi", "en"):
        qs = qs.filter(language=language)

    status = params.get("status")
    if status == "opted_out":
        qs = qs.filter(opted_out=True)
    elif status == "no_email":
        qs = qs.filter(email="")
    elif status == "cannot_receive":
        qs = qs.filter(Q(opted_out=True) | Q(email=""))

    owner = params.get("owner")
    if user.is_admin and owner:
        if owner == "none":
            qs = qs.filter(owner__isnull=True)
        elif owner.isdigit():
            qs = qs.filter(owner_id=int(owner))

    return qs


def active_filters(params):
    return {k: params.get(k) for k in FILTER_PARAMS if params.get(k)}
