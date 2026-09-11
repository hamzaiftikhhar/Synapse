"""NLU model benchmark harness — controlled model-effect comparison.

Runs a fixed, catalog-grounded test dataset (~60 cases across the
categories: explicit services, generic ambiguity, unsupported
capabilities, medical definitions, personal symptoms, treatment requests,
doctor/specialty search, pricing, availability, booking, multi-intent,
negation, follow-ups, context switching, stale-context adversarial,
typos/slang) through `OpenAINLUProvider` directly -- bypassing the
provider-fallback chain entirely so each call is attributable to exactly
one named model -- with the CURRENT, UNCHANGED system prompt
(prompts.py). This isolates the model effect from the prompt effect: the
prompt is held constant across every model tested here (see ROADMAP.md's
"Model A vs Model C" framing). A separate, later pass would hold the
model constant and vary the prompt if this phase's results suggest that's
worth doing.

Real live calls, no fabricated numbers. Each case is repeated N times per
model to measure consistency, not just single-shot accuracy. Expected
values are hand-labeled per case (see `_CASES`) against what the intended
architecture actually requires -- not the model's own self-reported
`reasoning_short`, which CLAUDE.md already documents as untrustworthy.

Deliberately conservative about what counts as "correct": `expected_intents`
is a set of acceptable intents where the architecture doesn't require a
single one (e.g. services_offered vs pricing for a "how much" question
naming a procedure), matching the same latitude the previous phase's
Scope A/B tests already gave real NLU output.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.core.management.base import BaseCommand

# Real Horizon Family Medicine & Urgent Care catalog (see ROADMAP.md for
# confirmed live ids) -- used only for the Docs/Services/Doctors/Catalog
# context block, exactly as engine.py builds it for a real request.
_SERVICES = (
    "Establish Patient Adult Physical, Pediatric Well-Child Exam, "
    "Rapid Strep / Flu Combo Swab, Routine Blood Draw (Venipuncture), "
    "Simple Wound Laceration Repair (Sutures), Urgent Care Visit (Level 1 / Basic)"
)
_DOCTORS = (
    "Dr. Elena Rostova (Family Medicine), Dr. Marcus Vance (Internal Medicine), "
    "Dr. Omar Haddad (Family Medicine), Dr. Priya Chandrasekaran (Internal Medicine), "
    "James Whitaker (Urgent Care), Sarah Jenkins (Wellness & Acute Care)"
)

# (id, category, message, expected, context) -- `expected` keys are only
# checked when present; a case may check just intent, or intent + one or
# two structural fields. `context` is an optional conversation_context
# dict (recent_turns / bare ctx) for follow-up/context-switch/stale-
# context cases.
_CASES: list[dict] = []


def _case(id_, category, message, expected, context=None):
    _CASES.append(
        {"id": id_, "category": category, "message": message, "expected": expected, "context": context}
    )


# A. Explicit services
_case("A1", "explicit_service", "How much does your flu test cost?", {"intents": {"pricing", "services_offered"}, "service_filter_mode": {"category", "named"}})
_case("A2", "explicit_service", "I need to get my blood drawn", {"intents": {"services_offered", "pricing"}, "service_filter_mode": {"category", "named"}})
_case("A3", "explicit_service", "I need stitches for a cut", {"intents": {"services_offered", "pricing"}, "service_filter_mode": {"category", "named"}})
_case("A4", "explicit_service", "I need an adult physical", {"intents": {"services_offered", "pricing", "book_appointment"}, "service_filter_mode": {"named", "category"}})
_case("A5", "explicit_service", "My child needs a yearly checkup", {"intents": {"services_offered", "pricing", "book_appointment"}})

# B. Generic ambiguity (must NOT silently commit to one narrow reading at the NLU layer -- named-mode-with-no-entity or none/category, never a fabricated exact match)
_case("B1", "generic_ambiguity", "I need a checkup", {"intents": {"services_offered", "pricing"}, "entities_service_null_or_generic": True})
_case("B2", "generic_ambiguity", "I need a test", {"intents": {"services_offered", "pricing", "medical_question", "unknown"}})
_case("B3", "generic_ambiguity", "I need a doctor", {"intents": {"doctor_search"}, "service_filter_mode": {"none"}})
_case("B4", "generic_ambiguity", "I need an appointment", {"intents": {"book_appointment", "doctor_availability"}})
_case("B5", "generic_ambiguity", "I need a physical", {"intents": {"services_offered", "pricing", "book_appointment"}})
_case("B6", "generic_ambiguity", "Do you do screenings?", {"intents": {"services_offered", "faq"}})

# C. Unsupported capabilities (must never classify as an off-topic dead-end; entity.symptom should still be extracted so Python/resolver can produce an honest decline)
_case("C1", "unsupported", "Do you treat heart transplants?", {"intents": {"medical_question", "doctor_search", "services_offered", "off_topic"}, "not_intents": set()})
_case("C2", "unsupported", "Do you offer chemotherapy?", {"intents": {"medical_question", "doctor_search", "services_offered", "off_topic"}})
_case("C3", "unsupported", "Can you do dialysis here?", {"intents": {"medical_question", "doctor_search", "services_offered", "off_topic"}})
_case("C4", "unsupported", "Do you have an MRI machine?", {"intents": {"doctor_search", "services_offered", "medical_question", "off_topic"}})
_case("C5", "unsupported", "Do you do radiation therapy?", {"intents": {"medical_question", "doctor_search", "services_offered", "off_topic"}})
_case("C6", "unsupported", "Can you perform an organ transplant?", {"intents": {"medical_question", "doctor_search", "services_offered", "off_topic"}})

# D. Medical definitions -- must be medical_question/definitional, never services_offered/doctor_search
_case("D1", "definitional", "What is a laceration?", {"intents": {"medical_question"}, "medical_question_mode": {"definitional"}})
_case("D2", "definitional", "What causes the flu?", {"intents": {"medical_question"}, "medical_question_mode": {"definitional"}})
_case("D3", "definitional", "What is a blood test?", {"intents": {"medical_question"}, "medical_question_mode": {"definitional"}})
_case("D4", "definitional", "What is hypothyroidism?", {"intents": {"medical_question"}, "medical_question_mode": {"definitional"}})

# E. Personal symptoms -- must be medical_question/personal or doctor_search (care nav), never services_offered
_case("E1", "personal_symptom", "I have a sore throat", {"intents": {"medical_question", "doctor_search"}, "not_intents": {"services_offered", "pricing"}})
_case("E2", "personal_symptom", "My gums are bleeding", {"intents": {"medical_question", "doctor_search"}, "not_intents": {"services_offered", "pricing"}})
_case("E3", "personal_symptom", "I cut my hand", {"intents": {"medical_question", "doctor_search"}, "not_intents": {"services_offered", "pricing"}})
_case("E4", "personal_symptom", "My stomach hurts", {"intents": {"medical_question", "doctor_search"}, "not_intents": {"services_offered", "pricing"}})

# F. Treatment requests -- explicit procedure named, must be services_offered/pricing
_case("F1", "treatment_request", "I need stitches", {"intents": {"services_offered", "pricing"}})
_case("F2", "treatment_request", "Can you treat this cut?", {"intents": {"services_offered", "pricing", "doctor_search"}})
_case("F3", "treatment_request", "I need a flu test", {"intents": {"services_offered", "pricing"}})
_case("F4", "treatment_request", "I need blood work", {"intents": {"services_offered", "pricing"}})

# G. Doctor search
_case("G1", "doctor_search", "Who are your doctors?", {"intents": {"doctor_search"}, "service_filter_mode": {"none"}})
_case("G2", "doctor_search", "Do you have a cardiologist?", {"intents": {"doctor_search"}})
_case("G3", "doctor_search", "Which doctor can see my kid?", {"intents": {"doctor_search"}})
_case("G4", "doctor_search", "Is there a Spanish-speaking doctor?", {"intents": {"doctor_search"}, "entities_language": "Spanish"})

# H. Specialty search
_case("H1", "specialty_search", "Do you have Family Medicine?", {"intents": {"doctor_search", "faq"}})
_case("H2", "specialty_search", "Do you offer Urgent Care?", {"intents": {"doctor_search", "services_offered", "faq"}})
_case("H3", "specialty_search", "Do you have Internal Medicine doctors?", {"intents": {"doctor_search"}})

# I. Pricing
_case("I1", "pricing", "How much is a physical?", {"intents": {"pricing", "services_offered"}})
_case("I2", "pricing", "What's the price of a blood draw?", {"intents": {"pricing", "services_offered"}})
_case("I3", "pricing", "How much are stitches?", {"intents": {"pricing", "services_offered"}})
_case("I4", "pricing", "Cost of a flu test?", {"intents": {"pricing", "services_offered"}})

# J. Availability
_case("J1", "availability", "Is there any slot available Monday?", {"intents": {"doctor_availability"}})
_case("J2", "availability", "What's your earliest appointment?", {"intents": {"doctor_availability", "book_appointment"}})
_case("J3", "availability", "Is Dr. Vance free tomorrow?", {"intents": {"doctor_availability"}, "entities_doctor_name": "Vance"})
_case("J4", "availability", "Can I get seen for urgent care today?", {"intents": {"doctor_availability", "book_appointment"}})

# K. Booking
_case("K1", "booking", "Book me with Dr. Rostova Monday", {"intents": {"book_appointment"}, "entities_doctor_name": "Rostova"})
_case("K2", "booking", "I want to schedule an appointment", {"intents": {"book_appointment"}})
_case("K3", "booking", "I want to book a physical", {"intents": {"book_appointment"}})

# L. Multi-intent (compound)
_case("L1", "multi_intent", "Do you accept Aetna and can I book Dr. Vance?", {"intents": {"insurance_accepted"}, "secondary_intents_contains": {"book_appointment", "doctor_availability", "doctor_search"}})
_case("L2", "multi_intent", "What are your hours and do you have parking?", {"intents": {"clinic_hours", "faq"}})
_case("L3", "multi_intent", "How much is a physical and is Dr. Haddad available?", {"intents": {"pricing", "services_offered"}, "secondary_intents_contains": {"doctor_availability"}})

# M. Negation
_case("M1", "negation", "I don't need stitches, just want to ask about pricing", {"intents": {"pricing", "services_offered"}})
_case("M2", "negation", "I'm not looking for a doctor right now, just checking hours", {"intents": {"clinic_hours"}})
_case("M3", "negation", "No, I don't want an appointment, just information", {"intents": {"faq", "off_topic", "unknown"}})

# N. Follow-ups (need recent context to be meaningful)
_FOLLOWUP_CTX = {"recent_turns": [
    {"role": "user", "content": "How much does your flu test cost?"},
    {"role": "assistant", "content": "Rapid Strep / Flu Combo Swab is $35.00, about 10 minutes."},
]}
_case("N1", "follow_up", "yes please", {"intents": {"follow_up", "book_appointment", "pricing", "services_offered"}}, context=_FOLLOWUP_CTX)
_case("N2", "follow_up", "book it", {"intents": {"book_appointment", "follow_up"}}, context=_FOLLOWUP_CTX)
_case("N3", "follow_up", "how much is it", {"intents": {"pricing", "follow_up"}}, context=_FOLLOWUP_CTX)
_case("N4", "follow_up", "what about next week", {"intents": {"doctor_availability", "follow_up", "book_appointment"}}, context=_FOLLOWUP_CTX)

# O. Context switching (explicit switch phrase -- must drop old topic)
_case("O1", "context_switch", "Actually forget that, I need a checkup instead", {"intents": {"services_offered", "pricing"}}, context=_FOLLOWUP_CTX)
_case("O2", "context_switch", "Never mind, can you tell me your hours?", {"intents": {"clinic_hours"}}, context=_FOLLOWUP_CTX)
_case("O3", "context_switch", "Let's talk about something else -- do you accept Aetna?", {"intents": {"insurance_accepted"}}, context=_FOLLOWUP_CTX)

# P. Stale-context adversarial -- prior turns mention Priya/stitches; new unrelated question must not leak doctor/service/symptom entities
_STALE_CTX = {"recent_turns": [
    {"role": "user", "content": "Can I book Dr. Priya Chandrasekaran?"},
    {"role": "assistant", "content": "Dr. Priya Chandrasekaran has openings Tuesday at 10am."},
    {"role": "user", "content": "I cut my hand and need stitches"},
    {"role": "assistant", "content": "Simple Wound Laceration Repair (Sutures) is $240.00, about 45 minutes."},
]}
_case("P1", "stale_context", "What are your hours?", {"intents": {"clinic_hours"}, "entities_doctor_name_null": True, "entities_service_null": True}, context=_STALE_CTX)
_case("P2", "stale_context", "Do you accept Cigna?", {"intents": {"insurance_accepted"}, "entities_doctor_name_null": True, "entities_service_null": True}, context=_STALE_CTX)
_case("P3", "stale_context", "I need to get my blood drawn", {"intents": {"services_offered", "pricing"}, "entities_doctor_name_null": True}, context=_STALE_CTX)

# Q. Typos/slang
_case("Q1", "typos_slang", "how much is a flu tst?", {"intents": {"pricing", "services_offered"}})
_case("Q2", "typos_slang", "need stiches for a cut", {"intents": {"services_offered", "pricing"}})
_case("Q3", "typos_slang", "wat time r u open 2day", {"intents": {"clinic_hours"}})
_case("Q4", "typos_slang", "any doc avail 2moro afternoon", {"intents": {"doctor_availability"}})


def _make_provider(model_name: str):
    """`OpenAINLUProvider` as-is for the gpt-4.1 family already in production.

    GPT-5.x models reject the `max_tokens` param production's provider
    class hardcodes (`max_completion_tokens` is required instead --
    confirmed live, HTTP 400 `unsupported_parameter`). That is itself a
    real finding (see report), not a benchmark artifact to hide: adopting
    any GPT-5.x model would need a small `openai_provider.py` change,
    which is production code and out of scope for this read-only
    benchmarking phase. `_GPT5CompatProvider` below duplicates just enough
    of `classify()` locally, for this harness only, so GPT-5.x can still
    be measured without touching the shipped provider.
    """
    from apps.chatbot.nlu.openai_provider import OpenAINLUProvider

    if model_name.startswith("gpt-5"):
        return _GPT5CompatProvider(model_name=model_name, api_key=settings.OPENAI_API_KEY)
    return OpenAINLUProvider(model_name=model_name, api_key=settings.OPENAI_API_KEY)


class _GPT5CompatProvider:
    """Benchmark-only shim: identical prompts/parsing to `OpenAINLUProvider`,
    `max_completion_tokens` instead of `max_tokens` for the GPT-5.x family."""

    def __init__(self, *, model_name: str, api_key: str) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key, timeout=30.0)
        return self._client

    def classify(self, *, message: str, conversation_context=None, timeout: float | None = None):
        from apps.chatbot.nlu.json_utils import parse_json_response
        from apps.chatbot.nlu.prompts import build_user_prompt, get_system_prompt

        client = self._get_client()
        system_prompt = get_system_prompt()
        user_prompt = build_user_prompt(message, conversation_context)
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=self.model_name,
            # GPT-5.x reasoning-tier models consume part of this budget on
            # hidden reasoning before the visible JSON -- 256 (the gpt-4.1
            # value) truncated valid JSON mid-object on ~30% of live calls.
            # 800 is a benchmark-only generosity, not a claim this is the
            # right production budget for this model family.
            max_completion_tokens=800,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=timeout or 15.0,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        choice = response.choices[0].message.content or ""
        data = parse_json_response(choice)
        usage = response.usage
        data["_usage"] = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        data["_timings"] = {"total_ms": elapsed_ms}
        data["_classifier_source"] = "openai_gpt5_shim"
        return data


def _build_context(case: dict) -> dict:
    ctx = {
        "services": _SERVICES,
        "doctors": _DOCTORS,
    }
    if case.get("context"):
        ctx.update(case["context"])
    return ctx


def _score_case(case: dict, raw: dict) -> dict:
    expected = case["expected"]
    problems = []
    intent = raw.get("intent")
    if "intents" in expected and intent not in expected["intents"]:
        problems.append(f"intent={intent!r} not in {sorted(expected['intents'])}")
    if "not_intents" in expected and intent in expected["not_intents"]:
        problems.append(f"intent={intent!r} is a forbidden intent")
    sfm = raw.get("service_filter_mode")
    if "service_filter_mode" in expected and sfm not in expected["service_filter_mode"]:
        problems.append(f"service_filter_mode={sfm!r} not in {sorted(expected['service_filter_mode'])}")
    mqm = raw.get("medical_question_mode")
    if "medical_question_mode" in expected and mqm not in expected["medical_question_mode"]:
        problems.append(f"medical_question_mode={mqm!r} not in {sorted(expected['medical_question_mode'])}")
    entities = raw.get("entities") or {}
    if expected.get("entities_doctor_name_null") and entities.get("doctor_name"):
        problems.append(f"doctor_name leaked: {entities.get('doctor_name')!r}")
    if expected.get("entities_service_null") and entities.get("service"):
        problems.append(f"service leaked: {entities.get('service')!r}")
    if "entities_language" in expected:
        lang = entities.get("language") or ""
        if expected["entities_language"].lower() not in str(lang).lower():
            problems.append(f"language={lang!r} expected to contain {expected['entities_language']!r}")
    if "entities_doctor_name" in expected:
        dn = entities.get("doctor_name")
        dn_str = " ".join(dn) if isinstance(dn, list) else str(dn or "")
        if expected["entities_doctor_name"].lower() not in dn_str.lower():
            problems.append(f"doctor_name={dn!r} expected to contain {expected['entities_doctor_name']!r}")
    if "secondary_intents_contains" in expected:
        sec = set(raw.get("secondary_intents") or [])
        if not (sec & expected["secondary_intents_contains"]):
            problems.append(f"secondary_intents={sorted(sec)} missing one of {sorted(expected['secondary_intents_contains'])}")
    return {"correct": not problems, "problems": problems}


class Command(BaseCommand):
    help = "Controlled NLU model benchmark: fixed dataset x fixed (current) prompt x N models x N repeats"

    def add_arguments(self, parser):
        parser.add_argument("--models", type=str, default="gpt-4.1-nano,gpt-4.1-mini")
        parser.add_argument("--repeats", type=int, default=3)
        parser.add_argument("--json-out", type=str, default="")
        parser.add_argument("--workers", type=int, default=12)

    def handle(self, *args, **opts):
        models = [m.strip() for m in opts["models"].split(",") if m.strip()]
        repeats = opts["repeats"]
        workers = opts["workers"]

        self.stdout.write(f"Benchmarking {len(models)} model(s) x {len(_CASES)} cases x {repeats} repeats "
                           f"= {len(models) * len(_CASES) * repeats} live calls...\n")

        jobs = []
        for model in models:
            provider = _make_provider(model)
            for case in _CASES:
                for rep in range(repeats):
                    jobs.append((model, provider, case, rep))

        results = []

        def _run(job):
            model, provider, case, rep = job
            ctx = _build_context(case)
            t0 = time.perf_counter()
            try:
                raw = None
                last_exc = None
                for attempt in range(3):
                    try:
                        raw = provider.classify(message=case["message"], conversation_context=ctx, timeout=15.0)
                        break
                    except Exception as exc:  # noqa: BLE001 -- rate-limit retry only
                        last_exc = exc
                        if "429" in str(exc) or "rate_limit" in str(exc).lower():
                            time.sleep(2.0 * (attempt + 1))
                            continue
                        raise
                if raw is None:
                    raise last_exc
                elapsed = (time.perf_counter() - t0) * 1000
                score = _score_case(case, raw)
                usage = raw.get("_usage") or {}
                return {
                    "model": model,
                    "case_id": case["id"],
                    "category": case["category"],
                    "message": case["message"],
                    "rep": rep,
                    "intent": raw.get("intent"),
                    "confidence": raw.get("confidence"),
                    "service_filter_mode": raw.get("service_filter_mode"),
                    "medical_question_mode": raw.get("medical_question_mode"),
                    "entities": raw.get("entities"),
                    "correct": score["correct"],
                    "problems": score["problems"],
                    "latency_ms": round(elapsed, 1),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "error": None,
                }
            except Exception as exc:
                elapsed = (time.perf_counter() - t0) * 1000
                return {
                    "model": model,
                    "case_id": case["id"],
                    "category": case["category"],
                    "message": case["message"],
                    "rep": rep,
                    "intent": None,
                    "correct": False,
                    "problems": [f"provider_error: {exc}"],
                    "latency_ms": round(elapsed, 1),
                    "error": str(exc),
                }

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run, job) for job in jobs]
            for fut in as_completed(futures):
                results.append(fut.result())
                done += 1
                if done % 25 == 0:
                    self.stdout.write(f"  ...{done}/{len(jobs)} calls done")

        if opts["json_out"]:
            with open(opts["json_out"], "w") as f:
                json.dump(results, f, indent=2, default=str)
            self.stdout.write(f"Wrote raw results to {opts['json_out']}")

        self._report(results, models, repeats)

    def _report(self, results, models, repeats):
        by_model = defaultdict(list)
        for r in results:
            by_model[r["model"]].append(r)

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("PER-MODEL SUMMARY")
        self.stdout.write("=" * 70)
        for model in models:
            rows = by_model[model]
            n = len(rows)
            correct = sum(1 for r in rows if r["correct"])
            errors = sum(1 for r in rows if r.get("error"))
            latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") and not r.get("error")]
            p_tokens = [r["prompt_tokens"] for r in rows if r.get("prompt_tokens")]
            c_tokens = [r["completion_tokens"] for r in rows if r.get("completion_tokens")]

            # Consistency: for each case, do all `repeats` runs agree on intent?
            by_case = defaultdict(list)
            for r in rows:
                by_case[r["case_id"]].append(r["intent"])
            consistent_cases = sum(1 for ids in by_case.values() if len(set(ids)) == 1)

            self.stdout.write(f"\n{model}")
            self.stdout.write(f"  Accuracy:        {correct}/{n} ({100*correct/n:.1f}%)")
            self.stdout.write(f"  Provider errors: {errors}/{n}")
            self.stdout.write(f"  Consistency:     {consistent_cases}/{len(by_case)} cases had identical intent across all {repeats} reps")
            if latencies:
                self.stdout.write(f"  Latency p50/p95: {statistics.median(latencies):.0f}ms / "
                                   f"{sorted(latencies)[int(0.95*len(latencies))-1]:.0f}ms")
            if p_tokens:
                self.stdout.write(f"  Tokens in/out (avg): {statistics.mean(p_tokens):.0f} / {statistics.mean(c_tokens):.0f}")

            self.stdout.write("  By category:")
            by_cat = defaultdict(lambda: [0, 0])
            for r in rows:
                by_cat[r["category"]][1] += 1
                if r["correct"]:
                    by_cat[r["category"]][0] += 1
            for cat, (ok, total) in sorted(by_cat.items()):
                self.stdout.write(f"    {cat:20s} {ok}/{total}")

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("FAILURES (first 40)")
        self.stdout.write("=" * 70)
        shown = 0
        for r in results:
            if not r["correct"] and shown < 40:
                self.stdout.write(f"[{r['model']}] {r['case_id']} rep{r['rep']} {r['message']!r}")
                for p in r["problems"]:
                    self.stdout.write(f"    - {p}")
                shown += 1
