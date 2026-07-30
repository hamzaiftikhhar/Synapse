"""Format SQL tool rows into user-facing text (SQL_ONLY routes)."""

from __future__ import annotations

from typing import Any


def format_sql_results(results: list[dict[str, Any]]) -> str:
    """Turn structured SQL rows into a concise chatbot reply without an LLM."""
    if not results:
        return "I couldn't find clinic data for that request. Please call the clinic for help."

    parts: list[str] = []
    for block in results:
        handler = block.get("handler", "")
        summary = (block.get("summary") or "").strip()
        rows = block.get("rows") or []

        if handler == "clinic_hours" and rows:
            open_days = [
                r for r in rows if not r.get("is_closed") and r.get("open_time")
            ]
            closed = [r for r in rows if r.get("is_closed")]
            if open_days:
                # Assume shared hours when identical
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
                    text = (
                        f"Our clinic is open {span} from {hours}."
                    )
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
            parts.append(text)
            continue

        if handler == "doctor_availability" and rows:
            preview = rows[:5]
            lines = [
                f"- {r['doctor']} at {r.get('time', r.get('start', ''))}"
                for r in preview
            ]
            more = f" (+{len(rows) - 5} more)" if len(rows) > 5 else ""
            parts.append(
                f"Available slots{more}:\n" + "\n".join(lines)
            )
            continue

        if handler == "search_doctors" and rows:
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

        if handler == "insurance_accepted" and rows:
            names = ", ".join(
                f"{r['provider_name']}" + (f" ({r['plan_name']})" if r.get("plan_name") else "")
                for r in rows[:5]
            )
            parts.append(f"We accept: {names}.")
            continue

        if handler == "services_offered" and rows:
            lines = [
                f"- {r['name']}"
                + (f" — {r['price']}" if r.get("price") else "")
                for r in rows[:6]
            ]
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
            parts.append(summary)

    return "\n\n".join(parts) if parts else "I couldn't find clinic data for that request."
