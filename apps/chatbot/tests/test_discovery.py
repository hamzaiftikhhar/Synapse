"""Tests for booking/discovery.py's specialty-suggestion matching.

Covers the fix for a live-confirmed bug: when nothing in the message
matched the symptom-keyword table, suggest_specialties() silently
substituted "clinic_specs[:limit]" (whichever specialties sorted first)
instead of returning no suggestion — so e.g. "I need a Cardiology and
Vascular doctor" at a clinic with no cardiology specialty got back
unrelated specialties framed as "may help."
"""

from __future__ import annotations

from django.test import TestCase

from apps.chatbot.booking.discovery import (
    _plain_label,
    resolve_symptom_service_ids,
    resolve_symptom_specialty_ids,
    suggest_specialties,
)
from apps.chatbot.engine import ChatEngine
from apps.chatbot.nlu.schemas import parse_nlu_payload
from apps.clinics.models import Clinic
from apps.services.models import Service
from apps.specialties.models import Specialty


class SuggestSpecialtiesNoMatchTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="discovery-clinic",
            name="Discovery Clinic",
            email="discovery@clinic.com",
            phone="+12125550002",
            address={"street": "3 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        # None of these are in _SYMPTOM_MAP's hint lists (which target
        # generic specialty categories like "cardiology"/"neurology"/
        # "primary care", not compound brand-style names) and none of the
        # keywords below appear anywhere in their names.
        self.zzz = Specialty.objects.create(
            clinic=self.clinic, name="Zzyzx Regenerative Medicine", slug="zzyzx"
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Aardvark Sports Recovery", slug="aardvark"
        )

    def test_no_keyword_match_returns_no_suggestions_not_first_in_list(self):
        suggested, guidance = suggest_specialties(
            self.clinic, message="I need a Cardiology and Vascular doctor"
        )
        self.assertEqual(suggested, [])
        self.assertNotIn("Zzyzx", guidance)
        self.assertNotIn("Aardvark", guidance)

    def test_keyword_match_still_works(self):
        migraine_specialty = Specialty.objects.create(
            clinic=self.clinic, name="Neurology", slug="neurology"
        )
        suggested, guidance = suggest_specialties(self.clinic, message="I have a migraine")
        names = [s["name"] for s in suggested]
        self.assertIn(migraine_specialty.name, names)
        self.assertIn(migraine_specialty.name, guidance)


class DentalVocabularyTests(TestCase):
    """Live-confirmed gap: _SYMPTOM_MAP had zero dental keywords, written
    for a general/multi-specialty medical clinic's vocabulary. At a
    dental-only clinic, real patient language ("give me teh tooth doctor",
    "I want to remove hte root canal") matched nothing, and -- once
    search_doctors/doctor_availability correctly started being honest about
    empty matches -- wrongly told a dental clinic's own patients it had no
    specialist for dental things. Verified against a StackUp-Technologies-
    shaped fixture (dental-only specialties) with the 30-query set from
    ROADMAP.md's investigation report, not just one example."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="dental-vocab-clinic",
            name="Dental Vocabulary Clinic",
            email="dentalvocab@clinic.com",
            phone="+12125550006",
            address={"street": "7 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.general = Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry"
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Restorative Dentistry", slug="restorative-dentistry"
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Cosmetic Dentistry", slug="cosmetic-dentistry"
        )

    def test_dental_symptom_language_matches_dentistry(self):
        for msg in (
            "I have a toothache",
            "my wisdom tooth hurts",
            "I need my tooth extracted",
            "my gums are bleeding",
            "I broke a tooth",
            "I need braces",
            "my crown fell off",
            "my tooth has been hurting since yesterday",
            "who should I see for a broken tooth",
            "I need someone for my gums",
        ):
            with self.subTest(msg=msg):
                suggested, _ = suggest_specialties(self.clinic, message=msg)
                names = [s["name"] for s in suggested]
                self.assertTrue(names, f"expected a dentistry match for: {msg!r}")

    def test_common_dental_typos_still_match(self):
        for msg in ("i got a toothace", "wisdon tooth removal"):
            with self.subTest(msg=msg):
                suggested, _ = suggest_specialties(self.clinic, message=msg)
                self.assertTrue([s["name"] for s in suggested])

    def test_non_dental_specialties_still_correctly_do_not_match(self):
        """The new dental group must not become a catch-all -- a genuinely
        unrelated specialty request still gets no suggestion at a
        dental-only clinic."""
        for msg in (
            "is there a cardiologist here",
            "can I see a dermatologist",
            "who treats migraines",
            "I need a psychiatrist",
            "do you have an OB-GYN",
            "is there a neurologist here",
        ):
            with self.subTest(msg=msg):
                suggested, _ = suggest_specialties(self.clinic, message=msg)
                self.assertEqual(suggested, [])

    def test_cross_domain_terms_do_not_leak_into_dentistry(self):
        """A dental clinic must not falsely claim relevance for clearly
        non-dental niches either -- the database (no such specialty here)
        stays authoritative regardless of the new keyword group."""
        for msg in ("do you offer botox", "can I get a mole checked", "whats my A1C"):
            with self.subTest(msg=msg):
                suggested, _ = suggest_specialties(self.clinic, message=msg)
                self.assertEqual(suggested, [])

    def test_ambiguous_messages_still_get_no_suggestion(self):
        for msg in ("I am in pain", "something is wrong", "I need help"):
            with self.subTest(msg=msg):
                suggested, _ = suggest_specialties(self.clinic, message=msg)
                self.assertEqual(suggested, [])


class PlainLabelWordBoundaryTests(TestCase):
    """Live-confirmed bug: naive substring containment made the "ent" (ENT/
    otolaryngology) mapping key match inside "dentistry" — every specialty
    at a real dental clinic ("Cosmetic Dentistry", "General Dentistry",
    "Restorative Dentistry") collapsed to "Ear, Nose & Throat Doctor" when
    suggested for a symptom ("I want to see a doctor about my heart" showed
    "these areas may help: Ear, Nose & Throat Doctor" three times over).
    Same class of bug already fixed once in response_templates.py's
    off-topic keyword lists ("trip" inside "strip") — same word-boundary
    fix applied here."""

    def test_dentistry_specialties_are_not_mapped_to_ent(self):
        for name in ["Cosmetic Dentistry", "General Dentistry", "Restorative Dentistry"]:
            with self.subTest(name=name):
                self.assertEqual(_plain_label(name), name)

    def test_real_ent_specialty_still_maps_correctly(self):
        self.assertEqual(_plain_label("ENT"), "Ear, Nose & Throat Doctor")
        self.assertEqual(_plain_label("Otolaryngology (ENT)"), "Ear, Nose & Throat Doctor")

    def test_unmapped_name_passes_through_unchanged(self):
        self.assertEqual(_plain_label("Podiatry"), "Podiatry")


class SoftMedicalReplyHonestFallbackTests(TestCase):
    """Exercises the real ChatEngine._soft_medical_reply method (not a
    mock) end to end against real Specialty rows -- the actual code path
    a patient's message reaches, not just the discovery function alone."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="soft-medical-clinic",
            name="Soft Medical Clinic",
            email="softmed@clinic.com",
            phone="+12125550003",
            address={"street": "4 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Zzyzx Regenerative Medicine", slug="zzyzx"
        )

    def test_unmatched_specialty_name_gets_honest_generic_reply(self):
        reply = ChatEngine()._soft_medical_reply(
            self.clinic, "I need a Cardiology and Vascular doctor"
        )
        self.assertNotIn("these areas may help", reply)
        self.assertNotIn("Zzyzx", reply)
        self.assertIn("find a doctor", reply.lower())


class SoftMedicalAmbiguityBlockTests(TestCase):
    """Live-confirmed gap: a bare concern description ("chest and stomach
    pain") is classified medical_question -> the soft_medical direct-reply
    lane (ChatEngine._soft_medical_reply) far more often than doctor_search
    -- confirmed via a live ChatEngine.process() run against a real seeded
    clinic during this phase's own verification. Without
    _soft_medical_ambiguity_block wired into that lane, the MEDIUM-tier
    quick-reply clarification built into resolve_symptom_specialty_ids
    would almost never actually be reached in practice, since
    suggest_specialties (which _soft_medical_reply calls) silently combines
    multiple ambiguous categories into one guidance sentence instead of
    asking."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="soft-medical-ambiguity-clinic",
            name="Soft Medical Ambiguity Clinic",
            email="softmedicalambiguity@clinic.com",
            phone="+12125550019",
            address={"street": "19 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Heart Center", slug="heart-center", category="Cardiology",
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Digestive Health", slug="digestive-health",
            category="Gastroenterology",
        )

    def test_ambiguous_concern_returns_a_clarify_block_with_chips(self):
        block = ChatEngine()._soft_medical_ambiguity_block(self.clinic, "chest and stomach pain")
        self.assertIsNotNone(block)
        self.assertEqual(block["found"], False)
        chips = block["meta"]["clarify_chips"]
        self.assertEqual({c["label"] for c in chips}, {"Cardiology", "Gastroenterology"})
        self.assertIn("Which one fits best", block["summary"])

    def test_unambiguous_concern_returns_none(self):
        block = ChatEngine()._soft_medical_ambiguity_block(self.clinic, "my chest hurts")
        self.assertIsNone(block)

    def test_bare_pain_returns_none(self):
        block = ChatEngine()._soft_medical_ambiguity_block(self.clinic, "I have pain")
        self.assertIsNone(block)


class SpecialtyHintWordBoundaryTests(TestCase):
    """Live-confirmed bug, second class: the specialty-hint side of
    suggest_specialties() also matched via naive substring containment
    (`h in name_l`) -- a symptom hint like "ent" (for ear/nose/throat
    complaints) matched inside an unrelated clinic-authored specialty name
    like "General Dentistry", exactly the same bug class as _plain_label's
    "ent" inside "dentistry". Verified live: a dental-only clinic got
    "General Dentistry" suggested for "my ear hurts" before this fix."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="dental-hint-clinic",
            name="Dental Hint Clinic",
            email="dentalhint@clinic.com",
            phone="+12125550004",
            address={"street": "5 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.dentistry = Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry"
        )

    def test_ear_hint_does_not_match_dentistry(self):
        suggested, _ = suggest_specialties(self.clinic, message="my ear hurts")
        self.assertEqual(suggested, [])

    def test_real_ent_specialty_still_matches(self):
        Specialty.objects.create(
            clinic=self.clinic, name="Otolaryngology (ENT)", slug="ent"
        )
        suggested, _ = suggest_specialties(self.clinic, message="my ear hurts")
        names = [s["name"] for s in suggested]
        self.assertIn("Otolaryngology (ENT)", names)
        self.assertNotIn(self.dentistry.name, names)


class SymptomEntityWiringTests(TestCase):
    """The NLU already extracts an entities.symptom value every turn
    (engine.py's nlu_result.entities.symptom), but suggest_specialties()
    used to only ever see the raw message string, re-deriving its own,
    sometimes-worse signal via _SYMPTOM_MAP's own substring matching. A
    real production trace showed the model's own reasoning recognizing
    "fracture" in "i want to book and boone fracture thing" while still
    emitting entities.symptom: null (a prompt gap, fixed separately in
    nlu/prompts.py) -- this test covers the engine-side half: once NLU
    does supply a symptom value, it must actually reach
    suggest_specialties() via the `reason` kwarg, not be dropped on the
    floor by _soft_medical_reply/_maybe_suggest_specialties ignoring it."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="symptom-wiring-clinic",
            name="Symptom Wiring Clinic",
            email="symptomwiring@clinic.com",
            phone="+12125550005",
            address={"street": "6 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        Specialty.objects.create(
            clinic=self.clinic, name="Orthopedics", slug="orthopedics"
        )

    def test_soft_medical_reply_uses_symptom_hint_not_only_raw_message(self):
        # The raw message alone doesn't contain any _SYMPTOM_MAP keyword,
        # but the NLU-normalized symptom_hint does -- suggest_specialties
        # is called with reason=symptom_hint, so it should still surface
        # Orthopedics even though the literal message wouldn't match.
        reply = ChatEngine()._soft_medical_reply(
            self.clinic, "not sure what's going on honestly", symptom_hint="fracture"
        )
        self.assertIn("orthopedic", reply.lower())

    def test_maybe_suggest_specialties_forwards_symptom_hint(self):
        suggested, guidance = ChatEngine()._maybe_suggest_specialties(
            self.clinic, "not sure what's going on honestly", {}, symptom_hint="fracture"
        )
        names = [s["name"] for s in suggested]
        self.assertIn("Orthopedics", names)


class SuggestSpecialtiesCategoryHintFallbackTests(TestCase):
    """Live-confirmed bug: "i have kidney stones" -- not in any
    _SYMPTOM_MAP keyword group -- got a generic "can't diagnose" reply even
    at a clinic with a real Urology specialty, because suggest_specialties
    (unlike resolve_symptom_specialty_ids) never consulted the NLU's
    specialty_category_hint fallback. This is the soft_medical/bare-symptom
    path (the MOST common real conversational shape -- "I have X" rather
    than "find me a doctor for X"), so this gap meant the entire hybrid
    resolution chain built for search_doctors/doctor_availability/
    services_offered never actually helped it. Fixed by factoring the
    category-hint branch into suggest_specialties itself so both this path
    and the SQL-handler path share one implementation."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="category-hint-fallback-clinic",
            name="Category Hint Fallback Clinic",
            email="categoryhintfallback@clinic.com",
            phone="+12125550014",
            address={"street": "14 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.urology = Specialty.objects.create(
            clinic=self.clinic, name="Urology Center", slug="urology-center",
            category="Urology",
        )

    def test_category_hint_resolves_when_no_keyword_matches(self):
        suggested, guidance = suggest_specialties(
            self.clinic, message="i have kidney stones", category_hint="Urology"
        )
        self.assertEqual([s["name"] for s in suggested], ["Urology Center"])
        self.assertIn("Urology Center", guidance)

    def test_category_hint_ignored_when_keyword_already_matched(self):
        """A keyword hit (here, dental) must win even if entities also
        carries an unrelated category hint -- same contract already
        enforced for resolve_symptom_specialty_ids, now shared code."""
        Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry",
            category="Dentistry",
        )
        suggested, _ = suggest_specialties(
            self.clinic, message="toothache", category_hint="Urology"
        )
        names = [s["name"] for s in suggested]
        self.assertIn("General Dentistry", names)
        self.assertNotIn("Urology Center", names)

    def test_soft_medical_reply_resolves_kidney_stones_via_category_hint(self):
        reply = ChatEngine()._soft_medical_reply(
            self.clinic, "i have kidney stones",
            symptom_hint="kidney stones", category_hint="Urology",
        )
        self.assertIn("Urology Center", reply)
        # Live-confirmed wording bug: the specialty name and "not a
        # diagnosis" disclaimer used to be stated twice in a row.
        self.assertEqual(reply.count("Urology Center"), 1)


