from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import QueryDict
from django.utils import timezone

from clients.access import visible_clients
from clients.filters import filter_clients

from . import personalize, sms
from .models import Campaign, Channel, Message


# --- Recipients ----------------------------------------------------------------------
# A recipient selection is carried between compose steps as a short string:
#   "ids:1,2,3"          the clients ticked in the list
#   "filter:q=oy&profession=taxi"  every client matching the list filters
# It is re-resolved against visible_clients() on every step, so a client that
# was reassigned in the meantime can never be messaged by the old owner.


def encode_ids(ids):
    return "ids:" + ",".join(str(i) for i in ids)


def encode_filter(params):
    return "filter:" + urlencode(params)


def recipients_queryset(user, selection):
    kind, _, value = (selection or "").partition(":")
    if kind == "ids":
        ids = [int(i) for i in value.split(",") if i.strip().isdigit() and len(i.strip()) < 18]
        return visible_clients(user).filter(pk__in=ids)
    if kind == "filter":
        params = QueryDict(mutable=True)
        for key, values in parse_qs(value).items():
            params.setlist(key, values)
        return filter_clients(user, params)
    return visible_clients(user).none()


@dataclass
class RecipientSummary:
    sendable: list = field(default_factory=list)
    opted_out: int = 0
    no_address: int = 0

    @property
    def total_selected(self):
        return len(self.sendable) + self.opted_out + self.no_address

    @property
    def languages(self):
        return {c.language for c in self.sendable}

    def first_in(self, language):
        return next((c for c in self.sendable if c.language == language), None)


def address_of(client, channel):
    return client.phone if channel == Channel.SMS else client.email


def summarize(queryset, channel=Channel.EMAIL):
    """Split the selected clients into who can receive this channel and who is skipped."""
    summary = RecipientSummary()
    for client in queryset.order_by("name"):
        if client.opted_out:
            summary.opted_out += 1
        elif not address_of(client, channel):
            summary.no_address += 1
        else:
            summary.sendable.append(client)
    return summary


# --- Rendering -----------------------------------------------------------------------


def render_for(client, content, channel=Channel.EMAIL):
    """Return (subject, body) for one client, in the client's own language. SMS have no subject."""
    lang = client.language
    context = personalize.context_for(client, content.get("due_date", ""))
    subject = "" if channel == Channel.SMS else personalize.render(content.get(f"subject_{lang}", ""), context)
    body = personalize.render(content.get(f"body_{lang}", ""), context)
    return subject, body


# --- Daily email limit ------------------------------------------------------------------


