"""Doctor and availability SQL handlers."""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

from django.utils import timezone

from apps.chatbot.nlu.languages import resolve_language_codes
from apps.chatbot.routing.signals import mentions_specific_doctor_role
from apps.chatbot.sql_tool.base import SQLContext, SQLResult
from apps.chatbot.sql_tool.utils import (
    DOCTOR_LIST_CEILING,
    build_name_filter,
    clinic_timezone,
    doctor_to_dict,
    entity_ids,
    entity_list,
    parse_natural_date,
)
from apps.chatbot.temporal import TemporalQuery

# Words that appear in booking/availability talk but are never a doctor's
# name — shared by search_doctors and doctor_availability so a fix to one
# can't drift from the other (Phase 41: "should" from "which doctor
# should I see" was extracted as doctor_name and reproduced live — zero
# doctors ever matched a name filter for "should"; previously only one of
# the two copies would have needed the fix, exactly the drift this shared
# constant prevents).
_NAME_NOISE = {
    "please", "doctor", "doctors", "dentist", "help", "find",
    "me", "a", "the", "good", "best", "free", "available", "open",
    "any", "some", "all", "on", "in", "at", "morning", "afternoon",
    "evening", "slot", "slots",
    "should", "would", "could", "can", "will", "shall", "do", "does", "did",
    "i", "my", "see", "seeing",
}


def _slot_at_or_after(slot: dict, floor_time) -> bool:
    start = slot.get("start") or ""
    if not start or floor_time is None:
        return True
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        return dt.time() >= floor_time
    except Exception:
        return True


def _slot_before(slot: dict, ceiling_time) -> bool:
    start = slot.get("start") or ""
    if not start or ceiling_time is None:
        return True
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        return dt.time() < ceiling_time
    except Exception:
        return True


