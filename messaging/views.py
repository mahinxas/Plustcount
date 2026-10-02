import uuid
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import admin_required
from clients.access import get_visible_client_or_404, visible_clients

from . import personalize, services, sms
from .forms import ComposeForm, TemplateForm
from .models import Campaign, Channel, Message, MessageTemplate


def _selection_from_request(request):
    """Work out which clients the user picked, from the list page or a client page."""
    if request.method == "GET":
        client_id = request.GET.get("client", "")
        if client_id.isdigit():
            get_visible_client_or_404(request.user, int(client_id))
            return services.encode_ids([int(client_id)])
        return ""
    if request.POST.get("recipients"):
        return request.POST["recipients"]
    if request.POST.get("scope") == "all_matching":
        return "filter:" + request.POST.get("filter_query", "")
    ids = [int(i) for i in request.POST.getlist("client_ids") if i.isdigit()]
    return services.encode_ids(ids) if ids else ""


def _channel_from_request(request):
    value = request.POST.get("channel") or request.GET.get("channel") or Channel.EMAIL
    return value if value in Channel.values else Channel.EMAIL


def compose(request):
    selection = _selection_from_request(request)
    if not selection:
        messages.info(request, "Select the clients you want to message first.")
        return redirect("clients:list")

    channel = _channel_from_request(request)
    is_sms = channel == Channel.SMS
    summary = services.summarize(services.recipients_queryset(request.user, selection), channel)
    if not summary.total_selected:
        messages.error(request, "None of the selected clients are available to you.")
        return redirect("clients:list")

    step = request.POST.get("step", "edit")
    if step == "edit":
        # First arrival (from the list or a client page), "Back" from the confirm page, or a channel switch.
        initial = {
            "channel": channel,
            "recipients": selection,
            "idempotency_key": request.POST.get("idempotency_key") or uuid.uuid4().hex,
        }
        for key in ("template", "due_date", "subject_fi", "body_fi", "subject_en", "body_en"):
            if key in request.POST:
                initial[key] = request.POST[key]
        if initial.get("template") and not MessageTemplate.objects.filter(pk=initial["template"], channel=channel).exists():
            initial.pop("template")  # a template for the other channel
        form = ComposeForm(initial=initial, languages=summary.languages, channel=channel)
    else:
        form = ComposeForm(request.POST, languages=summary.languages, channel=channel)

    channel_word = "SMS" if is_sms else "email"
    quota = services.quota_for(channel)
    over_limit = bool(quota and len(summary.sendable) > quota.remaining)
    if step in ("confirm", "send") and form.is_valid():
        if not summary.sendable:
            missing = "phone number" if is_sms else "email address"
            messages.error(request, f"No selected client can receive {channel_word} (opted out or no {missing}).")
        elif over_limit:
            messages.error(
                request,
                f"Only {quota.remaining} of today's {quota.limit} {'SMS' if is_sms else 'emails'} are left, and this send needs "
                f"{len(summary.sendable)}. Select fewer clients or send the rest tomorrow.",
            )
        elif step == "confirm":
            content = form.content()
            return render(request, "messaging/confirm.html", {
                "form": form,
                "summary": summary,
                "channel": channel,
                "previews": _previews(summary, content, channel),
                "sms_total": sum(sms.segments(services.render_for(c, content, channel)[1]) for c in summary.sendable)
                if is_sms else 0,
                "quota": quota,
            })
        else:
            try:
                campaign = services.create_campaign(
                    request.user,
                    form.cleaned_data["recipients"],
                    form.content(),
                    form.cleaned_data["idempotency_key"],
                    template=form.cleaned_data.get("template"),
                    channel=channel,
                )
            except services.DuplicateSend as dup:
                campaign = dup.campaign
            except services.DailyLimitReached as exc:
                # Someone else used up the day's emails between review and send.
                messages.error(request, f"{exc} Select fewer clients or send the rest tomorrow.")
                return redirect("clients:list")
            messages.success(request, f"Sending {channel_word} to {campaign.recipient_count} client(s).")
            return redirect("messaging:campaign_detail", pk=campaign.pk)

    templates = {
        str(t.pk): {"subject_fi": t.subject_fi, "body_fi": t.body_fi, "subject_en": t.subject_en, "body_en": t.body_en}
        for t in MessageTemplate.objects.filter(channel=channel)
    }
    samples = {
        lang: personalize.context_for(client, "")
        for lang in ("fi", "en")
        if (client := summary.first_in(lang))
    }
    return render(request, "messaging/compose.html", {
        "form": form,
        "summary": summary,
        "channel": channel,
        "is_sms": is_sms,
        "templates_json": templates,
        "samples_json": samples,
        "fields": personalize.FIELDS,
        "single_language": len(summary.languages) <= 1,
        "fi_count": sum(1 for c in summary.sendable if c.language == "fi"),
        "en_count": sum(1 for c in summary.sendable if c.language == "en"),
        "quota": quota,
        "over_limit": over_limit,
        "sms_max_parts": sms.MAX_PARTS,
        "sms_rules": {"basic": "".join(sorted(sms._GSM_BASIC)), "extended": "".join(sorted(sms._GSM_EXTENDED)), "max": sms.MAX_PARTS},
    })


