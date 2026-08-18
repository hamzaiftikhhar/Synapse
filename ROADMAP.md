# Synapse Chatbot — Roadmap

Status legend: ✅ done · 🔄 in progress · ⏳ planned · 💤 deferred (real, not forgotten)

This file is the record of what already happened and why, so a new session
doesn't have to re-derive it. **Read this and ARCHITECTURE.md before
inspecting source for a new phase.** Update this file at the end of every
phase — that's what keeps it trustworthy.

Baseline test/eval numbers referenced below (`313/313`, `674/682`, etc.) all
come from:
```
python manage.py test apps.chatbot.tests --keepdb
python manage.py run_chat_eval --target 520
```
(bare `manage.py test` with no args is broken — see ARCHITECTURE.md §12.)

---

## Phase 0 — Baseline ✅

Captured pre-refactor behavior (git baseline, full test/eval run, named
problem-case snapshot) before any change. Confirmed the P0 bug: an
unknown-doctor booking request showed a refusal message **and** launched
the booking wizard at the same time. Baseline: 303/303 tests, 678/682
(99.4%) eval, 4 pre-existing failures all in `adversarial_booking_slang_squeeze`
("yo can yall squeeze me in today").

## Phase 1 — Booking-wizard eligibility ✅

**Bug:** `ui_meta.py` derived booking-wizard eligibility from raw `intent`
instead of `ExecutionPlan.booking`, so a refusal (e.g. unknown-doctor) could
render next to an active wizard.
**Fix:** `wants_booking_wizard = exec_plan_booking` — single source of truth.
**File:** `apps/chatbot/ui_meta.py`.
**Verified:** 303/303, eval unchanged (678/682).

## Phase 2 — `resolve_plan_after_sql` ✅

**Bug:** `_should_hybrid_rag()` (engine.py) decided SQL→vector escalation
*after* the plan was built, as an untracked boolean — `EngineResult` could
end up describing two different routes (stale plan read for some fields,
escalated state for others), and the escalation path double-composed the
response (SQL text composed and discarded, then a second LLM call made).
**Fix:** planner pre-authorizes `fallback_vector_tasks` at planning time;
`resolve_plan_after_sql(plan, *, sql_found)` is the only legitimate
post-SQL plan mutation, called once by the engine, which reassigns its
`exec_plan` local to the result (no second variable to go stale).
**Files:** `apps/chatbot/planner.py`, `apps/chatbot/engine.py`.
**Verified:** 303/303, eval unchanged; dedicated hybrid-escalation
verification script (temp, deleted after use) proved `route`/`lane`/
`needs_vector`/`needs_llm` all agree post-resolution.
`_should_hybrid_rag` deleted only after the replacement was tested, per
explicit instruction.

## Phase 3 — Shared sensor logic (production ⇄ eval) ✅

**Bug:** `engine.py` and `eval/runner.py` independently reimplemented the
same sensor formulas and had drifted: eval was missing the typo-booking
branch of `is_booking_intent`, reimplemented `booking_commit` as a crude
4-phrase literal check instead of calling `is_booking_commit`, was missing
`looks_like_symptom` in `soft_medical`, reimplemented `matched_docs` with a
weaker inline matcher instead of calling `matching_document_ids`, had a
`doc_match` formula with an extra term and a missing intent, and had a
looser `degraded` formula. `choose_plan()` was also missing
`doctor_availability_query`/`urgent_availability` params entirely, so eval
could never exercise them.
**Fix:** extracted `compute_message_sensors()` into `planner.py` as the one
shared, pure, I/O-free sensor computation; both `engine.py` and
`eval/runner.py` now call it. Moved 3 pure ChatEngine private methods
(`_looks_like_symptom`, `_is_doctor_ranking_request`,
`_looks_like_instruction_injection`) to `routing/signals.py` as standalone
functions so eval could reach them.
**Files:** `planner.py`, `engine.py`, `eval/runner.py`, `routing/signals.py`.
**Verified:** 303/303 tests. Eval dropped 678/682 → **674/682 (98.8%)** —
**not a regression**: it's eval correctly seeing a real production behavior
it was previously blind to. "my kid got sick" (UNKNOWN intent, low
confidence) triggers `soft_medical=True` via `looks_like_symptom` matching
"sick", and `build_execution_plan` returns the soft-medical direct reply
*before* the low-confidence clarify check ever runs (`planner.py`, the
`facts.soft_medical and not sql_tasks...` branch). This has been true in
production the whole time; eval's old formula just couldn't see it.
**Open question, not resolved:** should `soft_medical` unconditionally
preempt clarify for low-confidence UNKNOWN intent? Flagged, not decided,
not touched since.

