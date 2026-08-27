"""Pending-offer uptake: a short yes/no executes the previous turn's offer.

NLU is mocked as the live failure mode — insurance_verification at 0.95 for
'Yep.' — so these tests prove the binder, not the model.
"""

from __future__ import annotations

from datetime import time
from unittest.mock import patch

from django.test import TestCase

from apps.chatbot.engine import ChatEngine
from apps.chatbot.models import ChatSession, ChatSessionStatus
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.widget.models import WidgetSettings

_AFFIRMATIONS = ("Yep.", "Sure", "Please do", "Go ahead", "sounds good")
_DECLINES = ("Not now", "No thanks", "maybe later")


class PendingUptakeEngineTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="uptake-clinic",
            name="Uptake Clinic",
            email="up@clinic.com",
            phone="+12125550077",
            timezone="America/Los_Angeles",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"date_horizon_days": 21}},
        )
        self.maya = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Maya Lin",
            is_active=True,
            is_accepting_patients=True,
        )
        for weekday in range(7):
            DoctorSchedule.objects.create(
                clinic=self.clinic,
                doctor=self.maya,
                day_of_week=weekday,
                start_time=time(8, 0),
                end_time=time(17, 0),
                slot_duration_min=30,
            )

    def _session_with_pending(self, token: str) -> ChatSession:
        return ChatSession.objects.create(
            clinic=self.clinic,
            session_token=token,
            status=ChatSessionStatus.ACTIVE,
            conversation_context={
                "last_doctor": {
                    "id": str(self.maya.id),
                    "name": self.maya.full_name,
                },
                "timeline": {
                    "pending_clarification": {
                        "type": "availability_alternative",
                        "action": "forward_scan",
                        "doctor_id": str(self.maya.id),
                        "doctor_name": self.maya.full_name,
                    },
                    "doctor": {
                        "id": str(self.maya.id),
                        "name": self.maya.full_name,
                    },
                },
            },
        )

    def _nlu(self, intent, **kwargs):
        return NLUResult(
            intent=intent,
            confidence=kwargs.get("confidence", 0.95),
            entities=kwargs.get("entities", ExtractedEntities()),
            resolved_ids=ResolvedIds(),
            needs_sql=True,
        )

    def _assert_availability_not_insurance(self, result, *, msg: str):
        self.assertNotIn("Search your plan", result.response, msg=msg)
        self.assertNotEqual(result.intent, Intent.INSURANCE_VERIFICATION.value, msg=msg)
        lowered = result.response.lower()
        self.assertTrue(
            "available" in lowered
            or "opening" in lowered
            or "slot" in lowered
            or "maya" in lowered,
            msg or result.response,
        )

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_varied_affirms_after_empty_day_are_not_insurance(self, mock_analyze):
        """Patients don't all say 'Yep.' — the binder is a speech-act, not a phrase list."""
        mock_analyze.return_value = self._nlu(Intent.INSURANCE_VERIFICATION)
        for i, text in enumerate(_AFFIRMATIONS):
            with self.subTest(text=text):
                result = ChatEngine().process(
                    clinic=self.clinic,
                    message=text,
                    session=self._session_with_pending(f"tok-affirm-{i}"),
                )
                self._assert_availability_not_insurance(result, msg=text)

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_varied_declines_do_not_run_insurance(self, mock_analyze):
        mock_analyze.return_value = self._nlu(Intent.INSURANCE_VERIFICATION)
        for i, text in enumerate(_DECLINES):
            with self.subTest(text=text):
                result = ChatEngine().process(
                    clinic=self.clinic,
                    message=text,
                    session=self._session_with_pending(f"tok-decline-{i}"),
                )
                self.assertIn("what else", result.response.lower(), msg=text)
                self.assertNotIn("Search your plan", result.response, msg=text)

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_a_new_insurance_question_is_not_stolen_by_pending(self, mock_analyze):
        mock_analyze.return_value = self._nlu(
            Intent.INSURANCE_ACCEPTED,
            entities=ExtractedEntities(insurance_provider=["Cigna"]),
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="is Cigna on the accepted list here",
            session=self._session_with_pending("tok-new-q"),
        )
        # Not a short uptake — pending must not rewrite a real insurance question.
        self.assertNotIn("what else", result.response.lower())

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_yes_plus_a_new_date_is_not_uptake(self, mock_analyze):
        mock_analyze.return_value = self._nlu(
            Intent.DOCTOR_AVAILABILITY,
            entities=ExtractedEntities(date=["Thursday morning"]),
        )
        result = ChatEngine().process(
            clinic=self.clinic,
            message="yes, Thursday morning if she's free",
            session=self._session_with_pending("tok-new-date"),
        )
        # Whole-message speech-act only. This is a new request, not 'Yep.'
        self.assertNotIn("Search your plan", result.response)
        self.assertNotIn("what else", result.response.lower())

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_stale_offer_expires_after_an_unrelated_turn(self, mock_analyze):
        """A pending offer is a same-turn speech-act, not a standing invitation.

        Regression: pending_clarification for availability_alternative/
        service_followup never expired on its own — an unrelated intervening
        turn left it armed, so a much later, unrelated short reply could
        still get wrongly bound to it instead of being judged on its own
        NLU classification.
        """
        session = self._session_with_pending("tok-stale-expire")

        mock_analyze.return_value = self._nlu(Intent.CLINIC_HOURS)
        ChatEngine().process(
            clinic=self.clinic, message="what are your hours", session=session
        )
        session.refresh_from_db()
        pending = (session.conversation_context or {}).get("timeline", {}).get(
            "pending_clarification"
        )
        self.assertIsNone(
            pending, "an unrelated intervening turn should expire the pending offer"
        )

        mock_analyze.return_value = self._nlu(Intent.INSURANCE_VERIFICATION)
        result = ChatEngine().process(
            clinic=self.clinic, message="sure", session=session
        )
        lowered = result.response.lower()
        self.assertNotIn("maya", lowered, msg=result.response)
        self.assertNotIn("available", lowered, msg=result.response)


