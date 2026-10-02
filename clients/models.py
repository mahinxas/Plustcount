from django.conf import settings
from django.db import models
from django.db.models import Q


class Client(models.Model):
    class CompanyType(models.TextChoices):
        TOIMINIMI = "toiminimi", "Toiminimi"
        OY = "oy", "Oy"
        PERSON = "person", "Private person"
        OTHER = "other", "Other"

    class Language(models.TextChoices):
        FI = "fi", "Finnish"
        EN = "en", "English"

    class Profession(models.TextChoices):
        DELIVERY_RIDER = "delivery_rider", "Delivery rider"
        TAXI = "taxi", "Taxi"
        RESTAURANT = "restaurant", "Restaurant"
        OTHER = "other", "Other"

    name = models.CharField(max_length=200)
    business_id = models.CharField("business ID (Y-tunnus)", max_length=9, blank=True)
    company_type = models.CharField(max_length=20, choices=CompanyType.choices, default=CompanyType.OTHER)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    language = models.CharField("message language", max_length=2, choices=Language.choices, default=Language.FI)
    profession = models.CharField(max_length=20, choices=Profession.choices, default=Profession.OTHER)
    notes = models.TextField("internal notes", blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clients",
    )
    opted_out = models.BooleanField(
        "opted out of messages",
        default=False,
        help_text="Skipped automatically when sending.",
    )
    opted_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["business_id"],
                condition=~Q(business_id=""),
                name="unique_business_id_when_set",
            ),
        ]
        indexes = [
            models.Index(fields=["owner", "name"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        return self.name


class ClientAssignment(models.Model):
    """History of every ownership change: who moved which client, from whom, to whom."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="assignments")
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"{self.client}: {self.from_user or 'unassigned'} -> {self.to_user or 'unassigned'}"
