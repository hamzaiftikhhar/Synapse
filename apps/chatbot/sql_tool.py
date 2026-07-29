"""
SQL Tool — queries clinic ORM models based on resolved NLU entities.

Each handler receives a Clinic + NLUResult and returns a structured dict
that the ChatEngine / AI Orchestrator can use directly or pass to the LLM.

All queries are read-only, multi-tenant-safe (always filtered by clinic).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Result container ─────────────────────────────────────────────────────────

@dataclass
class SQLResult:
    """Structured output from a SQL tool handler."""
    handler: str                        # which handler produced this
    found: bool = False
    rows: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""                   # human-readable one-liner for orchestrator
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handler": self.handler,
            "found": self.found,
            "rows": self.rows,
            "summary": self.summary,
            "meta": self.meta,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_natural_date(raw: str | None) -> date | None:
    """Very lightweight natural-language date parser (no external deps)."""
    if not raw:
        return None
    raw = raw.strip().lower()
    today = timezone.localdate()
    if raw in ("today", "now"):
        return today
    if raw == "tomorrow":
        return today + timedelta(days=1)
    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    }
    for name, weekday in day_map.items():
        if name in raw:
            days_ahead = (weekday - today.weekday()) % 7 or 7
            return today + timedelta(days=days_ahead)
    # Try explicit formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d", "%b %d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            # Attach current year if missing
            if parsed.year == 1900:
                parsed = parsed.replace(year=today.year)
            return parsed.date()
        except ValueError:
            continue
    return None


def _doctor_to_dict(doc: Any) -> dict[str, Any]:
    return {
        "id": str(doc.id),
        "full_name": doc.full_name,
        "title": doc.title,
        "bio": doc.bio[:300] if doc.bio else "",
        "languages": doc.languages,
        "is_accepting_patients": doc.is_accepting_patients,
        "specialties": [s.name for s in doc.specialties.all()],
        "services": [s.name for s in doc.services.filter(is_deleted=False)],
    }


def _slot_to_dict(start: datetime, end: datetime, doctor_name: str) -> dict[str, Any]:
    return {
        "doctor": doctor_name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "date": start.date().isoformat(),
        "time": start.strftime("%I:%M %p"),
    }


# ── Handlers ──────────────────────────────────────────────────────────────────

class SQLTool:
    """
    Dispatch NLU result to the right DB query.

    Usage:
        result = SQLTool.run(clinic, nlu)
        # result is a list[SQLResult] — one per resolved handler
    """

    @classmethod
    def run(cls, clinic: Any, nlu: Any) -> list[SQLResult]:
        from apps.chatbot.nlu.schemas import Intent

        intent = nlu.intent
        results: list[SQLResult] = []

        dispatch: dict[Intent, Any] = {
            Intent.DOCTOR_SEARCH:         cls.search_doctors,
            Intent.DOCTOR_AVAILABILITY:   cls.doctor_availability,
            Intent.BOOK_APPOINTMENT:      cls.doctor_availability,  # slots needed first
            Intent.CANCEL_APPOINTMENT:    cls.patient_appointments,
            Intent.RESCHEDULE_APPOINTMENT:cls.patient_appointments,
            Intent.INSURANCE_ACCEPTED:    cls.insurance_accepted,
            Intent.INSURANCE_VERIFICATION:cls.insurance_accepted,
            Intent.CLINIC_HOURS:          cls.clinic_hours,
            Intent.CLINIC_LOCATION:       cls.clinic_location,
            Intent.SERVICES_OFFERED:      cls.services_offered,
            Intent.PRICING:               cls.services_offered,
        }

        handler = dispatch.get(intent)
        if handler:
            try:
                results.append(handler(clinic, nlu))
            except Exception:
                logger.exception("SQLTool handler %s failed", handler.__name__)
                results.append(SQLResult(handler=handler.__name__, found=False, summary="DB query failed."))

        # Multi-intent: also run secondary intent handlers
        for secondary in nlu.secondary_intents:
            h2 = dispatch.get(secondary)
            if h2 and h2 != handler:
                try:
                    results.append(h2(clinic, nlu))
                except Exception:
                    logger.exception("SQLTool secondary handler %s failed", h2.__name__)

        return results or [SQLResult(handler="none", found=False, summary="No SQL handler for this intent.")]

    # ── Doctor search ──────────────────────────────────────────────────────

    @staticmethod
    def search_doctors(clinic: Any, nlu: Any) -> SQLResult:
        from apps.doctors.models import Doctor

        qs = (
            Doctor.objects
            .filter(clinic=clinic, is_deleted=False, is_active=True)
            .prefetch_related("specialties", "services")
        )

        entities = nlu.entities
        resolved = nlu.resolved_ids

        # Filter by doctor name if resolved
        if resolved.doctor_id:
            ids = resolved.doctor_id if isinstance(resolved.doctor_id, list) else [resolved.doctor_id]
            qs = qs.filter(id__in=ids)
        elif entities.doctor_name:
            names = entities.doctor_name if isinstance(entities.doctor_name, list) else [entities.doctor_name]
            from django.db.models import Q
            q = Q()
            for n in names:
                q |= Q(full_name__icontains=n)
            qs = qs.filter(q)

        # Filter by specialty
        if resolved.specialty_id:
            ids = resolved.specialty_id if isinstance(resolved.specialty_id, list) else [resolved.specialty_id]
            qs = qs.filter(doctor_specialties__specialty_id__in=ids).distinct()
        elif entities.specialty:
            specs = entities.specialty if isinstance(entities.specialty, list) else [entities.specialty]
            from django.db.models import Q
            q = Q()
            for s in specs:
                q |= Q(specialties__name__icontains=s)
            qs = qs.filter(q).distinct()

        doctors = list(qs[:10])
        rows = [_doctor_to_dict(d) for d in doctors]
        found = bool(rows)
        if found:
            names = ", ".join(d["full_name"] for d in rows[:3])
            summary = f"Found {len(rows)} doctor(s): {names}."
        else:
            summary = "No matching doctors found."
        return SQLResult(handler="search_doctors", found=found, rows=rows, summary=summary)

    # ── Doctor availability / open slots ───────────────────────────────────

    @staticmethod
    def doctor_availability(clinic: Any, nlu: Any) -> SQLResult:
        from apps.doctors.models import Doctor, DoctorSchedule, DoctorLeave
        from apps.appointments.models import Appointment, AppointmentStatus

        entities = nlu.entities
        resolved = nlu.resolved_ids

        # Determine target date(s)
        date_strs: list[str] = []
        if entities.date:
            date_strs = entities.date if isinstance(entities.date, list) else [entities.date]
        target_date = _parse_natural_date(date_strs[0] if date_strs else None) or timezone.localdate() + timedelta(days=1)

        # Determine doctor(s)
        doctor_qs = Doctor.objects.filter(clinic=clinic, is_deleted=False, is_active=True, is_accepting_patients=True)
        if resolved.doctor_id:
            ids = resolved.doctor_id if isinstance(resolved.doctor_id, list) else [resolved.doctor_id]
            doctor_qs = doctor_qs.filter(id__in=ids)
        elif entities.doctor_name:
            names = entities.doctor_name if isinstance(entities.doctor_name, list) else [entities.doctor_name]
            from django.db.models import Q
            q = Q()
            for n in names:
                q |= Q(full_name__icontains=n)
            doctor_qs = doctor_qs.filter(q)

        doctors = list(doctor_qs[:5])
        if not doctors:
            return SQLResult(
                handler="doctor_availability",
                found=False,
                summary="No matching doctors found to check availability.",
            )

        day_of_week = target_date.weekday()
        tz = timezone.get_current_timezone()
        slots: list[dict[str, Any]] = []

        for doctor in doctors:
            schedules = DoctorSchedule.objects.filter(
                clinic=clinic,
                doctor=doctor,
                day_of_week=day_of_week,
                is_active=True,
            )
            # Check leaves
            target_start = datetime.combine(target_date, time.min)
            target_end = datetime.combine(target_date, time.max)
            on_leave = DoctorLeave.objects.filter(
                clinic=clinic,
                doctor=doctor,
                is_active=True,
                start_at__lt=target_end,
                end_at__gt=target_start,
            ).exists()
            if on_leave:
                continue

            # Existing appointments on this day
            day_start = datetime.combine(target_date, time.min)
            day_end = datetime.combine(target_date, time.max)
            booked = set(
                Appointment.objects
                .filter(
                    clinic=clinic,
                    doctor=doctor,
                    start_time__range=(day_start, day_end),
                    status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
                )
                .values_list("start_time", flat=True)
            )

            for sched in schedules:
                slot_start = datetime.combine(target_date, sched.start_time)
                slot_end = datetime.combine(target_date, sched.end_time)
                current = slot_start
                while current + timedelta(minutes=sched.slot_duration_min) <= slot_end:
                    # Make timezone-aware for comparison
                    current_aware = timezone.make_aware(current, tz) if timezone.is_naive(current) else current
                    if current_aware not in booked:
                        slots.append(_slot_to_dict(current, current + timedelta(minutes=sched.slot_duration_min), doctor.full_name))
                    current += timedelta(minutes=sched.slot_duration_min)
                    if len(slots) >= 20:
                        break

        found = bool(slots)
        summary = (
            f"Found {len(slots)} available slot(s) on {target_date.strftime('%A, %B %d')}."
            if found
            else f"No available slots found on {target_date.strftime('%A, %B %d')}."
        )
        return SQLResult(
            handler="doctor_availability",
            found=found,
            rows=slots[:20],
            summary=summary,
            meta={"target_date": target_date.isoformat()},
        )

    # ── Patient's own appointments ─────────────────────────────────────────

    @staticmethod
    def patient_appointments(clinic: Any, nlu: Any, *, patient: Any = None) -> SQLResult:
        from apps.appointments.models import Appointment, AppointmentStatus

        if patient is None:
            return SQLResult(
                handler="patient_appointments",
                found=False,
                summary="Patient not authenticated — cannot retrieve appointments.",
            )

        qs = (
            Appointment.objects
            .filter(clinic=clinic, patient=patient)
            .select_related("doctor", "service")
            .order_by("-start_time")
        )
        # Upcoming by default
        upcoming = qs.filter(
            start_time__gte=timezone.now(),
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )[:10]

        rows = [
            {
                "id": str(a.id),
                "doctor": a.doctor.full_name,
                "service": a.service.name if a.service else "",
                "start_time": a.start_time.isoformat(),
                "status": a.status,
                "confirmation_code": a.confirmation_code,
            }
            for a in upcoming
        ]
        found = bool(rows)
        summary = f"Patient has {len(rows)} upcoming appointment(s)." if found else "No upcoming appointments found."
        return SQLResult(handler="patient_appointments", found=found, rows=rows, summary=summary)

    # ── Insurance acceptance ───────────────────────────────────────────────

    @staticmethod
    def insurance_accepted(clinic: Any, nlu: Any) -> SQLResult:
        from apps.insurance.models import InsurancePlan

        entities = nlu.entities
        resolved = nlu.resolved_ids

        qs = InsurancePlan.objects.filter(clinic=clinic, is_deleted=False, is_accepted=True)

        if resolved.insurance_plan_id:
            ids = (
                resolved.insurance_plan_id
                if isinstance(resolved.insurance_plan_id, list)
                else [resolved.insurance_plan_id]
            )
            qs = qs.filter(id__in=ids)
        elif entities.insurance_provider:
            providers = (
                entities.insurance_provider
                if isinstance(entities.insurance_provider, list)
                else [entities.insurance_provider]
            )
            from django.db.models import Q
            q = Q()
            for p in providers:
                q |= Q(provider_name__icontains=p) | Q(plan_name__icontains=p)
            qs = qs.filter(q)

        plans = list(qs[:20])
        rows = [
            {
                "id": str(p.id),
                "provider_name": p.provider_name,
                "plan_name": p.plan_name,
                "plan_type": p.plan_type,
                "is_accepted": p.is_accepted,
                "notes": p.notes[:200] if p.notes else "",
            }
            for p in plans
        ]
        found = bool(rows)
        if found:
            names = ", ".join(r["provider_name"] for r in rows[:3])
            summary = f"Accepted insurance plan(s): {names}."
        else:
            q_text = ""
            if entities.insurance_provider:
                q_text = f" for '{entities.insurance_provider}'"
            summary = f"No accepted insurance plans found{q_text}."
        return SQLResult(handler="insurance_accepted", found=found, rows=rows, summary=summary)

    # ── Clinic hours ───────────────────────────────────────────────────────

    @staticmethod
    def clinic_hours(clinic: Any, nlu: Any) -> SQLResult:  # noqa: ARG004
        from apps.clinics.models import ClinicBusinessHours

        DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        hours_qs = ClinicBusinessHours.objects.filter(clinic=clinic).order_by("day_of_week")
        rows = [
            {
                "day": DAY_NAMES[h.day_of_week],
                "open_time": h.open_time.strftime("%I:%M %p") if h.open_time else None,
                "close_time": h.close_time.strftime("%I:%M %p") if h.close_time else None,
                "is_closed": h.is_closed,
            }
            for h in hours_qs
        ]
        found = bool(rows)
        summary = f"Clinic hours loaded for {len(rows)} day(s)." if found else "No clinic hours configured."
        return SQLResult(handler="clinic_hours", found=found, rows=rows, summary=summary)

    # ── Clinic location ────────────────────────────────────────────────────

    @staticmethod
    def clinic_location(clinic: Any, nlu: Any) -> SQLResult:  # noqa: ARG004
        address = clinic.address or {}
        rows = [{"name": clinic.name, "address": address, "phone": clinic.phone, "email": clinic.email}]
        summary = f"Clinic location: {address.get('street', '')} {address.get('city', '')}".strip()
        return SQLResult(handler="clinic_location", found=True, rows=rows, summary=summary or "Location info loaded.")

    # ── Services offered ───────────────────────────────────────────────────

    @staticmethod
    def services_offered(clinic: Any, nlu: Any) -> SQLResult:
        from apps.services.models import Service

        qs = Service.objects.filter(clinic=clinic, is_deleted=False, is_active=True)

        entities = nlu.entities
        resolved = nlu.resolved_ids

        if resolved.service_id:
            qs = qs.filter(id=resolved.service_id)
        elif entities.service:
            qs = qs.filter(name__icontains=entities.service)

        services = list(qs[:20])
        rows = [
            {
                "id": str(s.id),
                "name": s.name,
                "description": s.description[:300] if s.description else "",
                "duration_min": s.duration_min,
                "price": f"${s.price_cents / 100:.2f}" if s.price_cents else "Contact for pricing",
            }
            for s in services
        ]
        found = bool(rows)
        summary = (
            f"Services offered: {', '.join(r['name'] for r in rows[:5])}."
            if found
            else "No services found."
        )
        return SQLResult(handler="services_offered", found=found, rows=rows, summary=summary)
