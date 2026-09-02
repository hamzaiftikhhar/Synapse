"""ui_meta.py row mappers (Phase 2): photo_url/is_accepted/duration_min/
price_cents/category were computed by SQL handlers but silently dropped
before reaching the frontend — these lock in the fix."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.ui_meta import (
    _map_doctor,
    _map_insurance,
    _map_service,
    _secondary_booking_offer_action,
    build_ui_meta,
)


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
        mapped = _map_insurance(row)
        self.assertFalse(mapped["is_accepted"])
        self.assertNotIn("select_message", mapped)

    def test_accepted_plan_keeps_booking_select_message(self):
        row = {"id": "1", "provider_name": "Aetna", "plan_name": "Gold", "is_accepted": True}
        mapped = _map_insurance(row)
        self.assertEqual(mapped["select_message"], "Continue booking with Aetna Gold")


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


def _nlu(
    *,
    intent=Intent.DOCTOR_SEARCH,
    secondary_intents=None,
    doctor_name=None,
    doctor_id=None,
    service=None,
    service_id=None,
) -> NLUResult:
    return NLUResult(
        intent=intent,
        secondary_intents=secondary_intents or [],
        confidence=0.9,
        entities=ExtractedEntities(doctor_name=doctor_name, service=service),
        resolved_ids=ResolvedIds(doctor_id=doctor_id, service_id=service_id),
    )


class SecondaryBookingOfferActionTests(SimpleTestCase):
    """Phase 48: 'who are your doctors and can i book with dr vance' used to
    silently drop the booking half with zero acknowledgment anywhere in the
    response (Phase 47 root cause: Intent.BOOK_APPOINTMENT has no
    _INTENT_SQL_TASKS entry, and is_booking_intent only ever checks the
    primary intent). This locks in the light, tap-to-continue chip fix —
    never the wizard itself, just a normal chat-message action identical in
    shape to the existing generic "Book Appointment" chip."""

    def test_no_action_without_book_appointment_secondary(self):
        nlu = _nlu(intent=Intent.DOCTOR_SEARCH, secondary_intents=[])
        self.assertIsNone(_secondary_booking_offer_action(nlu, exec_plan_booking=False))

    def test_no_action_for_a_different_secondary_intent(self):
        """"do you accept aetna and can i see dr vance next tuesday" -
        secondary is doctor_availability, which already has a working
        _INTENT_SQL_TASKS entry and is answered normally — must not also
        get the offer chip."""
        nlu = _nlu(
            intent=Intent.INSURANCE_ACCEPTED,
            secondary_intents=[Intent.DOCTOR_AVAILABILITY],
            doctor_name="Vance",
            doctor_id="doc-1",
        )
        self.assertIsNone(_secondary_booking_offer_action(nlu, exec_plan_booking=False))

    def test_no_action_when_already_launching_the_wizard(self):
        """Never double-offer when the primary intent already triggered a
        real booking flow."""
        nlu = _nlu(
            intent=Intent.BOOK_APPOINTMENT,
            secondary_intents=[Intent.BOOK_APPOINTMENT],
            doctor_name="Vance",
            doctor_id="doc-1",
        )
        self.assertIsNone(_secondary_booking_offer_action(nlu, exec_plan_booking=True))

    def test_doctor_offer_when_doctor_resolved(self):
        nlu = _nlu(
            intent=Intent.DOCTOR_SEARCH,
            secondary_intents=[Intent.BOOK_APPOINTMENT],
            doctor_name="Vance",
            doctor_id="doc-1",
        )
        action = _secondary_booking_offer_action(nlu, exec_plan_booking=False)
        self.assertIsNotNone(action)
        self.assertEqual(action["id"], "book_secondary")
        self.assertEqual(action["label"], "Book with Dr. Vance")
        self.assertEqual(action["behavior"], "message")
        self.assertEqual(action["message"], "I would like to book with Dr. Vance")

    def test_doctor_name_already_prefixed_is_not_doubled(self):
        nlu = _nlu(
            intent=Intent.DOCTOR_SEARCH,
            secondary_intents=[Intent.BOOK_APPOINTMENT],
            doctor_name="Dr. Vance",
            doctor_id="doc-1",
        )
        action = _secondary_booking_offer_action(nlu, exec_plan_booking=False)
        self.assertEqual(action["label"], "Book with Dr. Vance")

    def test_service_offer_when_no_doctor_but_service_resolved(self):
        nlu = _nlu(
            intent=Intent.PRICING,
            secondary_intents=[Intent.BOOK_APPOINTMENT],
            service="Establish Patient Adult Physical",
            service_id="svc-1",
        )
        action = _secondary_booking_offer_action(nlu, exec_plan_booking=False)
        self.assertIsNotNone(action)
        self.assertEqual(action["label"], "Book Establish Patient Adult Physical")

    def test_no_action_without_a_resolved_doctor_or_service(self):
        """The secondary intent is there, but nothing concrete to offer to
        book with/for — must fall through rather than show a vague chip."""
        nlu = _nlu(intent=Intent.DOCTOR_SEARCH, secondary_intents=[Intent.BOOK_APPOINTMENT])
        self.assertIsNone(_secondary_booking_offer_action(nlu, exec_plan_booking=False))

    def test_doctor_entity_without_resolution_does_not_offer(self):
        """An unresolved name (no real doctor matched) must not produce an
        action that silently sends a booking message for a nonexistent
        doctor."""
        nlu = _nlu(
            intent=Intent.DOCTOR_SEARCH,
            secondary_intents=[Intent.BOOK_APPOINTMENT],
            doctor_name="Nobody",
            doctor_id=None,
        )
        self.assertIsNone(_secondary_booking_offer_action(nlu, exec_plan_booking=False))


class BuildUiMetaSecondaryBookingIntegrationTests(SimpleTestCase):
    """build_ui_meta itself — confirms the chip is actually appended to
    meta['actions'] (not just returned by the helper in isolation) and
    that it's additive, never replacing the existing generic chips."""

    def test_chip_appended_to_actions_for_compound_booking_request(self):
        nlu = _nlu(
            intent=Intent.DOCTOR_SEARCH,
            secondary_intents=[Intent.BOOK_APPOINTMENT],
            doctor_name="Vance",
            doctor_id="doc-1",
        )
        meta = build_ui_meta(
            clinic=None,
            intent=Intent.DOCTOR_SEARCH.value,
            route="sql_only",
            sql_results=[],
            nlu=nlu,
            ui_priority="primary",
            exec_plan_booking=False,
        )
        ids = [a.get("id") for a in meta["actions"]]
        self.assertIn("book_secondary", ids)
        self.assertIn("book", ids)  # existing generic chip still present

    def test_no_chip_for_plain_single_intent_message(self):
        nlu = _nlu(intent=Intent.DOCTOR_SEARCH, secondary_intents=[])
        meta = build_ui_meta(
            clinic=None,
            intent=Intent.DOCTOR_SEARCH.value,
            route="sql_only",
            sql_results=[],
            nlu=nlu,
            ui_priority="primary",
            exec_plan_booking=False,
        )
        ids = [a.get("id") for a in meta["actions"]]
        self.assertNotIn("book_secondary", ids)