def search_doctors(ctx: SQLContext) -> SQLResult:
    from apps.doctors.models import Doctor

    clinic = ctx.clinic
    nlu = ctx.nlu
    qs = (
        Doctor.objects.filter(clinic=clinic, is_deleted=False, is_active=True)
        .prefetch_related("specialties", "services")
    )

    # A doctor named only to anchor a *different*, competing intent in the
    # same message (e.g. "who are your doctors and can I book with Dr.
    # Vance" — the booking clause, not this browse) must not silently
    # narrow this task — see planner._compute_blocked_entity_fields. A
    # genuine single-clause "tell me about Dr. Vance" still filters
    # normally: this only fires when a doctor-owning intent (booking,
    # availability, reschedule) is also present in the same message.
    doctor_blocked = "doctor_id" in ctx.blocked_entity_fields.get("doctors", frozenset())
    doctor_ids = [] if doctor_blocked else entity_ids(nlu.resolved_ids.doctor_id)
    names: list[str] = []
    name_filter_matched = False
    if doctor_ids:
        qs = qs.filter(id__in=doctor_ids)
    elif not doctor_blocked:
        names = entity_list(nlu.entities.doctor_name)
        # Ignore politeness / filler / availability tokens mistaken for names
        # e.g. "is any dr free on tuesday" → "free" must not filter doctors
        names = [
            n
            for n in names
            if n.lower() not in _NAME_NOISE
            and not all(tok in _NAME_NOISE for tok in n.lower().split())
        ]
        if names:
            named_qs = qs.filter(build_name_filter("full_name", names))
            if named_qs.exists():
                qs = named_qs
                name_filter_matched = True
            # else: survived noise-filtering (not pure filler) but matched
            # no real doctor -- live-confirmed bug: "which doctor HANDLES
            # ROOT canals?" extracts doctor_name="handles root" (neither
            # word is in _NAME_NOISE, so the earlier noise fix doesn't
            # catch it), which matches zero real doctors. Left unfiltered
            # here (mirrors the specs/specialty-name branch below, which
            # already has this exact `named_qs.exists()` safety net) so
            # the capability/specialty resolution fallback further down
            # still gets a chance instead of being blocked by a phantom
            # "a doctor was named" signal.

    # A doctor was explicitly named ("does Dr Lee treat cardiac issues") —
    # keep filtering by that doctor regardless of whether their symptom
    # also maps to a specialty; only a bare, doctor-less symptom mention
    # should trigger the honest "we don't have that" path below.
    #
    # Live-confirmed bug (first instance): this used to re-extract
    # entities.doctor_name raw (entity_list(nlu.entities.doctor_name))
    # instead of reusing the noise-filtered `names` above -- so a
    # hallucinated non-name entity the noise filter correctly stripped
    # from the actual query (e.g. "which doctor CAN DO teeth whitening"
    # -> doctor_name="can do", both tokens in _NAME_NOISE) still counted
    # as "a doctor was named" here. Second instance, fixed alongside this
    # one: `bool(names)` alone isn't enough either -- a hallucinated
    # phrase can survive noise-filtering (no individual token is pure
    # filler) and still match no real doctor ("handles root"). Must
    # reflect whether the name filter *actually matched something real*,
    # not merely whether non-noise text was extracted.
    doctor_named = bool(doctor_ids) or name_filter_matched

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    # Set only when the message itself gave *nothing at all* to go on --
    # no specialty entity, no symptom entity either. Deliberately NOT
    # keyed on resolve_symptom_specialty_ids returning None by itself:
    # that also returns None when the clinic has zero Specialty rows
    # configured at all (a data-completeness gap, not a message-ambiguity
    # one -- its own docstring's stated principle is that a clinic with no
    # specialty catalog is no evidence it lacks the relevant one, so that
    # case must keep falling through to an unfiltered browse, not a
    # clarification). Used after the service/language checks further down
    # to distinguish a genuinely unfiltered request from an explicit
    # "who are your doctors" browse.
    nothing_to_filter_on = False
    if specialty_ids:
        qs = qs.filter(doctor_specialties__specialty_id__in=specialty_ids).distinct()
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            named_qs = qs.filter(build_name_filter("specialties__name", specs)).distinct()
            if named_qs.exists() or doctor_named:
                qs = named_qs
            else:
                # A named specialty that didn't resolve at all
                # (resolved_ids.specialty_id empty, above) AND doesn't
                # literally appear in any real specialty name here --
                # live-confirmed bug: "Do you have any cardiology
                # specialist?" (entities.specialty="Cardiology" set,
                # unresolved) fell straight through to the generic
                # "I couldn't find matching doctors for that" formatter
                # fallback, while "Do you have any heart specialist?"
                # (a concern-map hint, no specialty entity) got the
                # specific, honest "We don't have a specialist for that
                # here" via the branch below -- two phrasings of the same
                # question giving two different answers. Give an
                # explicitly-named specialty the same catalog-aware
                # resolution chain (concern map -> suggest_specialties ->
                # category hint -> Phase 2 catalog match) the bare-symptom
                # path already uses below, both for a better match (a
                # synonym/category hit the literal name filter can't see)
                # and for the same honest-decline wording either way.
                from apps.chatbot.booking.discovery import (
                    SymptomResolution,
                    resolve_symptom_specialty_ids,
                    symptom_no_match_result,
                )

                resolution = resolve_symptom_specialty_ids(clinic, nlu, ctx.message)
                if resolution is None:
                    # The concern-map/catalog-match chain had nothing to
                    # add (e.g. "cardiology" isn't a _CONCERN_MAP phrase,
                    # and this particular LLM call's catalog_match came
                    # back not_applicable rather than no_match -- live-
                    # confirmed non-deterministic across repeated identical
                    # calls) -- but entities.specialty being non-empty at
                    # all is itself the detected constraint, independent
                    # of whether any resolver tier could further place it.
                    # A named specialty the clinic doesn't have is always
                    # "understood, not offered," never "nothing to go on."
                    resolution = SymptomResolution(matched_ids=[], understood=True)
                if resolution.matched_ids:
                    qs = qs.filter(
                        doctor_specialties__specialty_id__in=resolution.matched_ids
                    ).distinct()
                else:
                    return symptom_no_match_result("search_doctors", resolution, kind="doctor")
        elif not doctor_named and ctx.resolved_specialty_ids:
            # Clinic Capability Resolver live vertical slice: the planner
            # already ran resolve_capability/decide_routing for this exact
            # message (apply_capability_resolution) and authorized these
            # specialty ids -- a more targeted result than the internal
            # concern-map/category-hint chain below would independently
            # find, and consulting it here avoids redundantly re-resolving
            # a question already answered. Same authority rule Step 5
            # already established for resolved_service_ids.
            qs = qs.filter(
                doctor_specialties__specialty_id__in=ctx.resolved_specialty_ids
            ).distinct()
        elif not doctor_named:
            from apps.chatbot.booking.discovery import (
                resolve_symptom_specialty_ids,
                symptom_no_match_result,
            )

            resolution = resolve_symptom_specialty_ids(clinic, nlu, ctx.message)
            if resolution is not None:
                if resolution.matched_ids:
                    qs = qs.filter(
                        doctor_specialties__specialty_id__in=resolution.matched_ids
                    ).distinct()
                else:
                    return symptom_no_match_result("search_doctors", resolution, kind="doctor")
            elif not entity_list(nlu.entities.symptom):
                nothing_to_filter_on = True

    # Same principle for a service named only to anchor a pricing/services
    # clause elsewhere in the message — live-confirmed without this guard:
    # "who are your doctors and how much is a strep test" silently dropped
    # 3 of 6 real doctors from the browse-all-doctors answer.
    service_blocked = "service_id" in ctx.blocked_entity_fields.get("doctors", frozenset())
    service_id = None if service_blocked else nlu.resolved_ids.service_id
    service_named = bool(service_id) or (not service_blocked and bool(nlu.entities.service))
    if service_id:
        qs = qs.filter(services__id=service_id).distinct()
    elif not service_blocked and nlu.entities.service:
        qs = qs.filter(services__name__icontains=nlu.entities.service, services__is_deleted=False).distinct()
    elif not service_blocked and ctx.resolved_service_ids:
        # Proven bug (live-confirmed): "which doctor can do teeth
        # whitening?" already computes ctx.resolved_service_ids (the
        # shared per-turn message->service matcher, planner.py) with the
        # exact right service id -- neither branch above ever consulted
        # it, so this query stayed completely unfiltered by service, only
        # narrowed by specialty (4 doctors instead of the 2-3 who
        # actually offer it). resolved_service_ids only ever populates
        # from a close literal/token match against a real service name
        # (routing/signals.py::match_services_in_message), so it's
        # already conservative about firing on a bare symptom/concern
        # message ("yellow teeth" never triggers it) -- an additional
        # narrowing filter here, same as the two branches above, not a
        # new decision axis.
        qs = qs.filter(services__id__in=ctx.resolved_service_ids).distinct()
        service_named = True

    language_values = entity_list(getattr(nlu.entities, "language", None))
    if language_values:
        lang_codes = resolve_language_codes(language_values)
        # A language was named but didn't resolve to any known code — filter
        # to no rows rather than silently ignoring the request and returning
        # every doctor as if the question had never been asked.
        qs = qs.filter(languages__overlap=lang_codes) if lang_codes else qs.none()

    # Live-confirmed gap: a doctor_search message the NLU extracted
    # *nothing at all* from — no specialty, no symptom, no service, no
    # doctor name, no language ("is there an eye doctor here" at a clinic
    # with none; the LLM sometimes returns every entity null instead of
    # naming the unavailable specialty, confirmed non-deterministic across
    # runs) — silently fell through to browsing every active doctor,
    # indistinguishable from a deliberate "who are your doctors" browse
    # request. Gated on the positive signal instead of trying to
    # negatively infer "not a browse request": mentions_specific_doctor_role
    # only fires when the message actually names a specific role/specialty
    # word ("dentist," "eye doctor") — a phrasing this curated vocabulary
    # doesn't recognize (e.g. "list your doctors," which the narrower
    # is_doctor_browse_query regex was tried against first and
    # live-confirmed to miss) safely falls through to the existing browse
    # behavior instead of risking a false decline.
    if (
        nothing_to_filter_on
        and not doctor_named
        and not service_named
        and not language_values
        and mentions_specific_doctor_role(ctx.message)
    ):
        return SQLResult(
            handler="search_doctors",
            found=False,
            rows=[],
            summary=(
                "I'm not sure which kind of specialist that calls for — could "
                "you say a bit more about what you're looking for, or name a "
                "doctor or specialty directly?"
            ),
            meta={"authoritative_summary": True},
        )

    doctors = list(qs[:DOCTOR_LIST_CEILING])
    rows = [doctor_to_dict(d) for d in doctors]
    meta: dict[str, Any] = {}
    if rows:
        names = ", ".join(r["full_name"] for r in rows[:3])
        more = f" (+{len(rows) - 3} more)" if len(rows) > 3 else ""
        summary = f"Found {len(rows)} doctor(s): {names}{more}."
        if ctx.informational_service_candidates:
            # Clinic Capability Resolver: a "concern" can surface a real,
            # relevant service candidate alongside the specialty that
            # actually drove this doctor filter -- capability_routing_
            # policy.py's own rule is that this must never narrow the
            # query itself, only ever be mentioned. Previously computed,
            # logged in capability_resolver_live, and silently discarded:
            # "my smile looks dull and yellow, is there a quick fix"
            # correctly resolved General & Cosmetic Dentistry (the doctor
            # filter) *and* In-Office Laser Teeth Whitening (informational)
            # but the final reply never mentioned the service at all. Every
            # id is re-validated against this clinic's real active catalog
            # here -- never trust an id at face value this far downstream.
            from apps.services.models import Service

            info_names = list(
                Service.objects.filter(
                    clinic=clinic,
                    id__in=ctx.informational_service_candidates,
                    is_deleted=False,
                    is_active=True,
                ).values_list("name", flat=True)
            )
            if info_names:
                meta["informational_services"] = info_names
    else:
        summary = "No matching doctors found."
    return SQLResult(
        handler="search_doctors", found=bool(rows), rows=rows, summary=summary, meta=meta
    )


