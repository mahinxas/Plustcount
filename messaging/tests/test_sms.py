from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.tests.factories import make_admin, make_client, make_user
from messaging import services, sms
from messaging.models import Campaign, Message, MessageTemplate

CONTENT = {"body_fi": "Hei {name}, kuitit {due_date} mennessä.", "body_en": "Hi {name}, receipts by {due_date}.",
           "subject_fi": "", "subject_en": "", "due_date": "5.4.2027"}
LOCMEM = {"SMS_BACKEND": "messaging.sms.LocmemBackend"}


class LengthTests(TestCase):
    def test_finnish_letters_fit_standard_sms(self):
        self.assertEqual(sms.length_info("Hyvää päivää, Åsa!"), (18, 1, False))

    def test_parts(self):
        self.assertEqual(sms.segments("a" * 160), 1)
        self.assertEqual(sms.segments("a" * 161), 2)
        self.assertEqual(sms.segments("a" * 306), 2)
        self.assertEqual(sms.segments("a" * 307), 3)

    def test_euro_sign_counts_double(self):
        self.assertEqual(sms.length_info("€" * 80), (160, 1, False))

    def test_emoji_switches_to_unicode(self):
        count, parts, unicode = sms.length_info("Kiitos 🙂" + "a" * 70)
        self.assertTrue(unicode)
        self.assertEqual(parts, 2)


class BackendSafetyTests(TestCase):
    @override_settings(MESSAGING_TEST_MODE=True, SMS_TEST_MODE=True, MESSAGING_TEST_PHONE="", SMS_BACKEND="some.real.ProviderBackend")
    def test_test_mode_never_uses_a_real_provider(self):
        self.assertIsInstance(sms.get_backend(), sms.ConsoleBackend)

    @override_settings(MESSAGING_TEST_MODE=False, SMS_BACKEND="messaging.sms.ConsoleBackend")
    def test_console_backend_only_logs(self):
        with self.assertLogs("messaging.sms", level="INFO") as logs:
            message_id = sms.get_backend().send("+358401234567", "Hei!")
        self.assertTrue(message_id.startswith("console-"))
        self.assertIn("not sent", logs.output[0])


@override_settings(**LOCMEM)
class SmsCampaignTests(TestCase):
    def setUp(self):
        sms.outbox.clear()
        self.anna = make_user()

    def test_sms_goes_to_phone_and_skips_clients_without_phone(self):
        fi = make_client(owner=self.anna, name="Mäkinen Oy", phone="+358401111111", language="fi")
        en = make_client(owner=self.anna, name="Nordic Ltd", phone="+358402222222", language="en")
        make_client(owner=self.anna, phone="")
        make_client(owner=self.anna, phone="+358403333333", opted_out=True)
        with self.captureOnCommitCallbacks(execute=True):
            campaign = services.create_campaign(self.anna, services.encode_filter({}), CONTENT, "s1", channel="sms")
        self.assertEqual((campaign.channel, campaign.recipient_count, campaign.skipped_no_address, campaign.skipped_opted_out),
                         ("sms", 2, 1, 1))
        by_to = {m["to"]: m["text"] for m in sms.outbox}
        self.assertEqual(by_to[fi.phone], "Hei Mäkinen Oy, kuitit 5.4.2027 mennessä.")
        self.assertEqual(by_to[en.phone], "Hi Nordic Ltd, receipts by 5.4.2027.")
        self.assertEqual(Message.objects.filter(status="sent", channel="sms", sms_parts=1).count(), 2)
        self.assertEqual(campaign.display_subject, "Hi {name}, receipts by 5.4.2027.")

    def test_member_cannot_sms_other_members_clients(self):
        mine = make_client(owner=self.anna, phone="+358401111111")
        theirs = make_client(owner=make_user(), phone="+358402222222")
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(self.anna, services.encode_ids([mine.pk, theirs.pk]), CONTENT, "s2", channel="sms")
        self.assertEqual([m["to"] for m in sms.outbox], [mine.phone])