def provider_day():
    """(start of the provider's current day, next reset) as aware datetimes."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    now = timezone.now().astimezone(ZoneInfo(settings.EMAIL_LIMIT_TIMEZONE))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


@dataclass
class Quota:
    limit: int
    used: int
    resets_at: object = None

    @property
    def remaining(self):
        return max(self.limit - self.used, 0)


def email_quota():
    """Emails the provider still accepts today, or None when no limit applies.

    No limit applies when EMAIL_DAILY_LIMIT is 0, or in test mode without a test
    recipient (emails are then only printed and never reach the provider).
    Failed messages don't count; queued and sending ones do.
    """
    limit = settings.EMAIL_DAILY_LIMIT
    if not limit or (settings.MESSAGING_TEST_MODE and not settings.MESSAGING_TEST_RECIPIENT):
        return None
    start_of_day, resets_at = provider_day()
    today = Message.objects.filter(channel=Channel.EMAIL, created_at__gte=start_of_day)
    waiting = today.filter(status__in=[Message.Status.QUEUED, Message.Status.SENDING]).count()
    delivered_by_provider = None
    if settings.EMAIL_BACKEND == "messaging.brevo.BrevoEmailBackend":
        from . import brevo

        try:
            delivered_by_provider = brevo.emails_sent_today(start_of_day.date())  # the real count, as Brevo sees it
        except Exception:
            delivered_by_provider = None
    if delivered_by_provider is None:
        # Brevo unreachable (or another provider): count only emails this app really handed over.
        delivered_by_provider = today.filter(status=Message.Status.SENT, via_provider=True).count()
    return Quota(limit=limit, used=delivered_by_provider + waiting, resets_at=resets_at)


def sms_quota():
    """SMS our SIM can still send today, or None when no limit applies.

    Counts SMS that really left the phone today (Helsinki time) plus those still queued.
    """
    limit = settings.SMS_DAILY_LIMIT
    if not limit or (settings.SMS_TEST_MODE and not settings.MESSAGING_TEST_PHONE):
        return None
    from datetime import timedelta

    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    today = Message.objects.filter(channel=Channel.SMS, created_at__gte=start)
    used = (
        today.filter(status__in=[Message.Status.QUEUED, Message.Status.SENDING]).count()
        + today.filter(status=Message.Status.SENT, via_provider=True).count()
    )
    return Quota(limit=limit, used=used, resets_at=start + timedelta(days=1))


def sms_sent_today():
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return Message.objects.filter(channel=Channel.SMS, created_at__gte=start, status=Message.Status.SENT, via_provider=True).count()


def quota_for(channel):
    return sms_quota() if channel == Channel.SMS else email_quota()


class DailyLimitReached(Exception):
    def __init__(self, quota, needed, word="emails"):
        self.quota = quota
        self.needed = needed
        super().__init__(
            f"This send needs {needed} {word} but only {quota.remaining} of today's {quota.limit} are left."
        )


# --- Sending -------------------------------------------------------------------------


class DuplicateSend(Exception):
    def __init__(self, campaign):
        self.campaign = campaign


def create_campaign(user, selection, content, idempotency_key, template=None, channel=Channel.EMAIL):
    """Create a campaign and one queued message per sendable client, then queue the send.

    Recipients are resolved again here, inside the transaction, through
    visible_clients(); opted-out clients and clients without an address for
    this channel (email, or phone for SMS) are skipped and counted.
    """
    existing = Campaign.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        raise DuplicateSend(existing)

    summary = summarize(recipients_queryset(user, selection), channel)
    quota = quota_for(channel)
    if quota and len(summary.sendable) > quota.remaining:
        raise DailyLimitReached(quota, len(summary.sendable), "SMS" if channel == Channel.SMS else "emails")
    try:
        with transaction.atomic():
            campaign = Campaign.objects.create(
                sender=user,
                template=template,
                channel=channel,
                subject_fi=content.get("subject_fi", ""),
                body_fi=content.get("body_fi", ""),
                subject_en=content.get("subject_en", ""),
                body_en=content.get("body_en", ""),
                due_date=content.get("due_date", ""),
                recipient_count=len(summary.sendable),
                skipped_opted_out=summary.opted_out,
                skipped_no_address=summary.no_address,
                test_mode=settings.SMS_TEST_MODE if channel == Channel.SMS else settings.MESSAGING_TEST_MODE,
                idempotency_key=idempotency_key,
            )
            messages = []
            for client in summary.sendable:
                subject, body = render_for(client, content, channel)
                messages.append(
                    Message(
                        campaign=campaign,
                        client=client,
                        channel=channel,
                        language=client.language,
                        to_address=address_of(client, channel),
                        subject=subject,
                        body=body,
                        sms_parts=sms.segments(body) if channel == Channel.SMS else 0,
                    )
                )
            Message.objects.bulk_create(messages)

            from .tasks import send_campaign

            transaction.on_commit(lambda: send_campaign.delay(campaign.pk))
    except IntegrityError:
        # Two requests with the same key raced; the other one won.
        raise DuplicateSend(Campaign.objects.get(idempotency_key=idempotency_key))
    return campaign


# --- Retry and cancel ---------------------------------------------------------------------


def retry_messages(messages):
    """Queue failed or stuck messages again and start sending. Returns how many were queued."""
    ids = [m.pk for m in messages if m.can_retry and not m.client.opted_out]
    if not ids:
        return 0
    Message.objects.filter(pk__in=ids).update(status=Message.Status.QUEUED, error="", created_at=timezone.now())
    from .tasks import send_campaign

    for campaign_id in set(Message.objects.filter(pk__in=ids).values_list("campaign_id", flat=True)):
        Campaign.objects.filter(pk=campaign_id).update(status=Campaign.Status.QUEUED)
        transaction.on_commit(lambda cid=campaign_id: send_campaign.delay(cid))
    return len(ids)


def cancel_messages(messages):
    """Stop messages that are stuck waiting. Returns how many were cancelled."""
    ids = [m.pk for m in messages if m.can_cancel]
    Message.objects.filter(pk__in=ids).update(status=Message.Status.CANCELLED, error="Cancelled by user")
    return len(ids)


# --- SMS delivery status --------------------------------------------------------------------


def refresh_sms_status(messages, max_checks=30):
    """Ask the SMS provider what happened to recent SMS that are not finished yet.

    Only SMS sent through a backend with a ``status`` method (SMS Gate) in the last
    3 days are checked, at most ``max_checks`` per call and each at most once a minute.
    A provider error never breaks the page; the SMS keeps its last known state.
    """
    from datetime import timedelta

    from . import sms

    backend = sms.get_backend()
    if not hasattr(backend, "status"):
        return 0
    now = timezone.now()
    todo = [
        m for m in messages
        if m.channel == Channel.SMS and m.status == Message.Status.SENT and m.provider_message_id.startswith("smsgate:")
        and m.delivery_state not in Message.FINAL_DELIVERY_STATES
        and m.created_at > now - timedelta(days=3)
        and (not m.delivery_checked_at or now - m.delivery_checked_at > timedelta(seconds=60))
    ][:max_checks]
    checked = 0
    for m in todo:
        try:
            state, error = backend.status(m.provider_message_id)
        except Exception:
            continue
        m.delivery_state, m.delivery_checked_at = state, now
        fields = ["delivery_state", "delivery_checked_at"]
        if state == "Failed":
            m.status, m.error = Message.Status.FAILED, (error or "The phone could not send this SMS.")[:500]
            fields += ["status", "error"]
        Message.objects.filter(pk=m.pk).update(**{f: getattr(m, f) for f in fields})
        checked += 1
    return checked