class AuthoritativeSummaryGuardTests(TestCase):
    """Live-confirmed regression: engine.py's soft_medical fallback (in
    _compose_from_plan) unconditionally replaced ANY not-found SQL summary
    with a generic "I can't diagnose symptoms" disclaimer -- harmless while
    search_doctors always defaulted to a full browse (so it never actually
    returned found=False for a doctor_search), but as soon as the symptom-
    matching fix made it return an honest, specific "we don't have a
    specialist for that" summary, this fallback started silently discarding
    the better answer for a worse, generic one."""

    def test_authoritative_summary_is_detected(self):
        sql_rows = [
            {
                "handler": "search_doctors",
                "found": False,
                "rows": [],
                "summary": "We don't have a specialist for that here.",
                "meta": {"authoritative_summary": True},
            }
        ]
        self.assertTrue(ChatEngine()._has_authoritative_summary(sql_rows))

    def test_non_authoritative_not_found_is_not_detected(self):
        """Existing zero-result cases (e.g. an unmatched doctor name) have
        no authoritative_summary flag -- the soft_medical fallback must
        still apply for those, unchanged from before this fix."""
        sql_rows = [
            {
                "handler": "search_doctors",
                "found": False,
                "rows": [],
                "summary": "No matching doctors found.",
            }
        ]
        self.assertFalse(ChatEngine()._has_authoritative_summary(sql_rows))

    def test_empty_sql_rows_is_not_detected(self):
        self.assertFalse(ChatEngine()._has_authoritative_summary([]))