## Phase 4 — Service resolver wiring ✅

Wired the existing, already-tested `match_services_in_message()` (already
running via `compute_message_sensors`) through to be authoritative for SQL:
`MessageSensors.matched_service_ids` → `PlannerFacts.matched_service_ids` →
`ExecutionPlan.resolved_service_ids` → `SQLContext.resolved_service_ids` →
`services_offered()`. The handler now does
`ctx.resolved_service_ids or _match_services_strict(ctx)` — planner-
authorized first, legacy matcher only as fallback, never regressing
call sites that bypass the planner (`SQLTool.run`).
**Files:** `planner.py`, `engine.py`, `eval/runner.py`, `sql_tool/base.py`,
`sql_tool/service.py`, `sql_tool/handlers/services.py`. New:
`tests/test_service_resolver_authority.py`.
**Verified:** 308/308 (303 + 5 new), eval unchanged 674/682. End-to-end
temp test proved a real `ChatEngine.process()` call threading a real
service UUID from message → resolved_service_ids → SQL filter.
**Old matchers not deleted** — explicit instruction, see Phase 6.

## Phase 5 — Category-mode resolution precedence ✅

**Bug:** category mode never consulted `resolved_ids.service_id` at all
(named mode did), and fell back to a raw `entities.service` icontains that
silently matches zero rows for a paraphrase (e.g. NLU extracts "laser
treatment", no service is literally named that).
**Fix:** category mode now checks `resolved_ids.service_id` first, same as
named mode; the icontains-on-raw-entity fallback was removed for category
mode specifically (kept for named mode, unaffected).
**File:** `apps/chatbot/sql_tool/handlers/services.py`.
**Tests added** (`tests/test_services_category_filter.py`): resolved ID
wins despite a paraphrase that icontains would miss; resolved ID wins over
a *disagreeing* message-resolver result; no resolved ID falls through to
the message resolver correctly.
**Verified:** 311/311, eval unchanged 674/682.

## Phase 6 — Service matcher audit ✅ (no deletions)

Audited all three matchers (see ARCHITECTURE.md §5). Empirically compared
`match_services_in_message` vs `_match_services_strict` across 36
adversarial messages / 30 services — zero cases where the legacy matcher
found something the canonical one missed. **But** found a real, provable
reason not to delete it anyway: `build_service_catalog(clinic, limit=40)`
caps the canonical resolver's input at 40 services; `_match_services_strict`
queries the DB uncapped. A clinic with >40 active services has services
past #40 (alphabetically) **invisible** to the canonical resolver — not a
worse match, never a candidate at all.
**New permanent test:** `LegacyMatcherCatalogLimitTests` (in
`test_service_resolver_authority.py`) — 45-service clinic, target service
sorted 45th, proves the capped catalog can't see it and the legacy matcher
still does. This is the standing reason the legacy matcher stays; if
`build_service_catalog`'s limit is ever raised/removed, re-run this
analysis before deleting `_match_services_strict`.
**Verified:** 313/313, eval unchanged. No production code changed.

## Phase 7 — `PlannerFacts` / `ExecutionPlan` dead-field cleanup ✅ (partial)

Grepped every `facts.<field>` read inside `build_execution_plan` and
cross-referenced the rest of the codebase. Removed 5 fields from
`PlannerFacts` that were computed, serialized into `to_dict()`, and never
read by the planner or by anything downstream: `booking_commit`,
`service_hit`, `prefer_vector`, `confidence_band`, `matched_doc_ids`. Each
has a real, independently-tracked source elsewhere that's what's actually
used (e.g. `booking_commit` the local var in engine.py, `conf_policy.band.value`
for confidence_band).
`choose_plan()`'s public signature was kept **fully unchanged** (still
accepts all 5 as params) — it just stopped forwarding them internally, with
a `del ...` line mirroring the pre-existing `del needs_vector` pattern. Zero
test call sites needed updating.
**Found, not removed:** `ExecutionPlan.scores` / `PlannerScores` — same
"computed, serialized, never read" pattern, confirmed via full-codebase
grep including `apps/api` and `frontend/src`. Not removed here because it's
structurally bigger (whole class, ~9 construction call sites across every
early-return branch of `build_execution_plan`) — "one small group at a
time." 💤 Deferred, own phase whenever wanted.
**Verified:** 313/313, eval unchanged.

