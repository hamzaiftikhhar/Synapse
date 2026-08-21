"""ChatVisitor model mechanics — the anonymous-identity layer added ahead
of the resume/pagination API. See ROADMAP.md's persistent-chat-history
phase for the full design; this covers only the schema itself (Step 1 of
that phase) — uniqueness, clinic scoping, and the visitor->session->patient
relationships the rest of the phase builds on."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.chatbot.models import ChatSession, ChatSessionStatus, ChatVisitor
from apps.clinics.models import Clinic
from apps.patients.models import Patient


class ChatVisitorModelTests(TestCase):
    def setUp(self):
        self.clinic_a = Clinic.objects.create(
            slug="visitor-clinic-a",
            name="Visitor Clinic A",
            email="a@visitor-test.com",
            phone="+12125550001",
            timezone="America/Los_Angeles",
        )
        self.clinic_b = Clinic.objects.create(
            slug="visitor-clinic-b",
            name="Visitor Clinic B",
            email="b@visitor-test.com",
            phone="+12125550002",
            timezone="America/Los_Angeles",
        )

    def test_visitor_key_is_globally_unique_not_just_per_clinic(self):
        """Deliberate design choice (see plan §3): global uniqueness means a
        query that forgets its clinic= filter fails closed (no row / wrong
        row) rather than silently returning another tenant's visitor."""
        ChatVisitor.objects.create(clinic=self.clinic_a, visitor_key="dup-key")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChatVisitor.objects.create(clinic=self.clinic_b, visitor_key="dup-key")

    def test_visitor_can_have_multiple_sessions(self):
        visitor = ChatVisitor.objects.create(clinic=self.clinic_a, visitor_key="multi-session")
        s1 = ChatSession.objects.create(
            clinic=self.clinic_a, visitor=visitor, session_token="tok-1",
            status=ChatSessionStatus.ACTIVE,
        )
        s2 = ChatSession.objects.create(
            clinic=self.clinic_a, visitor=visitor, session_token="tok-2",
            status=ChatSessionStatus.ACTIVE,
        )
        self.assertEqual(set(visitor.chat_sessions.values_list("id", flat=True)), {s1.id, s2.id})

    def test_deleting_visitor_does_not_delete_its_sessions(self):
        """visitor FK is SET_NULL, not CASCADE — a conversation must survive
        even if its visitor identity is later removed (e.g. a future
        erasure request should be able to drop the visitor's identity
        without silently destroying the clinic's own record of the
        conversation having happened)."""
        visitor = ChatVisitor.objects.create(clinic=self.clinic_a, visitor_key="to-delete")
        session = ChatSession.objects.create(
            clinic=self.clinic_a, visitor=visitor, session_token="tok-survives",
            status=ChatSessionStatus.ACTIVE,
        )
        visitor.delete()
        session.refresh_from_db()
        self.assertIsNone(session.visitor_id)

    def test_visitor_patient_link_is_nullable_and_optional(self):
        visitor = ChatVisitor.objects.create(clinic=self.clinic_a, visitor_key="anon-only")
        self.assertIsNone(visitor.patient_id)

    def test_visitor_can_link_to_a_patient(self):
        patient = Patient.objects.create(
            clinic=self.clinic_a, phone="+15551234567", first_name="Ali", last_name="Test",
        )
        visitor = ChatVisitor.objects.create(
            clinic=self.clinic_a, visitor_key="linked", patient=patient,
        )
        self.assertEqual(visitor.patient_id, patient.id)
        self.assertIn(visitor, patient.chat_visitors.all())
