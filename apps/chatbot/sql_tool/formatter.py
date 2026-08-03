"""Format SQL tool rows into user-facing text (sql_fast lane — no LLM)."""

from __future__ import annotations

from typing import Any

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
            open_days = [
                r for r in rows if not r.get("is_closed") and r.get("open_time")
            ]
            closed = [r for r in rows if r.get("is_closed")]
            if open_days:
                first = open_days[0]
                same = all(
                    r.get("open_time") == first.get("open_time")
                    and r.get("close_time") == first.get("close_time")
                    for r in open_days
                )
                day_names = [r["day"] for r in open_days]
                if same and len(open_days) >= 5:
                    span = f"{day_names[0]} through {day_names[-1]}"
                    hours = f"{first.get('open_time')} to {first.get('close_time')}"
                    text = f"Our clinic is open {span} from {hours}."
                else:
                    bits = [
                        f"{r['day']} {r.get('open_time')}–{r.get('close_time')}"
                        for r in open_days
                    ]
                    text = "Our clinic hours: " + "; ".join(bits) + "."
                if closed:
                    text += f" We are closed on {', '.join(r['day'] for r in closed)}."
                text += (
                    " If you need to reach us outside these hours, you can leave a "
                    "message and expect a callback within 24 hours."
                )
                parts.append(text)
            elif summary:
                parts.append(summary)
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
                parts.append(summary if summary and "No available" in summary else EMPTY_AVAILABILITY)
                continue
            preview = rows[:5]
            lines = [
                f"- {r['doctor']} at {r.get('time', r.get('start', ''))}"
                for r in preview
            ]
            more = f" (+{len(rows) - 5} more)" if len(rows) > 5 else ""
            parts.append("Available slots" + more + ":\n" + "\n".join(lines))
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
            # Prefer handler summary (handles accepted + explicitly rejected plans)
            if summary:
                parts.append(summary)
            else:
                accepted = [r for r in rows if r.get("is_accepted", True)]
                names = ", ".join(
                    f"{r['provider_name']}"
                    + (f" ({r['plan_name']})" if r.get("plan_name") else "")
                    for r in accepted[:8]
                )
                parts.append(f"We accept: {names}." if names else summary)
            continue

        if handler == "services_offered":
            if not rows:
                parts.append(summary or "I couldn't find services for that request.")
                continue
            lines = []
            for r in rows[:6]:
                bit = f"- {r['name']}"
                if r.get("price"):
                    bit += f" — {r['price']}"
                dur = r.get("duration_min")
                if dur:
                    bit += f" ({dur} min)"
                lines.append(bit)
            parts.append("Services we offer:\n" + "\n".join(lines))
            continue

        if handler == "patient_appointments" and rows:
            lines = [
                f"- {r['doctor']} on {r['start_time']} ({r['status']})"
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
