"""Patient list search + date-of-birth validation."""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.api.test_helpers import make_clinic_admin
from apps.patients.dob import validate_date_of_birth
from apps.patients.models import Patient

URL = "/api/v1/patients"


class PatientSearchTests(TestCase):
    def setUp(self):
        _user, clinic, self.headers = make_clinic_admin(
            email="patient-search@test.com",
            clinic_slug="patient-search",
        )
        self.clinic = clinic
        Patient.objects.create(
            clinic=clinic,
            first_name="Ali",
            last_name="Hamza",
            phone="+15551230001",
            email="ali.hamza@example.com",
        )
        Patient.objects.create(
            clinic=clinic,
            first_name="Aisha",
            last_name="Malik",
            phone="+15551230002",
            email="aisha@example.com",
        )

    def test_full_name_query_matches_first_and_last(self):
        resp = self.client.get(
            URL,
            {"search": "Ali Hamza"},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        names = [r["full_name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["Ali Hamza"])

    def test_single_token_still_matches(self):
        # "Hamza" (not "Ali") — "Ali" is a substring of "Aisha" under icontains.
        resp = self.client.get(URL, {"search": "Hamza"}, headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        names = [r["full_name"] for r in resp.json()["results"]]
        self.assertEqual(names, ["Ali Hamza"])


class PatientDobValidationTests(TestCase):
    def setUp(self):
        _user, clinic, self.headers = make_clinic_admin(
            email="patient-dob@test.com",
            clinic_slug="patient-dob",
        )
        self.clinic = clinic

    def _payload(self, **overrides):
        base = {
            "phone": "+15559870001",
            "first_name": "Nova",
            "last_name": "Patient",
            "email": "nova@example.com",
            "date_of_birth": "1990-05-15",
        }
        base.update(overrides)
        return base

    def test_future_dob_rejected_by_api(self):
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post(
            URL,
            data=self._payload(date_of_birth=future, phone="+15559870011"),
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("future", resp.json()["detail"].lower())

    def test_too_old_dob_rejected_by_api(self):
        ancient = date(timezone.localdate().year - 130, 1, 1).isoformat()
        resp = self.client.post(
            URL,
            data=self._payload(date_of_birth=ancient, phone="+15559870012"),
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_valid_dob_accepted(self):
        resp = self.client.post(
            URL,
            data=self._payload(),
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["date_of_birth"], "1990-05-15")

    def test_model_rejects_future_dob(self):
        with self.assertRaises(ValidationError):
            Patient.objects.create(
                clinic=self.clinic,
                first_name="Bad",
                last_name="Dob",
                phone="+15559870013",
                date_of_birth=timezone.localdate() + timedelta(days=3),
            )

    def test_validator_allows_today(self):
        today = timezone.localdate()
        self.assertEqual(validate_date_of_birth(today), today)

    def test_too_old_check_does_not_crash_on_leap_day(self):
        """Constructing `date(today.year - 120, today.month, today.day)`
        raises a raw ValueError (not the intended ValidationError) whenever
        today is Feb 29 and year-120 isn't also a leap year -- the two can
        disagree exactly at a non-leap century boundary. Rare in practice,
        but the whole point of this validator is to never surface a raw
        exception instead of a clean, patient-facing message."""
        from datetime import date as real_date
        from unittest.mock import patch

        with patch(
            "apps.patients.dob.timezone.localdate",
            return_value=real_date(2220, 2, 29),  # 2220 leap, 2100 is not
        ):
            # A very old but not-quite-120-years-back DOB must still pass.
            result = validate_date_of_birth(real_date(2101, 3, 1))
            self.assertEqual(result, real_date(2101, 3, 1))
            # And a genuinely too-old one must still raise ValidationError,
            # not crash.
            with self.assertRaises(ValidationError):
                validate_date_of_birth(real_date(2050, 1, 1))
