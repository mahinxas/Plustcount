from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from clients.access import visible_clients
from clients.models import Client
from messaging.models import Campaign, Message
from messaging.services import email_quota, sms_quota, sms_sent_today

from .forms import TeamMemberForm
from .models import User
from .permissions import admin_required


def dashboard(request):
    user = request.user
    now = timezone.now()
    clients = visible_clients(user)
    campaigns = Campaign.objects.select_related("sender").annotate(
        sent=Count("messages", filter=Q(messages__status=Message.Status.SENT)),
        failed=Count("messages", filter=Q(messages__status=Message.Status.FAILED)),
    ).order_by("-created_at")  # Meta ordering is dropped once counts are added
    messages_qs = Message.objects.filter(client__in=clients)
    if not user.is_admin:
        campaigns = campaigns.filter(sender=user)
        messages_qs = messages_qs.filter(campaign__sender=user)

    by_profession = {row["profession"]: row["n"] for row in clients.values("profession").annotate(n=Count("id"))}
    professions = _donut_segments(
        [{"value": value, "label": label, "count": by_profession.get(value, 0)} for value, label in Client.Profession.choices]
    )
    context = {
        "client_count": clients.count(),
        "opted_out_count": clients.filter(opted_out=True).count(),
        "no_email_count": clients.filter(email="").count(),
        # Counted once even when a client is both opted out and missing an email.
        "cannot_receive_count": clients.filter(Q(opted_out=True) | Q(email="")).count(),
        "sent_30d": messages_qs.filter(status=Message.Status.SENT, created_at__gte=now - timedelta(days=30)).count(),
        "sms_30d": messages_qs.filter(
            status=Message.Status.SENT, channel="sms", created_at__gte=now - timedelta(days=30)
        ).count(),
        "failed_recent": messages_qs.filter(status=Message.Status.FAILED, created_at__gte=now - timedelta(days=7)).count(),
        "recent_campaigns": campaigns[:6],
        "professions": professions,
        "profession_total": sum(p["count"] for p in professions),
    }
    context["email_30d"] = context["sent_30d"] - context["sms_30d"]
    context["usage_bars"] = [
        _usage_bar("Emails today", "mail", "emails", email_quota()),
        _usage_bar("SMS today", "phone", "SMS", sms_quota()),
    ]
    if not sms_quota():
        context["usage_bars"].append({"title": "SMS today", "icon": "phone", "word": "SMS", "unlimited": True,
                                      "sent": sms_sent_today()})
    context["usage_bars"] = [b for b in context["usage_bars"] if b]
    if user.is_admin:
        team = sorted(
            (m for m in _team_rows().filter(is_active=True) if m.role == User.Role.MEMBER or m.client_count),
            key=lambda m: (-m.client_count, m.display_name),
        )
        context["team"] = team
        context["team_max"] = max([m.client_count for m in team] + [1])
        context["unassigned_count"] = clients.filter(owner__isnull=True).count()
    return render(request, "accounts/dashboard.html", context)


def _usage_bar(title, icon, word, quota):
    if not quota:
        return None
    pct = min(round(100 * quota.used / quota.limit), 100)
    level = "danger" if quota.remaining == 0 else "warning" if pct >= 80 else "ok"
    return {"title": title, "icon": icon, "word": word, "quota": quota, "pct": pct, "level": level}


DONUT_GAP = 0.6  # gap between segments, in % of the circumference (about 2px on screen)


def _donut_segments(items):
    """Add donut geometry to each item. The circle uses pathLength=100, so dash values are percentages.

    Colour follows the entity: each item keeps its slot (1-4) by its fixed position in the list,
    whatever its count, so filtering never repaints a profession.
    """
    total = sum(i["count"] for i in items)
    offset = 0.0
    for slot, item in enumerate(items, start=1):
        pct = 100 * item["count"] / total if total else 0
        item["slot"] = slot
        item["pct"] = round(pct)
        item["dash"] = f"{max(pct - DONUT_GAP, 0):.2f}" if pct < 100 else "100"
        item["rest"] = f"{100 - max(pct - DONUT_GAP, 0):.2f}"
        item["offset"] = f"{-offset:.2f}"
        offset += pct
    return items


def _team_rows():
    since = timezone.now() - timedelta(days=30)
    return User.objects.annotate(
        client_count=Count("clients", distinct=True),
        sent_30d=Count(
            "campaigns__messages",
            filter=Q(campaigns__messages__status=Message.Status.SENT, campaigns__messages__created_at__gte=since),
            distinct=True,
        ),
    ).order_by("-is_active", "first_name", "last_name")


@admin_required
def team_list(request):
    return render(request, "accounts/team_list.html", {"team": _team_rows()})


@admin_required
def team_member_edit(request, pk=None):
    member = get_object_or_404(User, pk=pk) if pk else None
    form = TeamMemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        if member == request.user and (not form.cleaned_data["is_active"] or form.cleaned_data["role"] != User.Role.ADMIN):
            form.add_error(None, "You cannot deactivate yourself or remove your own admin role.")
        else:
            saved = form.save()
            if member and not saved.is_active and saved.clients.exists():
                messages.warning(
                    request,
                    f"{saved.display_name} is deactivated but still has {saved.clients.count()} client(s). "
                    "Reassign them from the client list.",
                )
            else:
                messages.success(request, f"{saved.display_name} saved.")
            return redirect("team")
    return render(request, "accounts/team_form.html", {"form": form, "member": member})
