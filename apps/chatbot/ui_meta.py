"""
Build frontend UI metadata from ChatEngine results.

The frontend renders rich components (doctor cards, slots, maps, etc.)
from `meta` — no AI logic on the client.
"""

from __future__ import annotations

from typing import Any

from apps.chatbot.nlu.schemas import Intent
from apps.chatbot.sql_tool.utils import DOCTOR_LIST_CEILING


def _entity_nonempty(value: Any) -> bool:
    return value not in (None, "", [], ())


def _nlu_has_schedule_constraints(nlu: Any) -> bool:
    if nlu is None:
        return False
    ents = getattr(nlu, "entities", None)
    if ents is None:
        return False
    return _entity_nonempty(getattr(ents, "date", None)) or _entity_nonempty(
        getattr(ents, "time", None)
    )


def _nlu_has_booking_pins(nlu: Any) -> bool:
    """Who/what/when extracted from THIS message — not leftover session context."""
    if nlu is None:
        return False
    ents = getattr(nlu, "entities", None)
    if ents is None:
        return False
    return any(
        _entity_nonempty(getattr(ents, key, None))
        for key in ("doctor_name", "service", "specialty", "date", "time")
    )


def _has_availability_handler(sql_results: list[dict[str, Any]]) -> bool:
    return any(block.get("handler") == "doctor_availability" for block in sql_results)


