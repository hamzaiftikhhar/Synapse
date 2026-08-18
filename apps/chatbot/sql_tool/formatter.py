"""Format SQL tool rows into user-facing text (sql_fast lane — no LLM)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _day_label(row: dict[str, Any] | None) -> str:
    """"Thursday, August 20" from a row's ISO date, or "" if unparseable."""
    raw = str((row or {}).get("date") or "")[:10]
    if not raw:
        return ""
    try:
        day = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return ""
    return f"{day.strftime('%A')}, {day.strftime('%B')} {day.day}"


def _format_hours_grouped(rows: list[dict[str, Any]]) -> str:
    """Compress repeated schedules into patient-facing ranges."""
    open_days = [r for r in rows if not r.get("is_closed") and r.get("open_time")]
    closed = [r for r in rows if r.get("is_closed")]
    if not open_days:
        return "Hours aren't listed — message us and we'll confirm."

    def _fmt_time(t: str | None) -> str:
        if not t:
            return ""
        return str(t).replace(":00", "").strip()

    groups: list[tuple[str, str, str]] = []
    for row in open_days:
        key = f"{row.get('open_time')}|{row.get('close_time')}"
        if groups and groups[-1][0] == key:
            groups[-1] = (key, groups[-1][1], row["day"])
        else:
            groups.append((key, row["day"], row["day"]))

    parts: list[str] = []
    for key, start_day, end_day in groups:
        open_t, close_t = key.split("|", 1)
        span = start_day if start_day == end_day else f"{start_day}–{end_day}"
        parts.append(f"{span} {_fmt_time(open_t)}–{_fmt_time(close_t)}")

    text = "We're open " + ", ".join(parts) + "."
    if closed:
        closed_names = ", ".join(r["day"] for r in closed)
        text += f" Closed {closed_names}."
    return text


def _format_availability(rows: list[dict[str, Any]], *, recommended: dict | None = None) -> str:
    # Name the day. Asking for "thurs" and being offered an unlabelled 12:00 PM
    # gave no way to notice the slots were for a different date than requested.
    day = _day_label(recommended or (rows[0] if rows else None))
    on_day = f" on {day}" if day else ""
    if recommended:
        doc = recommended.get("doctor") or recommended.get("doctor_name") or "A doctor"
        when = recommended.get("time") or recommended.get("label") or ""
        return f"Earliest opening{on_day}: {doc} at {when}."
    preview = rows[:3]
    if len(preview) == 1:
        r = preview[0]
        return (
            f"{r.get('doctor', 'A doctor')} has an opening{on_day} "
            f"at {r.get('time', r.get('start', ''))}."
        )
    lines = [f"{r.get('doctor')} at {r.get('time', r.get('start', ''))}" for r in preview]
    more = f" (+{len(rows) - 3} more)" if len(rows) > 3 else ""
    return f"Openings{more}{on_day}: " + "; ".join(lines) + "."

# Backend-owned honesty copy — never invent call-the-clinic availability
EMPTY_AVAILABILITY = (
    "I couldn't retrieve availability right now. "
    "You can try another day, or tap Start Booking to pick a time."
)
EMPTY_DOCTORS = (
    "I couldn't find matching doctors for that. "
    "Try a specialty name, or ask me to list our doctors."
)
EMPTY_GENERIC = (
    "I couldn't find clinic data for that request. "
    "Try asking about hours, insurance, doctors, or booking."
)
SQL_FAILURE = (
    "I couldn't retrieve that clinic information right now. Please try again in a moment."
)


def format_sql_results(results: list[dict[str, Any]]) -> str:
    """Turn structured SQL rows into a concise chatbot reply without an LLM."""
    if not results:
        return EMPTY_GENERIC

    parts: list[str] = []
    for block in results:
        handler = block.get("handler", "")
        summary = (block.get("summary") or "").strip()
        rows = block.get("rows") or []
        found = block.get("found", bool(rows))

        if handler == "clinic_hours":
            if not rows:
                parts.append(summary or SQL_FAILURE)
                continue
            parts.append(_format_hours_grouped(rows))
            continue

        if handler == "clinic_location" and rows:
            row = rows[0]
            address_bits = [
                row.get("street", ""),
                row.get("city", ""),
                row.get("state", ""),
                row.get("zip", ""),
            ]
            address = ", ".join(bit for bit in address_bits if bit)
            phone = row.get("phone") or ""
            text = f"We're located at {address}." if address else summary
            if phone:
                text += f" You can reach us at {phone}."
            parts.append(text or SQL_FAILURE)
            continue

        if handler == "doctor_availability":
            if not found or not rows:
                # The handler's own wording wins when it resolved the request
                # and is telling the patient something specific — the date has
                # passed, the month isn't open yet, the expression was
                # ambiguous. Generic copy would erase that answer.
                meta = block.get("meta") or {}
                if summary and (meta.get("authoritative_summary") or "No available" in summary):
                    parts.append(summary)
                else:
                    parts.append(EMPTY_AVAILABILITY)
                continue
            recommended = rows[0] if rows else None
            parts.append(_format_availability(rows, recommended=recommended))
            continue

        if handler == "search_doctors":
            if not found or not rows:
                parts.append(EMPTY_DOCTORS)
                continue
            preview = rows[:3]
            lines = [
                f"- {r['full_name']}"
                + (f" ({', '.join(r['specialties'])})" if r.get("specialties") else "")
                for r in preview
            ]
            parts.append(
                "Here are a few doctors who may be a good fit:\n" + "\n".join(lines)
            )
            continue

        if handler == "list_specialties" and rows:
            names = ", ".join(r["name"] for r in rows[:8])
            parts.append(f"Our specialties include: {names}.")
            continue

        if handler == "insurance_accepted":
            if not found or not rows:
                parts.append(
                    summary
                    or "I couldn't find matching insurance plans in our records for that."
                )
                continue
            # Named miss / mixed results already have an honest Yes/No summary.
            # Browse (accepted-only) still uses the searchable card list intro.
            if any(not row.get("is_accepted", True) for row in rows):
                parts.append(summary or "We currently don't accept that plan.")
            else:
                parts.append("Search your plan below.")
            continue

        if handler == "services_offered":
            if not rows:
                parts.append(summary or "I couldn't find services for that request.")
                continue
            # Cards render the list — keep prose minimal for patients
            parts.append("Pick a service below.")
            continue

        if handler == "patient_appointments":
            if not found or not rows:
                parts.append(
                    summary
                    or (
                        "To cancel or reschedule, please verify your phone number first "
                        "so I can pull up your appointments."
                    )
                )
                continue
            lines = [
                f"- {r['doctor']} on {r.get('when') or r.get('start_time')} ({r['status']})"
                for r in rows[:5]
            ]
            parts.append("Your upcoming appointments:\n" + "\n".join(lines))
            continue

        if summary:
            # Prefer honesty over inventing — strip call-clinic inventions for empty DB
            if not found and "DB query failed" in summary:
                parts.append(SQL_FAILURE)
            else:
                parts.append(summary)

    return "\n\n".join(parts) if parts else EMPTY_GENERIC
