"""Per-mode step sequences for the booking wizard."""

from __future__ import annotations

from apps.chatbot.booking.state import BookingStep

# Ordered steps after optional discovery guidance (handled in chat, not wizard).
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
    "first_available": [
        BookingStep.SPECIALTY,  # soft filter optional; can skip via clear
        BookingStep.DATE,
        BookingStep.TIME,  # best match auto-picks doctor for slot
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


def steps_for_mode(mode: str) -> list[BookingStep]:
    return list(MODE_STEPS.get(mode, MODE_STEPS["specialty_first"]))


def first_step(mode: str) -> BookingStep:
    return steps_for_mode(mode)[0]


def next_step(mode: str, current: str) -> BookingStep | None:
    steps = steps_for_mode(mode)
    try:
        idx = next(i for i, s in enumerate(steps) if s.value == current)
    except StopIteration:
        return steps[0]
    if idx + 1 >= len(steps):
        return None
    return steps[idx + 1]


def prev_step(mode: str, current: str) -> BookingStep | None:
    steps = steps_for_mode(mode)
    try:
        idx = next(i for i, s in enumerate(steps) if s.value == current)
    except StopIteration:
        return None
    if idx <= 0:
        return None
    return steps[idx - 1]


def step_index(mode: str, current: str) -> tuple[int, int]:
    steps = steps_for_mode(mode)
    # Exclude confirmed from "of N" progress for UX
    visible = [s for s in steps if s != BookingStep.CONFIRMED]
    try:
        idx = next(i for i, s in enumerate(visible) if s.value == current)
        return idx + 1, len(visible)
    except StopIteration:
        return len(visible), len(visible)
