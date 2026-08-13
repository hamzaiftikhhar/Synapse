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

    def test_optional_plan_and_network_saved(self):
        resp = self.client.post(
            "/api/v1/insurance",
            data={
                "provider_name": "Aetna",
                "plan_name": "Gold",
                "plan_type": "PPO",
            },
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["provider_name"], "Aetna")
        self.assertEqual(body["plan_name"], "Gold")
        self.assertEqual(body["plan_type"], "PPO")
        self.assertTrue(body["is_accepted"])
        self.assertEqual(body["notes"], "")

    def test_long_plan_type_is_truncated(self):
        resp = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Aetna", "plan_type": "P" * 80},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(resp.json()["plan_type"]), 50)

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

    def test_create_strips_whitespace(self):
        resp = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "  Aetna  ", "plan_name": "  Gold  ", "plan_type": "  PPO  "},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["provider_name"], "Aetna")
        self.assertEqual(body["plan_name"], "Gold")
        self.assertEqual(body["plan_type"], "PPO")

    def test_search_matches_provider_plan_and_network(self):
        self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Blue Cross", "plan_name": "Gold", "plan_type": "HMO"},
            content_type="application/json",
            headers=self.headers,
        )
        self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Cigna", "plan_type": "EPO"},
            content_type="application/json",
            headers=self.headers,
        )
        by_payer = self.client.get("/api/v1/insurance?search=Blue", headers=self.headers)
        self.assertEqual(by_payer.json()["count"], 1)
        by_plan = self.client.get("/api/v1/insurance?search=Gold", headers=self.headers)
        self.assertEqual(by_plan.json()["count"], 1)
        by_network = self.client.get("/api/v1/insurance?search=EPO", headers=self.headers)
        self.assertEqual(by_network.json()["count"], 1)

    def test_patch_rejects_blank_provider_name(self):
        created = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Aetna"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        resp = self.client.patch(
            f"/api/v1/insurance/{created['id']}",
            data={"provider_name": "   "},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_updates_optional_fields_without_notes(self):
        created = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Aetna"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        resp = self.client.patch(
            f"/api/v1/insurance/{created['id']}",
            data={"plan_name": "Silver", "plan_type": "HMO"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["plan_name"], "Silver")
        self.assertEqual(resp.json()["plan_type"], "HMO")
        self.assertEqual(resp.json()["notes"], "")

    def test_soft_delete_does_not_hard_delete_and_marks_not_accepted(self):
        from apps.insurance.models import InsurancePlan

        created = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Humana"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        self.client.delete(f"/api/v1/insurance/{created['id']}", headers=self.headers)
        row = InsurancePlan.objects.get(id=created["id"])
        self.assertTrue(row.is_deleted)
        self.assertFalse(row.is_accepted)

    def test_helper_rejects_blank_name(self):
        from apps.insurance.services.insurance_service import create_insurance_plan

        with self.assertRaises(ValueError):
            create_insurance_plan(clinic=self.clinic, provider_name="  ")

    def test_unauthenticated_requests_rejected(self):
        self.assertEqual(self.client.get("/api/v1/insurance").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/v1/insurance",
                data={"provider_name": "Aetna"},
                content_type="application/json",
            ).status_code,
            401,
        )

    def test_filter_is_accepted_and_include_deleted(self):
        accepted = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Aetna", "is_accepted": True},
            content_type="application/json",
            headers=self.headers,
        ).json()
        rejected = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Medicaid", "is_accepted": False},
            content_type="application/json",
            headers=self.headers,
        ).json()
        self.client.delete(f"/api/v1/insurance/{accepted['id']}", headers=self.headers)

        live = self.client.get("/api/v1/insurance", headers=self.headers).json()
        self.assertEqual(live["count"], 1)
        self.assertEqual(live["results"][0]["provider_name"], "Medicaid")

        not_accepted = self.client.get(
            "/api/v1/insurance?is_accepted=false", headers=self.headers
        ).json()
        self.assertEqual(not_accepted["count"], 1)
        self.assertEqual(not_accepted["results"][0]["id"], rejected["id"])

        with_deleted = self.client.get(
            "/api/v1/insurance?include_deleted=true", headers=self.headers
        ).json()
        self.assertEqual(with_deleted["count"], 2)

    def test_patch_truncates_plan_type_and_rejects_deleted(self):
        created = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Aetna"},
            content_type="application/json",
            headers=self.headers,
        ).json()
        resp = self.client.patch(
            f"/api/v1/insurance/{created['id']}",
            data={"plan_type": "P" * 80},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["plan_type"]), 50)

        self.client.delete(f"/api/v1/insurance/{created['id']}", headers=self.headers)
        gone = self.client.patch(
            f"/api/v1/insurance/{created['id']}",
            data={"plan_name": "Gold"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(gone.status_code, 404)

    def test_unicode_payer_round_trips(self):
        resp = self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Müller Kranken 健康保険", "plan_name": "Gold"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["provider_name"], "Müller Kranken 健康保険")


class InsuranceOnboardingGateTests(TestCase):
    def setUp(self):
        from apps.clinics.models import ClinicBusinessHours
        from apps.doctors.models import Doctor, DoctorSchedule
        from apps.services.models import Service

        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@ins-onboard.test", clinic_slug="ins-onboard-clinic"
        )
        self.clinic.clinic_type = "dermatology"
        self.clinic.phone = "555-0100"
        self.clinic.address = {
            "line1": "1 Main St",
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country": "US",
        }
        self.clinic.save()
        doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Test")
        Service.objects.create(clinic=self.clinic, name="Consult", duration_min=30)
        ClinicBusinessHours.objects.create(
            clinic=self.clinic, day_of_week=0, open_time="09:00", close_time="17:00"
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=doctor,
            day_of_week=0,
            start_time="09:00",
            end_time="17:00",
        )

    def test_resume_cursor_accepts_insurance_slug(self):
        resp = self.client.patch(
            "/api/v1/clinics/me",
            data={"onboarding_step": "insurance"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["onboarding_step"], "insurance")

    def test_status_counts_insurance_but_ready_without_it(self):
        status = self.client.get(
            "/api/v1/clinics/me/onboarding-status", headers=self.headers
        ).json()
        self.assertTrue(status["ready"])
        self.assertEqual(status["counts"]["insurance_plans"], 0)
        self.client.post(
            "/api/v1/insurance",
            data={"provider_name": "Aetna"},
            content_type="application/json",
            headers=self.headers,
        )
        after = self.client.get(
            "/api/v1/clinics/me/onboarding-status", headers=self.headers
        ).json()
        self.assertTrue(after["ready"])
        self.assertEqual(after["counts"]["insurance_plans"], 1)

    def test_complete_succeeds_with_zero_insurance(self):
        resp = self.client.post(
            "/api/v1/clinics/me/onboarding/complete", headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "active")


class InsuranceChatbotWithoutDoctorLinkTests(TestCase):
    """Onboarding does not create DoctorInsurance rows. Chatbot browse
    mode must still list accepted plans."""

    def setUp(self):
        from apps.insurance.services.insurance_service import create_insurance_plan

        self.user, self.clinic, self.headers = make_clinic_admin(
            email="owner@ins-chat.test", clinic_slug="ins-chat-clinic"
        )
        self.aetna = create_insurance_plan(
            clinic=self.clinic, provider_name="Aetna", plan_name="Gold", plan_type="PPO"
        )

    def test_browse_lists_plan_with_no_doctor_m2m(self):
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.insurance import insurance_accepted
        from apps.doctors.models import DoctorInsurance

        self.assertFalse(
            DoctorInsurance.objects.filter(insurance_plan=self.aetna).exists()
        )
        result = insurance_accepted(
            SQLContext(
                clinic=self.clinic,
                nlu=NLUResult(intent=Intent.INSURANCE_ACCEPTED, entities=ExtractedEntities()),
            )
        )
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["provider_name"], "Aetna")
        self.assertEqual(result.rows[0]["plan_name"], "Gold")
        self.assertEqual(result.rows[0]["plan_type"], "PPO")

    def test_named_payer_match(self):
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.insurance import insurance_accepted

        result = insurance_accepted(
            SQLContext(
                clinic=self.clinic,
                nlu=NLUResult(
                    intent=Intent.INSURANCE_ACCEPTED,
                    entities=ExtractedEntities(insurance_provider="Aetna"),
                ),
            )
        )
        self.assertTrue(result.found)
        self.assertIn("Yes", result.summary)

    def test_empty_catalog_does_not_crash(self):
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.insurance import insurance_accepted
        from apps.insurance.models import InsurancePlan

        InsurancePlan.objects.filter(clinic=self.clinic).delete()
        result = insurance_accepted(
            SQLContext(
                clinic=self.clinic,
                nlu=NLUResult(intent=Intent.INSURANCE_ACCEPTED, entities=ExtractedEntities()),
            )
        )
        self.assertFalse(result.found)
        self.assertIn("call the clinic", result.summary.lower())

    def test_browse_excludes_deleted_and_not_accepted(self):
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.insurance import insurance_accepted
        from apps.insurance.services.insurance_service import create_insurance_plan

        create_insurance_plan(
            clinic=self.clinic, provider_name="Hidden Payer", is_accepted=False
        )
        deleted = create_insurance_plan(clinic=self.clinic, provider_name="Deleted Payer")
        deleted.is_deleted = True
        deleted.save(update_fields=["is_deleted"])

        result = insurance_accepted(
            SQLContext(
                clinic=self.clinic,
                nlu=NLUResult(intent=Intent.INSURANCE_ACCEPTED, entities=ExtractedEntities()),
            )
        )
        names = {row["provider_name"] for row in result.rows}
        self.assertIn("Aetna", names)
        self.assertNotIn("Hidden Payer", names)
        self.assertNotIn("Deleted Payer", names)

    def test_named_rejected_payer_says_no(self):
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.insurance import insurance_accepted
        from apps.insurance.services.insurance_service import create_insurance_plan

        create_insurance_plan(
            clinic=self.clinic, provider_name="Medicaid", is_accepted=False
        )
        result = insurance_accepted(
            SQLContext(
                clinic=self.clinic,
                nlu=NLUResult(
                    intent=Intent.INSURANCE_ACCEPTED,
                    entities=ExtractedEntities(insurance_provider="Medicaid"),
                ),
            )
        )
        self.assertTrue(result.found)
        self.assertIn("No", result.summary)
        self.assertIn("currently don't accept", result.summary)

    def test_named_mixed_accepted_and_rejected(self):
        from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.insurance import insurance_accepted
        from apps.chatbot.sql_tool.formatter import format_sql_results
        from apps.insurance.services.insurance_service import create_insurance_plan

        self.aetna.is_accepted = False
        self.aetna.plan_name = "HMO"
        self.aetna.save(update_fields=["is_accepted", "plan_name"])
        create_insurance_plan(
            clinic=self.clinic,
            provider_name="Aetna",
            plan_name="PPO",
            is_accepted=True,
        )
        result = insurance_accepted(
            SQLContext(
                clinic=self.clinic,
                nlu=NLUResult(
                    intent=Intent.INSURANCE_ACCEPTED,
                    entities=ExtractedEntities(insurance_provider="Aetna"),
                ),
            )
        )
        self.assertTrue(result.found)
        self.assertEqual(len(result.rows), 2)
        self.assertIn("Yes", result.summary)
        self.assertIn("currently don't accept", result.summary)
        text = format_sql_results([result.to_dict()])
        self.assertNotIn("Search your plan below", text)
        self.assertIn("Yes", text)
