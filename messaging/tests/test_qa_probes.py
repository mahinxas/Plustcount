"""SQA probes: each test states the behaviour a correct app must have."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import PASSWORD, make_admin, make_client, make_user
from messaging.models import Campaign, Message

LIVE = {"MESSAGING_TEST_MODE": False, "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


def _campaign(sender):
    return Campaign.objects.create(sender=sender, subject_en="s", body_en="b", idempotency_key=f"k{Campaign.objects.count()}")


def _msg(campaign, client, **kw):
    return Message.objects.create(campaign=campaign, client=client, language="en", to_address=client.email, body="b", **kw)


@override_settings(**LIVE)
class MessageActionProbes(TestCase):
    def setUp(self):
        self.anna = make_user()
        self.client.login(username=self.anna.email, password=PASSWORD)
        self.campaign = _campaign(self.anna)

    def test_retry_skips_client_who_opted_out_since(self):
        c = make_client(owner=self.anna, opted_out=True)
        m = _msg(self.campaign, c, status="failed")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("messaging:message_action"), {"action": "retry", "message_ids": [m.pk]})
        m.refresh_from_db()
        self.assertNotEqual(m.status, "sent", "opted-out client was messaged on retry")

    def test_cancel_without_selection_does_not_touch_everything(self):
        c = make_client(owner=self.anna)
        m = _msg(self.campaign, c, status="queued")
        Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - timedelta(minutes=10))
        self.client.post(reverse("messaging:message_action"), {"action": "cancel"})
        m.refresh_from_db()
        self.assertEqual(m.status, "queued", "empty selection cancelled every stuck message")

    def test_next_backslash_is_not_an_external_redirect(self):
        resp = self.client.post(reverse("messaging:message_action"), {"action": "retry", "next": "/\\evil.example"})
        self.assertTrue(resp["Location"].startswith("/"))

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse("messaging:message_action")).status_code, 405)


class AccessProbes(TestCase):
    def setUp(self):
        self.anna, self.ben, self.admin = make_user(), make_user(), make_admin()
        self.theirs = make_client(owner=self.ben)

    def _login(self, u):
        self.client.login(username=u.email, password=PASSWORD)

    def test_member_cannot_read_edit_delete_others_client(self):
        self._login(self.anna)
        for url in (reverse("clients:detail", args=[self.theirs.pk]), reverse("clients:edit", args=[self.theirs.pk])):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse("clients:quick_update", args=[self.theirs.pk]), {"field": "email", "value": "x@y.fi"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("clients:delete", args=[self.theirs.pk])).status_code, 403)

    def test_member_cannot_view_others_campaign(self):
        camp = _campaign(self.ben)
        self._login(self.anna)
        self.assertEqual(self.client.get(reverse("messaging:campaign_detail", args=[camp.pk])).status_code, 404)

    def test_member_cannot_use_admin_pages(self):
        self._login(self.anna)
        for name in ("team", "team_create", "clients:create", "clients:import_upload", "messaging:template_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_member_owner_param_cannot_widen_filter(self):
        self._login(self.anna)
        r = self.client.get(reverse("clients:list"), {"owner": self.ben.pk})
        self.assertEqual(r.context["total"], 0)

    def test_anonymous_redirected_to_login(self):
        for name in ("dashboard", "clients:list", "messaging:log", "messaging:compose"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/login/", r["Location"])

    def test_deactivated_user_session_is_dead(self):
        self._login(self.anna)
        self.anna.is_active = False
        self.anna.save()
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_xss_in_client_name_is_escaped(self):
        make_client(owner=self.anna, name="<script>alert(1)</script>")
        self._login(self.anna)
        body = self.client.get(reverse("clients:list")).content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)


class InputProbes(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.login(username=self.admin.email, password=PASSWORD)

    def test_list_survives_garbage_params(self):
        for qs in ("page=abc", "page=-1", "page=999999", "owner=abc", "profession=%00", "q=%27%20OR%201%3D1--", "status=zzz"):
            self.assertEqual(self.client.get(reverse("clients:list") + "?" + qs).status_code, 200, qs)

    def test_compose_survives_garbage_recipients(self):
        for rec in ("ids:", "ids:abc", "ids:99999999999999999999", "filter:%%%", "bogus", "ids:1,,2"):
            r = self.client.post(reverse("messaging:compose"), {"recipients": rec, "step": "confirm"})
            self.assertIn(r.status_code, (200, 302), rec)

    def test_bulk_assign_garbage(self):
        r = self.client.post(reverse("clients:bulk_assign"), {"client_ids": ["x", "1"], "assign_to": "99999"})
        self.assertEqual(r.status_code, 404)

    def test_team_admin_cannot_demote_self(self):
        r = self.client.post(reverse("team_edit", args=[self.admin.pk]),
                             {"email": self.admin.email, "first_name": "A", "last_name": "B", "role": "member", "is_active": "on"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_admin)


class LoginThrottleProbes(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_locked_after_repeated_failures_even_with_right_password(self):
        u = make_user()
        for _ in range(5):
            self.client.post(reverse("login"), {"username": u.email, "password": "wrong"})
        r = self.client.post(reverse("login"), {"username": u.email, "password": PASSWORD})
        self.assertEqual(r.status_code, 429)

    def test_success_resets_counter(self):
        u = make_user()
        for _ in range(4):
            self.client.post(reverse("login"), {"username": u.email, "password": "wrong"})
        self.assertEqual(self.client.post(reverse("login"), {"username": u.email, "password": PASSWORD}).status_code, 302)