## Phase 8 — Remove `PlannerScores` ✅

Completed the Phase 7 deferral. Removed the `PlannerScores` dataclass,
`ExecutionPlan.scores`, `PlannerDecision.scores`, and all 9 construction
sites inside `build_execution_plan` (including the two multi-line
score-weighting blocks). `conf` (confidence float) survived — still used
for `fact_dict["confidence"]`, unrelated to the removed score math.
**File:** `apps/chatbot/planner.py` only (6 insertions, 71 deletions).
**Verified:** 313/313 (exact match to Phase 7 baseline), eval unchanged
674/682. Zero behavioral change — this was a pure dead-code removal, not
bundled with anything else, per explicit instruction.

## Phase 9A — NLU total timeout ceiling ✅

**Bug, confirmed against a real transcript:** provider chain (primary
openai 3.5s → openai_fallback 3.0s → gemini 3.0s) let each attempt claim
its own full timeout independently on failure — observed 10.9s NLU latency
for one message against a documented "3.5s timeout."
Implemented by an external agent (Cursor) in this repo, then **independently
verified** (not trusted blind): re-ran the diff, re-ran all tests myself,
confirmed the `_MIN_ATTEMPT_SECONDS = 0.1` floor genuinely matches
`deadline.py`'s own `max(0.1, seconds)` clamp, confirmed `future.cancel()`
semantics claim against real `concurrent.futures` behavior.
**Fix:** `NLU_TOTAL_BUDGET_SECONDS` (default 5.0) bounds the whole chain;
`min(per_provider_cap, remaining)` per attempt — cap-then-remaining, not an
even split (primary keeps its full 3.5s when it's the only/first attempt).
A budget-exhausted skip does not trip that provider's circuit breaker.
**Files:** `config/settings/base.py`, `apps/chatbot/nlu/classifier.py`,
`apps/chatbot/tests/test_nlu.py` (7 deterministic fake-clock tests from
Cursor + 1 realistic multi-turn circuit-breaker test added during
verification — see ARCHITECTURE.md §8 for what it found).
**Also found and fixed during verification, unrelated to 9A:** a
pre-existing date-flaky test in `test_sql_tool.py`
(`assertNotIn("T", when)` — the fixture schedules "today + 2 days," and
when that lands on a Tuesday or Thursday the weekday abbreviation itself
contains "T", ~2/7 of days). Fixed with a precise ISO-separator regex
instead of a bare substring check.
**Verified:** 321/321 (320 after the flaky-test fix + 1 new realistic
test), eval unchanged 674/682.

## Phase 9B — Embedding model cold start ✅

**Bug, reproduced and measured on this machine, not assumed:** local
SentenceTransformer (`BAAI/bge-base-en-v1.5`) loads lazily on first vector
search. Measured: **20.26s** cold (9.77s import + 7.28s construct + 3.22s
first encode) vs **0.042s** warm — ~480x. Matches a real transcript's 24.9s
`vector_ms`. pgvector's HNSW index was never the bottleneck (confirmed
present in migrations).
**Fix:** `KnowledgeConfig.ready()` synchronously warms the model via
`warm_up_embedding_service()`, guarded by `should_warm_up_embeddings(argv)`
which skips non-serving management commands (found and added
`run_chat_eval` to the skip list after observing it triggered warm-up
unnecessarily — it never touches real vector search).
**Files:** `apps/knowledge/apps.py`, `apps/knowledge/embeddings/factory.py`.
New: `apps/knowledge/tests/test_embedding_warmup.py`.
**Verified end-to-end with real (non-mocked) `django.setup()`**, not just
unit tests: simulated `runserver` startup → model in `_model_cache` before
any request exists (~18.8s, paid once). Simulated `test` startup → cache
stays empty, setup completes in ~1.9s. Unit tests separately prove a
simulated "first real request" after warm-up does not re-trigger
`SentenceTransformer.__init__`.
**Untouched, as instructed:** embedding model/provider, vector DB,
retrieval algorithm, planner, engine, NLU, response generation.
**Verified:** 346/346 (321 + 25 knowledge tests, incl. 1 renamed/fixed),
eval unchanged 674/682.

