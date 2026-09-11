"""nlu/resolvers.py: consolidated doctor-name resolution + service->specialty resolution."""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.nlu.resolvers import (
    resolve_catalog_match,
    resolve_doctor_candidates,
    resolve_doctor_from_text,
    resolve_entities,
    resolve_pediatric_service_fallback,
    resolve_specialty_for_service,
)
from apps.chatbot.nlu.schemas import CatalogMatch, ExtractedEntities
from apps.chatbot.routing import (
    build_doctor_catalog,
    build_specialty_catalog,
    catalog_for_catalog_match_context,
)
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorService, DoctorSpecialty
from apps.services.models import Service
from apps.specialties.models import Specialty


class ResolveDoctorFromTextTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="resolver-clinic",
            name="Resolver Clinic",
            email="resolver@clinic.com",
            phone="+12125550000",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Rajat Sharma",
            title="MD",
            is_active=True,
        )

    def test_exact_full_name_match(self):
        result = resolve_doctor_from_text(self.clinic, "Book with Dr. Rajat Sharma please")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))

    def test_last_name_match(self):
        result = resolve_doctor_from_text(self.clinic, "Can I see Sharma on Friday?")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))

    def test_typo_tolerance_fuzzy_fallback(self):
        result = resolve_doctor_from_text(self.clinic, "book with dr rajet sharme")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))

    def test_unrelated_text_does_not_match(self):
        result = resolve_doctor_from_text(self.clinic, "what insurance do you accept")
        self.assertIsNone(result)

    def test_empty_text_returns_none(self):
        self.assertIsNone(resolve_doctor_from_text(self.clinic, ""))
        self.assertIsNone(resolve_doctor_from_text(self.clinic, None))


class FuzzyMatchShortWordCollisionTests(TestCase):
    """Phase 40: a real, long eHealthForum patient narrative ("...i had
    explained to the dr...") fuzzy-matched the common word "had" against a
    real clinic doctor's surname "Haddad" at 0.725 — a "did you mean Dr.
    Omar Haddad?" prompt on a message that named no doctor at all. Root
    cause: _fuzzy_score's substring-match branch had no minimum length on
    the shorter string, so a 3-letter common word being a literal prefix of
    a much longer surname scored almost as high as a genuine partial name.
    """

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="haddad-collision-clinic",
            name="Haddad Collision Clinic",
            email="haddad@clinic.com",
            phone="+12125550001",
            timezone="America/New_York",
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Omar Haddad",
            title="MD",
            is_active=True,
        )

    def test_long_narrative_with_had_does_not_suggest_haddad(self):
        text = (
            "i have a large hard knot beneath the skin of my left cheek. "
            "the following day i went to an er due to more aggressive "
            "facial swelling. the dr there gave me a cat scan. at this "
            "point i had explained to the dr that none of my teeth were "
            "bothering me in any way. what could be causing this knot"
        )
        resolution = resolve_doctor_candidates(self.clinic, text)
        self.assertNotEqual(resolution.status, "clarify")
        self.assertIsNone(resolve_doctor_from_text(self.clinic, text))

    def test_short_partial_name_still_resolves(self):
        # "Sharma"-style short-but-genuine last names must still work —
        # the fix only excludes matches below the length floor.
        result = resolve_doctor_from_text(self.clinic, "book with dr haddad please")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], str(self.doctor.id))


class ResolveSpecialtyForServiceTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="specialty-resolver-clinic",
            name="Specialty Resolver Clinic",
            email="spec@clinic.com",
            phone="+12125550001",
            timezone="America/New_York",
        )
        self.aesthetics = Specialty.objects.create(
            clinic=self.clinic, name="Aesthetics", slug="aesthetics"
        )
        self.dermatology = Specialty.objects.create(
            clinic=self.clinic, name="Dermatology", slug="dermatology"
        )
        self.botox = Service.objects.create(
            clinic=self.clinic, name="Botox", duration_min=30, price_cents=50000
        )

    def test_resolves_via_doctor_specialty_relation(self):
        doctor = Doctor.objects.create(clinic=self.clinic, full_name="Dr. Aesthetic One")
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=doctor, specialty=self.aesthetics
        )
        DoctorService.objects.create(clinic=self.clinic, doctor=doctor, service=self.botox)

        specialty_id = resolve_specialty_for_service(self.clinic, str(self.botox.id))
        self.assertEqual(specialty_id, str(self.aesthetics.id))

    def test_picks_specialty_with_most_doctors_performing_service(self):
        one_aesthetic = Doctor.objects.create(clinic=self.clinic, full_name="Dr. A")
        two_derm = Doctor.objects.create(clinic=self.clinic, full_name="Dr. B")
        three_derm = Doctor.objects.create(clinic=self.clinic, full_name="Dr. C")
        for doc in (one_aesthetic, two_derm, three_derm):
            DoctorService.objects.create(clinic=self.clinic, doctor=doc, service=self.botox)
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=one_aesthetic, specialty=self.aesthetics
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=two_derm, specialty=self.dermatology
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=three_derm, specialty=self.dermatology
        )

        specialty_id = resolve_specialty_for_service(self.clinic, str(self.botox.id))
        self.assertEqual(specialty_id, str(self.dermatology.id))

    def test_no_doctors_performing_service_returns_none(self):
        self.assertIsNone(resolve_specialty_for_service(self.clinic, str(self.botox.id)))

    def test_none_service_id_returns_none(self):
        self.assertIsNone(resolve_specialty_for_service(self.clinic, None))


