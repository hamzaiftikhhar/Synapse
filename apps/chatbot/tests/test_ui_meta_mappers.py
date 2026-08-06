"""ui_meta.py row mappers (Phase 2): photo_url/is_accepted/duration_min/
price_cents/category were computed by SQL handlers but silently dropped
before reaching the frontend — these lock in the fix."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.ui_meta import _map_doctor, _map_insurance, _map_service


class MapDoctorTests(SimpleTestCase):
    def test_forwards_photo_url(self):
        row = {"id": "1", "full_name": "Dr. Test", "photo_url": "https://example.com/a.jpg"}
        mapped = _map_doctor(row)
        self.assertEqual(mapped["photo_url"], "https://example.com/a.jpg")

    def test_defaults_photo_url_to_empty_string(self):
        row = {"id": "1", "full_name": "Dr. Test"}
        mapped = _map_doctor(row)
        self.assertEqual(mapped["photo_url"], "")


class MapInsuranceTests(SimpleTestCase):
    def test_forwards_is_accepted_true(self):
        row = {"id": "1", "provider_name": "Blue Cross", "is_accepted": True}
        self.assertTrue(_map_insurance(row)["is_accepted"])

    def test_forwards_is_accepted_false(self):
        row = {"id": "1", "provider_name": "Medicaid", "is_accepted": False}
        self.assertFalse(_map_insurance(row)["is_accepted"])


class MapServiceTests(SimpleTestCase):
    def test_forwards_duration_price_and_category(self):
        row = {
            "id": "1",
            "name": "Botox",
            "duration_min": 30,
            "price_cents": 50000,
            "category": "Aesthetic",
        }
        mapped = _map_service(row)
        self.assertEqual(mapped["duration_min"], 30)
        self.assertEqual(mapped["price_cents"], 50000)
        self.assertEqual(mapped["category"], "Aesthetic")
