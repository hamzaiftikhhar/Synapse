"""Generate 500+ clinic-agnostic routing eval cases (typos, slang, short/long)."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any, Iterable


@dataclass(frozen=True)
class EvalCase:
    """One expected routing outcome."""

    case_id: str
    message: str
    expected_lane: str
    expected_family: str
    acceptable_lanes: frozenset[str] = field(default_factory=frozenset)
    tags: tuple[str, ...] = ()
    # Optional synthetic clinic catalogs for dynamic matching
    services: tuple[dict[str, str], ...] = ()
    documents: tuple[dict[str, Any], ...] = ()
    # Simulate NLU timeout / low confidence when rules miss
    force_unknown: bool = False
    confidence_override: float | None = None


_DEFAULT_SERVICES = (
    {"id": "s1", "name": "Adult Cleaning, Exam & X-Rays"},
    {"id": "s2", "name": "Surgical Tooth Extraction"},
    {"id": "s3", "name": "Full Body Mole & Cancer Screening"},
    {"id": "s4", "name": "Botox / Dysport Wrinkle Treatment"},
    {"id": "s5", "name": "Urgent Care Visit (Level 1 / Basic)"},
    {"id": "s6", "name": "Pediatric Well-Child Exam"},
)

_DEFAULT_DOCS = (
    {
        "id": "d1",
        "title": "Patient Agreement & Clinical Protocols",
        "routing_summary": (
            "Arrive early for appointments. Cancellation and deposit policies. "
            "Post-op instructions for gauze, straws, smoking, and sun exposure before laser."
        ),
        "routing_keywords": [
            "arrive",
            "cancellation",
            "deposit",
            "post-op",
            "gauze",
            "straw",
            "smoking",
            "sun exposure",
            "laser",
            "policy",
        ],
    },
)


def _noise(phrases: Iterable[str]) -> list[str]:
    """Expand with short/slang/typo/long wrappers — still clinic-agnostic."""
    out: list[str] = []
    prefixes = ("", "hey ", "umm ", "quick q — ", "can you tell me ", "pls ")
    suffixes = ("", "?", "??", " please", " thx", " thanks")
    typos = {
        "appointment": ["apointment", "appt"],
        "doctor": ["docotr"],
        "insurance": ["insurence"],
        "hours": ["houres", "hrs"],
    }
    for p in phrases:
        base = p.strip()
        if not base:
            continue
        for pre, suf in product(prefixes[:4], suffixes[:4]):
            out.append(f"{pre}{base}{suf}".strip())
        # single typo swap when keyword present
        lower = base.lower()
        for key, alts in typos.items():
            if key in lower:
                for alt in alts[:2]:
                    out.append(base.lower().replace(key, alt, 1))
                break
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for m in out:
        k = m.lower().strip()
        if k and k not in seen:
            seen.add(k)
            uniq.append(m)
    return uniq


def build_eval_cases(*, target: int = 520) -> list[EvalCase]:
    """Build a large paraphrased battery. Always returns >= target cases."""
    cases: list[EvalCase] = []
    svc = _DEFAULT_SERVICES
    docs = _DEFAULT_DOCS

    def add(
        family: str,
        lane: str,
        messages: list[str],
        *,
        tags: tuple[str, ...] = (),
        services: tuple[dict[str, str], ...] | None = None,
        documents: tuple[dict[str, Any], ...] | None = None,
        force_unknown: bool = False,
        confidence: float | None = None,
        also: frozenset[str] | None = None,
        limit: int | None = None,
    ) -> None:
        msgs = _noise(messages)
        if limit is not None:
            msgs = msgs[:limit]
        for i, msg in enumerate(msgs):
            cases.append(
                EvalCase(
                    case_id=f"{family}-{len(cases):04d}-{i}",
                    message=msg,
                    expected_lane=lane,
                    expected_family=family,
                    acceptable_lanes=also or frozenset({lane}),
                    tags=tags,
                    services=services if services is not None else svc,
                    documents=documents if documents is not None else docs,
                    force_unknown=force_unknown,
                    confidence_override=confidence,
                )
            )

    # ── Direct ────────────────────────────────────────────────────────────
    add(
        "greeting",
        "direct",
        ["hi", "hello", "hey there", "good morning", "hi how are you"],
        tags=("direct",),
        limit=40,
    )
    add(
        "farewell",
        "direct",
        ["bye", "goodbye", "thanks bye", "see you", "take care"],
        tags=("direct",),
        limit=25,
    )
    add(
        "off_topic",
        "direct",
        ["i want pizza", "who won the world cup", "tell me a joke about cats"],
        tags=("direct",),
        also=frozenset({"direct", "clarify"}),
        limit=20,
    )
    add(
        "emergency",
        "direct",
        [
            "I have severe chest pain and can't breathe",
            "I think I'm having a heart attack",
            "my arm is numb and chest hurts badly",
        ],
        tags=("safety",),
        limit=18,
    )

    # ── SQL hours (not duration) ──────────────────────────────────────────
    add(
        "hours",
        "sql_fast",
        [
            "hours?",
            "what are your hours",
            "clinic hours",
            "when are you open",
            "are you open on saturday",
            "what time do you close",
            "tell me about the clinic hours",
        ],
        tags=("sql", "hours"),
        limit=55,
    )

    # ── Duration must NOT be hours ────────────────────────────────────────
    add(
        "duration",
        "sql_fast",
        [
            "How much hours does it take to do Adult Cleaning, Exam & X-Rays?",
            "how much hours does Full Body Mole & Cancer Screening take",
            "how much time does Botox Treatment takes",
            "how long does an urgent care visit take",
            "how long is Surgical Tooth Extraction",
        ],
        tags=("sql", "duration", "regression"),
        also=frozenset({"sql_fast"}),
        limit=50,
    )

    # ── Pricing / services ────────────────────────────────────────────────
    add(
        "pricing",
        "sql_fast",
        [
            "How much does Adult Cleaning, Exam & X-Rays cost",
            "what does a well child exam cost",
            "price for Surgical Tooth Extraction",
            "how much is Botox / Dysport Wrinkle Treatment",
            "cost of Full Body Mole & Cancer Screening",
        ],
        tags=("sql", "pricing"),
        limit=45,
    )
    add(
        "services",
        "sql_fast",
        [
            "what services do you offer",
            "list of services",
            "which services do you provide",
            "can you tell me something about the Cancer Screening",
            "tell me about Botox Treatment",
        ],
        tags=("sql", "services"),
        limit=40,
    )

    # ── Doctors ───────────────────────────────────────────────────────────
    add(
        "doctors",
        "sql_fast",
        [
            "help me find a doctor",
            "find me a doctor please",
            "hey can you help me find a dentist",
            "list of doctors",
            "who are your doctors",
            "show me doctors",
        ],
        tags=("sql", "doctors"),
        limit=45,
    )

    # ── Insurance ─────────────────────────────────────────────────────────
    add(
        "insurance",
        "sql_fast",
        [
            "do you accept Aetna",
            "do you take Medicaid",
            "do you take Medi-Cal",
            "umm do you guys accept Delta Dental",
            "check my insurance",
            "what insurance do you accept",
        ],
        tags=("sql", "insurance"),
        limit=45,
    )

    # ── Location ──────────────────────────────────────────────────────────
    add(
        "location",
        "sql_fast",
        [
            "where are you located",
            "what is your address",
            "how do I get to the clinic",
            "parking at the clinic",
        ],
        tags=("sql", "location"),
        limit=28,
    )

    # ── Booking transactional ─────────────────────────────────────────────
    add(
        "booking",
        "booking",
        [
            "I would like to book an appointment",
            "book an appointment",
            "I wanna book something with Dr Maya",
            "please schedule an appointment",
            "start booking",
            "can I book a visit for tomorrow",
        ],
        tags=("booking",),
        limit=40,
    )

    # ── Knowledge / FAQ (vector) ──────────────────────────────────────────
    add(
        "faq",
        "vector_rag",
        [
            "how early should patients arrive",
            "what is your cancellation policy",
            "for how many hours you can't use straws",
            "how many days we are required to avoid sun exposure",
            "how many days avoid sun before laser treatments",
            "whats the replacement tray fee roughly",
            "what is the down payment",
            "post-op gauze instructions",
        ],
        tags=("rag", "policy"),
        also=frozenset({"vector_rag"}),
        limit=55,
    )

    # ── Informational appointment ≠ booking ───────────────────────────────
    add(
        "appointment_info",
        "vector_rag",
        [
            "What time should I arrive for my appointment?",
            "do I need to arrive early for my appointment",
            "what happens if I miss my appointment",
        ],
        tags=("rag", "speech_act"),
        also=frozenset({"vector_rag", "sql_fast"}),
        limit=24,
    )

    # ── Timeout / unknown recovery with catalog ───────────────────────────
    add(
        "timeout_recover",
        "vector_rag",
        [
            "explain the clinical protocols briefly",
            "random policy question about deposits",
            "what is the cancellation deposit policy",
        ],
        tags=("rag", "timeout"),
        force_unknown=True,
        confidence=0.5,
        also=frozenset({"vector_rag", "clarify"}),
        limit=24,
    )

    # ── Low confidence + no docs → clarify ────────────────────────────────
    add(
        "low_conf_clarify",
        "clarify",
        ["asdf qwerty zxcv", "bluurb mleep", "???!!!"],
        tags=("clarify",),
        force_unknown=True,
        confidence=0.2,
        documents=(),
        services=(),
        also=frozenset({"clarify", "direct"}),
        limit=12,
    )

    # ── Soft medical / specialty (direct or sql) ──────────────────────────
    add(
        "soft_medical",
        "direct",
        [
            "I have a mild headache for two days",
            "my skin is itchy but not emergency",
        ],
        tags=("medical",),
        also=frozenset({"direct", "sql_fast", "vector_rag", "clarify"}),
        limit=16,
    )

    # ── Horizon golden regressions (router inversion) ─────────────────────
    horizon_docs = (
        {
            "id": "h1",
            "title": "Membership & Refund Policy",
            "routing_summary": (
                "Membership termination refund and prorated dues. "
                "Cancellation fee within 24 hours. Reactivation rules."
            ),
            "routing_keywords": [
                "refund",
                "membership",
                "cancellation",
                "cancel",
                "fee",
                "reactivate",
                "prorated",
                "dues",
            ],
        },
    )
    add(
        "horizon_cancel_fee",
        "vector_rag",
        [
            "I need to cancel my appointment for tomorrow afternoon, but it's less than 24 hours away... am I gonna get charged a fee for that?",
            "what is your cancel fee policy",
            "If I drop my membership halfway through the year do I get a refund",
        ],
        tags=("rag", "horizon", "regression"),
        documents=horizon_docs,
        also=frozenset({"vector_rag"}),
        limit=12,
    )
    add(
        "horizon_emergency",
        "direct",
        [
            "My husband has been complaining about this tight pressure in his chest that's radiating down his arm for the past hour. Can I bring him in for a quick walk-in right now?",
            "tight pressure in chest radiating to arm",
            "chest hurts and left arm is numb",
        ],
        tags=("safety", "horizon", "regression"),
        also=frozenset({"direct"}),
        limit=12,
    )
    add(
        "horizon_service_list",
        "sql_fast",
        [
            "What are the urgent care your clinic provides?",
            "what urgent care services do you provide",
            "can you please tell me what are the things you provide",
        ],
        tags=("sql", "horizon", "regression"),
        also=frozenset({"sql_fast", "clarify"}),
        limit=12,
    )
    add(
        "horizon_no_visit_sku",
        "clarify",
        [
            "how many times we can visit a specialized doctor",
            "if we put 55 kg of meat in Sulphuric acid how much time it will take to completely dissolve",
        ],
        tags=("clarify", "horizon", "regression"),
        force_unknown=True,
        confidence=0.5,
        also=frozenset({"clarify", "direct"}),
        limit=8,
    )
    add(
        "horizon_specialties",
        "sql_fast",
        [
            "can you please tell me what specialities you provide",
            "what specialties do you provide",
        ],
        tags=("sql", "horizon", "regression"),
        also=frozenset({"sql_fast", "clarify"}),
        limit=8,
    )

    # ── Adversarial: Gen-Z / regional slang, typos, compound asks ──────────
    # expected_lane/acceptable_lanes below are the ACTUAL observed lanes from
    # running this battery (apps.chatbot.eval.runner.evaluate_routing_case)
    # against each phrase individually, not guessed — see the class docstring
    # note in test_eval_battery.py. Most resolve to `clarify`: this documents
    # real, measured robustness gaps against casual phrasing (no "uhc"
    # insurance alias, "squeeze me in"/"need sumthing" not matching the
    # transactional-booking regex, "tmrw"/"b4" not normalized, etc.) rather
    # than asserting these are handled correctly. The one hard invariant —
    # none of this casual/illness phrasing may ever resolve to the
    # safety-critical `emergency` lane — is enforced separately in
    # test_eval_battery.py's test_no_adversarial_case_becomes_emergency.
    # Each phrase gets its own add() call (rather than being grouped with a
    # shared `limit`) so _noise()'s prefix/suffix expansion can't silently
    # truncate a later phrase in the list out of the battery entirely.
    add(
        "adversarial_booking_slang_squeeze",
        "clarify",
        ["yo can yall squeeze me in today"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_booking_slang_after_work",
        "clarify",
        ["need sumthing after work"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_booking_slang_tmrw",
        "clarify",
        ["got anything tmrw"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_insurance_slang_uhc",
        "clarify",
        ["do yall take uhc"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_medical_slang_accutane",
        "clarify",
        ["im on accutane rn"],
        tags=("adversarial", "genz"),
        limit=8,
    )
    add(
        "adversarial_medical_slang_pediatric",
        "clarify",
        ["my kid got sick"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_pricing_slang_botox",
        "sql_fast",
        ["botox b4 wedding?"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_appointment_lookup_slang",
        "clarify",
        ["cant remembr if i booked"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_doctor_search_slang_filler",
        "sql_fast",
        ["who does filler"],
        tags=("adversarial", "genz"),
        services=(
            *_DEFAULT_SERVICES,
            {"id": "s7", "name": "Dermal Filler Injections"},
        ),
        limit=4,
    )
    add(
        "adversarial_availability_slang_cooked",
        "clarify",
        ["is friday cooked?"],
        tags=("adversarial", "genz"),
        limit=4,
    )
    add(
        "adversarial_compound_insurance_booking",
        "clarify",
        ["do you take Aetna and can I book with Dr. Lee friday"],
        tags=("adversarial", "compound"),
        limit=4,
    )
    # Phase 2 (multi-intent coverage): the NLU prompt's compound rule names
    # insurance+booking (above), doctor+availability, pricing+service, and
    # hours+location as example categories that must never "silently answer
    # only one half." Each category below is split into an _explicit case
    # (an "and is/are/do" connector _COMPOUND_RE already recognizes) and an
    # _comma case (a natural comma-joined phrasing with no such connector) --
    # verified via direct execution before writing expected_lane, not
    # guessed. Where a case fails today, that is the documented finding,
    # not a mistake in the test: see ROADMAP.md for the two root causes.
    add(
        "adversarial_compound_doctor_availability",
        "clarify",
        ["tell me about Dr Lee and is he available friday"],
        tags=("adversarial", "compound"),
        limit=4,
    )
    add(
        "adversarial_compound_doctor_bio",
        "clarify",
        ["who is your best dentist and are they free tomorrow"],
        tags=("adversarial", "compound"),
        limit=4,
    )
    add(
        "adversarial_compound_pricing_explicit",
        "clarify",
        ["how much is a cleaning and do you also do whitening"],
        tags=("adversarial", "compound"),
        limit=4,
    )
    add(
        "adversarial_compound_pricing_comma",
        "clarify",
        ["whats the cost of a filling, do you offer root canals too"],
        tags=("adversarial", "compound"),
        limit=4,
    )
    add(
        "adversarial_compound_hours_explicit",
        "clarify",
        ["what time do you open and where are you located"],
        tags=("adversarial", "compound"),
        limit=4,
    )
    add(
        "adversarial_compound_hours_comma",
        "clarify",
        ["are you open sunday and whats your address"],
        tags=("adversarial", "compound"),
        limit=4,
    )

    # Pad to target with systematic paraphrases of core SQL intents
    if len(cases) < target:
        fillers = [
            ("hours2", "sql_fast", "what are your opening hours today"),
            ("hours2", "sql_fast", "office hours please"),
            ("doctors2", "sql_fast", "I need help finding a physician"),
            ("insurance2", "sql_fast", "are you in network with Aetna"),
            ("services2", "sql_fast", "do you offer Cleaning services"),
            ("pricing2", "sql_fast", "what's the fee for Tooth Extraction"),
            ("faq2", "vector_rag", "tell me about your cancellation fee policy"),
            ("booking2", "booking", "I'd like to schedule a visit"),
        ]
        i = 0
        while len(cases) < target:
            fam, lane, msg = fillers[i % len(fillers)]
            # vary message
            variants = [
                msg,
                msg + "?",
                "hey " + msg,
                msg.replace("your", "the clinic"),
                "pls " + msg,
            ]
            m = variants[(len(cases) + i) % len(variants)]
            cases.append(
                EvalCase(
                    case_id=f"pad-{len(cases):04d}",
                    message=m,
                    expected_lane=lane,
                    expected_family=fam,
                    acceptable_lanes=frozenset({lane}),
                    tags=("pad",),
                    services=svc,
                    documents=docs if lane == "vector_rag" else docs,
                )
            )
            i += 1

    return cases[: max(target, len(cases))]
