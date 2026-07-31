"""
Build frontend UI metadata from ChatEngine results.

The frontend renders rich components (doctor cards, slots, maps, etc.)
from `meta` — no AI logic on the client.
"""

from __future__ import annotations

from typing import Any

from apps.chatbot.nlu.schemas import Intent


def build_ui_meta(
    *,
    clinic: Any,
    intent: str,
    route: str,
    sql_results: list[dict[str, Any]],
    is_emergency: bool = False,
    message: str = "",
    nlu: Any = None,
    booking_commit: bool = False,
    last_doctor: dict[str, Any] | None = None,
    last_specialty: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map SQL handler output + intent to frontend component payloads."""
    meta: dict[str, Any] = {
        "actions": _contextual_actions(
            intent,
            clinic,
            is_emergency,
            has_doctors=False,
            booking_commit=booking_commit,
        ),
    }

    # Book appointment / reschedule → embed wizard in chat (Homey-style)
    if intent in (
        Intent.BOOK_APPOINTMENT.value,
        Intent.RESCHEDULE_APPOINTMENT.value,
    ):
        from apps.chatbot.booking.config import get_booking_config
        from apps.chatbot.booking.discovery import suggest_specialties

        cfg = get_booking_config(clinic)
        suggested, guidance = ([], "")
        if cfg.get("ai_discovery"):
            suggested, guidance = suggest_specialties(clinic, message=message)
        booking: dict[str, Any] = {
            "launch": True,
            "suggested_specialties": suggested,
            "guidance": guidance,
            "reason": message,
        }
        if last_doctor:
            booking["doctor_id"] = last_doctor.get("id")
            booking["doctor_name"] = last_doctor.get("name")
        if last_specialty:
            booking["specialty_id"] = last_specialty.get("id")
            booking["specialty_name"] = last_specialty.get("name")
        meta["booking"] = booking
        # Soft specialty chips still useful; wizard embeds via booking.launch
        if suggested and not booking_commit:
            meta["specialties"] = [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "description": s.get("description") or s.get("plain_label") or "",
                    "doctor_count": s.get("doctor_count"),
                    "recommended": True,
                    "select_message": f"I need a {s.get('name')} doctor",
                }
                for s in suggested[:4]
            ]
        meta["actions"] = _contextual_actions(
            intent,
            clinic,
            is_emergency,
            has_doctors=False,
            booking_commit=True,
            omit_book=True,
        )
        return meta

    has_doctors = False
    for block in sql_results:
        handler = block.get("handler", "")
        rows = block.get("rows") or []

        if handler == "search_doctors" and rows:
            doctors = _dedupe_doctors([_map_doctor(r) for r in rows])[:3]
            meta["doctors"] = doctors
            has_doctors = bool(doctors)

        elif handler == "list_specialties" and rows:
            # Soft list only — never dump 20; prefer when intentionally requested
            mapped = [_map_specialty(r) for r in rows[:6]]
            meta.setdefault("specialties", mapped)

        elif handler == "doctor_availability" and rows:
            # Prefer not dumping many slots into chat — leave for wizard
            pass

        elif handler == "insurance_accepted" and rows:
            meta["insurance"] = [_map_insurance(r) for r in rows[:3]]

        elif handler == "services_offered" and rows:
            meta["services"] = [_map_service(r) for r in rows[:5]]

        elif handler == "clinic_hours" and rows:
            # Prose only — do not emit day cards
            pass

        elif handler == "clinic_location" and rows:
            row = rows[0]
            address = row.get("address") or {}
            street = city = state = zip_code = ""
            if isinstance(address, dict):
                street = address.get("street", "")
                city = address.get("city", "")
                state = address.get("state", "")
                zip_code = address.get("zip", "")
                query = ", ".join(p for p in (street, city, state, zip_code) if p)
            else:
                query = str(address)
            phone = row.get("phone") or getattr(clinic, "phone", "")
            maps_url = (
                f"https://www.google.com/maps/search/?api=1&query={query}" if query else ""
            )
            meta["location"] = {
                "name": row.get("name") or clinic.name,
                "street": street if isinstance(address, dict) else "",
                "city": city if isinstance(address, dict) else "",
                "state": state if isinstance(address, dict) else "",
                "zip": zip_code if isinstance(address, dict) else "",
                "phone": phone,
                "maps_url": maps_url,
            }
            if maps_url:
                meta.setdefault("buttons", []).append(
                    {
                        "id": "maps",
                        "label": "Open in Google Maps",
                        "icon": "MapPin",
                        "behavior": "open_url",
                        "url": maps_url,
                    }
                )
            if phone:
                meta.setdefault("buttons", []).append(
                    {
                        "id": "call",
                        "label": "Call Clinic",
                        "icon": "Phone",
                        "behavior": "call",
                        "phone": phone,
                    }
                )

        elif handler == "patient_appointments" and rows:
            meta["appointments"] = rows

    meta["actions"] = _contextual_actions(
        intent,
        clinic,
        is_emergency,
        has_doctors=has_doctors,
        booking_commit=booking_commit,
    )

    if is_emergency:
        phone = getattr(clinic, "phone", "") or "911"
        meta["buttons"] = [
            {
                "id": "emergency_call",
                "label": "Call Emergency (911)",
                "icon": "Siren",
                "variant": "emergency",
                "behavior": "call",
                "phone": "911",
            },
        ]
        if getattr(clinic, "phone", ""):
            meta["buttons"].append(
                {
                    "id": "clinic_call",
                    "label": "Call Clinic",
                    "icon": "Phone",
                    "behavior": "call",
                    "phone": clinic.phone,
                }
            )

    return meta


def _dedupe_doctors(doctors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for d in doctors:
        key = str(d.get("id") or d.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _contextual_actions(
    intent: str,
    clinic: Any,
    is_emergency: bool,
    *,
    has_doctors: bool = False,
    booking_commit: bool = False,
    omit_book: bool = False,
) -> list[dict[str, Any]]:
    """Action chips under the latest assistant response. Book always; no Main Menu."""
    actions: list[dict[str, Any]] = []

    smart = _smart_action(intent, clinic, is_emergency, has_doctors=has_doctors)
    if smart:
        actions.append(smart)

    # Book Appointment → chat message (never open wizard client-side)
    if not omit_book:
        filled = booking_commit or intent in (
            Intent.BOOK_APPOINTMENT.value,
            Intent.RESCHEDULE_APPOINTMENT.value,
        )
        actions.append(
            {
                "id": "book",
                "label": "Book Appointment",
                "icon": "Calendar",
                "behavior": "message",
                "filled": filled,
                "message": "I would like to book an appointment",
            }
        )

    # Deduplicate by id while preserving order
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for a in actions:
        aid = a.get("id") or ""
        if aid in seen:
            continue
        seen.add(aid)
        unique.append(a)
    return unique


def _smart_action(
    intent: str,
    clinic: Any,
    is_emergency: bool,
    *,
    has_doctors: bool = False,
) -> dict[str, Any] | None:
    if is_emergency or intent == Intent.EMERGENCY.value:
        return {
            "id": "emergency",
            "label": "Emergency Call",
            "icon": "Siren",
            "variant": "emergency",
            "behavior": "call",
            "phone": "911",
        }
    if intent in (Intent.CLINIC_LOCATION.value,):
        return {
            "id": "maps",
            "label": "Get Directions",
            "icon": "MapPin",
            "behavior": "message",
            "message": "Where is the clinic located?",
        }
    if intent in (Intent.CLINIC_HOURS.value,):
        # Hours already answered — offer insurance as situational alternate
        return {
            "id": "insurance",
            "label": "Check Insurance",
            "icon": "Shield",
            "behavior": "message",
            "message": "Do you accept my insurance?",
        }
    if intent in (Intent.DOCTOR_SEARCH.value, Intent.DOCTOR_AVAILABILITY.value):
        if has_doctors:
            return {
                "id": "insurance",
                "label": "Check Insurance",
                "icon": "Shield",
                "behavior": "message",
                "message": "Do you accept my insurance?",
            }
        return {
            "id": "doctors",
            "label": "Find a Doctor",
            "icon": "Stethoscope",
            "behavior": "message",
            "message": "Help me find a doctor",
        }
    if intent in (Intent.INSURANCE_ACCEPTED.value, Intent.INSURANCE_VERIFICATION.value):
        return {
            "id": "insurance",
            "label": "Check Insurance",
            "icon": "Shield",
            "behavior": "message",
            "message": "Do you accept my insurance?",
        }
    if intent in (Intent.SERVICES_OFFERED.value, Intent.PRICING.value):
        return {
            "id": "services",
            "label": "View Services",
            "icon": "BriefcaseMedical",
            "behavior": "message",
            "message": "What services do you offer?",
        }
    if intent in (Intent.MEDICAL_QUESTION.value,):
        return {
            "id": "doctors",
            "label": "Find a Doctor",
            "icon": "Stethoscope",
            "behavior": "message",
            "message": "Help me find a doctor",
        }
    # Default: Find a Doctor
    return {
        "id": "find_doctor",
        "label": "Find a Doctor",
        "icon": "Search",
        "behavior": "message",
        "message": "Help me find a doctor",
    }


def _map_doctor(row: dict[str, Any]) -> dict[str, Any]:
    name = row.get("full_name", "")
    return {
        "id": row.get("id"),
        "name": name,
        "title": row.get("title", ""),
        "bio": row.get("bio", ""),
        "languages": row.get("languages", []),
        "accepting": row.get("is_accepting_patients", True),
        "specialties": row.get("specialties", []),
        "select_message": f"I would like to book an appointment with {name}",
    }


def _map_specialty(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description", ""),
        "doctor_count": row.get("doctor_count", 0),
        "select_message": f"I need a {row.get('name')} doctor",
    }


def _map_slot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{row.get('doctor_id', '')}_{row.get('start', '')}",
        "label": f"{row.get('doctor', 'Doctor')} — {row.get('time', '')}",
        "start": row.get("start", ""),
        "doctor": row.get("doctor", ""),
        "doctor_id": row.get("doctor_id"),
    }


def _map_insurance(row: dict[str, Any]) -> dict[str, Any]:
    provider = row.get("provider_name", "")
    plan = row.get("plan_name", "")
    return {
        "id": row.get("id"),
        "name": provider,
        "plan": plan,
        "notes": row.get("notes", ""),
        "select_message": f"Do you accept {provider}" + (f" {plan}" if plan else "") + "?",
    }


def _map_service(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name", ""),
        "description": row.get("description", ""),
        "price": row.get("price", ""),
        "select_message": f"Tell me more about {row.get('name', 'this service')}",
    }
