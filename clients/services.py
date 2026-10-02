from django.db import transaction

from .models import Client, ClientAssignment


@transaction.atomic
def assign_clients(actor, clients, to_user):
    """Give each client to ``to_user`` (or make it unassigned when None).

    Records one history row per client whose owner actually changes and
    returns the number of changed clients. The new owner sees the client (and
    its full message history) at once; the old owner loses access at once,
    because access is checked against ``Client.owner`` on every request.
    """
    if not actor.is_admin:
        raise PermissionError("Only admins can assign clients.")
    if to_user is not None and not to_user.is_active:
        raise ValueError("Cannot assign clients to a deactivated user.")

    ids = [c.pk for c in clients]
    locked = Client.objects.select_for_update().filter(pk__in=ids)
    history = []
    changed_ids = []
    for client in locked:
        if client.owner_id == (to_user.pk if to_user else None):
            continue
        history.append(
            ClientAssignment(client=client, from_user_id=client.owner_id, to_user=to_user, changed_by=actor)
        )
        changed_ids.append(client.pk)

    Client.objects.filter(pk__in=changed_ids).update(owner=to_user)
    ClientAssignment.objects.bulk_create(history)
    return len(changed_ids)
