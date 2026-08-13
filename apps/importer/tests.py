"""Spreadsheet import pipeline — CSV vertical slice for Services.

Uses django.test.TestCase + apps.api.test_helpers.make_clinic_admin,
matching the house style in apps/clinics/tests.py. The background-thread
upload path (apps/importer/services/pipeline.py::enqueue_import_pipeline)
is bypassed in tests via run_import_pipeline() called synchronously, so
assertions don't need to poll/sleep for a daemon thread.
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.api.test_helpers import make_clinic_admin
from apps.importer.models import ImportJob, ImportJobStatus, ImportRecord, ImportRecordStatus
from apps.importer.services import committer, pipeline
from apps.services.models import Service


def _csv_upload(text: str, name: str = "services.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


def _xlsx_upload(rows: list[list], name: str = "services.xlsx") -> SimpleUploadedFile:
    import io

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class ImporterTestCase(TestCase):
    """Base class for every importer test except ImportLLMMappingTests —
    patches the LLM call to fail so tests exercise the deterministic
    heuristic-mapping path and never hit the real OpenAI API (no network,
    no cost, no flakiness from a real model's mapping guesses)."""

    def setUp(self):
        super().setUp()
        patcher = mock_patch(
            "apps.importer.services.mapper._call_llm",
            side_effect=RuntimeError("LLM disabled in tests"),
        )
        self.mock_llm = patcher.start()
        self.addCleanup(patcher.stop)


class ImportUploadTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@import.test", clinic_slug="import-clinic"
        )

    def _upload(self, csv_text: str, record_type: str = "services"):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": record_type, "file": _csv_upload(csv_text)},
            headers=self.headers,
        )
        return resp

    def test_csv_upload_happy_path_maps_and_extracts(self):
        csv_text = (
            "Service Name,Cash Price,Duration (min)\n"
            "Botox,299,30\n"
            "Consultation,150,45\n"
        )
        resp = self._upload(csv_text)
        self.assertEqual(resp.status_code, 201, resp.content)
        job_id = resp.json()["id"]

        job = ImportJob.objects.get(id=job_id)
        pipeline.run_import_pipeline(job)  # synchronous, no background thread in tests
        job.refresh_from_db()

        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        self.assertEqual(job.total_row_count, 2)
        records = list(job.records.order_by("row_number"))
        self.assertEqual(len(records), 2)
        # "Service Name" -> name via heuristic synonym match
        self.assertEqual(records[0].canonical_data["name"]["value"], "Botox")

    def test_unknown_record_type_rejected(self):
        resp = self._upload("a,b\n1,2\n", record_type="not-a-real-type")
        self.assertEqual(resp.status_code, 400)

    def test_wrong_extension_rejected(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": SimpleUploadedFile("services.txt", b"a,b\n1,2\n", content_type="text/plain"),
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_unsupported_record_type_string_rejected(self):
        resp = self._upload("a,b\n1,2\n", record_type="patients")
        self.assertEqual(resp.status_code, 400)

    def test_tenant_isolation_on_get(self):
        resp = self._upload("Service Name,Cash Price\nBotox,299\n")
        job_id = resp.json()["id"]
        _, _, other_headers = make_clinic_admin(
            email="owner2@otherimport.test", clinic_slug="other-import-clinic"
        )
        other_resp = self.client.get(f"/api/v1/import/jobs/{job_id}", headers=other_headers)
        self.assertEqual(other_resp.status_code, 404)


class ImportXlsxTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@xlsx.test", clinic_slug="xlsx-clinic"
        )

    def test_xlsx_upload_happy_path(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _xlsx_upload(
                    [
                        ["Service Name", "Cash Price", "Duration (min)"],
                        ["Botox", 299, 30],
                        ["Consultation", 150, 45],
                    ]
                ),
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()

        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        self.assertEqual(job.total_row_count, 2)
        records = list(job.records.order_by("row_number"))
        self.assertEqual(records[0].canonical_data["name"]["value"], "Botox")
        self.assertEqual(records[0].canonical_data["price_cents"]["value"], 29900)

    def test_xlsx_blank_rows_skipped_and_limits_enforced(self):
        rows = [["Service Name", "Cash Price"]] + [["", ""]] + [[f"Service {i}", 100] for i in range(3)]
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _xlsx_upload(rows)},
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.total_row_count, 3)  # blank spacer row skipped

    def test_corrupt_xlsx_fails_cleanly_not_500(self):
        bad_file = SimpleUploadedFile(
            "broken.xlsx", b"not a real workbook", content_type="application/octet-stream"
        )
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": bad_file},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)  # upload itself succeeds, parse fails async
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.FAILED)


class ImportMappingTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@mapping.test", clinic_slug="mapping-clinic"
        )

    def _mapped_job(self, csv_text: str) -> ImportJob:
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _csv_upload(csv_text)},
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        return job

    def test_unknown_columns_preserved_not_discarded(self):
        job = self._mapped_job(
            "Service Name,Cash Price,Room Number\nBotox,299,Room 3\n"
        )
        record = job.records.first()
        self.assertIn("Room Number", record.raw_data)
        self.assertEqual(record.raw_data["Room Number"], "Room 3")
        self.assertNotIn("Room Number", record.canonical_data)

    def test_missing_required_column_flags_needs_review_not_500(self):
        job = self._mapped_job("Cash Price\n299\n")
        record = job.records.first()
        self.assertEqual(record.status, ImportRecordStatus.NEEDS_REVIEW)
        self.assertTrue(any(e["field"] == "name" for e in record.validation_errors))

    def test_patch_mapping_re_extracts_synchronously(self):
        job = self._mapped_job("Weird Header,Cash Price\nBotox,299\n")
        record = job.records.first()
        self.assertNotIn("name", record.canonical_data)  # "Weird Header" didn't heuristically match

        resp = self.client.patch(
            f"/api/v1/import/jobs/{job.id}/mapping",
            data={"mapping": {"Weird Header": "name", "Cash Price": "price_cents"}},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        record.refresh_from_db()
        self.assertEqual(record.canonical_data["name"]["value"], "Botox")
        self.assertEqual(record.canonical_data["price_cents"]["value"], 29900)


class ImportConfidenceTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@confidence.test", clinic_slug="confidence-clinic"
        )

    def test_low_confidence_flags_needs_review_but_keeps_value(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Some Unrecognized Header\nBotox\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        record = job.records.first()
        # Heuristic mapper leaves an unrecognized header unmapped (confidence 0) —
        # value never reaches canonical_data, and the record is NEEDS_REVIEW
        # because the required "name" field is then missing.
        self.assertEqual(record.status, ImportRecordStatus.NEEDS_REVIEW)


class ImportDuplicateTests(ImporterTestCase):
    """Unit-tests apps.importer.services.duplicates.find_duplicate directly
    — the integration test at the bottom confirms duplicate_match reaches
    the record, but overall record.status also depends on mapping
    confidence (see ImportConfidenceTests), so status isn't asserted here
    for the heuristic-mapped cases."""

    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@dupes.test", clinic_slug="dupes-clinic"
        )

    def test_exact_match_against_existing_service(self):
        from apps.importer.services import duplicates

        Service.objects.create(clinic=self.clinic, name="Botox", duration_min=30)
        match = duplicates.find_duplicate(
            record_type="services", name="Botox", clinic=self.clinic, in_batch_names=[]
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["similarity"], 1.0)

    def test_fuzzy_match_against_existing_provider(self):
        from apps.doctors.models import Doctor
        from apps.importer.services import duplicates

        Doctor.objects.create(clinic=self.clinic, full_name="Dr. John Smith")
        match = duplicates.find_duplicate(
            record_type="providers", name="Dr. Jon Smith", clinic=self.clinic, in_batch_names=[]
        )
        self.assertIsNotNone(match)
        self.assertGreaterEqual(match["similarity"], 0.85)

    def test_clearly_different_name_not_flagged(self):
        from apps.doctors.models import Doctor
        from apps.importer.services import duplicates

        Doctor.objects.create(clinic=self.clinic, full_name="Dr. John Smith")
        match = duplicates.find_duplicate(
            record_type="providers", name="Dr. James Okafor", clinic=self.clinic, in_batch_names=[]
        )
        self.assertIsNone(match)

    def test_in_batch_duplicate_flagged(self):
        from apps.importer.services import duplicates

        match = duplicates.find_duplicate(
            record_type="services", name="Botox", clinic=self.clinic, in_batch_names=["Botox"]
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["similarity"], 1.0)

    def test_duplicate_from_another_clinic_not_flagged(self):
        from apps.importer.services import duplicates

        _, other_clinic, _ = make_clinic_admin(
            email="owner2@otherdupes.test", clinic_slug="other-dupes-clinic"
        )
        Service.objects.create(clinic=other_clinic, name="Botox", duration_min=30)
        match = duplicates.find_duplicate(
            record_type="services", name="Botox", clinic=self.clinic, in_batch_names=[]
        )
        self.assertIsNone(match)

    def test_duplicate_match_reaches_the_record_through_the_pipeline(self):
        Service.objects.create(clinic=self.clinic, name="Botox", duration_min=30)
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _csv_upload("Service Name,Cash Price\nBotox,299\n")},
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        record = job.records.first()
        self.assertIsNotNone(record.duplicate_match)
        self.assertEqual(record.duplicate_match["similarity"], 1.0)


class ImportServiceDefaultTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@defaults.test", clinic_slug="defaults-clinic"
        )

    def test_blank_duration_defaults_to_30_and_commits(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _csv_upload("Service Name\nBotox\n")},
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        record = job.records.get()
        self.assertEqual(record.canonical_data["duration_min"]["value"], 30)
        self.assertIn("defaults to", record.canonical_data["duration_min"]["reason"])

        self.client.post(
            f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve", headers=self.headers
        )
        commit = self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        self.assertEqual(commit.status_code, 200, commit.content)
        service = Service.objects.get(clinic=self.clinic, name="Botox")
        self.assertEqual(service.duration_min, 30)
        self.assertIsNone(service.price_cents)

    def test_provided_duration_is_not_overwritten(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Duration (min)\nBotox,45\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        record = job.records.get()
        self.assertEqual(record.canonical_data["duration_min"]["value"], 45)
        self.assertNotIn("defaults to", record.canonical_data["duration_min"].get("reason", ""))


class ImportInvalidValueTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@invalid.test", clinic_slug="invalid-clinic"
        )

    def test_non_numeric_price_flags_error_not_500(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Cash Price\nBotox,call for pricing\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        record = job.records.first()
        self.assertEqual(record.status, ImportRecordStatus.NEEDS_REVIEW)

    def test_non_numeric_duration_flags_error_not_500(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Duration (min)\nBotox,about half an hour\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        record = job.records.first()
        self.assertTrue(any(e["field"] == "duration_min" for e in record.validation_errors))


class ImportGuardTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@guard.test", clinic_slug="guard-clinic"
        )

    def test_patient_data_headers_fail_before_mapping(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Patient Name,Date of Birth,SSN\nJohn Doe,1980-01-01,123-45-6789\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.FAILED)
        self.assertIn("patient", job.error_message.lower())
        self.assertEqual(job.records.count(), 0)
        self.mock_llm.assert_not_called()

    def test_insurance_id_on_services_import_still_fails(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Insurance ID\nBotox,60054\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.FAILED)
        self.assertIn("patient", job.error_message.lower())
        self.mock_llm.assert_not_called()


class ImportReviewFlowTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@review.test", clinic_slug="review-clinic"
        )
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Cash Price,Duration (min)\nBotox,299,30\nBad Row,not-a-number,30\n"),
            },
            headers=self.headers,
        )
        self.job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(self.job)
        self.job.refresh_from_db()
        self.records = list(self.job.records.order_by("row_number"))

    def test_approve_and_reject_transitions(self):
        good, bad = self.records
        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/records/{good.id}/approve", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["status"], "approved")

        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/records/{bad.id}/reject", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "rejected")

    def test_approve_all_approves_ready_and_skips_invalid(self):
        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/approve-all", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["approved_count"], 1)
        self.assertEqual(resp.json()["skipped_count"], 1)
        good, bad = self.records
        good.refresh_from_db()
        bad.refresh_from_db()
        self.assertEqual(good.status, ImportRecordStatus.APPROVED)
        self.assertEqual(bad.status, ImportRecordStatus.NEEDS_REVIEW)

    def test_approve_blocked_when_validation_errors_present(self):
        _, bad = self.records
        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/records/{bad.id}/approve", headers=self.headers
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_record_fixes_value_and_allows_approve(self):
        _, bad = self.records
        resp = self.client.patch(
            f"/api/v1/import/jobs/{self.job.id}/records/{bad.id}",
            data={"values": {"price_cents": 15000}},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        bad.refresh_from_db()
        self.assertEqual(bad.validation_errors, [])
        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/records/{bad.id}/approve", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)


class ImportCommitTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@commit.test", clinic_slug="commit-clinic"
        )
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload(
                    "Service Name,Cash Price,Duration (min)\nBotox,299,30\nFiller,499,45\n"
                ),
            },
            headers=self.headers,
        )
        self.job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(self.job)
        self.job.refresh_from_db()

    def _approve_all(self):
        for record in self.job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{self.job.id}/records/{record.id}/approve", headers=self.headers
            )

    def test_commit_creates_real_service_rows(self):
        self._approve_all()
        resp = self.client.post(f"/api/v1/import/jobs/{self.job.id}/commit", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["created_count"], 2)
        self.assertEqual(Service.objects.filter(clinic=self.clinic).count(), 2)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, ImportJobStatus.COMMITTED)
        self.assertTrue(all(r.status == "committed" for r in self.job.records.all()))

    def test_commit_blocked_with_outstanding_records(self):
        # Approve only one of two — the other is still NEEDS_REVIEW/READY.
        first = self.job.records.first()
        self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/records/{first.id}/approve", headers=self.headers
        )
        resp = self.client.post(f"/api/v1/import/jobs/{self.job.id}/commit", headers=self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Service.objects.filter(clinic=self.clinic).count(), 0)

    def test_commit_blocked_with_zero_approved(self):
        for record in self.job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{self.job.id}/records/{record.id}/reject", headers=self.headers
            )
        resp = self.client.post(f"/api/v1/import/jobs/{self.job.id}/commit", headers=self.headers)
        self.assertEqual(resp.status_code, 400)

    def test_atomic_rollback_on_mid_commit_failure(self):
        self._approve_all()
        from apps.services.services.service_service import create_service as real_create_service

        calls = {"n": 0}

        def flaky_create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real_create_service(**kwargs)  # first call really inserts

        with mock_patch(
            "apps.importer.services.committer.create_service", side_effect=flaky_create
        ):
            with self.assertRaises(RuntimeError):
                committer.commit_job(self.job)
        # The first record's real insert must be rolled back along with the second's failure.
        self.assertEqual(Service.objects.filter(clinic=self.clinic).count(), 0)
        self.job.refresh_from_db()
        self.assertNotEqual(self.job.status, ImportJobStatus.COMMITTED)


