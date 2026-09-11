"""Tests for SQL Tool handlers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentSource, AppointmentStatus
from apps.chatbot.nlu.schemas import CatalogMatch, ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.sql_tool import SQLContext, SQLTool, format_sql_results
from apps.chatbot.sql_tool.handlers import (
    clinic_hours,
    doctor_availability,
    insurance_accepted,
    list_specialties,
    patient_appointments,
    search_doctors,
    services_offered,
)
from apps.clinics.models import Clinic, ClinicBusinessHours
from apps.doctors.models import Doctor, DoctorInsurance, DoctorSchedule, DoctorService, DoctorSpecialty
from apps.insurance.models import InsurancePlan
from apps.patients.models import Patient
from apps.services.models import Service
from apps.specialties.models import Specialty


def _nlu(
    intent: Intent,
    *,
    entities: ExtractedEntities | None = None,
    resolved: ResolvedIds | None = None,
) -> NLUResult:
    return NLUResult(
        intent=intent,
        confidence=0.9,
        entities=entities or ExtractedEntities(),
        resolved_ids=resolved or ResolvedIds(),
        needs_sql=True,
    )


class SQLToolTestBase(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="sql-tool-clinic",
            name="SQL Tool Clinic",
            email="sql@clinic.com",
            phone="+12125550000",
            address={
                "street": "1 Main St",
                "city": "Boston",
                "state": "MA",
                "zip": "02101",
            },
            timezone="America/New_York",
        )
        self.cardio = Specialty.objects.create(
            clinic=self.clinic,
            name="Cardiology",
            slug="cardiology",
        )
        Specialty.objects.create(
            clinic=self.clinic,
            name="General Practice",
            slug="general-practice",
        )
        self.consult = Service.objects.create(
            clinic=self.clinic,
            name="Consultation",
            duration_min=30,
            price_cents=20000,
        )
        self.blue = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Blue Cross",
            plan_name="PPO",
            is_accepted=True,
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Hamza Ali",
            title="MD",
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            specialty=self.cardio,
        )
        DoctorService.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            service=self.consult,
        )
        DoctorInsurance.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            insurance_plan=self.blue,
        )

        for day in range(5):
            ClinicBusinessHours.objects.create(
                clinic=self.clinic,
                day_of_week=day,
                open_time=time(8, 0),
                close_time=time(17, 0),
                is_closed=False,
            )
            DoctorSchedule.objects.create(
                clinic=self.clinic,
                doctor=self.doctor,
                day_of_week=day,
                start_time=time(9, 0),
                end_time=time(12, 0),
                slot_duration_min=30,
            )

        self.patient = Patient.objects.create(
            clinic=self.clinic,
            phone="+12125551111",
            first_name="Test",
            last_name="Patient",
        )

        tz = ZoneInfo("America/New_York")
        start = timezone.make_aware(
            datetime.combine(
                timezone.now().astimezone(tz).date() + timedelta(days=2),
                time(10, 0),
            ),
            tz,
        )
        Appointment.objects.create(
            clinic=self.clinic,
            doctor=self.doctor,
            patient=self.patient,
            service=self.consult,
            start_time=start,
            end_time=start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
            confirmation_code="SQL001",
            source=AppointmentSource.CHATBOT,
        )


class SearchDoctorsTests(SQLToolTestBase):
    def test_search_by_name(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Hamza")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["full_name"], "Dr. Hamza Ali")

    def test_search_by_specialty(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertIn("Cardiology", result.rows[0]["specialties"])

    def test_bare_symptom_resolves_to_matching_specialty(self):
        """Live-confirmed bug: a bare symptom mention (no named specialty/
        doctor) used to apply no filter at all, silently returning every
        active doctor at the clinic regardless of relevance. entities.symptom
        should resolve through the same concern->specialty matching
        suggest_specialties() already uses, same as the real NLU output for
        "am asking about the doctor related to cardiac"."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(symptom="cardiac")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["full_name"], "Dr. Hamza Ali")

    def test_bare_symptom_with_no_matching_specialty_is_honest_not_a_full_browse(self):
        """The clinic fixture has no eye/vision specialty -- must say so,
        not silently return the Cardiology/General Practice doctor as if
        vision were a good fit."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(symptom="blurry vision")),
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertIn("don't have a specialist", result.summary)

    def test_named_doctor_with_unrelated_symptom_still_searches_that_doctor(self):
        """A doctor named alongside a symptom ("does Dr Hamza treat vision
        issues") must keep searching that doctor -- the symptom mismatch
        should not silently zero out an explicit doctor-name search."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_SEARCH,
                entities=ExtractedEntities(doctor_name="Hamza", symptom="blurry vision"),
            ),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["full_name"], "Dr. Hamza Ali")

    def test_invariant_capability_question_with_no_symptom_entity_never_unfiltered_browse(self):
        """The invariant this plan is built around, tested directly: a
        capability question ("do you treat toothaches here?") with NO
        symptom entity at all (a real NLU trace shape, not a hypothetical
        -- entity extraction correctly never claims a symptom wasn't
        stated) must resolve via the concern-phrase map (Phase 1 fix,
        live-confirmed bug) to an honest decline. It must NEVER fall
        through to search_doctors's unfiltered "every doctor" browse --
        this clinic has no Dentistry specialty, so returning Dr. Hamza
        Ali (Cardiology) framed as a good fit would be exactly the
        "heart specialist" -> "here are six random doctors" failure this
        whole phase exists to close."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
            message="Do you treat tooth pain here?",
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertIn("don't have a specialist", result.summary)

    def test_invariant_catalog_match_no_match_never_unfiltered_browse(self):
        """Same invariant, exercised via the Phase 2 tier (nlu.catalog_match)
        instead of the Phase 1 concern-map tier: a validated "no_match"
        catalog_match (an explicit capability request this clinic's real
        catalog doesn't cover) must produce the same honest decline --
        never Dr. Hamza Ali handed back as if Rheumatology were a fit."""
        nlu = replace(
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
            catalog_match=CatalogMatch(status="no_match", match_type="specialty"),
        )
        ctx = SQLContext(
            clinic=self.clinic, nlu=nlu, message="Do you have a rheumatologist on staff?"
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertIn("don't have a specialist", result.summary)

    def test_invariant_catalog_match_ambiguous_never_unfiltered_browse(self):
        """An "ambiguous" catalog_match must render clarification chips --
        never a confident guess and never an unfiltered browse.

        "rheumatologist"/"immunologist" have no _CONCERN_MAP entry (unlike
        "heart", which would word-boundary-match this clinic's real
        Cardiology specialty at an earlier tier and short-circuit before
        tier 4 ever ran) -- this message is chosen so tiers 1-3 find
        nothing and the Phase 2 tier is what actually produces the chips.
        """
        nlu = replace(
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
            catalog_match=CatalogMatch(
                status="ambiguous",
                match_type="specialty",
                candidates=[
                    {"id": str(self.cardio.id), "name": "Cardiology", "match_type": "specialty"},
                    {"id": "00000000-0000-0000-0000-000000000099", "name": "Vascular Surgery", "match_type": "specialty"},
                ],
            ),
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message="Do you have a rheumatologist or immunologist on staff?",
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertIn("clarify_chips", result.meta)


class SearchDoctorsResolvedServiceIdsFallbackTests(SQLToolTestBase):
    """Live-confirmed bug (Clinic Capability Resolver Phase A investigation):
    `ctx.resolved_service_ids` (the shared per-turn message->service matcher
    already computed once by planner.py, and already consumed by
    services.py's category-mode fallback) was never read by search_doctors
    at all -- "which doctor can do teeth whitening?" resolved the exact
    right service id into `resolved_service_ids`, yet the doctor query
    stayed filtered by specialty only, returning every doctor in that
    specialty regardless of whether they actually offer the named service.
    """

    def setUp(self):
        super().setUp()
        # A second Cardiology doctor who does NOT offer Consultation --
        # proves the fix narrows by service, not merely by specialty.
        self.other_cardio_doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Priya Nair",
            title="MD",
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic,
            doctor=self.other_cardio_doctor,
            specialty=self.cardio,
        )

    def test_resolved_service_ids_narrows_an_otherwise_unfiltered_specialty_browse(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
            resolved_service_ids=[str(self.consult.id)],
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = [r["full_name"] for r in result.rows]
        self.assertEqual(names, ["Dr. Hamza Ali"])
        self.assertNotIn("Dr. Priya Nair", names)

    def test_explicit_service_id_still_takes_precedence_over_resolved_service_ids(self):
        """resolved_ids.service_id (a confident DB-resolved entity match)
        must win outright -- resolved_service_ids is a fallback for when
        nothing more specific was found, not a competing signal."""
        other_service = Service.objects.create(
            clinic=self.clinic, name="Annual Physical", duration_min=45
        )
        DoctorService.objects.create(
            clinic=self.clinic, doctor=self.other_cardio_doctor, service=other_service
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_SEARCH,
                entities=ExtractedEntities(specialty="Cardiology"),
                resolved=ResolvedIds(service_id=str(other_service.id)),
            ),
            resolved_service_ids=[str(self.consult.id)],
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = [r["full_name"] for r in result.rows]
        self.assertEqual(names, ["Dr. Priya Nair"])

    def test_no_resolved_service_ids_is_unaffected(self):
        """Regression guard: with nothing in resolved_service_ids, behavior
        is byte-for-byte the pre-fix specialty-only browse."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = {r["full_name"] for r in result.rows}
        self.assertEqual(names, {"Dr. Hamza Ali", "Dr. Priya Nair"})


class SearchDoctorsResolvedSpecialtyIdsLiveSliceTests(SQLToolTestBase):
    """Clinic Capability Resolver live vertical slice: ctx.resolved_
    specialty_ids is the planner-authorized output of
    apply_capability_resolution (a real live resolve_capability +
    decide_routing call) for a bare-concern message with no named
    specialty entity at all -- e.g. "my gums are bleeding, who should I
    see?" classified doctor_search with only entities.symptom set."""

    def setUp(self):
        super().setUp()
        self.gp = Specialty.objects.get(clinic=self.clinic, name="General Practice")
        self.gp_doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Priya Nair",
            title="MD",
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.gp_doctor, specialty=self.gp
        )

    def test_resolved_specialty_ids_filters_a_bare_symptom_message(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(symptom="gums bleeding")),
            resolved_specialty_ids=[str(self.gp.id)],
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = [r["full_name"] for r in result.rows]
        self.assertEqual(names, ["Dr. Priya Nair"])

    def test_named_specialty_entity_still_takes_precedence(self):
        """A confidently DB-resolved specialty entity is a stronger signal
        than the live resolver's concern-shaped output -- must win outright,
        mirroring the equivalent resolved_service_ids precedence test."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_SEARCH,
                entities=ExtractedEntities(specialty="Cardiology"),
                resolved=ResolvedIds(specialty_id=str(self.cardio.id)),
            ),
            resolved_specialty_ids=[str(self.gp.id)],
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = [r["full_name"] for r in result.rows]
        self.assertEqual(names, ["Dr. Hamza Ali"])

    def test_no_resolved_specialty_ids_is_unaffected(self):
        """Regression guard: with nothing in resolved_specialty_ids, a bare
        symptom falls through to the existing internal resolver chain
        exactly as before this slice existed."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(symptom="cardiac")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["full_name"], "Dr. Hamza Ali")


class HallucinatedDoctorNameZeroMatchTests(SQLToolTestBase):
    """Live-confirmed bug (Clinic Capability Resolver vertical slice):
    "which doctor handles root canals?" extracts entities.doctor_name=
    "handles root" -- a hallucinated verb-phrase fragment that survives
    _NAME_NOISE filtering (neither "handles" nor "root" is pure filler)
    but matches zero real doctors. Before this fix, `doctor_named` was set
    to True merely because *some* non-noise name text was extracted, which
    incorrectly blocked the resolved_specialty_ids fallback below it -- the
    live resolver had already correctly resolved "root canals" to
    Endodontics, but the SQL layer still reported "I couldn't find matching
    doctors for that" instead of surfacing the real Endodontics doctor."""

    def test_search_doctors_falls_through_to_resolved_specialty_when_name_matches_nobody(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_SEARCH,
                entities=ExtractedEntities(doctor_name="handles root"),
            ),
            resolved_specialty_ids=[str(self.cardio.id)],
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = [r["full_name"] for r in result.rows]
        self.assertEqual(names, ["Dr. Hamza Ali"])

    def test_doctor_availability_falls_through_to_resolved_specialty_when_name_matches_nobody(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_AVAILABILITY,
                entities=ExtractedEntities(doctor_name="handles root"),
            ),
            resolved_specialty_ids=[str(self.cardio.id)],
            message="which doctor handles root canals, are they free tomorrow?",
        )
        result = doctor_availability(ctx)
        self.assertNotIn("don't have a specialist", result.summary)

    def test_search_doctors_name_that_actually_matches_still_takes_precedence(self):
        """Regression guard: when the noise-surviving name DOES match a
        real doctor, the name filter still wins outright over
        resolved_specialty_ids -- this fix must not weaken that precedence
        for the ordinary case where NLU extracts a genuine name."""
        other_specialty = Specialty.objects.get(clinic=self.clinic, name="General Practice")
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_SEARCH,
                entities=ExtractedEntities(doctor_name="Hamza Ali"),
            ),
            resolved_specialty_ids=[str(other_specialty.id)],
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = [r["full_name"] for r in result.rows]
        self.assertEqual(names, ["Dr. Hamza Ali"])