def _first_str(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value in (None, ""):
        return None
    return str(value)


def _secondary_booking_offer_action(
    nlu: Any, *, exec_plan_booking: bool
) -> dict[str, Any] | None:
    """A light, tap-to-continue booking chip for a compound message whose
    SECONDARY intent asked to book (e.g. "who are your doctors and can i
    book with dr vance") — the planner's own `booking` flag is driven only
    by the *primary* intent (Phase 47 finding: Intent.BOOK_APPOINTMENT has
    no _INTENT_SQL_TASKS entry and secondary intents don't set
    facts.is_booking_intent), so this request was previously silently a
    no-op with zero acknowledgment anywhere in the response.

    Deliberately never launches the wizard itself — `behavior: "message"`
    just sends a normal chat message, identical in shape and effect to the
    existing generic "Book Appointment" chip below. The *next* turn goes
    through the ordinary booking flow exactly as if the patient had typed
    that message themselves.
    """
    if exec_plan_booking or nlu is None:
        return None
    secondary = getattr(nlu, "secondary_intents", None) or []
    if Intent.BOOK_APPOINTMENT not in secondary:
        return None
    entities = getattr(nlu, "entities", None)
    resolved = getattr(nlu, "resolved_ids", None)
    if entities is None or resolved is None:
        return None

    doctor_id = _first_str(getattr(resolved, "doctor_id", None))
    doctor_name = _first_str(getattr(entities, "doctor_name", None))
    if doctor_id and doctor_name:
        label_name = doctor_name if doctor_name.lower().startswith("dr") else f"Dr. {doctor_name}"
        return {
            "id": "book_secondary",
            "label": f"Book with {label_name}",
            "icon": "Calendar",
            "behavior": "message",
            "filled": False,
            "message": f"I would like to book with {label_name}",
        }

    service_id = getattr(resolved, "service_id", None)
    service_name = _first_str(getattr(entities, "service", None))
    if service_id and service_name:
        return {
            "id": "book_secondary",
            "label": f"Book {service_name}",
            "icon": "Calendar",
            "behavior": "message",
            "filled": False,
            "message": f"I would like to book {service_name}",
        }
    return None


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
    last_service: dict[str, Any] | None = None,
    last_insurance: dict[str, Any] | None = None,
    active_booking: dict[str, Any] | None = None,
    ui_priority: str = "optional",
    doctor_resolution: Any | None = None,
    exec_plan_booking: bool = False,
) -> dict[str, Any]:
    """Map SQL handler output + intent to frontend component payloads."""
    meta: dict[str, Any] = {
        "actions": _contextual_actions(
            intent,
            clinic,
            is_emergency,
            has_doctors=False,
            booking_commit=booking_commit,
            ui_priority=ui_priority,
        ),
    }

    # patient_appointments must be handled before the booking-card early
    # return below (a transactional cancel/reschedule also sets
    # exec_plan.booking=True, e.g. "book a new visit instead") — otherwise
    # that return skips it before the main sql_results loop ever runs it.
    for block in sql_results:
        if block.get("handler") == "patient_appointments":
            appt_rows = block.get("rows") or []
            if (block.get("meta") or {}).get("requires_auth"):
                meta["verify_identity"] = True
            else:
                # Authenticated with zero rows still needs to reach the
                # frontend as an (empty) appointments list — that's what
                # renders the "No upcoming appointments" card instead of
                # silently falling through to a generic text reply.
                meta["appointments"] = [_map_appointment(r) for r in appt_rows]
            break

    # Book appointment / reschedule / cancel → embed wizard in chat (Homey-style),
    # gated exclusively by planner.py's `booking` flag — never by raw intent.
    # The planner already turns transactional requests into booking=True while
    # leaving knowledge-only questions (e.g. "what's your cancellation fee")
    # or refusals (e.g. unknown_doctor_refusal) as booking=False; ui_meta must
    # not re-decide this from `intent` alone, or a refusal response can render
    # next to an active wizard launch. See planner.build_execution_plan for
    # the actual booking-eligibility decision.
    #
    # Exception: when the patient already gave a day/time (or availability SQL
    # ran), show slots — do NOT open the discovery path picker.
    schedule_first = _nlu_has_schedule_constraints(nlu) or _has_availability_handler(
        sql_results
    )
    wants_booking_wizard = exec_plan_booking

    if wants_booking_wizard and not (
        schedule_first
        and intent
        in {
            Intent.BOOK_APPOINTMENT.value,
            Intent.RESCHEDULE_APPOINTMENT.value,
        }
    ):
        from apps.chatbot.routing.signals import is_generic_book_request

        nlu_pins = _nlu_has_booking_pins(nlu)
        named_doctor = False
        named_service = False
        ents = getattr(nlu, "entities", None) if nlu is not None else None
        if ents is not None:
            named_doctor = _entity_nonempty(getattr(ents, "doctor_name", None))
            named_service = _entity_nonempty(getattr(ents, "service", None))
        generic_restart = is_generic_book_request(message) and not nlu_pins
        booking_in_progress = (
            bool(active_booking)
            and active_booking.get("step") != "confirmed"
            and not generic_restart
        )

        suggested, guidance = ([], "")
        if not booking_in_progress:
            from apps.chatbot.booking.config import get_booking_config
            from apps.chatbot.booking.discovery import suggest_specialties

            cfg = get_booking_config(clinic)
            if cfg.get("ai_discovery"):
                suggested, guidance = suggest_specialties(clinic, message=message)

        booking: dict[str, Any] = {
            "launch": not booking_in_progress,
            "suggested_specialties": suggested,
            "guidance": guidance,
            "reason": message,
        }
        if booking_in_progress:
            booking["booking_id"] = active_booking.get("booking_id")
        if last_doctor and not generic_restart:
            booking["doctor_id"] = last_doctor.get("id")
            booking["doctor_name"] = last_doctor.get("name")
        if last_specialty and last_specialty.get("id") and not generic_restart:
            booking["specialty_id"] = last_specialty.get("id")
            booking["specialty_name"] = last_specialty.get("name")
        if last_service and last_service.get("id") and not generic_restart:
            if named_service or not named_doctor:
                booking["service_id"] = last_service.get("id")
                booking["service_name"] = last_service.get("name")
        if last_insurance and last_insurance.get("name"):
            booking["insurance_name"] = last_insurance.get("name")
        meta["booking"] = booking
        # Soft specialty chips still useful; wizard embeds via booking.launch.
        # No select_message here on purpose — the frontend dispatches a
        # structured select_specialty action carrying this id (see
        # specialty-card.tsx), not a synthesized chat message.
        if suggested and not booking_commit:
            meta["specialties"] = [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "description": s.get("description") or s.get("plain_label") or "",
                    "doctor_count": s.get("doctor_count"),
                    "recommended": True,
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
            ui_priority=ui_priority,
        )
        return orchestrate_ui_meta(meta, intent=intent, ui_priority=ui_priority)

    has_doctors = False
    for block in sql_results:
        handler = block.get("handler", "")
        rows = block.get("rows") or []

        if handler == "search_doctors" and rows:
            # Handler already bounds the query (DOCTOR_LIST_CEILING) --
            # this is a ceiling, not a re-truncation, same pattern as the
            # insurance card list below.
            doctors = _dedupe_doctors([_map_doctor(r) for r in rows])[:DOCTOR_LIST_CEILING]
            meta["doctors"] = doctors
            has_doctors = bool(doctors)

        elif handler == "list_specialties" and rows:
            # Soft list only — never dump 20; prefer when intentionally requested
            mapped = [_map_specialty(r) for r in rows[:6]]
            meta.setdefault("specialties", mapped)

        elif handler == "doctor_availability" and rows:
            mapped = [_map_slot(r) for r in _slots_in_scope(rows, block.get("meta"))[:6]]
            if mapped:
                meta["recommended"] = {
                    "type": "slot",
                    "slot": mapped[0],
                    "action": "book_slot",
                    "label": "Book this time",
                }
                meta["time_slots"] = mapped

        elif handler == "insurance_accepted" and rows:
            # Handler already bounds the query (12 accepted, or 12 for a named
            # provider) — [:20] is a ceiling, not a re-truncation, so the new
            # searchable insurance list actually has something to search.
            meta["insurance"] = [_map_insurance(r) for r in rows[:20]]

        elif handler == "services_offered" and rows:
            filter_mode = getattr(nlu, "service_filter_mode", None) if nlu else None
            # Handler already bounds the query ([:20], sql_tool/handlers/
            # services.py) — this is a ceiling, not a re-truncation, same
            # pattern as insurance/doctors. A browse ("what services do you
            # offer") used to cut off at 5 regardless of how many the
            # clinic actually has; a resolved single service ("how much is
            # X") still returns exactly that one.
            limit = 1 if filter_mode == "named" else min(20, len(rows))
            services = [_map_service(r) for r in rows[:limit]]
            if services:
                meta["recommended"] = {
                    "type": "service",
                    "service": services[0],
                    "action": "select_service",
                    "label": f"Book {services[0].get('name', 'this service')}",
                }
            meta["services"] = services

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

        # patient_appointments already handled above, before the
        # booking-card early return.

    meta["actions"] = _contextual_actions(
        intent,
        clinic,
        is_emergency,
        has_doctors=has_doctors,
        booking_commit=booking_commit,
        ui_priority=ui_priority,
    )

    # A compound message's secondary intent asked to book (e.g. "who are
    # your doctors and can i book with dr vance") — the primary intent's
    # own answer above is unaffected; this only adds an explicit, tappable
    # acknowledgment that the booking half of the message was heard.
    # Deliberately unconditional on ui_priority's cross-sell chip policy:
    # that policy exists to suppress *generic* upsell chips, not to hide
    # a direct answer to something the patient explicitly asked in this
    # same message.
    secondary_booking = _secondary_booking_offer_action(
        nlu, exec_plan_booking=exec_plan_booking
    )
    if secondary_booking:
        meta["actions"].append(secondary_booking)

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

    return orchestrate_ui_meta(meta, intent=intent, ui_priority=ui_priority)