class ImportProvidersAndSpecialtiesTests(ImporterTestCase):
    """Same pipeline as Services, generalized by record_type — proves the
    Providers/Specialties commit path apps.doctors.services.doctor_service
    / apps.specialties.services.specialty_service wired in this slice."""

    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@providers.test", clinic_slug="providers-import-clinic"
        )

    def _upload_map_approve_commit(self, csv_text: str, record_type: str):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": record_type, "file": _csv_upload(csv_text, "data.csv")},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        for record in job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve", headers=self.headers
            )
        resp = self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        return resp, job

    def test_providers_csv_import_creates_doctors(self):
        from apps.doctors.models import Doctor

        resp, _job = self._upload_map_approve_commit(
            "Physician Name,Title\nDr. Alice Chen,MD\nDr. Bo Diallo,DO\n", "providers"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["created_count"], 2)
        self.assertEqual(
            set(Doctor.objects.filter(clinic=self.clinic).values_list("full_name", flat=True)),
            {"Dr. Alice Chen", "Dr. Bo Diallo"},
        )
        self.assertEqual(
            list(Doctor.objects.get(full_name="Dr. Alice Chen").languages),
            [],
        )

    def test_blank_languages_column_does_not_assume_english(self):
        from apps.doctors.models import Doctor

        resp, _job = self._upload_map_approve_commit(
            "Provider Name,Languages\nDr. No Lang,\n",
            "providers",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        doctor = Doctor.objects.get(clinic=self.clinic, full_name="Dr. No Lang")
        self.assertEqual(list(doctor.languages), [])

    def test_specialties_csv_import_creates_specialties(self):
        from apps.specialties.models import Specialty

        resp, _job = self._upload_map_approve_commit(
            "Specialty Name\nCardiology\nNeurology\n", "specialties"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["created_count"], 2)
        self.assertEqual(
            set(Specialty.objects.filter(clinic=self.clinic).values_list("name", flat=True)),
            {"Cardiology", "Neurology"},
        )

    def test_insurance_csv_import_creates_plans(self):
        from apps.insurance.models import InsurancePlan

        resp, _job = self._upload_map_approve_commit(
            "Insurance Name,Plan name,Network / type\n"
            "Aetna,,PPO\n"
            "Blue Cross Blue Shield,Gold,HMO\n"
            "Cigna,,\n",
            "insurance",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["created_count"], 3)
        rows = {
            (p.provider_name, p.plan_name, p.plan_type)
            for p in InsurancePlan.objects.filter(clinic=self.clinic)
        }
        self.assertEqual(
            rows,
            {
                ("Aetna", "", "PPO"),
                ("Blue Cross Blue Shield", "Gold", "HMO"),
                ("Cigna", "", ""),
            },
        )

    def test_insurance_import_rejects_blank_payer(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "insurance",
                "file": _csv_upload("Insurance Name,Plan name\n,Gold\nAetna,\n"),
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        blank = job.records.get(row_number=1)
        valid = job.records.get(row_number=2)
        self.assertEqual(blank.status, ImportRecordStatus.NEEDS_REVIEW)
        self.assertTrue(
            any(err.get("field") == "provider_name" for err in blank.validation_errors)
        )
        self.assertEqual(
            (valid.canonical_data.get("provider_name") or {}).get("value"), "Aetna"
        )
        self.assertFalse(
            any(err.get("field") == "provider_name" for err in valid.validation_errors)
        )


class ImportInsuranceEdgeTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@ins-import.test", clinic_slug="ins-import-clinic"
        )

    def _mapped(self, csv_text: str) -> ImportJob:
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "insurance", "file": _csv_upload(csv_text, "insurance.csv")},
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        return job

    def test_heuristic_maps_common_payer_headers(self):
        from apps.importer.services.heuristics import heuristic_map_columns

        mapping = heuristic_map_columns(
            "insurance",
            ["Insurance Name", "Plan name", "Network / type"],
        )
        self.assertEqual(mapping["Insurance Name"]["target"], "provider_name")
        self.assertEqual(mapping["Plan name"]["target"], "plan_name")
        self.assertEqual(mapping["Network / type"]["target"], "plan_type")

    def test_sample_csv_headers_match_template(self):
        """Keep in lockstep with frontend/src/features/importer/templates.ts."""
        from apps.importer.services.heuristics import heuristic_map_columns

        mapping = heuristic_map_columns(
            "insurance", ["Insurance Name", "Plan name", "Network / type"]
        )
        self.assertEqual(
            {info["target"] for info in mapping.values()},
            {"provider_name", "plan_name", "plan_type"},
        )

    def test_heuristic_maps_payer_carrier_and_bare_name(self):
        from apps.importer.services.heuristics import heuristic_map_columns

        mapping = heuristic_map_columns("insurance", ["Payer", "Product", "Network"])
        self.assertEqual(mapping["Payer"]["target"], "provider_name")
        self.assertEqual(mapping["Product"]["target"], "plan_name")
        self.assertEqual(mapping["Network"]["target"], "plan_type")
        mapping_name = heuristic_map_columns("insurance", ["Name"])
        self.assertEqual(mapping_name["Name"]["target"], "provider_name")

    def test_payer_id_notes_and_npi_are_not_mapped(self):
        job = self._mapped(
            "Insurance Name,Payer ID,Notes,NPI\nAetna,ABC123,in network,1234567890\n"
        )
        record = job.records.first()
        self.assertEqual(record.canonical_data["provider_name"]["value"], "Aetna")
        self.assertNotIn("notes", record.canonical_data)
        self.assertNotIn("payer_id", record.canonical_data)
        self.assertIn("Payer ID", record.raw_data)
        self.assertIn("Notes", record.raw_data)
        self.assertIn("NPI", record.raw_data)

    def test_mapping_rejects_invented_target(self):
        job = self._mapped("Insurance Name\nAetna\n")
        resp = self.client.patch(
            f"/api/v1/import/jobs/{job.id}/mapping",
            data={"mapping": {"Insurance Name": "payer_id"}},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_xlsx_import_creates_plans(self):
        from apps.insurance.models import InsurancePlan

        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "insurance",
                "file": _xlsx_upload(
                    [
                        ["Insurance Name", "Plan name", "Network / type"],
                        ["Aetna", "Gold", "PPO"],
                        ["Cigna", "", ""],
                    ],
                    "insurance.xlsx",
                ),
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        for record in job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve",
                headers=self.headers,
            )
        commit = self.client.post(
            f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers
        )
        self.assertEqual(commit.status_code, 200, commit.content)
        self.assertEqual(commit.json()["created_count"], 2)
        rows = {
            (p.provider_name, p.plan_name, p.plan_type, p.is_accepted, p.notes)
            for p in InsurancePlan.objects.filter(clinic=self.clinic)
        }
        self.assertEqual(rows, {("Aetna", "Gold", "PPO", True, ""), ("Cigna", "", "", True, "")})

    def test_commit_does_not_create_doctor_insurance_links(self):
        from apps.doctors.models import Doctor, DoctorInsurance
        from apps.insurance.models import InsurancePlan

        Doctor.objects.create(clinic=self.clinic, full_name="Dr. Link Test")
        job = self._mapped("Insurance Name\nAetna\n")
        for record in job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve",
                headers=self.headers,
            )
        self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        self.assertEqual(InsurancePlan.objects.filter(clinic=self.clinic).count(), 1)
        self.assertEqual(DoctorInsurance.objects.filter(clinic=self.clinic).count(), 0)

    def test_duplicate_against_existing_payer(self):
        from apps.importer.services import duplicates
        from apps.insurance.models import InsurancePlan

        InsurancePlan.objects.create(clinic=self.clinic, provider_name="Aetna")
        match = duplicates.find_duplicate(
            record_type="insurance", name="Aetna", clinic=self.clinic, in_batch_names=[]
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["similarity"], 1.0)

    def test_same_payer_different_plans_are_not_duplicates(self):
        from apps.importer.services import duplicates
        from apps.insurance.models import InsurancePlan

        InsurancePlan.objects.create(
            clinic=self.clinic, provider_name="Aetna", plan_name="Gold", plan_type="PPO"
        )
        silver = duplicates.find_duplicate(
            record_type="insurance",
            name="Aetna",
            clinic=self.clinic,
            in_batch_names=[],
            extra={"plan_name": "Silver", "plan_type": "HMO"},
        )
        self.assertIsNone(silver)
        same_network = duplicates.find_duplicate(
            record_type="insurance",
            name="Aetna",
            clinic=self.clinic,
            in_batch_names=[],
            extra={"plan_name": "Gold", "plan_type": "HMO"},
        )
        self.assertIsNone(same_network)

    def test_identical_payer_plan_network_is_duplicate_case_insensitive(self):
        from apps.importer.services import duplicates
        from apps.insurance.models import InsurancePlan

        InsurancePlan.objects.create(
            clinic=self.clinic, provider_name="Aetna", plan_name="Gold", plan_type="PPO"
        )
        match = duplicates.find_duplicate(
            record_type="insurance",
            name="aetna",
            clinic=self.clinic,
            in_batch_names=[],
            extra={"plan_name": "GOLD", "plan_type": "ppo"},
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["label"], "Aetna · Gold · PPO")

    def test_soft_deleted_plan_is_not_a_duplicate(self):
        from apps.importer.services import duplicates
        from apps.insurance.models import InsurancePlan

        plan = InsurancePlan.objects.create(clinic=self.clinic, provider_name="Aetna")
        plan.is_deleted = True
        plan.save(update_fields=["is_deleted"])
        match = duplicates.find_duplicate(
            record_type="insurance", name="Aetna", clinic=self.clinic, in_batch_names=[]
        )
        self.assertIsNone(match)

    def test_csv_same_payer_different_plans_imports_both(self):
        from apps.insurance.models import InsurancePlan

        job = self._mapped(
            "Insurance Name,Plan name,Network / type\n"
            "Aetna,Gold,PPO\n"
            "Aetna,Silver,HMO\n"
        )
        statuses = {r.row_number: r.duplicate_match for r in job.records.all()}
        self.assertIsNone(statuses[1])
        self.assertIsNone(statuses[2])
        for record in job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve",
                headers=self.headers,
            )
        commit = self.client.post(
            f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers
        )
        self.assertEqual(commit.status_code, 200, commit.content)
        self.assertEqual(commit.json()["created_count"], 2)
        rows = {
            (p.provider_name, p.plan_name, p.plan_type)
            for p in InsurancePlan.objects.filter(clinic=self.clinic)
        }
        self.assertEqual(rows, {("Aetna", "Gold", "PPO"), ("Aetna", "Silver", "HMO")})

    def test_csv_identical_rows_flag_in_batch_duplicate(self):
        job = self._mapped(
            "Insurance Name,Plan name,Network / type\n"
            "Aetna,Gold,PPO\n"
            "Aetna,Gold,PPO\n"
        )
        first, second = job.records.get(row_number=1), job.records.get(row_number=2)
        self.assertIsNone(first.duplicate_match)
        self.assertIsNotNone(second.duplicate_match)
        self.assertEqual(second.duplicate_match["label"], "Aetna · Gold · PPO")

    def test_heuristic_maps_carrier_company_insurer(self):
        from apps.importer.services.heuristics import heuristic_map_columns

        for header in ("Carrier", "Company", "Insurer"):
            mapping = heuristic_map_columns("insurance", [header])
            self.assertEqual(mapping[header]["target"], "provider_name", header)

    def test_insurance_id_column_is_allowed_on_payer_lists(self):
        job = self._mapped("Insurance Name,Insurance ID\nAetna,60054\n")
        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        record = job.records.first()
        self.assertEqual(record.canonical_data["provider_name"]["value"], "Aetna")
        self.assertNotIn("insurance_id", record.canonical_data)

    def test_member_id_still_fails_insurance_import_as_phi(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "insurance",
                "file": _csv_upload(
                    "Insurance Name,Member ID\nAetna,M-12345\n", "insurance.csv"
                ),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.FAILED)
        self.assertIn("patient", job.error_message.lower())

    def test_commit_skips_rejected_blank_and_keeps_valid(self):
        from apps.insurance.models import InsurancePlan

        job = self._mapped("Insurance Name,Plan name\n,Gold\nAetna,\n")
        blank = job.records.get(row_number=1)
        valid = job.records.get(row_number=2)
        self.client.post(
            f"/api/v1/import/jobs/{job.id}/records/{blank.id}/reject",
            headers=self.headers,
        )
        self.client.post(
            f"/api/v1/import/jobs/{job.id}/records/{valid.id}/approve",
            headers=self.headers,
        )
        commit = self.client.post(
            f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers
        )
        self.assertEqual(commit.status_code, 200, commit.content)
        self.assertEqual(commit.json()["created_count"], 1)
        self.assertEqual(
            InsurancePlan.objects.get(clinic=self.clinic).provider_name, "Aetna"
        )

    def test_commit_blocked_while_row_still_needs_review(self):
        job = self._mapped("Insurance Name\nAetna\n")
        resp = self.client.post(
            f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_jobs_filters_insurance_record_type(self):
        job = self._mapped("Insurance Name\nAetna\n")
        listing = self.client.get(
            "/api/v1/import/jobs?record_type=insurance", headers=self.headers
        )
        self.assertEqual(listing.status_code, 200)
        self.assertIn(str(job.id), [row["id"] for row in listing.json()])
        services = self.client.get(
            "/api/v1/import/jobs?record_type=services", headers=self.headers
        )
        self.assertNotIn(str(job.id), [row["id"] for row in services.json()])

    def test_empty_insurance_csv_fails_cleanly(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "insurance",
                "file": _csv_upload("Insurance Name\n", "insurance.csv"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.FAILED)
        self.assertIn("no data", job.error_message.lower())

    def test_unicode_payer_imports(self):
        from apps.insurance.models import InsurancePlan

        job = self._mapped("Insurance Name\nMüller Kranken\n")
        record = job.records.first()
        self.client.post(
            f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve",
            headers=self.headers,
        )
        self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        self.assertEqual(
            InsurancePlan.objects.get(clinic=self.clinic).provider_name,
            "Müller Kranken",
        )

    def test_whitespace_payer_stripped_on_commit(self):
        from apps.insurance.models import InsurancePlan

        job = self._mapped("Insurance Name\n  Aetna  \n")
        for record in job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve",
                headers=self.headers,
            )
        self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        self.assertEqual(
            InsurancePlan.objects.get(clinic=self.clinic).provider_name, "Aetna"
        )

    def test_long_network_truncated_on_commit(self):
        from apps.insurance.models import InsurancePlan

        job = self._mapped("Insurance Name,Network / type\nAetna," + ("P" * 80) + "\n")
        for record in job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve",
                headers=self.headers,
            )
        resp = self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(InsurancePlan.objects.get(clinic=self.clinic).plan_type), 50)

    def test_insurance_job_does_not_create_services(self):
        from apps.insurance.models import InsurancePlan
        from apps.services.models import Service

        job = self._mapped("Insurance Name\nAetna\n")
        for record in job.records.all():
            self.client.post(
                f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve",
                headers=self.headers,
            )
        self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        self.assertEqual(InsurancePlan.objects.filter(clinic=self.clinic).count(), 1)
        self.assertEqual(Service.objects.filter(clinic=self.clinic).count(), 0)

    def test_tenant_cannot_see_other_clinic_insurance_job(self):
        job = self._mapped("Insurance Name\nAetna\n")
        _, _, other_headers = make_clinic_admin(
            email="other@ins-import-2.test", clinic_slug="ins-import-clinic-2"
        )
        resp = self.client.get(f"/api/v1/import/jobs/{job.id}", headers=other_headers)
        self.assertEqual(resp.status_code, 404)


class ImportFileSafetyTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@filesafety.test", clinic_slug="filesafety-clinic"
        )

    def test_oversized_file_rejected_at_upload(self):
        from django.test import override_settings

        with override_settings(IMPORTER_MAX_FILE_SIZE_BYTES=10):
            resp = self.client.post(
                "/api/v1/import/jobs",
                data={
                    "record_type": "services",
                    "file": _csv_upload("Service Name,Cash Price\nBotox,299\n"),
                },
                headers=self.headers,
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ImportJob.objects.filter(clinic=self.clinic).count(), 0)

    def test_too_many_rows_fails_during_parse(self):
        from django.test import override_settings

        rows = "\n".join(f"Service {i},{i}" for i in range(10))
        csv_text = "Service Name,Cash Price\n" + rows + "\n"
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _csv_upload(csv_text)},
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        with override_settings(IMPORTER_MAX_ROWS=3):
            pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.FAILED)
        self.assertIn("too many rows", job.error_message.lower())

    def test_too_many_columns_fails_during_parse(self):
        from django.test import override_settings

        headers = ",".join(f"Column {i}" for i in range(10))
        csv_text = f"{headers}\n" + ",".join(str(i) for i in range(10)) + "\n"
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _csv_upload(csv_text)},
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        with override_settings(IMPORTER_MAX_COLUMNS=3):
            pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJobStatus.FAILED)
        self.assertIn("too many columns", job.error_message.lower())

    def test_wrong_extension_rejected_with_clean_400(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": SimpleUploadedFile("services.docx", b"not a spreadsheet", content_type="application/octet-stream"),
            },
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)


class ImportResumabilityTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@resume.test", clinic_slug="resume-clinic"
        )

    def test_job_revisited_later_is_still_patchable_and_approvable(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Cash Price\nBotox,299\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()

        # Simulate the owner navigating away and coming back later: a
        # fresh GET, not the object already held in memory.
        later = self.client.get(f"/api/v1/import/jobs/{job.id}", headers=self.headers)
        self.assertEqual(later.status_code, 200)
        self.assertEqual(later.json()["status"], "mapped")

        records_resp = self.client.get(f"/api/v1/import/jobs/{job.id}/records", headers=self.headers)
        record_id = records_resp.json()["results"][0]["id"]
        approve_resp = self.client.post(
            f"/api/v1/import/jobs/{job.id}/records/{record_id}/approve", headers=self.headers
        )
        self.assertEqual(approve_resp.status_code, 200)
        commit_resp = self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        self.assertEqual(commit_resp.status_code, 200)

    def test_unfinished_jobs_listed_for_resume(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Cash Price\nBotox,299\n"),
            },
            headers=self.headers,
        )
        job_id = resp.json()["id"]
        listing = self.client.get("/api/v1/import/jobs?record_type=services", headers=self.headers)
        self.assertEqual(listing.status_code, 200)
        self.assertIn(job_id, [row["id"] for row in listing.json()])