class DoctorAvailabilityResolvedServiceIdsTests(SQLToolTestBase):
    """Live-confirmed bug, real production trace (Horizon Family Medicine &
    Urgent Care): "is there any doctor available Monday afternoon that can
    treat the stitches?" carries no specialty/symptom entity NLU can ground
    deterministically, only a capability phrase that should resolve to the
    clinic's real "Simple Wound Laceration Repair (Sutures)" service (via
    the deterministic per-turn matcher, or -- once enabled -- the Clinic
    Capability Resolver's live vertical slice) into ctx.resolved_service_ids.
    search_doctors already consults that field (see
    SearchDoctorsResolvedServiceIdsFallbackTests above); doctor_availability
    never did, so a doctor_availability-classified capability question fell
    through to browsing every active doctor's availability regardless of
    whether they actually offer the resolved service."""

    def setUp(self):
        super().setUp()
        # A second Cardiology doctor who does NOT offer Consultation --
        # proves the fix narrows by service, not merely leaving the
        # existing (absent) specialty filter's unfiltered browse in place.
        self.other_cardio_doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Priya Nair",
            title="MD",
            is_accepting_patients=True,
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic,
            doctor=self.other_cardio_doctor,
            specialty=self.cardio,
        )
        for day in range(5):
            DoctorSchedule.objects.create(
                clinic=self.clinic,
                doctor=self.other_cardio_doctor,
                day_of_week=day,
                start_time=time(9, 0),
                end_time=time(12, 0),
                slot_duration_min=30,
            )

    def test_resolved_service_ids_narrows_availability_to_doctors_who_offer_it(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities(date="Monday")),
            resolved_service_ids=[str(self.consult.id)],
            message="is there any doctor available Monday that can do a consultation",
        )
        result = doctor_availability(ctx)
        self.assertTrue(result.found)
        doctors_shown = {r.get("doctor") for r in result.rows}
        self.assertIn("Dr. Hamza Ali", doctors_shown)
        self.assertNotIn("Dr. Priya Nair", doctors_shown)

    def test_no_doctor_offers_the_resolved_service_is_an_honest_decline(self):
        """A resolved service id that genuinely matches no doctor at this
        clinic must be an honest "no matching doctors" decline -- never a
        silent fallback to showing every doctor's availability instead."""
        unlinked_service = Service.objects.create(
            clinic=self.clinic, name="Unlinked Service", duration_min=15,
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities(date="Monday")),
            resolved_service_ids=[str(unlinked_service.id)],
            message="is there any doctor available Monday for the unlinked service",
        )
        result = doctor_availability(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])

    def test_no_resolved_service_ids_is_unaffected(self):
        """Regression guard: with nothing in resolved_service_ids, an
        entity-less availability browse still returns every active doctor,
        exactly as before this fix."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities(date="Monday")),
            message="is there any doctor available Monday",
        )
        result = doctor_availability(ctx)
        self.assertTrue(result.found)
        doctors_shown = {r.get("doctor") for r in result.rows}
        self.assertIn("Dr. Hamza Ali", doctors_shown)
        self.assertIn("Dr. Priya Nair", doctors_shown)

    def test_explicit_service_id_also_narrows_availability(self):
        """The same three-tier precedence search_doctors already has
        (explicit resolved_ids.service_id wins outright) now applies to
        doctor_availability too."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_AVAILABILITY,
                entities=ExtractedEntities(date="Monday"),
                resolved=ResolvedIds(service_id=str(self.consult.id)),
            ),
            message="is there any doctor available Monday for a consultation",
        )
        result = doctor_availability(ctx)
        self.assertTrue(result.found)
        doctors_shown = {r.get("doctor") for r in result.rows}
        self.assertIn("Dr. Hamza Ali", doctors_shown)
        self.assertNotIn("Dr. Priya Nair", doctors_shown)


