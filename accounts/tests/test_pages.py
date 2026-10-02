from django.test import TestCase
from django.urls import reverse

from messaging.models import Campaign, MessageTemplate

from .factories import make_admin, make_client, make_user


class PagesRenderTests(TestCase):
    """Every main page renders for both roles (catches template errors)."""

    def test_pages(self):
        admin, member = make_admin(), make_user()
        client = make_client(owner=member)
        template = MessageTemplate.objects.create(title="T", subject_fi="S", body_fi="B")
        campaign = Campaign.objects.create(sender=member, idempotency_key="x", subject_fi="Hi {due_date}", due_date="5.4.2027")
        member_urls = [
            reverse("dashboard"), reverse("clients:list"), reverse("clients:list") + "?status=cannot_receive",
            reverse("clients:detail", args=[client.pk]), reverse("clients:detail", args=[client.pk]) + "?tab=history",
            reverse("clients:edit", args=[client.pk]), reverse("messaging:log"), reverse("messaging:log") + "?status=pending&days=7",
            reverse("messaging:templates"), reverse("messaging:campaign_detail", args=[campaign.pk]),
            reverse("messaging:compose") + f"?client={client.pk}",
        ]
        admin_urls = member_urls + [
            reverse("clients:list") + "?owner=none", reverse("clients:create"), reverse("clients:import_upload"),
            reverse("team"), reverse("team_create"), reverse("team_edit", args=[member.pk]),
            reverse("messaging:template_create"), reverse("messaging:template_edit", args=[template.pk]),
        ]
        for user, urls in ((member, member_urls), (admin, admin_urls)):
            self.client.force_login(user)
            for url in urls:
                with self.subTest(user=user.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(reverse("dashboard")), "Hi 5.4.2027")
