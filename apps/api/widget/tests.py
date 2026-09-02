"""Persistent chat history — Steps 2 & 3 (ROADMAP.md Phase 29+). Step 2 is
the resume and cursor-pagination endpoints; Step 3 adds visitor wiring on
the actual guest-chat send path plus the lightweight contact-capture
endpoint. `apps/chatbot/tests/` covers the underlying model/engine
mechanics (ChatVisitor uniqueness, the sequence-number race fix from Step
1, OTP/booking identity-linking from Step 3); this file covers the HTTP
surface — tenant isolation, ownership, cursor correctness, rate limiting,
and (Step 3) that a real guest message always ends up attached to the
calling browser's own ChatVisitor, never someone else's."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.core.cache import cache
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings

from apps.chatbot.engine import EngineResult
from apps.chatbot.models import (
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    ChatVisitor,
    MessageRole,
    MessageType,
)
from apps.clinics.models import Clinic
from apps.patients.models import Patient

CONFIG_URL = "/api/v1/widget/config"
RESUME_URL = "/api/v1/widget/chat/resume"
GUEST_CHAT_URL = "/api/v1/widget/chat/guest"
CONTACT_URL = "/api/v1/widget/chat/contact"
_VISITOR_HEADER = "X-Synapse-Visitor-Id"


def _messages_url(session_token: str) -> str:
    return f"/api/v1/widget/chat/sessions/{session_token}/messages"


def _fake_engine_result() -> EngineResult:
    """A canned successful ChatEngine.process() return value — guest-chat
    tests care about visitor/session wiring, not the NLU/LLM pipeline, so
    the real engine is never invoked."""
    return EngineResult(
        response="Sure, here's an answer.",
        route="faq",
        intent="faq",
        confidence=0.9,
    )


def _make_clinic(slug: str) -> Clinic:
    return Clinic.objects.create(
        slug=slug,
        name=f"{slug} Clinic",
        email=f"{slug}@test.com",
        phone="+12125550000",
        timezone="America/Los_Angeles",
    )


def _seed_messages(session: ChatSession, count: int) -> None:
    """Create `count` ChatMessage rows with dense, correctly-ordered
    sequence numbers — content encodes its own sequence number so test
    assertions can check ordering/gaps directly off the visible content."""
    for i in range(1, count + 1):
        ChatMessage.objects.create(
            clinic=session.clinic,
            session=session,
            role=MessageRole.USER if i % 2 else MessageRole.ASSISTANT,
            message_type=MessageType.TEXT,
            content=f"message {i}",
            sequence_number=i,
            metadata={},
        )


class ResumeFirstTimeVisitorTests(TestCase):
    """Step 4-correction (ROADMAP.md Phase 29 Step 3.1): resume is a pure
    read. Opening the widget for the first time must write nothing to the
    database at all — not even a ChatVisitor. Only the actual send-message
    path (guest_chat_message -> _resolve_guest_session) creates one."""

    def setUp(self):
        self.clinic = _make_clinic("resume-fresh")

    def test_first_time_widget_open_creates_no_visitor_and_returns_null_identity(self):
        resp = self.client.get(RESUME_URL, {"clinic_slug": self.clinic.slug})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body["visitor_id"])
        self.assertIsNone(body["session_token"])
        self.assertFalse(body["has_history"])
        self.assertEqual(body["messages"], [])
        self.assertFalse(body["has_more"])
        self.assertEqual(ChatVisitor.objects.filter(clinic=self.clinic).count(), 0)

    def test_first_time_widget_open_creates_no_chat_session_either(self):
        self.client.get(RESUME_URL, {"clinic_slug": self.clinic.slug})
        self.assertEqual(ChatSession.objects.filter(clinic=self.clinic).count(), 0)
        self.assertEqual(ChatVisitor.objects.filter(clinic=self.clinic).count(), 0)

    def test_repeated_first_time_opens_create_nothing_no_matter_how_many_times(self):
        for _ in range(3):
            self.client.get(RESUME_URL, {"clinic_slug": self.clinic.slug})
        self.assertEqual(ChatVisitor.objects.filter(clinic=self.clinic).count(), 0)
        self.assertEqual(ChatSession.objects.filter(clinic=self.clinic).count(), 0)

    def test_missing_visitor_header_is_not_an_error(self):
        resp = self.client.get(RESUME_URL, {"clinic_slug": self.clinic.slug})
        self.assertEqual(resp.status_code, 200)

    def test_garbage_unrecognized_visitor_header_creates_nothing_and_returns_null_identity(self):
        """An unrecognized value is indistinguishable, from the server's
        perspective, from "no header at all" — never an error, and (unlike
        the old Step 2 behavior) never a reason to mint anything either."""
        resp = self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "totally-made-up-value"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsNone(body["visitor_id"])
        self.assertFalse(body["has_history"])
        self.assertEqual(ChatVisitor.objects.filter(clinic=self.clinic).count(), 0)


class ResumeExistingVisitorTests(TestCase):
    def setUp(self):
        self.clinic = _make_clinic("resume-existing")
        self.visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="known-visitor")

    def test_known_visitor_with_no_session_yet_has_no_history(self):
        """A visitor can exist (e.g. they resumed once already) without
        ever having sent a message yet."""
        resp = self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "known-visitor"},
        )
        body = resp.json()
        self.assertEqual(body["visitor_id"], "known-visitor")
        self.assertIsNone(body["session_token"])
        self.assertFalse(body["has_history"])
        # Still must not create a session just from resuming.
        self.assertEqual(ChatSession.objects.filter(visitor=self.visitor).count(), 0)

    def test_known_visitor_resumes_their_conversation(self):
        session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-existing",
            status=ChatSessionStatus.ACTIVE,
        )
        _seed_messages(session, 3)

        resp = self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "known-visitor"},
        )
        body = resp.json()
        self.assertEqual(body["session_token"], "tok-existing")
        self.assertTrue(body["has_history"])
        self.assertEqual([m["content"] for m in body["messages"]], ["message 1", "message 2", "message 3"])
        self.assertFalse(body["has_more"])

    def test_resuming_does_not_create_a_second_session(self):
        session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-existing",
            status=ChatSessionStatus.ACTIVE,
        )
        _seed_messages(session, 1)
        for _ in range(3):
            self.client.get(
                RESUME_URL, {"clinic_slug": self.clinic.slug},
                headers={_VISITOR_HEADER: "known-visitor"},
            )
        self.assertEqual(ChatSession.objects.filter(visitor=self.visitor).count(), 1)

    def test_resumes_the_most_recently_active_of_multiple_sessions(self):
        from django.utils import timezone
        from datetime import timedelta

        older = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-older",
            status=ChatSessionStatus.ACTIVE,
        )
        older.last_active_at = timezone.now() - timedelta(days=1)
        older.save(update_fields=["last_active_at"])
        newer = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-newer",
            status=ChatSessionStatus.ACTIVE,
        )
        resp = self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "known-visitor"},
        )
        self.assertEqual(resp.json()["session_token"], "tok-newer")


class ResumeActiveBookingTests(TestCase):
    """Phase 42A: an in-progress booking must survive a closed tab —
    separate from historical booking_wizard chat rows, which are always
    rendered inert on resume (see hydrateHistoryRow in message-parser.ts).
    """

    def setUp(self):
        self.clinic = _make_clinic("resume-active-booking")
        self.visitor = ChatVisitor.objects.create(
            clinic=self.clinic, visitor_key="booking-visitor"
        )

    def _session_with_booking(self, *, step: str) -> ChatSession:
        from apps.chatbot.booking.state import BookingSession

        booking = BookingSession.create(clinic_id=str(self.clinic.id), mode="service_first")
        booking.step = step
        return ChatSession.objects.create(
            clinic=self.clinic,
            visitor=self.visitor,
            session_token="tok-booking",
            status=ChatSessionStatus.ACTIVE,
            conversation_context={"booking": booking.to_dict()},
        )

    def test_in_progress_booking_is_surfaced_on_resume(self):
        from apps.chatbot.booking.state import BookingStep

        session = self._session_with_booking(step=BookingStep.PATH.value)
        resp = self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "booking-visitor"},
        )
        body = resp.json()
        self.assertIsNotNone(body["active_booking"])
        self.assertEqual(body["active_booking"]["step"], BookingStep.PATH.value)

    def test_confirmed_booking_is_not_surfaced_as_active(self):
        from apps.chatbot.booking.state import BookingStep

        self._session_with_booking(step=BookingStep.CONFIRMED.value)
        resp = self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "booking-visitor"},
        )
        self.assertIsNone(resp.json()["active_booking"])

    def test_no_booking_at_all_is_none_not_an_error(self):
        ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-nobooking",
            status=ChatSessionStatus.ACTIVE,
        )
        resp = self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "booking-visitor"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["active_booking"])


class ResumePaginationChainTests(TestCase):
    """Step 4-correction requirement: resume's own initial page is bounded
    exactly like every other page — never a "load everything" path — and
    stitching resume's page together with however many /messages?before=
    calls it takes to reach the start of a long conversation reconstructs
    it exactly once, with no duplicates and no gaps."""

    def setUp(self):
        self.clinic = _make_clinic("resume-chain-clinic")
        self.visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="chain-visitor")
        self.session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-chain",
            status=ChatSessionStatus.ACTIVE,
        )

    def _resume(self):
        return self.client.get(
            RESUME_URL, {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "chain-visitor"},
        ).json()

    def _page(self, before):
        return self.client.get(
            _messages_url("tok-chain"), {"clinic_slug": self.clinic.slug, "before": before},
            headers={_VISITOR_HEADER: "chain-visitor"},
        ).json()

    def test_resume_returns_only_a_bounded_first_page_not_the_whole_conversation(self):
        _seed_messages(self.session, 120)
        body = self._resume()
        self.assertEqual(len(body["messages"]), 50)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["messages"][0]["content"], "message 71")
        self.assertEqual(body["messages"][-1]["content"], "message 120")

    def test_a_500_plus_message_conversation_never_comes_back_whole_from_resume(self):
        _seed_messages(self.session, 500)
        body = self._resume()
        self.assertEqual(len(body["messages"]), 50)
        self.assertLess(len(body["messages"]), 500)
        self.assertTrue(body["has_more"])

    def test_older_messages_load_through_the_cursor_endpoint_after_resume(self):
        _seed_messages(self.session, 120)
        first = self._resume()
        cursor = first["messages"][0]["sequence_number"]
        second = self._page(cursor)
        self.assertEqual(len(second["messages"]), 50)
        self.assertTrue(second["has_more"])
        self.assertEqual(second["messages"][-1]["content"], "message 70")
        self.assertEqual(second["messages"][0]["content"], "message 21")

    def test_stitching_resume_with_repeated_pagination_reconstructs_the_full_conversation_once(self):
        """No duplicate/gap across the whole chain — resume's page plus
        however many older pages it takes to reach message 1."""
        total = 517  # deliberately not a multiple of the 50-message page size
        _seed_messages(self.session, total)

        first = self._resume()
        all_seqs = [m["sequence_number"] for m in first["messages"]]
        has_more = first["has_more"]
        cursor = all_seqs[0] if all_seqs else None

        pages_fetched = 1
        while has_more:
            page = self._page(cursor)
            seqs = [m["sequence_number"] for m in page["messages"]]
            self.assertTrue(seqs, "has_more=True but an empty page was returned")
            all_seqs = seqs + all_seqs
            cursor = seqs[0]
            has_more = page["has_more"]
            pages_fetched += 1
            self.assertLess(pages_fetched, 50, "pagination did not terminate")

        self.assertEqual(all_seqs, list(range(1, total + 1)))
        self.assertEqual(len(all_seqs), len(set(all_seqs)))
        self.assertGreater(pages_fetched, 1)


class ResumeTenantIsolationTests(TestCase):
    def test_clinic_a_visitor_key_is_never_resolved_for_clinic_b(self):
        clinic_a = _make_clinic("tenant-a")
        clinic_b = _make_clinic("tenant-b")
        ChatVisitor.objects.create(clinic=clinic_a, visitor_key="shared-looking-key")

        resp = self.client.get(
            RESUME_URL, {"clinic_slug": clinic_b.slug},
            headers={_VISITOR_HEADER: "shared-looking-key"},
        )
        body = resp.json()
        # Never silently resolves to clinic A's visitor, and (resume being
        # a pure read now) nothing is minted for clinic B either — fails
        # closed all the way to "nothing happened", not just "isolated".
        self.assertIsNone(body["visitor_id"])
        self.assertFalse(body["has_history"])
        self.assertEqual(ChatVisitor.objects.filter(clinic=clinic_b).count(), 0)
        self.assertEqual(ChatVisitor.objects.filter(clinic=clinic_a).count(), 1)

    def test_unknown_clinic_slug_404s(self):
        resp = self.client.get(RESUME_URL, {"clinic_slug": "does-not-exist"})
        self.assertEqual(resp.status_code, 404)


class MessagesPaginationTests(TestCase):
    def setUp(self):
        self.clinic = _make_clinic("paginate-clinic")
        self.visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="page-visitor")
        self.session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-page",
            status=ChatSessionStatus.ACTIVE,
        )

    def _get(self, **params):
        return self.client.get(
            _messages_url("tok-page"),
            {"clinic_slug": self.clinic.slug, **params},
            headers={_VISITOR_HEADER: "page-visitor"},
        )

    def test_no_history_case(self):
        resp = self._get()
        body = resp.json()
        self.assertEqual(body["messages"], [])
        self.assertFalse(body["has_more"])

    def test_exactly_50_messages_one_full_page_no_more(self):
        _seed_messages(self.session, 50)
        resp = self._get(limit=50)
        body = resp.json()
        self.assertEqual(len(body["messages"]), 50)
        self.assertFalse(body["has_more"])
        self.assertEqual(body["messages"][0]["content"], "message 1")
        self.assertEqual(body["messages"][-1]["content"], "message 50")

    def test_51_messages_first_page_has_more(self):
        _seed_messages(self.session, 51)
        resp = self._get(limit=50)
        body = resp.json()
        self.assertEqual(len(body["messages"]), 50)
        self.assertTrue(body["has_more"])
        # Newest-first-boundary: the initial (no-cursor) page is the 50
        # MOST RECENT messages, i.e. #2..#51, not #1..#50.
        self.assertEqual(body["messages"][0]["content"], "message 2")
        self.assertEqual(body["messages"][-1]["content"], "message 51")

    def test_100_messages_two_full_pages_no_duplicates_no_gaps(self):
        _seed_messages(self.session, 100)
        page1 = self._get(limit=50).json()
        self.assertEqual(len(page1["messages"]), 50)
        self.assertTrue(page1["has_more"])
        oldest_cursor = page1["messages"][0]["sequence_number"]

        page2 = self._get(limit=50, before=oldest_cursor).json()
        self.assertEqual(len(page2["messages"]), 50)
        self.assertFalse(page2["has_more"])

        seq1 = [m["sequence_number"] for m in page1["messages"]]
        seq2 = [m["sequence_number"] for m in page2["messages"]]
        self.assertEqual(set(seq1) & set(seq2), set())  # no duplicates
        self.assertEqual(sorted(seq2 + seq1), list(range(1, 101)))  # no gaps
        self.assertEqual(seq2, list(range(1, 51)))
        self.assertEqual(seq1, list(range(51, 101)))

    def test_limit_is_clamped_to_max_page_size(self):
        _seed_messages(self.session, 150)
        resp = self._get(limit=99999)
        self.assertEqual(len(resp.json()["messages"]), 100)

    def test_before_cursor_below_one_is_rejected(self):
        resp = self._get(before=0)
        self.assertEqual(resp.status_code, 422)

    def test_new_messages_arriving_mid_pagination_do_not_disturb_an_older_page(self):
        _seed_messages(self.session, 60)
        page1 = self._get(limit=50).json()
        oldest_cursor = page1["messages"][0]["sequence_number"]

        # Simulate a real new message arriving on the live tail while the
        # reader is scrolled up loading history — a genuinely newer
        # sequence number than anything either page will ever return.
        ChatMessage.objects.create(
            clinic=self.clinic, session=self.session, role=MessageRole.USER,
            message_type=MessageType.TEXT, content="message 61 (arrived mid-scroll)",
            sequence_number=61, metadata={},
        )

        page2 = self._get(limit=50, before=oldest_cursor).json()
        self.assertEqual(len(page2["messages"]), 10)  # messages 1..10
        self.assertEqual(
            [m["content"] for m in page2["messages"]],
            [f"message {i}" for i in range(1, 11)],
        )
        self.assertFalse(page2["has_more"])
        # The new message must never leak into an *older* page.
        self.assertNotIn("message 61 (arrived mid-scroll)", [m["content"] for m in page2["messages"]])


class MessagesOwnershipTests(TestCase):
    def setUp(self):
        self.clinic = _make_clinic("owner-clinic")
        self.other_clinic = _make_clinic("owner-clinic-other")
        self.visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="owner-visitor")
        self.session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-owner",
            status=ChatSessionStatus.ACTIVE,
        )
        _seed_messages(self.session, 2)

    def test_correct_visitor_can_read(self):
        resp = self.client.get(
            _messages_url("tok-owner"), {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "owner-visitor"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["messages"]), 2)

    def test_missing_visitor_header_on_a_visitor_linked_session_is_rejected(self):
        resp = self.client.get(
            _messages_url("tok-owner"), {"clinic_slug": self.clinic.slug},
        )
        self.assertEqual(resp.status_code, 404)

    def test_wrong_visitor_header_is_rejected(self):
        resp = self.client.get(
            _messages_url("tok-owner"), {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "someone-elses-visitor-key"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_unknown_session_token_404s(self):
        resp = self.client.get(
            _messages_url("does-not-exist"), {"clinic_slug": self.clinic.slug},
            headers={_VISITOR_HEADER: "owner-visitor"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_clinic_b_cannot_read_clinic_a_session_even_with_correct_token(self):
        resp = self.client.get(
            _messages_url("tok-owner"), {"clinic_slug": self.other_clinic.slug},
            headers={_VISITOR_HEADER: "owner-visitor"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_legacy_session_with_no_visitor_is_still_readable_by_token_alone(self):
        """Pre-Step-1 sessions have visitor=NULL — must keep working exactly
        as the rest of this app already trusts session_token, not become
        unreadable just because the new visitor concept exists."""
        legacy = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-legacy", status=ChatSessionStatus.ACTIVE,
        )
        _seed_messages(legacy, 1)
        resp = self.client.get(
            _messages_url("tok-legacy"), {"clinic_slug": self.clinic.slug},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["messages"]), 1)


class WidgetConfigTimezoneTests(TestCase):
    """Step 4 dependency: date separators need the clinic's IANA timezone,
    which /widget/config didn't expose to the frontend at all before this."""

    def test_config_includes_the_clinic_timezone(self):
        clinic = Clinic.objects.create(
            slug="tz-config-clinic", name="TZ Config Clinic",
            email="tz-config@test.com", phone="+12125550600",
            timezone="America/Chicago",
        )
        resp = self.client.get(CONFIG_URL, {"clinic_slug": clinic.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["timezone"], "America/Chicago")


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.clinic = _make_clinic("ratelimit-clinic")

    def tearDown(self):
        cache.clear()

    def test_resume_is_rate_limited_per_ip(self):
        with patch("apps.api.widget.router._RESUME_MAX_PER_IP", 2):
            for _ in range(2):
                resp = self.client.get(RESUME_URL, {"clinic_slug": self.clinic.slug})
                self.assertEqual(resp.status_code, 200)
            resp = self.client.get(RESUME_URL, {"clinic_slug": self.clinic.slug})
            self.assertEqual(resp.status_code, 429)

    def test_messages_endpoint_is_rate_limited_per_ip(self):
        visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="rl-visitor")
        session = ChatSession.objects.create(
            clinic=self.clinic, visitor=visitor, session_token="tok-rl",
            status=ChatSessionStatus.ACTIVE,
        )
        with patch("apps.api.widget.router._MESSAGES_MAX_PER_IP", 2):
            for _ in range(2):
                resp = self.client.get(
                    _messages_url("tok-rl"), {"clinic_slug": self.clinic.slug},
                    headers={_VISITOR_HEADER: "rl-visitor"},
                )
                self.assertEqual(resp.status_code, 200)
            resp = self.client.get(
                _messages_url("tok-rl"), {"clinic_slug": self.clinic.slug},
                headers={_VISITOR_HEADER: "rl-visitor"},
            )
            self.assertEqual(resp.status_code, 429)

    def test_contact_is_rate_limited_per_ip(self):
        visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="rl-contact-visitor")
        with patch("apps.api.widget.router._CONTACT_MAX_PER_IP", 1):
            resp = self.client.post(
                CONTACT_URL,
                data={"clinic_slug": self.clinic.slug, "email": "rl-1@example.com"},
                content_type="application/json",
                headers={_VISITOR_HEADER: "rl-contact-visitor"},
            )
            self.assertEqual(resp.status_code, 200)
            resp = self.client.post(
                CONTACT_URL,
                data={"clinic_slug": self.clinic.slug, "email": "rl-2@example.com"},
                content_type="application/json",
                headers={_VISITOR_HEADER: "rl-contact-visitor"},
            )
            self.assertEqual(resp.status_code, 429)