class SearchDoctorsLanguageTests(SQLToolTestBase):
    """Doctor.languages is catalog data (ISO 639-1 codes) — search_doctors
    must filter by *any* language present on file via the universal name/code
    table in nlu/languages.py, never a per-language routing rule. Deliberately
    uses languages absent from every other test/fixture in this session
    (Mandarin/Swahili/Urdu, not Spanish/Punjabi/Arabic) to prove genericity
    rather than re-confirming the exact examples that exposed the bug."""

    def setUp(self):
        super().setUp()
        self.doctor.languages = ["en"]
        self.doctor.save(update_fields=["languages"])
        self.mandarin_doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Li Wei",
            title="MD",
            is_accepting_patients=True,
            languages=["en", "zh"],
        )
        self.swahili_urdu_doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Amara Njeri",
            title="MD",
            is_accepting_patients=True,
            languages=["sw", "ur"],
        )

    def test_filters_by_language_name(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(language="Mandarin")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = {r["full_name"] for r in result.rows}
        self.assertEqual(names, {"Dr. Li Wei"})

    def test_filters_by_a_second_unrelated_language(self):
        """Same mechanism, different language — proves this isn't a
        Mandarin-specific path either."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(language="Urdu")),
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        names = {r["full_name"] for r in result.rows}
        self.assertEqual(names, {"Dr. Amara Njeri"})

    def test_no_doctor_speaks_requested_language(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(language="French")),
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)

    def test_no_language_entity_returns_all_doctors_unfiltered(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
        )
        result = search_doctors(ctx)
        names = {r["full_name"] for r in result.rows}
        self.assertIn("Dr. Hamza Ali", names)

    def test_unrecognized_language_word_matches_nothing_not_everything(self):
        """An unresolvable language value must never silently fall back to
        an unfiltered doctor list."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(language="Klingon")),
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)


