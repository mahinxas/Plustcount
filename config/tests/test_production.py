import re
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from accounts.tests.factories import make_admin, make_client, make_user


class HealthCheckTests(TestCase):
    def test_ok_without_login(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok", "cache": "ok"})

    def test_unavailable_when_database_is_down(self):
        with mock.patch("config.health.connection.cursor", side_effect=Exception("db down")):
            response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["database"], "down")

    def test_unavailable_when_cache_is_down(self):
        with mock.patch("config.health.cache.set", side_effect=Exception("redis down")):
            response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["cache"], "down")

    def test_post_not_allowed(self):
        self.assertEqual(self.client.post(reverse("healthz")).status_code, 405)

    def test_does_not_leak_error_details(self):
        with mock.patch("config.health.connection.cursor", side_effect=Exception("password=hunter2")):
            response = self.client.get(reverse("healthz"))
        self.assertNotIn("hunter2", response.content.decode())


class ContentSecurityPolicyTests(TestCase):
    """The CSP only works if no page needs inline scripts or inline event handlers."""

    def test_header_is_strict(self):
        response = self.client.get(reverse("login"))
        policy = response.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", policy)
        self.assertNotIn("unsafe-inline", policy.split("style-src-attr")[0])
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)

    def test_pages_have_no_inline_scripts_or_handlers(self):
        admin, member = make_admin(), make_user()
        client = make_client(owner=member)
        urls = [
            reverse("login"), reverse("password_reset"), reverse("dashboard"), reverse("clients:list"),
            reverse("clients:detail", args=[client.pk]), reverse("clients:edit", args=[client.pk]),
            reverse("messaging:log"), reverse("messaging:templates"), reverse("messaging:template_create"),
            reverse("messaging:compose") + f"?client={client.pk}", reverse("team"),
        ]
        self.client.force_login(admin)
        for url in urls:
            html = self.client.get(url).content.decode()
            self.assertIsNone(re.search(r"<script(?![^>]*(\ssrc=|type=\"application/json\"))[^>]*>", html), f"inline <script> on {url}")
            self.assertIsNone(re.search(r"\son(click|submit|change|input|load|error)\s*=", html), f"inline handler on {url}")

    def test_destructive_actions_use_data_confirm(self):
        admin = make_admin()
        client = make_client(owner=make_user())
        self.client.force_login(admin)
        html = self.client.get(reverse("clients:detail", args=[client.pk])).content.decode()
        self.assertIn("data-confirm=", html)


class SecurityHeaderTests(TestCase):
    def test_basic_headers(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