class GuestChatVisitorWiringTests(TestCase):
    """The bridge Step 2's own report flagged as required for Step 3:
    _resolve_guest_session (used by the real send-message path, unlike
    /chat/resume which deliberately never creates anything) must resolve
    or mint a ChatVisitor and attach it, exactly once, to the ChatSession
    a guest message ends up in."""

    def setUp(self):
        self.clinic = _make_clinic("guest-wiring-clinic")
        patcher = patch("apps.api.widget.router.ChatEngine")
        self.mock_engine_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_engine_cls.return_value.process.return_value = _fake_engine_result()

    def _send(self, message="Hello", session_token=None, visitor_key=None):
        headers = {_VISITOR_HEADER: visitor_key} if visitor_key else {}
        return self.client.post(
            GUEST_CHAT_URL,
            data={"clinic_slug": self.clinic.slug, "message": message, "session_token": session_token},
            content_type="application/json",
            headers=headers,
        )

    def test_first_message_creates_and_attaches_a_visitor(self):
        resp = self._send()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        session_token = body["meta"]["session_token"]
        visitor_id = body["meta"]["visitor_id"]
        self.assertTrue(visitor_id)
        session = ChatSession.objects.get(clinic=self.clinic, session_token=session_token)
        self.assertIsNotNone(session.visitor_id)
        self.assertEqual(session.visitor.visitor_key, visitor_id)

    def test_first_actual_message_is_what_creates_both_visitor_and_session_not_opening_the_widget(self):
        """The other half of the Step 4-correction: resume creates
        nothing (see ResumeFirstTimeVisitorTests); sending the first real
        message is what creates both, exactly once each."""
        self.assertEqual(ChatVisitor.objects.filter(clinic=self.clinic).count(), 0)
        self.assertEqual(ChatSession.objects.filter(clinic=self.clinic).count(), 0)

        resp = self._send()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ChatVisitor.objects.filter(clinic=self.clinic).count(), 1)
        self.assertEqual(ChatSession.objects.filter(clinic=self.clinic).count(), 1)

    def test_repeated_messages_with_the_returned_identity_reuse_the_same_visitor_and_session(self):
        first = self._send().json()
        token, visitor_id = first["meta"]["session_token"], first["meta"]["visitor_id"]
        second = self._send(message="follow-up", session_token=token, visitor_key=visitor_id).json()
        self.assertEqual(second["meta"]["session_token"], token)
        self.assertEqual(second["meta"]["visitor_id"], visitor_id)
        self.assertEqual(ChatSession.objects.filter(clinic=self.clinic).count(), 1)
        self.assertEqual(ChatVisitor.objects.filter(clinic=self.clinic).count(), 1)

    def test_known_visitor_without_a_session_token_resumes_its_active_session_not_a_new_one(self):
        visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="returning-visitor")
        ChatSession.objects.create(
            clinic=self.clinic, visitor=visitor, session_token="tok-returning",
            status=ChatSessionStatus.ACTIVE,
        )
        body = self._send(visitor_key="returning-visitor").json()
        self.assertEqual(body["meta"]["session_token"], "tok-returning")
        self.assertEqual(ChatSession.objects.filter(visitor=visitor).count(), 1)

    def test_legacy_session_gets_adopted_by_its_own_browser_on_the_next_message(self):
        """Pre-Step-3 sessions have visitor=NULL — the first message sent
        against one afterwards must adopt it into the visitor concept
        rather than leaving it permanently unresumable."""
        legacy = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-legacy-adopt", status=ChatSessionStatus.ACTIVE,
        )
        body = self._send(session_token="tok-legacy-adopt").json()
        legacy.refresh_from_db()
        self.assertIsNotNone(legacy.visitor_id)
        self.assertEqual(legacy.visitor.visitor_key, body["meta"]["visitor_id"])
        self.assertEqual(ChatSession.objects.filter(clinic=self.clinic).count(), 1)

    def test_a_session_already_owned_by_a_different_visitor_is_never_reassigned(self):
        owner = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="owner-visitor")
        session = ChatSession.objects.create(
            clinic=self.clinic, visitor=owner, session_token="tok-owned",
            status=ChatSessionStatus.ACTIVE,
        )
        self._send(session_token="tok-owned")  # no header -> mints an unrelated new visitor
        session.refresh_from_db()
        self.assertEqual(session.visitor_id, owner.id)


