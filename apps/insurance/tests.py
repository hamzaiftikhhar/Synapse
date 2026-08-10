from django.test import TestCase

from apps.api.test_helpers import make_clinic_admin


class InsurancePlanCrudTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@insurance.test", clinic_slug="insurance-clinic"
        )

    def test_create_and_list(self):
        resp = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Aetna", "plan_name": "PPO"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        listed = self.client.get("/api/v1/insurance", headers=self.headers)
        self.assertEqual(listed.json()["count"], 1)

    def test_blank_provider_rejected(self):
        resp = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "  "},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_soft_delete_excludes_from_list(self):
        created = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Cigna"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        self.client.delete(f"/api/v1/insurance/{created['id']}", headers=self.headers)
        resp = self.client.get("/api/v1/insurance", headers=self.headers)
        self.assertEqual(resp.json()["count"], 0)

    def test_tenant_isolation(self):
        _, _, other_headers = make_clinic_admin(
            email="owner2@insurance.test", clinic_slug="insurance-clinic-2"
        )
        created = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "United"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        resp = self.client.get(f"/api/v1/insurance/{created['id']}", headers=other_headers)
        self.assertEqual(resp.status_code, 404)