def _previews(summary, content, channel=Channel.EMAIL):
    previews = []
    for lang in ("fi", "en"):
        client = summary.first_in(lang)
        if client:
            subject, body = services.render_for(client, content, channel)
            count = sum(1 for c in summary.sendable if c.language == lang)
            previews.append({
                "lang": lang, "client": client, "subject": subject, "body": body, "count": count,
                "to": services.address_of(client, channel), "parts": sms.segments(body),
            })
    return previews


# --- Message log -------------------------------------------------------------------------


def message_log(request):
    base = Message.objects.filter(client__in=visible_clients(request.user)).select_related("client", "campaign__sender")
    days = request.GET.get("days", "")
    if days.isdigit():
        base = base.filter(created_at__gte=timezone.now() - timedelta(days=int(days)))
    channel = request.GET.get("channel", "")
    if channel in Channel.values:
        base = base.filter(channel=channel)
    else:
        channel = ""
    q = (request.GET.get("q") or "").strip()
    if q:
        base = base.filter(
            Q(client__name__icontains=q) | Q(subject__icontains=q) | Q(to_address__icontains=q) | Q(body__icontains=q)
        )

    pending = [Message.Status.QUEUED, Message.Status.SENDING]
    counts = base.aggregate(
        all=Count("id"),
        sent=Count("id", filter=Q(status=Message.Status.SENT)),
        failed=Count("id", filter=Q(status=Message.Status.FAILED)),
        pending=Count("id", filter=Q(status__in=pending)),
    )
    status = request.GET.get("status", "")
    qs = base
    if status == "pending":
        qs = qs.filter(status__in=pending)
    elif status in (Message.Status.SENT, Message.Status.FAILED):
        qs = qs.filter(status=status)
    else:
        status = ""
    tabs = [
        {"label": "All", "value": "", "count": counts["all"]},
        {"label": "Sent", "value": "sent", "count": counts["sent"]},
        {"label": "Failed", "value": "failed", "count": counts["failed"], "alert": counts["failed"] > 0},
        {"label": "In progress", "value": "pending", "count": counts["pending"]},
    ]
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    services.refresh_sms_status(page.object_list)

    campaigns = Campaign.objects.select_related("sender").annotate(
        sent=Count("messages", filter=Q(messages__status=Message.Status.SENT)),
        failed=Count("messages", filter=Q(messages__status=Message.Status.FAILED)),
    ).order_by("-created_at")  # Meta ordering is dropped once counts are added
    if not request.user.is_admin:
        campaigns = campaigns.filter(sender=request.user)
    return render(request, "messaging/log.html", {
        "page": page,
        "page_range": paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "campaigns": campaigns[:5],
        "tabs": tabs,
        "status": status,
        "q": q,
        "days": days if days.isdigit() else "",
        "channel": channel,
        "channels": Channel.choices,
    })