class MatchSpecialtyByCategoryTests(TestCase):
    """Live-confirmed gap, found while verifying the care-concern
    quick-reply chips end to end: _match_specialty only ever checked
    Specialty.name/slug (icontains, then fuzzy) -- never the canonical
    core.care_categories.CareCategory tag. A clinic naming its specialty
    something that doesn't literally contain the category word ("Heart
    Center" tagged category="Cardiology") meant a direct category mention
    ("I think it's related to Cardiology" -- exactly what
    apps/chatbot/booking/discovery.py::ambiguous_category_chips's tapped
    chip sends) resolved to no specialty at all, even though the clinic
    plainly has one."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="category-specialty-match-clinic",
            name="Category Specialty Match Clinic",
            email="categoryspecialtymatch@clinic.com",
            phone="+12125550018",
            timezone="America/New_York",
        )
        self.heart_center = Specialty.objects.create(
            clinic=self.clinic, name="Heart Center", slug="heart-center",
            category="Cardiology",
        )

    def test_category_name_resolves_via_category_tag(self):
        resolved = resolve_entities(self.clinic, ExtractedEntities(specialty="Cardiology"))
        self.assertEqual(resolved.specialty_id, str(self.heart_center.id))

    def test_role_noun_alias_still_resolves_via_category(self):
        resolved = resolve_entities(self.clinic, ExtractedEntities(specialty="cardiologist"))
        self.assertEqual(resolved.specialty_id, str(self.heart_center.id))

    def test_name_match_still_takes_priority_over_category(self):
        """When a specialty's own name already matches, that must win --
        the category check is only a fallback for when name/slug matching
        finds nothing."""
        Specialty.objects.create(
            clinic=self.clinic, name="Cardiology Wing", slug="cardiology-wing",
            category="Other",
        )
        resolved = resolve_entities(self.clinic, ExtractedEntities(specialty="Cardiology"))
        specialty = Specialty.objects.get(id=resolved.specialty_id)
        self.assertEqual(specialty.name, "Cardiology Wing")

    def test_unrelated_category_does_not_match(self):
        resolved = resolve_entities(self.clinic, ExtractedEntities(specialty="Dermatology"))
        self.assertIsNone(resolved.specialty_id)

    def test_dentist_role_noun_resolves_via_shared_alias(self):
        """DOCTOR_ROLE_ALIASES (routing/signals.py) is shared between this
        resolver and mentions_specific_doctor_role -- "dentist" was added
        alongside the "is there an eye doctor" fix (found while chasing
        the same class of unresolved-role gap) so a clinic whose specialty
        isn't literally named "Dentistry" still resolves a direct
        "dentist" mention."""
        dentistry = Specialty.objects.create(
            clinic=self.clinic, name="Smile Studio", slug="smile-studio",
            category="Dentistry",
        )
        resolved = resolve_entities(self.clinic, ExtractedEntities(specialty="dentist"))
        self.assertEqual(resolved.specialty_id, str(dentistry.id))


class DoctorCatalogTests(TestCase):
    """Phase 41: the Small LLM had no doctor roster in its prompt at all —
    root cause of "Tell me about Priya and Omar" extracting patient_name
    instead of doctor_name and misclassifying off_topic (reproduced live).
    """

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="catalog-clinic",
            name="Catalog Clinic",
            email="catalog@clinic.com",
            phone="+12125550002",
            timezone="America/New_York",
        )
        self.specialty = Specialty.objects.create(clinic=self.clinic, name="Pediatrics")
        self.doctor = Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Test Doe", is_active=True
        )
        DoctorSpecialty.objects.create(
            clinic=self.clinic, doctor=self.doctor, specialty=self.specialty
        )
        Doctor.objects.create(
            clinic=self.clinic, full_name="Dr. Inactive", is_active=False
        )

    def test_includes_active_doctors_with_specialty(self):
        catalog = build_doctor_catalog(self.clinic)
        names = {d["full_name"]: d["specialty"] for d in catalog}
        self.assertEqual(names.get("Dr. Test Doe"), "Pediatrics")

    def test_excludes_inactive_doctors(self):
        catalog = build_doctor_catalog(self.clinic)
        names = [d["full_name"] for d in catalog]
        self.assertNotIn("Dr. Inactive", names)


class PediatricServiceFallbackTests(TestCase):
    """Phase 41: a deterministic backstop for "which doctors can see
    children" when the Small LLM doesn't map it to the real service (a
    measured, not hypothetical, reliability gap — never the primary
    mechanism, since the LLM gets it right most of the time)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="pediatric-fallback-clinic",
            name="Pediatric Fallback Clinic",
            email="pedfallback@clinic.com",
            phone="+12125550003",
            timezone="America/New_York",
        )
        self.pediatric_service = Service.objects.create(
            clinic=self.clinic, name="Pediatric Well-Child Exam"
        )

    def test_matches_age_group_language(self):
        for text in (
            "Which doctors can see children?",
            "Which doctors can see my child?",
            "Do you have anyone who treats kids?",
            "Who provides pediatric care for infants?",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    resolve_pediatric_service_fallback(self.clinic, text),
                    str(self.pediatric_service.id),
                )

    def test_no_match_without_age_group_language(self):
        self.assertIsNone(
            resolve_pediatric_service_fallback(self.clinic, "Do you have any doctors?")
        )

    def test_no_pediatric_service_returns_none(self):
        self.pediatric_service.delete()
        self.assertIsNone(
            resolve_pediatric_service_fallback(self.clinic, "Which doctors can see children?")
        )