def list_specialties(ctx: SQLContext) -> SQLResult:
    from django.db.models import Count, Q

    from apps.specialties.models import Specialty

    clinic = ctx.clinic
    nlu = ctx.nlu
    qs = Specialty.objects.filter(clinic=clinic, is_deleted=False, is_active=True)

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    if specialty_ids:
        qs = qs.filter(id__in=specialty_ids)
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            qs = qs.filter(build_name_filter("name", specs))

    # One annotated query instead of a per-specialty .count() (was up to 20
    # extra COUNT queries per "what specialties do you offer" chat message).
    qs = qs.annotate(
        doctor_count=Count(
            "doctors",
            filter=Q(doctors__is_deleted=False, doctors__is_active=True),
        )
    )
    specialties = list(qs.order_by("name")[:20])
    rows = [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "description": (s.description or "")[:300],
            "doctor_count": s.doctor_count,
        }
        for s in specialties
    ]
    if rows:
        names = ", ".join(r["name"] for r in rows[:5])
        summary = f"Specialties: {names}."
    else:
        summary = "No specialties found."
    return SQLResult(handler="list_specialties", found=bool(rows), rows=rows, summary=summary)


def doctor_availability(ctx: SQLContext) -> SQLResult:
    from apps.doctors.models import Doctor
    from apps.chatbot.sql_tool.utils import parse_time_ceiling, parse_time_floor
    from apps.chatbot.booking.config import booking_horizon_days
    from apps.chatbot.temporal import day_label, resolve_temporal_query

    clinic = ctx.clinic
    nlu = ctx.nlu
    tz = clinic_timezone(clinic)
    today = timezone.now().astimezone(tz).date()

    scope = resolve_temporal_query(
        date_entities=entity_list(nlu.entities.date),
        today=today,
        horizon_days=booking_horizon_days(clinic),
        message=ctx.message,
        tz=tz,
    )
    if not scope.searchable:
        return SQLResult(
            handler="doctor_availability",
            found=False,
            summary=_unsearchable_summary(scope),
            meta={**scope.as_meta(), "authoritative_summary": True},
        )

    time_entities = _clean_time_entities(entity_list(nlu.entities.time))
    time_floor = parse_time_floor(time_entities)
    time_ceiling = parse_time_ceiling(time_entities)

    doctor_qs = Doctor.objects.filter(
        clinic=clinic,
        is_deleted=False,
        is_active=True,
        is_accepting_patients=True,
    )
    doctor_ids = entity_ids(nlu.resolved_ids.doctor_id)
    names: list[str] = []
    name_filter_matched = False
    if doctor_ids:
        doctor_qs = doctor_qs.filter(id__in=doctor_ids)
    else:
        names = entity_list(nlu.entities.doctor_name)
        names = [
            n
            for n in names
            if n.lower() not in _NAME_NOISE
            and not all(tok in _NAME_NOISE for tok in n.lower().split())
        ]
        if names:
            named_qs = doctor_qs.filter(build_name_filter("full_name", names))
            if named_qs.exists():
                doctor_qs = named_qs
                name_filter_matched = True
            # else: same live-confirmed bug as search_doctors -- a
            # hallucinated phrase can survive noise-filtering and still
            # match no real doctor ("which doctor HANDLES ROOT canals?"
            # -> doctor_name="handles root"). Left unfiltered so the
            # specialty/capability resolution fallback below still runs.

    # Same live-confirmed bug and fix as search_doctors above: must reflect
    # whether the name filter *actually matched a real doctor*, not merely
    # whether non-noise text was extracted -- a hallucinated non-name
    # value (e.g. "can do", or "handles root") must not otherwise
    # incorrectly count as "a doctor was named."
    doctor_named = bool(doctor_ids) or name_filter_matched

    specialty_ids = entity_ids(nlu.resolved_ids.specialty_id)
    symptom_resolution = None
    # Same gap as search_doctors, same fix: a message naming a specific,
    # unresolved doctor role ("is there an eye doctor available tomorrow"
    # at a clinic with none) with no specialty/symptom entity at all must
    # not silently check availability for every doctor at the clinic --
    # see mentions_specific_doctor_role's docstring for why this is gated
    # on a positive role-noun match rather than a negative "not a browse"
    # inference (an "any doctor available tomorrow" query, which names no
    # specific role, must keep working exactly as before).
    unresolved_role_mentioned = False
    if specialty_ids:
        doctor_qs = doctor_qs.filter(doctor_specialties__specialty_id__in=specialty_ids).distinct()
    else:
        specs = entity_list(nlu.entities.specialty)
        if specs:
            named_qs = doctor_qs.filter(build_name_filter("specialties__name", specs)).distinct()
            if named_qs.exists() or doctor_named:
                doctor_qs = named_qs
            else:
                # Same fix, same live-confirmed bug, as search_doctors: a
                # named specialty that doesn't resolve and doesn't
                # literally match any real specialty name must get the
                # same catalog-aware resolution chain as a bare symptom
                # mention, not a different, generic "no matching doctors"
                # fallback. symptom_no_match_result isn't called in this
                # branch directly, but must still be imported here --
                # Python's function-wide local-variable scoping means the
                # `elif not doctor_named:` branch's own import below only
                # binds the name along *that* code path; the shared
                # "if not doctors:" handling further down needs it
                # regardless of which branch actually ran.
                from apps.chatbot.booking.discovery import (
                    SymptomResolution,
                    resolve_symptom_specialty_ids,
                    symptom_no_match_result,
                )

                resolution = resolve_symptom_specialty_ids(clinic, nlu, ctx.message)
                if resolution is None:
                    # Same reasoning as search_doctors's identical fix: a
                    # named specialty is itself the detected constraint,
                    # independent of whether any resolver tier -- or a
                    # non-deterministic catalog_match call -- could place
                    # it further.
                    resolution = SymptomResolution(matched_ids=[], understood=True)
                if resolution.matched_ids:
                    doctor_qs = doctor_qs.filter(
                        doctor_specialties__specialty_id__in=resolution.matched_ids
                    ).distinct()
                else:
                    symptom_resolution = resolution
        elif not doctor_named and ctx.resolved_specialty_ids:
            # Same fix as search_doctors: doctor_availability had never
            # consumed ctx.resolved_specialty_ids at all -- the Clinic
            # Capability Resolver's live vertical slice only reached
            # search_doctors, so a doctor_availability-classified message
            # naming a capability rather than a specialty/symptom (e.g.
            # "is the root canal doctor free tomorrow?") fell straight to
            # the bare-symptom branch below, which has nothing to resolve
            # against since no entities.symptom was set either -- an
            # unresolved-role decline despite the planner already having
            # authorized a specialty via apply_capability_resolution.
            doctor_qs = doctor_qs.filter(
                doctor_specialties__specialty_id__in=ctx.resolved_specialty_ids
            ).distinct()
        elif not doctor_named:
            # Same fix as search_doctors: a bare symptom ("cardiac doctor
            # available tomorrow") must not silently check availability
            # for every doctor at the clinic regardless of specialty.
            from apps.chatbot.booking.discovery import (
                resolve_symptom_specialty_ids,
                symptom_no_match_result,
            )

            resolution = resolve_symptom_specialty_ids(clinic, nlu, ctx.message)
            if resolution is not None:
                if resolution.matched_ids:
                    doctor_qs = doctor_qs.filter(
                        doctor_specialties__specialty_id__in=resolution.matched_ids
                    ).distinct()
                else:
                    symptom_resolution = resolution
            elif not entity_list(nlu.entities.symptom) and mentions_specific_doctor_role(
                ctx.message
            ):
                unresolved_role_mentioned = True

    # Service-level narrowing, same three-tier pattern as search_doctors
    # above (explicit resolved_ids.service_id -> literal entities.service
    # text match -> ctx.resolved_service_ids) -- applied on top of
    # whatever the specialty chain above already produced, never in place
    # of it. Live-confirmed gap: unlike search_doctors, this handler never
    # consulted a service at all -- "is there any doctor available Monday
    # afternoon that can treat the stitches?" (doctor_availability, no
    # specialty/symptom entity, only a capability phrase that should
    # resolve to Horizon's real "Simple Wound Laceration Repair (Sutures)"
    # service) fell through the specialty chain with nothing to filter on
    # and returned every active doctor's Monday-afternoon slots, stitches
    # capability or not. Same "doctors" key as search_doctors's own block
    # would use, kept per-task as "availability" for symmetry with
    # _SERVICE_BLOCKED_TASKS_BY_INTENT's existing per-task keying, even
    # though nothing populates that key for this task today.
    service_blocked = "service_id" in ctx.blocked_entity_fields.get("availability", frozenset())
    service_id = None if service_blocked else nlu.resolved_ids.service_id
    if service_id:
        doctor_qs = doctor_qs.filter(services__id=service_id).distinct()
    elif not service_blocked and nlu.entities.service:
        doctor_qs = doctor_qs.filter(
            services__name__icontains=nlu.entities.service, services__is_deleted=False
        ).distinct()
    elif not service_blocked and ctx.resolved_service_ids:
        doctor_qs = doctor_qs.filter(services__id__in=ctx.resolved_service_ids).distinct()

    # Live-confirmed bug (real production trace): this used to be
    # doctor_qs[:5] -- a "how many to show" cap borrowed from
    # search_doctors's DOCTOR_LIST_CEILING listing use case, but wrong
    # here: this feeds an availability SEARCH ("does any slot exist"),
    # not a listing. A clinic with 6+ doctors where the one(s) with real
    # availability happened to sort past the first 5 (default/PK query
    # order, not meaningful) got a confidently wrong "No available slots
    # found" -- reproduced live: the chatbot said Friday had nothing,
    # while the real booking wizard (querying the same DoctorSchedule
    # data with no such cap) found a real 9:30 AM slot with the 6th
    # doctor. _first_day_with_slots already bounds cost via
    # _MAX_DAYS_SCANNED and stops at the first day with any slot -- an
    # arbitrary doctor-count cap here can only make an honest "no slots"
    # into a false one, never make a real search meaningfully cheaper in
    # the common case.
    doctors = [] if (symptom_resolution or unresolved_role_mentioned) else list(doctor_qs)
    if not doctors:
        if symptom_resolution is not None:
            no_match = symptom_no_match_result(
                "doctor_availability", symptom_resolution, kind="doctor"
            )
            return SQLResult(
                handler="doctor_availability",
                found=False,
                summary=no_match.summary,
                meta={**scope.as_meta(), "target_date": scope.start.isoformat(), **no_match.meta},
            )
        if unresolved_role_mentioned:
            return SQLResult(
                handler="doctor_availability",
                found=False,
                summary=(
                    "I'm not sure which kind of specialist that calls for — could "
                    "you say a bit more about what you're looking for, or name a "
                    "doctor or specialty directly?"
                ),
                meta={
                    **scope.as_meta(),
                    "target_date": scope.start.isoformat(),
                    "authoritative_summary": True,
                },
            )
        return SQLResult(
            handler="doctor_availability",
            found=False,
            summary="No matching doctors found to check availability.",
            meta={**scope.as_meta(), "target_date": scope.start.isoformat()},
        )

    slots, target_date = _first_day_with_slots(
        clinic,
        scope=scope,
        doctors=doctors,
        time_floor=time_floor,
        time_ceiling=time_ceiling,
    )
    target_date = target_date or scope.start

    found = bool(slots)
    where = day_label(target_date, today=today)
    if found:
        summary = f"Found {len(slots)} available slot(s) on {where}."
        if scope.conflict and scope.conflict_weekday:
            # The date the patient gave and the weekday they gave disagree.
            # The date wins, but we say so rather than quietly picking one.
            summary += (
                f" Note: you mentioned {scope.conflict_weekday}, but "
                f"{where} is a {target_date.strftime('%A')}."
            )
    else:
        # A month with nothing open must say so about the month, not about
        # whichever single day the scan happened to end on.
        if scope.is_range and scope.scope_label:
            where = scope.scope_label
        if time_entities:
            wanted = ", ".join(time_entities)
            summary = (
                f"No available slots on {where} for {wanted}. "
                "Try another day or time."
            )
        else:
            summary = (
                f"No available slots found on {where}. "
                "Try another day, or tap Book Appointment to pick a time."
            )
    return SQLResult(
        handler="doctor_availability",
        found=found,
        rows=slots[:20],
        summary=summary,
        meta={
            **scope.as_meta(),
            "target_date": target_date.isoformat(),
            "authoritative_summary": True,
        },
    )


