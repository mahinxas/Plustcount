from django.test import TestCase
from django.urls import reverse

from accounts.tests.factories import make_admin, make_client, make_user
from clients.access import visible_clients
from clients.models import ClientAssignment


class VisibilityTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.anna = make_user()
        self.ben = make_user()
        self.annas = make_client(owner=self.anna)
        self.bens = make_client(owner=self.ben)
        self.unassigned = make_client()

    def test_member_sees_only_own_clients(self):
        self.assertEqual(list(visible_clients(self.anna)), [self.annas])

    def test_admin_sees_all(self):
        self.assertEqual(visible_clients(self.admin).count(), 3)

    def test_member_cannot_open_or_edit_other_members_client(self):
        self.client.force_login(self.anna)
        self.assertEqual(self.client.get(reverse("clients:detail", args=[self.bens.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("clients:edit", args=[self.bens.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("clients:detail", args=[self.unassigned.pk])).status_code, 404)

    def test_member_list_hides_other_clients(self):
        self.client.force_login(self.anna)
        response = self.client.get(reverse("clients:list"))
        self.assertContains(response, self.annas.name)
        self.assertNotContains(response, self.bens.name)
        self.assertNotContains(response, self.unassigned.name)

    def test_member_owner_filter_is_ignored(self):
        self.client.force_login(self.anna)
        response = self.client.get(reverse("clients:list"), {"owner": self.ben.pk})
        self.assertNotContains(response, self.bens.name)

    def test_member_cannot_change_owner_via_edit(self):
        self.client.force_login(self.anna)
        self.client.post(reverse("clients:edit", args=[self.annas.pk]), {
            "name": "Uusi Nimi Oy", "company_type": "oy", "language": "fi", "profession": "taxi", "owner": self.ben.pk,
        })
        self.annas.refresh_from_db()
        self.assertEqual(self.annas.name, "Uusi Nimi Oy")
        self.assertEqual(self.annas.owner, self.anna)

    def test_member_cannot_create_delete_assign_or_import(self):
        self.client.force_login(self.anna)
        self.assertEqual(self.client.get(reverse("clients:create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("clients:delete", args=[self.annas.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("clients:import_upload")).status_code, 403)
        response = self.client.post(reverse("clients:bulk_assign"), {"client_ids": [self.bens.pk], "assign_to": self.anna.pk})
        self.assertEqual(response.status_code, 403)
        self.bens.refresh_from_db()
        self.assertEqual(self.bens.owner, self.ben)


class AssignmentTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.anna = make_user()
        self.ben = make_user()
        self.client.force_login(self.admin)

    def test_move_client_records_history_and_moves_access(self):
        c = make_client(owner=self.anna)
        self.client.post(reverse("clients:bulk_assign"), {"client_ids": [c.pk], "assign_to": self.ben.pk})
        c.refresh_from_db()
        self.assertEqual(c.owner, self.ben)
        self.assertFalse(visible_clients(self.anna).filter(pk=c.pk).exists())
        self.assertTrue(visible_clients(self.ben).filter(pk=c.pk).exists())
        a = ClientAssignment.objects.get(client=c)
        self.assertEqual((a.from_user, a.to_user, a.changed_by), (self.anna, self.ben, self.admin))

    def test_bulk_assign_and_unassign(self):
        clients = [make_client() for _ in range(3)]
        ids = [c.pk for c in clients]
        self.client.post(reverse("clients:bulk_assign"), {"client_ids": ids, "assign_to": self.anna.pk})
        self.assertEqual(visible_clients(self.anna).count(), 3)
        self.client.post(reverse("clients:bulk_assign"), {"client_ids": ids, "assign_to": "none"})
        self.assertEqual(visible_clients(self.anna).count(), 0)
        self.assertEqual(ClientAssignment.objects.count(), 6)

    def test_no_history_when_owner_unchanged(self):
        c = make_client(owner=self.anna)
        self.client.post(reverse("clients:bulk_assign"), {"client_ids": [c.pk], "assign_to": self.anna.pk})
        self.assertEqual(ClientAssignment.objects.count(), 0)

    def test_cannot_assign_to_deactivated_user(self):
        gone = make_user(is_active=False)
        c = make_client()
        response = self.client.post(reverse("clients:bulk_assign"), {"client_ids": [c.pk], "assign_to": gone.pk})
        self.assertEqual(response.status_code, 404)

    def test_owner_change_through_edit_form_is_recorded(self):
        c = make_client(owner=self.anna)
        self.client.post(reverse("clients:edit", args=[c.pk]), {
            "name": c.name, "company_type": "oy", "language": "fi", "profession": "taxi", "owner": self.ben.pk, "email": c.email,
        })
        c.refresh_from_db()
        self.assertEqual(c.owner, self.ben)
        self.assertEqual(ClientAssignment.objects.filter(client=c).count(), 1)

    def test_unsafe_next_url_is_ignored(self):
        c = make_client()
        response = self.client.post(reverse("clients:bulk_assign"), {
            "client_ids": [c.pk], "assign_to": self.anna.pk, "next": "https://evil.example/",
        })
        self.assertRedirects(response, reverse("clients:list"))


class QuickEditTests(TestCase):
    def setUp(self):
        self.anna = make_user()
        self.ben = make_user()
        self.mine = make_client(owner=self.anna, email="", phone="")
        self.theirs = make_client(owner=self.ben, email="")
        self.client.force_login(self.anna)
        self.back = reverse("clients:list") + "?status=cannot_receive"

    def test_add_missing_email_and_return_to_list(self):
        response = self.client.post(reverse("clients:quick_update", args=[self.mine.pk]),
                                    {"field": "email", "value": " New@Client.FI ", "next": self.back})
        self.assertRedirects(response, self.back, fetch_redirect_response=False)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.email, "new@client.fi")

    def test_add_phone_is_normalised(self):
        self.client.post(reverse("clients:quick_update", args=[self.mine.pk]), {"field": "phone", "value": "040 123 4567"})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.phone, "+358401234567")

    def test_invalid_value_saves_nothing(self):
        self.client.post(reverse("clients:quick_update", args=[self.mine.pk]), {"field": "email", "value": "not-an-email"})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.email, "")

    def test_only_email_and_phone_allowed(self):
        self.client.post(reverse("clients:quick_update", args=[self.mine.pk]), {"field": "owner", "value": str(self.ben.pk)})
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.owner, self.anna)

    def test_cannot_edit_other_members_client(self):
        response = self.client.post(reverse("clients:quick_update", args=[self.theirs.pk]), {"field": "email", "value": "x@y.fi"})
        self.assertEqual(response.status_code, 404)

    def test_external_next_is_ignored(self):
        response = self.client.post(reverse("clients:quick_update", args=[self.mine.pk]),
                                    {"field": "email", "value": "a@b.fi", "next": "https://evil.example/"})
        self.assertRedirects(response, reverse("clients:detail", args=[self.mine.pk]), fetch_redirect_response=False)

    def test_full_edit_returns_to_list(self):
        response = self.client.post(reverse("clients:edit", args=[self.mine.pk]) + "?next=" + self.back.replace("?", "%3F").replace("=", "%3D"), {
            "name": self.mine.name, "company_type": "oy", "language": "fi", "profession": "taxi",
            "email": "full@edit.fi", "next": self.back,
        })
        self.assertRedirects(response, self.back, fetch_redirect_response=False)