class ResolveCatalogMatchTests(TestCase):
    """Phase 2 of the catalog-matching plan (ROADMAP.md): the one place an
    LLM-proposed CatalogMatch.catalog_id/candidates is checked against
    real data. LLM confidence must never be treated as truth -- every case
    here is about what happens to a *claimed* match once it's checked."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="catalog-match-clinic",
            name="Catalog Match Clinic",
            email="catalogmatch@clinic.com",
            phone="+12125550020",
            timezone="America/New_York",
        )
        self.other_clinic = Clinic.objects.create(
            slug="catalog-match-other-clinic",
            name="Other Clinic",
            email="othercatalogmatch@clinic.com",
            phone="+12125550021",
            timezone="America/New_York",
        )
        self.cardiology = Specialty.objects.create(
            clinic=self.clinic, name="Cardiology", slug="cardiology",
        )
        self.dermatology = Specialty.objects.create(
            clinic=self.clinic, name="Dermatology", slug="dermatology",
        )
        self.inactive_specialty = Specialty.objects.create(
            clinic=self.clinic, name="Retired Specialty", slug="retired-specialty",
            is_active=False,
        )
        self.deleted_specialty = Specialty.objects.create(
            clinic=self.clinic, name="Deleted Specialty", slug="deleted-specialty",
            is_deleted=True,
        )
        self.other_clinic_specialty = Specialty.objects.create(
            clinic=self.other_clinic, name="Cardiology", slug="cardiology",
        )
        self.root_canal = Service.objects.create(
            clinic=self.clinic, name="Root Canal", duration_min=60, price_cents=80000,
        )

    def test_not_applicable_and_no_match_pass_through_unvalidated(self):
        for status in ("not_applicable", "no_match", "unresolved"):
            with self.subTest(status=status):
                raw = CatalogMatch(status=status, match_type="specialty")
                result = resolve_catalog_match(self.clinic, raw)
                self.assertEqual(result.status, status)
                self.assertIsNone(result.catalog_id)

    def test_matched_real_tenant_active_id_is_trusted(self):
        raw = CatalogMatch(
            status="matched", match_type="specialty", catalog_id=str(self.cardiology.id)
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.catalog_id, str(self.cardiology.id))

    def test_matched_service_id_is_trusted(self):
        raw = CatalogMatch(
            status="matched", match_type="service", catalog_id=str(self.root_canal.id)
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.catalog_id, str(self.root_canal.id))

    def test_matched_hallucinated_id_is_downgraded_to_unresolved(self):
        """An id that doesn't exist at all -- the LLM must never be
        trusted just because it claimed high confidence."""
        raw = CatalogMatch(
            status="matched", match_type="specialty", catalog_id="00000000-0000-0000-0000-000000000000"
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "unresolved")
        self.assertIsNone(result.catalog_id)

    def test_matched_wrong_tenant_id_is_downgraded_to_unresolved(self):
        """A real, active Specialty row -- but it belongs to a different
        clinic. The tenant boundary is a real DB filter, never inferred
        from "the prompt only offered this clinic's ids"."""
        raw = CatalogMatch(
            status="matched",
            match_type="specialty",
            catalog_id=str(self.other_clinic_specialty.id),
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "unresolved")
        self.assertIsNone(result.catalog_id)

    def test_matched_inactive_id_is_downgraded_to_unresolved(self):
        raw = CatalogMatch(
            status="matched", match_type="specialty", catalog_id=str(self.inactive_specialty.id)
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "unresolved")

    def test_matched_deleted_id_is_downgraded_to_unresolved(self):
        raw = CatalogMatch(
            status="matched", match_type="specialty", catalog_id=str(self.deleted_specialty.id)
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "unresolved")

    def test_matched_wrong_catalog_type_is_downgraded_to_unresolved(self):
        """A real, active, this-tenant id -- but it's a Service id claimed
        as match_type=specialty. The type must match the model actually
        queried, not just "some real id.\""""
        raw = CatalogMatch(
            status="matched", match_type="specialty", catalog_id=str(self.root_canal.id)
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "unresolved")

    def test_ambiguous_two_valid_candidates_stays_ambiguous_with_real_names(self):
        raw = CatalogMatch(
            status="ambiguous",
            match_type="specialty",
            candidates=[
                {"id": str(self.cardiology.id), "match_type": "specialty"},
                {"id": str(self.dermatology.id), "match_type": "specialty"},
            ],
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "ambiguous")
        names = {c["name"] for c in result.candidates}
        self.assertEqual(names, {"Cardiology", "Dermatology"})

    def test_ambiguous_with_one_hallucinated_candidate_drops_it_not_the_real_one(self):
        raw = CatalogMatch(
            status="ambiguous",
            match_type="specialty",
            candidates=[
                {"id": str(self.cardiology.id), "match_type": "specialty"},
                {"id": "00000000-0000-0000-0000-000000000000", "match_type": "specialty"},
            ],
        )
        result = resolve_catalog_match(self.clinic, raw)
        # Only one candidate survived validation -- this is a match now,
        # not a real ambiguity anymore.
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.catalog_id, str(self.cardiology.id))

    def test_ambiguous_with_zero_valid_candidates_is_downgraded_to_unresolved(self):
        raw = CatalogMatch(
            status="ambiguous",
            match_type="specialty",
            candidates=[
                {"id": "00000000-0000-0000-0000-000000000000", "match_type": "specialty"},
                {"id": "11111111-1111-1111-1111-111111111111", "match_type": "specialty"},
            ],
        )
        result = resolve_catalog_match(self.clinic, raw)
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.candidates, [])