---

## Off-roadmap — Real-world booking bugs found via live testing ✅ (partial)

Not a numbered phase — the user found these by actually using the chatbot
from the dashboard and pasted real conversation transcripts + pipeline-debug
logs. Two rounds:

**Round 1 (external agent, "Cursor," verified not fixed by me):** race
condition on booking-widget mount firing 3 duplicate `POST
/booking/start` requests (in-flight ref added), "thurs"/"tues"/"weds" not
recognized as day abbreviations (added, with whole-word matching so
"sunscreen"/"sun damage" don't misread as Sunday), availability replies not
naming which day they used (silent tomorrow-fallback was invisible), noon/
12:30 rendering as "0:00"/"0:30" in the confirmation card (missing
`hour12: true`), Postgres deadlocks surfacing as raw 500s instead of a clean
409, and a pre-insert overlap check that only matched exact `start_time`
instead of any overlap (mismatched the DB's own exclusion constraint).
Verified independently: all 5 files genuinely modified, 408/408 (chatbot +
appointments) tests pass here.

**Round 2 (found after Round 1, from new transcripts + real pipeline-debug
logs in `logs/chat/`):**

1. **Date extraction still silently defaulted to "tomorrow" for typo'd/
   differently-prepositioned phrasing.** Confirmed from real logs: "is
   there any doc avaialbe of fri mornign" (typo "mornign", preposition
   "of" not "on") produced `entities.date: null` from *both* local
   extraction and the LLM — `sql_tool/handlers/doctors.py`'s
   `target_date is None` fallback then silently used tomorrow, and three
   different requested days (fri/wed/mon) all collapsed to the same
   Wednesday. Root cause: `entity_extract.py`'s day-abbreviation regex
   required either an `on|this|next` prefix or an *exactly*-spelled
   trailing time-of-day word — "of" and "mornign" each independently broke
   it, and together guaranteed failure. **Fix:** re-tiered the 7 short
   day-forms by actual collision risk instead of treating them uniformly:
   `mon`/`tue`/`thu`/`fri` (no real English-word collision) now match
   unconditionally; `wed`/`sat` (low collision risk) get a broadened
   preposition set (`on|this|next|for|of`); `sun` (genuine, dermatology-
   specific collision — "sun damage", "sun exposure") deliberately keeps
   the narrow `on|this|next`-only framing. Applied identically to
   `nlu/entity_extract.py` and `sql_tool/utils.py::parse_natural_date` (two
   independent regexes that both needed the same fix). Verified against
   real collision phrases ("for sun damage", "of sun damage and
   sunscreen", "she sat down for the consultation", "we got wed last
   year") — none misfire.
2. **Confirmation card showed the wrong AM/PM** (booked 9:30 AM, confirmed
   "9:30 pm") — same hour digits, flipped meridiem, which is the signature
   of a ~12-hour timezone difference between the clinic ("-07:00" in the
   actual SQL rows, confirmed real) and the viewer's browser. Root cause:
   `formatConfirmTime` in `booking-wizard.tsx` used
   `new Date(raw).toLocaleTimeString(undefined, {hour12: true})`, which
   re-interprets the instant in the *browser's* local timezone. The same
   file already has the correct, documented pattern for this exact
   situation two functions away (`slotHour()`: "never `Date.getHours()`,
   which would silently convert to the browser's local timezone") — just
   not applied here. **Fix:** `formatConfirmTime` now reads the wall-clock
   hour/minute directly from the ISO string's digits, matching
   `slotHour()`'s existing rule; the `Date`/`toLocaleTimeString` path is
   gone (the file's only use of `toLocaleTimeString`, confirmed by
   grepping the whole frontend).

3. **Casual "accommodate me" scheduling phrasing misclassified as `faq`
   instead of an availability request.** Confirmed from real pipeline-
   debug logs: "can you hope me in for tue night" / "can you slip me in
   for sat morning" reached the Small LLM (gpt-4.1-nano) and got
   `intent=faq` (its own `reasoning_short` even said "Booking appointment
   for Tuesday night" while still outputting `faq`) → routed to
   `vector_rag` → the reply negotiated a time entirely in ungrounded prose
   instead of ever reaching `doctor_availability`/SQL. Root cause chain:
   the codebase already has a near-identical rule for "squeeze me in" (→
   `DOCTOR_AVAILABILITY`), but it lives in the "strong" rule tier, which is
   **opt-in only** (`NLU_RULES_BEFORE_LLM`, default `False`,
   `config/settings/base.py`) — off in this deployment. `eval/runner.py`
   calls `tier="strong"` *unconditionally* (no such gate), which is why
   eval already passed cases like this without ever proving production
   would. **Fix:** added a new, narrow pattern —
   `\b(?:hope?|slip|fit|pencil|work)\s+me\s+in\b` → `doctor_availability`
   — to the **"fast" tier** (`_match_fast`, unconditionally active
   pre-LLM), not the strong tier; entities still come through correctly
   via the existing `_with_entities` local-extraction merge (verified:
   `entities.date=["tue"]` etc., no LLM round-trip needed at all).
   Deliberately excludes "squeeze me in" itself — that phrase stays
   governed by the separate, still-dormant strong-tier rule, which is
   entangled with the long-standing `adversarial_booking_slang_squeeze`
   eval failure (unrelated, pre-existing since Phase 0, not touched).
   **File:** `apps/chatbot/nlu/rules.py`. **Tests:** 3 new in `test_nlu.py`
   — the exact failing phrasings + typo/synonym variants resolve to
   `doctor_availability` with correct dates; "I hope the doctor is
   available"/"work on my prescription"-style false-positive guards;
   confirms `squeeze me in` is untouched. **Verified end-to-end** (not
   just the rule in isolation): a real `ChatEngine.process()` call for
   "can you hope me in for tue night" now produces
   `intent=doctor_availability`, `route=sql_only`, `lane=sql_fast`, a real
   SQL query (`sql_ms` present), and a correctly-dated grounded response
   ("No available slots on Tuesday, August 25...") in **158ms** total —
   down from ~3.4s, since this phrasing no longer needs any LLM call at
   all. **Verified:** 330/330 chatbot tests, eval unchanged 674/682
   (including the pre-existing `adversarial_booking_slang_squeeze` failures
   — confirmed still failing for the exact same reason, untouched by this
   fix).
   **Worth flagging, not acted on:** the "strong" tier contains several
   other plausibly-still-relevant rules (book+appointment, doctor+
   availability phrasing, doctor-search) that are *also* dormant in
   production the same way this one was, and eval's unconditional
   `tier="strong"` call means eval has never proven any of them work in
   production either — this is the same class of production/eval drift
   Phase 3 fixed for the sensor layer, just at the classification layer
   instead. Not audited further here — that's a phase of its own (probably
   "does each dormant strong-tier rule still make sense, and should it move
   to fast-tier, get deleted, or stay opt-in").

**Files:** `apps/chatbot/nlu/entity_extract.py`, `apps/chatbot/sql_tool/utils.py`,
`apps/chatbot/nlu/rules.py`, `frontend/src/features/booking/booking-wizard.tsx`.
**Verified:** 330/330 chatbot tests, 408/408 chatbot+appointments, eval
unchanged 674/682. One pre-existing, unrelated flake reproduced in
isolation (`ConcurrentBookingTests.test_two_parallel_inserts_only_one_succeeds`
— a genuine Postgres deadlock race between two threads, 2/3 pass rate with
nothing else running; not touched by this or the prior round's changes).

**Still found, not fixed — needs its own scoping:**
- **Cross-turn day-of-week memory lost.** "Tuesday" (established in one
  turn) → "so let me in between 3-6" (next turn, no day repeated) →
  resolved to Wednesday (tomorrow-fallback again, not Tuesday from
  context). Same category as the already-deferred conversation-state/
  coreference item ("book with him") — short-term slot memory, not
  request-level entity extraction. Don't patch into the entity-extraction
  fix above; it's a different layer (conversation state, not per-message
  parsing).
- **Booking-picker frontend UX** — a real, separately-scoped proposal
  (data-driven appointment picker: single component, adapts to few-vs-many
  slots/doctors/dates, explicit per-option state, mobile-first) was
  provided but not implemented — it's a UI/interaction redesign, not a bug
  fix, and deserves its own design pass rather than being bundled into a
  correctness-bug round.

---

## ⏳ Phase 9C — Honest RAG degraded states

**Not started.** See ARCHITECTURE.md §7 for the confirmed bug: 4 different
failure states (empty retrieval, budget exhausted, LLM timeout, LLM error)
all produce the identical `empty_rag_reply()` copy, even when
`vector_rows` had real, relevant hits. Plan: distinguish "no results" from
"results found but synthesis failed" with different copy; don't
over-engineer the wording beyond that split. Add tests for both states.

## ⏳ Phase 10 — Service-existence questions → SQL

**Not started.** See ARCHITECTURE.md §6. "Do you have/offer/provide X?",
"Is X available?", "Is X a service?" need to land in the same SQL-triggering
bucket as "How much is X?" / "What services do you offer?" already do —
this is an intent/mode classification fix, not a RAG-authority fix (RAG
already correctly respects SQL facts when SQL runs). Regression battery:
6 phrasings of the same HydraFacial-style question must produce the same
service-existence answer.

## ⏳ Phase 11 — Doctor resolution evidence floor

**Not started.** Confirmed from a real transcript: "Schedule me with Dr."
(no name at all) resolves to a specific doctor instead of asking which one.
Root cause not yet fully traced (partial investigation pointed at
`resolve_doctor_candidates`'s stopword filtering leaving a stray word as a
weak fuzzy-match candidate, but wasn't confirmed against the actual booking-
flow code path). Needs: minimum-evidence rule (exact name / sufficiently
distinctive partial name / explicit UI-provided doctor ID) before ever
entering booking with a resolved doctor.

## 💤 Deferred — Conversation state / coreference

Real, confirmed from transcript ("which one treats cancer?" → "Dr. Chloe
Bennet" → "book with him" fails to resolve "him"). Deliberately not folded
into Phase 11 (doctor resolution) — the two are different problems: Phase 11
is about not over-trusting weak *explicit* evidence, this is about *implicit*
reference resolution, which needs actual conversation-state design work.
No phase number assigned yet; needs its own scoping pass before starting.

## 💤 Deferred — `ThreadPoolExecutor` saturation

See ARCHITECTURE.md §8. Real, documented, not measured under actual
concurrent load yet. Do not fix opportunistically inside an NLU-latency
phase — it changes concurrency behavior, which deserves isolated testing.

## 💤 Deferred — Remove `PlannerScores` — superseded, see Phase 8 (done)

## 💤 Deferred — Remove `_match_services_strict`

Blocked on the `build_service_catalog` 40-service catalog limit (Phase 6).
Either raise/remove that limit, or give the SQL-handler fallback path an
uncapped catalog fetch, before revisiting deletion.

---

## Working agreement (why phases stay this small)

- One phase, one focus. Report before starting the next.
- Every "found this too" gets a line in this file, not a same-turn fix,
  unless the phase's own scope already covers it.
- Every bug fix reproduces the failure first (with a real number/trace
  where possible — see 9A/9B above for what that looks like), then makes
  the smallest change, then adds a regression test that would have caught
  it.
- Full command reference: see `CLAUDE.md`.