class GuestVisitorConcurrencyTests(TransactionTestCase):
    def test_two_concurrent_calls_with_the_same_known_visitor_key_resolve_to_one_visitor(self):
        """The visitor-creation race the plan calls out explicitly. Uses an
        already-known key (the realistic shape: a browser that already
        holds a visitor_id from an earlier /chat/resume sends two messages
        close together) — mirrors apps.chatbot.tests.test_message_
        sequencing's TransactionTestCase + ThreadPoolExecutor pattern.
        Two truly-simultaneous *cold-start* requests (no key at all yet)
        are a separate, inherent limitation of a header-only identity
        scheme with no client-side coordination — noted in the Step 3
        report, not covered here."""
        from apps.api.widget.router import _find_or_create_visitor

        clinic = Clinic.objects.create(
            slug="visitor-concurrency-clinic",
            name="Visitor Concurrency Clinic",
            email="visitor-concurrency@test.com",
            phone="+12125550500",
            timezone="America/Los_Angeles",
        )
        visitor_key = "concurrent-known-visitor"
        ChatVisitor.objects.create(clinic=clinic, visitor_key=visitor_key)
        clinic_id = clinic.id

        def resolve():
            try:
                c = Clinic.objects.get(pk=clinic_id)
                visitor, created = _find_or_create_visitor(c, visitor_key)
                return visitor.id, created
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(resolve)
            f2 = pool.submit(resolve)
            r1, r2 = f1.result(), f2.result()

        self.assertEqual(r1[0], r2[0])
        self.assertFalse(r1[1])
        self.assertFalse(r2[1])
        self.assertEqual(ChatVisitor.objects.filter(clinic=clinic, visitor_key=visitor_key).count(), 1)


