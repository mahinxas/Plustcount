"""Update the delivery state of recent SMS from the SMS provider. Safe to run from cron every few minutes."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from messaging.models import Channel, Message
from messaging.services import refresh_sms_status


class Command(BaseCommand):
    help = "Ask the SMS provider for the delivery state of SMS sent in the last 3 days."

    def handle(self, *args, **options):
        recent = Message.objects.filter(channel=Channel.SMS, status=Message.Status.SENT,
                                        created_at__gte=timezone.now() - timedelta(days=3))
        checked = refresh_sms_status(list(recent), max_checks=500)
        self.stdout.write(self.style.SUCCESS(f"Checked {checked} SMS."))
