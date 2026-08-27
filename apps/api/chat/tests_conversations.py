"""Staff-facing conversations inbox — GET /chat/conversations and
GET /chat/conversations/{id}/messages. Both a clinic's own staff and a
super admin who has entered the clinic (/auth/enter-clinic) reach these
through the exact same clinic_from(request) tenant resolution every other
staff dashboard endpoint already uses — no separate permission model."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.api.auth.jwt import create_staff_access_token
from apps.api.test_helpers import make_clinic_admin
from apps.chatbot.models import (
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    ChatVisitor,
    MessageRole,
    MessageType,
)
from apps.patients.models import Patient

CONVERSATIONS_URL = "/api/v1/chat/conversations"


def _messages_url(session_id: str) -> str:
    return f"/api/v1/chat/conversations/{session_id}/messages"


def _seed_messages(session: ChatSession, count: int) -> None:
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


def _super_admin_headers(*, email: str, tenant: str | None = None, clinic_id=None):
    user = User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Sup3rSecret!",
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    token = create_staff_access_token(
        user_id=user.id, role=user.role, tenant=tenant, clinic_id=clinic_id
    )
    return user, {"Authorization": f"Bearer {token}"}


class ConversationsListTests(TestCase):
    def setUp(self):
        self.owner, self.clinic, self.headers = make_clinic_admin(
            email="owner@convo-test.com",
            clinic_slug="convo-clinic",
            clinic_name="Convo Clinic",
        )
        self.other_owner, self.other_clinic, self.other_headers = make_clinic_admin(
            email="other-owner@convo-test.com", clinic_slug="convo-clinic-other"
        )

    def test_clinic_owner_sees_only_their_own_conversations(self):
        visitor = ChatVisitor.objects.create(clinic=self.clinic, visitor_key="v1")
        session = ChatSession.objects.create(
            clinic=self.clinic,
            visitor=visitor,
            session_token="tok-1",
            status=ChatSessionStatus.ACTIVE,
        )
        _seed_messages(session, 2)
        other_session = ChatSession.objects.create(
            clinic=self.other_clinic,
            session_token="tok-other",
            status=ChatSessionStatus.ACTIVE,
        )
        _seed_messages(other_session, 1)

        resp = self.client.get(CONVERSATIONS_URL, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["session_token"], "tok-1")
        self.assertEqual(body["results"][0]["display_name"], "Anonymous visitor")
        self.assertEqual(body["results"][0]["message_count"], 2)
        self.assertEqual(body["results"][0]["last_message_preview"], "message 2")

    def test_conversation_with_a_known_patient_shows_their_name_and_phone(self):
        patient = Patient.objects.create(
            clinic=self.clinic, first_name="Ali", last_name="Test", phone="+15551234567"
        )
        ChatSession.objects.create(
            clinic=self.clinic,
            patient=patient,
            session_token="tok-patient",
            status=ChatSessionStatus.ACTIVE,
            is_authenticated=True,
        )
        resp = self.client.get(CONVERSATIONS_URL, headers=self.headers)
        body = resp.json()
        self.assertEqual(body["results"][0]["display_name"], "Ali Test")
        self.assertEqual(body["results"][0]["phone"], "+15551234567")

    def test_legacy_session_with_no_visitor_or_patient_shows_anonymous(self):
        ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-legacy", status=ChatSessionStatus.ACTIVE
        )
        resp = self.client.get(CONVERSATIONS_URL, headers=self.headers)
        body = resp.json()
        self.assertEqual(body["results"][0]["display_name"], "Anonymous")

    def test_search_filters_by_patient_name(self):
        p1 = Patient.objects.create(
            clinic=self.clinic, first_name="Sara", last_name="Jones", phone="+15550001111"
        )
        p2 = Patient.objects.create(
            clinic=self.clinic, first_name="Bilal", last_name="Khan", phone="+15550002222"
        )
        ChatSession.objects.create(
            clinic=self.clinic, patient=p1, session_token="tok-sara",
            status=ChatSessionStatus.ACTIVE,
        )
        ChatSession.objects.create(
            clinic=self.clinic, patient=p2, session_token="tok-bilal",
            status=ChatSessionStatus.ACTIVE,
        )

        resp = self.client.get(CONVERSATIONS_URL, {"search": "sara"}, headers=self.headers)
        body = resp.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["session_token"], "tok-sara")

    def test_ordered_by_most_recently_active_first(self):
        older = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-older", status=ChatSessionStatus.ACTIVE
        )
        older.last_active_at = timezone.now() - timedelta(days=1)
        older.save(update_fields=["last_active_at"])
        ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-newer", status=ChatSessionStatus.ACTIVE
        )
        resp = self.client.get(CONVERSATIONS_URL, headers=self.headers)
        body = resp.json()
        self.assertEqual(
            [r["session_token"] for r in body["results"]], ["tok-newer", "tok-older"]
        )

    def test_pagination_limit_and_offset(self):
        for i in range(5):
            ChatSession.objects.create(
                clinic=self.clinic, session_token=f"tok-{i}", status=ChatSessionStatus.ACTIVE
            )
        resp = self.client.get(CONVERSATIONS_URL, {"limit": 2, "offset": 0}, headers=self.headers)
        body = resp.json()
        self.assertEqual(body["count"], 5)
        self.assertEqual(len(body["results"]), 2)

    def test_unauthenticated_request_is_rejected(self):
        resp = self.client.get(CONVERSATIONS_URL)
        self.assertIn(resp.status_code, (401, 403))

    def test_list_does_not_n_plus_one_on_message_count_or_preview(self):
        """message_count/last_message_preview used to cost 2 extra queries
        *per row* (a .count() and a .order_by().first()) — up to 200 extra
        queries for a 100-row page. Both are now correlated subqueries on
        the single list query, so the query count must stay flat regardless
        of how many sessions or messages exist."""
        for i in range(8):
            session = ChatSession.objects.create(
                clinic=self.clinic, session_token=f"n1-tok-{i}", status=ChatSessionStatus.ACTIVE
            )
            _seed_messages(session, 3)

        with self.assertNumQueries(6):
            # 4 queries are per-request staff-JWT/tenant-resolution
            # overhead (user, clinic, subscription, clinic_staff membership
            # — flat regardless of conversation count), then exactly 1 for
            # qs.count() and 1 for the annotated page itself (select_related
            # folds patient/visitor into that same query, and the two
            # correlated subqueries fold message_count/last_message into it
            # too) — 6 total no matter how many sessions or messages exist.
            resp = self.client.get(CONVERSATIONS_URL, {"limit": 8}, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 8)
        for row in body["results"]:
            self.assertEqual(row["message_count"], 3)
            self.assertEqual(row["last_message_preview"], "message 3")


class ConversationsSuperAdminTests(TestCase):
    def setUp(self):
        self.owner, self.clinic, _ = make_clinic_admin(
            email="owner2@convo-test.com", clinic_slug="convo-clinic-sa"
        )
        ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-sa", status=ChatSessionStatus.ACTIVE
        )

    def test_super_admin_without_entering_a_clinic_sees_nothing(self):
        _, headers = _super_admin_headers(email="sa1@convo-test.com")
        resp = self.client.get(CONVERSATIONS_URL, headers=headers)
        # No clinic context at all -> clinic_from raises 400, matching every
        # other staff-scoped endpoint's existing behavior for "no tenant".
        self.assertEqual(resp.status_code, 400)

    def test_super_admin_after_entering_the_clinic_sees_its_conversations(self):
        _, headers = _super_admin_headers(
            email="sa2@convo-test.com", tenant=self.clinic.slug, clinic_id=self.clinic.id
        )
        resp = self.client.get(CONVERSATIONS_URL, headers=headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["session_token"], "tok-sa")


class ConversationMessagesTests(TestCase):
    def setUp(self):
        self.owner, self.clinic, self.headers = make_clinic_admin(
            email="owner3@convo-test.com", clinic_slug="convo-msgs-clinic"
        )
        self.other_owner, self.other_clinic, self.other_headers = make_clinic_admin(
            email="owner4@convo-test.com", clinic_slug="convo-msgs-other"
        )
        self.session = ChatSession.objects.create(
            clinic=self.clinic, session_token="tok-msgs", status=ChatSessionStatus.ACTIVE
        )

    def test_first_page_is_bounded_and_newest_first_boundary(self):
        _seed_messages(self.session, 60)
        resp = self.client.get(_messages_url(str(self.session.id)), headers=self.headers)
        body = resp.json()
        self.assertEqual(len(body["messages"]), 50)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["messages"][0]["content"], "message 11")
        self.assertEqual(body["messages"][-1]["content"], "message 60")

    def test_before_cursor_returns_older_page_no_gap_no_duplicate(self):
        _seed_messages(self.session, 60)
        first = self.client.get(_messages_url(str(self.session.id)), headers=self.headers).json()
        cursor = first["messages"][0]["sequence_number"]
        second = self.client.get(
            _messages_url(str(self.session.id)), {"before": cursor}, headers=self.headers
        ).json()
        self.assertEqual(len(second["messages"]), 10)
        self.assertFalse(second["has_more"])
        seq1 = {m["sequence_number"] for m in first["messages"]}
        seq2 = {m["sequence_number"] for m in second["messages"]}
        self.assertEqual(seq1 & seq2, set())
        self.assertEqual(seq1 | seq2, set(range(1, 61)))

    def test_other_clinics_staff_cannot_read_this_conversation(self):
        _seed_messages(self.session, 1)
        resp = self.client.get(_messages_url(str(self.session.id)), headers=self.other_headers)
        self.assertEqual(resp.status_code, 404)

    def test_unknown_session_id_404s(self):
        resp = self.client.get(
            _messages_url("00000000-0000-7000-8000-000000000000"), headers=self.headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_malformed_session_id_404s_not_500(self):
        resp = self.client.get(_messages_url("not-a-uuid"), headers=self.headers)
        self.assertEqual(resp.status_code, 404)

    def test_invalid_cursor_rejected(self):
        resp = self.client.get(
            _messages_url(str(self.session.id)), {"before": 0}, headers=self.headers
        )
        self.assertEqual(resp.status_code, 422)

    def test_structured_metadata_round_trips(self):
        """Proves the staff view can show doctor/service/booking cards, not
        just plain text — required for frontend MessageRenderer reuse."""
        ChatMessage.objects.create(
            clinic=self.clinic,
            session=self.session,
            role=MessageRole.ASSISTANT,
            message_type=MessageType.TEXT,
            content="here are some doctors",
            sequence_number=1,
            metadata={"doctors": [{"id": "d1", "name": "Dr. Test"}]},
        )
        resp = self.client.get(_messages_url(str(self.session.id)), headers=self.headers)
        body = resp.json()
        self.assertEqual(body["messages"][0]["metadata"]["doctors"][0]["name"], "Dr. Test")


STAFF_MESSAGE_URL = "/api/v1/chat/message/staff"
STAFF_RESUME_URL = "/api/v1/chat/message/staff/resume"


class StaffChatResumeTests(TestCase):
    """GET /chat/message/staff/resume — a staff user's own most recent QA
    session in the *current* clinic, scoped by created_by_user so two
    different staff members (or a super admin across different clinics
    they've entered) never resume each other's conversation."""

    def setUp(self):
        self.owner, self.clinic, self.headers = make_clinic_admin(
            email="resume-owner@convo-test.com", clinic_slug="resume-clinic"
        )

    def test_no_prior_session_returns_no_history_and_creates_nothing(self):
        before = ChatSession.objects.count()
        resp = self.client.get(STAFF_RESUME_URL, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["has_history"])
        self.assertEqual(body["messages"], [])
        self.assertIsNone(body["session_token"])
        # Pure read — opening the widget must never itself create a session.
        self.assertEqual(ChatSession.objects.count(), before)

    def test_resumes_own_prior_session_with_its_messages(self):
        send = self.client.post(
            STAFF_MESSAGE_URL, {"message": "hello"}, content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(send.status_code, 200)
        first_token = send.json()["meta"]["session_token"]

        resp = self.client.get(STAFF_RESUME_URL, headers=self.headers)
        body = resp.json()
        self.assertTrue(body["has_history"])
        self.assertEqual(body["session_token"], first_token)
        self.assertEqual(len(body["messages"]), 2)  # user turn + assistant reply
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertEqual(body["messages"][0]["content"], "hello")

    def test_two_staff_members_at_the_same_clinic_never_resume_each_others_session(self):
        other_user = User.objects.create_user(
            username="resume-other", email="resume-other@convo-test.com",
            password="Sup3rSecret!", role=UserRole.CLINIC_ADMIN, is_active=True,
        )
        from apps.accounts.models import ClinicStaff

        ClinicStaff.objects.create(user=other_user, clinic=self.clinic, is_active=True)
        other_token = create_staff_access_token(
            user_id=other_user.id, role=other_user.role,
            tenant=self.clinic.slug, clinic_id=self.clinic.id,
        )
        other_headers = {"Authorization": f"Bearer {other_token}"}

        self.client.post(
            STAFF_MESSAGE_URL, {"message": "from the owner"}, content_type="application/json",
            headers=self.headers,
        )

        resp = self.client.get(STAFF_RESUME_URL, headers=other_headers)
        body = resp.json()
        self.assertFalse(body["has_history"])
        self.assertEqual(body["messages"], [])

    def test_super_admin_resumes_a_different_session_per_clinic(self):
        other_clinic_owner, other_clinic, _ = make_clinic_admin(
            email="resume-other-clinic@convo-test.com", clinic_slug="resume-clinic-2"
        )
        sa = User.objects.create_user(
            username="resume-sa", email="resume-sa@convo-test.com",
            password="Sup3rSecret!", role=UserRole.SUPER_ADMIN, is_active=True,
        )
        token_a = create_staff_access_token(
            user_id=sa.id, role=sa.role, tenant=self.clinic.slug, clinic_id=self.clinic.id,
        )
        token_b = create_staff_access_token(
            user_id=sa.id, role=sa.role, tenant=other_clinic.slug, clinic_id=other_clinic.id,
        )
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        self.client.post(
            STAFF_MESSAGE_URL, {"message": "hello from clinic A"},
            content_type="application/json", headers=headers_a,
        )

        # Entered clinic A -> resumes clinic A's session.
        resp_a = self.client.get(STAFF_RESUME_URL, headers=headers_a)
        self.assertTrue(resp_a.json()["has_history"])

        # Entered clinic B, same super admin -> no session there yet, and
        # never sees clinic A's conversation.
        resp_b = self.client.get(STAFF_RESUME_URL, headers=headers_b)
        self.assertFalse(resp_b.json()["has_history"])

        self.client.post(
            STAFF_MESSAGE_URL, {"message": "hello from clinic B"},
            content_type="application/json", headers=headers_b,
        )
        resp_b2 = self.client.get(STAFF_RESUME_URL, headers=headers_b)
        self.assertTrue(resp_b2.json()["has_history"])
        self.assertEqual(resp_b2.json()["messages"][0]["content"], "hello from clinic B")

        # Switching back to clinic A still finds clinic A's own session.
        resp_a2 = self.client.get(STAFF_RESUME_URL, headers=headers_a)
        self.assertEqual(resp_a2.json()["messages"][0]["content"], "hello from clinic A")
