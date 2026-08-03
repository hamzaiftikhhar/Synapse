"""Per-mode step sequences for the booking wizard.

Patient-facing booking paths (chosen on the PATH step) map to modes:

  first_available  → general         (date → time; doctor auto-assigned on slot)
  help_choose      → specialty_first (specialty → doctor → date → time)
  know_doctor      → choose_doctor   (doctor → date → time)

Clinic WidgetSettings.booking.mode remains a fallback default only.
"""

from __future__ import annotations

from apps.chatbot.booking.state import BookingStep

# Ordered steps after PATH selection (PATH itself is shared / not in these lists).
MODE_STEPS: dict[str, list[BookingStep]] = {
    "specialty_first": [
        BookingStep.SPECIALTY,
        BookingStep.DOCTOR,
        BookingStep.DATE,
        BookingStep.TIME,
        BookingStep.DETAILS,
        BookingStep.OTP,
        BookingStep.CONFIRMED,
    ],
    "choose_doctor": [
        BookingStep.DOCTOR,
        BookingStep.DATE,
        BookingStep.TIME,
        BookingStep.DETAILS,
        BookingStep.OTP,
        BookingStep.CONFIRMED,
    ],
    # Earliest clinic appointment — no specialty/doctor picker; slot binds a doctor.
    "first_available": [
        BookingStep.DATE,
        BookingStep.TIME,
        BookingStep.DETAILS,
        BookingStep.OTP,
        BookingStep.CONFIRMED,
    ],
    "general": [
        BookingStep.DATE,
        BookingStep.TIME,
        BookingStep.DETAILS,
        BookingStep.OTP,
        BookingStep.CONFIRMED,
    ],
}

# UI path key → internal mode
PATH_TO_MODE: dict[str, str] = {
    "first_available": "general",
    "help_choose": "specialty_first",
    "know_doctor": "choose_doctor",
}

PATH_OPTIONS = [
    {
        "id": "first_available",
        "emoji": "🏥",
        "title": "First Available Appointment",
        "description": "Book the soonest open slot — the clinic assigns a doctor.",
        "recommended": True,
    },
    {
        "id": "help_choose",
        "emoji": "🩺",
        "title": "Help Me Choose a Doctor",
        "description": "Pick a specialty (or symptom area), then a doctor.",
        "recommended": False,
    },
    {
        "id": "know_doctor",
        "emoji": "👨‍⚕️",
        "title": "I Have a Doctor in Mind",
        "description": "Skip specialty and choose your doctor directly.",
        "recommended": False,
    },
]


def steps_for_mode(mode: str) -> list[BookingStep]:
    return list(MODE_STEPS.get(mode, MODE_STEPS["specialty_first"]))


def first_step(mode: str) -> BookingStep:
    return steps_for_mode(mode)[0]


def next_step(mode: str, current: str) -> BookingStep | None:
    if current == BookingStep.PATH.value:
        return first_step(mode)
    steps = steps_for_mode(mode)
    try:
        idx = next(i for i, s in enumerate(steps) if s.value == current)
    except StopIteration:
        return steps[0]
    if idx + 1 >= len(steps):
        return None
    return steps[idx + 1]


def prev_step(mode: str, current: str) -> BookingStep | None:
    if current == BookingStep.PATH.value:
        return None
    steps = steps_for_mode(mode)
    try:
        idx = next(i for i, s in enumerate(steps) if s.value == current)
    except StopIteration:
        return BookingStep.PATH
    if idx <= 0:
        return BookingStep.PATH
    return steps[idx - 1]


def step_index(mode: str, current: str) -> tuple[int, int]:
    """Progress after PATH. PATH itself reports (0, total)."""
    steps = steps_for_mode(mode)
    visible = [s for s in steps if s != BookingStep.CONFIRMED]
    if current == BookingStep.PATH.value:
        return 0, len(visible)
    try:
        idx = next(i for i, s in enumerate(visible) if s.value == current)
        return idx + 1, len(visible)
    except StopIteration:
        return len(visible), len(visible)


def resolve_mode_from_path(path_id: str) -> str:
    key = (path_id or "").strip().lower()
    return PATH_TO_MODE.get(key, "specialty_first")
