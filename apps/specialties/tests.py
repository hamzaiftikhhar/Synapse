from django.test import TestCase

from apps.api.test_helpers import make_clinic_admin
from apps.specialties.models import Specialty


class SpecialtyCrudTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@specialties.test", clinic_slug="specialties-clinic"
        )

    def test_create_generates_unique_slug(self):
        resp = self.client.post(
            "/api/v1/specialties",
            data={"name": "Cosmetic Dermatology"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["slug"], "cosmetic-dermatology")

    def test_duplicate_name_gets_disambiguated_slug(self):
        for _ in range(2):
            resp = self.client.post(
                "/api/v1/specialties",
                data={"name": "Dermatology"},
                content_type="application/json",
                headers=self.headers,
            )
            self.assertEqual(resp.status_code, 201)
        slugs = set(
            Specialty.objects.filter(clinic=self.clinic).values_list("slug", flat=True)
        )
        self.assertEqual(len(slugs), 2)

    def test_list_excludes_soft_deleted(self):
        create = self.client.post(
            "/api/v1/specialties",
            data={"name": "Orthodontics"},
            content_type="application/json",
            headers=self.headers,
        )
        specialty_id = create.json()["id"]
        self.client.delete(f"/api/v1/specialties/{specialty_id}", headers=self.headers)
        resp = self.client.get("/api/v1/specialties", headers=self.headers)
        self.assertEqual(resp.json()["count"], 0)

    def test_blank_name_rejected(self):
        resp = self.client.post(
            "/api/v1/specialties",
            data={"name": "  "},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_tenant_isolation(self):
        _, other_clinic, other_headers = make_clinic_admin(
            email="owner2@specialties.test", clinic_slug="specialties-clinic-2"
        )
        created = self.client.post(
            "/api/v1/specialties",
            data={"name": "Primary Care"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        resp = self.client.get(
            f"/api/v1/specialties/{created['id']}", headers=other_headers
        )
        self.assertEqual(resp.status_code, 404)