class ChatContactTests(TestCase):
    def setUp(self):
        self.clinic = _make_clinic("contact-clinic")
        self.visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="contact-visitor")

    def _contact(self, *, email=None, phone=None, visitor_key="contact-visitor"):
        payload = {"clinic_slug": self.clinic.slug}
        if email is not None:
            payload["email"] = email
        if phone is not None:
            payload["phone"] = phone
        headers = {_VISITOR_HEADER: visitor_key} if visitor_key else {}
        return self.client.post(
            CONTACT_URL, data=payload, content_type="application/json", headers=headers,
        )

    def test_contact_with_email_creates_an_unverified_patient_and_links_the_visitor(self):
        resp = self._contact(email="anon@example.com")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["linked"])
        self.assertFalse(body["patient_verified"])
        self.visitor.refresh_from_db()
        self.assertIsNotNone(self.visitor.patient_id)
        self.assertEqual(self.visitor.patient.email, "anon@example.com")
        self.assertFalse(self.visitor.patient.is_verified)

    def test_contact_with_phone_creates_an_unverified_patient_and_links_the_visitor(self):
        resp = self._contact(phone="+15557778888")
        self.assertTrue(resp.json()["linked"])
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.patient.phone, "+15557778888")
        self.assertFalse(self.visitor.patient.is_verified)

    def test_reuses_an_existing_patient_by_email_rather_than_duplicating(self):
        existing = Patient.objects.create(
            clinic=self.clinic, phone="+15559990001", email="existing-contact@example.com",
            first_name="Ex", last_name="Isting",
        )
        self._contact(email="existing-contact@example.com")
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.patient_id, existing.id)
        self.assertEqual(
            Patient.objects.filter(clinic=self.clinic, email="existing-contact@example.com").count(), 1
        )

    def test_reuses_an_existing_patient_by_phone_rather_than_duplicating(self):
        existing = Patient.objects.create(
            clinic=self.clinic, phone="+15559990002", first_name="Ex", last_name="Isting",
        )
        self._contact(phone="+15559990002")
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.patient_id, existing.id)
        self.assertEqual(Patient.objects.filter(clinic=self.clinic, phone="+15559990002").count(), 1)

    def test_contact_capture_does_not_authenticate_the_session(self):
        session = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-contact-session",
            status=ChatSessionStatus.ACTIVE, is_authenticated=False,
        )
        self._contact(email="not-auth@example.com")
        session.refresh_from_db()
        self.assertFalse(session.is_authenticated)
        self.assertIsNotNone(session.patient_id)

    def test_contact_backfills_all_prior_sessions_for_the_visitor(self):
        s1 = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-contact-1",
            status=ChatSessionStatus.CLOSED,
        )
        s2 = ChatSession.objects.create(
            clinic=self.clinic, visitor=self.visitor, session_token="tok-contact-2",
            status=ChatSessionStatus.ACTIVE,
        )
        self._contact(email="backfill@example.com")
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertEqual(s1.patient_id, s2.patient_id)
        self.assertIsNotNone(s1.patient_id)

    def test_skip_never_calling_contact_creates_no_patient(self):
        self.assertEqual(Patient.objects.filter(clinic=self.clinic).count(), 0)

    def test_missing_visitor_header_is_rejected(self):
        resp = self._contact(email="x@example.com", visitor_key=None)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(Patient.objects.filter(clinic=self.clinic).count(), 0)

    def test_missing_email_and_phone_is_rejected(self):
        resp = self._contact()
        self.assertEqual(resp.status_code, 422)

    def test_already_linked_visitor_is_not_reassigned_by_a_second_submission(self):
        first_patient = Patient.objects.create(
            clinic=self.clinic, phone="+15559990003", first_name="First", last_name="Linked",
        )
        self.visitor.patient = first_patient
        self.visitor.save(update_fields=["patient"])
        self._contact(email="different-person@example.com")
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.patient_id, first_patient.id)
        self.assertFalse(
            Patient.objects.filter(clinic=self.clinic, email="different-person@example.com").exists()
        )