def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign.objects.select_related("sender", "template"), pk=pk)
    if not request.user.is_admin and campaign.sender_id != request.user.pk:
        # Members only see their own sends; admins see everything.
        raise Http404
    msgs = list(campaign.messages.filter(client__in=visible_clients(request.user)).select_related("client"))
    services.refresh_sms_status(msgs)
    counts = {s: 0 for s in Message.Status.values}
    for row in campaign.messages.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]
    sms_parts = campaign.messages.aggregate(n=Sum("sms_parts"))["n"] or 0
    return render(request, "messaging/campaign_detail.html", {
        "campaign": campaign,
        "message_list": msgs,
        "counts": counts,
        "in_progress": counts["queued"] + counts["sending"] > 0,
        "sms_parts": sms_parts,
        "retryable": sum(1 for m in msgs if m.can_retry),
        "cancellable": sum(1 for m in msgs if m.can_cancel),
    })


# --- Templates ---------------------------------------------------------------------------


def template_list(request):
    channel = request.GET.get("channel", Channel.EMAIL)
    if channel not in Channel.values:
        channel = Channel.EMAIL
    counts = {c: MessageTemplate.objects.filter(channel=c).count() for c in Channel.values}
    return render(request, "messaging/template_list.html", {
        "templates": MessageTemplate.objects.filter(channel=channel),
        "channel": channel,
        "counts": counts,
    })


@admin_required
def template_edit(request, pk=None):
    template = get_object_or_404(MessageTemplate, pk=pk) if pk else None
    start_channel = request.GET.get("channel") if request.GET.get("channel") in Channel.values else Channel.EMAIL
    form = TemplateForm(request.POST or None, instance=template, initial=None if template else {"channel": start_channel})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if obj.created_by_id is None:
            obj.created_by = request.user
        obj.save()
        messages.success(request, f"Template “{obj.title}” saved.")
        return redirect(f"{reverse('messaging:templates')}?channel={obj.channel}")
    return render(request, "messaging/template_form.html", {
        "form": form,
        "template_obj": template,
        "fields": personalize.FIELDS,
        "sms_rules": {"basic": "".join(sorted(sms._GSM_BASIC)), "extended": "".join(sorted(sms._GSM_EXTENDED)), "max": sms.MAX_PARTS},
    })


@admin_required
@require_POST
def template_delete(request, pk):
    template = get_object_or_404(MessageTemplate, pk=pk)
    template.delete()
    messages.success(request, f"Template “{template.title}” deleted.")
    return redirect("messaging:templates")


# --- Retry / cancel -------------------------------------------------------------------------


def _messages_for_action(request, campaign_pk=None):
    qs = Message.objects.filter(client__in=visible_clients(request.user)).select_related("campaign", "client")
    if not request.user.is_admin:
        qs = qs.filter(campaign__sender=request.user)
    if campaign_pk:
        qs = qs.filter(campaign_id=campaign_pk)
    ids = [int(i) for i in request.POST.getlist("message_ids") if i.isdigit() and len(i) < 18]
    if ids:
        return list(qs.filter(pk__in=ids))
    # Nothing ticked: only a whole-campaign action may act on "everything"; never the whole log.
    return list(qs) if campaign_pk else []


@require_POST
def message_action(request):
    action = request.POST.get("action")
    campaign_pk = request.POST.get("campaign") or None
    messages_list = _messages_for_action(request, campaign_pk)
    if action == "retry":
        n = services.retry_messages(messages_list)
        messages.success(request, f"{n} message(s) queued again.") if n else messages.info(request, "Nothing to retry.")
    elif action == "cancel":
        n = services.cancel_messages(messages_list)
        messages.success(request, f"{n} message(s) cancelled.") if n else messages.info(request, "Nothing to cancel.")
    back = request.POST.get("next", "")
    if not back.startswith("/") or back.startswith("//"):
        back = reverse("messaging:log")
    return redirect(back)
