"""ChatMessage sequence-number generation must be safe under concurrent
writes to the same session — a read-then-write race here silently drops a
message (the second insert hits uq_message_session_sequence, and the
broad except in _save_messages swallows it with no visible error).
Persistent-chat-history work makes concurrent writes to one session more
likely (multi-tab resume), not less, so this is a real prerequisite, not
speculative hardening. Mirrors apps.appointments.tests.test_overlap_and_
slots.ConcurrentBookingTests' TransactionTestCase + ThreadPoolExecutor
pattern exactly."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from django.db import connections
from django.test import TransactionTestCase

from apps.chatbot.engine import ChatEngine
from apps.chatbot.models import ChatMessage, ChatSession, ChatSessionStatus
from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.clinics.models import Clinic


def _nlu(intent: Intent = Intent.FAQ, confidence: float = 0.9) -> NLUResult:
    return NLUResult(
        intent=intent,
        confidence=confidence,
        entities=ExtractedEntities(),
        resolved_ids=ResolvedIds(),
        needs_sql=False,
    )


class ConcurrentMessageSequencingTests(TransactionTestCase):
    def test_two_parallel_turns_on_one_session_do_not_drop_a_message(self):
        clinic = Clinic.objects.create(
            slug="race-chat-clinic",
            name="Race Chat Clinic",
            email="race-chat@test.com",
            phone="+12125550088",
            timezone="America/Los_Angeles",
        )
        session = ChatSession.objects.create(
            clinic=clinic,
            session_token="tok-race-chat",
            status=ChatSessionStatus.ACTIVE,
        )
        session_id = session.id

        def turn(user_text: str, reply_text: str) -> str:
            try:
                s = ChatSession.objects.get(pk=session_id)
                ChatEngine()._save_messages(s, user_text, reply_text, _nlu())
                return "ok"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(turn, "first tab question", "first tab answer")
            f2 = pool.submit(turn, "second tab question", "second tab answer")
            results = [f1.result(), f2.result()]

        self.assertEqual(results, ["ok", "ok"])

        messages = list(
            ChatMessage.objects.filter(session_id=session_id).order_by("sequence_number")
        )
        # Two turns * two messages (user+assistant) each = 4 rows, no
        # IntegrityError-swallowed drops, and sequence numbers are dense
        # and unique (1,2,3,4 in some interleaving) — never a repeat, never
        # a gap from a silently-lost insert.
        self.assertEqual(len(messages), 4)
        sequence_numbers = [m.sequence_number for m in messages]
        self.assertEqual(sequence_numbers, sorted(set(sequence_numbers)))
        self.assertEqual(sequence_numbers, [1, 2, 3, 4])

    def test_a_single_turn_still_creates_both_messages_in_order(self):
        """Not just concurrency — the ordinary single-turn path must still
        work exactly as before behind the new transaction.atomic() wrap."""
        clinic = Clinic.objects.create(
            slug="normal-chat-clinic",
            name="Normal Chat Clinic",
            email="normal-chat@test.com",
            phone="+12125550089",
            timezone="America/Los_Angeles",
        )
        session = ChatSession.objects.create(
            clinic=clinic,
            session_token="tok-normal-chat",
            status=ChatSessionStatus.ACTIVE,
        )
        ChatEngine()._save_messages(session, "hello", "hi there", _nlu(Intent.GREETING, 0.99))

        messages = list(
            ChatMessage.objects.filter(session=session).order_by("sequence_number")
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].sequence_number, 1)
        self.assertEqual(messages[0].metadata["intent"], "greeting")
        self.assertEqual(messages[1].role, "assistant")
        self.assertEqual(messages[1].sequence_number, 2)

    def test_ui_meta_is_persisted_onto_the_assistant_message(self):
        """Step 4 dependency (ROADMAP.md's persistent-chat-history phase):
        the assistant row's metadata used to always be {} — a resumed
        conversation could never show anything but plain text for a past
        doctor-cards/booking-wizard/time-slots turn. _save_messages now
        stores the same `ui_meta` dict the live response sends as `meta`."""
        clinic = Clinic.objects.create(
            slug="ui-meta-clinic",
            name="UI Meta Clinic",
            email="ui-meta@test.com",
            phone="+12125550090",
            timezone="America/Los_Angeles",
        )
        session = ChatSession.objects.create(
            clinic=clinic,
            session_token="tok-ui-meta",
            status=ChatSessionStatus.ACTIVE,
        )
        ui_meta = {
            "doctors": [{"id": "d1", "name": "Dr. Test"}],
            "booking": {"launch": True, "booking_id": "b1"},
        }
        ChatEngine()._save_messages(
            session, "find me a doctor", "Here are some doctors", _nlu(), ui_meta,
        )

        assistant = ChatMessage.objects.get(session=session, role="assistant")
        self.assertEqual(assistant.metadata, ui_meta)

    def test_omitted_ui_meta_still_saves_an_empty_dict_not_none(self):
        """Existing callers (this file included) that don't pass ui_meta at
        all must keep working exactly as before the field was added."""
        clinic = Clinic.objects.create(
            slug="ui-meta-omitted-clinic",
            name="UI Meta Omitted Clinic",
            email="ui-meta-omitted@test.com",
            phone="+12125550091",
            timezone="America/Los_Angeles",
        )
        session = ChatSession.objects.create(
            clinic=clinic,
            session_token="tok-ui-meta-omitted",
            status=ChatSessionStatus.ACTIVE,
        )
        ChatEngine()._save_messages(session, "hi", "hello", _nlu())
        assistant = ChatMessage.objects.get(session=session, role="assistant")
        self.assertEqual(assistant.metadata, {})