class DoctorAvailabilityBareSymptomTests(SQLToolTestBase):
    """Same fix as SearchDoctorsTests, applied to doctor_availability --
    "is there a cardiac doctor available tomorrow" must not silently check
    every doctor's availability regardless of specialty."""

    def test_bare_symptom_resolves_to_matching_specialty(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_AVAILABILITY,
                entities=ExtractedEntities(symptom="cardiac"),
            ),
            message="is there a cardiac doctor available tomorrow",
        )
        result = doctor_availability(ctx)
        self.assertNotIn("don't have a specialist", result.summary)

    def test_bare_symptom_with_no_matching_specialty_is_honest(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_AVAILABILITY,
                entities=ExtractedEntities(symptom="blurry vision"),
            ),
            message="is there an eye doctor available tomorrow",
        )
        result = doctor_availability(ctx)
        self.assertFalse(result.found)
        self.assertIn("don't have a specialist", result.summary)

    def test_unclassifiable_symptom_asks_targeted_clarification_not_decline(self):
        """Not in _SYMPTOM_MAP and no NLU category-hint fallback -- must
        ask what kind of specialist this is, not assert one isn't offered
        (which would presume a category we never actually identified)."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_AVAILABILITY,
                entities=ExtractedEntities(symptom="a weird thing"),
            ),
            message="is there a doctor for a weird thing tomorrow",
        )
        result = doctor_availability(ctx)
        self.assertFalse(result.found)
        self.assertIn("not sure which kind of specialist", result.summary)
        self.assertNotIn("don't have a specialist", result.summary)


class DoctorAvailabilityDoesNotTruncateThePoolBeforeSearchingTests(TestCase):
    """Live-confirmed bug, real production trace (StackUp Technologies):
    "give me the first available doctor for friday" (no doctor/specialty/
    symptom entity -- the bare-browse "check every doctor" path) said "No
    available slots found on Friday" -- while the real booking wizard,
    querying the exact same DoctorSchedule data with no such cap, found a
    real 9:30 AM slot with a 6th doctor the same day. Root cause: this
    path capped the doctor pool at [:5] (borrowed from search_doctors's
    DOCTOR_LIST_CEILING listing cap) *before* checking availability --
    correct for "how many doctor cards to show," wrong for "does any slot
    exist," where checking fewer doctors than exist can only ever produce
    a false negative, never a real answer. The clinic's 6th doctor (by
    default/PK query order, not any meaningful ranking) had the only
    Friday schedule; the other 5 only worked Monday-Thursday."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="six-doctor-clinic",
            name="Six Doctor Clinic",
            email="sixdoctor@clinic.com",
            phone="+12125550040",
            timezone="America/New_York",
        )
        # First 5 doctors: Monday-Thursday only (days 0-3) -- explicitly
        # NOT Friday (day 4), and created first so they sort ahead of the
        # 6th under the default/PK query order the old [:5] slice used.
        for i in range(5):
            doc = Doctor.objects.create(
                clinic=self.clinic,
                full_name=f"Dr. Weekday {i}",
                is_accepting_patients=True,
            )
            for day in range(4):
                DoctorSchedule.objects.create(
                    clinic=self.clinic,
                    doctor=doc,
                    day_of_week=day,
                    start_time=time(9, 0),
                    end_time=time(12, 0),
                    slot_duration_min=30,
                )
        # The 6th doctor: Friday only -- the only one with real
        # availability for the date this test asks about.
        self.friday_doctor = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Friday Only", is_accepting_patients=True,
        )
        DoctorSchedule.objects.create(
            clinic=self.clinic,
            doctor=self.friday_doctor,
            day_of_week=4,
            start_time=time(9, 0),
            end_time=time(12, 0),
            slot_duration_min=30,
        )
        for day in range(5):
            ClinicBusinessHours.objects.create(
                clinic=self.clinic,
                day_of_week=day,
                open_time=time(8, 0),
                close_time=time(17, 0),
                is_closed=False,
            )

    def test_availability_search_finds_the_sixth_doctors_friday_slot(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities(date="Friday")),
            message="give me the first available doctor for friday",
        )
        result = doctor_availability(ctx)
        self.assertTrue(result.found)
        self.assertTrue(any(r.get("doctor") == "Dr. Friday Only" for r in result.rows))