class CategoryMatchingTests(TestCase):
    """A clinic's Specialty.category (core.care_categories.CareCategory)
    is an additional, exact-match signal alongside the existing fuzzy
    name/slug match -- a specialty whose free-text name shares no words
    with any _SYMPTOM_MAP hint must still resolve correctly if it's
    tagged with the right canonical category."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="category-match-clinic",
            name="Category Match Clinic",
            email="categorymatch@clinic.com",
            phone="+12125550007",
            address={"street": "8 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )

    def test_category_alone_matches_even_with_unrelated_name(self):
        Specialty.objects.create(
            clinic=self.clinic,
            name="Dr. Aziz's Smile Studio",  # shares no word with any dental hint
            slug="smile-studio",
            category="Dentistry",
        )
        suggested, _ = suggest_specialties(self.clinic, message="I have a toothache")
        self.assertIn("Dr. Aziz's Smile Studio", [s["name"] for s in suggested])

    def test_uncategorized_specialty_still_relies_on_name_match_only(self):
        Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry"
        )
        suggested, _ = suggest_specialties(self.clinic, message="I have a toothache")
        self.assertIn("General Dentistry", [s["name"] for s in suggested])

    def test_wrong_category_does_not_match(self):
        Specialty.objects.create(
            clinic=self.clinic, name="Heart Center", slug="heart-center", category="Cardiology"
        )
        suggested, _ = suggest_specialties(self.clinic, message="I have a toothache")
        self.assertEqual(suggested, [])


class SymptomResolutionChainTests(TestCase):
    """The full resolution chain: deterministic keyword+category match ->
    NLU specialty_category_hint fallback -> "not understood" for a
    targeted clarification. Exercises resolve_symptom_specialty_ids
    directly, matching the exact chain search_doctors/doctor_availability
    both call through _symptom_no_match_result."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="resolution-chain-clinic",
            name="Resolution Chain Clinic",
            email="resolutionchain@clinic.com",
            phone="+12125550008",
            address={"street": "9 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.dentistry = Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry",
            category="Dentistry",
        )

    def _nlu(self, symptom, category_hint=None):
        entities = {"symptom": symptom}
        if category_hint is not None:
            entities["specialty_category_hint"] = category_hint
        return parse_nlu_payload({"intent": "doctor_search", "entities": entities})

    def test_deterministic_keyword_match_is_understood_and_resolves(self):
        result = resolve_symptom_specialty_ids(self.clinic, self._nlu("toothache"), "toothache")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [str(self.dentistry.id)])

    def test_deterministic_keyword_with_no_clinic_match_is_understood_but_empty(self):
        """"Cardiac" IS in _SYMPTOM_MAP -- the concern is categorized, the
        clinic just doesn't offer it. That's a confident decline, not a
        clarification."""
        result = resolve_symptom_specialty_ids(self.clinic, self._nlu("cardiac"), "cardiac")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [])

    def test_no_keyword_and_no_llm_hint_is_not_understood(self):
        """Nothing in _SYMPTOM_MAP, and the LLM didn't supply a category
        hint either -- genuinely unclassifiable, must ask a targeted
        clarification rather than declare "not offered.\""""
        result = resolve_symptom_specialty_ids(
            self.clinic, self._nlu("a weird thing"), "a weird thing"
        )
        self.assertFalse(result.understood)
        self.assertEqual(result.matched_ids, [])

    def test_llm_category_hint_fallback_resolves_when_keyword_map_has_nothing(self):
        nlu = self._nlu("a weird mouth thing", category_hint="Dentistry")
        result = resolve_symptom_specialty_ids(self.clinic, nlu, "a weird mouth thing")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [str(self.dentistry.id)])

    def test_llm_category_hint_fallback_understood_but_not_offered(self):
        nlu = self._nlu("a weird heart thing", category_hint="Cardiology")
        result = resolve_symptom_specialty_ids(self.clinic, nlu, "a weird heart thing")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [])

    def test_llm_hint_never_consulted_when_keyword_map_already_matched(self):
        """The LLM fallback is only for when the deterministic map has
        nothing at all -- a keyword hit must win even if entities also
        carries a (here, deliberately wrong) category hint."""
        nlu = self._nlu("toothache", category_hint="Cardiology")
        result = resolve_symptom_specialty_ids(self.clinic, nlu, "toothache")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [str(self.dentistry.id)])


