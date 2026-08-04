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
            "something about the patient agreement",
            "explain the clinical protocols briefly",
            "random policy question about deposits",
        ],
        tags=("rag", "timeout"),
        force_unknown=True,
        confidence=0.5,
        also=frozenset({"vector_rag"}),
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
        also=frozenset({"direct", "sql_fast", "vector_rag"}),
        limit=16,
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