class CrossVisitorPrivacyTests(TestCase):
    """The critical privacy rule from the Step 3 brief, stated as a non-goal
    in the plan's own §5: resolving to the same Patient never grants one
    visitor access to another visitor's conversation."""

    def test_same_patient_across_two_browsers_does_not_expose_the_others_history(self):
        clinic = _make_clinic("privacy-clinic")
        patient = Patient.objects.create(
            clinic=clinic, phone="+15551112222", email="shared-person@example.com",
            first_name="Shared", last_name="Person", is_verified=True,
        )
        visitor_a = ChatVisitor.objects.create(clinic=clinic, visitor_key="browser-a", patient=patient)
        ChatVisitor.objects.create(clinic=clinic, visitor_key="browser-b", patient=patient)

        session_a = ChatSession.objects.create(
            clinic=clinic, visitor=visitor_a, patient=patient, session_token="tok-browser-a",
            status=ChatSessionStatus.ACTIVE, is_authenticated=True,
        )
        _seed_messages(session_a, 3)

        resume_resp = self.client.get(
            RESUME_URL, {"clinic_slug": clinic.slug}, headers={_VISITOR_HEADER: "browser-b"},
        )
        body = resume_resp.json()
        self.assertIsNone(body["session_token"])
        self.assertFalse(body["has_history"])

        messages_resp = self.client.get(
            _messages_url("tok-browser-a"), {"clinic_slug": clinic.slug},
            headers={_VISITOR_HEADER: "browser-b"},
        )
        self.assertEqual(messages_resp.status_code, 404)

        own_resp = self.client.get(
            _messages_url("tok-browser-a"), {"clinic_slug": clinic.slug},
            headers={_VISITOR_HEADER: "browser-a"},
        )
        self.assertEqual(own_resp.status_code, 200)
        self.assertEqual(len(own_resp.json()["messages"]), 3)