class CatalogMatchContextBuilderTests(TestCase):
    """build_specialty_catalog + catalog_for_catalog_match_context -- the
    id-tagged Catalog: block the Phase 2 NLU prompt reads from
    (nlu/prompts.py). Real ids only, active/non-deleted only, and the
    documented 50-row combined-size tripwire (ROADMAP.md's Phase 2 entry:
    a temporary implementation threshold, not an architectural ceiling)."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="catalog-context-clinic",
            name="Catalog Context Clinic",
            email="catalogcontext@clinic.com",
            phone="+12125550023",
            timezone="America/New_York",
        )

    def test_build_specialty_catalog_excludes_inactive_and_deleted(self):
        active = Specialty.objects.create(
            clinic=self.clinic, name="Cardiology", slug="cardiology"
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Retired", slug="retired", is_active=False
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Deleted", slug="deleted", is_deleted=True
        )
        catalog = build_specialty_catalog(self.clinic)
        self.assertEqual(catalog, [{"id": str(active.id), "name": "Cardiology"}])

    def test_context_block_empty_when_nothing_to_show(self):
        self.assertEqual(catalog_for_catalog_match_context([], []), "")

    def test_context_block_renders_id_tagged_lines(self):
        block = catalog_for_catalog_match_context(
            [{"id": "spec-1", "name": "Cardiology"}],
            [{"id": "svc-1", "name": "Root Canal"}],
        )
        self.assertIn("[specialty] id=spec-1 name=Cardiology", block)
        self.assertIn("[service] id=svc-1 name=Root Canal", block)

    def test_combined_over_threshold_is_truncated_not_dropped(self):
        specialties = [{"id": f"spec-{i}", "name": f"Specialty {i}"} for i in range(40)]
        services = [{"id": f"svc-{i}", "name": f"Service {i}"} for i in range(40)]
        block = catalog_for_catalog_match_context(specialties, services, size_threshold=50)
        lines = block.split("\n")
        self.assertEqual(len(lines), 50)
        # Still real, correctly-tagged lines -- a truncated list, not
        # dropped or malformed ones.
        self.assertTrue(all(l.startswith("[specialty]") or l.startswith("[service]") for l in lines))

    def test_combined_under_threshold_is_not_truncated(self):
        specialties = [{"id": f"spec-{i}", "name": f"Specialty {i}"} for i in range(10)]
        services = [{"id": f"svc-{i}", "name": f"Service {i}"} for i in range(10)]
        block = catalog_for_catalog_match_context(specialties, services, size_threshold=50)
        self.assertEqual(len(block.split("\n")), 20)