class SearchDoctorsUnresolvedRoleTests(SQLToolTestBase):
    """Live-confirmed gap: a doctor_search message naming a specific role
    ("is there an eye doctor here") that the NLU extracted *no* entity for
    at all -- no specialty, no symptom (unlike DoctorAvailabilityBareSymptomTests
    above, where entities.symptom is always populated) -- silently browsed
    every active doctor instead of an honest clarification. Confirmed live
    via ChatEngine.process() that the NLU's entity extraction for an
    out-of-catalog role request is non-deterministic (sometimes grounds to
    a real category name, sometimes returns every entity null), so this
    must be handled deterministically downstream regardless of which the
    LLM does this time."""

    def test_unresolved_specific_role_gets_honest_clarification(self):
        """Updated by the Phase 1 discovery-gate fix (ROADMAP.md): "eye" is
        a real _CONCERN_MAP phrase (-> ophthalmology/optometry), and that
        map now gets a chance to run for this message even with no
        symptom entity (previously gated on entities.symptom being
        non-empty, so this message fell through to
        mentions_specific_doctor_role's vaguer "not sure which kind of
        specialist" catch-all instead of the map ever seeing it). The
        system does understand "eye doctor" -- it should say so honestly
        ("we don't have that specialist") rather than claim uncertainty
        it doesn't actually have. This is a demonstrated improvement, not
        a loosened assertion: same underlying SymptomResolution.understood
        =True/matched_ids=[] case every other honest-decline test in this
        file already exercises, just reached via a role-noun phrasing
        instead of a symptom-narrative one."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
            message="is there an eye doctor here",
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertIn("don't have a specialist", result.summary)

    def test_role_noun_absent_from_the_concern_map_still_gets_the_vaguer_clarification(self):
        """The mentions_specific_doctor_role fallback (a curated role-noun
        regex, broader than _CONCERN_MAP's phrase list) still matters for
        a role word the concern map has no entry for at all -- confirms
        that path isn't dead code after the fix above. "Podiatrist" is not
        a _CONCERN_MAP phrase (no foot/podiatry entry exists), so this
        must still fall through to the generic "not sure which kind of
        specialist" clarification, unchanged."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
            message="is there a podiatrist here",
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        self.assertIn("not sure which kind of specialist", result.summary)

    def test_generic_browse_phrasing_not_covered_by_the_role_vocabulary_still_browses(self):
        """"list your doctors" isn't in _DOCTOR_BROWSE_RE (no "which/what/
        who are/do you have" phrasing) and names no specific role either --
        must still fall through to the full roster, not a false decline."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
            message="list your doctors",
        )
        result = search_doctors(ctx)
        names = {r["full_name"] for r in result.rows}
        self.assertIn("Dr. Hamza Ali", names)

    def test_role_noun_that_does_resolve_is_unaffected(self):
        """When the NLU *does* extract the specialty (e.g. "cardiologist"
        aliasing to the real Cardiology specialty), this is an ordinary
        resolved search, not the unresolved-role path -- must not decline.
        resolved_ids.specialty_id is set explicitly here to simulate what
        nlu/resolvers.py::resolve_entities (via _match_specialty's role-
        alias fallback) would already have populated by the time a real
        request reaches this handler -- search_doctors's own raw
        entities.specialty fallback branch is plain name substring
        matching and doesn't itself understand role-noun aliases."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_SEARCH,
                entities=ExtractedEntities(specialty="cardiologist"),
                resolved=ResolvedIds(specialty_id=str(self.cardio.id)),
            ),
            message="do you have a cardiologist",
        )
        result = search_doctors(ctx)
        names = {r["full_name"] for r in result.rows}
        self.assertEqual(names, {"Dr. Hamza Ali"})

    def test_empty_message_ui_action_still_browses(self):
        """browse_doctors (the "Find a Doctor" button) calls search_doctors
        with no real message text at all and deliberately wants the full
        roster -- there's no patient wording to be ambiguous about."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities()),
        )
        result = search_doctors(ctx)
        names = {r["full_name"] for r in result.rows}
        self.assertIn("Dr. Hamza Ali", names)


class DoctorAvailabilityUnresolvedRoleTests(SQLToolTestBase):
    """Same fix as SearchDoctorsUnresolvedRoleTests, applied to
    doctor_availability -- "is there an eye doctor available tomorrow"
    must not silently check every doctor's availability."""

    def test_unresolved_specific_role_gets_honest_clarification(self):
        """Updated by the Phase 1 discovery-gate fix (ROADMAP.md) -- see
        the identical note on SearchDoctorsUnresolvedRoleTests above.
        "eye" is a real _CONCERN_MAP phrase (-> ophthalmology/optometry);
        it now resolves here too and this clinic has no match, so the
        honest, specific decline is correct."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities()),
            message="is there an eye doctor available tomorrow",
        )
        result = doctor_availability(ctx)
        self.assertFalse(result.found)
        self.assertIn("don't have a specialist", result.summary)

    def test_role_noun_absent_from_the_concern_map_still_gets_the_vaguer_clarification(self):
        """Confirms mentions_specific_doctor_role's fallback still fires
        for a role word _CONCERN_MAP has no entry for at all."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities()),
            message="is there a podiatrist available tomorrow",
        )
        result = doctor_availability(ctx)
        self.assertFalse(result.found)
        self.assertIn("not sure which kind of specialist", result.summary)

    def test_any_doctor_available_query_is_unaffected(self):
        """No specific role named -- must keep checking every doctor's
        availability exactly as before."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities()),
            message="is any doctor available tomorrow",
        )
        result = doctor_availability(ctx)
        self.assertNotIn("not sure which kind of specialist", result.summary)


class NamedSpecialtyUnresolvedFallsBackToCatalogResolutionTests(TestCase):
    """Live-confirmed bug (real production trace, StackUp Technologies --
    a dental-only clinic): "Do you have any heart specialist?" (a
    _CONCERN_MAP hint, no entities.specialty) got the honest, specific
    "We don't have a specialist for that here..." decline, but "Do you
    have any cardiology specialist?" -- the exact same question, just
    naming the specialty directly, so entities.specialty=["Cardiology"]
    was set and never resolved to a real Specialty row here -- fell
    through to a completely different, generic "I couldn't find matching
    doctors for that. Try a specialty name..." (sql_tool/formatter.py's
    EMPTY_DOCTORS). Root cause: search_doctors/doctor_availability's
    `if specs:` branch only ever ran a literal specialties__name filter
    and never delegated to the catalog-aware resolution chain
    (resolve_symptom_specialty_ids) the way the bare-symptom branch right
    next to it already did -- so an explicitly-named, unresolved
    specialty never got a chance at Phase 1/2's honest-decline machinery
    at all. Fixed by trying the literal name filter first (unchanged,
    common case) and only falling back to the resolver chain when it
    finds nothing."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="dental-only-clinic",
            name="Dental Only Clinic",
            email="dentalonly@clinic.com",
            phone="+12125550030",
            timezone="America/New_York",
        )
        for name, slug in (
            ("Cosmetic Dentistry", "cosmetic-dentistry"),
            ("General Dentistry", "general-dentistry"),
        ):
            Specialty.objects.create(clinic=self.clinic, name=name, slug=slug)
        self.dentist = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Ahmed Raza", is_accepting_patients=True,
        )

    def test_named_specialty_that_doesnt_resolve_gets_the_same_honest_decline_as_a_hint(self):
        """"Cardiology" is a specialty NAME, not a _CONCERN_MAP symptom
        PHRASE ("heart"/"chest"/"cardiac" are phrases; "cardiology"/
        "cardiologist" are only hint WORDS consulted after a phrase
        already matched) -- so the deterministic tiers alone have nothing
        to go on for this exact wording, same as the live-reproduced
        "Do you have a rheumatologist on staff?" case. The real fix here
        is Phase 2's catalog_match tier, which a real NLU call populates
        for exactly this shape of question (see nlu/prompts.py's own
        "do you have a heart specialist" example) -- set explicitly here
        since this test bypasses the real LLM call. Without the
        doctors.py fix, this tier was unreachable for this branch at all:
        `if specs:` short-circuited straight to the literal name filter
        and never consulted resolve_symptom_specialty_ids (and therefore
        never catalog_match) even when it was already populated."""
        nlu = replace(
            _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
            catalog_match=CatalogMatch(status="no_match", match_type="specialty"),
        )
        ctx = SQLContext(
            clinic=self.clinic, nlu=nlu, message="Do you have any cardiology specialist?"
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])
        # The same wording the bare-hint phrasing ("heart specialist")
        # already gets via resolve_symptom_specialty_ids -- never the
        # generic formatter.py EMPTY_DOCTORS fallback.
        self.assertIn("don't have a specialist", result.summary)
        self.assertNotIn("Try a specialty name", result.summary)

    def test_named_specialty_still_honest_decline_even_when_no_resolver_tier_has_anything(self):
        """Second live-confirmed layer of the same bug: catalog_match
        itself is non-deterministic across repeated identical real LLM
        calls (live-confirmed: 1 of 4 identical "Do you have any
        cardiology specialist?" calls came back catalog_match=
        not_applicable instead of no_match, with entities.specialty still
        correctly set to "Cardiology" every time). When that happens AND
        "cardiology" isn't a _CONCERN_MAP phrase either,
        resolve_symptom_specialty_ids legitimately returns None -- but an
        explicitly-named specialty is itself the detected constraint,
        independent of whether any resolver tier could further place it.
        This must still be the honest decline, never the generic
        "couldn't find matching doctors, try a specialty name" fallback
        -- the user already did name one."""
        nlu = _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology"))
        self.assertEqual(nlu.catalog_match.status, "not_applicable")  # the default -- not set
        ctx = SQLContext(
            clinic=self.clinic, nlu=nlu, message="Do you have any cardiology specialist?"
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertIn("don't have a specialist", result.summary)
        self.assertNotIn("Try a specialty name", result.summary)

    def test_doctor_availability_named_specialty_honest_decline_with_no_resolver_signal(self):
        nlu = _nlu(
            Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities(specialty="Cardiology")
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message="Do you have any cardiology specialist available tomorrow?",
        )
        result = doctor_availability(ctx)
        self.assertFalse(result.found)
        self.assertIn("don't have a specialist", result.summary)

    def test_named_specialty_that_does_resolve_by_name_is_unaffected(self):
        """The common case -- a literal name match must keep working
        exactly as before, unchanged by the fallback."""
        Specialty.objects.create(
            clinic=self.clinic, name="Orthodontics", slug="orthodontics",
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic,
            doctor=self.dentist,
            specialty=Specialty.objects.get(clinic=self.clinic, slug="orthodontics"),
        )
        nlu = _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Orthodontics"))
        ctx = SQLContext(
            clinic=self.clinic, nlu=nlu, message="Which doctors specialize in orthodontics?"
        )
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["full_name"], "Dr. Ahmed Raza")

    def test_doctor_availability_named_specialty_unresolved_gets_the_honest_decline(self):
        nlu = replace(
            _nlu(Intent.DOCTOR_AVAILABILITY, entities=ExtractedEntities(specialty="Cardiology")),
            catalog_match=CatalogMatch(status="no_match", match_type="specialty"),
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=nlu,
            message="Do you have any cardiology specialist available tomorrow?",
        )
        result = doctor_availability(ctx)
        self.assertFalse(result.found)
        self.assertIn("don't have a specialist", result.summary)

    def test_named_specialty_that_matches_via_concern_map_category_is_found(self):
        """The fallback isn't just for a better message -- a synonym the
        literal name filter can't see should now actually resolve, not
        just decline more politely. "Heart Center" doesn't literally
        contain "Cardiology" by name, but its category="Cardiology"
        matches the chest_pain concern-map entry's hint words once the
        message contains one of that entry's actual phrases ("heart") --
        the same mechanism that already resolves a bare "heart
        specialist" mention with no specialty entity at all. (The hint
        words "cardiology"/"cardiologist" are only ever consulted for
        NAME/category matching after a phrase like "heart" is found in
        the message -- they are not themselves phrases the concern map
        scans for.)"""
        heart_center = Specialty.objects.create(
            clinic=self.clinic, name="Heart Center", slug="heart-center", category="Cardiology",
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.dentist, specialty=heart_center,
        )
        nlu = _nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology"))
        ctx = SQLContext(clinic=self.clinic, nlu=nlu, message="Do you have a heart specialist?")
        result = search_doctors(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["full_name"], "Dr. Ahmed Raza")