@override_settings(**LOCMEM)
class SmsComposeViewTests(TestCase):
    def setUp(self):
        sms.outbox.clear()
        self.anna = make_user()
        self.c = make_client(owner=self.anna, phone="+358401111111", language="fi")
        self.client.force_login(self.anna)

    def post(self, step, **extra):
        data = {"channel": "sms", "recipients": services.encode_ids([self.c.pk]), "idempotency_key": "k",
                "step": step, "body_fi": CONTENT["body_fi"], "due_date": "2027-04-05", **extra}
        return self.client.post(reverse("messaging:compose"), data)

    def test_no_subject_needed_and_confirm_shows_sms(self):
        response = self.post("confirm")
        self.assertTemplateUsed(response, "messaging/confirm.html")
        self.assertContains(response, "SMS to 1 client")
        self.assertContains(response, "About 1 SMS in total")

    def test_send_creates_sms_campaign(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("send")
        campaign = Campaign.objects.get()
        self.assertRedirects(response, reverse("messaging:campaign_detail", args=[campaign.pk]))
        self.assertEqual(len(sms.outbox), 1)

    def test_too_long_sms_rejected(self):
        response = self.post("confirm", body_fi="a" * 500)
        self.assertIn("body_fi", response.context["form"].errors)

    def test_compose_page_offers_only_sms_templates(self):
        MessageTemplate.objects.create(title="Email one", subject_fi="S", body_fi="B")
        MessageTemplate.objects.create(title="SMS one", channel="sms", body_fi="B")
        response = self.client.get(reverse("messaging:compose") + f"?client={self.c.pk}&channel=sms")
        titles = [t.title for t in response.context["form"].fields["template"].queryset]
        self.assertEqual(titles, ["SMS one"])


class SmsTemplateFormTests(TestCase):
    def test_sms_template_needs_no_subject(self):
        self.client.force_login(make_admin())
        response = self.client.post(reverse("messaging:template_create"), {
            "title": "SMS", "channel": "sms", "subject_fi": "ignored", "body_fi": "Hei {name}!",
        })
        self.assertRedirects(response, reverse("messaging:templates") + "?channel=sms")
        template = MessageTemplate.objects.get()
        self.assertEqual((template.channel, template.subject_fi), ("sms", ""))


class GammuBackendTests(TestCase):
    def run_with(self, returncode=0, stdout="Written message with ID /var/spool/gammu/outbox/OUTC1.txt", text="Hei!"):
        from unittest import mock
        done = mock.Mock(returncode=returncode, stdout=stdout, stderr="")
        with override_settings(GAMMU_INJECT_COMMAND="gammu-smsd-inject", GAMMU_CONFIG="/etc/gammu-smsdrc"):
            with mock.patch("subprocess.run", return_value=done) as run:
                result = sms.GammuBackend().send("+358401234567", text)
        return result, run.call_args.args[0]

    def test_queues_sms_without_shell(self):
        result, cmd = self.run_with()
        self.assertEqual(result, "gammu:OUTC1.txt")
        self.assertEqual(cmd, ["gammu-smsd-inject", "-c", "/etc/gammu-smsdrc", "TEXT", "+358401234567", "-text", "Hei!"])

    def test_long_and_unicode_messages(self):
        text = "Kiitos 🙂 " + "a" * 100
        _, cmd = self.run_with(text=text)
        self.assertIn("-unicode", cmd)
        self.assertEqual(cmd[cmd.index("-len") + 1], str(len(text)))

    def test_text_with_shell_characters_is_one_argument(self):
        _, cmd = self.run_with(text="Hei; rm -rf / $(whoami)")
        self.assertEqual(cmd[-1], "Hei; rm -rf / $(whoami)")

    def test_failure_raises(self):
        with self.assertRaises(sms.GammuError):
            self.run_with(returncode=2, stdout="Error opening device")

    @override_settings(MESSAGING_TEST_MODE=True, SMS_TEST_MODE=True, MESSAGING_TEST_PHONE="", SMS_BACKEND="messaging.sms.GammuBackend")
    def test_test_mode_never_touches_the_modem(self):
        self.assertIsInstance(sms.get_backend(), sms.ConsoleBackend)


@override_settings(KDECONNECT_COMMAND="kdeconnect-cli", KDECONNECT_DEVICE="abc123")
class KdeConnectBackendTests(TestCase):
    def run_with(self, returncode=0, output=""):
        from unittest import mock
        done = mock.Mock(returncode=returncode, stdout=output, stderr="")
        with mock.patch("subprocess.run", return_value=done) as run:
            result = sms.KdeConnectBackend().send("+358401234567", "Hei $(whoami)!")
        return result, run.call_args.args[0]

    def test_sends_through_phone_without_shell(self):
        result, cmd = self.run_with()
        self.assertTrue(result.startswith("kdeconnect-"))
        self.assertEqual(cmd, ["kdeconnect-cli", "--device", "abc123", "--send-sms", "Hei $(whoami)!",
                               "--destination", "+358401234567"])

    def test_unreachable_phone_fails(self):
        with self.assertRaises(sms.KdeConnectError):
            self.run_with(output="error: Device not reachable")

    @override_settings(KDECONNECT_DEVICE="")
    def test_missing_device_id(self):
        with self.assertRaisesMessage(sms.KdeConnectError, "KDECONNECT_DEVICE is not set"):
            sms.KdeConnectBackend().send("+358401234567", "Hei")


@override_settings(MESSAGING_TEST_MODE=True, SMS_TEST_MODE=True, MESSAGING_TEST_PHONE="+358409999999", MESSAGING_TEST_ALLOWED={"+358401111111"},
                   SMS_BACKEND="messaging.sms.LocmemBackend")
class TestPhoneTests(TestCase):
    def test_sms_redirected_to_test_phone_except_allowed(self):
        sms.outbox.clear()
        anna = make_user()
        make_client(owner=anna, phone="+358401111111")
        make_client(owner=anna, phone="+358402222222")
        with self.captureOnCommitCallbacks(execute=True):
            services.create_campaign(anna, services.encode_filter({}), CONTENT, "tp", channel="sms")
        self.assertEqual(sorted(m["to"] for m in sms.outbox), ["+358401111111", "+358409999999"])


@override_settings(SMSGATE_URL="https://sms.test/3rdparty/v1/messages", SMSGATE_USERNAME="u", SMSGATE_PASSWORD="p")
class SmsGateBackendTests(TestCase):
    def test_posts_message(self):
        from unittest import mock
        resp = mock.Mock(status_code=202, text="")
        resp.json.return_value = {"id": "abc", "state": "Pending"}
        with mock.patch("requests.post", return_value=resp) as post:
            self.assertEqual(sms.SmsGateBackend().send("+358401234567", "Hei"), "smsgate:abc")
        self.assertEqual(post.call_args.kwargs["json"], {"textMessage": {"text": "Hei"}, "phoneNumbers": ["+358401234567"]})
        self.assertEqual(post.call_args.kwargs["auth"], ("u", "p"))

    def test_bad_password(self):
        from unittest import mock
        with mock.patch("requests.post", return_value=mock.Mock(status_code=401, text="")):
            with self.assertRaisesMessage(sms.SmsGateError, "username or password"):
                sms.SmsGateBackend().send("+358401234567", "Hei")


@override_settings(MESSAGING_TEST_MODE=True, SMS_TEST_MODE=False, MESSAGING_TEST_PHONE="+358409999999",
                   SMS_BACKEND="messaging.sms.LocmemBackend")
class LiveSmsTests(TestCase):
    def test_live_sms_goes_to_real_number_while_email_stays_in_test(self):
        sms.outbox.clear()
        anna = make_user()
        make_client(owner=anna, phone="+358402222222")
        with self.captureOnCommitCallbacks(execute=True):
            campaign = services.create_campaign(anna, services.encode_filter({}), CONTENT, "live", channel="sms")
        self.assertEqual([m["to"] for m in sms.outbox], ["+358402222222"])
        self.assertFalse(sms.outbox[0]["text"].startswith("[TEST]"))
        self.assertFalse(campaign.test_mode)


@override_settings(MESSAGING_TEST_MODE=False, SMS_TEST_MODE=False, SMS_DAILY_LIMIT=1, SMS_BACKEND="messaging.sms.LocmemBackend")
class SmsLimitTests(TestCase):
    def test_sms_over_daily_limit_stopped(self):
        anna = make_user()
        make_client(owner=anna, phone="+358401111111")
        make_client(owner=anna, phone="+358402222222")
        with self.assertRaises(services.DailyLimitReached):
            services.create_campaign(anna, services.encode_filter({}), CONTENT, "lim", channel="sms")

    @override_settings(SMS_DAILY_LIMIT=0)
    def test_dashboard_shows_sms_bar(self):
        anna = make_user()
        self.client.force_login(anna)
        self.assertContains(self.client.get(reverse("dashboard")), "SMS today")


@override_settings(MESSAGING_TEST_MODE=False, SMS_TEST_MODE=False, SMS_DAILY_LIMIT=0, SMS_BACKEND="messaging.sms.LocmemBackend",
                   SMS_SEND_DELAY_SECONDS=0)
class RetryCancelTests(TestCase):
    def setUp(self):
        sms.outbox.clear()
        self.anna = make_user()
        make_client(owner=self.anna, phone="+358401111111")
        self.campaign = services.create_campaign(self.anna, services.encode_filter({}), CONTENT, "rc", channel="sms")
        # simulate an interrupted send: queued long ago, never processed
        from datetime import timedelta
        from django.utils import timezone
        Message.objects.update(created_at=timezone.now() - timedelta(minutes=10))
        self.client.force_login(self.anna)

    def test_retry_stuck_message_sends_it(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("messaging:message_action"), {"action": "retry", "campaign": self.campaign.pk})
        self.assertEqual(Message.objects.get().status, "sent")
        self.assertEqual(len(sms.outbox), 1)

    def test_cancel_stuck_message(self):
        self.client.post(reverse("messaging:message_action"), {"action": "cancel", "campaign": self.campaign.pk})
        self.assertEqual(Message.objects.get().status, "cancelled")

    def test_other_member_cannot_retry(self):
        self.client.force_login(make_user())
        self.client.post(reverse("messaging:message_action"), {"action": "cancel", "campaign": self.campaign.pk})
        self.assertEqual(Message.objects.get().status, "queued")


@override_settings(SMS_TEST_MODE=False, SMS_BACKEND="messaging.sms.SmsGateBackend", SMSGATE_USERNAME="u", SMSGATE_PASSWORD="p",
                   SMSGATE_URL="https://sms.test/3rdparty/v1/messages")
class DeliveryStatusTests(TestCase):
    def make_msg(self):
        anna = make_user()
        c = make_client(owner=anna, phone="+358401111111")
        campaign = Campaign.objects.create(sender=anna, channel="sms", idempotency_key="d")
        return Message.objects.create(campaign=campaign, client=c, channel="sms", language="fi", to_address=c.phone,
                                      body="Hei", status="sent", provider_message_id="smsgate:abc")

    def fake(self, payload):
        from unittest import mock
        r = mock.Mock(status_code=200); r.json.return_value = payload
        return mock.patch("requests.get", return_value=r)

    def test_pending_shows_waiting_for_phone(self):
        m = self.make_msg()
        with self.fake({"state": "Pending", "recipients": [{"state": "Pending"}]}):
            services.refresh_sms_status([m])
        m.refresh_from_db()
        self.assertEqual((m.delivery_state, m.delivery_label), ("Pending", "Waiting for phone"))

    def test_failed_on_phone_marks_failed(self):
        m = self.make_msg()
        with self.fake({"state": "Failed", "recipients": [{"state": "Failed", "error": "No credit"}]}):
            services.refresh_sms_status([m])
        m.refresh_from_db()
        self.assertEqual((m.status, m.error), ("failed", "No credit"))

    def test_delivered_is_not_checked_again(self):
        m = self.make_msg()
        Message.objects.filter(pk=m.pk).update(delivery_state="Delivered")
        m.refresh_from_db()
        from unittest import mock
        with mock.patch("requests.get") as get:
            services.refresh_sms_status([m])
        get.assert_not_called()