class SymptomNoMatchMessagingTests(TestCase):
    """search_doctors' actual response text differs based on whether the
    concern was understood-but-declined vs. genuinely not categorized."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="no-match-messaging-clinic",
            name="No Match Messaging Clinic",
            email="nomatchmessaging@clinic.com",
            phone="+12125550009",
            address={"street": "10 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry",
            category="Dentistry",
        )

    def test_understood_but_not_offered_gives_honest_decline(self):
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.doctors import search_doctors

        nlu = parse_nlu_payload(
            {"intent": "doctor_search", "entities": {"symptom": "cardiac"}}
        )
        ctx = SQLContext(clinic=self.clinic, nlu=nlu, message="is there a cardiac doctor")
        result = search_doctors(ctx)
        self.assertIn("don't have a specialist", result.summary)

    def test_not_understood_gives_targeted_clarification(self):
        from apps.chatbot.sql_tool.base import SQLContext
        from apps.chatbot.sql_tool.handlers.doctors import search_doctors

        nlu = parse_nlu_payload(
            {"intent": "doctor_search", "entities": {"symptom": "a weird thing"}}
        )
        ctx = SQLContext(clinic=self.clinic, nlu=nlu, message="doctor for a weird thing")
        result = search_doctors(ctx)
        self.assertIn("not sure which kind of specialist", result.summary)
        self.assertNotIn("don't have a specialist", result.summary)


class SymptomServiceResolutionChainTests(TestCase):
    """resolve_symptom_service_ids mirrors resolve_symptom_specialty_ids'
    chain, but matches Service.category only -- no fuzzy name/slug match,
    since service names are procedures ("Root Canal"), not specialty words."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="service-resolution-clinic",
            name="Service Resolution Clinic",
            email="serviceresolution@clinic.com",
            phone="+12125550010",
            address={"street": "11 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.root_canal = Service.objects.create(
            clinic=self.clinic, name="Root Canal", category="Dentistry",
        )

    def _nlu(self, symptom, category_hint=None):
        entities = {"symptom": symptom}
        if category_hint is not None:
            entities["specialty_category_hint"] = category_hint
        return parse_nlu_payload({"intent": "services_offered", "entities": entities})

    def test_deterministic_keyword_match_resolves_by_category(self):
        result = resolve_symptom_service_ids(self.clinic, self._nlu("toothache"), "toothache")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [str(self.root_canal.id)])

    def test_service_name_is_never_fuzzy_matched(self):
        """"Root Canal" doesn't share a word with any _SYMPTOM_MAP hint --
        only the category tag should resolve it, never a name/slug guess
        the way suggest_specialties does for specialties."""
        uncategorized = Service.objects.create(clinic=self.clinic, name="Root Canal Plus")
        result = resolve_symptom_service_ids(self.clinic, self._nlu("toothache"), "toothache")
        self.assertNotIn(str(uncategorized.id), result.matched_ids)

    def test_deterministic_keyword_with_no_clinic_match_is_understood_but_empty(self):
        result = resolve_symptom_service_ids(self.clinic, self._nlu("cardiac"), "cardiac")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [])

    def test_no_keyword_and_no_llm_hint_is_not_understood(self):
        result = resolve_symptom_service_ids(
            self.clinic, self._nlu("a weird thing"), "a weird thing"
        )
        self.assertFalse(result.understood)
        self.assertEqual(result.matched_ids, [])

    def test_llm_category_hint_fallback_resolves_when_keyword_map_has_nothing(self):
        nlu = self._nlu("a weird mouth thing", category_hint="Dentistry")
        result = resolve_symptom_service_ids(self.clinic, nlu, "a weird mouth thing")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [str(self.root_canal.id)])

    def test_no_symptom_entity_returns_none(self):
        nlu = parse_nlu_payload({"intent": "services_offered", "entities": {}})
        result = resolve_symptom_service_ids(self.clinic, nlu, "how much is a physical")
        self.assertIsNone(result)


