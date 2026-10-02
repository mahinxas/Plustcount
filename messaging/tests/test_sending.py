from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.tests.factories import make_admin, make_client, make_user
from messaging import personalize, services
from messaging.models import Campaign, Message, MessageTemplate

CONTENT = {
    "subject_fi": "Kuitit {due_date} mennessä",
    "body_fi": "Hei {name},\nlähetäthän maaliskuun kuitit {due_date} mennessä.",
    "subject_en": "Receipts by {due_date}",
    "body_en": "Hello {name},\nplease send your March receipts by {due_date}.",
    "due_date": "5.4.2027",
}

LIVE = {"MESSAGING_TEST_MODE": False, "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


class PersonalizeTests(TestCase):
    def test_only_known_fields_are_replaced(self):
        c = make_client(name="Virtanen Oy")
        text = personalize.render("Hei {name} {unknown} {__class__}", personalize.context_for(c))
        self.assertEqual(text, "Hei Virtanen Oy {unknown} {__class__}")

    def test_unknown_placeholders(self):
        self.assertEqual(personalize.unknown_placeholders("{name} {nmae}"), ["nmae"])


@override_settings(**LIVE)
class SendServiceTests(TestCase):
    def setUp(self):
        self.anna = make_user()
        self.ben = make_user()

    def test_language_is_picked_per_client_and_opted_out_skipped(self):
        fi = make_client(owner=self.anna, name="Mäkinen Oy", language="fi")
        en = make_client(owner=self.anna, name="Nordic Ltd", language="en")
        make_client(owner=self.anna, opted_out=True)
        make_client(owner=self.anna, email="")
        with self.captureOnCommitCallbacks(execute=True):
            campaign = services.create_campaign(
                self.anna, services.encode_filter({}), CONTENT, "key-1"
            )
        self.assertEqual((campaign.recipient_count, campaign.skipped_opted_out, campaign.skipped_no_address), (2, 1, 1))
        self.assertEqual(len(mail.outbox), 2)
        by_to = {m.to[0]: m for m in mail.outbox}
        self.assertEqual(by_to[fi.email].subject, "Kuitit 5.4.2027 mennessä")
        self.assertIn("Hei Mäkinen Oy", by_to[fi.email].body)
        self.assertNotIn("http", by_to[fi.email].body)  # no unsubscribe or other links added
        self.assertEqual(by_to[en.email].subject, "Receipts by 5.4.2027")
        self.assertNotIn("http", by_to[en.email].body)
        self.assertEqual(Message.objects.filter(status="sent").count(), 2)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "done")

    def test_member_cannot_send_to_other_members_clients(self):
        mine = make_client(owner=self.anna)
        theirs = make_client(owner=self.ben)
        with self.captureOnCommitCallbacks(execute=True):
            campaign = services.create_campaign(
                self.anna, services.encode_ids([mine.pk, theirs.pk]), CONTENT, "key-2"
            )
        self.assertEqual(campaign.recipient_count, 1)
        self.assertEqual([m.to[0] for m in mail.outbox], [mine.email])

    def test_same_key_does_not_send_twice(self):
        make_client(owner=self.anna)
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(self.anna, services.encode_filter({}), CONTENT, "same")
        with self.assertRaises(services.DuplicateSend):
            services.create_campaign(self.anna, services.encode_filter({}), CONTENT, "same")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Campaign.objects.count(), 1)

    def test_provider_failure_marks_message_failed(self):
        make_client(owner=self.anna)
        with override_settings(EMAIL_BACKEND="messaging.tests.test_sending.BrokenBackend"):
            with self.captureOnCommitCallbacks(execute=True):
                services.create_campaign(self.anna, services.encode_filter({}), CONTENT, "key-3")
        msg = Message.objects.get()
        self.assertEqual(msg.status, "failed")
        self.assertIn("provider down", msg.error)


class BrokenBackend:
    def __init__(self, *args, **kwargs):
        pass

    def open(self):
        return True

    def close(self):
        pass

    def send_messages(self, messages):
        raise ConnectionError("provider down")


