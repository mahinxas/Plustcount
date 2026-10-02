import logging
import time

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import sms
from .models import Campaign, Channel, Message
from .sender import open_connection, send_email, send_sms

logger = logging.getLogger(__name__)


@shared_task
def send_campaign(campaign_id):
    """Send every queued message of a campaign, one by one, in the background.

    Each message is claimed (queued -> sending) before it is sent, so a task
    that runs twice never sends the same message twice. A failure marks only
    that message as failed; the rest continue.
    """
    campaign = Campaign.objects.get(pk=campaign_id)
    Campaign.objects.filter(pk=campaign_id).update(status=Campaign.Status.SENDING)
    is_sms = campaign.channel == Channel.SMS
    provider = "SMS provider" if is_sms else "email provider"
    try:
        connection = sms.get_backend() if is_sms else open_connection()
        if not is_sms:
            connection.open()
    except Exception as exc:
        logger.error("Could not connect to the %s for campaign %s: %s", provider, campaign_id, exc)
        Message.objects.filter(campaign_id=campaign_id, status=Message.Status.QUEUED).update(
            status=Message.Status.FAILED, error=f"Could not connect to the {provider}: {exc}"[:500]
        )
        Campaign.objects.filter(pk=campaign_id).update(status=Campaign.Status.DONE)
        return
    if is_sms:
        reached_provider = connection.__class__.__name__ not in ("ConsoleBackend", "LocmemBackend")
        test_address = settings.MESSAGING_TEST_PHONE
    else:
        reached_provider = connection.__class__.__name__ == "BrevoEmailBackend"
        test_address = settings.MESSAGING_TEST_RECIPIENT
    delay = getattr(connection, "delay_seconds", 0) if is_sms else 0
    first = True
    try:
        for message_id in Message.objects.filter(campaign_id=campaign_id, status=Message.Status.QUEUED).values_list(
            "pk", flat=True
        ):
            claimed = Message.objects.filter(pk=message_id, status=Message.Status.QUEUED).update(
                status=Message.Status.SENDING
            )
            if not claimed:
                continue
            message = Message.objects.select_related("client").get(pk=message_id)
            if message.client.opted_out:  # opted out after this was queued
                Message.objects.filter(pk=message_id).update(status=Message.Status.CANCELLED, error="Client opted out")
                continue
            if delay and not first:
                time.sleep(delay)  # space out SMS so the carrier doesn't block the SIM
            first = False
            try:
                if is_sms:
                    provider_id = send_sms(message, backend=connection)
                else:
                    provider_id = send_email(message, connection=connection)
            except Exception as exc:  # any provider/network error fails just this message
                logger.warning("Message %s failed: %s", message_id, exc)
                Message.objects.filter(pk=message_id).update(status=Message.Status.FAILED, error=str(exc)[:500])
            else:
                Message.objects.filter(pk=message_id).update(
                    status=Message.Status.SENT, sent_at=timezone.now(), provider_message_id=provider_id or "",
                    via_provider=reached_provider,
                    delivered_to=(
                        "" if not reached_provider and campaign.test_mode
                        else message.to_address if not campaign.test_mode or message.to_address.lower() in settings.MESSAGING_TEST_ALLOWED
                        else test_address
                    ),
                )
    finally:
        if not is_sms:
            connection.close()
        Campaign.objects.filter(pk=campaign_id).update(status=Campaign.Status.DONE)