class ServicesOfferedSymptomMessagingTests(TestCase):
    """services_offered's category-mode fallback wires the same
    understood/not-understood distinction into its own decline/clarify
    copy, mirroring SymptomNoMatchMessagingTests for search_doctors."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="services-symptom-clinic",
            name="Services Symptom Clinic",
            email="servicessymptom@clinic.com",
            phone="+12125550011",
            address={"street": "12 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        Service.objects.create(clinic=self.clinic, name="Root Canal", category="Dentistry")

    def _ctx(self, symptom, message):
        from apps.chatbot.sql_tool.base import SQLContext

        nlu = parse_nlu_payload(
            {
                "intent": "services_offered",
                "entities": {"symptom": symptom},
                "service_filter_mode": "category",
            }
        )
        return SQLContext(clinic=self.clinic, nlu=nlu, message=message)

    def test_symptom_resolves_to_matching_service(self):
        from apps.chatbot.sql_tool.handlers.services import services_offered

        result = services_offered(self._ctx("toothache", "what service treats a toothache"))
        self.assertTrue(result.found)
        self.assertEqual(result.rows[0]["name"], "Root Canal")

    def test_understood_but_not_offered_gives_honest_decline(self):
        from apps.chatbot.sql_tool.handlers.services import services_offered

        result = services_offered(self._ctx("cardiac", "what service treats a cardiac issue"))
        self.assertIn("don't have a service", result.summary)

    def test_not_understood_gives_targeted_clarification(self):
        from apps.chatbot.sql_tool.handlers.services import services_offered

        result = services_offered(self._ctx("a weird thing", "service for a weird thing"))
        self.assertIn("not sure which kind of service", result.summary)
        self.assertNotIn("don't have a service", result.summary)


class GenericPainKeywordPrecedenceTests(TestCase):
    """Regression tests for a bug that was pinned (not fixed) for two
    phases: the generic catch-all concern (bare "pain", mapped to Primary
    Care) matched via plain substring containment, so ANY message
    containing "pain" as a substring -- including a specific multi-word
    phrase from an unrelated concern, like "tooth pain" or "chest pain" --
    also hinted Primary Care, on top of whatever specific specialty/
    category that phrase's own concern already resolved.

    Fixed via word-boundary phrase matching (`_phrase_matches`) plus
    excluding `specific=False` (generic) entries from the category set
    entirely (`_hint_names_and_categories`) -- a specific phrase now always
    wins outright, and the generic catch-all never resolves a category on
    its own. These tests now assert the fixed behavior; see
    `PainWordBoundaryAndCrossCategoryTests` below for the broader
    cross-category negative-assertion suite added alongside this fix.
    """

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="pain-precedence-clinic",
            name="Pain Precedence Clinic",
            email="painprecedence@clinic.com",
            phone="+12125550012",
            address={"street": "13 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.dentistry = Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry",
            category="Dentistry",
        )
        self.primary_care = Specialty.objects.create(
            clinic=self.clinic, name="Primary Care Clinic", slug="primary-care-clinic",
            category="Primary Care",
        )
        self.root_canal = Service.objects.create(
            clinic=self.clinic, name="Root Canal", category="Dentistry",
        )
        self.annual_physical = Service.objects.create(
            clinic=self.clinic, name="Annual Physical", category="Primary Care",
        )

    def test_specialty_phrase_with_bare_pain_substring_no_longer_leaks_primary_care(self):
        """"Tooth pain" contains "pain" as a bare substring -- must resolve
        to Dentistry alone now, not also Primary Care."""
        suggested, _ = suggest_specialties(self.clinic, message="I have tooth pain")
        names = {s["name"] for s in suggested}
        self.assertEqual(names, {"General Dentistry"})

    def test_same_specialty_symptom_without_bare_pain_substring_is_precise(self):
        """"Toothache" -- no bare "pain" substring -- resolves to Dentistry
        alone; unaffected by this fix, kept as a control."""
        suggested, _ = suggest_specialties(self.clinic, message="I have a toothache")
        names = {s["name"] for s in suggested}
        self.assertEqual(names, {"General Dentistry"})

    def test_service_phrase_with_bare_pain_substring_no_longer_leaks_primary_care(self):
        nlu = parse_nlu_payload(
            {"intent": "services_offered", "entities": {"symptom": "tooth pain"}}
        )
        result = resolve_symptom_service_ids(self.clinic, nlu, "I have tooth pain")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [str(self.root_canal.id)])

    def test_same_service_symptom_without_bare_pain_substring_is_precise(self):
        nlu = parse_nlu_payload(
            {"intent": "services_offered", "entities": {"symptom": "toothache"}}
        )
        result = resolve_symptom_service_ids(self.clinic, nlu, "I have a toothache")
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [str(self.root_canal.id)])

    def test_bare_pain_alone_no_longer_resolves_primary_care(self):
        """The actual mechanism behind the fix: a message with *only* the
        generic catch-all matching must not resolve a category at all,
        even though this clinic has a real Primary Care specialty that
        would previously have absorbed it."""
        suggested, _ = suggest_specialties(self.clinic, message="I have pain")
        self.assertEqual(suggested, [])


class PainWordBoundaryAndCrossCategoryTests(TestCase):
    """Broader regression suite added alongside the "pain" precedence fix
    (round-three review request): proves the fix holds across several
    unrelated categories, not just dental, and that the underlying
    mechanism is a real word-boundary regex -- not merely "specific wins
    when something else also matches"."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="pain-boundary-clinic",
            name="Pain Boundary Clinic",
            email="painboundary@clinic.com",
            phone="+12125550015",
            address={"street": "15 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.cardiology = Specialty.objects.create(
            clinic=self.clinic, name="Heart Center", slug="heart-center", category="Cardiology",
        )
        self.dentistry = Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry", category="Dentistry",
        )
        self.orthopedics = Specialty.objects.create(
            clinic=self.clinic, name="Bone & Joint Clinic", slug="bone-joint", category="Orthopedics",
        )
        self.primary_care = Specialty.objects.create(
            clinic=self.clinic, name="Primary Care Clinic", slug="primary-care-clinic", category="Primary Care",
        )

    def test_chest_pain_resolves_cardiology_and_intentional_primary_care_hint(self):
        """The cardiac concern's own hints tuple deliberately includes
        "primary care" as a secondary route (same as headache/stomach/
        orthopedic/ENT) -- that's existing, intentional design, not the
        "pain" leak. What must NOT happen is an unrelated third category
        (e.g. Dentistry/Orthopedics) appearing."""
        suggested, _ = suggest_specialties(self.clinic, message="I have chest pain")
        names = {s["name"] for s in suggested}
        self.assertEqual(names, {"Heart Center", "Primary Care Clinic"})

    def test_tooth_pain_resolves_dentistry_only(self):
        """Dentistry's hints tuple does NOT include primary care, so this is
        the clean case proving the generic "pain" catch-all contributes
        nothing extra -- unlike chest/back pain above."""
        suggested, _ = suggest_specialties(self.clinic, message="I have tooth pain")
        names = {s["name"] for s in suggested}
        self.assertEqual(names, {"General Dentistry"})
        self.assertNotIn("Primary Care Clinic", names)

    def test_back_pain_resolves_orthopedics_and_intentional_primary_care_hint(self):
        suggested, _ = suggest_specialties(self.clinic, message="I have back pain")
        names = {s["name"] for s in suggested}
        self.assertEqual(names, {"Bone & Joint Clinic", "Primary Care Clinic"})

    def test_painting_does_not_trigger_the_generic_pain_entry(self):
        """Word-boundary proof, not just specificity precedence: "painting"
        contains "pain" as a substring but must not match the bare-word
        phrase at all."""
        suggested, _ = suggest_specialties(self.clinic, message="I am painting my house")
        self.assertEqual(suggested, [])

    def test_painful_does_not_trigger_the_generic_pain_entry(self):
        suggested, _ = suggest_specialties(self.clinic, message="this is painful")
        self.assertEqual(suggested, [])