class ListSpecialtiesTests(SQLToolTestBase):
    def test_lists_all_specialties(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.DOCTOR_SEARCH))
        result = list_specialties(ctx)
        self.assertTrue(result.found)
        names = {row["name"] for row in result.rows}
        self.assertIn("Cardiology", names)
        self.assertIn("General Practice", names)


class InsuranceTests(SQLToolTestBase):
    def test_insurance_by_provider(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider="Blue Cross"),
            ),
        )
        result = insurance_accepted(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["provider_name"], "Blue Cross")


class InsurancePlanTypeTests(SQLToolTestBase):
    """Phase 41: "Aetna HMO" and "Aetna PPO" used to return the identical
    row — provider matching ignored plan_type entirely, so whichever plan
    existed for that provider silently "answered" a question about a
    different type (reproduced live: both returned the HMO Plus row)."""

    def setUp(self):
        super().setUp()
        self.aetna_hmo = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Aetna",
            plan_name="HMO Plus",
            plan_type="HMO",
            is_accepted=True,
        )
        self.aetna_ppo = InsurancePlan.objects.create(
            clinic=self.clinic,
            provider_name="Aetna",
            plan_name="PPO",
            plan_type="PPO",
            is_accepted=True,
        )

    def test_hmo_question_returns_hmo_plan(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider=["Aetna HMO", "Aetna"]),
            ),
            message="Do you accept Aetna HMO?",
        )
        result = insurance_accepted(ctx)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["plan_type"], "HMO")
        self.assertIn("HMO Plus", result.summary)

    def test_ppo_question_returns_ppo_plan_not_hmo(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider=["Aetna PPO", "Aetna"]),
            ),
            message="Do you accept Aetna PPO?",
        )
        result = insurance_accepted(ctx)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["plan_type"], "PPO")
        self.assertIn("PPO", result.summary)
        self.assertNotIn("HMO Plus", result.summary)

    def test_requested_type_not_on_file_is_honest_not_silent(self):
        """A provider with only an HMO plan, asked about PPO, must say so
        — never present the HMO plan as if it answered a PPO question."""
        self.aetna_ppo.delete()
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.INSURANCE_ACCEPTED,
                entities=ExtractedEntities(insurance_provider=["Aetna PPO", "Aetna"]),
            ),
            message="Do you accept Aetna PPO?",
        )
        result = insurance_accepted(ctx)
        self.assertIn("don't see a Aetna PPO plan", result.summary)
        self.assertIn("HMO Plus", result.summary)