def orchestrate_ui_meta(
    meta: dict[str, Any], *, intent: str, ui_priority: str
) -> dict[str, Any]:
    """Backend UI orchestrator — one primary component, progressive disclosure."""
    primary = _pick_primary_component(meta, intent=intent)
    meta["primary_component"] = primary
    meta["recommended_action"] = (meta.get("recommended") or {}).get("action")
    if primary:
        meta = _suppress_competing_components(meta, primary, ui_priority=ui_priority)
    return meta


def _pick_primary_component(meta: dict[str, Any], *, intent: str) -> str | None:
    if meta.get("verify_identity"):
        return "verify_identity"
    # A cancel/reschedule request that resolves real appointments must show
    # those (with their own Cancel/Reschedule actions) ahead of the "start a
    # new booking" wizard — the wizard also gets attached for these intents
    # (see build_ui_meta's booking-card branch, "book a new visit instead"),
    # but it isn't the thing the patient actually asked for.
    if meta.get("appointments"):
        return "appointments"
    if meta.get("booking", {}).get("launch"):
        return "booking"
    if meta.get("time_slots"):
        return "time_slots"
    if meta.get("doctors"):
        return "doctors"
    if meta.get("services"):
        return "services"
    if meta.get("insurance"):
        return "insurance"
    if meta.get("location"):
        return "location"
    return None


def _suppress_competing_components(
    meta: dict[str, Any], primary: str, *, ui_priority: str
) -> dict[str, Any]:
    """Hide secondary UI blocks when a primary component is active."""
    if ui_priority in {"NONE", "INLINE", "EMERGENCY"}:
        meta.pop("specialties", None)
        if primary != "services":
            meta.pop("services", None)
    if primary == "booking":
        meta.pop("specialties", None)
    if primary == "time_slots":
        meta.pop("doctors", None)
    if primary == "services" and meta.get("services") and len(meta["services"]) == 1:
        meta.pop("specialties", None)
    if primary == "insurance":
        meta.pop("services", None)
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


# UIPriority -> which cross-sell chips are allowed this turn. Emergency/booking
# turns already have their own dedicated UI (911 buttons / the wizard) and
# never need the generic smart-action or Book Appointment chip on top of it.
# NONE/INLINE (informational answers, clarify turns) get no cross-sell chips —
# this is the actual card-spam fix; it does not touch the handler's own
# direct-answer card (e.g. the insurance card still renders for NONE).
_CHIP_POLICY: dict[str, dict[str, bool]] = {
    "emergency": {"smart": False, "book": False},
    "booking": {"smart": False, "book": False},
    "primary": {"smart": True, "book": True},
    "optional": {"smart": True, "book": True},
    "inline": {"smart": False, "book": False},
    "none": {"smart": False, "book": False},
}