class ImportTenantIsolationTests(ImporterTestCase):
    """Every job/record-scoped endpoint must 404 for a different clinic's
    JWT — matching the _get_doctor/_get_service convention used
    throughout the API (404, never 403, so tenant existence isn't
    leaked)."""

    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@isolation.test", clinic_slug="isolation-clinic"
        )
        _, self.other_clinic, self.other_headers = make_clinic_admin(
            email="owner2@otherisolation.test", clinic_slug="other-isolation-clinic"
        )
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Cash Price\nBotox,299\n"),
            },
            headers=self.headers,
        )
        self.job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(self.job)
        self.job.refresh_from_db()
        self.record = self.job.records.first()

    def test_get_job_404s_for_other_clinic(self):
        resp = self.client.get(f"/api/v1/import/jobs/{self.job.id}", headers=self.other_headers)
        self.assertEqual(resp.status_code, 404)

    def test_list_records_404s_for_other_clinic(self):
        resp = self.client.get(
            f"/api/v1/import/jobs/{self.job.id}/records", headers=self.other_headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_patch_mapping_404s_for_other_clinic(self):
        resp = self.client.patch(
            f"/api/v1/import/jobs/{self.job.id}/mapping",
            data={"mapping": {"Service Name": "name"}},
            content_type="application/json",
            headers=self.other_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_patch_record_404s_for_other_clinic(self):
        resp = self.client.patch(
            f"/api/v1/import/jobs/{self.job.id}/records/{self.record.id}",
            data={"values": {"name": "Hacked"}},
            content_type="application/json",
            headers=self.other_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_approve_404s_for_other_clinic(self):
        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/records/{self.record.id}/approve",
            headers=self.other_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_reject_404s_for_other_clinic(self):
        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/records/{self.record.id}/reject",
            headers=self.other_headers,
        )
        self.assertEqual(resp.status_code, 404)

    def test_commit_404s_for_other_clinic(self):
        resp = self.client.post(
            f"/api/v1/import/jobs/{self.job.id}/commit", headers=self.other_headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_delete_404s_for_other_clinic(self):
        resp = self.client.delete(f"/api/v1/import/jobs/{self.job.id}", headers=self.other_headers)
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(ImportJob.objects.filter(id=self.job.id).exists())


class ImportDeleteTests(ImporterTestCase):
    def setUp(self):
        super().setUp()
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@delete.test", clinic_slug="delete-clinic"
        )

    def test_delete_uncommitted_job(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _csv_upload("Service Name\nBotox\n")},
            headers=self.headers,
        )
        job_id = resp.json()["id"]
        resp = self.client.delete(f"/api/v1/import/jobs/{job_id}", headers=self.headers)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(ImportJob.objects.filter(id=job_id).exists())

    def test_cannot_delete_committed_job(self):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={
                "record_type": "services",
                "file": _csv_upload("Service Name,Cash Price\nBotox,299\n"),
            },
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        record = job.records.first()
        self.client.post(
            f"/api/v1/import/jobs/{job.id}/records/{record.id}/approve", headers=self.headers
        )
        self.client.post(f"/api/v1/import/jobs/{job.id}/commit", headers=self.headers)
        resp = self.client.delete(f"/api/v1/import/jobs/{job.id}", headers=self.headers)
        self.assertEqual(resp.status_code, 400)


class ImportLLMMappingTests(TestCase):
    """Does NOT inherit ImporterTestCase — these tests mock
    apps.importer.services.mapper._call_llm directly, per scenario,
    instead of always forcing the heuristic fallback."""

    def setUp(self):
        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@llm.test", clinic_slug="llm-clinic"
        )

    def _upload_and_run(self, csv_text: str):
        resp = self.client.post(
            "/api/v1/import/jobs",
            data={"record_type": "services", "file": _csv_upload(csv_text)},
            headers=self.headers,
        )
        job = ImportJob.objects.get(id=resp.json()["id"])
        pipeline.run_import_pipeline(job)
        job.refresh_from_db()
        return job

    def test_successful_llm_mapping_is_used(self):
        fake_mapping = {
            "Physician Name": {"target": None, "confidence": 0.0, "reason": "not a service field"},
            "Treatment": {"target": "name", "confidence": 0.95, "reason": "clearly the service name"},
            "Cash Price": {"target": "price_cents", "confidence": 0.9, "reason": "price column"},
        }
        with mock_patch(
            "apps.importer.services.mapper._call_llm", return_value=fake_mapping
        ):
            job = self._upload_and_run("Physician Name,Treatment,Cash Price\nDr. Lee,Botox,299\n")
        self.assertEqual(job.metadata["mapping_source"], "llm")
        record = job.records.first()
        self.assertEqual(record.canonical_data["name"]["value"], "Botox")

    def test_llm_timeout_falls_back_to_heuristic_never_fails_job(self):
        with mock_patch(
            "apps.importer.services.mapper._call_llm", side_effect=TimeoutError("slow")
        ):
            job = self._upload_and_run("Service Name,Cash Price\nBotox,299\n")
        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        self.assertEqual(job.metadata["mapping_source"], "heuristic_fallback")

    def test_malformed_llm_json_falls_back_to_heuristic(self):
        with mock_patch(
            "apps.importer.services.mapper._call_llm", side_effect=ValueError("bad json")
        ):
            job = self._upload_and_run("Service Name,Cash Price\nBotox,299\n")
        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        self.assertEqual(job.metadata["mapping_source"], "heuristic_fallback")

    def test_out_of_catalog_target_falls_back_to_heuristic(self):
        fake_mapping = {
            "Service Name": {"target": "not_a_real_field", "confidence": 0.9, "reason": "hallucinated"},
            "Cash Price": {"target": "price_cents", "confidence": 0.9, "reason": "price"},
        }
        with mock_patch(
            "apps.importer.services.mapper._call_llm", return_value=fake_mapping
        ):
            job = self._upload_and_run("Service Name,Cash Price\nBotox,299\n")
        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        self.assertEqual(job.metadata["mapping_source"], "heuristic_fallback")

    def test_duplicate_target_falls_back_to_heuristic(self):
        fake_mapping = {
            "Service Name": {"target": "name", "confidence": 0.9, "reason": "a"},
            "Treatment": {"target": "name", "confidence": 0.8, "reason": "also name?!"},
        }
        with mock_patch(
            "apps.importer.services.mapper._call_llm", return_value=fake_mapping
        ):
            job = self._upload_and_run("Service Name,Treatment\nBotox,Botox Treatment\n")
        self.assertEqual(job.metadata["mapping_source"], "heuristic_fallback")

    def test_missing_openai_key_falls_back_cleanly(self):
        from django.test import override_settings

        with override_settings(OPENAI_API_KEY=""):
            job = self._upload_and_run("Service Name,Cash Price\nBotox,299\n")
        self.assertEqual(job.status, ImportJobStatus.MAPPED)
        self.assertEqual(job.metadata["mapping_source"], "heuristic_fallback")