# A day scan is bounded so a wide horizon can never turn one question into an
# unbounded walk. Days the roster never works are skipped before any query.
_MAX_DAYS_SCANNED = 62


def _first_day_with_slots(
    clinic: Any,
    *,
    scope: TemporalQuery,
    doctors: list[Any],
    time_floor: time | None,
    time_ceiling: time | None,
) -> tuple[list[dict[str, Any]], date | None]:
    """Earliest day inside `scope` that has bookable slots left.

    A single-day scope visits exactly one day, so this is the previous
    behaviour for "Monday morning"; a month scope walks the month instead of
    collapsing to an arbitrary date.
    """
    from apps.chatbot.booking.slots import active_holds_for_date, compute_slots_for_day
    from apps.doctors.models import DoctorSchedule

    working_days = set(
        DoctorSchedule.objects.filter(
            clinic=clinic, doctor__in=doctors, is_active=True
        ).values_list("day_of_week", flat=True)
    )

    for scanned, day in enumerate(scope.iter_days()):
        if scanned >= _MAX_DAYS_SCANNED:
            break
        if working_days and day.weekday() not in working_days:
            continue
        slots = compute_slots_for_day(
            clinic,
            target_date=day,
            doctors=doctors,
            max_slots=20,
            excluded_keys=active_holds_for_date(clinic, day),
        )
        if time_floor is not None:
            slots = [s for s in slots if _slot_at_or_after(s, time_floor)]
        if time_ceiling is not None:
            slots = [s for s in slots if _slot_before(s, time_ceiling)]
        if slots:
            return slots, day
    return [], None


