from django.conf import settings
from django.db import models

from clients.models import Client


class Channel(models.TextChoices):
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"


class MessageTemplate(models.Model):
    """A shared template with a Finnish and an English version."""

    title = models.CharField(max_length=120)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    subject_fi = models.CharField("subject (Finnish)", max_length=200, blank=True)
    body_fi = models.TextField("message (Finnish)", blank=True)
    subject_en = models.CharField("subject (English)", max_length=200, blank=True)
    body_en = models.TextField("message (English)", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        constraints = [
            # "Receipts reminder" can exist once as an email and once as an SMS.
            models.UniqueConstraint(fields=["title", "channel"], name="unique_template_title_per_channel"),
        ]

    def __str__(self):
        return self.title


class Campaign(models.Model):
    """One send action by one user: a single email or a bulk send."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        DONE = "done", "Done"

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="campaigns")
    template = models.ForeignKey(MessageTemplate, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    subject_fi = models.CharField(max_length=200, blank=True)
    body_fi = models.TextField(blank=True)
    subject_en = models.CharField(max_length=200, blank=True)
    body_en = models.TextField(blank=True)
    due_date = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    recipient_count = models.PositiveIntegerField(default=0)
    skipped_opted_out = models.PositiveIntegerField(default=0)
    skipped_no_address = models.PositiveIntegerField(default=0)
    test_mode = models.BooleanField(default=False)
    # Stops a double-clicked "Send" from creating two campaigns.
    idempotency_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_channel_display()} to {self.recipient_count} client(s)"

    @property
    def display_subject(self):
        # Show the date that was actually sent, not the {due_date} placeholder.
        # An SMS has no subject, so its first line stands in for one.
        # The app is in English, so the English version is shown when there is one.
        text = self.subject_en or self.subject_fi
        if self.channel == Channel.SMS or not text:
            text = (self.body_en or self.body_fi).strip().split("\n", 1)[0]
        return text.replace("{due_date}", self.due_date or "{due_date}")

    @property
    def is_sms(self):
        return self.channel == Channel.SMS


class Message(models.Model):
    """One message to one client. History belongs to the client, not the sender."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="messages")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="messages")
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    language = models.CharField(max_length=2, choices=Client.Language.choices)
    to_address = models.CharField(max_length=254)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    sms_parts = models.PositiveSmallIntegerField("SMS parts", default=0, help_text="How many SMS this message used (0 for email).")
    error = models.CharField(max_length=500, blank=True)
    provider_message_id = models.CharField(max_length=200, blank=True)
    # What the provider reports after accepting it (SMS Gate: Pending, Processed, Sent, Delivered, Failed).
    delivery_state = models.CharField(max_length=20, blank=True)
    delivery_checked_at = models.DateTimeField(null=True, blank=True)
    delivered_to = models.CharField(
        max_length=254, blank=True,
        help_text="Where it really went. Differs from to_address in test mode; empty if only printed or logged.",
    )
    via_provider = models.BooleanField(default=False, help_text="Handed to the real provider (not only printed or logged).")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["client", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_channel_display()} to {self.client} ({self.status})"

    STUCK_AFTER = 120  # seconds "sending" before we assume the send was interrupted

    @property
    def is_stuck(self):
        from django.utils import timezone

        if self.status == self.Status.QUEUED:
            return (timezone.now() - self.created_at).total_seconds() > self.STUCK_AFTER
        return self.status == self.Status.SENDING and (timezone.now() - self.created_at).total_seconds() > self.STUCK_AFTER

    @property
    def can_retry(self):
        return self.status == self.Status.FAILED or self.is_stuck

    @property
    def can_cancel(self):
        return self.status in (self.Status.QUEUED, self.Status.SENDING) and self.is_stuck

    FINAL_DELIVERY_STATES = {"Delivered", "Failed"}

    @property
    def delivery_label(self):
        """Plain-language delivery state for an SMS handed to the phone, or ''."""
        return {"Pending": "Waiting for phone", "Processed": "Sent", "Sent": "Sent", "Delivered": "Delivered"}.get(
            self.delivery_state, ""
        )

    @property
    def is_test_copy(self):
        """Sent in test mode: the client did not receive it."""
        return self.campaign.test_mode
