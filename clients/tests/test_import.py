from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.tests.factories import make_admin, make_client, make_user
from clients.models import Client, ClientAssignment
from clients.validators import normalize_business_id, normalize_phone

CSV = (
    "Nimi;Y-tunnus;Sähköposti;Puhelin;Kieli;Yhtiömuoto\n"
    "Mäkinen Rakennus Oy;0112038-9;info@makinen.test;040 123 4567;suomi;Oy\n"
    "Nordic Design Tmi;;hello@nordic.test;+358501112222;english;tmi\n"
    ";;missing@name.test;;fi;\n"
    "Bad Email Oy;;not-an-email;;fi;\n"
    "Duplicate Oy;;info@makinen.test;;fi;\n"
    "Existing Oy;;existing@client.test;;fi;\n"
).encode("utf-8")


class ValidatorTests(TestCase):
    def test_business_id(self):
        self.assertEqual(normalize_business_id("0112038-9"), "0112038-9")
        self.assertEqual(normalize_business_id("112038-9"), "0112038-9")
        with self.assertRaises(ValidationError):
            normalize_business_id("0112038-8")
        with self.assertRaises(ValidationError):
            normalize_business_id("abc")

    def test_phone(self):
        self.assertEqual(normalize_phone("040 123 4567"), "+358401234567")
        self.assertEqual(normalize_phone("00358401234567"), "+358401234567")
        with self.assertRaises(ValidationError):
            normalize_phone("12")


class ImportFlowTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.anna = make_user()
        make_client(email="existing@client.test")
        self.client.force_login(self.admin)

    def test_full_import(self):
        upload = SimpleUploadedFile("clients.csv", CSV, content_type="text/csv")
        self.assertRedirects(self.client.post(reverse("clients:import_upload"), {"file": upload}), reverse("clients:import_map"))

        # Finnish headers are mapped automatically.
        page = self.client.get(reverse("clients:import_map"))
        self.assertEqual(page.context["form"]["email"].initial, "2")

        mapping = {"name": "0", "business_id": "1", "email": "2", "phone": "3", "language": "4", "company_type": "5", "owner": self.anna.pk}
        self.assertRedirects(self.client.post(reverse("clients:import_map"), mapping), reverse("clients:import_preview"))

        preview = self.client.get(reverse("clients:import_preview"))
        self.assertEqual(preview.context["valid_count"], 2)
        problems = {p["line"]: p for p in preview.context["problems"]}
        self.assertEqual(set(problems), {4, 5, 6, 7})
        self.assertIn("Name is missing.", problems[4]["errors"])
        self.assertTrue(problems[6]["duplicate"])
        self.assertTrue(problems[7]["duplicate"])

        self.client.post(reverse("clients:import_preview"))
        makinen = Client.objects.get(business_id="0112038-9")
        self.assertEqual(makinen.phone, "+358401234567")
        self.assertEqual(makinen.company_type, "oy")
        self.assertEqual(makinen.owner, self.anna)
        nordic = Client.objects.get(email="hello@nordic.test")
        self.assertEqual((nordic.language, nordic.company_type), ("en", "toiminimi"))
        self.assertEqual(ClientAssignment.objects.filter(to_user=self.anna).count(), 2)

    def test_rejects_other_file_types(self):
        upload = SimpleUploadedFile("clients.txt", b"x", content_type="text/plain")
        response = self.client.post(reverse("clients:import_upload"), {"file": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ".csv or .xlsx")


class ProfessionTests(TestCase):
    def test_filter_by_profession(self):
        admin = make_admin()
        make_client(name="Taksi Virtanen", profession="taxi")
        make_client(name="Ravintola Kulma", profession="restaurant")
        self.client.force_login(admin)
        response = self.client.get(reverse("clients:list"), {"profession": "taxi"})
        self.assertContains(response, "Taksi Virtanen")
        self.assertNotContains(response, "Ravintola Kulma")

    def test_import_maps_finnish_profession(self):
        from clients.importer import validate_rows
        [row] = validate_rows([["Taksi Oy", "taksi"]], {"name": 0, "profession": 1})
        self.assertEqual(row["data"]["profession"], "taxi")


class DashboardFilterTests(TestCase):
    def test_cannot_receive_filter(self):
        admin = make_admin()
        make_client(name="Ok Oy")
        make_client(name="Optout Oy", opted_out=True)
        make_client(name="Noemail Oy", email="")
        self.client.force_login(admin)
        r = self.client.get(reverse("clients:list"), {"status": "cannot_receive"})
        self.assertContains(r, "Optout Oy")
        self.assertContains(r, "Noemail Oy")
        self.assertNotContains(r, "Ok Oy")