_WEEKDAY_WORDS = frozenset(
    w.lower()
    for w in (
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "mon", "tue", "tues", "wed", "weds", "thu", "thur", "thurs",
        "fri", "sat", "sun",
    )
)


def _clean_time_entities(values: list[str]) -> list[str]:
    """Drop values that name a day or a bare number rather than a time.

    The NLU has been observed filing "Friday" and "2" under `time` — which
    produced the reply "No available slots on Friday, August 21 for Friday"
    and risks a nonsense floor/ceiling filter suppressing real slots.
    """
    cleaned = []
    for value in values:
        text = str(value).strip().lower()
        if not text or text in _WEEKDAY_WORDS or text.isdigit():
            continue
        cleaned.append(value)
    return cleaned


def _unsearchable_summary(scope: TemporalQuery) -> str:
    """What we say when there is nothing safe to search.

    Every branch names the constraint back to the patient and offers no
    slots. Substituting the earliest opening here is what let someone book
    19 August after asking about 12 January.
    """
    from apps.chatbot.temporal import TemporalStatus, day_label

    asked = scope.scope_label or scope.requested_text or "that date"
    if scope.status is TemporalStatus.PAST:
        return (
            f"{asked} has already passed. Which upcoming date would you like "
            "me to check?"
        )
    if scope.status is TemporalStatus.BEYOND_HORIZON:
        through = (
            day_label(scope.horizon_end) if scope.horizon_end else "the current window"
        )
        return (
            f"This clinic is scheduling appointments through {through}, so "
            f"{asked} isn't open for booking yet."
        )
    if scope.status is TemporalStatus.AMBIGUOUS:
        return (
            f"I couldn't pin down the date you meant by \"{asked}\". Could you "
            "give me the full date — for example \"September 1\"?"
        )
    return (
        f"I couldn't confidently work out which date \"{asked}\" refers to. "
        "Could you give me the full date — for example \"January 12, 2027\"?"
    )
