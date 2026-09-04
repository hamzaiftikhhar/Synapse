from django.test import TestCase

from apps.api.test_helpers import make_clinic_admin


class ServiceCategoryTests(TestCase):
    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@services.test", clinic_slug="services-clinic"
        )

    def test_valid_category_is_saved(self):
        resp = self.client.post(
            "/api/v1/services",
            data={"name": "Root Canal", "category": "Dentistry"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["category"], "Dentistry")

    def test_invalid_category_rejected(self):
        resp = self.client.post(
            "/api/v1/services",
            data={"name": "Something", "category": "Not A Real Category"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_category_can_be_updated(self):
        created = self.client.post(
            "/api/v1/services",
            data={"name": "Consultation"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        self.assertEqual(created["category"], "")
        resp = self.client.patch(
            f"/api/v1/services/{created['id']}",
            data={"category": "Cardiology"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["category"], "Cardiology")