EMBED_POLICY_URL = "/api/v1/widget/embed-policy"


class OriginAllowlistTests(TestCase):
    """Clinic.allowed_origins enforcement, via resolve_public_clinic — the
    single choke point every public /widget/* endpoint now shares (see
    apps.api.auth.deps). Exercised through /widget/config since every other
    endpoint routes through the exact same helper."""

    def test_registered_origin_is_allowed(self):
        clinic = _make_clinic("origin-allowed")
        clinic.allowed_origins = ["https://origin-allowed.example.com"]
        clinic.save(update_fields=["allowed_origins"])

        resp = self.client.get(
            CONFIG_URL, {"clinic_slug": clinic.slug},
            headers={"Origin": "https://origin-allowed.example.com"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_unregistered_origin_is_rejected(self):
        clinic = _make_clinic("origin-rejected")
        clinic.allowed_origins = ["https://the-real-site.example.com"]
        clinic.save(update_fields=["allowed_origins"])

        resp = self.client.get(
            CONFIG_URL, {"clinic_slug": clinic.slug},
            headers={"Origin": "https://evil.example.com"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_empty_allowed_origins_rejects_any_non_platform_origin(self):
        """The security-relevant default: a clinic that hasn't registered
        anything is NOT open to the world — its widget simply doesn't work
        from a third-party site yet."""
        clinic = _make_clinic("origin-unconfigured")
        self.assertEqual(clinic.allowed_origins, [])

        resp = self.client.get(
            CONFIG_URL, {"clinic_slug": clinic.slug},
            headers={"Origin": "https://anything.example.com"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_missing_origin_header_is_allowed(self):
        """Non-browser callers (and every existing test in this file) send
        no Origin header at all — that must keep working."""
        clinic = _make_clinic("origin-missing-header")

        resp = self.client.get(CONFIG_URL, {"clinic_slug": clinic.slug})
        self.assertEqual(resp.status_code, 200)

    @override_settings(CORS_ALLOWED_ORIGINS=["https://dashboard.synapse.test"])
    def test_platform_origin_is_always_allowed_regardless_of_clinic(self):
        """Regression for the staff/super-admin dashboard reusing these same
        public endpoints for its own 'test the bot' widget (WidgetProvider /
        GlobalChatWidget both fire GET /widget/config with mode='clinic') —
        this must work even for a clinic with zero registered origins."""
        clinic = _make_clinic("origin-platform-dashboard")
        self.assertEqual(clinic.allowed_origins, [])

        resp = self.client.get(
            CONFIG_URL, {"clinic_slug": clinic.slug},
            headers={"Origin": "https://dashboard.synapse.test"},
        )
        self.assertEqual(resp.status_code, 200)


class EmbedPolicyTests(TestCase):
    """GET /widget/embed-policy — server-to-server only, consumed by the
    Next.js embed route's Edge Middleware to build its CSP header. Never
    404s: an unknown clinic and a clinic with nothing configured must look
    identical to the caller (both mean 'no origins to allow')."""

    def test_known_clinic_returns_its_origins(self):
        clinic = _make_clinic("embed-policy-known")
        clinic.allowed_origins = ["https://a.example.com", "https://b.example.com"]
        clinic.save(update_fields=["allowed_origins"])

        resp = self.client.get(EMBED_POLICY_URL, {"clinic_slug": clinic.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["allowed_origins"],
            ["https://a.example.com", "https://b.example.com"],
        )

    def test_unconfigured_clinic_returns_empty_list(self):
        clinic = _make_clinic("embed-policy-unconfigured")

        resp = self.client.get(EMBED_POLICY_URL, {"clinic_slug": clinic.slug})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["allowed_origins"], [])

    def test_unknown_clinic_slug_returns_empty_list_not_404(self):
        resp = self.client.get(EMBED_POLICY_URL, {"clinic_slug": "does-not-exist"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["allowed_origins"], [])