class ClinicHoursTests(SQLToolTestBase):
    def test_clinic_hours(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.CLINIC_HOURS))
        result = clinic_hours(ctx)
        self.assertTrue(result.found)
        self.assertEqual(len(result.rows), 5)


class ServicesTests(SQLToolTestBase):
    def test_services_offered(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.SERVICES_OFFERED))
        result = services_offered(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["name"], "Consultation")

    def test_named_search_with_no_match_says_so_specifically(self):
        """A specific ask that comes up empty against a real, non-empty
        catalog gets copy naming that — not the old undifferentiated
        "No services found." used for every empty case alike."""
        nlu = NLUResult(
            intent=Intent.SERVICES_OFFERED,
            confidence=0.9,
            entities=ExtractedEntities(service="Botox Injections"),
            resolved_ids=ResolvedIds(),
            needs_sql=True,
            service_filter_mode="named",
        )
        ctx = SQLContext(clinic=self.clinic, nlu=nlu)
        result = services_offered(ctx)
        self.assertFalse(result.found)
        self.assertIn("couldn't find a service matching that", result.summary)

    def test_invariant_capability_question_with_no_symptom_entity_never_unfiltered_browse(self):
        """Same invariant as SearchDoctorsTests, for services_offered's
        category-mode fallback: "do you do root canals?" with no service/
        symptom entity, service_filter_mode="category" (the shape a
        capability question with no literal service name gets), must
        resolve via the concern-phrase map to an honest decline -- never
        fall through to mode="category"'s unfiltered path and return
        "Consultation" as if it were a root canal."""
        nlu = NLUResult(
            intent=Intent.SERVICES_OFFERED,
            confidence=0.9,
            entities=ExtractedEntities(),
            resolved_ids=ResolvedIds(),
            needs_sql=True,
            service_filter_mode="category",
        )
        ctx = SQLContext(clinic=self.clinic, nlu=nlu, message="Can you do a root canal?")
        result = services_offered(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])

    def test_invariant_catalog_match_no_match_never_unfiltered_browse(self):
        """Same invariant, via the Phase 2 tier: a validated "no_match"
        catalog_match for a service-mode capability request must produce
        an honest decline -- never "Consultation" handed back as if it
        were laser hair removal."""
        nlu = replace(
            NLUResult(
                intent=Intent.SERVICES_OFFERED,
                confidence=0.9,
                entities=ExtractedEntities(),
                resolved_ids=ResolvedIds(),
                needs_sql=True,
                service_filter_mode="category",
            ),
            catalog_match=CatalogMatch(status="no_match", match_type="service"),
        )
        ctx = SQLContext(
            clinic=self.clinic, nlu=nlu, message="Do you offer laser hair removal?"
        )
        result = services_offered(ctx)
        self.assertFalse(result.found)
        self.assertEqual(result.rows, [])

    def test_browse_with_no_services_at_all_says_not_configured(self):
        """A filterless browse at a clinic with zero active services says
        the clinic hasn't listed any yet, not that the search missed."""
        empty_clinic = Clinic.objects.create(
            slug="no-services-clinic", name="No Services Clinic",
            email="none@clinic.com", phone="+12125550099", timezone="America/New_York",
        )
        ctx = SQLContext(clinic=empty_clinic, nlu=_nlu(Intent.SERVICES_OFFERED))
        result = services_offered(ctx)
        self.assertFalse(result.found)
        self.assertIn("hasn't listed any bookable services yet", result.summary)


class ServicesOfferedCapabilityResolverNoneModeTests(SQLToolTestBase):
    """Live-confirmed bug (Clinic Capability Resolver 2-tenant pin-point
    sweep): "can i just walk in for a minor cut or do i need to book
    something first" classifies service_filter_mode="none" (a logistics
    question, not "which service"), so services_offered's "never collapse
    an ambiguous browse to one fuzzy SKU" guard fired and showed the full
    service picker -- even though the resolver had already run for this
    exact message and confidently, validated-ly identified the one real
    service (Simple Wound Laceration Repair (Sutures), confidence 0.9).
    The planner had already authorized an answer; the handler discarded
    it. capability_resolver_used distinguishes that validated signal from
    the older, cruder message-token matcher, which must keep triggering
    the original "none" guard unchanged."""

    def setUp(self):
        super().setUp()
        self.physical = Service.objects.create(
            clinic=self.clinic, name="Annual Physical", duration_min=45, price_cents=15000
        )

    def test_resolver_validated_match_narrows_an_otherwise_unfiltered_none_mode_browse(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.SERVICES_OFFERED),
            resolved_service_ids=[str(self.consult.id)],
            capability_resolver_used=True,
        )
        result = services_offered(ctx)
        self.assertTrue(result.found)
        names = [r["name"] for r in result.rows]
        self.assertEqual(names, ["Consultation"])
        self.assertIn("Consultation is $200.00, about 30 minutes.", result.summary)

    def test_unvalidated_resolved_service_ids_still_get_the_original_none_guard(self):
        """Regression guard: the same resolved_service_ids, without
        capability_resolver_used, must not narrow the browse -- this is
        the exact signal shape the older message-token matcher produces,
        and the "none" mode guard exists specifically to not trust it."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.SERVICES_OFFERED),
            resolved_service_ids=[str(self.consult.id)],
        )
        result = services_offered(ctx)
        self.assertTrue(result.found)
        names = {r["name"] for r in result.rows}
        self.assertEqual(names, {"Consultation", "Annual Physical"})

    def test_capability_resolver_used_with_no_resolved_service_ids_is_unaffected(self):
        """Regression guard: the flag alone, with nothing resolved, must
        not change plain browse behavior."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.SERVICES_OFFERED),
            capability_resolver_used=True,
        )
        result = services_offered(ctx)
        self.assertTrue(result.found)
        names = {r["name"] for r in result.rows}
        self.assertEqual(names, {"Consultation", "Annual Physical"})