class ConcernCategoryAmbiguityTests(TestCase):
    """The new MEDIUM-confidence tier: 2+ distinct categories genuinely
    ambiguous only when (a) the message lexically implies 2+ categories
    and (b) the clinic actually offers 2+ of them. Otherwise resolves
    normally (HIGH) or falls through to the existing understood/not-
    understood path (LOW), matching round-two and round-three's review
    corrections respectively."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="concern-ambiguity-clinic",
            name="Concern Ambiguity Clinic",
            email="concernambiguity@clinic.com",
            phone="+12125550016",
            address={"street": "16 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        self.dentistry = Specialty.objects.create(
            clinic=self.clinic, name="General Dentistry", slug="general-dentistry", category="Dentistry",
        )
        self.cardiology = Specialty.objects.create(
            clinic=self.clinic, name="Heart Center", slug="heart-center", category="Cardiology",
        )
        self.gastro = Specialty.objects.create(
            clinic=self.clinic, name="Digestive Health Center", slug="digestive-health",
            category="Gastroenterology",
        )

    def _nlu(self, symptom):
        return parse_nlu_payload(
            {"intent": "doctor_search", "entities": {"symptom": symptom}}
        )

    def test_tooth_and_jaw_hurt_is_high_not_medium(self):
        """Two matched entries (tooth, jaw), same category (Dentistry) --
        no ambiguity, must not trigger a clarification. This is the exact
        case the second review round caught as a flaw in the original
        "2+ entries matched" MEDIUM rule."""
        result = resolve_symptom_specialty_ids(
            self.clinic, self._nlu("my tooth and jaw hurt"), "my tooth and jaw hurt"
        )
        self.assertTrue(result.understood)
        self.assertEqual(result.ambiguous_categories, [])
        self.assertEqual(result.matched_ids, [str(self.dentistry.id)])

    def test_chest_and_stomach_pain_is_medium_when_clinic_offers_both(self):
        result = resolve_symptom_specialty_ids(
            self.clinic, self._nlu("chest and stomach pain"), "chest and stomach pain"
        )
        self.assertTrue(result.understood)
        self.assertEqual(result.matched_ids, [])
        self.assertEqual(
            set(result.ambiguous_categories), {"Cardiology", "Gastroenterology"}
        )

    def test_bare_pain_is_low_not_medium(self):
        result = resolve_symptom_specialty_ids(
            self.clinic, self._nlu("I have pain"), "I have pain"
        )
        self.assertFalse(result.understood)
        self.assertEqual(result.ambiguous_categories, [])
        self.assertEqual(result.matched_ids, [])

    def test_ambiguous_categories_produce_quick_reply_chips(self):
        from apps.chatbot.booking.discovery import symptom_no_match_result

        result = resolve_symptom_specialty_ids(
            self.clinic, self._nlu("chest and stomach pain"), "chest and stomach pain"
        )
        sql_result = symptom_no_match_result("search_doctors", result, kind="doctor")
        chips = sql_result.meta["clarify_chips"]
        self.assertEqual(len(chips), 2)
        labels = {c["label"] for c in chips}
        self.assertEqual(labels, {"Cardiology", "Gastroenterology"})
        for chip in chips:
            self.assertEqual(chip["behavior"], "message")

    def test_tooth_and_stomach_collapses_to_high_when_clinic_lacks_gastro(self):
        """Clinic-aware filtering (round-three review): a second lexically-
        implied category that the clinic doesn't actually offer must not
        surface as a dead-end chip -- it should collapse to the one real
        option instead."""
        dentistry_only_clinic = Clinic.objects.create(
            slug="dentistry-only-clinic",
            name="Dentistry Only Clinic",
            email="dentistryonly@clinic.com",
            phone="+12125550017",
            address={"street": "17 Main St", "city": "Boston", "state": "MA", "zip": "02101"},
            timezone="America/New_York",
        )
        dentistry = Specialty.objects.create(
            clinic=dentistry_only_clinic, name="General Dentistry", slug="general-dentistry",
            category="Dentistry",
        )
        result = resolve_symptom_specialty_ids(
            dentistry_only_clinic,
            self._nlu("my tooth and stomach hurt"),
            "my tooth and stomach hurt",
        )
        self.assertTrue(result.understood)
        self.assertEqual(result.ambiguous_categories, [])
        self.assertEqual(result.matched_ids, [str(dentistry.id)])
