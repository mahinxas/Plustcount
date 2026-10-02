from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.permissions import admin_required

from . import importer
from .access import get_visible_client_or_404, visible_clients
from .filters import active_filters, filter_clients
from .models import Client
from .forms import ClientForm, ImportMappingForm, ImportUploadForm, active_users
from .services import assign_clients
from .validators import normalize_phone

User = get_user_model()

PAGE_SIZE = 50


def _safe_next(request, default):
    """Where to go after an action: the page the user came from, if it is on this site."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return candidate
    return default
IMPORT_SESSION_KEY = "client_import"


def client_list(request):
    user = request.user
    qs = filter_clients(user, request.GET)
    paginator = Paginator(qs, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    filters = active_filters(request.GET)

    everyone = visible_clients(user)
    status = request.GET.get("status", "")
    owner = request.GET.get("owner", "")
    tabs = [{"label": "All clients", "count": everyone.count(), "params": {"status": "", "owner": "" if owner == "none" else owner},
             "active": not status and owner != "none"}]
    if user.is_admin:
        tabs.append({"label": "Unassigned", "count": everyone.filter(owner__isnull=True).count(),
                     "params": {"status": "", "owner": "none"}, "active": owner == "none" and not status})
    tabs.append({"label": "Can't receive email", "count": everyone.filter(Q(opted_out=True) | Q(email="")).count(),
                 "params": {"status": "cannot_receive", "owner": "" if owner == "none" else owner},
                 "active": status in ("cannot_receive", "opted_out", "no_email")})

    return render(
        request,
        "clients/list.html",
        {
            "page": page,
            "page_range": paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
            "total": paginator.count,
            "filters": filters,
            "filter_query": urlencode(filters),
            "tabs": tabs,
            "can_email": status not in ("cannot_receive", "opted_out", "no_email"),
            "members": active_users() if user.is_admin else None,
            "professions": Client.Profession.choices,
        },
    )


def client_detail(request, pk):
    client = get_visible_client_or_404(request.user, pk)
    tab = request.GET.get("tab", "messages")
    context = {"client": client, "tab": tab}
    if tab == "history":
        context["assignments"] = client.assignments.select_related("from_user", "to_user", "changed_by")
    elif tab == "messages":
        context["client_messages"] = list(client.messages.select_related("campaign__sender").order_by("-created_at")[:100])
        from messaging.services import refresh_sms_status

        refresh_sms_status(context["client_messages"])
    if request.user.is_admin:
        context["members"] = active_users()
    return render(request, "clients/detail.html", context)


@admin_required
def client_create(request):
    form = ClientForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            owner = form.cleaned_data.pop("owner", None)
            client = form.save(commit=False)
            client.owner = None
            client.save()
            if owner:
                assign_clients(request.user, [client], owner)
        messages.success(request, f"Client {client.name} added.")
        return redirect("clients:detail", pk=client.pk)
    return render(request, "clients/form.html", {"form": form, "title": "Add client"})


def client_edit(request, pk):
    client = get_visible_client_or_404(request.user, pk)
    old_owner = client.owner
    form = ClientForm(request.POST or None, instance=client, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            new_owner = form.cleaned_data.get("owner", old_owner) if request.user.is_admin else old_owner
            client = form.save(commit=False)
            client.owner = old_owner  # ownership only changes through assign_clients (keeps history)
            if client.opted_out and not client.opted_out_at:
                client.opted_out_at = timezone.now()
            elif not client.opted_out:
                client.opted_out_at = None
            client.save()
            if request.user.is_admin and new_owner != old_owner:
                assign_clients(request.user, [client], new_owner)
        messages.success(request, f"{client.name} saved.")
        return redirect(_safe_next(request, reverse("clients:detail", args=[client.pk])))
    return render(request, "clients/form.html", {
        "form": form,
        "client": client,
        "title": f"Edit {client.name}",
        "next": _safe_next(request, ""),
    })


QUICK_FIELDS = {"email": "Email", "phone": "Phone"}


@require_POST
def quick_update(request, pk):
    """Fill in one missing contact detail straight from the client list."""
    client = get_visible_client_or_404(request.user, pk)
    field = request.POST.get("field", "")
    value = (request.POST.get("value") or "").strip()
    back = _safe_next(request, reverse("clients:detail", args=[client.pk]))
    if field not in QUICK_FIELDS:
        messages.error(request, "This detail can't be edited here.")
        return redirect(back)
    try:
        if field == "email":
            value = value.lower()
            validate_email(value)
        else:
            value = normalize_phone(value)
            if not value:
                raise ValidationError("empty")
    except ValidationError:
        messages.error(request, f"{QUICK_FIELDS[field]} for {client.name} is not valid. Nothing was saved.")
        return redirect(back)
    setattr(client, field, value)
    client.save(update_fields=[field, "updated_at"])
    messages.success(request, f"{QUICK_FIELDS[field]} saved for {client.name}.")
    return redirect(back)


@admin_required
@require_POST
def client_delete(request, pk):
    client = get_object_or_404(visible_clients(request.user), pk=pk)
    name = client.name
    client.delete()
    messages.success(request, f"Client {name} and their message history were deleted.")
    return redirect("clients:list")


@admin_required
@require_POST
def bulk_assign(request):
    """Assign, move or unassign the selected clients."""
    ids = [int(i) for i in request.POST.getlist("client_ids") if i.isdigit()]
    target = request.POST.get("assign_to", "")
    next_url = _safe_next(request, reverse("clients:list"))

    if not ids:
        messages.error(request, "Select at least one client first.")
        return redirect(next_url)
    if target == "none":
        to_user = None
    elif target.isdigit():
        to_user = get_object_or_404(User, pk=int(target), is_active=True)
    else:
        messages.error(request, "Choose who the clients should go to.")
        return redirect(next_url)

    clients = list(visible_clients(request.user).filter(pk__in=ids))
    changed = assign_clients(request.user, clients, to_user)
    if to_user:
        messages.success(request, f"{changed} client(s) assigned to {to_user.display_name}.")
    else:
        messages.success(request, f"{changed} client(s) are now unassigned.")
    return redirect(next_url)


# --- Import ------------------------------------------------------------------------


@admin_required
def import_upload(request):
    form = ImportUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            headers, rows = importer.read_table(form.cleaned_data["file"])
        except importer.ImportFileError as exc:
            form.add_error("file", str(exc))
        else:
            request.session[IMPORT_SESSION_KEY] = {
                "filename": form.cleaned_data["file"].name,
                "headers": headers,
                "rows": rows,
            }
            return redirect("clients:import_map")
    return render(request, "clients/import_upload.html", {"form": form})


@admin_required
def import_map(request):
    data = request.session.get(IMPORT_SESSION_KEY)
    if not data:
        return redirect("clients:import_upload")
    form = ImportMappingForm(
        request.POST or None,
        headers=data["headers"],
        fields=importer.FIELDS,
        initial_mapping=importer.guess_mapping(data["headers"]),
    )
    if request.method == "POST" and form.is_valid():
        data["mapping"] = form.mapping()
        data["owner_id"] = form.cleaned_data["owner"].pk if form.cleaned_data["owner"] else None
        request.session[IMPORT_SESSION_KEY] = data
        return redirect("clients:import_preview")
    return render(
        request,
        "clients/import_map.html",
        {"form": form, "filename": data["filename"], "row_count": len(data["rows"]), "sample": data["rows"][:3], "headers": data["headers"]},
    )


@admin_required
def import_preview(request):
    data = request.session.get(IMPORT_SESSION_KEY)
    if not data or "mapping" not in data:
        return redirect("clients:import_upload")
    owner = User.objects.filter(pk=data.get("owner_id"), is_active=True).first() if data.get("owner_id") else None
    results = importer.validate_rows(data["rows"], data["mapping"])

    if request.method == "POST":
        created = importer.save_rows(results, request.user, owner)
        del request.session[IMPORT_SESSION_KEY]
        messages.success(request, f"{created} client(s) imported.")
        return redirect("clients:list")

    valid = [r for r in results if not r["errors"] and not r["duplicate"]]
    problems = [r for r in results if r["errors"] or r["duplicate"]]
    return render(
        request,
        "clients/import_preview.html",
        {
            "filename": data["filename"],
            "valid_count": len(valid),
            "valid_sample": valid[:20],
            "problems": problems,
            "owner": owner,
        },
    )


@admin_required
@require_POST
def import_cancel(request):
    request.session.pop(IMPORT_SESSION_KEY, None)
    return redirect("clients:list")
