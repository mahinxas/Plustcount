from unittest import mock

from django.core import mail
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.tests.factories import make_client, make_user
from messaging import brevo, services
from messaging.models import Campaign, Message

BREVO = {
    "BREVO_API_KEY": "test-key",
    "BREVO_API_URL": "https://api.brevo.test/v3",
    "EMAIL_BACKEND": "messaging.brevo.BrevoEmailBackend",
    "DEFAULT_FROM_EMAIL": "Tilitoimisto <viestit@firm.test>",
    "MESSAGING_TEST_MODE": False,
}
CONTENT = {"subject_fi": "Kuitit", "body_fi": "Hei {name}", "subject_en": "Receipts", "body_en": "Hi {name}", "due_date": ""}


def fake_response(status, payload):
    response = mock.Mock(status_code=status, text=str(payload))
    response.json.return_value = payload
    return response


@override_settings(**BREVO)
class BrevoBackendTests(TestCase):
    @mock.patch("requests.Session.post", return_value=fake_response(201, {"messageId": "<abc@brevo>"}))
    def test_sends_through_api(self, post):
        email = EmailMessage("Kuitit", "Hei!", to=["Asiakas Oy <asiakas@client.test>"],
                             headers={"X-Client-Message-Id": "42"})
        self.assertEqual(email.send(), 1)
        self.assertEqual(email.provider_message_id, "<abc@brevo>")
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertEqual(url, "https://api.brevo.test/v3/smtp/email")
        self.assertEqual(payload["sender"], {"email": "viestit@firm.test", "name": "Tilitoimisto"})
        self.assertEqual(payload["to"], [{"email": "asiakas@client.test", "name": "Asiakas Oy"}])
        self.assertEqual((payload["subject"], payload["textContent"]), ("Kuitit", "Hei!"))
        self.assertEqual(payload["headers"], {"X-Mailin-custom": "message:42"})

    def test_api_key_sent_as_header(self):
        backend = brevo.BrevoEmailBackend()
        backend.open()
        self.assertEqual(backend.session.headers["api-key"], "test-key")
        backend.close()

    @mock.patch("requests.Session.post", return_value=fake_response(401, {"code": "unauthorized", "message": "Key not found"}))
    def test_bad_key_gives_clear_error(self, post):
        with self.assertRaisesMessage(brevo.BrevoError, "Brevo rejected the API key"):
            EmailMessage("S", "B", to=["a@b.test"]).send()

    @mock.patch("requests.Session.post", return_value=fake_response(401, {
        "code": "unauthorized",
        "message": "We have detected you are using an unrecognised IP address 91.152.53.98. If you performed this "
                   "action make sure to add the new IP address in this link: https://app.brevo.com/security/authorised_ips",
    }))
    def test_blocked_ip_is_explained(self, post):
        with self.assertRaisesMessage(brevo.BrevoError, "Brevo blocked the request from IP address 91.152.53.98"):
            EmailMessage("S", "B", to=["a@b.test"]).send()

    @mock.patch("requests.Session.post", return_value=fake_response(402, {"message": "Not enough credits"}))
    def test_campaign_marks_messages_failed_when_quota_used_up(self, post):
        anna = make_user()
        make_client(owner=anna)
        with override_settings(EMAIL_DAILY_LIMIT=0):
            with self.captureOnCommitCallbacks(execute=True):
                services.create_campaign(anna, services.encode_filter({}), CONTENT, "q1")
        message = Message.objects.get()
        self.assertEqual(message.status, "failed")
        self.assertIn("daily limit or credits", message.error)

    @mock.patch("requests.Session.post", side_effect=__import__("requests").ConnectionError("down"))
    def test_network_error(self, post):
        with self.assertRaisesMessage(brevo.BrevoError, "Could not reach Brevo"):
            EmailMessage("S", "B", to=["a@b.test"]).send()

    @mock.patch("requests.Session.post", return_value=fake_response(201, {"messageId": "<id-1@brevo>"}))
    def test_campaign_stores_brevo_message_id(self, post):
        anna = make_user()
        make_client(owner=anna)
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(anna, services.encode_filter({}), CONTENT, "q2")
        self.assertEqual(Message.objects.get().provider_message_id, "<id-1@brevo>")


@override_settings(MESSAGING_TEST_MODE=False, EMAIL_DAILY_LIMIT=3,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class DailyLimitTests(TestCase):
    def setUp(self):
        self.anna = make_user()
        self.clients = [make_client(owner=self.anna) for _ in range(4)]

    def test_send_over_limit_is_stopped_before_anything_is_queued(self):
        with self.assertRaises(services.DailyLimitReached):
            services.create_campaign(self.anna, services.encode_filter({}), CONTENT, "big")
        self.assertEqual(Campaign.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_queued_emails_count_towards_limit(self):
        # Not yet sent (still queued): they will reach the provider, so they already count.
        services.create_campaign(self.anna, services.encode_ids([self.clients[0].pk, self.clients[1].pk]), CONTENT, "a")
        self.assertEqual(services.email_quota().remaining, 1)

    def test_only_emails_really_sent_by_provider_count(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(self.anna, services.encode_ids([self.clients[0].pk, self.clients[1].pk]), CONTENT, "a")
        self.assertEqual(services.email_quota().remaining, 3)  # locmem: nothing reached a provider
        Message.objects.filter(pk=Message.objects.first().pk).update(via_provider=True)
        self.assertEqual(services.email_quota().remaining, 2)

    @override_settings(EMAIL_BACKEND="messaging.brevo.BrevoEmailBackend", BREVO_API_KEY="k")
    @mock.patch("messaging.brevo.emails_sent_today", return_value=120)
    def test_uses_brevo_count_when_available(self, _):
        from django.test.utils import override_settings as o
        with o(EMAIL_DAILY_LIMIT=300):
            self.assertEqual(services.email_quota().used, 120)

    def test_failed_messages_do_not_count(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(self.anna, services.encode_ids([self.clients[0].pk]), CONTENT, "b")
        Message.objects.update(status="failed")
        self.assertEqual(services.email_quota().remaining, 3)

    def test_compose_shows_limit_error(self):
        self.client.force_login(self.anna)
        response = self.client.post(reverse("messaging:compose"), {
            "recipients": services.encode_filter({}), "idempotency_key": "k", "step": "confirm", **CONTENT,
        })
        self.assertTemplateUsed(response, "messaging/compose.html")
        self.assertContains(response, "of today&#x27;s 3 emails are left")

    @override_settings(MESSAGING_TEST_MODE=True, MESSAGING_TEST_RECIPIENT="")
    def test_no_limit_when_emails_are_only_printed(self):
        self.assertIsNone(services.email_quota())


class SettingsTests(TestCase):
    def test_brevo_key_selects_api_backend(self):
        import importlib
        import os

        from config import settings as project_settings

        with mock.patch.dict(os.environ, {"BREVO_API_KEY": "k", "DJANGO_DEBUG": "1"}):
            os.environ.pop("EMAIL_BACKEND", None)
            reloaded = importlib.reload(project_settings)
            self.assertEqual(reloaded.EMAIL_BACKEND, "messaging.brevo.BrevoEmailBackend")
        importlib.reload(project_settings)
