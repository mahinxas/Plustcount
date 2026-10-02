"""Add the firm's starter email and SMS templates (skips any that already exist). Adds no clients or users."""

from django.core.management.base import BaseCommand

from messaging.default_templates import TEMPLATES
from messaging.models import MessageTemplate


class Command(BaseCommand):
    help = "Add the starter email and SMS templates. Existing templates are left as they are."

    def handle(self, *args, **options):
        added = 0
        for data in TEMPLATES:
            _, created = MessageTemplate.objects.get_or_create(title=data["title"], channel=data["channel"], defaults=data)
            added += created
        self.stdout.write(self.style.SUCCESS(f"{added} template(s) added, {len(TEMPLATES) - added} already there."))
