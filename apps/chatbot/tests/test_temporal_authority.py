"""Temporal authority: the LLM interprets, deterministic code decides.

Every case here comes from a production transcript in `logs/chat/`, using the
exact entity payloads the live NLU produced. The failures they pin were not
parse bugs — they were authority bugs. The model emitted ``2023-11-17`` for
"16 nov friday", moving the patient's own day so the weekday would fit a year
they never said; it emitted ``2023-10-16`` for "16 oct friday", which is a
Monday. Two real appointments were booked on 19 August by patients who had
asked about November and January.

The five invariants below are what stop that, and each class defends one.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from apps.chatbot.nlu.schemas import ExtractedEntities, Intent, NLUResult, ResolvedIds
from apps.chatbot.sql_tool.base import SQLContext
from apps.chatbot.sql_tool.handlers.doctors import doctor_availability
from apps.chatbot.temporal import (
    TemporalPrecision,
    TemporalStatus,
    resolve_temporal_query,
)
from apps.chatbot.ui_meta import build_ui_meta
from apps.clinics.models import Clinic
from apps.doctors.models import Doctor, DoctorSchedule
from apps.widget.models import WidgetSettings

_TZ = ZoneInfo("America/Los_Angeles")
# The transcript's own day, so weekday arithmetic is reproducible.
_TODAY = date(2026, 8, 18)
# apex-dental's real configured horizon; horizon_end = 2026-09-08.
_HORIZON = 21


def _resolve(entities, *, message, today=_TODAY, horizon=_HORIZON):
    return resolve_temporal_query(
        date_entities=entities or [],
        today=today,
        horizon_days=horizon,
        message=message,
        tz=_TZ,
    )


class Invariant1ExplicitDateWinsTests(TestCase):
    """An explicit calendar date is never overridden by a weekday, a relative
    date, or an LLM-normalized value."""

    def test_16_oct_friday_means_october_16_not_the_next_friday(self):
        scope = _resolve(
            ["2023-10-16", "friday"], message="book me with dr aris 16 oct friday"
        )
        self.assertEqual(scope.start, date(2026, 10, 16))
        self.assertEqual(scope.precision, TemporalPrecision.EXPLICIT_DATE)

    def test_16_oct_friday_is_internally_consistent_so_no_conflict(self):
        scope = _resolve(
            ["2023-10-16", "friday"], message="book me with dr aris 16 oct friday"
        )
        self.assertEqual(scope.start.strftime("%A"), "Friday")
        self.assertFalse(scope.conflict)

    def test_16_nov_friday_keeps_the_date_and_records_the_disagreement(self):
        # November 16 2026 is a Monday. The date the patient gave wins; we do
        # not silently slide to Friday November 20.
        scope = _resolve(
            ["2023-11-17", "friday"], message="book me with dr aris 16 nov friday"
        )
        self.assertEqual(scope.start, date(2026, 11, 16))
        self.assertTrue(scope.conflict)
        self.assertEqual(scope.conflict_weekday, "Friday")

    def test_the_models_day_shift_is_never_adopted(self):
        # The NLU said the 17th; the patient said the 16th.
        scope = _resolve(
            ["2023-11-17", "friday"], message="book me with dr aris 16 nov friday"
        )
        self.assertNotEqual(scope.start.day, 17)

    def test_explicit_date_outranks_a_weekday_regardless_of_order(self):
        message = "book me with dr aris 16 oct friday"
        forward = _resolve(["friday", "2023-10-16"], message=message)
        reverse = _resolve(["2023-10-16", "friday"], message=message)
        self.assertEqual(forward.start, reverse.start)
        self.assertEqual(forward.start, date(2026, 10, 16))

    def test_precision_ordering_is_explicit_then_month_then_weekday(self):
        self.assertLess(TemporalPrecision.EXPLICIT_DATE, TemporalPrecision.MONTH)
        self.assertLess(TemporalPrecision.MONTH, TemporalPrecision.WEEKDAY)
        self.assertLess(TemporalPrecision.WEEKDAY, TemporalPrecision.RELATIVE)


class Invariant2NoSilentSubstitutionTests(TestCase):
    """A recognized-but-unresolvable constraint never becomes another date."""

    def test_12_jan_with_no_nlu_entity_still_resolves_from_the_message(self):
        # The live NLU returned date=None for this exact sentence one minute
        # after returning "12-Jan" for it. The message is the source of truth.
        scope = _resolve([], message="is there any slot available on 12-Jan")
        self.assertEqual(scope.start, date(2027, 1, 12))

    def test_coming_januray_typo_asks_instead_of_scanning_forward(self):
        scope = _resolve([], message="is there any slot available for coming januray")
        self.assertIs(scope.status, TemporalStatus.UNRESOLVED)
        self.assertIsNone(scope.start)

    def test_coming_feb_resolves_to_next_february(self):
        scope = _resolve([], message="is there any slot available for coming feb")
        self.assertEqual(scope.start, date(2027, 2, 1))
        self.assertEqual(scope.end, date(2027, 2, 28))

    def test_a_half_typed_year_is_not_completed_for_the_patient(self):
        scope = _resolve(
            ["13-January-2023"],
            message="is there any slot available on 13-January-202",
        )
        self.assertIs(scope.status, TemporalStatus.UNRESOLVED)

    def test_genuinely_unconstrained_requests_still_scan_forward(self):
        for message in ("any doctor free?", "is there any", "may I book something"):
            scope = _resolve([], message=message)
            self.assertIs(scope.status, TemporalStatus.UNSPECIFIED, msg=message)

    def test_asap_is_preserved_as_a_forward_scan(self):
        scope = _resolve(["asap"], message="I need something asap")
        self.assertIs(scope.status, TemporalStatus.UNSPECIFIED)

    def test_sun_damage_is_not_a_sunday_constraint(self):
        scope = _resolve([], message="do you treat sun damage")
        self.assertIs(scope.status, TemporalStatus.UNSPECIFIED)


class HyphenAndCompactFormatTests(TestCase):
    def test_hyphenated_and_spaced_forms_all_resolve(self):
        cases = {
            "is there any slot available on 12-Jan": date(2027, 1, 12),
            "is there any slot available on 12-JAn": date(2027, 1, 12),
            "is there any slot available on 12-January": date(2027, 1, 12),
            "is there any slot available on 13-January": date(2027, 1, 13),
            "anything on 16 oct": date(2026, 10, 16),
            "anything on jan 12": date(2027, 1, 12),
            "anything on december 12": date(2026, 12, 12),
        }
        for message, expected in cases.items():
            scope = _resolve([], message=message, horizon=900)
            self.assertEqual(scope.start, expected, msg=message)

    def test_a_past_year_the_patient_spelled_out_is_reported_as_past(self):
        for message, entity in (
            ("is there any slot available on 13-January-2024", "2024-01-13"),
            ("is there any slot available on 13-January-2025", "2025-01-13"),
        ):
            scope = _resolve([entity], message=message)
            self.assertIs(scope.status, TemporalStatus.PAST, msg=message)

    def test_iso_grounding_survives_a_zero_padded_month(self):
        # "2024-01-13" is a faithful normalization of "13-January-2024" even
        # though the literal token "01" appears nowhere in the message.
        scope = _resolve(
            ["2024-01-13"], message="is there any slot available on 13-January-2024"
        )
        self.assertIsNotNone(scope.start)
        self.assertEqual(scope.start, date(2024, 1, 13))

    def test_labels_carry_the_year_when_it_is_not_this_year(self):
        scope = _resolve(
            ["2023-12-12"], message="is there any slot available on 12-dec-2023"
        )
        self.assertIn("2023", scope.scope_label)


class WeekdayOrdinalAmbiguityTests(TestCase):
    """"tuesday 2" must not quietly become "next Tuesday"."""

    def test_tuesday_25_uses_the_day_of_month(self):
        scope = _resolve(["tuesday"], message="book me with dr aris on tuesday 25")
        self.assertEqual(scope.start, date(2026, 8, 25))

    def test_tuesday_1_resolves_to_the_september_tuesday(self):
        scope = _resolve(["Tuesday"], message="book me with dr aris on tuesday 1")
        self.assertEqual(scope.start, date(2026, 9, 1))

    def test_tuesday_2_is_ambiguous_rather_than_next_tuesday(self):
        scope = _resolve(["Tuesday"], message="book me with dr aris on tuesday 2")
        self.assertIs(scope.status, TemporalStatus.AMBIGUOUS)
        self.assertIsNone(scope.start)

    def test_three_different_questions_do_not_get_one_answer(self):
        answers = {
            _resolve(["Tuesday"], message=f"book me with dr aris on tuesday {n}").start
            for n in (25, 2, 1)
        }
        self.assertEqual(len(answers), 3)

    def test_a_clock_time_after_a_weekday_is_not_a_day_of_month(self):
        scope = _resolve(["Tuesday"], message="book me on tuesday at 2pm")
        self.assertIs(scope.status, TemporalStatus.RESOLVED)
        self.assertEqual(scope.start.weekday(), 1)


def _nlu(*, dates=None, times=None) -> NLUResult:
    return NLUResult(
        intent=Intent.DOCTOR_AVAILABILITY,
        confidence=0.9,
        entities=ExtractedEntities(date=dates, time=times),
        resolved_ids=ResolvedIds(),
        needs_sql=True,
    )


class _AvailabilityCase(TestCase):
    horizon = 21

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug=f"authority-{self._testMethodName[:30]}",
            name="Authority Clinic",
            email="authority@clinic.com",
            phone="+12125550041",
            timezone="America/Los_Angeles",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic,
            configuration={"booking": {"date_horizon_days": self.horizon}},
        )
        self.doctor = Doctor.objects.create(
            clinic=self.clinic,
            full_name="Dr. Aris Thorne",
            is_active=True,
            is_accepting_patients=True,
        )
        for weekday in range(7):
            DoctorSchedule.objects.create(
                clinic=self.clinic,
                doctor=self.doctor,
                day_of_week=weekday,
                start_time=time(8, 0),
                end_time=time(17, 0),
                slot_duration_min=30,
            )

    def run_handler(self, message, dates=None, times=None):
        return doctor_availability(
            SQLContext(
                clinic=self.clinic, nlu=_nlu(dates=dates, times=times), message=message
            )
        )


class Invariant3RefusalBlocksSlotsTests(_AvailabilityCase):
    """UNRESOLVED / PAST / BEYOND_HORIZON / AMBIGUOUS never yield slots."""

    def test_no_refusal_status_ever_returns_a_row(self):
        cases = [
            ("is there any slot available for coming januray", None),
            ("is there any slot available on 13-January-2024", ["2024-01-13"]),
            ("is there any slot available for coming december", ["December"]),
            ("book me with dr aris on tuesday 2", ["Tuesday"]),
            ("is there any appointment available in November", ["November"]),
        ]
        for message, dates in cases:
            result = self.run_handler(message, dates=dates)
            self.assertFalse(result.found, msg=message)
            self.assertEqual(result.rows, [], msg=message)
            self.assertFalse(result.meta["temporal_searchable"], msg=message)

    def test_a_refusal_never_produces_a_clickable_chip(self):
        for message, dates in (
            ("is there any slot available for coming januray", None),
            ("is there any slot available for coming december", ["December"]),
            ("book me with dr aris on tuesday 2", ["Tuesday"]),
        ):
            result = self.run_handler(message, dates=dates)
            meta = build_ui_meta(
                clinic=self.clinic,
                intent="doctor_availability",
                route="sql_only",
                sql_results=[result.to_dict()],
            )
            self.assertFalse(meta.get("time_slots"), msg=message)
            self.assertFalse(meta.get("recommended"), msg=message)

    def test_the_earliest_opening_is_not_offered_as_a_substitute(self):
        result = self.run_handler("is there any slot available on 12-Jan")
        tomorrow = (timezone.now().astimezone(_TZ).date() + timedelta(days=1)).strftime(
            "%B"
        )
        self.assertEqual(result.rows, [])
        self.assertNotIn(tomorrow, result.summary)

    def test_a_refusal_asks_for_the_full_date(self):
        result = self.run_handler("is there any slot available for coming januray")
        self.assertIn("couldn't confidently work out", result.summary)


class Invariant4OneDateEverywhereTests(_AvailabilityCase):
    """SQL rows, the stated date, and the chips all agree."""

    def test_every_row_and_chip_lies_inside_the_resolved_scope(self):
        for message, dates in (
            ("can you book an appointment for me on monday afternoon", ["Monday"]),
            ("is there any appointment available for Monday morning", ["monday"]),
            ("anything tomorrow", ["tomorrow"]),
            ("any doctor free", None),
        ):
            result = self.run_handler(message, dates=dates)
            start, end = result.meta["scope_start"], result.meta["scope_end"]
            for row in result.rows:
                self.assertGreaterEqual(row["date"], start, msg=message)
                self.assertLessEqual(row["date"], end, msg=message)
            meta = build_ui_meta(
                clinic=self.clinic,
                intent="doctor_availability",
                route="sql_only",
                sql_results=[result.to_dict()],
            )
            for chip in meta.get("time_slots") or []:
                self.assertGreaterEqual(chip["date"], start, msg=message)
                self.assertLessEqual(chip["date"], end, msg=message)

    def test_the_summary_names_the_same_day_the_rows_belong_to(self):
        result = self.run_handler("anything on monday morning", dates=["monday"])
        self.assertTrue(result.found)
        target = result.meta["target_date"]
        self.assertEqual({row["date"] for row in result.rows}, {target})
        weekday = date.fromisoformat(target).strftime("%A")
        self.assertIn(weekday, result.summary)

    def test_a_weekday_never_leaks_into_the_time_filter_text(self):
        # Logged NLU put "Friday" in the time entity; the reply read
        # "No available slots on Friday, August 21 for Friday."
        result = self.run_handler(
            "book me with dr aris 16 oct friday",
            dates=["2023-10-16", "friday"],
            times=["Friday"],
        )
        self.assertNotIn("for Friday", result.summary)


class Invariant5BookingUsesTheSameStateTests(TestCase):
    """The booking wizard consumes the canonical resolution, never its own."""

    def setUp(self):
        self.clinic = Clinic.objects.create(
            slug="booking-temporal-clinic",
            name="Booking Temporal Clinic",
            email="bt@clinic.com",
            phone="+12125550042",
            timezone="America/Los_Angeles",
        )
        WidgetSettings.objects.create(
            clinic=self.clinic, configuration={"booking": {"date_horizon_days": 21}}
        )

    def _seed(self, text):
        from apps.chatbot.booking.service import BookingService
        from apps.chatbot.booking.state import BookingSession, BookingStep

        session = BookingSession(
            booking_id="bk-temporal",
            clinic_id=str(self.clinic.id),
            mode="full",
            step=BookingStep.DATE.value,
        )
        BookingService._apply_date_time_hint(session, self.clinic, text)
        return session

    def test_an_explicit_date_is_not_downgraded_to_the_next_weekday(self):
        # Previously seeded the next Friday via parse_natural_date(dates[0]).
        session = self._seed("book me with dr aris 16 oct friday")
        today = timezone.now().astimezone(_TZ).date()
        if session.date:
            seeded = date.fromisoformat(session.date)
            self.assertNotEqual(seeded.weekday(), 4)
            self.assertGreater(seeded, today + timedelta(days=21))

    def test_an_unresolvable_date_seeds_nothing(self):
        session = self._seed("is there any slot available for coming januray")
        self.assertIsNone(session.date)

    def test_a_month_request_does_not_seed_a_single_day(self):
        session = self._seed("book me something in december")
        self.assertIsNone(session.date)

    def test_a_plain_weekday_still_seeds_the_date_step(self):
        session = self._seed("book me for monday")
        self.assertIsNotNone(session.date)
        self.assertEqual(date.fromisoformat(session.date).weekday(), 0)

    def test_asap_still_seeds_today(self):
        session = self._seed("I need something asap")
        today = timezone.now().astimezone(_TZ).date()
        self.assertEqual(session.date, today.isoformat())


class ImportOrderTests(TestCase):
    def test_temporal_can_be_imported_before_sql_tool(self):
        """`temporal` importing `sql_tool.utils` at module scope deadlocked:
        the package __init__ pulls in the handlers, one of which imports
        `temporal`. It only ever worked because production happened to import
        `sql_tool` first."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import django;django.setup();"
                "import apps.chatbot.temporal;print('ok')",
            ],
            capture_output=True,
            text=True,
            cwd=".",
            env={
                "PATH": "/usr/bin:/bin",
                "DJANGO_SETTINGS_MODULE": "config.settings.development",
                "HOME": "/tmp",
            },
        )
        self.assertNotIn("circular import", result.stderr)