class SlotConfirmationUptakeTests(TestCase):
    """"yes i want her" / "yes sure" / "book it" taking up a just-offered
    specific slot ("Earliest opening: Dr Maya Lin at 12 PM"). Root cause,
    reproduced against a real transcript (ROADMAP.md): pending_offer_from_turn
    only ever recorded a pending offer for the *empty*-day "check another
    day?" case — a genuinely *found* slot, the most common confirmation
    moment in the whole system, was never tracked at all, so the next
    short reply was classified from zero context and fell through to a
    generic vector search that always came back empty. NLU is mocked
    exactly as above: these tests prove the binder + planner recognize the
    resolved booking intent, independent of what the live model happens to
    guess for a short, ambiguous message."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="slot-confirm-clinic",
            name="Slot Confirm Clinic",
            email="sc@clinic.com",
            phone="+12125550088",
            timezone="America/Los_Angeles",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"date_horizon_days": 21}},
        )
        self.priya = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Priya Chandrasekaran",
            is_active=True,
            is_accepting_patients=True,
        )

    def _session_with_slot_offer(self, token: str) -> ChatSession:
        return ChatSession.objects.create(
            clinic=self.clinic,
            session_token=token,
            status=ChatSessionStatus.ACTIVE,
            conversation_context={
                "last_doctor": {"id": str(self.priya.id), "name": self.priya.full_name},
                "timeline": {
                    "pending_clarification": {
                        "type": "slot_confirmation",
                        "action": "confirm_slot",
                        "doctor_id": str(self.priya.id),
                        "doctor_name": self.priya.full_name,
                        "date": "2026-08-31",
                        "time": "12:00 PM",
                    },
                    "doctor": {"id": str(self.priya.id), "name": self.priya.full_name},
                },
            },
        )

    def _nlu(self, intent, confidence=0.85):
        return NLUResult(
            intent=intent,
            confidence=confidence,
            entities=ExtractedEntities(),
            resolved_ids=ResolvedIds(),
            needs_sql=False,
        )

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_yes_i_want_her_launches_booking_not_rag(self, mock_analyze):
        # The real, observed live-model failure: a bare confirmation
        # classified as faq with no grounding, which used to reach vector
        # search and find nothing.
        mock_analyze.return_value = self._nlu(Intent.FAQ, confidence=0.95)
        result = ChatEngine().process(
            clinic=self.clinic,
            message="yes i want her",
            session=self._session_with_slot_offer("tok-slot-1"),
        )
        self.assertIn("book", result.response.lower())
        self.assertNotIn("couldn't find", result.response.lower())

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_yes_sure_launches_booking_not_rag(self, mock_analyze):
        mock_analyze.return_value = self._nlu(Intent.FAQ, confidence=0.95)
        result = ChatEngine().process(
            clinic=self.clinic,
            message="yes sure",
            session=self._session_with_slot_offer("tok-slot-2"),
        )
        self.assertIn("book", result.response.lower())
        self.assertNotIn("couldn't find", result.response.lower())

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_book_it_launches_booking(self, mock_analyze):
        mock_analyze.return_value = self._nlu(Intent.BOOK_APPOINTMENT)
        result = ChatEngine().process(
            clinic=self.clinic,
            message="book it",
            session=self._session_with_slot_offer("tok-slot-3"),
        )
        self.assertIn("book", result.response.lower())

    @patch("apps.chatbot.nlu.intent_entity.IntentEntityService.analyze")
    def test_unrelated_message_expires_the_slot_offer(self, mock_analyze):
        """Context inheritance must not contaminate an unrelated turn —
        the exact "test 8" safety case from the architectural review this
        phase responds to."""
        session = self._session_with_slot_offer("tok-slot-5")

        mock_analyze.return_value = self._nlu(Intent.CLINIC_HOURS, confidence=0.96)
        ChatEngine().process(
            clinic=self.clinic, message="what are your clinic hours", session=session
        )
        session.refresh_from_db()
        pending = (session.conversation_context or {}).get("timeline", {}).get(
            "pending_clarification"
        )
        self.assertIsNone(
            pending, "an unrelated intervening turn should expire the slot offer"
        )
