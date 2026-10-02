from django.test import TestCase
from django.urls import reverse

from .factories import PASSWORD, make_admin, make_user


class AuthTests(TestCase):
    def test_pages_require_login(self):
        for url in [reverse("dashboard"), reverse("clients:list"), reverse("messaging:log"), reverse("team")]:
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_login_with_email(self):
        user = make_user()
        response = self.client.post(reverse("login"), {"username": user.email, "password": PASSWORD})
        self.assertRedirects(response, reverse("dashboard"))

    def test_deactivated_user_cannot_log_in(self):
        user = make_user(is_active=False)
        response = self.client.post(reverse("login"), {"username": user.email, "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivation_ends_existing_session(self):
        user = make_user()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        user.is_active = False
        user.save()
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_member_cannot_open_team_pages(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("team")).status_code, 403)
        self.assertEqual(self.client.get(reverse("team_create")).status_code, 403)

    def test_admin_creates_member(self):
        self.client.force_login(make_admin())
        response = self.client.post(reverse("team_create"), {
            "first_name": "Aino", "last_name": "Virtanen", "email": "Aino@Firm.test",
            "role": "member", "is_active": "on", "password": "Kirjanpito-2026!",
        })
        self.assertRedirects(response, reverse("team"))
        from accounts.models import User
        aino = User.objects.get(email="aino@firm.test")
        self.assertTrue(aino.check_password("Kirjanpito-2026!"))

    def test_admin_cannot_deactivate_self(self):
        admin = make_admin()
        self.client.force_login(admin)
        response = self.client.post(reverse("team_edit", args=[admin.pk]), {
            "first_name": admin.first_name, "email": admin.email, "role": "admin",
        })
        self.assertEqual(response.status_code, 200)
        admin.refresh_from_db()
        self.assertTrue(admin.is_active)