class PatientAppointmentsTests(SQLToolTestBase):
    def test_requires_patient(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.CANCEL_APPOINTMENT))
        result = patient_appointments(ctx)
        self.assertFalse(result.found)
        self.assertTrue(result.meta.get("requires_auth"))

    def test_auth_prompt_always_says_phone_never_the_clinics_general_mode(self):
        """Live-confirmed bug: this summary used to read the clinic's
        *general* verification_mode (email by default) to word itself --
        "please verify your email address" -- directly above a
        verify-identity card that actually asked for a phone number and
        texted the code, because the appointment-management OTP endpoint
        (apps/api/auth/patient_router.py::send_otp) always forces phone
        (require_existing_patient=True) regardless of that setting. A
        clinic explicitly configured for email-mode new-patient booking
        must still get the phone-worded prompt here -- this flow has
        exactly one contact method, not a clinic-configurable choice."""
        from apps.widget.models import WidgetSettings

        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"verification_mode": "email"}},
        )
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.CANCEL_APPOINTMENT))
        result = patient_appointments(ctx)
        self.assertIn("phone number", result.summary)
        self.assertNotIn("email", result.summary)

    def test_returns_upcoming(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.CANCEL_APPOINTMENT),
            patient=self.patient,
        )
        result = patient_appointments(ctx)
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["confirmation_code"], "SQL001")
        when = result.rows[0]["when"]
        self.assertRegex(when, r"\d{1,2}:\d{2} [AP]M")
        # No raw ISO datetime separator leaked through (e.g. "...T10:00...").
        # A bare "T" substring check is flaky here: the weekday abbreviation
        # itself is "Tue" or "Thu" roughly 2 days out of 7.
        self.assertNotRegex(when, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
        # The appointment card rendered alongside this text already shows
        # the date/time (appointment-card.tsx) -- this text only needs to
        # name the doctor and never leak the raw `when`/ISO value itself,
        # same de-duplication already applied to search_doctors above.
        text = format_sql_results([result.to_dict()])
        self.assertIn(result.rows[0]["doctor"], text)
        self.assertNotIn(when, text)
        self.assertNotIn("T10:00", text)


class SQLToolDispatcherTests(SQLToolTestBase):
    def test_dispatch_insurance_intent(self):
        nlu = _nlu(
            Intent.INSURANCE_ACCEPTED,
            entities=ExtractedEntities(insurance_provider="Blue Cross"),
        )
        results = SQLTool.run(self.clinic, nlu)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].handler, "insurance_accepted")
        self.assertTrue(results[0].found)

    def test_dispatch_doctor_search_runs_search_doctors(self):
        nlu = _nlu(Intent.DOCTOR_SEARCH)
        results = SQLTool.run(self.clinic, nlu)
        handlers = {r.handler for r in results}
        self.assertIn("search_doctors", handlers)
        self.assertNotIn("list_specialties", handlers)


class SQLFormatterTests(SQLToolTestBase):
    def test_format_clinic_hours(self):
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.CLINIC_HOURS))
        result = clinic_hours(ctx)
        text = format_sql_results([result.to_dict()])
        self.assertIn("we're open", text.lower())
        self.assertIn("Monday", text)

    def test_search_doctors_text_does_not_repeat_card_data(self):
        """The doctor cards below already show name/title/specialties in
        full -- the text bubble must not duplicate that (live-reported UX
        issue: a bulleted name+every-specialty list on top of the same
        cards, unreadable once a clinic has more than a couple of
        doctors). Matches the pattern insurance_accepted already uses for
        its own multi-result browse ("Search your plan below.")."""
        Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Second Doctor", is_accepting_patients=True
        )
        ctx = SQLContext(clinic=self.clinic, nlu=_nlu(Intent.DOCTOR_SEARCH))
        result = search_doctors(ctx)
        self.assertGreaterEqual(len(result.rows), 2)
        text = format_sql_results([result.to_dict()])
        self.assertNotIn(self.doctor.full_name, text)
        self.assertNotIn("Cardiology", text)

    def test_search_doctors_text_single_result_still_names_the_doctor(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(doctor_name="Hamza")),
        )
        result = search_doctors(ctx)
        text = format_sql_results([result.to_dict()])
        self.assertIn(self.doctor.full_name, text)


class SearchDoctorsInformationalServiceCandidatesTests(SQLToolTestBase):
    """Live-confirmed gap (Clinic Capability Resolver): "my smile looks
    dull and yellow, is there a quick fix" correctly resolved both a
    specialty (drove the doctor filter) and a real, relevant service
    candidate -- capability_routing_policy.py's own rule is that a
    concern's service candidate must only ever be informational, never a
    silent filter. That candidate was computed, logged in
    capability_resolver_live, and then discarded outright -- the final
    reply never mentioned it at all, just a bare doctor list."""

    def test_real_candidate_is_named_alongside_the_doctor_list(self):
        Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Second Doctor", is_accepting_patients=True
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
            informational_service_candidates=[str(self.consult.id)],
        )
        result = search_doctors(ctx)
        self.assertIn("informational_services", result.meta)
        self.assertEqual(result.meta["informational_services"], ["Consultation"])
        text = format_sql_results([result.to_dict()])
        self.assertIn("You might also ask about: Consultation.", text)

    def test_no_candidates_is_unaffected(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
        )
        result = search_doctors(ctx)
        self.assertNotIn("informational_services", result.meta)
        text = format_sql_results([result.to_dict()])
        self.assertNotIn("You might also ask about", text)

    def test_fabricated_id_never_reaches_the_reply(self):
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
            informational_service_candidates=["00000000-0000-0000-0000-000000000000"],
        )
        result = search_doctors(ctx)
        self.assertNotIn("informational_services", result.meta)
        text = format_sql_results([result.to_dict()])
        self.assertNotIn("You might also ask about", text)

    def test_inactive_service_id_never_reaches_the_reply(self):
        inactive = Service.objects.create(
            clinic=self.clinic, name="Discontinued Service", is_active=False
        )
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(Intent.DOCTOR_SEARCH, entities=ExtractedEntities(specialty="Cardiology")),
            informational_service_candidates=[str(inactive.id)],
        )
        result = search_doctors(ctx)
        self.assertNotIn("informational_services", result.meta)

    def test_no_doctors_found_is_unaffected(self):
        """A candidate must never be the reason a "no doctors found"
        result looks like it found something."""
        ctx = SQLContext(
            clinic=self.clinic,
            nlu=_nlu(
                Intent.DOCTOR_SEARCH,
                resolved=ResolvedIds(doctor_id="00000000-0000-0000-0000-000000000000"),
            ),
            informational_service_candidates=[str(self.consult.id)],
        )
        result = search_doctors(ctx)
        self.assertFalse(result.found)
        self.assertNotIn("informational_services", result.meta)