class TestModeTests(TestCase):
    @override_settings(MESSAGING_TEST_MODE=True, MESSAGING_TEST_RECIPIENT="tester@firm.test",
                       EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_test_mode_redirects_to_test_address(self):
        anna = make_user()
        make_client(owner=anna, email="real@client.test")
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(anna, services.encode_filter({}), CONTENT, "t-1")
        self.assertEqual(mail.outbox[0].to, ["tester@firm.test"])
        self.assertFalse(mail.outbox[0].subject.startswith("[TEST]"))


@override_settings(**LIVE)
class ComposeViewTests(TestCase):
    def setUp(self):
        self.anna = make_user()
        self.c1 = make_client(owner=self.anna, language="fi")
        self.client.force_login(self.anna)

    def _post(self, step, **extra):
        data = {"recipients": services.encode_ids([self.c1.pk]), "idempotency_key": "abc", "step": step, **CONTENT, "due_date": "2027-04-05", **extra}
        return self.client.post(reverse("messaging:compose"), data)

    def test_confirm_step_shows_summary_without_sending(self):
        response = self._post("confirm")
        self.assertContains(response, "Email to 1 client")
        self.assertContains(response, "Hei " + self.c1.name)
        self.assertEqual(Campaign.objects.count(), 0)

    def test_send_step_creates_campaign(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post("send")
        campaign = Campaign.objects.get()
        self.assertRedirects(response, reverse("messaging:campaign_detail", args=[campaign.pk]))
        self.assertEqual(len(mail.outbox), 1)

    def test_missing_language_version_is_an_error(self):
        response = self._post("confirm", subject_fi="", body_fi="")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "messaging/compose.html")
        self.assertIn("subject_fi", response.context["form"].errors)

    def test_due_date_required_when_used(self):
        response = self._post("confirm", due_date="")
        self.assertIn("due_date", response.context["form"].errors)

    def test_other_members_campaign_is_hidden(self):
        ben = make_user()
        campaign = Campaign.objects.create(sender=ben, idempotency_key="x")
        self.assertEqual(self.client.get(reverse("messaging:campaign_detail", args=[campaign.pk])).status_code, 404)

    def test_new_owner_sees_earlier_messages(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._post("send")
        ben, admin = make_user(), make_admin()
        from clients.services import assign_clients
        assign_clients(admin, [self.c1], ben)
        self.client.force_login(ben)
        self.assertContains(self.client.get(reverse("messaging:log")), self.c1.name)
        self.client.force_login(self.anna)
        self.assertNotContains(self.client.get(reverse("messaging:log")), self.c1.name)


class TemplatePermissionTests(TestCase):
    def test_member_can_view_but_not_edit_templates(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("messaging:templates")).status_code, 200)
        self.assertEqual(self.client.get(reverse("messaging:template_create")).status_code, 403)

    def test_admin_template_rejects_unknown_fields(self):
        self.client.force_login(make_admin())
        response = self.client.post(reverse("messaging:template_create"), {
            "title": "Kuitit", "subject_fi": "Kuitit", "body_fi": "Hei {nimi}",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MessageTemplate.objects.exists())


@override_settings(**LIVE)
class DueDateTests(TestCase):
    def test_past_due_date_rejected(self):
        anna = make_user()
        c = make_client(owner=anna)
        self.client.force_login(anna)
        response = self.client.post(reverse("messaging:compose"), {
            "recipients": services.encode_ids([c.pk]), "idempotency_key": "k", "step": "confirm",
            **CONTENT, "due_date": "2020-01-01",
        })
        self.assertIn("due_date", response.context["form"].errors)


@override_settings(MESSAGING_TEST_MODE=True, MESSAGING_TEST_RECIPIENT="tester@firm.test",
                   MESSAGING_TEST_ALLOWED={"own@client.test"}, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AllowListTests(TestCase):
    def test_allowed_test_client_gets_own_email_others_redirected(self):
        anna = make_user()
        make_client(owner=anna, email="own@client.test")
        make_client(owner=anna, email="real@client.test")
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(anna, services.encode_filter({}), CONTENT, "al")
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["own@client.test", "tester@firm.test"])
