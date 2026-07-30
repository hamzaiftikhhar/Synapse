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
) -> dict[str, Any]:
    """Map SQL handler output + intent to frontend component payloads."""
    meta: dict[str, Any] = {
        "persistent_actions": _persistent_actions(intent, clinic, is_emergency),
    }

    for block in sql_results:
        handler = block.get("handler", "")
        rows = block.get("rows") or []

        if handler == "search_doctors" and rows:
            meta["doctors"] = [_map_doctor(r) for r in rows]

        elif handler == "list_specialties" and rows:
            meta.setdefault("specialties", [_map_specialty(r) for r in rows])

        elif handler == "doctor_availability" and rows:
            meta["time_slots"] = [_map_slot(r) for r in rows]
            if block.get("meta", {}).get("target_date"):
                meta["booking"] = {
                    "step": "time",
                    "target_date": block["meta"]["target_date"],
                }

        elif handler == "insurance_accepted" and rows:
            meta["insurance"] = [_map_insurance(r) for r in rows]

        elif handler == "services_offered" and rows:
            meta["services"] = [_map_service(r) for r in rows]

        elif handler == "clinic_hours" and rows:
            meta["hours"] = rows
            meta.setdefault("buttons", []).extend(
                [
                    {
                        "id": "book",
                        "label": "Book Appointment",
                        "behavior": "message",
                        "message": "I would like to book an appointment",
                    }
                ]
            )

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
            maps_url = f"https://www.google.com/maps/search/?api=1&query={query}" if query else ""
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
                        "behavior": "open_url",
                        "url": maps_url,
                    }
                )
            if phone:
                meta.setdefault("buttons", []).append(
                    {
                        "id": "call",
                        "label": "Call Clinic",
                        "behavior": "call",
                        "phone": phone,
                    }
                )

        elif handler == "patient_appointments" and rows:
            meta["appointments"] = rows

    # Intent-based quick replies when no rich component was produced
    if intent == Intent.BOOK_APPOINTMENT.value and "booking" not in meta:
        meta["booking"] = {"step": "start"}
        meta.setdefault("quick_replies", _booking_quick_replies())

    if is_emergency:
        phone = getattr(clinic, "phone", "") or "911"
        meta["buttons"] = [
            {
                "id": "emergency_call",
                "label": "Call Emergency (911)",
                "behavior": "call",
                "phone": "911",
            },
        ]
        if getattr(clinic, "phone", ""):
            meta["buttons"].append(
                {
                    "id": "clinic_call",
                    "label": "Call Clinic",
                    "behavior": "call",
                    "phone": clinic.phone,
                }
            )

    return meta


def _persistent_actions(intent: str, clinic: Any, is_emergency: bool) -> list[dict[str, Any]]:
    """Always-visible action bar items."""
    actions = [
        {
            "id": "book",
            "label": "Book Appointment",
            "behavior": "message",
            "message": "I would like to book an appointment",
        },
        {
            "id": "menu",
            "label": "Main Menu",
            "behavior": "message",
            "message": "Main menu",
        },
    ]

    smart = _smart_action(intent, clinic, is_emergency)
    if smart:
        actions.insert(0, smart)

    return actions


def _smart_action(intent: str, clinic: Any, is_emergency: bool) -> dict[str, Any] | None:
    if is_emergency or intent == Intent.EMERGENCY.value:
        return {
            "id": "emergency",
            "label": "Emergency Call",
            "behavior": "call",
            "phone": "911",
        }
    if intent in (Intent.CLINIC_LOCATION.value,):
        return {
            "id": "maps",
            "label": "Open Google Maps",
            "behavior": "message",
            "message": "Where is the clinic located?",
        }
    if intent in (Intent.CLINIC_HOURS.value,):
        return {
            "id": "hours",
            "label": "Clinic Hours",
            "behavior": "message",
            "message": "What are your clinic hours?",
        }
    if intent in (Intent.DOCTOR_SEARCH.value, Intent.DOCTOR_AVAILABILITY.value):
        return {
            "id": "doctors",
            "label": "Find Doctor",
            "behavior": "message",
            "message": "Help me find a doctor",
        }
    if intent in (Intent.INSURANCE_ACCEPTED.value, Intent.INSURANCE_VERIFICATION.value):
        return {
            "id": "insurance",
            "label": "Check Insurance",
            "behavior": "message",
            "message": "Do you accept my insurance?",
        }
    if intent in (Intent.SERVICES_OFFERED.value, Intent.PRICING.value):
        return {
            "id": "services",
            "label": "View Services",
            "behavior": "message",
            "message": "What services do you offer?",
        }
    return None


def _booking_quick_replies() -> list[dict[str, str]]:
    return [
        {"label": "Doctor first", "message": "Book with a specific doctor"},
        {"label": "By specialty", "message": "Book by specialty"},
        {"label": "General appointment", "message": "Book a general appointment"},
    ]


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
