"""Clinic Capability Resolver — Phase B routing policy (design, not yet
consumed by any live decision path).

Translates a `CapabilityResolution` into a routing decision, honoring the
rules agreed after Phase A's evidence:

- Explicit service request -> the resolved service candidate(s) may drive
  service/doctor filtering (more than one only when the resolver itself
  judged the request genuinely ambiguous between real catalog items --
  see `decide_routing`'s "explicit" branch).
- Explicit specialty request -> the resolved specialty candidate(s) may
  drive doctor filtering, same rule.
- Care concern/navigation -> specialty-level candidates may guide doctor
  discovery; service candidates are informational only -- never a silent
  filter -- unless the user separately, explicitly requests that service.
  This covers the ambiguous-concern case too: a concern never silently
  becomes a service/booking requirement, ambiguous or not.
- Unsupported capability (no candidates at all) -> an honest decline, the
  same shape the existing system already produces today.
- Provider failure -> never reported as "no matching service" -- a
  distinct, honest "couldn't check" outcome.

Deliberately does NOT use confidence as a threshold anywhere (Phase A
evidence: "I'm not sure if I need stitches" scored the same 1.0 as the
explicit "I need stitches" -- confidence tracks linguistic clarity, not
how committal the caller should be). All candidates a context permits are
passed through as one OR-filter set, the same granularity the existing
concern-map/`suggest_specialties` chain already uses when it finds 2+
plausible specialties -- no new ambiguity math is introduced.

This module is not yet called from `planner.py`, `discovery.py`, or any
SQL handler -- Phase 4 (shadow mode) logs what this policy *would* decide
alongside what the existing pipeline actually does, before anything here
is trusted to drive a live response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from apps.chatbot.booking.capability_resolver import (
    CapabilityResolution,
    ResolverContext,
)

RoutingAction = Literal["filter", "decline", "unavailable"]


@dataclass(frozen=True)
class RoutingDecision:
    action: RoutingAction
    specialty_ids: list[str] = field(default_factory=list)
    # Only ever populated for context="explicit" -- a concern's service
    # candidates are informational and must never reach this field. See
    # `informational_service_candidates` instead.
    service_ids: list[str] = field(default_factory=list)
    informational_service_candidates: list[str] = field(default_factory=list)
    reasoning: str = ""


def decide_routing(
    context: ResolverContext, resolution: CapabilityResolution
) -> RoutingDecision:
    """Pure function: no DB access, no side effects -- easy to unit test
    and easy to call from a shadow-logging site without any risk to the
    live response."""
    if resolution.outcome == "provider_error":
        return RoutingDecision(
            action="unavailable",
            reasoning="provider_error -- must never be reported as a semantic no-match",
        )

    if not resolution.candidates:
        return RoutingDecision(action="decline", reasoning="no_candidates")

    if context == "explicit":
        # Top candidate *per type*, not top-of-the-whole-list -- this
        # module's own docstring already frames it this way ("the top
        # service candidate"/"the top specialty candidate", independently).
        # Live-confirmed bug: the previous code took resolution.candidates[0]
        # outright, so whichever type the model happened to rank first
        # silently discarded an equally-confident candidate of the *other*
        # type -- "can i just walk in for a minor cut or do i need to book
        # something first" (services_offered intent, sql_tasks=["services"])
        # resolved ('specialty', 'Urgent Care', 1.0) ranked first and
        # ('service', 'Simple Wound Laceration Repair (Sutures)', 1.0)
        # second; specialty_ids got set, service_ids stayed empty, and the
        # services_offered handler -- which only ever reads
        # resolved_service_ids, never resolved_specialty_ids -- had nothing
        # to act on despite the resolver having found the exact right
        # answer. Each SQL task already only consults the one field
        # relevant to its own domain (search_doctors/doctor_availability
        # read specialty_ids, services_offered/pricing read service_ids),
        # so populating both here is never over-filtering -- it just stops
        # discarding a real answer whenever the ranked-first type happens
        # not to be the one this turn's task needs.
        #
        # All candidates *of a given type* are taken, not just the first
        # -- capability-family reliability phase, live-reproduced: "I need
        # a checkup" (service_filter_mode="named", no entities.service) is
        # genuinely ambiguous between "Establish Patient Adult Physical"
        # and "Pediatric Well-Child Exam" from the wording alone, but the
        # old "top service only" rule here silently forced a single pick
        # (Adult Physical, per one real trace) even when the resolver
        # itself is now prompted to return both for a genuine tie (see
        # `_EXPLICIT_INSTRUCTIONS`). This does not reopen the ranked-
        # first-type-discards-the-other-type bug fixed above: a clear,
        # single match (the overwhelming majority of explicit asks --
        # "flu test", "stitches") still returns exactly one id per type,
        # since the resolver itself only returns 2+ same-type candidates
        # when it judges the request genuinely ambiguous, not merely to
        # hedge. `services_offered`/`search_doctors` both already accept
        # multiple resolved ids via `id__in` and list every match rather
        # than silently picking one.
        specialty_ids = [
            c.id for c in resolution.candidates if c.target_type == "specialty"
        ]
        service_ids = [
            c.id for c in resolution.candidates if c.target_type == "service"
        ]
        return RoutingDecision(
            action="filter",
            specialty_ids=specialty_ids,
            service_ids=service_ids,
            reasoning="explicit_all_per_type",
        )

    # context == "concern": specialty candidates (all of them -- no
    # confidence cutoff) form the doctor-discovery filter; service
    # candidates are surfaced for a caller to display as "you might also
    # be interested in..." but must never narrow a SQL query on their own.
    specialty_ids = [
        c.id for c in resolution.candidates if c.target_type == "specialty"
    ]
    service_candidates = [
        c.id for c in resolution.candidates if c.target_type == "service"
    ]
    if not specialty_ids:
        # A concern with only service-shaped candidates and no specialty
        # signal at all -- honest decline, same as today's existing
        # behavior for an unmatched concern, not a silent service filter.
        return RoutingDecision(
            action="decline",
            informational_service_candidates=service_candidates,
            reasoning="concern_no_specialty_candidate",
        )
    return RoutingDecision(
        action="filter",
        specialty_ids=specialty_ids,
        informational_service_candidates=service_candidates,
        reasoning="concern_specialty_only",
    )