def _contextual_actions(
    intent: str,
    clinic: Any,
    is_emergency: bool,
    *,
    has_doctors: bool = False,
    booking_commit: bool = False,
    omit_book: bool = False,
    ui_priority: str = "optional",
) -> list[dict[str, Any]]:
    """Action chips under the latest assistant response, gated by ui_priority."""
    policy = _CHIP_POLICY.get(ui_priority, _CHIP_POLICY["optional"])
    actions: list[dict[str, Any]] = []

    if policy["smart"]:
        smart = _smart_action(intent, clinic, is_emergency, has_doctors=has_doctors)
        if smart:
            actions.append(smart)

    # Book Appointment → chat message (never open wizard client-side)
    if not omit_book and policy["book"]:
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
        return None
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
        return None
    if intent in (Intent.SERVICES_OFFERED.value, Intent.PRICING.value):
        # Cards already shown — no redundant View Services chip
        return None
    if intent in (Intent.MEDICAL_QUESTION.value,):
        return {
            "id": "doctors",
            "label": "Find a Doctor",
            "icon": "Stethoscope",
            "behavior": "message",
            "message": "Help me find a doctor",
        }
    # Default: no chip spam on informational turns
    return None


def _map_doctor(row: dict[str, Any]) -> dict[str, Any]:
    name = row.get("full_name", "")
    return {
        "id": row.get("id"),
        "name": name,
        "title": row.get("title", ""),
        "bio": row.get("bio", ""),
        "photo_url": row.get("photo_url", ""),
        "languages": row.get("languages", []),
        "accepting": row.get("is_accepting_patients", True),
        "specialties": row.get("specialties", []),
        "select_message": f"I would like to book an appointment with {name}",
    }


def _map_specialty(row: dict[str, Any]) -> dict[str, Any]:
    # No select_message -- the frontend dispatches a structured
    # select_specialty action carrying this id (specialty-card.tsx), not a
    # synthesized chat message.
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description", ""),
        "doctor_count": row.get("doctor_count", 0),
    }


def _slots_in_scope(
    rows: list[dict[str, Any]], meta: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Drop slots the patient's question doesn't cover.

    A chip is one tap from a real appointment, so this is a hard invariant
    rather than a display nicety: two bookings in the production logs were
    made on 19 August by patients who had asked about November and January.
    Nothing renders unless the temporal layer resolved a scope and the slot
    falls inside it.
    """
    meta = meta or {}
    start = meta.get("scope_start")
    end = meta.get("scope_end")
    if "temporal_status" in meta and not meta.get("temporal_searchable"):
        return []
    if not start or not end:
        return rows
    kept = []
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not day or start <= day <= end:
            kept.append(row)
    return kept


def _map_slot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{row.get('doctor_id', '')}_{row.get('start', '')}",
        "label": f"{row.get('doctor', 'Doctor')} — {row.get('time', '')}",
        "start": row.get("start", ""),
        "end": row.get("end", ""),
        "date": row.get("date", ""),
        "time": row.get("time", ""),
        "doctor": row.get("doctor", ""),
        "doctor_id": row.get("doctor_id"),
    }


def _map_appointment(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "doctor": row.get("doctor", ""),
        "doctor_id": row.get("doctor_id"),
        "service": row.get("service", ""),
        "start_time": row.get("start_time", ""),
        "end_time": row.get("end_time", ""),
        "when": row.get("when", ""),
        "status": row.get("status", ""),
        "confirmation_code": row.get("confirmation_code", ""),
    }


def _map_insurance(row: dict[str, Any]) -> dict[str, Any]:
    provider = row.get("provider_name", "")
    plan = row.get("plan_name", "")
    accepted = bool(row.get("is_accepted", True))
    mapped: dict[str, Any] = {
        "id": row.get("id"),
        "name": provider,
        "plan": plan,
        "notes": row.get("notes", ""),
        "is_accepted": accepted,
    }
    if accepted:
        mapped["select_message"] = f"Continue booking with {provider}" + (
            f" {plan}" if plan else ""
        )
    return mapped


def _map_service(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "name": row.get("name", ""),
        "description": row.get("description", ""),
        "duration_min": row.get("duration_min"),
        "price_cents": row.get("price_cents"),
        "category": row.get("category", ""),
        "price": row.get("price", ""),
        "select_message": f"I would like to book {row.get('name', 'this service')}",
    }
