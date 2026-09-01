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

## Phase 12 — Temporal availability correctness ✅

**Bug, reproduced against current code before anything changed.** Asked on
2026-08-18, "is there any appointment available in December 12 morning"
answered with August slots, and "anything in November" answered with next
week's. Three independent defects fed the same output:

1. **`dates[0]` decided the search.** The NLU emits every date-ish string it
   found, unordered. Real logged payload for that December question:
   `["2023-12-12", "december 12"]` — the patient's own words *and* an ISO
   date the model normalized against its training cutoff. Position 0 won, so
   a year the patient never typed became the query, and the reply's weekday
   ("Tuesday, December 12") was correct for 2023 and wrong for 2026.
2. **Bare months parsed to nothing and silently became tomorrow.**
   `parse_natural_date("November")` returns `None`; the handler's
   `if target_date is None: target_date = tomorrow` turned an unanswerable
   question into a confidently wrong answer. Confirmed for both "November"
   and "December".
3. **Nothing downstream checked scope.** `ui_meta.py`'s availability branch
   maps `rows[:6]` into clickable chips and never reads `meta.target_date`,
   so August slots rendered as "Earliest openings" under December prose —
   one tap from a real booking on the wrong date.

**Root cause, one sentence:** temporal information was an unvalidated list of
strings read positionally, not resolved state — the same gap
`resolved_service_ids` closed for services in Phase 4.

**Fix:** new `apps/chatbot/temporal.py` — `TemporalQuery` (status, inclusive
`start`/`end`, `is_range`, `scope_label`, `horizon_end`) produced by
`resolve_temporal_query()`. Every entity becomes a dated candidate; each is
scored on **groundedness** — whether all its tokens appear in what the
patient actually typed. `"december 12"` is grounded, `"2023-12-12"` is not
(no `2023` anywhere in the message), so entity order stops mattering and a
model-invented past date is discarded rather than merely deprioritized.
Deliberately *not* fixed with `dates[-1]` or any other positional rule.
Five outcomes replace the boolean parse: `RESOLVED`, `UNSPECIFIED` (no
constraint given, or "asap" — forward scan, still works), `UNRESOLVED`
(constraint given but unreadable — ask, never substitute tomorrow), `PAST`,
`BEYOND_HORIZON`. Months stay months (`2026-11-01 → 2026-11-30`) and the
handler walks the range for the earliest real opening instead of collapsing
to one arbitrary day; the scan is bounded at 62 days and skips weekdays the
roster never works. Weekday now comes from `day_label(canonical_date)`
only.

**Booking horizon, separated from requested scope:** `get_booking_config`
advertised `date_horizon_days: 30` and then coerced with `or 14`, so any
clinic storing a blank value silently got 14. Both fallbacks now come from
`DEFAULT_BOOKING_CONFIG` itself (applied to all five numeric keys, since
that's how the two drifted apart), capped by a new `MAX_HORIZON_DAYS = 365`,
and exposed as `booking_horizon_days(clinic)`. The availability layer
enforces it: November past a 30-day horizon returns "This clinic is
scheduling appointments through Thursday, September 17, so November 2026
isn't open for booking yet" — not August slots. Default stays 30; raising it
is now a per-clinic `WidgetSettings` value that actually takes effect.

**Scope invariant at the UI boundary:** the handler puts `scope_start`/
`scope_end` on the SQL block and `ui_meta._slots_in_scope()` drops any row
outside it before mapping chips. Upstream resolution already guarantees the
rows match; the check stays because a mismatched chip is worse than no chip.
`formatter.py` also needed an `authoritative_summary` flag — its
`"No available" in summary` string sniff would otherwise have replaced every
new honest refusal with the generic "couldn't retrieve availability" copy.

**Before → after** (today = 2026-08-18, horizon 30d):

| Question | Before | After |
|---|---|---|
| "…available in November" | silent tomorrow → Aug 19 slots | `beyond_horizon`, Nov 1–30, no chips |
| "…available in December" | silent tomorrow → Aug 19 slots | `beyond_horizon`, Dec 1–31, no chips |
| "…in December 12 morning" | 2023-12-12 "Tuesday" | 2026-12-12 **Saturday** |
| "…in December 15 morning" | 2023-12-15 "Friday" | 2026-12-15 **Tuesday** |
| "…for Monday morning" | 2026-08-24 | 2026-08-24 (unchanged) |
| "anything asap" | silent tomorrow | forward scan to horizon |

**Files:** new `apps/chatbot/temporal.py`; `sql_tool/handlers/doctors.py`,
`booking/config.py`, `ui_meta.py`, `sql_tool/formatter.py`.
**Tests:** new `apps/chatbot/tests/test_temporal_scope.py`, 36 tests
covering all seven transcript phrasings end-to-end through the handler
(asserting the slot payload, not just the prose), the hallucinated-year
cases in both entity orders, month ranges and year rollover, horizon refusal
and clamping, the config fallback, and the required weekday proofs
(Dec 12 2026 → Saturday, Dec 15 2026 → Tuesday).
**Verified:** 447 chatbot+appointments tests, up from a 411/411 baseline
measured on this machine with the same command; eval unchanged **674/682**
(the same 8 pre-existing `adversarial_booking_slang_squeeze` /
`adversarial_medical_slang_pediatric` failures, untouched — no expected
values edited). Confirmed the new tests are real: stashing only the four
production diffs makes **12 of the 36 fail**, all in the handler / horizon /
formatter / UI-invariant groups.
One pre-existing failure, not counted as a pass and not caused here: the
already-documented `ConcurrentBookingTests.test_two_parallel_inserts_only_
one_succeeds` Postgres deadlock. It passed on the first full-suite run and
errored on the second. **It has degraded since it was last recorded** — the
earlier note says ~2/3 pass in isolation; it now fails 3/3 in isolation, and
**3/3 with this phase's four diffs stashed**, so the degradation predates
this work. The test inserts via `Appointment.objects.create()` directly, so
it bypasses the `OperationalError` → 409 handling added to
`BookingService.confirm()` in the prior round and hits the exclusion
constraint raw. Left alone deliberately (out of scope); worth its own pass.

**Deliberately untouched** (each remains its own phase): "Sure"
conversation-state handling, casual squeeze-me-in intent, service-existence
routing, doctor-resolution evidence, booking-picker redesign, RAG behavior.

**Noted, not fixed:** the deferred cross-turn day-of-week memory item above
no longer produces a *wrong* day — an unreadable follow-up now resolves to
`UNSPECIFIED` and scans forward rather than asserting tomorrow — but it
still doesn't remember "Tuesday" from the previous turn. Unchanged in
scope; it's conversation state, not per-message parsing.

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

## ✅ Phase 13 — Temporal authority layer

**Done.** Phase 12 added a canonical `TemporalQuery` but left the LLM as a
*source* of dates rather than a suggestion to be checked. A follow-up audit
against a live transcript found nine defects sharing one root cause: nothing
in the system read the patient's own message for a date.

The rule this phase establishes: **the LLM may interpret, deterministic code
decides.** Three candidate sources, ranked by `TemporalPrecision`
(EXPLICIT_DATE > MONTH > WEEKDAY > RELATIVE > FLEXIBLE) and then by
groundedness — never by entity order:

1. `scan_temporal_expressions()` reads the message. Grounded by construction.
2. `entity_extract` for weekdays/relatives (reused, not re-implemented — it
   holds the "sun damage is not Sunday" collision tiering).
3. NLU entities, believed only where the message backs them component by
   component.

Why this mattered, from the logs: for "16 nov friday" the model emitted
`2023-11-17`, moving the patient's day from the 16th to the 17th so the
weekday would fit a year they never said. For "16 oct friday" it emitted
`2023-10-16` — a Monday. Two appointments were booked on 19 August by
patients who had asked about November and January.

Behaviour now: an explicit date outranks any weekday said with it (a
mismatch records `conflict=True` and is stated in the reply, never silently
moved). "tuesday 25" → Aug 25, "tuesday 1" → Sep 1, "tuesday 2" → AMBIGUOUS,
ask. Unreadable constraints ("coming januray", "13-January-202") return
UNRESOLVED and offer **no** alternative slots — per product decision the
assistant may mention that an earlier opening exists but must not query,
render, or book one until asked. `asap`/unconstrained still forward-scan.

Five invariants, one test class each in `test_temporal_authority.py`:
explicit date wins; no silent substitution; a refusal yields no rows and no
chips; SQL date == stated date == chip date; **booking consumes the same
canonical state**. That last one was live: `_apply_date_time_hint` still ran
its own `parse_natural_date(dates[0])` and seeded the *next Friday* for "16
oct friday" — the wizard disagreeing with the answer just shown.

Also fixed: F0, a latent circular import (`temporal` → `sql_tool.utils` →
package `__init__` → `handlers.doctors` → `temporal`) that survived only
because production imported `sql_tool` first; and the NLU filing "Friday"
and "2" under the `time` entity, which produced "No available slots on
Friday, August 21 **for Friday**".

Two Phase 12 test *fixtures* were corrected, not loosened. Both had messages
that accidentally contradicted what they asserted: one checked "an ungrounded
ISO date is distrusted" using a message containing "december" (now correctly
resolvable from the message), the other expected chips from a
`beyond_horizon` block, which the new hard invariant forbids outright. The
assertions are unchanged.

Deliberately unsupported: bare numeric `12/01` stays UNRESOLVED rather than
guessing US vs. international order. Booking concurrency untouched.

Result: **428/428 relevant tests** (412 chatbot + 16 knowledge), 82 of them
temporal; eval **674/682 (98.8%)**, unchanged from baseline. Two pre-existing
environment failures reproduced in isolation and unrelated to this diff:
`apps.knowledge.tests.test_embedding_warmup` (numpy SIGFPE on this machine)
and `ConcurrentBookingTests.test_two_parallel_inserts_only_one_succeeds`
(DB deadlock; imports nothing this phase changed).

## ✅ Phase 14 — Flexible/past temporal semantics

**Done.** Phase 13's authority layer was kept. Two edge cases from a live
transcript (2026-08-19, session `01a0150b-…`) were classified as UNRESOLVED
when they already had a defined status.

Root cause: `looks_temporal()` treated `_FLEXIBLE` words (`earliest`, `asap`,
`next available`, …) as "a date constraint we failed to read". Combined with
NLU sending `date=null` for "When is dr maya availabel earliest", there was
no candidate, so the resolver asked for a calendar date (and cited January
2027 in the refusal template). Separately, `parse_natural_date` returned
`None` for `yesterday`, and the scanner did not emit it either.

Fix, smallest: strip flexible phrases before the unreadable-constraint check
so they fall through to the existing `UNSPECIFIED` forward-scan; parse
`yesterday` against the resolver's `today` (not the wall clock) and emit it
from the message scanner so status is `PAST`. `today`/`tomorrow` unchanged.
Did not add a new enum value. Did not touch booking drafts, REVIEW, or
follow-up binding.

Result: 428/428 chatbot tests, 16/16 knowledge (warmup/xlsx SIGFPE excluded,
pre-existing), eval 674/682 (98.8%) unchanged.

## ✅ Phase 15 — Booking draft isolation

**Done.** Same 2026-08-19 transcript: after an Adult Cleaning REVIEW draft
for Dr Aris, "book appointment with dr maya instantly" (and variants that
name a different doctor, no service, no slot tap) resumed the leftover
service and the leftover REVIEW slot. A new booking utterance was treated
as a continuation of a commitment this turn never made.

Root cause, two inheritance paths:

1. `BookingService._apply_prefill` already cleared date/slot on
   `changed_doctor`, but did **not** drop `service_id` when this call named
   a doctor and omitted a service. `start()` also never passed `slot_start`
   into `_apply_prefill`, so a leftover REVIEW/DETAILS/OTP step could not
   be distinguished from an explicit chip tap.
2. `ui_meta.build_ui_meta` injected `last_service` on every non-generic
   restart, including "put me on Dr Lin's list" which named only a doctor.

Fix, smallest: `stale_service` (doctor passed, service not, session still
has a service) clears the leftover service; `stale_commitment` (doctor or
service named, no `slot_start` this call, leftover slot or DETAILS/OTP/REVIEW)
clears date/slot/hold and drops back to DATE. `start()` now forwards
`slot_start` so a real tap is not stale. `last_service` is injected only if
this turn named a service, or named neither doctor nor service.

Tests use varied wording, not the transcript line three times: "could you
get me in with Dr Lin right away", "put me down for Maya as soon as you
can", "put me on Dr Lin's list as soon as you can", "book the cleaning we
already discussed". Did not treat `"instantly"` as ASAP. Did not touch
hybrid RAG or NLU `doctor_name` pollution.

## ✅ Phase 16 — Pending-offer uptake

**Done.** Same transcript: after "Would you like me to check other days
for Dr. Maya Lin?", "Sure" / "yes" / "Yep." classified as
`insurance_verification` 0.95 and answered "Search your plan…". `"Yep."`
is not an intent; it takes up whatever offer the previous turn recorded.

Root cause: `pending_clarification` was stored and never bound. NLU
classified the short turn in a vacuum. No `if text.lower() in ["sure",
"yes"]` list was added — that would misfire on "yes, Thursday morning".

Fix: `classify_uptake(message)` is a whole-message speech-act (max 48
chars) → `affirm` / `decline` / `None`. Engine runs it after entity
resolution, before sensors/planner. Affirm + `availability_alternative`
rewrites NLU to `DOCTOR_AVAILABILITY` with the offered `doctor_id` on
`resolved_ids` (not `doctor_name` on entities — that would make
`resolve_doctor_candidates(clinic, "Yep.")` run). Affirm +
`service_followup` pins the service and shows availability, not a forced
booking. Decline is `OFF_TOPIC` with "No problem — what else can I help
you with?". `pending_offer_from_turn` records the offer after compose:
empty searchable `doctor_availability`, or a service-answer
(`services_offered` / `medical_question` / `faq` / `pricing`) that matched
a service.

Tests cover varied patient phrasing on purpose: Yep / Sure / Please do /
Go ahead / sounds good / ok; Not now / No thanks / maybe later / nope;
and non-uptake "yes, Thursday morning if she's free", "is Cigna on the
accepted list here", "what time do you close on Saturdays". Engine tests
mock NLU as `insurance_verification` 0.95 — the live failure mode — so
they prove the binder, not the model.

Result of Phases 15+16 together: **444/444 chatbot tests**, 21/21
knowledge (warmup/xlsx SIGFPE excluded, pre-existing), eval **674/682
(98.8%)** unchanged. Same 8 eval failures as Phase 3/14
(`adversarial_booking_slang_squeeze`, `adversarial_medical_slang_pediatric`).

Found, not fixed (unchanged from the transcript review): hybrid RAG on a
resolved empty availability day; NLU stuffing extra tokens into
`doctor_name` (`"maya yesterday"`, `"maya instantly"`); `"instantly"` is
not an ASAP synonym in the temporal layer.

## ✅ Phase 17 — No hybrid RAG on resolved empty availability

**Done.** Empty `doctor_availability` SQL is a resolved answer ("nothing
open that day"), not a thin miss that clinic documents might fill. Mid-
confidence + `allow_hybrid` / `knowledge_q` still pre-authorized
`fallback_vector_tasks` for *any* SQL-only plan with a catalog, so an
empty Tuesday scan could escalate to RAG and invent openings.

Fix, smallest: skip fallback pre-authorization when `sql_tasks` includes
`availability`. Insurance / services / FAQ empty still may hybrid — those
are the cases documents can actually complete. Did not change
`resolve_plan_after_sql`'s contract or `_sql_found`.

Tests (varied wording): "when's the soonest Maya has a gap on Tuesday",
"any openings with Lin that afternoon", "can she see me Tuesday or is she
booked solid" — no fallback. Contrasts: Cigna accepted-list and
HydraFacial existence still pre-authorize hybrid.

## ✅ Phase 18 — Strip temporal junk from `doctor_name`

**Done.** `_DOCTOR_RE` captures the next two tokens after `Dr.`, so
"dr maya yesterday" / "dr maya instantly" became the name. NLU did the
same. Grounding kept the string because both tokens appear in the message;
SQL `full_name__icontains "maya yesterday"` then missed Maya.

Fix: `clean_doctor_name()` peels temporal/ASAP tokens (and `right away`)
off the value. Used by `_extract_doctors` and `sanitize_entities`. Two-
part names still survive a following day word ("dr maya lin tomorrow" →
"maya lin"). Did not put this in an LLM prompt.

Tests: extract + sanitize on yesterday / instantly / immediately /
right away phrasings, plus "is Dr Hamza free this afternoon" still Hamza.

## ✅ Phase 19 — `instantly` / `immediately` / `right away` as ASAP

**Done.** Same transcript family as "book with Dr Maya instantly". Temporal
already fell through to UNSPECIFIED (no date words), but booking
`is_asap_request` and the urgent-availability signal did not treat those
phrases as "you pick", so the wizard stayed on DATE instead of seeding
today the way `asap` does.

Fix: add the three phrases to `_FLEXIBLE` (temporal), `_ASAP_RE`
(booking seed), and `_URGENT_AVAILABILITY_RE`. Did **not** add them to
`entity_extract` date patterns — that would emit a FLEXIBLE candidate and
rescue an unreadable date (`coming januray instantly` must stay
UNRESOLVED, same as `coming januray earliest`).

## ✅ Phase 20 — Doctor resolution evidence floor

**Done.** "Schedule me with Dr." (no name) fuzzy-matched a real roster
member because `schedule` survived the word filter (`STOPWORDS` +
`{doctor, dr, doc, book}` only) and scored above 0.60 against a surname.

Fix: `_name_evidence_tokens` drops booking/availability verbs and
honorifics; token-fuzzy only runs on what's left. Exact last-name /
full-name substring matches still work ("Schedule me with Dr Thorne",
"could you get me in with Aris this week"). Honorific-only / "book with
a doctor" / "I want to see a doctor please" → `unknown`. This is the
Phase 11 evidence floor, implemented against the confirmed transcript
cause rather than a guessed one.

Result of Phases 17–20: **454/454 chatbot tests**, 21/21 knowledge
(warmup/xlsx SIGFPE excluded, pre-existing), eval **674/682 (98.8%)**
unchanged.

## ✅ Phase 11 — Doctor resolution evidence floor

**Done in Phase 20.** The guessed cause was right: `resolve_doctor_candidates`
left `"schedule"` as a fuzzy token on "Schedule me with Dr." See Phase 20
for the evidence-floor fix and tests.

## ✅ Phase 21 — Code-review pass on Phases 13–20; two new regressions found and fixed

**Done.** Requested scope: verify Phases 13–20 (pasted as an external
report) against actual source rather than the prose, find any additional
bugs, run the real suites, and assess whether the remaining deferred items
are worth pursuing. Every claimed fix in Phases 13–20 was independently
re-derived from the diff and re-run — all correct as documented. Two
regressions were found in the Phase 15/16 code itself, both reachable
through normal chat flow, neither mentioned in the pasted report.

**Bug A — `stale_service` had no step-scoping.** `booking/service.py`'s
Phase 15 fix cleared a session's `service_id` whenever a doctor was named
without a service, with no check on how committed the draft was — unlike
its sibling `stale_commitment`, which correctly gates on
`_SLOT_COMMITTED_STEPS`. Reproduced directly: `start()` with only a
service, then `start()` naming a doctor with no service (an entirely
ordinary SERVICE→DOCTOR progression within one live conversation) wiped
the just-picked service. `ui_meta.py`'s
`if named_service or not named_doctor: booking["service_id"] = ...`
confirms this is reachable through real chat, not just a direct API call.

Fix: `stale_service` now additionally requires `session.slot_start` or
`session.step in cls._SLOT_COMMITTED_STEPS` — the same commitment gate
`stale_commitment` already used. A genuinely stale REVIEW/DETAILS/OTP
draft still gets its service cleared; a same-turn SERVICE→DOCTOR pick does
not. Regression test:
`test_booking_resume.BookingDraftIsolationTests.test_service_picked_moments_ago_survives_an_immediate_doctor_pick`.

**Bug B — `pending_clarification` never expired.** Phase 16's offer-uptake
mechanism recorded `availability_alternative` / `service_followup` offers
but only ever cleared them on an explicit affirm or decline — an unrelated
intervening turn left the offer armed indefinitely. Reproduced directly: an
availability offer for Dr. Maya, then an unrelated "what are your hours"
turn, then a later unrelated "sure" (classified live as
`insurance_verification`, the exact failure Phase 16 exists to catch) still
wrongly bound to the two-turns-stale Dr. Maya offer instead of being judged
on its own NLU classification.

Fix: `engine.py` now clears `pending_clarification` on any turn where it is
present, of type `availability_alternative` or `service_followup`, and was
not itself consumed as an affirm/decline this turn — i.e. it survives
exactly one turn (the reply it was offered for) and no longer. The
longer-lived `type="doctor"` disambiguation use of the same field is
deliberately untouched — different lifecycle, not part of this bug.
Regression test: `test_pending_uptake.PendingUptakeEngineTests.test_stale_offer_expires_after_an_unrelated_turn`.

Both fixes verified independently (before/after reproduction scripts) and
together: **494/494 chatbot+knowledge tests** (492 baseline + 2 new
regression tests), eval **674/682 (98.8%)** unchanged — same 8 pre-existing
failures as Phase 3/14/20.

**Remaining deferred items — assessed, not started:**
- **Phase 9C (honest RAG degraded states)** and **Phase 10
  (service-existence → SQL)** are still open and still well-scoped; no
  reason found this pass to reprioritize or redesign either.
- **Coreference ("book with him")** is real and unfixed. Still correctly
  deferred — it's implicit reference resolution, a different problem from
  the explicit-evidence work in Phase 11/20, and needs its own
  conversation-state design pass rather than a bolt-on.
- **`ThreadPoolExecutor` saturation** is unmeasured under real concurrent
  load. No new evidence this pass either way; still correctly deferred
  rather than fixed opportunistically.
- No architectural alternative surfaced during this review that would
  replace any of these three more cheaply than doing the deferred work
  itself — the existing scoping stands.

## ✅ Phase 22 — Chat card collapse-on-supersede (stacked booking UIs)

**Done, two passes.** Reported symptom: after picking a time from the
"Earliest openings" quick-suggestion card, the "Book Appointment" wizard
appeared *below* it in the transcript instead of replacing it. First pass
(just disabling the old slot buttons) was reported back as insufficient —
user follow-up with screenshots showed a second, worse instance: a
previously-abandoned wizard, shown inactive as a full-size "Booking closed"
card, still sitting on screen with a brand-new wizard stacked below it
after an unrelated insurance question.

Root cause (verified against the real render tree, not assumed): the chat
transcript in `chat-widget.tsx` is a plain `messages` array rendered in
order — nothing ever removes an old message. `activeWizardId` already
computes "only the most recent, non-dismissed, non-completed wizard is
active" correctly (confirmed by reading it — every mint path, client- and
server-side, funnels through it), so only one wizard is ever *interactive*
at a time. The actual bug was purely visual: an inactive wizard still
rendered its full header + step-progress + card frame, just swapping the
inner content for "Booking closed" text — so it still occupied a full
card's worth of screen exactly as if it were live. Same problem, smaller
version, in the standalone `time_slots` quick-suggestion card, which had no
"already used" state at all.

Ruled out via direct reproduction against the real backend (not just
frontend reasoning) rather than assumed: hypothesized that
`meta.booking`/`primary_component` might get re-attached to an *unrelated*
turn (e.g. an insurance question) whenever an abandoned-but-unconfirmed
draft sits in `conversation_context`, auto-reminting a wizard the user
never asked for. Reproduced the exact scenario — `BookingService.start()`
with a slot prefill (mirroring what the wizard's mount does on a slot
click), left unconfirmed, then a mocked `INSURANCE_ACCEPTED` turn through
the real `ChatEngine().process()` — and `meta.booking` came back `None`.
The planner correctly excludes booking meta for unrelated intents; this
hypothesis does not hold, so it was not "fixed." The second wizard in the
report is almost certainly a genuine new "Book Appointment" chip click,
which is correct behavior — the actual bug is that neither it nor the
abandoned first draft collapse visually, which is what this phase fixes.
Checked the "re-fetch on Back" half of the report against the backend too:
`serializers.py::_time_options` runs `_slots_for_day` as a fresh DB query
on every `apply_step` call including `"back"` — the wizard's own internal
time step was already correct.

Fix: `TimeSlotsMessage` now collapses to a one-line "✓ 12:30 PM · Nora
Hassan" receipt the instant a slot is picked, replacing the grid entirely
rather than just disabling its buttons. `BookingWizard` now returns a
compact one-line "Booking closed · <doctor>" summary instead of its full
header/step-progress/body frame whenever `active=false` and the draft
never reached `confirmed` (a genuinely confirmed booking keeps its full
`ConfirmedStep` receipt — that one is a legitimate persistent record, not
a closed draft). No chat-widget.tsx changes needed — `activeWizardId` was
already correctly scoped; only the *rendering* of "not active" needed to
shrink. Net effect: at any moment, the transcript shows a run of one-line
receipts for past picks/attempts and exactly one full-size, live booking
UI — matching "swap content of a single container" without a rewrite of
the transcript architecture.

Found, not fixed (same latent gap, not part of the reported bug):
`doctor-card.tsx` and `service-card.tsx` have the identical "no lock after
select" gap. Not touched this phase to keep the change scoped to what was
reported.

Verified via `tsc --noEmit` (clean on both touched files; the only
reported error is a pre-existing, unrelated one in `insurance-card.tsx`),
by tracing the render/activeWizardId logic directly, and by a real
backend reproduction (`ChatEngine().process()` through the mocked-NLU
pipeline) for the ruled-out auto-remint hypothesis. `eslint` could not run
in this environment (pre-existing Node v16.17 vs. the toolchain's
`structuredClone` requirement — unrelated to this change).

**Environment finding, not a code bug:** the user's running dev server had
been started under Node v16.17.0 (the default on `PATH`; `nvm` has 20.20.2
installed but not selected) against a Next.js version requiring 18.18+.
Under the unsupported version Turbopack kept serving stale compiled output
across the fix without erroring, so the first live retest still showed the
pre-fix behavior despite correct source and a passing `tsc`. Killed and
restarted the dev server under Node 20.20.2 with a clean Turbopack cache
— confirmed working after that. Anyone running this frontend locally
needs `nvm use` (or equivalent) before `npm run dev`.

**Follow-up round, after live retest:** user confirmed the collapse fix
resolved the stacking, then asked for two more changes to the same flow:

1. The collapsed slot receipt (a one-line "✓ 9:00 AM · Nora Hassan" pill)
   was itself redundant — the wizard's own header already states the same
   fact. `TimeSlotsMessage` now returns `null` once a slot is picked
   instead of rendering a receipt, so the transcript shows literally one
   card once the wizard is up.
2. The REVIEW step had no Back button (`step !== "review"` was excluded
   from the footer's Back condition on purpose from the earlier REVIEW-gate
   phase). Removed that exclusion — but doing so surfaced a real backend
   gap first: `apply_step("back")`'s `prev_step()` is purely list-order
   based (`[..., DETAILS, OTP, REVIEW, CONFIRMED]`), so Back from REVIEW
   would always compute OTP as the previous step — even though REVIEW is
   *only* ever reached by skipping OTP entirely (confirmed by grepping
   every `session.step = BookingStep.REVIEW.value` assignment in
   `service.py`: exactly two sites, `_route_to_review_if_authenticated`
   and `submit_details`'s `verification_mode="none"` branch — there is no
   third path where OTP was genuinely completed before reaching REVIEW).
   Fixed `apply_step("back")` to skip past OTP straight to DETAILS
   whenever the session is authenticated or the clinic's
   `verification_mode` is `"none"` — the same two conditions that skip OTP
   going forward, now honored going backward too.

Tests added to `test_booking_auth_skip.py`: `test_back_from_review_skips_
otp_straight_to_details_when_authenticated`, `test_back_from_otp_itself_
still_lands_on_details_when_unauthenticated` (proves the fix doesn't touch
the ordinary back-from-OTP case, which is the only "back" a non-skip
patient ever exercises), and `NoVerificationModeReviewTests::test_back_
from_review_skips_otp_straight_to_details` for the second skip-reason.
Verified: `tsc --noEmit` clean; `test_booking_auth_skip.py` 13/13; full
suite **497/497** chatbot+knowledge (494 + 3 new); eval **674/682 (98.8%)**
unchanged. Still not driven through a live browser session on this side —
flagging per this repo's UI-testing convention; the user is expected to
confirm visually since that's what surfaced the environment issue above.

**Second live-test round, same day:** live retest on the fixed dev server
found two more real issues, both fixed:

1. **Back-from-DETAILS-skip was too narrow.** The first fix only skipped
   OTP going back from REVIEW, landing an authenticated patient on DETAILS
   — but `_route_to_review_if_authenticated` skips *both* DETAILS and OTP
   going forward, so DETAILS was never a real stop for that session either.
   Confirmed live: Back showed a contact-details form asking an
   already-verified patient to re-enter an "email or phone for
   verification" — then picking a time again from the step before it
   skipped straight past DETAILS to REVIEW, proving the DETAILS stop was a
   Back-only dead end. **Important distinction caught before landing
   wrong**: the `verification_mode="none"` skip is a *different* shortcut
   that genuinely shows and submits DETAILS (only OTP is skipped after
   it) — a first pass at this fix conflated the two conditions and would
   have wrongly skipped DETAILS for that case too, discarding a
   genuinely-filled-in form. Split into two independent checks in
   `apply_step("back")`: OTP is skipped for either shortcut,  DETAILS is
   additionally skipped only for the true authenticated-with-patient case
   (`is_authenticated and patient is not None`, matching
   `_route_to_review_if_authenticated`'s own guard exactly). Updated
   `test_back_from_review_skips_details_and_otp_straight_to_time_when_
   authenticated` to assert landing on TIME (not DETAILS) and to close the
   loop — re-picking a time from there must route straight back to REVIEW,
   not resurrect DETAILS.
2. **Duplicate doctor name on the TIME step.** The wizard's shared header
   already shows the doctor's name once a doctor is picked (via
   `state.options.doctor_name`, present in `_time_options`' and
   `_date_options`' payloads) — `TimeStep`'s own body was *also* rendering
   `[doctor_name, date]`, showing the name twice on one screen. Checked
   `DateStep` for the same pattern — clean, its body never reads
   `doctor_name` — so this was isolated to `TimeStep`. Fix: `TimeStep`'s
   subtitle now shows only the date; the header still carries the doctor
   name once.

Verified: `test_booking_auth_skip.py` 13/13 (updated, not just re-passed),
full suite **497/497** unchanged, `tsc --noEmit` clean, dev server
recompiled successfully on both edits. Still pending a live visual
confirmation from the user.

## ✅ Phase 23 — NLU cold-first-message failures

**Reported:** the very first message of a session, sent right after a page
refresh, frequently comes back as the generic "I want to make sure I help
with the right thing — find a doctor, book, hours, or insurance?"
clarification, regardless of what was actually asked. Subsequent messages
in the same session work fine.

**Reproduced directly against the live dev backend** (port 8000, not
guessed): sent real first-messages to brand-new sessions and read
`timings.nlu_ms` / `intent` / `confidence` off the actual response.
`intent="unknown", confidence=0.5` is the exact, hardcoded payload
`classifier.py` returns when the whole provider chain (primary → mini
fallback → secondary) exhausts `NLU_TOTAL_BUDGET_SECONDS` — confirmed this
is genuinely what fires, not a misclassification by a working model.

**Two real causes found, both fixed:**

1. **A fresh `OpenAI` client was constructed on every single `classify()`
   call** (`openai_provider.py`), not just the first one of a session —
   each call built its own `httpx` transport with an empty connection
   pool, paying a TCP+TLS handshake to `api.openai.com` on top of real
   inference time, every time. `get_nlu_provider()` already caches one
   provider instance per worker process, so the client is now cached
   there too (lazy-init in `_get_client()`) and reused for the process's
   lifetime — the way OpenAI's own SDK docs recommend. Confirmed safe:
   `run_with_deadline()` already enforces the real per-call timeout
   independently in a worker thread, so the client's own timeout is just
   a generous outer bound now, not the actual budget.
2. **The timeout ceiling itself was too tight for the real, measured
   latency distribution.** Even after fix #1, direct measurement against
   the live backend showed genuine (would-have-succeeded) primary-provider
   calls landing anywhere from 1.4s to 3.3s in normal conditions — with
   the old 3.5s per-provider / 5.0s total budget (set in Phase 9A off a
   much worse ~9.5s-latency incident), a non-trivial fraction of ordinary,
   correct calls had too little margin and got cut off mid-flight,
   falling through to the clarify fallback. Raised
   `NLU_API_TIMEOUT_SECONDS` 3.5→5.0 and `NLU_TOTAL_BUDGET_SECONDS` 5.0→7.0
   in `.env`, `.env.example`, and `config/settings/base.py`'s defaults (so
   an environment without an explicit override is also protected).

**Also isolated, not fixed (correctly out of scope):** a separate ~5.8-6s
outlier appeared, but only ever on the first request immediately after the
Django dev worker process itself had just restarted (confirmed by
comparing against the same test run on an already-warm, non-just-restarted
worker: 3.3s, not 5.9s) — ordinary Django/Python process cold-start cost,
unrelated to the NLU-specific fixes here, and not representative of a real
deployment where workers don't restart between sessions. Not touched.

**Files:** `apps/chatbot/nlu/openai_provider.py`, `.env`, `.env.example`,
`config/settings/base.py`. `GeminiNLUProvider` was checked for the same
per-call-client anti-pattern — it uses raw `urllib.request` per call with
no persistent-client concept to fix, and is only a secondary/rarely-used
fallback provider, so left alone.

**Verified:** `apps.chatbot.tests` **459/459**, eval **674/682 (98.8%)**
unchanged. Live re-measurement after both fixes: 8 fresh sessions,
**0/8 fallbacks** — including one call that took 5.9s (would have
timed out and failed under the old 3.5s/5.0s ceiling) and completed
correctly under the new 5.0s/7.0s one. This is the single clearest piece
of evidence the fix works: an otherwise-identical slow call that used to
fail now succeeds.

### Phase 23 follow-up — the deliberately-deferred cold-process case, now fixed

Reported live via a real pasted trace: the first chat message sent right
after the Django dev server auto-reloaded (StatReloader restart, triggered
by an unrelated code edit) failed with `OpenAI API timed out after 5.0s`
→ clarify fallback; an immediate retry of the identical message succeeded
in 4.4s. This is exactly the case Phase 23 above isolated and explicitly
left unfixed as "not representative of a real deployment where workers
don't restart between sessions" — true for the *frequency* (dev-only
reload churn vs. a rare prod worker respawn), but the underlying cost is
real either way: whoever sends the first message to a freshly started
worker pays it, dev or prod.

**Measured directly** (`manage.py shell`, fresh process, real configured
OpenAI key — not estimated): a cold `models.list()` call took **5834ms**;
the very next `classify()` call on that now-warm connection took
**3224ms**. The gap (~2.6s) is pure DNS+TCP+TLS+auth handshake cost, and
the cold total (~5.8s) lines up exactly with Phase 23's previously-observed
"5.8-6s outlier." At a 5.0s single-provider budget, a cold call fails;
a warm one comfortably succeeds.

**Fix:** mirrors the exact pattern `apps.knowledge.apps.KnowledgeConfig`
already uses for the embedding model (Phase 9B) — warm the connection at
process startup instead of on the first real request.
- `OpenAINLUProvider.warm_up()` (`openai_provider.py`): fires one free,
  non-billed `models.list()` call through the same cached client
  `classify()` will use, so the pool has a live connection before any
  real user message arrives. Swallows failures — best-effort, never
  raises.
- `warm_up_nlu_provider()` (`nlu/factory.py`): resolves the configured
  provider and calls `warm_up()` if it defines one. Gemini has no
  persistent-client concept (raw `urllib` per call, confirmed in Phase 23)
  and simply doesn't define `warm_up()` — skipped via `getattr`, no
  special-casing needed.
- `ChatbotConfig.ready()` (`apps/chatbot/apps.py`, previously empty) calls
  it, gated by a `should_warm_up_nlu(sys.argv)` skip-list identical in
  intent to `should_warm_up_embeddings` (test/migrate/shell/etc. don't
  serve requests and shouldn't pay for a warm connection; `run_chat_eval`
  is skipped because it's explicitly offline/no-live-LLM-calls per
  CLAUDE.md). Fires on every dev-server reload (that's the point — it's
  exactly when the bug reproduces) and once per real worker process in
  production.

**Files:** `apps/chatbot/nlu/openai_provider.py` (`warm_up`),
`apps/chatbot/nlu/factory.py` (`warm_up_nlu_provider`),
`apps/chatbot/apps.py` (`ready()` + `should_warm_up_nlu`, was empty).

**Tests:** 13 new, `apps/chatbot/tests/test_nlu_warmup.py` — argv skip-list
(mirrors `test_embedding_warmup.py`'s coverage), `warm_up_nlu_provider()`
calls the provider's `warm_up()` when present / no-ops safely when absent
(Gemini) / swallows a construction failure, `OpenAINLUProvider.warm_up()`
no-ops with no API key, hits `models.list()` with a 3s timeout on the
cached client, swallows a network failure, and reuses the exact same
client instance a real `classify()` call would. `apps.chatbot.tests
apps.knowledge.tests` — **630/630**. Eval **674/682 (98.8%)** unchanged
(warm-up never runs under `run_chat_eval`, and doesn't touch
routing/classify logic itself). `manage.py check` clean.

**Known limitations:** no live re-measurement of "8 fresh dev-server
reloads, 0/8 fallbacks" (Phase 23's own gold-standard verification for the
first two fixes) — the shell-based measurement above proves the mechanism
end-to-end (cold vs. warm, same client, real key) but wasn't repeated
across multiple real server restarts. Reasonable given the direct,
quantified proof already in hand, but flagged rather than silently assumed
equivalent.

## ✅ Phase 24 — Booking wizard UI/UX pass

**Reported:** double top margin above the wizard card vs. the earlier
time-slots card; a visible "jerk" and scroll-jump-to-mid-card when the
wizard renders; inconsistent card height step to step; the review step
showing "Step 6 of 6" as literally the first screen an authenticated
patient sees; a general ask for an industry-standard styling/wording pass.

**Root causes, each confirmed by reading the actual render path — none
guessed:**

1. **Double margin.** `MessageRenderer` always wraps its output in
   `<div className="w-full">`, even when the inner component (e.g.
   `TimeSlotsMessage` after Phase 22's collapse-to-null) renders nothing.
   The message list's `gap-4` applies on both sides of every flex child
   regardless of content, so an empty wrapper silently doubles the visual
   gap between the two real messages around it. Fixed: `MessageRenderer`
   now returns `null` outright when there's no body and no context
   actions to show — no DOM node, no gap contribution at all.
2. **Scroll jerk.** `BookingWizard` mounts with a short "Preparing your
   booking…" placeholder, and the message-list auto-scroll fires
   immediately when the wizard message is *added* — before `start()`
   resolves and the card grows to its real height. The scroll settles on
   the short placeholder's height; nothing re-triggers it once the card
   grows, leaving the view stuck mid-card. Fixed: `handleBookingStarted`
   (already wired to the wizard's `onStarted` callback, which fires right
   as the loaded state is set) now re-settles scroll position once the
   browser has painted the loaded content, gated behind the same
   `stickToBottom` check the rest of the auto-scroll logic already
   respects — so a patient who deliberately scrolled up to re-read
   something is never yanked back down.
3. **Inconsistent card height.** The wizard's scrollable body had a max
   height but no minimum, so a short step (Review: an icon and two lines)
   collapsed the whole card while a tall step (Time: a multi-section slot
   grid) stretched it near its ceiling. Added a `min-h-[240px]` floor so
   short steps no longer visibly shrink the card between steps.
4. **"Step 6 of 6" on the first screen.** Root cause was real, not
   cosmetic: `step_index()` counted every step in the mode's abstract
   sequence, including DETAILS and OTP — steps this specific
   authenticated, slot-prefilled session never shows at all (see Phase
   23's sibling fix for the same skip mechanism). Fixed properly, not
   patched: added `details_skipped`/`otp_skipped` fields to
   `BookingSession`, set once at the exact moment each shortcut actually
   fires (`_route_to_review_if_authenticated` sets both;
   `verification_mode="none"` sets only `otp_skipped`, since that path
   genuinely shows and submits DETAILS). `step_index()` now excludes
   skipped steps from the count. As a bonus, this let the `back` action's
   Phase 23 fix collapse down to reading these same two persisted flags
   instead of re-deriving `is_authenticated`/`verification_mode` fresh on
   every "back" click — one source of truth for both consumers, checked
   against real UX research: "the step counter should show only the
   steps that are currently visible to the user, and steps hidden by
   conditions or branching should not be counted from the visible total"
   ([UXPin, progress tracker best practices](https://www.uxpin.com/studio/blog/design-progress-trackers/)).

**Researched, deliberately not changed:** searched current chatbot-UI and
healthcare-chat-color best practice
([Parallel](https://www.parallelhq.com/blog/chatbot-ux-design),
[Webstacks](https://www.webstacks.com/blog/healthcare-website-design))
before touching anything cosmetic. Findings validated more than they
prescribed: "one thing per screen" progressive disclosure and hybrid
button+free-text input are already this wizard's actual architecture, not
a gap. On color specifically: the widget's primary color is already a
per-clinic config value (`configuration.widget.primary_color`), and the
research is explicit that a chat widget should match the *host business's*
own branding, not a single fixed palette — so a global recolor here would
work against the multi-tenant design already in place, not with it.
Deliberately left alone rather than overriding a live, per-clinic brand
setting on a real product.

**Files:** `frontend/src/features/chat/messages/message-renderer.tsx`,
`frontend/src/features/chat/chat-widget.tsx`,
`frontend/src/features/booking/booking-wizard.tsx`,
`apps/chatbot/booking/state.py`, `apps/chatbot/booking/modes.py`,
`apps/chatbot/booking/serializers.py`, `apps/chatbot/booking/service.py`,
`apps/chatbot/tests/test_booking_auth_skip.py` (new
`test_review_progress_excludes_steps_this_session_never_shows`, asserting
the exact `{"current": 4, "total": 4}` this fix produces where it used to
report 6 of 6).

**Verified:** `tsc --noEmit` clean; `test_booking_auth_skip.py` 14/14; full
suite **498/498** chatbot+knowledge (497 + 1 new); eval **674/682 (98.8%)**
unchanged. Not driven through a live browser session on this side, per
this repo's standing UI-testing convention — margin/jerk/sizing fixes are
mechanically well-understood from the render path (empty flex child,
async-load-after-scroll, missing min-height) but should still get a real
visual pass from the user.

**Known remaining nuance, not chased further:** the "4 of 4" fix excludes
DETAILS/OTP from the count, but a slot-prefilled authenticated booking
*also* never shows DOCTOR/DATE/TIME as separate screens (they're
prefilled from the triggering message, same as before) — those aren't
tracked as "skipped" the way DETAILS/OTP now are, so the count is more
accurate than before but not a literal "1 of 1." Chasing full accuracy
here starts touching prefill semantics well beyond the reported bug;
flagging honestly rather than overclaiming precision the fix doesn't have.

## ✅ Phase 25 — Stale server env var + missing small-talk rule coverage

**Reported:** Phase 23's NLU timeout fix appeared not to have taken —
pasted pipeline-debug logs still showed "OpenAI API timed out after 3.5s"
(the pre-fix value) well after that fix shipped. Separately: "how is
everything going on" classified as `intent=faq` and got an oddly formal
clarify reply; user suspected a hardcoded FAQ route.

**Issue 1 — genuinely not the same bug reappearing, a different one:**
confirmed via `ps eww -p <pid>` that the specific `manage.py runserver`
process the user's frontend was hitting had `NLU_API_TIMEOUT_SECONDS=3.5`
baked into its actual OS-level environment — not sourced from `.zshrc` /
`.zprofile` (checked, absent), most likely set once, interactively, in
that terminal's long-lived shell session (alive since the prior Monday)
and inherited by every process it launched since. Real environment
variables take precedence over `.env`-file values in this stack, so
Phase 23's `.env` edit was silently ignored for this one variable — while
`NLU_TOTAL_BUDGET_SECONDS` (never separately exported) *did* pick up the
new 7.0s correctly, which is why the total chain ran ~7s instead of the
old ~5s, but the primary attempt itself stayed capped at the old 3.5s
and still failed on real latency spikes. Fixed by killing that server
process tree and starting a fresh one from a clean shell — confirmed via
`ps eww` on the new PID that `NLU_API_TIMEOUT_SECONDS=5.0` /
`NLU_TOTAL_BUDGET_SECONDS=7.0` are now actually what the live process is
running, not just what `manage.py shell` reports in a separate process.

**Issue 2 — real, not hardcoded, but a genuine gap:** `intent=faq` was a
live GPT-4.1-nano classification, not a hardcoded route — verified this
isn't fabricated by checking `nlu/rules.py`'s existing `_GREETING_EXACT`
set, which already special-cases *many* "how are you" phrasings
("how's it going", "how are things", "how do you do", …) as a free,
~0ms, rule-based `greeting` response, entirely bypassing the LLM. "How is
everything going on" just wasn't in that set or matched by its regex, so
it fell through to a real, several-second LLM call that landed on a
defensible-but-not-great `faq` label for what's plainly small talk.
Extended `_GREETING_EXACT` with the "how's/how is everything (going)
(on)?" family, and fixed a related latent gap while there: the exact-set
lookup never stripped trailing punctuation before matching (regex-based
greeting matches already did, and `_FAREWELL_EXACT` two lines down
already had this exact fix for farewell) — "how's everything going on?"
was failing the new test until this was added too, one line, matching an
already-established convention in the same file rather than inventing a
new one.

**Files:** `apps/chatbot/nlu/rules.py`,
`apps/chatbot/tests/test_nlu.py` (new
`test_how_is_everything_going_is_a_greeting_not_an_llm_round_trip`).

**Verified:** `apps.chatbot.tests` **461/461** (459 + 2 new), eval
**674/682 (98.8%)** unchanged. Live re-test against the restarted server:
"how is everything going on" → `intent=greeting`, 0.31s wall (rule-based,
was previously several seconds through the LLM landing on `faq`); a real
booking/insurance question through the same server still gets genuine LLM
classification and a real answer, confirming the greeting-rule extension
didn't overreach into stealing real questions.

**Process note for future phases:** a settings/`.env` fix is only as good
as the process that's actually running it — verifying via a fresh
`manage.py shell` invocation confirms what a *new* process would compute,
not what an already-running long-lived server process has baked into its
actual environment. Checking `ps eww -p <pid>` against the specific
listening PID is the reliable way to confirm a config change reached a
live server, not just the settings module.

## ✅ Phase 26 — Doctor/service cards collapse-on-select

**Reported:** picking a doctor from a `doctor_cards` list left the whole
card (including the *other*, still-clickable doctors' Select buttons)
sitting above the newly-launched booking wizard — the exact "two UIs
stacked" complaint from Phase 22, now hitting a different card type.

**Not a new bug — the latent gap Phase 22 explicitly flagged and deferred**
("`doctor-card.tsx` and `service-card.tsx` have the identical 'no lock
after select' gap... worth its own small pass if it's ever reported as a
live bug rather than a latent one"). It was, so it got one.

**Fix:** same pattern as `TimeSlotsMessage` — `DoctorCards` and
`ServiceCards` each track whether any card in the list has been picked
and return `null` outright once one has, collapsing the whole list rather
than leaving other options live next to an already-launched wizard.
Checked `CardsMessage` (the generic specialty-list card) for the same
risk first — it's architecturally different: its clicks go through
`onAction("suggested", msg)`, a normal chat round-trip (new user message
→ new assistant response), not an instant client-side wizard mint, so
there's no direct stacking risk the same way. Left alone.

**Files:** `frontend/src/features/chat/messages/doctor-card.tsx`,
`frontend/src/features/chat/messages/service-card.tsx`.

**Verified:** `tsc --noEmit` clean. Not driven through a live browser
session on this side — same standing caveat as the rest of this UI/UX
line of fixes; mechanically identical to the already-confirmed-working
`TimeSlotsMessage` fix from Phase 22, but worth a real visual check.

## ✅ Phase 27 — Complete the email architecture (Resend + remaining templates)

**Requested:** user added a real Resend API key and wanted "the complete
architecture of the emails" — every event that should send an email wired
up: OTP-by-email, password reset, account creation, clinic/demo
confirmations, clinic→us and demo→us internal notifications.

**Audit finding, confirmed by grepping every call site directly (not
assumed):** SaaS-Phase 4 had already built a `NotificationService` method
for every one of these events, and **every one already had a real, wired
caller** — patient OTP by email (`otp_service.py:223`), staff verify,
password reset (2 call sites), clinic invite (2 call sites), application
received, demo request received, the internal demo→us notification, and
all 6 billing lifecycle emails. The "explore which events need emails"
part of the request was already done; nothing was missing on coverage.

What was actually missing: (1) no real email provider — only
`ConsoleEmailProvider`/`SMTPEmailProvider` existed; (2) 7 of 13 email types
were still plain-text f-strings, not using the HTML template system
SaaS-Phase 4 built for billing; (3) no `RESEND_API_KEY` setting. Full plan
in `/Users/apple/.claude/plans/peppy-stirring-grove.md` — asked the user
directly about sender-domain verification status before implementing
(none yet; using Resend's shared `onboarding@resend.dev` test sender,
swappable later via `DEFAULT_FROM_EMAIL` alone, no code change).

**Fix:**
- `ResendEmailProvider` in `apps/notifications/providers.py` — raw HTTP via
  `urllib.request` (no new pip dependency, mirrors `GeminiNLUProvider`'s
  existing "no heavy SDK" precedent in this repo). `get_email_provider()`
  now selects it whenever `RESEND_API_KEY` is set, before the DEBUG/console
  fallback (mirrors `get_sms_provider()`'s existing Twilio-first pattern).
- 7 new HTML templates (`templates/emails/{patient_otp,staff_verify,
  password_reset,clinic_invite,application_received,demo_request_received,
  demo_request_notification}.html`), each extending the existing
  `emails/base.html` + `_cta_button.html` layout billing already used. The
  7 corresponding `NotificationService` methods now call
  `send_templated_email(...)` instead of `send_email(body=f"...")` —
  method signatures and every caller unchanged.
- `RESEND_API_KEY` added to `config/settings/base.py`, `.env`, `.env.example`.
  Also fixed the key's casing in `.env` (`Resend_API_Key` → `RESEND_API_KEY`
  — `env()` lookups are exact-name, so the mismatched case would have
  silently never been read at all) and switched `DEFAULT_FROM_EMAIL` to the
  Resend test sender.

**Real regression found and fixed before it shipped:** this repo has no
separate test-settings module — `manage.py test` loads the same `.env` as
the dev server, so `RESEND_API_KEY` is present during automated test runs
too. The first version of `get_email_provider()`'s "Resend wins when
configured" change made 12 pre-existing tests across
`apps.api.applications`, `apps.api.platform`, `apps.accounts`, and
`apps.billing` start making **real HTTP calls to Resend's API during
`manage.py test`** — those tests exercise real invite/notification code
paths without mocking `NotificationService.send_email`, relying on the old
always-safe console default. Caught by running the full suite before
declaring done, not by assumption. Fixed with the same `argv[1] == "test"`
check `apps.knowledge.apps.should_warm_up_embeddings` already uses in this
exact codebase for the identical reason (don't do real external work under
non-serving management commands) — `get_email_provider()` now never
selects Resend under `manage.py test`, regardless of the key being set.
Added `GetEmailProviderTests.test_resend_is_never_selected_under_the_real_
test_runner` — unpatched, exercising the actual guard every other test in
the suite really depends on, not just the patched-around unit-test version
of the selection logic.

**Also found and fixed in the same pass:** `apps/api/applications/
tests.py::test_internal_notification_sent_when_recipient_configured`
checked the plain-text `body` for a link URL — correct before this phase
(the email was plain text, so the raw URL string lived directly in body),
now wrong, because `strip_tags()` drops an `<a>` tag's `href` along with
the tag itself when deriving the text fallback, so a link's URL only ever
survives into `html_body` now. Fixed the assertion to check the right
field rather than loosening it — same standard as any other test fix in
this repo.

**Files:** `apps/notifications/providers.py`, `apps/notifications/
service.py`, `apps/notifications/tests.py`, `apps/api/applications/
tests.py`, `config/settings/base.py`, `.env`, `.env.example`, 7 new
`templates/emails/*.html` files.

**Verified:** `apps.notifications` 24/24 (new). Full suite —
`apps.notifications apps.billing apps.accounts apps.api
apps.chatbot.tests` — **596/596**. `apps.chatbot.tests apps.knowledge.tests`
**499/499**. Eval **674/682 (98.8%)** unchanged. No live email was sent
during implementation or any test run — every provider-level test mocks
the HTTP call; nothing hit the real Resend API.

**Known limitation, not chased further:** `onboarding@resend.dev` is
Resend's shared test sender — fine for verifying the pipeline works, but
production sending needs the user to verify a real domain in Resend's
dashboard and update `DEFAULT_FROM_EMAIL` (a `.env` change only, already
designed for this).

## ✅ Phase 28 — Bare time-of-day / weekend temporal gaps

**Reported, pulled straight from `logs/chat/`:** "is there any doc
available tonight" / "...in the morning" / "...in the afternoon" all
returned the generic "I couldn't confidently work out which date... refers
to" reply — asking for a full date on a message that plainly names today.
Scanned every saved log for the exact failure string first, not just the
three pasted examples: confirmed these three are live (2026-08-21), and
that older log hits for "yesterday"/"earliest" are stale entries already
fixed by earlier phases (Phase 12-14) — not still-open.

**Two distinct root causes, both in `apps/chatbot/temporal.py`'s
resolution chain, confirmed by tracing `resolve_temporal_query` directly
against the real logged NLU output rather than guessing:**

1. **"tonight" was detected but never resolved.** `_RELATIVE_WORDS`
   (used only to decide "they said *something* temporal" for
   `looks_temporal()`) has always included "tonight" — but nothing in the
   actual parsing chain (`scan_temporal_expressions`, `_parse_entity`,
   `_TODAY_WORDS`) recognized it, so `constraint_detected=True` with zero
   usable candidates always fell through to `TemporalStatus.UNRESOLVED`.
   Exact same shape of bug Phase 14 already fixed once for "yesterday" —
   the code comment for that fix says it explicitly: "a well-extracted
   NLU entity still died as UNRESOLVED."
2. **"morning"/"afternoon" arrived as contaminated NLU date entities.**
   Confirmed directly from the production logs: the live NLU sometimes
   files a bare time-of-day word under `entities.date`
   (`date="morning"`, `date="afternoon"`) instead of only `entities.time`.
   `_parse_entity` had no branch for these words, so they became
   unparseable `raw_entities` — non-empty, so `constraint_detected=True`,
   but nothing resolvable, landing on the same UNRESOLVED reply.

**Fix:** widened `_TODAY_WORDS` in `temporal.py` to include "tonight",
"morning", "afternoon", "evening", "night", "noon" — a bare time-of-day
word with nothing more specific in the same message now means today,
mirroring exactly how "today"/"now"/"same day" already worked. Added
`\btonight\b` to `entity_extract.py`'s `_DATE_PATTERNS` so the
message-level extractor (Source 2 of the resolver) independently produces
"tonight" as a candidate too, not just the entity-contamination path —
matching how `\btoday\b` was already there. Verified the "more explicit
date always wins" invariant this file is built around
(`TemporalPrecision.RELATIVE` sorts after `WEEKDAY`/`MONTH`/
`EXPLICIT_DATE`) protects this correctly: "next tuesday morning" still
resolves to Tuesday, not today.

**Found proactively, not yet reported — same bug class, audited for
directly:** "weekend" was the other `_RELATIVE_WORDS` entry with no
resolution path anywhere, identical shape to the "tonight" gap. Not in any
saved log — found by checking every other word in that list for the same
detected-but-never-resolved pattern, per the explicit ask to find gaps
before they're hit, not just patch what's already been reported. Fixed
with a new `_weekend_bounds(today)` helper (Saturday-Sunday of the coming
weekend, or today's own weekend if today already is Sat/Sun) wired into
both `scan_temporal_expressions` (message-level, mirrors the existing
"yesterday" block exactly) and `_parse_entity` (entity-level — the
scanned/`explicit` fallback there only accepts `EXPLICIT_DATE`/`MONTH`
precision, so a `RELATIVE`-precision weekend range needed its own branch,
not just reuse of the scanner). Handles the Sunday edge case correctly: a
naive "next Saturday" formula would jump a full week ahead when asked on a
Sunday — pinned with a dedicated regression test that it collapses to just
today instead, via the resolver's existing `max(start, today)` clamp.

**Files:** `apps/chatbot/temporal.py`, `apps/chatbot/nlu/entity_extract.py`,
`apps/chatbot/tests/test_temporal_scope.py` (2 new test classes, 10 tests:
`BareTimeOfDayMeansTodayTests`, `WeekendMeansTheUpcomingSaturdaySundayTests`
— covering tonight/morning/afternoon/evening/noon/night, both the
message-only and NLU-entity-contamination paths, the weekday-still-wins
regression guard, the Phase 12/13 misspelled-month guard, and all three
weekend edge cases).

**Verified:** direct reproduction of the exact three logged failures
against `resolve_temporal_query` before and after (before: all three
UNRESOLVED; after: all three RESOLVED to today). `test_temporal_scope
test_temporal_authority test_temporal_lane_binding` **102/102**. Full
suite **509/509** (499 + 10 new). Eval **674/682 (98.8%)** unchanged.
Live end-to-end retest against the running dev server: "tonight" /
"morning" / "afternoon" / "this weekend" all now search correctly instead
of asking for a full date (one transient NLU-provider timeout hit on the
first live "tonight" call — confirmed by its distinct error text and
immediate clean retry that this was ordinary LLM latency variance already
covered by Phase 23/25's timeout-budget fix, not a regression from this
phase).

**Also swept, confirmed clean:** every other `_RELATIVE_WORDS` entry
("week", "month", "same day", "asap"/"soonest"/"earliest"/"next
available") either already resolves correctly or is a bare-unqualified
form unlikely enough in real chat that it wasn't worth adding speculative
handling without evidence. Scanned the *entire* `logs/chat/` directory,
not just this bug's own pattern, for other recurring clarify/fallback
buckets (63 "NLU timeout" hits, 15 "low-confidence clarify" hits, 4
`BEYOND_HORIZON`, 2 `PAST`) — spot-checked the most recent of each and
confirmed they're either already-addressed by Phase 23/25, artifacts of
this session's own live-server testing, or genuinely correct clarify
behavior for actually-ambiguous input, not a hidden gap.

## ✅ Phase 29 — Resend User-Agent (Cloudflare 1010)

**Bug, reproduced live 2026-08-21 before any code change:** `RESEND_API_KEY`
was set, `get_email_provider()` correctly selected `ResendEmailProvider`,
and all 21 `apps.notifications` unit tests passed — but a real send
through that provider returned HTTP 403 with Cloudflare `error code: 1010`.
The API key was valid: GET `/domains` with a custom `User-Agent` returned
200 (no verified domain on the account, as expected), and the same POST
to `https://api.resend.com/emails` returned 200 (`id=ffff5e2b-…`) once a
non-default UA was set. urllib's default `Python-urllib/3.x` is the
signature Cloudflare was banning.

**Fix:** `ResendEmailProvider.send` now sends `User-Agent: Synapse/1.0`
(`_RESEND_USER_AGENT` in `apps/notifications/providers.py`). No other
header or provider-selection change.

**Tests:** `test_send_posts_expected_request_shape` now asserts the UA
header. New `test_send_does_not_use_python_urllib_user_agent` reproduces
the actual failure mode — header must be present (otherwise urllib injects
`Python-urllib/3.x`) and must not start with `Python-urllib`.

**Verified:** `python manage.py test apps.notifications.tests --keepdb`
**22/22**. Live send through the unpatched provider to Resend's
`delivered@resend.dev` sink (the same call that 403'd before this change)
now returns without error, including `NotificationService.send_staff_verify_email`.
Eval not re-run: this is outbound HTTP headers on the email provider, not
routing.

**Not fixed here (same as Phase 27):** `onboarding@resend.dev` is still the
shared test sender; production needs a verified domain + `DEFAULT_FROM_EMAIL`
change. `PLATFORM_NOTIFICATION_EMAIL` still optional/no-op when unset.

## ✅ Phase 30 — Console visibility for email + chat traces

**Bug:** after Resend became the live provider, successful sends no longer
appeared in the runserver terminal — only `ConsoleEmailProvider` printed
`=== EMAIL ===` dumps. Separately, chat pipeline traces (`NEW CHAT REQUEST`)
were off because `DEBUG_CHAT_PIPELINE` defaults False in `base.py` and was
unset in `.env`; Django's default logging also never surfaces `apps.*`
`logger.info` (only `django` / `django.server`).

**Fix:**
- All email providers (`console` / `smtp` / `resend`) call `_log_email_sent`
  after a successful send — From/To/Subject/plain body printed to stdout.
  Failures still only log the error, no fake success dump.
- `config/settings/development.py` defaults `DEBUG_CHAT_PIPELINE=True` and
  adds an `apps` INFO console logger on top of Django's `DEFAULT_LOGGING`.
- `pipeline_debug_enabled()` forces the chat dump off under `manage.py test`
  and `run_chat_eval` so those don't print a trace per case.

**Tests:** `test_successful_send_prints_to_console` /
`test_failed_send_does_not_print_success_dump` on Resend;
`apps.chatbot.tests.test_pipeline_debug` for runserver-on / test-off /
eval-off / explicit-false.

**Verified:** `python manage.py test apps.notifications.tests apps.chatbot.tests.test_pipeline_debug --keepdb` **28/28**. Eval not re-run (logging only).

**Restart `runserver`** after this change — Django settings load at process
start.

## ✅ Phase 29 — Persistent chat history / visitor identity, Step 1: schema

**Requested:** a large new initiative — persistent chat history across
browser restarts, a stable anonymous visitor identity, linking that
identity to a patient by email/phone without recreating the conversation,
and WhatsApp-style frontend UX (infinite scroll, date separators,
scroll-to-latest). Full architecture audit + plan written and approved
first, per the request's own instruction and this repo's established
convention — see `/Users/apple/.claude/plans/peppy-stirring-grove.md` for
the complete 14-section design (industry-pattern grounding, the
cookie-vs-localStorage decision and why, the identity-linking mechanics
including an explicit cross-device privacy boundary, full API/frontend/
test plan). Reviewed by an external pass (pasted back by the user) before
implementation started; several of its corrections were adopted (contact
capture ≠ authentication stated as a hard rule; an explicit "linking never
exposes another browser's history" boundary; `visitor_id` moved to a
header on every endpoint, never a body param; dropped a speculative
14-day auto-close from v1) and one was evaluated and adapted rather than
applied literally (its "derive visitor from server-side session" note
conflicts with the very cookie-vs-localStorage finding that motivated the
plan — no server-side session exists to derive from by design; the
header-everywhere convention above is the actionable form of the same
underlying concern).

**Audit headline finding:** the schema is closer to done than the request
assumed — `ChatSession` and a separate `ChatMessage` (role/content/
metadata/sequence_number) already exist and already write a full per-turn
transcript on every message. The actual gap was narrower: nothing ever
read that transcript back (frontend `messages` state always started
empty), there was no identity above a single browser session, and
`session_token` lived in `sessionStorage` — which is cleared on tab close,
meaning "close the browser, reopen it, chat is still there" could not have
worked even in principle before this phase. Confirmed via direct file
reads, not assumed; see the plan's §1 for the full seven-question audit.

**This phase is Step 1 of the plan's 7-step sequence (§14) only — schema,
not the API/frontend yet**, per the plan's own explicit recommendation to
land each step independently rather than as one large change:

1. **New `ChatVisitor` model** (`apps/chatbot/models.py`) — `clinic` FK,
   `visitor_key` (**globally** unique, not just per-clinic — a deliberate
   choice from the plan's design review: a query that forgets its `clinic=`
   filter then fails closed instead of silently returning another
   tenant's visitor), `patient` FK (nullable, `SET_NULL`), `first_seen_at`/
   `last_seen_at`. No `email`/`phone` columns — `Patient` already owns
   those.
2. **`ChatSession` gains a nullable `visitor` FK** (`SET_NULL`) + a new
   `[visitor, last_active_at]` index (the resume flow's core query: "this
   visitor's most recent conversation").
3. **Real bug found and fixed during design review, not originally in
   scope:** `ChatEngine._save_messages`'s sequence-number generation
   (`apps/chatbot/engine.py`) was a bare read-then-write
   (`last_seq + 1`) with no locking, wrapped in a broad
   `except Exception: logger.exception(...)` that silently swallows the
   resulting `IntegrityError` — two concurrent requests against the same
   session could race, and the second message would vanish with no
   visible error anywhere. Multi-tab resume (this phase's whole point)
   makes this measurably more likely to fire, not less, so it's a real
   prerequisite. Fixed with `transaction.atomic()` +
   `ChatSession.objects.select_for_update()` locking the session row for
   the duration of the read-increment-write. **Verified the fix is real,
   not just plausible**: temporarily reverted it (`git stash`) and
   confirmed the new concurrency test fails without it (2 messages instead
   of 4), then restored it and confirmed the test passes — the same
   discipline as every other fix this session, not just "added a lock and
   assumed it worked."

**Files:** `apps/chatbot/models.py`, `apps/chatbot/engine.py`,
`apps/chatbot/migrations/0004_add_chat_visitor.py` (purely additive —
`CreateModel(ChatVisitor)` + nullable `AddField` + two new indexes, no
data touched, confirmed via `makemigrations --check` finding nothing
further pending), `apps/chatbot/tests/test_message_sequencing.py` (new —
mirrors `apps.appointments.tests.test_overlap_and_slots.
ConcurrentBookingTests`'s established `TransactionTestCase` +
`ThreadPoolExecutor` + `connections.close_all()` pattern exactly),
`apps/chatbot/tests/test_chat_visitor_model.py` (new — global uniqueness,
multi-session-per-visitor, `SET_NULL` survival, patient linking).

**Verified:** new tests 7/7 (2 sequencing + 5 model). Full suite
`apps.chatbot.tests apps.knowledge.tests` **520/520**. `apps.patients
apps.billing` **60/60** (the plan flags `[clinic,patient]`-adjacent
billing analytics as worth re-checking given the new FK). Eval
**674/682 (98.8%)** unchanged. `makemigrations --check` clean.

**Not yet built — the remaining 6 steps of the plan, explicitly deferred
to their own phases, not started:** the resume/pagination/contact API
endpoints, identity-linking wiring into OTP verification, the booking
dedup-bug fix, the frontend localStorage/resume/history-hydration work,
the WhatsApp-style upward-scroll/date-separator/scroll-to-latest UI, and
analytics event hooks. This phase is schema-only, landed and verified in
isolation exactly as the plan's own sequencing calls for.

## ✅ Phase 29 Step 2 — Resume + cursor-pagination API

**Scope, exactly as requested — only two new endpoints, nothing else
touched:** `GET /api/v1/widget/chat/resume` and
`GET /api/v1/widget/chat/sessions/{session_token}/messages`, added to the
existing `apps/api/widget/router.py` alongside `/chat/guest` (not a new
router — this domain already lives here). No frontend, no localStorage, no
contact-capture endpoint, no OTP/identity-linking wiring, no booking dedup
change — all explicitly out of scope per the request and left untouched.

**Inspected first, reused directly rather than inventing a parallel
pattern:** `_resolve_clinic(slug)` (existing, reused as-is for both new
endpoints); `client_ip()` + `check_rate_limit()` (existing, from
`apps/api/auth/deps.py` / `core/ratelimit.py` — the exact
`_X_MAX_PER_IP, _X_IP_WINDOW_S` module-constant + `check_rate_limit(scope,
identifier, limit=, window_seconds=)` style already used in
`apps/api/verification/router.py`/`apps/api/auth/router.py`, mirrored
precisely); `request.headers.get(...)` for the visitor header (matching
the existing `X-Tenant-ID` custom-header convention in
`apps/api/auth/deps.py`); the `TestCase` + `self.client.get(url, params,
headers={...})` testing convention from
`apps/appointments/tests/test_authz_and_timezone.py::
WidgetPatientAuthzTests`.

**Compatibility concern found and flagged before writing any code, per
the request's own instruction:** `_resolve_guest_session()` (the existing
function `/chat/guest` already uses to find-or-create a session) has no
visitor concept at all — a session created by a real chat message today
gets `visitor=NULL`, so `/chat/resume` cannot find it yet. This is
correct and expected for Step 2 (the plan's own §14 always scoped this
step to "tested in isolation with fixture sessions, no frontend
dependency yet") but is a real, necessary follow-up: **something in Step
3 or the start of Step 4 needs to make `/chat/guest` accept/attach a
visitor**, or the resume endpoint will never find a real conversation in
practice. Flagged explicitly below, not silently left for later to
discover the hard way.

**Design decisions worth stating explicitly (matching what the plan
already committed to, implemented precisely):**
- **`/chat/resume` never creates a `ChatSession`.** It may create a
  `ChatVisitor` (cheap, no conversation implied) but only ever *finds* an
  existing session, or reports `has_history=false` — verified with a
  dedicated test (`test_first_time_visitor_does_not_create_a_chat_
  session`) and by resuming the same known visitor 3 times in a row and
  confirming the session count never grows past 1. This was the one thing
  specifically flagged to watch for going in, and it's the actual behavior.
- **`visitor_key` global uniqueness (from Step 1) is what makes the
  find-or-create path safe.** A key that resolves to a *different*
  clinic's visitor is treated identically to an unrecognized key — a
  fresh visitor is minted, never an error, never a silent cross-tenant
  resolution. `ChatVisitor.objects.create()` inside `transaction.atomic()`
  with an `IntegrityError` retry loop handles the astronomically-unlikely
  token-collision case without ever surfacing a 500.
- **Cursor pagination via `sequence_number`, strictly `<` the cursor,
  never offset-based** — the over-fetch-by-one trick
  (`qs.order_by("-sequence_number")[: limit + 1]`, trim to `limit`, then
  reverse to ascending) computes `has_more` without a second `COUNT`
  query. Because the cursor is a strict inequality on an immutable,
  unique-per-session integer, a page's contents can never shift once
  computed — new messages arriving elsewhere in the same session (the
  live tail growing while a reader scrolls up) cannot appear in, or
  disturb, an already-fetched older page. Verified directly with a test
  that inserts a new message *between* two paginated fetches and confirms
  the second (older) page is unaffected.
- **Ownership check on `/chat/sessions/{token}/messages`: additive, not
  regressive.** A session with `visitor` set now requires the header to
  match, or it 404s (same status as "session not found" — never confirms
  a token is real to someone who can't prove ownership). A pre-Step-1
  session with `visitor=NULL` keeps working via `session_token` alone,
  exactly as every other existing endpoint in this app already trusts it
  — new data gets a strictly stronger guarantee, old data isn't broken.

**Files:**
- `apps/api/widget/router.py` — two new endpoints, three new schemas
  (`ChatMessageHistoryOut`, `ChatResumeOut`, `ChatMessagesPageOut`), three
  new helpers (`_find_or_create_visitor`, `_message_page`,
  `_serialize_messages`), new rate-limit constants.
- `apps/api/widget/tests.py` — **new file** (this app had no test file at
  all before this phase). 25 tests across 6 classes: first-time visitor,
  existing-visitor resume, tenant isolation, pagination (boundaries at
  exactly 50/51/100, no-history, clamped limit, invalid cursor, new
  messages arriving mid-pagination), ownership (correct/missing/wrong
  visitor header, unknown session, cross-clinic, legacy no-visitor
  session), rate limiting on both endpoints.

**API examples (live, against the real dev server, not just unit
tests):**
```
GET /api/v1/widget/chat/resume?clinic_slug=fit-me-in-verify-clinic
(no X-Synapse-Visitor-Id header — first-ever visit)
→ 200 {"session_token": null, "visitor_id": "oB0Ca...DRygBw",
       "has_history": false, "messages": [], "has_more": false}

GET /api/v1/widget/chat/resume?clinic_slug=fit-me-in-verify-clinic
X-Synapse-Visitor-Id: oB0Ca...DRygBw   (now linked to a real 2-message session)
→ 200 {"session_token": "XFaNG...CGWI", "visitor_id": "oB0Ca...DRygBw",
       "has_history": true, "has_more": false,
       "messages": [{"role":"user","content":"what are your hours",...},
                     {"role":"assistant","content":"We're open Monday–...",...}]}

GET /api/v1/widget/chat/sessions/XFaNG...CGWI/messages
    ?clinic_slug=fit-me-in-verify-clinic&limit=1
X-Synapse-Visitor-Id: oB0Ca...DRygBw
→ 200 {"messages": [{"content": "We're open Monday–Thursday...", "sequence_number": 2}],
       "has_more": true}

GET /api/v1/widget/chat/sessions/XFaNG...CGWI/messages
    ?clinic_slug=fit-me-in-verify-clinic
X-Synapse-Visitor-Id: wrong-visitor
→ 404  (identical to "session not found" — proves ownership without
        confirming the token's existence to a non-owner)
```
(Resuming required manually attaching the visitor to the session in a
shell, since `/chat/guest` doesn't do that wiring yet — see the
compatibility note above; the resume/pagination mechanics themselves are
fully real, not simulated.)

**Verified:** new tests **25/25**. Full regression —
`apps.chatbot.tests apps.knowledge.tests apps.patients apps.billing
apps.api.widget.tests` — **605/605**. Eval **674/682 (98.8%)** unchanged.
`makemigrations --check` clean (no model changes this step). Migration
from Step 1 applied to the real dev database (not just the test DB —
checked explicitly, matching this repo's own recurring gotcha).

**Affects Step 3 directly:** identity-linking (Step 3) needs
`_resolve_guest_session`/`/chat/guest` to actually attach a `ChatVisitor`
to sessions it creates/finds — otherwise `/chat/resume` stays correct but
practically unused, since nothing will ever populate `ChatSession.visitor`
for a real conversation. Recommend this wiring lands at the start of Step
3 (small, isolated) before the OTP-linking logic itself, since linking
depends on sessions already having a visitor to backfill onto.

## ✅ Phase 29 Step 3 — Visitor wiring + anonymous → identified linking

**Scope, exactly as requested:** fixed the Step 2 compatibility gap
(`_resolve_guest_session` now attaches a `ChatVisitor`), added
`POST /api/v1/widget/chat/contact` (unverified capture only), and wired
anonymous→identified linking into both places that resolve a `Patient`
onto a `ChatSession`. No frontend/localStorage, no infinite scroll/date
separators/scroll-to-latest, no analytics, no retention/deletion system,
no unrelated booking refactor — all left untouched.

**Root cause / key finding, not in the original plan text:** the plan's
§5 named `otp_service.verify_otp` as *the* place a `Patient` gets resolved
onto a `ChatSession`. Reading `apps/chatbot/booking/service.py::confirm()`
in full (as instructed) found a **second, independent** call site doing
the same thing at what was then lines 925-929 — booking's own contact
step can authenticate a session without OTP ever running (`verification_
mode="none"`, or an authenticated-skip re-book). Wiring the linking logic
into only `otp_service.py` would have silently missed every booking-led
identification. Fixed by extracting one shared primitive both call.

**Files:**
- `apps/chatbot/services/visitor_service.py` — **new file.**
  `link_visitor_to_patient(visitor, patient)`: the core primitive — links
  once (no-ops, doesn't reassign, if the visitor already has a different
  or the same patient), then `ChatSession.objects.filter(visitor=visitor)
  .exclude(patient=patient).update(patient=patient)` backfills every
  session the visitor already owns. Never touches `is_authenticated` —
  that's a per-session fact about whether *that* session itself completed
  its own verification, not something a visitor-level backfill should
  claim on a session's behalf (a session that was never itself OTP-
  verified must not retroactively look authenticated just because a
  *different* session for the same visitor was). `link_session_visitor_
  to_patient(session, patient)` — convenience wrapper for the two call
  sites below, which already have a session in hand.
- `apps/chatbot/services/otp_service.py::verify_otp` — one new call,
  right after the existing `session.patient = patient; is_authenticated =
  True` write: `link_session_visitor_to_patient(session, patient)`.
- `apps/chatbot/booking/service.py::confirm()` — two changes:
  (1) **dedup fix**: the inline `Patient.objects.get_or_create(phone=...)`
  / manual email lookup-or-create (this file's own comment already flagged
  it as able to create a duplicate `Patient` for the same person on a
  differently-formatted phone) is now routed through `patient_service.
  get_or_create_by_phone`/`get_or_create_by_email` — the same primitives
  every other identity-resolution path in this app already uses. The
  downstream fallback-fill block (fill blank first/last/email on an
  existing patient) is unchanged and still fires for patients found via
  dedup with missing name info. Dropped the now-unused `Patient` import.
  (2) `link_session_visitor_to_patient(chat_session, patient)` added,
  unconditionally, right after the existing `chat_session.patient =
  patient` block — unconditional (not just inside the `if patient_id is
  None` guard) because the visitor may still need linking even when
  `chat_session` already had a patient from an earlier verification.
- `apps/patients/services/patient_service.py` — added `get_or_create_by_
  email`, mirroring `get_or_create_by_phone` exactly (dedup by email
  first, then create via the phone primitive using `email_placeholder_
  phone` so it also gets `Patient.phone`'s uniqueness for free). Booking's
  email branch and the new contact endpoint both use this instead of each
  doing their own inline version.
- `apps/api/widget/router.py`:
  - `_resolve_guest_session(clinic, session_token, visitor=None)` — new
    `visitor` param. Session-token hit + no visitor on the row → **adopts**
    the visitor (legacy pre-Step-1 sessions get pulled into the visitor
    concept the first time their own browser sends another message).
    Session-token hit + row already has a *different* visitor → never
    reassigned. No usable token, but visitor known → resumes that
    visitor's existing active session instead of forking a new one.
    Neither found → mints a new session with `visitor` attached from the
    start.
  - `guest_chat_message` — now resolves/mints the visitor via the same
    `_find_or_create_visitor` Step 2 already built, before calling
    `_resolve_guest_session`; `visitor_id` added to the response `meta`
    dict alongside the existing `session_token`, so a browser that never
    calls `/chat/resume` first still learns its own visitor id.
  - `POST /chat/contact` — new endpoint. Body `{clinic_slug, email?,
    phone?}`, visitor from the header (422 if missing). Never sets `Patient.
    is_verified`; if the visitor is already linked, the existing link wins
    and no new `Patient` lookup happens at all (a casual, unverified
    submission never reassigns an established identity). Uses `link_
    visitor_to_patient` for the backfill, so behaves identically to the
    OTP/booking paths. Rate-limited (`_CONTACT_MAX_PER_IP=10/600s`).
- `apps/api/widget/tests.py` — 18 new tests: `GuestChatVisitorWiringTests`
  (5: creates+attaches on first message, repeat reuses, returning-visitor-
  no-token resumes instead of forking, legacy adoption, never reassigns an
  owned session), `GuestVisitorConcurrencyTests` (1, `TransactionTestCase`
  + `ThreadPoolExecutor`, mirrors Step 1's pattern), `ChatContactTests`
  (10: email/phone create, dedup-reuse by email/phone, does-not-authenticate,
  backfills prior sessions, skip-creates-nothing, missing-header/missing-
  contact 422s, already-linked-not-reassigned), `CrossVisitorPrivacyTests`
  (1), plus one new rate-limit test.
- `apps/chatbot/tests/test_visitor_patient_linking.py` — **new file**, 11
  tests: `visitor_service` unit tests (links, doesn't reassign, `None`-safe,
  no-visitor-session-safe), OTP-verification linking (links visitor,
  backfills *every* prior session for that visitor while leaving `id`/
  `session_token`/`ChatMessage` rows and the non-verified session's own
  `is_authenticated` untouched, legacy no-visitor sessions unaffected),
  booking-confirm linking + the dedup regression itself (existing patient
  reused by phone, by email; legacy no-visitor session still books).
- `apps/patients/tests.py` — was empty boilerplate; added 3 tests for
  `get_or_create_by_email` (create, case-insensitive reuse, doesn't
  overwrite an existing patient's verification status).

**Privacy boundary — verified, not just asserted:** `CrossVisitorPrivacyTests`
creates two `ChatVisitor`s in different "browsers" both pointing at the
same `Patient`, seeds messages on browser A's session, then confirms
browser B's own header gets `has_history=false` from `/chat/resume` and a
plain 404 from `/chat/sessions/{browser-A-token}/messages` — even knowing
the exact token. This works structurally, not by convention: every query
in this phase (`link_visitor_to_patient`'s backfill, the ownership check
in `chat_messages_page`) filters by the *specific* `ChatVisitor` row, never
by `patient` across visitors — there is still no "all conversations for
this patient" query anywhere in the codebase for a future feature to
accidentally reuse unsafely.

**Verified:** new tests — 18 (`apps/api/widget/tests.py`) + 11
(`test_visitor_patient_linking.py`) + 3 (`apps/patients/tests.py`) = **32,
all passing**. Full regression — `apps.chatbot.tests apps.knowledge.tests
apps.patients apps.billing apps.api.widget.tests` — **637/637** (605 + 32
new). Eval **674/682 (98.8%)**, unchanged (this step touches no NLU/
routing code). `makemigrations --check` clean — no schema change this step.

**Known limitations / found-but-not-fixed:**
- **Two truly-simultaneous cold-start requests (no visitor key at all yet)
  mint two different visitors.** `_find_or_create_visitor` never trusts a
  client-*supplied* key value, only echoes back a previously-issued one
  (a deliberate Step 2 decision — kept unchanged here) — so if a browser's
  very first two requests both omit the header, there's genuinely no
  server-side way to recognize them as the same browser without some
  client-side coordination. `GuestVisitorConcurrencyTests` tests the
  realistic, meaningful race instead (concurrent calls with an *already-
  known* key resolve to the one existing row) — this is a frontend-
  sequencing concern for Step 4 (establish identity via `/chat/resume`
  before the first `/chat/guest` send fires), not a server bug.
- **A parallel, narrower session-level race**: a known visitor with *no*
  active session yet, sending two truly-concurrent first messages, could
  create two `ChatSession` rows (no DB-level uniqueness on `(visitor,
  status=active)`). Not defended against — adding one would mean a new
  partial/conditional `UniqueConstraint` migration, which felt like more
  schema surface than this step's explicit scope asked for. Flagging
  instead of silently fixing or silently ignoring; worth a conscious call
  before Step 4 if the frontend can't rule out double-submit.
- `ChatVisitor.last_seen_at` (added in Step 1) is `auto_now_add=True`, not
  `auto_now=True` — it freezes at creation and never actually updates on
  return visits, which is very likely a Step 1 typo/bug (the field is
  presumably meant to track *last* seen, not just first). Left alone this
  step since nothing built in Steps 2-3 reads or depends on it and fixing
  it would mean an unrequested migration; flagging for a small, isolated
  fix whenever the field is actually first consumed by something.
- General guest-endpoint rate limiting beyond the three endpoints this
  phase has touched (`/chat/guest` itself, `/otp/send`, `/otp/verify`) —
  pre-existing gap, unchanged, already flagged in the plan's §12.

**Recommended next phase:** Step 4 (frontend: localStorage + resume-on-
mount) — per the user's explicit instruction, **do not start without
review of this report first.**

## ✅ Phase 29 Step 3.1 — Correction: resume must be a pure read

Step 3 landed `/chat/resume` reusing Step 2's `_find_or_create_visitor` —
so a bare widget open with **no** visitor header still minted a fresh
`ChatVisitor` (this was Step 2's own deliberate, tested, and at-the-time-
approved design: "opening the widget may create a lightweight `ChatVisitor`
identity, which has no conversation-creation side effect of its own").
Before starting Step 4, the user tightened this: opening the widget must
create **nothing** — not a `ChatVisitor`, not a `ChatSession` — for a
first-time browser. Only sending an actual message does. This is a
deliberate correction to already-shipped Step 2/3 behavior, not a bug fix.

**What changed:**
- `resume_chat` (`apps/api/widget/router.py`) no longer calls `_find_or_
  create_visitor`. It now does a plain `ChatVisitor.objects.filter(clinic=
  clinic, visitor_key=visitor_key).first()` — a pure read. No header, or a
  header that doesn't resolve (garbage value, or another clinic's key —
  same fail-closed behavior as before, just via "resolve nothing" instead
  of "mint a fresh one") all produce the identical response: `visitor_id:
  null, session_token: null, has_history: false`, and **zero rows
  written**.
- `ChatResumeOut.visitor_id` changed from `str` to `str | None` — the
  contract now has a real way to say "there is no identity yet," which it
  didn't before (Step 2/3 always returned *some* key, even a freshly-
  minted throwaway one).
- `_find_or_create_visitor` itself is unchanged and still used exactly
  where it should be: `guest_chat_message` (first real message → creates
  visitor + session together) and `chat_contact` (an explicit POST is a
  deliberate action, not a passive widget-open, so it may still create a
  visitor to link to).
- No schema change, no migration.

**Tests updated (behavior intentionally changed, not loosened — old
assertions directly contradicted the new requirement):**
- `ResumeFirstTimeVisitorTests` — rewritten: asserts `visitor_id is None`
  and zero `ChatVisitor`/`ChatSession` rows exist after a bare open,
  including 3 repeated opens in a row. The garbage-header test now asserts
  nothing is created either (previously asserted a fresh identity was
  minted).
- `ResumeTenantIsolationTests` — clinic B resuming with clinic A's key now
  asserts clinic B gets zero visitors created (previously asserted a
  fresh one was minted for B, just not A's).
- New `ResumePaginationChainTests` (4 tests): resume's own page is bounded
  to 50 even at 120 messages; a 500-message conversation never comes back
  whole from resume; the cursor resume returns chains correctly into
  `/chat/sessions/{token}/messages?before=`; and a full stitch-the-whole-
  conversation-together test at 517 messages (deliberately not a multiple
  of the page size) proving no duplicate and no gap across resume + every
  subsequent page down to message 1.
- New test on `GuestChatVisitorWiringTests`: explicit before/after row-count
  assertion that the first real message — not the widget opening — is what
  creates exactly one `ChatVisitor` and one `ChatSession`.
- All Step 2/3 tests that already covered "known visitor with pre-existing
  rows resumes without sending a message" (`ResumeExistingVisitorTests`)
  needed no changes — they never depended on resume *creating* the
  visitor, only *finding* it, so they were already correct under the new
  contract.

**Verified:** widget suite **49/49** (was 43; +6). Full regression —
`apps.chatbot.tests apps.knowledge.tests apps.patients apps.billing
apps.api.widget.tests` — **643/643**. Eval **674/682 (98.8%)**, unchanged.
`makemigrations --check` clean (no model changes).

**Recommended next phase:** Step 4 (frontend) — per the user's explicit
instruction, do not start without review of this report first.

## ✅ Phase 29 Step 4 — Frontend: resume, WhatsApp-style pagination, date separators

**Two small backend companions landed first, both explicitly anticipated
by the original plan's §4/§8 rather than scope creep discovered mid-step:**
- `ChatMessage.metadata` for assistant turns was always `{}` — the actual
  structured payload (`ui_meta`: doctor/service/insurance cards, booking
  wizard launch params, time slots, ...) was computed and discarded every
  turn, never persisted. Without this, "preserve structured messages on
  reload" was structurally impossible — resumed history could only ever
  render as plain text. `ChatEngine._save_messages` now takes an optional
  `ui_meta` param and stores it as the assistant row's `metadata`; the one
  real call site (`engine.py:574`) passes the same `ui_meta` dict already
  computed for the live response. Existing callers that omit it (this
  file's own concurrency tests) keep working — it defaults to `{}`.
- `/widget/config` never exposed the clinic's IANA timezone at all — date
  separators need it (clinic-local "day", not browser-local) and there was
  nothing to read. Added `timezone: str` to `WidgetConfigOut`, sourced
  from `clinic.timezone` (always populated, has a model default).

**Frontend — the actual Step 4 work, inspected before extending (per the
request's own instruction) rather than building parallel mechanisms:**
- `widget-provider.tsx`: added `visitorId`/`setVisitorId`, localStorage-
  backed per-clinic (`synapse_visitor_id_<slug>`, mirroring the existing
  `sessionToken`/`sessionStorage` pattern exactly but with `localStorage`
  since this is the one identifier meant to survive a browser restart).
  `sessionToken`'s own existing mechanism is untouched — resume re-derives
  it fresh from the visitor id every time rather than needing its own
  cross-restart persistence, so there was nothing to change there.
- `services/index.ts` (`widgetService`): new `resume(clinicSlug,
  visitorId)` and `getMessages(sessionToken, clinicSlug, {before, limit},
  visitorId)`; `sendGuestMessage` now takes a `visitorId` param. All three
  send `X-Synapse-Visitor-Id` as a real header only when a value exists —
  never an empty-string header, matching the backend's own "no header at
  all" vs. "no visitor" equivalence.
- `message-parser.ts`: new `hydrateHistoryMessages(rows)` — deliberately
  **reuses `parseChatResponse`** (wraps each persisted assistant row into
  the same shape a live `ChatMessageResponse` has, `meta` = the row's now-
  persisted `ui_meta`) rather than writing a second parallel mapper, so a
  historical doctor-cards/booking-wizard/time-slots turn renders through
  the exact same `MessageRenderer` path a live one does. User rows reuse
  the existing `userTextMessage`. Only `createdAt` gets overridden with
  the row's real timestamp afterward.
- `chat-chrome.tsx`: new `clinicDayLabel(iso, timeZone)` + `DateSeparator`
  — deliberately distinct from the existing `formatMessageTime` (browser-
  local, meant for one message's own timestamp), grouped by the *clinic's*
  timezone via `lib/timezone.ts`'s existing `isoToClinicParts`. Calendar-
  day arithmetic ("yesterday") is done on already-extracted "YYYY-MM-DD"
  strings via `Date.UTC`, never on a real instant — sidesteps DST entirely
  rather than being subtly wrong twice a year.
- `chat-widget.tsx` — the integration:
  - **Resume fires on widget *open*, not mount, and only when a visitor id
    already exists in localStorage** — a brand-new browser never calls
    `/chat/resume` at all, matching the explicit requirement ("don't hit
    the backend just to be told no"). Guarded by a ref so it fires at most
    once per page load; the effect's dependency on `widgetCtx.visitorId`
    correctly re-fires once `WidgetProvider`'s own mount-time localStorage
    read populates it (avoids a real first-render race where `visitorId`
    is still `null` on the very first paint).
  - Hydrated history replaces `messages` in one shot, `stickToBottom`
    forced true, jumps to bottom without animation (`scrollToBottom(false)`)
    — no visible scroll animation on initial load.
  - Upward pagination: an `IntersectionObserver` on a sentinel div above
    the oldest rendered message (only rendered at all when `has_more` is
    true), `rootMargin: "200px"` so it triggers before the literal top
    edge. `loadOlderMessages` calls the existing cursor-pagination
    endpoint, prepends via `hydrateHistoryMessages`, and updates the
    oldest-cursor ref for the next page.
  - **Scroll-position preservation**: captures `scrollHeight`/`scrollTop`
    right before the prepending `setMessages` call; a `useEffect` after
    the DOM updates adds the height delta back onto `scrollTop`. A
    `isPrependingRef` flag tells the *existing* auto-scroll effect to skip
    entirely for this update (in practice `stickToBottom.current` is
    already `false` whenever a prepend can even fire, since reaching the
    sentinel requires having scrolled away from the bottom — the flag is
    the explicit, testable guarantee rather than an implicit one).
  - **Unread badge on the existing "Latest" button** (`showJumpDown` was
    already there from before this phase) — increments only when a
    message is *appended* (not prepended) while not stuck to bottom;
    resets on `scrollToBottom` (button click) and on the reader manually
    scrolling back down. Noted honestly: this app has no live-push
    channel (request/response only), so in today's architecture this path
    is rarely exercised — implemented correctly for when it is, not
    theater.
  - Date separators inserted via a `renderItems` memo that walks
    `messages` once and interleaves `DateSeparator` entries wherever the
    clinic-local calendar day changes — presentation-only, never touches
    `messages` state or the backend.
  - Booking-wizard replay: **no special-casing needed.** Inspected
    `BookingInlineCard`/`BookingWizard` first — `active` (already existing,
    already used for the live multi-wizard-per-session case) gates the
    component's own `.start()` call, so a hydrated wizard-launch message
    only becomes interactive if it's the single most-recent, non-
    dismissed, non-completed one across the *entire* message array
    (hydrated + live combined) — exactly the same rule live chat already
    used for multiple wizards in one long conversation. Reusing it for
    history replay was a discovery from reading the component, not a new
    mechanism.
  - `sendGuestMessage` now sends `visitorId`; a first-time message's
    response `meta.visitor_id` is what the frontend learns and persists —
    opening the widget itself never invents one.

**Verification — and an explicit limitation, stated per the repo's own
"say so if you can't test the UI" rule:**
- `tsc --noEmit`: clean, zero errors.
- `next build` (this machine's default Node, v16.17.0, is too old for
  Next.js 15 — re-ran under `nvm use 20.20.2`): **succeeds.** Only pre-
  existing warnings in files this phase never touched, plus one pre-
  existing warning already present on a line inside `chat-widget.tsx`
  this phase didn't modify (`patientSessionToken`'s own dependency array
  — confirmed via `git diff` that the flagged line isn't part of this
  diff).
- Dev server smoke test (Node 20): `/embed/[clinicSlug]` renders 200,
  contains the expected chat panel markup, zero server-side render errors
  in the log.
- **Backend verified live, end-to-end, against the real dev database**
  (not just unit tests): `/widget/config` now returns `timezone`; a first
  guest message creates exactly one `ChatVisitor` + one `ChatSession`; a
  second message with the returned token/visitor header reuses both (DB
  query confirmed: 1 visitor, 1 session, 4 messages after 2 turns); the
  assistant row's persisted `metadata` now contains the full `ui_meta`
  dict (`lane`, `actions`, `planner`, `routing`, ...) instead of `{}`;
  `/chat/resume` returns that exact history back correctly hydrated.
- **What was not possible to verify: real interactive browser testing.**
  No browser-automation tool is available in this environment — clicking
  through open→scroll-up→older-page-loads→Latest-button→date-separators-
  visually-correct was not directly exercised, only traced through the
  code and confirmed structurally via the backend round-trip above and a
  clean SSR render. This is a real gap, not a formality — flagging it
  plainly rather than claiming a manual walkthrough that didn't happen.
- Backend regression unaffected by the frontend work (no backend files in
  this phase have logic changes beyond the two additions above): full
  suite **646/646** (643 + the 2 new `_save_messages` metadata tests + 1
  new `WidgetConfigOut.timezone` test). Eval **674/682 (98.8%)**,
  unchanged. `makemigrations --check` clean.

**Also worth flagging plainly:** this session observed the repository
auto-committing after tool-driven edits (17 local commits ahead of
`origin/main` by the end of this step, none created via an explicit `git
commit` call in this conversation) — almost certainly a configured hook in
this environment, not an action taken deliberately here. Nothing was
pushed. Noted for the user's awareness since it materially changes local
repo state.

**Known limitations / found-but-not-fixed:**
- No live interactive browser verification (see above) — recommend a real
  manual pass before treating this as fully done, per this repo's own "UI
  changes need browser verification" rule.
- The two genuine, previously-flagged races from Step 3 (two truly-
  simultaneous cold-start requests minting two visitors; a known visitor
  with no active session yet receiving two truly-concurrent first
  messages) are unchanged by this step — still frontend-sequencing
  concerns, not something this step's scope covered.
- Contact-capture UI (the optional email/phone card) was not part of this
  step's explicit requirements list and was not built.
- Analytics hooks (plan §9) remain deliberately deferred, as explicitly
  requested.

**Recommended next phase:** a real manual browser walkthrough of the
acceptance flow (new browser → open → no network call → send message →
visitor/session created → close/reopen → history resumes → scroll up →
older history loads → Latest button + unread badge → date separators) —
this step's own explicit next ask — before any further chat-history work.

## ✅ Phase 31 — Chat card collapse-on-supersede, extended (verify_identity, appointments, picker cards)

**Reported (with screenshot):** a fully-interactive "Verify your
identity" OTP form and a fully-interactive "No upcoming appointments /
Book a New Appointment" card both stayed on screen, live and re-clickable,
underneath the booking wizard that had already superseded them — even
though the OTP had already succeeded and booking had already moved on.

Same bug class as Phase 22 ("Chat card collapse-on-supersede"), which
fixed `booking_wizard`/`time_slots` and explicitly logged
`doctor-card.tsx`/`service-card.tsx` as having "the identical no-lock-
after-select gap, not touched to keep the change scoped." This phase
closes the gap everywhere it still existed, reusing the exact
`payload.completed` convention Phase 22 established (6 prior usages, all
scoped to `booking_wizard`) rather than inventing a new mechanism.

**Root cause, confirmed by direct reads before writing anything:**
`doctor-card.tsx`/`service-card.tsx`/`time-slots-message.tsx` already
self-collapse via a local `useState("picked")` → `return null`, but only
when *their own* button was clicked — an old card superseded by an
*unrelated* later message never learns about it. `verify-identity.tsx`
and `appointment-card.tsx`'s empty state had no collapse concept at all.
`message-renderer.tsx` never threaded `message.id`/`message.payload`
into either of those two components (`booking_wizard`'s case was the only
one that already did, via `onDismiss={() => onBookingDismiss?.(message.id)}`
— the precedent this phase copies). `chat-widget.tsx`'s `handleAction`
cases for `select_doctor`/`select_slot`/`select_service`/`book_appointment`/
`start_reschedule` all did a bare `setMessages([...prev, bookingWizardMessage(...)])`
with no completed-marking at all, unlike `sendText`'s own response
handler, which already marks prior `booking_wizard` messages completed
when a new one launches.

**Second issue found while investigating, confirmed with the user before
building:** `book_appointment` (from the empty-appointments card)
synthesized the wizard purely client-side, with no backend round-trip at
all, while every *other* "Book Appointment" entry point in this app
already goes through a real message (`runBackendAction`'s
`launch_booking` behavior, `chat-widget.tsx`). Asked the user directly
(two clarifying questions) rather than guessing on an architectural
trade-off: whether *all* booking-launch clicks — including ones carrying
precise structured data (doctor_id, exact slot ISO timestamp, service_id)
— should be re-sent as free text for the backend NLU to re-parse.
Confirmed answer: no — only `book_appointment` (no structured data to
lose) becomes a real message; `select_doctor`/`select_slot`/
`select_service`/`start_reschedule` (exact IDs/timestamps already
resolved) stay local, since converting those would force the NLU to
re-guess values the client already had verbatim — a reliability
regression, not an improvement, and exactly the kind of "downstream
handler re-interpreting the user's already-resolved intent" this
codebase's own architecture rule (CLAUDE.md) warns against.

**Fix:**
- `message-renderer.tsx` now threads `message.id`/`message.payload?.completed`
  into `doctor_cards`, `service_cards`, `appointments`, and `verify_identity`
  (mirroring `booking_wizard`'s existing pattern exactly).
- `verify-identity.tsx` gained a `completed` prop — a compact "✓ Identity
  verified" row replaces the live form once true. (Fixed a real hooks-
  rule violation caught by `next build`'s own lint step during this
  change: the early return for `completed` was first placed *before* the
  component's `useState`/`useEffect` calls, which is a conditional-hooks
  violation — moved below all hook calls, verified clean.)
- `appointment-card.tsx`'s `AppointmentCards` gained `completed`/`messageId`
  props — the empty-state branch renders a compact "You started booking a
  new appointment ↓" line instead of the card+button once true, and now
  passes `messageId` into its `book_appointment` action payload.
- `doctor-card.tsx`, `service-card.tsx`, `time-slots-message.tsx` — each
  now forwards `messageId` into its own `onAction` payload alongside the
  doctor/service/slot data it already sent (their existing local
  self-collapse behavior is unchanged).
- `chat-widget.tsx`: new `markMessageCompleted(messages, messageId)`
  helper (module-level, same style as the existing `runBackendAction`).
  `handleIdentityVerified` gained a `messageId` first parameter and now
  marks that message completed in the same `setMessages` call that
  appends the appointments card — in *both* the success and failure
  branches, since OTP verification itself had already succeeded either
  way. `handleAction`'s `select_doctor`/`select_slot`/`select_service`
  cases now mark the triggering picker message completed alongside
  launching the wizard (still fully local, per the confirmed decision).
  `book_appointment` now branches: if `messageId` is present (the empty-
  card path), it marks that message completed and calls
  `sendText("I would like to book an appointment")` — a real `/chat/guest`
  round-trip, no different from typing it; if not (e.g. `insurance-
  card.tsx`'s post-selection prompt, which carries a real `insurance`
  plan name), the original local-synthesis path is untouched, preserving
  that structured data.

**Files:** `frontend/src/features/chat/messages/verify-identity.tsx`,
`appointment-card.tsx`, `doctor-card.tsx`, `service-card.tsx`,
`time-slots-message.tsx`, `message-renderer.tsx`;
`frontend/src/features/chat/chat-widget.tsx`. No backend changes.

**Verified:** `tsc --noEmit` clean. `next build` under `nvm use 20.20.2`
(this machine's default Node is too old for Next.js, established in
Phase 29 Step 4) — succeeds, zero new warnings (same pre-existing,
unrelated warnings as before this change; confirmed via `git diff` that
none of the flagged lines are part of this diff). The hooks-rule error
above was caught by this same build step and fixed before the build was
considered passing, not after.

**Known limitation, stated plainly:** no browser-automation tool is
available in this environment — the actual click-through (verify → OTP
success → compact confirmation appears while the appointments card shows;
click Book a New Appointment → compact line appears and a real assistant
turn follows) was traced through the code, not clicked through in a real
browser. Flagging this the same way Phase 29 Step 4 did, not silently.

**Recommended next phase:** a real manual browser walkthrough of this
exact flow (OTP verify → appointments empty state → Book a New
Appointment → picker cards → wizard) before treating this as fully done.

**Follow-up, same day, live screenshot:** the first fix only handled
supersession triggered by a *click* (`handleAction`'s cases). Reported
with a screenshot: typing "I want to cancel my appointment" (a normal
message, no click at all) got back a reply whose `meta` bundled an empty
`appointments` card *and* a `booking_wizard` launch in the very same
turn — the wizard rendered correctly, but the appointments card next to
it stayed in its full "No upcoming appointments / Book a New Appointment"
form instead of collapsing, because nothing marks a card completed when
the supersession comes from a normal `sendText` turn rather than a click.
User also confirmed the click path itself was working correctly, isolating
the gap precisely to this one path.

Root cause: `sendText`'s own `launchedWizard` block only ever marked
*prior* `booking_wizard` messages completed — never `appointments`/
`verify_identity`, and never anything arriving in the *same* turn as the
wizard (only `prev`, never `parsed.messages`, was touched).

Fix, `chat-widget.tsx`'s `sendText` response handler: when `launchedWizard`
is true, (1) the `base` map (over `prev`) now also completes any open
`appointments`/`verify_identity` message, not just `booking_wizard`; (2)
a new `incoming` map (over `parsed.messages` itself, added — this list
was previously spread in unmodified) completes any `appointments`/
`verify_identity` message arriving *alongside* the wizard in this exact
reply, so a same-turn-bundled card never renders live even for a single
frame. The wizard message itself is explicitly excluded from both passes
so it's never accidentally marked completed the instant it's created.

**Verified:** `tsc --noEmit` clean, `next build` succeeds, no new
warnings. Same browser-testing limitation as above — traced through the
code (confirmed the wizard's own `booking_wizard` entry is untouched by
either new pass; confirmed `bookingUpdate`'s downstream lookup, which
reads from the same `next` array, is unaffected since it only ever
matches on `booking_wizard` type), not clicked through live.

## ✅ Phase 32 — Staff conversations inbox + real browser verification of persistent chat

**Two things requested together:** (1) a staff-facing "Conversations" page
so a clinic owner, or a super admin who has entered that clinic, can read
patient chat transcripts — a feature that didn't exist at all; (2) actual
browser verification of Phase 29 Steps 4/5 (frontend resume/pagination),
since everything up to this point had only ever been checked via
`tsc`/`next build`/direct backend curl calls — the user's own words: "the
most important test is the real browser flow, not just backend tests."
Researched industry conversation-inbox patterns first (Intercom/Zendesk/
Front-style two-pane list+transcript layout) rather than inventing a
layout from scratch.

**New backend endpoints**, `apps/api/chat/router.py`: `GET /chat/
conversations` (`PaginatedOut[ConversationSummaryOut]`, same `search`/
`limit`/`offset` idiom as `list_patients`) and `GET /chat/conversations/
{session_id}/messages` (cursor-paginated, same shape as the widget's own
history endpoint). Both reuse `clinic_from(request)` — the same tenant
resolution every other staff dashboard endpoint already uses, so a clinic
owner and a super admin who has entered that clinic hit the exact same
code path with no separate permission model needed. Extracted the
cursor-pagination query (`apps/api/widget/router.py`'s old `_message_page`)
into a shared `apps/chatbot/services/message_history.py::paginate_messages`
so the widget and staff endpoints share one implementation instead of two.
New tests: `apps/api/chat/tests_conversations.py`, 16 tests (tenant
isolation, super-admin-before/after-entering, search, pagination
boundaries, ownership 404s, structured-metadata round-trip).

**New frontend page**, `frontend/src/app/dashboard/conversations/page.tsx`
— two-pane inbox (list + transcript), a "Conversations" nav entry added.
Deliberately **reuses `MessageRenderer` in read-only mode** for the
transcript (confirmed safe to call with only `message` — every
interactive callback is optional-chained or gated behind a prop that's
simply not passed) rather than building a second rendering path — a
doctor/service/booking card in a patient's history renders identically to
how the live widget shows it. Per the user's confirmed choice, older
messages load via a plain "Load older messages" button, not the patient
widget's infinite-scroll polish.

**Real browser verification, `frontend/e2e/`** — the first frontend test
infrastructure in this repo (Playwright, committed, `npm run test:e2e`).
This environment's Node (16.17) and Playwright's newest browser builds
don't support this machine's macOS 12 — pinned `@playwright/test@1.48.0`,
the last release train still shipping mac12-compatible Chromium, run
under `nvm use 20.20.2`. Two spec files, 8 tests total, seeding fixtures
directly via `python manage.py shell` rather than mocking anything.

**Three real bugs found and fixed by this browser testing — none of them
were visible to `tsc`, `next build`, or any backend curl call, which is
exactly the gap real browser testing exists to close:**

1. **CORS silently blocked every resume/pagination request.** The
   backend's `CORS_ALLOW_HEADERS` (`config/settings/base.py`) allow-listed
   `x-tenant-id` but never `x-synapse-visitor-id` — added in Step 2 of the
   chat-history work and never revisited. Any cross-origin request
   carrying the visitor header (i.e. every resume call, every pagination
   call, and every guest message after the first) was rejected by the
   browser's own CORS preflight before it ever reached the network tab in
   a meaningful way — invisible to `curl`, which doesn't enforce CORS at
   all. This means **returning-visitor history restore has been
   completely non-functional in this environment this entire time**,
   despite passing 646/646 backend tests. Fixed: added
   `x-synapse-visitor-id` to the allow-list.
2. **The "resuming" skeleton got stuck forever in dev mode.** The resume
   `useEffect` combined a permanent `resumeAttemptedRef` guard ("only ever
   run once") with a per-invocation `cancelled` cleanup flag (the usual
   "don't set state after unmount" hygiene). React's dev-only Strict Mode
   double-invoke (mount → cleanup → remount) set `cancelled = true` from
   the *first* invocation's cleanup before its own `await` resolved, while
   the ref had already blocked the *second* invocation from retrying — the
   one fetch that actually completed then discarded its own result and
   never called `setResuming(false)`. Fixed by removing the `cancelled`
   flag entirely — `resumeAttemptedRef` already guarantees this effect's
   async work starts at most once for the widget's whole lifetime, so
   nothing else was relying on it.
3. **Upward pagination could eagerly fetch every older page on resume,
   without the user ever scrolling** — violating the plan's own explicit
   requirement ("never return the entire conversation on open"). Root
   cause: `el.scrollTo({behavior:"auto"})`'s "instant" jump-to-bottom does
   not update `scrollTop` synchronously — the actual scroll commit can be
   deferred by an unpredictable number of frames, worse under load — so
   the upward-pagination `IntersectionObserver`'s first notification could
   fire while the container was still at its pre-scroll (top) position,
   misreading the sentinel as "the user scrolled up." Fixed with two
   independent guards in the observer callback: a fixed 500ms delay
   before the observer even attaches (lets the scroll commit settle
   first), plus checking `stickToBottom.current` (only ever flips false
   from a real scroll event) instead of trusting the observer's own
   intersection snapshot alone.

**Also found: one test-only bug, not a product bug** — the Latest-button
test used a case-sensitive `/Latest/` regex against the button's own
`aria-label="Jump to latest"` (lowercase), which never matched. The
product code was correct throughout; only the test assertion was wrong.

**Verified:** Playwright suite **8/8, twice consecutively** (confirmed not
a lucky single run). Backend: `apps.chatbot.tests apps.knowledge.tests
apps.patients apps.billing apps.api.widget.tests apps.api.chat.
tests_conversations` — **662/662**. Eval **674/682 (98.8%)**, unchanged.
`tsc --noEmit` and `next build` clean, no new warnings. `makemigrations
--check` clean (no schema changes this phase).

**Found, not fixed:** two isolated test flakes seen once each during
iteration (a composer `.fill()` not registering, a resume assertion
timing out) that did not reproduce on retry or in isolation — logged as
test-infrastructure flakiness, not chased further given they never
reproduced against a fixed input.

**Recommended next phase:** Step 6 (analytics hooks) remains explicitly
deferred per the user's own instruction — chat UX and identity linking
were the priority, analytics comes after. The Conversations page has no
polish pass yet (relative timestamps, empty states) beyond functional
correctness; a design pass would be a reasonable next step if the feature
gets real usage.

## ✅ Phase 33 — Booking confirmation persistence + inert historical UI cards

Triggered by the user's own real-world manual test as a logged-in clinic
admin (found via the widget in **staff mode**, not the anonymous public
embed): booked an appointment, got a live confirmation card ("Ali, we've
got you confirmed... Code 2I4YAP"), then reported three things — (1)
resume didn't restore their prior chat despite the conversation correctly
appearing in the new Phase-32 staff Conversations tab, (2) the booking
confirmation left no trace in chat history, and (3) historical chat
messages have live, clickable UI that could misfire. Per the user's
explicit delegation ("you know better decisions so make the best
decisions") on (2) and (3), designed and implemented both; (1) was
diagnosed and is a scope finding, not a bug in what shipped.

**(1) Resume-not-firing — root cause, not fixed this phase.** Phase 29's
visitor/resume system was wired only into the anonymous public embed path
(`/chat/guest` → `_resolve_guest_session`, `apps/api/widget/router.py`).
Confirmed by direct code reading that neither `_resolve_staff_test_session`
nor `_resolve_session` (`apps/api/chat/router.py`, the staff-dashboard-
widget and patient-JWT paths respectively) ever sets `ChatSession.visitor`.
`GlobalChatWidget` (`frontend/src/components/chat/global-chat-widget.tsx`)
switches to `assistantMode: "staff"` — routing through `/chat/message/
staff` — the instant a logged-in staff/admin user is anywhere in
`/dashboard/*`, which is what the user's own test hit. Verified against
their actual session (`ChatSession` for clinic `apex-dental`: `visitor_id:
None, patient_id: 019fefbc-..., is_authenticated: True`) — consistent with
this code path. Extending resume to the patient-JWT-authenticated flow is
real, separate scope (a patient's *own* identity already exists via the
JWT, so "resume" there might key off `patient_id` directly rather than the
anonymous-visitor mechanism) — not started, needs its own phase.

**(2) Confirmation persistence.** `BookingService.confirm()`
(`apps/chatbot/booking/service.py`) is a separate API call entirely,
outside `ChatEngine.process()`/`_save_messages()` — a confirmed booking
left zero trace in `ChatMessage`. Added `persist_confirmation_message()`
(`apps/chatbot/services/message_history.py`), called from `confirm()`
right after the existing `link_session_visitor_to_patient()` call, reusing
the `confirmation` dict `serialize_step`/`_slot_summary` already compute
(no new data shape invented) and the same `select_for_update()` sequence-
number locking `ChatEngine._save_messages` uses. Frontend: wired the
already-built-but-never-used `ConfirmationCard`/`case "confirmation"`
(`message-renderer.tsx`) up in `message-parser.ts::appendMetaComponents`,
and suppressed the duplicate plain-text bubble when a confirmation card is
also rendering.

**(3) Inert historical UI — risk-scoped, not blanket-disabled.** Reasoned
through which historical cards are genuinely dangerous if clicked from a
stale view versus merely redundant: `booking_wizard` (mounting it live
would call `BookingWizard.start()` against a stale/expired hold, no click
even required — just scrolling it into view) and `appointments` Cancel/
Reschedule (a real, deliberate action against a live appointment,
one-click-away) are real risks; doctor/service/time_slots picker cards and
quick_replies/buttons are not (clicking just starts a new chat turn, no
mutation) and were **deliberately left untouched this pass** — stated
explicitly rather than silently incomplete. Fixed at the single choke
point where persisted history becomes live `ChatMessage[]`
(`hydrateHistoryRow`, `message-parser.ts`): historical `booking_wizard`
messages get `payload.completed = true` (the existing Phase-22 "inert,
already-superseded" convention — full collapse); historical `appointments`
messages get a new `payload.readOnly = true` (distinct from `completed` —
keeps the informational content visible, just strips the Cancel/
Reschedule buttons and the empty-state "Book a New Appointment" button).
`AppointmentCard`/`AppointmentCards` (`appointment-card.tsx`) and
`message-renderer.tsx`'s `case "appointments"` thread the new prop through.

**Files changed:** `apps/chatbot/services/message_history.py` (new
`persist_confirmation_message`), `apps/chatbot/booking/service.py`
(`confirm()` call site), `frontend/src/features/chat/message-parser.ts`
(confirmation rendering, dedup, historical inert-forcing),
`frontend/src/features/chat/messages/message-renderer.tsx` (`readOnly`
threading), `frontend/src/features/chat/messages/appointment-card.tsx`
(`readOnly` prop on both components), `apps/chatbot/tests/
test_booking_auth_skip.py` (new regression test).

**Tests:** new `test_confirm_review_persists_a_confirmation_chat_message`
(`NoVerificationModeReviewTests`) — books, confirms, asserts exactly one
`ChatMessage` carries `metadata["confirmation"]` matching the API response
(confirmation code, doctor name) and that the doctor's name appears in
`content`. Full suite: `apps.chatbot.tests apps.knowledge.tests
apps.patients apps.billing apps.api.widget.tests apps.api.chat.
tests_conversations` — **663/663** (662 baseline + 1 new). `tsc --noEmit`
and `next build` clean. Playwright **8/8** (re-run against a fresh dev
server after clearing a stale/corrupted Turbopack cache from a long-
running session — see below).

**Found, not part of this phase's fix:** the dev server process that had
been running for the entire session (~2h45m) had accumulated a corrupted
Turbopack chunk cache, serving 500s ("Failed to load chunk...") on the
embed route — killed the process and cleared `frontend/.next` to get a
clean Playwright run. Environmental, not a product bug; noted in case it
recurs on other very-long dev sessions.

**Known limitations / found but not fixed:**
- Resume does not cover the staff-widget or patient-JWT chat paths — see
  (1) above. Needs a scoping conversation before implementation: is
  persisting/resuming the staff-QA-widget case even desirable, versus
  patient-JWT resume which clearly is.
- Doctor/service/time_slots picker cards and quick_replies/buttons remain
  live-clickable in historical views — deliberately deferred, see (3).
- Paddle sandbox billing issue reported in the same message ("can't reach
  Paddle... when change or remove the plan") — not yet investigated, no
  reproduction detail gathered yet.

**Recommended next phase:** scope and implement patient-JWT-path resume if
the user wants it; separately, investigate the Paddle sandbox billing
report.

## ✅ Phase 34 — Dev DB cleanup + analytics dashboard donut-chart bug

Triggered by the user's own manual testing of a new (uncommitted,
in-progress) analytics dashboard feature: 92 clinics had accumulated in
the dev DB (mostly orphaned Playwright fixtures — E2E specs seeded unique
timestamped clinics on every run but never tore them down), the
"Appointment status" donut chart wasn't rendering on `/dashboard`, and a
gold badge appeared to be floating over the charts.

**DB cleanup.** Confirmed with the user which 6 clinics were real
(apex-dental, lumina-skin, horizon-family-care, beula-medical-family-
clinic, stackup-technologies, comsats-university-islamabadlahore) before
touching anything, since deletion is irreversible. Deleting `Clinic` rows
directly hit `ProtectedError` — `Appointment.doctor`/`Appointment.patient`
are `on_delete=PROTECT`, which blocks the `Doctor`/`Patient` CASCADE from
completing even though `Doctor.clinic`/`Patient.clinic` are themselves
CASCADE — so `Appointment` rows for the target clinics have to be deleted
first. Deleted 86 clinics (3,305 cascaded rows) and 719 anonymous
(`patient_id IS NULL`) `ChatSession` rows within the 6 kept clinics.
Delegated a background agent to top up each kept clinic to 5-6 doctors,
8-10 patients, 5-6 services plus realistic appointments spanning
7/30/90/180/365-day windows (final counts and the full DoctorSchedule/
Appointment seeding script are in that agent's report, not reproduced
here) — verified counts directly afterward. Also had it add `afterAll`
teardown (reusing each spec's existing `djangoShell`/`execSync` seeding
pattern) to all three Playwright specs so this doesn't reaccumulate; ran
the full E2E suite 3× to confirm teardown holds even on mid-run failure,
and the clinic count returns to exactly 6 every time.

**Donut chart — real bug, root-caused via direct DOM inspection, not
guessed.** `AnalyticsDonutChart` (`bars-donut.tsx`) rendered its legend
text correctly but zero `<path>` elements inside the Recharts `<Pie>` on
`/dashboard`, while the identical component with identical data rendered
correctly on `/dashboard/analytics`. Confirmed via `page.evaluate()`
against the live DOM (not a screenshot) that the SVG had a
`recharts-pie-sector` group with an empty `recharts-shape` child — no
path was ever drawn, and nothing recovers it since there's no further
re-render to force reconciliation once React settles. Root cause:
`/dashboard` fires three independent React Query hooks
(`useAnalyticsOverview`, `useConversations`, `useAppointments`) that
resolve at different times, each triggering a full re-render of
`DashboardHomePage`, each passing a freshly-computed (new-reference)
`statuses` array to `AnalyticsDonutChart` — `/dashboard/analytics` only
has the one overview query, so it doesn't re-render mid-flight the same
way. Recharts' Pie enter-animation apparently gets interrupted by one of
these re-renders and never recovers. Fixed by adding
`isAnimationActive={false}` to every animated Recharts element in the
shared chart library (`bars-donut.tsx`'s Pie and both Bar charts,
`line-area.tsx`'s Line and Area) — verified via the same direct-DOM method
that sectors went from 0 paths to 2 correctly-colored paths. This also
addresses the user's separate "charts render too slowly" complaint, since
charts now paint immediately instead of animating in.

**Corrected an initial misdiagnosis.** The "Conversations & Appointments"
combo line chart on `/dashboard` first appeared blank via a `fullPage:
true` Playwright screenshot. A proper in-viewport screenshot after
scrolling the chart into view showed it had been rendering correctly the
whole time (real multi-series line with real peaks) — the blank appearance
was an artifact of capturing a very long page with `fullPage: true`, not a
product bug. Corrected this explicitly rather than letting a false "fixed
a bug" claim stand; the `isAnimationActive={false}` change to Line/Area
was kept anyway since it's harmless and consistent with the Pie fix, but
no bug was confirmed for it specifically.

**The gold "Fourth Wing" badge — solved, not a bug.** Traced via
`document.elementFromPoint()` + ancestor walk to `GlobalChatWidget`'s
floating launcher button (`fixed ... bottom-5 right-5 z-[60]`, present on
every dashboard page by design) — apex-dental's widget has a custom
avatar image configured that happens to be a gold wax-seal graphic. Not a
rendering defect; the launcher always floats over page content by design,
same as any chat-bubble widget.

**Test-bug fix, not a product bug.** The reseed/teardown background
agent's suite run surfaced a new, consistent (3/3) failure:
`dashboard-analytics.spec.ts`'s date-range-tab assertion expected
`data-state="active"`, which is Radix's convention — this repo uses
`@base-ui/react/tabs` (`src/components/ui/tabs.tsx`), whose `Tab`
component sets a boolean `data-active` attribute instead (confirmed by
reading `node_modules/@base-ui/react/tabs/tab/TabsTabDataAttributes.js`).
Confirmed live via DOM dump that clicking the tab correctly sets
`aria-selected="true"`, `data-active`, and fires the real `?range=7d` API
call — the filter itself was never broken. Fixed the assertion to check
`aria-selected="true"` instead (more implementation-agnostic than pinning
to a specific UI-library data attribute).

**Files changed:** `frontend/src/components/dashboard/charts/bars-donut.tsx`,
`frontend/src/components/dashboard/charts/line-area.tsx`,
`frontend/e2e/dashboard-analytics.spec.ts` (assertion fix),
`frontend/e2e/chat-persistence.spec.ts`, `frontend/e2e/staff-conversations.spec.ts`
(afterAll teardown), `frontend/package.json` (`@playwright/test` re-pinned
to exactly `1.48.0` — a `npm install` between sessions had silently drifted
it past the mac12-compatible pin from Phase 32 via the `^1.48.0` caret
range; re-pinned without the caret so this can't recur).

**Verified:** Playwright **11/11** (all three specs, run 3× for the
teardown check plus once more after the test-assertion fix — consistent).
Backend: `apps.chatbot.tests apps.knowledge.tests apps.patients
apps.billing apps.api.widget.tests apps.api.chat.tests_conversations
apps.api.analytics` — **682/682**. `tsc --noEmit` clean. Clinic count
verified back to exactly 6 after a full E2E run.

**Known limitations / found but not fixed:** the analytics dashboard's
top KPI cards, chart color palette (currently unmodified Tailwind stock
colors — `#7C3AED`/`#16A34A`/`#EF4444`/`#F59E0B`/`#3B82F6` — confirmed via
`colors.ts`), missing axis-unit labels, and missing per-chart filters are
all still open per the user's explicit request for a proper design pass
rather than a quick patch — deliberately not started in this phase.

**Recommended next phase:** the visual redesign (KPI cards matching a
user-supplied reference layout, considered color palette, axis labels,
filters) as its own focused design phase.

## ✅ Phase 35 — Staff-widget session leakage, tenant-switch isolation, conversations-list N+1

Triggered by two things in one message: a bug report ("new chat attaches
to an old chat in the Conversations tab, but the widget shows a blank/new
conversation") and a request for a "world class" DB architecture review of
chat history ahead of an AWS deployment — indexing, pagination, leakage,
scalability.

**Bug — root-caused precisely, not guessed.** `WidgetProvider`
(`frontend/src/providers/widget-provider.tsx`) persists `sessionToken` to
`sessionStorage` under a single clinic-scoped key
(`synapse_widget_session_<slug>`) shared by **both** the real patient-
facing embed widget and the dashboard's own staff/QA widget — because
`DashboardWidgetProvider` mounts it with `mode="clinic"` regardless of
which assistant mode the chat itself ends up running in.
`ChatWidget.sendText`'s staff branch called the same `patientSessionToken()`
/`rememberSessionToken()` used by the real patient flow, so it
transparently reused whatever token a *previous* QA sitting — hours or
days earlier, same browser tab — had left in `sessionStorage`:
`_resolve_staff_test_session` (`apps/api/chat/router.py`) does
`ChatSession.objects.get(clinic=clinic, session_token=session_token)` and
happily reuses whatever it finds. Every new test message kept appending
onto that same, ever-growing `ChatSession` (correctly visible in the
staff Conversations tab), while the widget's own `messages` state is
plain React state that resets to `[]` on every fresh mount — and staff
mode was never wired into the resume/hydrate effect (that's gated to
`resolvedMode === "clinic"` only) — so the UI always looked blank. Two
completely true, individually-correct-looking facts, with no bug in
either one alone; the mismatch was the bug.

**Fix.** Staff-mode's session token now lives in a dedicated in-memory
ref (`staffSessionTokenRef`, `chat-widget.tsx`), never routed through
`widgetCtx.setSessionToken`/`sessionStorage`. `patientSessionToken()`/
`rememberSessionToken()` both branch on `staffMode` so every existing call
site (send, pagination, verify-identity, booking actions) picks up the
right token automatically — no per-call-site changes needed. A fresh page
load now always starts a genuinely fresh QA session, matching what the UI
already showed. Verified directly against the DB, not just the UI: seeded
a stale session token into `sessionStorage` exactly as a leftover QA
sitting would, sent a message through a live browser, and confirmed a
**new** `ChatSession` was created (28→29) while the stale one gained zero
messages.

**Follow-up case the user flagged directly: a super admin who enters a
different clinic mid-session.** Since `ChatWidget` doesn't remount on a
tenant switch, the in-memory ref above would otherwise keep belonging to
whichever clinic was active when it was last set. Added an effect that
tracks the resolved active tenant (`getActiveTenant() || clinic?.slug ||
clinicSlug`, the same resolution `sendText` already used) and calls
`resetChat()` — which now also clears `staffSessionTokenRef` — the moment
it changes. Note for the record: `_resolve_staff_test_session`'s query is
already clinic-scoped, so a stale cross-clinic token could never actually
leak another clinic's messages even before this — this fix removes the
wasted lookup and the UI inconsistency (old clinic's transcript still on
screen against a new clinic's tenant), not a real data leak that existed.

**DB architecture review — what's already solid, verified by reading the
actual schema, not assumed:** `TenantModel`'s UUIDv7 primary keys
(time-ordered, avoids the random-UUID index-bloat problem at scale, with
both a Python default and a `db_default=UuidV7()` for raw SQL paths);
`ChatMessage`'s composite indexes (`session+created_at`,
`clinic+created_at`, `session+message_type`) plus the
`UniqueConstraint(session, sequence_number)`, which doubles as the exact
covering index `paginate_messages`'s `ORDER BY -sequence_number` needs;
`ChatSession`'s indexes matching its real query shapes
(`clinic+status`, `clinic+last_active_at`, `clinic+patient`,
`visitor+last_active_at` for resume); cursor-based (not offset) message
pagination, over-fetching by one row to learn `has_more` without a second
`COUNT` query; correct `CASCADE`/`SET_NULL` choices (messages cascade with
their session; patient/visitor links `SET_NULL` so deleting a patient
record never destroys conversation history, only anonymizes the
linkage); tenant isolation already covered by existing tests
(`test_other_clinics_staff_cannot_read_this_conversation`, etc.) —
re-ran them, still green. `ip_hash` is stored hashed, never a raw IP.

**Found and fixed — real N+1 in `GET /chat/conversations`.**
`_serialize_conversation` ran `messages.order_by("-sequence_number")
.first()` **and** `messages.count()` — two extra queries **per row on the
page**, up to 200 for a 100-row page, neither covered by the endpoint's
existing `select_related("patient", "visitor")`. Replaced both with
correlated subqueries (`Subquery`+`OuterRef`, one for the count, one for
the latest message's content) folded into the single list query. Added
`test_list_does_not_n_plus_one_on_message_count_or_preview`
(`apps/api/chat/tests_conversations.py`), asserting the request costs a
flat 6 queries (4 of them per-request staff-JWT/tenant-resolution
overhead, unrelated to row count) with 8 seeded conversations — proven
via `assertNumQueries`, not inferred.

**Small AWS-readiness addition.** `config/settings/base.py`:
`CONN_HEALTH_CHECKS: True` alongside the existing `CONN_MAX_AGE=60` —
verifies a pooled connection before reuse instead of handing a worker a
dead one, which matters once this runs as multiple long-lived workers
behind RDS (a failover or idle-connection reap becomes a transparent
reconnect instead of a random request failure).

**Files changed:** `frontend/src/features/chat/chat-widget.tsx`
(staff session isolation + tenant-switch reset), `apps/api/chat/router.py`
(N+1 fix), `apps/api/chat/tests_conversations.py` (new regression test),
`config/settings/base.py` (`CONN_HEALTH_CHECKS`).

**Verified:** `apps.api.chat.tests_conversations` — **17/17** (16 baseline
+ 1 new). Combined suite (`apps.chatbot.tests apps.knowledge.tests
apps.patients apps.billing apps.api.widget.tests apps.api.chat.
tests_conversations apps.api.analytics`) — **692/692**. `tsc --noEmit`
clean. Live-browser DB verification of the session fix as described
above.

**Known limitations / found but not fixed — real recommendations for an
actual AWS deployment, not started here:**
- No retention/archival policy for `chat_messages` — an unbounded table
  is fine at today's volume but is the kind of thing worth a TTL/cold-
  storage plan before multi-year production volume, not before then.
- The conversations list itself (`GET /chat/conversations`) still uses
  offset pagination — fine at realistic per-clinic scale (thousands, not
  millions, of conversations per tenant) but would degrade at very high
  offsets; cursor-based would be the "no asterisks" answer if a single
  clinic's conversation count ever gets large enough to matter.
- Connection pooling here is Django-level (`CONN_MAX_AGE`/
  `CONN_HEALTH_CHECKS`) only — an actual AWS deployment with many
  concurrent workers (ECS/Lambda) should sit behind RDS Proxy or PgBouncer
  at the infrastructure layer; that's an AWS setup decision, not a code
  change, and wasn't started here.
- Message `content` is plaintext in the DB (expected — needed for the
  product to function); at-rest encryption is an RDS/AWS-level control.
  Whether field-level encryption is warranted depends on the specific
  compliance posture being targeted — flagging for a decision, not
  assuming an answer.

**Recommended next phase:** none of the above four are urgent; revisit if
volume, compliance requirements, or a specific clinic's conversation count
make one of them load-bearing.

## ✅ Phase 36 — Staff/super-admin chat resume, per-clinic isolation

Triggered by a report that looked at first like the opposite of what it
turned out to be. The user described "refreshing the page loses my
conversation, but the widget still somehow attaches the new one to the
old thread in the Conversations tab." Direct DB verification (three
sessions inspected across a 17-minute window) showed that was **not**
actually happening — Phase 35's fix was working exactly as designed,
creating a genuinely fresh session on every reload. The real, verified
problem was the opposite of the report's framing: nothing ever got
**resumed**. Every fresh widget open threw away a perfectly good,
already-persisted conversation and started over — for staff testing the
bot from the dashboard, and for a super admin doing the same across
whichever clinics they'd entered.

**The design, stated plainly and confirmed with the user before
building:** every person who chats — anonymous visitor, verified patient,
staff/clinic-admin, or super admin — should get *their own* most recent
conversation restored automatically when they open the widget. Anonymous
visitors and verified patients already had this (Phase 29, keyed by a
browser-stored visitor id) — confirmed still working, not touched. Staff
and super-admin had nothing — that's the gap this phase closes, keyed by
the staff JWT's own identity (user + clinic) instead of anything
browser-stored, which sidesteps the whole class of `sessionStorage`
staleness/cross-contamination bug Phase 35 was defensively patching
around.

**Schema change.** `ChatSession` gained `created_by_user` (nullable FK to
`accounts.User`, `SET_NULL`, migration `chatbot.0005`) — set only when
`_resolve_staff_test_session` (`apps/api/chat/router.py`) *creates* a new
QA session, never on reuse. Without this there was no way to answer "whose
QA session is this" at all — a `ChatSession` only ever recorded which
*clinic*, never which *staff member*. New composite index
`(clinic, created_by_user, last_active_at)` backs the resume query
directly, same pattern as the existing `(visitor, last_active_at)` index
for anonymous resume.

**New endpoint**, `GET /chat/message/staff/resume` — pure read (mirrors
the public widget's `/chat/resume` contract exactly: never creates a
`ChatSession`, only sending a real message does). Finds *this* staff
user's most recent QA session in *this* clinic
(`created_by_user=request.auth.user, clinic=clinic_from(request)`),
returns its latest page via the same `paginate_messages` helper
everything else already shares.

**Frontend**, `chat-widget.tsx`: a new resume effect, gated on `staffMode`
and keyed by the resolved active tenant (`getActiveTenant() || clinic?.slug
|| clinicSlug`) — fires once per distinct tenant this component instance
sees (not once ever), so a super admin switching clinics mid-session gets
a fresh resume attempt for the *new* clinic rather than silently skipping
it because some other clinic was already resumed earlier in the tab. Also
fixed a smaller latent bug found while in this code: `VerifyIdentity`'s
`sessionToken` prop had a redundant `|| widgetCtx.sessionToken` fallback
that could leak the real patient-facing token into staff mode's identity
cards — `patientSessionToken()` already handles that fallback correctly
internally, so the extra one was removed.

**Verified, not assumed, at every layer:**
- Direct DB inspection before writing anything, to confirm what was
  actually true (see above — the report's own framing was partly wrong).
- 4 new backend tests (`apps/api/chat/tests_conversations.py`,
  `StaffChatResumeTests`): no prior session → no history, created
  nothing; resumes own session with correct messages; two staff members
  at the same clinic never see each other's session; a super admin
  resumes a *different* session per clinic and switching back finds the
  right one again — all passing.
- Live browser verification via Playwright, not just unit tests: seeded a
  stale scenario, sent a real message, reloaded the actual page, reopened
  the actual widget, confirmed a uniquely-timestamped marker message was
  genuinely visible in the rendered DOM. Same for the super-admin
  cross-clinic case — confirmed clinic B never sees clinic A's marker,
  and switching back to clinic A finds clinic A's own marker, not
  clinic B's. Both promoted from throwaway scripts into a permanent,
  self-seeding, self-tearing-down spec (`frontend/e2e/
  staff-chat-resume.spec.ts`) rather than deleted after use.
- One debugging false alarm worth recording: an early live-verification
  attempt appeared to fail (`toBeVisible` timeout) because the test
  reused the same literal marker text across repeated runs against a
  session that correctly kept accumulating history — Playwright's
  strict-mode locator threw on multiple matches, which a `.catch(() =>
  false)` in the test script silently swallowed as "not found." Diagnosed
  by screenshotting the actual page (the marker was right there) before
  concluding anything was broken, then fixed by using a timestamped
  marker per run — a test-script bug, never a product one.
- Also found and fixed, while re-running the full E2E suite: a
  pre-existing, unrelated test-only bug in `dashboard-analytics.spec.ts`
  (a `getByRole("heading", { name: "Appointments" })` locator became
  ambiguous after the earlier analytics-redesign phase added an
  "Appointments by specialty" panel — fixed with `exact: true`, same for
  "Patients" vs. "Patients by appointment count"). And a smaller version
  of Phase 34's own "E2E fixtures never clean up" leak, self-inflicted by
  this phase's own new spec: `seedSuperAdminTokens` created a super-admin
  `User` row not tied to any single clinic (a super admin isn't a
  `ClinicStaff` row), so deleting the two test clinics in `afterAll`
  didn't cascade it away — added a matching `deleteSuperAdmin` teardown
  call and cleaned up the two that had already leaked into the dev DB.

**Files changed:** `apps/chatbot/models.py` + migration
`0005_chatsession_created_by_user_and_more`, `apps/api/chat/router.py`
(new endpoint, `_resolve_staff_test_session` signature),
`apps/api/chat/schemas.py` (`StaffChatResumeOut`), `apps/api/chat/
tests_conversations.py` (4 new tests), `frontend/src/features/chat/
chat-widget.tsx`, `frontend/src/services/index.ts`, `frontend/src/types/
api.ts`, new `frontend/e2e/staff-chat-resume.spec.ts`, `frontend/e2e/
dashboard-analytics.spec.ts` (unrelated locator fix).

**Verified:** Backend combined suite (`apps.chatbot.tests apps.knowledge.
tests apps.patients apps.billing apps.api.widget.tests apps.api.chat.
tests_conversations apps.api.analytics`) — **696/696**. Playwright, full
suite — **13/13**. `tsc --noEmit` clean. `makemigrations --check` clean.
Dev DB confirmed back to exactly 6 clinics and zero leaked test users
after a full E2E run.

**Known limitations / found but not fixed:** none identified as
out-of-scope this phase — the anonymous-visitor and verified-patient
resume paths were re-confirmed working, not modified.

**Recommended next phase:** none pending from this report. The Paddle
sandbox billing question from earlier in this session (change/remove
plan failing because the seeded test clinics' `paddle_subscription_id`
values were never created via a real Paddle Checkout) is still the one
open item waiting on the user's choice between fixing the seed data or
tightening the error message — see the Paddle investigation earlier in
this session's history.

## ✅ Phase 37 — NLU context blindness + capability-question misroute (real transcript, real trace logs)

Triggered by "the first message always gives a wrong answer or times out" plus
a real, full pasted transcript from `horizon-family-care`. Investigated via
the actual logs before touching anything — this repo already had everything
needed: `logs/chat/*.json` structured pipeline traces (dev-only,
`DEBUG_CHAT_PIPELINE`, safely `False` by default in `base.py`/`production.py`,
confirmed) plus `chat_pipeline_trace`/`OpenAI NLU timing` log lines. Matched
the pasted transcript's timestamps to 16 real trace files and read the exact
internal `degraded_reason`, vector-hit counts, and per-stage timings for
every turn — not reconstructed from the persisted `ChatMessage.metadata`
alone (which doesn't carry `degraded_reason` or vector scores).

**What the real data actually showed — three distinct findings, not one:**

1. **NLU classification alone consistently takes 2.1–4.5 seconds** across
   all 16 real calls (`api_call_ms` — the OpenAI round trip — is ~99% of
   that; local processing is ~0ms). This is the honest answer to "why does
   it feel slow": not a timeout (none of these 16 calls actually hit
   `NLU_TOTAL_BUDGET_SECONDS=7.0`), but a genuinely slow classification step
   eating most of the request budget on every turn, not just the first.
   Correcting the user's own framing here explicitly: this transcript's data
   does not show timeouts firing — it shows slow-but-completing calls,
   which is a different problem with a different fix.
2. **Most of the "I couldn't find clinic-specific information" replies were
   genuine zero-hit vector searches** (`degraded_reason=empty_vector`,
   `hits=0`), not the Phase-9C budget/timeout-masking gap this looked like
   at first glance. Two sub-causes, both real: (a) content-free replies
   ("sure"/"yes"/"no"/bare "Earliest") were independently classified by the
   NLU with unfounded high confidence (0.85–0.95) into an arbitrary topic
   (e.g. "membership") with zero connection to what was actually being
   discussed, guaranteeing a meaningless vector search; (b) genuine
   retrieval-quality sensitivity — "Whihc **doc** treats the fever" (0
   hits) vs. "Whihc **doctor** treats the fever" (1 hit, correct answer),
   same clinic, same knowledge base, one word apart. (b) is a real,
   separate embedding-quality gap, not fixed here — noted below.
3. **Capability/meta questions about the assistant itself** ("What are the
   things you can help me with", "what are the things that you hvae")
   classified as `faq` (0.95 confidence) → routed to vector search against
   *clinic* documents → guaranteed zero hits, because no clinic writes a
   document describing its own chatbot's capabilities. The *first* message
   of the same real session asked essentially the same thing and got
   classified `off_topic` instead, which already has the correct canned
   "here's what I can help with" reply on the `direct`/template lane — the
   right answer already existed, the classifier just didn't reach it
   consistently.

**Fixes, both in `apps/chatbot/nlu/prompts.py` (the single source-of-truth
NLU prompt file per `ARCHITECTURE.md` §13), both extending the existing,
deliberate "Small LLM produces semantics" design rather than bypassing it
with a hardcoded rule:**

1. **Bounded recent-turn context, added to the NLU call itself** — the
   thing explicitly requested, and the thing the real evidence most directly
   supports. `apps/chatbot/engine.py`'s `process()` now calls the
   already-existing `self._load_history(session, limit=6)` (previously only
   used for the *Large* LLM's synthesis step, `_generate_response`) and
   threads it into the NLU's `conversation_context` as `recent_turns`.
   `build_user_prompt` (`nlu/prompts.py`) renders it as a compact
   `Recent:\nU: ...\nA: ...` plain-text block — deliberately never JSON
   (cheaper in tokens, and nothing shaped like state to copy fields out of)
   — each line truncated to 90 chars, and explicitly excluded from the
   generic `Ctx:` JSON dump so it isn't double-encoded. The system prompt
   gained one explicit, bounded instruction: use recent turns only to
   resolve what a short/bare current message is responding to; never let
   them supply or override an entity the current message doesn't itself
   state; prefer low confidence over guessing when even the immediately
   preceding turn doesn't make the target clear. This mirrors this file's
   own prior lesson, left as a comment already in the code before this
   phase: full booking-draft JSON was once added to this same context and
   had to be removed because the classifier started copying stale dates out
   of it — the fix here is scoped narrowly (plain conversational text,
   explicit "don't override" instruction, 3-exchange cap) specifically to
   avoid repeating that mistake. Deliberately does **not** touch or
   duplicate `conversation_state.py`'s existing `pending_clarification`/
   `classify_uptake` mechanism (ARCHITECTURE.md §10) — that remains the
   precise, code-owned path for offers the engine explicitly recorded; this
   is the fallback for everything else, letting the model itself reason
   about context instead of adding more hardcoded state-tracking.
2. **One explicit routing rule**: "what can you do/help with" style
   questions about the assistant's own scope → `off_topic`, not `faq`.

**Verified, not assumed — and reported honestly where evidence was mixed:**
manual live re-testing of the exact failing turns showed real improvement in
some cases but also one apparent regression on an unrelated query
(`"where are you doctor placed"` dropped from 0.85→0.40 confidence in one
run). Given LLM prompt changes are probabilistic, not deterministic, a
handful of manual spot-checks against a `temperature=0.1` model is not
sufficient evidence either way — this is exactly the situation
`run_chat_eval`'s 682-case offline battery exists for. Ran it:
**674/682 (98.8%) — identical to the last recorded baseline**, same two
pre-existing adversarial failures (`adversarial_booking_slang_squeeze`,
`adversarial_medical_slang_pediatric`, both already-known gaps, unrelated to
this change), zero new failures. That single manual "regression" is far
more likely ordinary sampling variance than something this change caused.
Full suite: `apps.chatbot.tests apps.knowledge.tests` — **540/540** (535
baseline + 5 new). New tests: `apps/chatbot/tests/test_prompts.py` — 5
cases covering the plain-text (never JSON) rendering, truncation, malformed-
entry handling, exclusion from the generic `Ctx:` dump, and that both new
system-prompt rules are actually present in the shipped prompt text.

**Research grounding, per explicit request** — read Anthropic's own current
context-engineering guidance rather than relying on priors alone: the
"right altitude" principle (concrete, bounded heuristics — not brittle
keyword rules, not vague guidance) directly shaped the "resolve short
replies against the immediately preceding turn, never override current-
message entities" instruction; "curate the minimal set of information that
fully outlines expected behavior" directly shaped the plain-text/truncated/
6-message-cap rendering over a fuller transcript dump. General OpenAI-
ecosystem guidance on structured-output latency (minimize schema/output
size) is noted for the next phase below but not acted on here — this
phase's own measurement shows the ~99% latency cost is the raw OpenAI API
round trip itself, not prompt construction or local processing, so schema
trimming is a real but smaller lever than it looked before measuring.

**Found, not fixed — real, separate items for their own phase, not bundled
in here:**
- **Raw NLU API latency (2.1–4.5s per call)** is not something a prompt
  change fixes — it's the OpenAI round trip itself. Worth its own
  investigation: is this normal for `gpt-4.1-nano` at this prompt size in
  this environment, or is something (network path, account tier, time of
  day) making it slower than it should be? A real before/after would need
  a controlled comparison this session didn't have time to run.
  `Recent:` adds real tokens to every call (measured: ~780–900 input tokens
  now vs. ~680–860 before across the reproductions above) — input-token
  cost is usually cheap relative to output generation, but this wasn't
  independently isolated from the raw-latency question above.
- **Embedding-quality gap**: "doc" vs. "doctor" changing whether the same
  relevant chunk clears the similarity threshold. Query normalization/
  expansion or a lower `CHAT_VECTOR_MIN_SCORE` are both real options, each
  with real tradeoffs (false positives vs. false negatives) — needs its own
  investigation, not a reflexive threshold change.
- **The capability-question rule is a prompt hint, not a guarantee** — it
  measurably helped in the eval battery but did not reliably fire in every
  manual retry of the exact phrasing from the real transcript. LLM prompt
  rules are probabilistic; if this specific miss recurs, the next lever is
  a `fast`-tier regex rule (the always-active tier per ARCHITECTURE.md §3,
  the same mechanism already used for a near-identical past bug — "hope me
  in"/"slip me in" reaching the LLM) rather than continuing to strengthen
  prose instructions.
- Phase 9C (Honest RAG degraded states, `⏳` in this file) remains a real,
  separate, unfixed gap — this phase's real trace evidence just happened
  not to catch it in the flesh for this specific transcript, since the
  actual `degraded_reason`s here were genuine empty-vector, not budget/
  timeout masking. Still open.

**Files changed:** `apps/chatbot/nlu/prompts.py` (system prompt rules,
`recent_turns` rendering), `apps/chatbot/engine.py` (`_load_history` wired
into `nlu_ctx`), `apps/chatbot/tests/test_prompts.py` (5 new tests).

**Recommended next phase:** measure raw NLU API latency in isolation
(same prompt, repeated calls, no other variables) to determine whether
2–4.5s is this environment's normal or a fixable anomaly; Phase 9C; the
embedding-quality gap, if it recurs.

## ✅ Phase 38 — Booking-confirmation context resolver + doctor-name-match safety

Triggered by an external architectural review (against a real transcript)
identifying that short confirmations and doctor-name references were
falling into RAG despite the system having already resolved what they
meant. Reviewed, reproduced each claim directly, and fixed the two P0
items; two P1 routing gaps the same review flagged turned out to already
self-resolve once the P0 fixes landed. This deliberately does **not**
resolve the "Deferred — Conversation state / coreference" item just above
in git history (kept, now placed after this entry) — that one is *implicit*
pronoun reference to a doctor mentioned earlier in an ordinary answer
("book with him" after "Dr. Chloe Bennett specializes in..."), a genuinely
different problem from this phase's *explicit offer confirmation*
("yes i want her" after the assistant itself offered a specific slot).
Still open, not touched here.

### Root cause

**P0 — booking-slot confirmation.** This codebase already had the right
architecture for this — `conversation_state.py`'s `pending_clarification`/
`classify_uptake`/`apply_pending_uptake`, which binds a short reply to
whatever the *previous* turn actually offered, is exactly the "Context
Resolver before the Planner" the review asked for, just under different
names. The gap was narrower than "missing architecture": `pending_offer_
from_turn` (the function that decides "what did this turn just offer")
only recognized the *empty-day* availability case ("no slots that day,
want me to check another day?"). A **found**, specific slot — "Earliest
opening: Dr Priya Chandrasekaran at 12 PM," the single most common
confirmation moment in the whole system — was never recorded as a pending
offer at all. So a following "yes i want her" had nothing to attach to,
fell through to being independently classified by the NLU from zero
context (reproduced directly: real model output was `intent=faq,
confidence=0.95`), and reached vector search, which correctly found
nothing for a message with no real semantic content — the "I couldn't
find clinic-specific information" reply was accurate to what RAG was
asked, the bug was being asked at all.

A second, independent gap sat one layer down even after fixing the first:
`apply_pending_uptake` correctly rewrites `nlu.intent` to `BOOK_APPOINTMENT`,
but `planner.py`'s `is_booking_intent` **re-derives its own answer from the
raw message text** (`is_transactional_booking`/`is_booking_commit`),
ignoring that the intent was already resolved. "book it" happened to work
even before this second fix purely because it contains the literal word
"book"; "yes i want her" and "yes sure" contain no transactional-booking
language at all and fell through to `clarify` despite carrying the
correctly-resolved intent — direct, reproducible proof the gap was in the
text-based re-derivation, not in the context resolver itself.

**P0 — doctor-name-match safety.** `_fuzzy_score`'s substring branch
(`nlu/resolvers.py`) scored *any* prefix/substring relationship at a flat
0.92 — including "priya" being a strict prefix of the longer, different,
equally real name "priyanka." 0.92 clears `resolve_doctor_candidates`'s
`HIGH_CONFIDENCE=0.85` band, so `engine.py`'s existing, already-correct
`doctor_resolution`/`did_you_mean_doctor_reply` mechanism (used
unconditionally, for any message that plausibly names a doctor —
independent of final intent) silently treated it as a certain match
instead of a "did you mean" case it was already built to handle.

**P1 items that turned out to already be effects of the P0 fixes, not
separate bugs:** "what about dr priyanka" and "what is the full name of Dr
Priyanka?" both started correctly surfacing "Did you mean Dr. Priya
Chandrasekaran?" the moment the `_fuzzy_score` fix landed, via the *same*
pre-existing `doctor_resolution` mechanism above — no separate change
needed. "Can you find me a doctor for my fever" and "what is the full
name of Dr X" needed one more thing: an explicit NLU prompt rule (symptom-
driven doctor search and structured doctor-fact questions were
classifying as `medical_question`/`faq` instead of `doctor_search`,
sending both to a dead-end vector search over clinic documents that don't
describe doctors).

### Architectural changes

Deliberately **not** a new "Context Resolver" layer — the review's own
explicit instruction was "make the smallest clean architectural change,"
and a second, parallel resolver would have duplicated a system that was
already right, just incomplete. Extended what exists instead:

1. `pending_offer_from_turn` (`conversation_state.py`) gained a third
   offer type, `slot_confirmation`, for a *found* availability slot —
   parallel in shape to the two existing types (`availability_alternative`,
   `service_followup`), added to the same short-lived-expiry set in
   `engine.py` so an unrelated intervening turn correctly clears it (the
   review's own explicit "context contamination" requirement).
2. `apply_pending_uptake` gained the matching `slot_confirmation` case —
   rewrites intent to `BOOK_APPOINTMENT` with the offered doctor resolved,
   tags `raw["_pending_type"]` for the planner to trust downstream.
3. `classify_uptake`'s affirm matcher gained a second, narrow regex
   (`_AFFIRM_REFERENCE_RE`) for a *fixed, small* vocabulary of confirmation-
   plus-pronoun/generic-reference phrasing ("yes i want her/him/it/them",
   "yes sure/please/okay", "book it/her/him/them", "that/this one/doctor")
   — deliberately not "yes + anything," preserving the pre-existing "yes,
   Thursday morning is new information, not uptake" boundary exactly (a
   named *different* doctor or a specific day still fails to match, by
   design, verified by test).
4. `planner.py`'s `is_booking_intent` now also accepts
   `nlu.raw.get("_pending_type") == "slot_confirmation"` as an alternative
   to the text-based `is_transactional_booking`/`is_booking_commit`
   checks — trusting a resolution the context layer already made instead
   of re-deriving it from text that a confirmation reply was never going
   to look like in the first place.
5. `_fuzzy_score`'s substring branch (`nlu/resolvers.py`) now scales by
   how much of the longer string the match actually accounts for
   (`0.55 + 0.35 * shorter_len/longer_len`) instead of a flat 0.92 —
   "priya"/"priyanka" (5/8 chars) now lands at 0.77, `resolve_doctor_
   candidates`'s "medium"/clarify band, not "high"/silent-resolve.
   Verified this doesn't touch the common "just say the first name" case
   (that's exact-token equality, a separate branch, unaffected) or the
   documented typo-tolerance case ("rjet"→"rajat", 0.6, a different —
   Levenshtein — branch, also unaffected).
6. One new NLU prompt rule (`nlu/prompts.py`): symptom-driven doctor
   search and structured "about a named doctor" questions → `doctor_search`,
   not `medical_question`/`faq` — the doctor catalog answers these, not
   clinic documents.
7. `STOPWORDS` (`routing/signals.py`, shared more broadly than just this
   fix) gained "the"/"is"/"of"/"are"/"was"/"were" — found while verifying
   the doctor-safety fix: `_name_evidence_tokens` wasn't filtering these,
   so "what is the full name of dr priyanka" fed "the" and "name" in as
   spurious name-evidence tokens alongside "priyanka," surfacing an
   unrelated doctor as a weak "other close match."

**Considered and explicitly rejected**: raising `_match_doctor`'s (a
*different*, cruder resolver feeding `resolved_ids.doctor_id` for
structured SQL filtering) accept threshold to require high confidence,
plus adding a duplicate "did you mean" fallback inside `search_doctors`
directly. Implemented first, then reverted after reproducing the result —
it worked, but produced a confusing *second*, redundant "did you mean" /
"no doctors found" message stacked on top of the response the
pre-existing `engine.py` mechanism (item 5 above) already produces
correctly on its own. Smallest-change discipline meant keeping the one
fix that actually was the root cause and discarding the second, unneeded
one — left here as an explicit note since the temptation to keep "extra
safety" code that isn't actually load-bearing is exactly the kind of
unnecessary-rewrite the review asked to avoid.

### Files changed

`apps/chatbot/conversation_state.py` (slot_confirmation offer type +
uptake case, `_AFFIRM_REFERENCE_RE`), `apps/chatbot/engine.py`
(slot_confirmation added to the short-lived-expiry set), `apps/chatbot/
planner.py` (`is_booking_intent` trusts a resolved pending uptake),
`apps/chatbot/nlu/resolvers.py` (`_fuzzy_score` substring scaling),
`apps/chatbot/nlu/prompts.py` (doctor_search routing rule),
`apps/chatbot/routing/signals.py` (`STOPWORDS` additions), `apps/chatbot/
tests/test_conversation_state.py` (6 new tests), `apps/chatbot/tests/
test_pending_uptake.py` (4 new tests).

### Tests / results

All 8 of the review's own requested test phrases, reproduced directly
against the live engine end-to-end, not just unit-tested in isolation:
"yes i want her" / "yes sure" / "book it" → correctly launch booking with
Dr. Priya resolved; "that doctor" → reasonable doctor_search repeat (no
pending offer existed to confirm, since a plain search-results list isn't
an offer); "Can you find me a doctor for my fever" → `doctor_search` with
a real doctor list, no RAG; "what about dr priyanka" → "Did you mean Dr.
Priya Chandrasekaran?", never a silent substitution; "what is the full
name of Dr Priyanka?" → `doctor_search`, same honest clarify; a genuinely
unrelated message ("what are your clinic hours") after a real booking
offer → answered normally, offer correctly expired, no contamination.

10 new backend tests (6 in `test_conversation_state.py` covering
`pending_offer_from_turn`'s new branch, `classify_uptake`'s new pattern
*and* its preserved "new information" boundary, `apply_pending_uptake`'s
new case, and the planner fix directly via `compute_message_sensors`; 4
in `test_pending_uptake.py`, engine-level with NLU mocked to the exact
live failure mode, matching that file's existing methodology). Full
suite: `apps.chatbot.tests apps.knowledge.tests` — **550/550** (540
baseline + 10 new). Eval: **674/682 (98.8%)** — identical to the last
recorded baseline, same two pre-existing adversarial gaps, zero new
failures, run twice (once after the doctor-safety fix alone, once after
the complete change set) to isolate which change any regression would
have belonged to had one appeared.

### Remaining edge cases (stated plainly, not fixed here)

- **"that doctor" without a specific slot offered** doesn't resolve to a
  specific doctor from the prior search-results list — it's treated as a
  fresh doctor_search (reasonable, not broken, but not "resolves the
  reference" either). Plain search results were deliberately not treated
  as an "offer" (they're information, not a question awaiting a yes/no) —
  resolving *this* case is the general coreference problem the pre-
  existing "Deferred — Conversation state / coreference" entry above is
  about, not something folded into this phase.
- **Booking a confirmed slot still asks for the time again** — `yes i
  want her` correctly launches the booking flow with the right doctor
  pre-filled, but the *specific* offered slot (date/time) isn't
  carried into it — `ui_meta.py`'s booking-prefill dict has no slot/time
  field yet, only doctor/specialty/service/insurance. A real, scoped
  follow-up, not attempted here to keep this phase to the confirmation-
  routing bug specifically.
- **`did_you_mean_doctor_reply`'s "other close matches"** can still
  surface a weak, borderline-relevant second candidate (observed:
  "James Whitaker" alongside "Priya" for a "priyanka" query, before the
  STOPWORDS fix reduced but did not entirely eliminate this) — cosmetic,
  not a safety issue (the *primary* suggestion is correct and it's still
  phrased as a question), not chased further.
- The doctor-safety fix (`_fuzzy_score`) was verified against the specific
  cases surfaced this phase (priya/priyanka, sara/sarah, rjet/rajat, jo/
  joanna, mike/michael) plus the full eval battery — not exhaustively
  fuzzed against every possible name pair a real clinic roster could
  contain.

## ✅ Phase 39 — Server-side working context (conversation memory)

Triggered by a second real transcript, worse in kind than Phase 38's:
"Based on what we already discussed, who did you recommend?" got a
confident, specific, **invented** answer ("I recommended Dr. Omar
Haddad... Monday, August 28, at 8:00 AM") — a recommendation that never
happened; the real prior turn for that fever question had actually
returned an unrelated doctor-name-verification refusal. Reproduced
directly against real `logs/chat/*.json` trace files (not guessed): the
Large LLM's own `### Recent conversation` context for that call showed
exactly this fabricated exchange, meaning the hallucination was already
baked into what it was given to work with, from a `_load_history(limit=2)`
window too thin to ground an honest answer. Scoped and implemented from
an external architectural review's plan (validated independently against
the same trace files before writing any code — its diagnosis of
`ConversationTimeline`'s unused fields matched exactly).

**Root cause, precisely, not just "no memory":** `ConversationTimeline`
(`conversation_state.py`) already had `insurance`/`doctor`/
`availability_target` slots — they were mostly *never written*.
`engine.py` never called `merge_turn_context(..., insurance=...)`;
`build_planner_facts` carried zero timeline fields at all, so the planner
had no way to consult session memory even where it existed. The one thing
that *was* available to compensate — Phase 37's `recent_turns` — is
deliberately bounded and forbidden from supplying entities the current
message doesn't state (correct, load-bearing, and exactly why it can't
also serve as a memory mechanism: a recall question is *itself* the
current message, so that rule doesn't block the LLM from "helpfully"
inventing content to answer it with).

**Architectural decision — validated, not just followed:** do not put a
fuller transcript into the Small LLM (Phase 37 already measured that
tradeoff); do not store working context client-side (this clinic's own
`ChatSession.conversation_context` is already server-side, tenant-scoped,
and resume-safe — a client-owned store would fork staff/patient/embed and
fight Phase 35's session isolation); do expand the one existing
`ConversationTimeline` and have Python write to it and read from it,
never a second LLM call. This was checked against a real competitor
example (a property-leasing chatbot's own browser localStorage dump) the
user asked about directly: useful as a *product* clue (it persists a
structured booking draft and last-FAQ-subject slots, the same shape of
idea), not as an architecture to copy — it stores full transcript *and*
PII (name/email/phone) in client-side localStorage, which this system
deliberately does not do.

**What was added, all in `conversation_state.py` unless noted:**

- `ConversationTimeline` gained five fields: `shown_doctors` (ordered,
  capped at 6, **overwritten** each turn a doctor list is actually shown
  — never an accumulating log), `last_recommendation` (`{id, name,
  reason}`; `reason="listed"` when SQL returned a list vs. an actual
  single-doctor recommendation — the composed reply says "I listed" or "I
  recommended" accordingly, never blurs the two), `last_slots` (capped at
  8, from real `doctor_availability` SQL rows), `problem` (this-turn
  `entities.symptom`), `preview_only` (per-turn, not sticky).
- `classify_session_recall(message)` → `insurance`/`recommendation`/
  `topic`/`time`/`None`, a `direct_mode="session_recall"` short-circuit in
  `build_execution_plan` (same pattern as the existing emergency/
  medical-advice-refusal overrides) that stops before vector/SQL/the
  Large LLM run at all. `compose_session_recall` answers from the
  timeline via a plain template — an unset pin says so honestly ("You
  haven't told me your insurance yet") instead of guessing. A genuine new
  clinic question ("What insurance do you accept?") doesn't match and
  reaches SQL exactly as before — verified by test, not assumed.
- `classify_pin_amendment(message, timeline)` → true only when a bare
  date/time retarget ("Actually Tuesday", "No, Monday was better", "make
  it tomorrow") coincides with an open doctor/availability thread *and*
  no confirmed booking — that guard is load-bearing: it's what keeps this
  from ever hijacking a real reschedule of an existing appointment, which
  correctly still requires identity verification via its own, separate,
  untouched path. `engine.py` overrides `nlu.intent` to
  `DOCTOR_AVAILABILITY` on a match and keeps the resolved doctor pin,
  trusting the NLU's own date/time extraction as-is.
- `resolve_ordinal_doctor_ref(message, timeline)` → "the second doctor
  you mentioned" resolved by list index against `shown_doctors`. **Does
  not** close the "Deferred — Conversation state / coreference" gap
  below — ordinal list-index reference is a narrower, safer problem than
  general unbound pronoun resolution ("him", "that one" with nothing to
  index into); "book with him" after a prose bio (no list shown) still
  correctly fails to resolve, verified by test.
- `classify_preview_only(message)` → "don't book anything until you show
  me...", persisted as a per-turn (non-sticky) timeline flag; suppresses
  `exec_plan.booking` in `planner.py` while leaving availability SQL
  untouched.
- `PlannerFacts`/`build_planner_facts` (`planner.py`) gained the four
  corresponding fields — computed in `engine.py` (where timeline is
  available) exactly like the pre-existing `doctor_followup`/
  `unknown_doctor_requested` pattern, since `compute_message_sensors`
  itself stays pure/I/O-free by design.
- `engine.py`: pins `insurance`/`problem` right after entity resolution
  (from *this turn's* `nlu.entities` only — never from `recent_turns` or
  prior state, mirroring the NLU prompt's own "current message only"
  entity rule); overwrites `shown_doctors`/`last_recommendation`/
  `last_slots` right after SQL execution, from the raw rows a turn
  actually produced, not the composed prose.

**Explicitly not this phase** (per the plan's own scope, respected):
compound multi-constraint booking ("fever + Aetna + cost + earliest +
book" in one turn, "cheapest service that can treat my problem"); the
unknown-doctor refusal firing on a message that never named a doctor;
emergency-trigger sensitivity (104°F-but-stable under-escalated relative
to "diagnose my appendicitis" over-conservatively refused); insurance
handler contradictions (a structured card showing Aetna HMO Plus for a
PPO question, while the LLM's own prose correctly distinguished HMO vs.
PPO in the same conversation); empty RAG on genuinely out-of-scope
clinical questions (kidney stone surgery); cloning the competitor's
client-side localStorage architecture. All real, all found in the same
transcript, all deliberately left for their own phases.

**Files changed:** `apps/chatbot/conversation_state.py` (5 new timeline
fields, 4 new classifiers, 1 compose function), `apps/chatbot/engine.py`
(pin-writing after resolve, shown/slots-writing after SQL, the four
sensors computed and threaded through, `session_recall` dispatch),
`apps/chatbot/planner.py` (4 new `PlannerFacts` fields, `session_recall`
override, `preview_only` suppressing `booking`), `apps/chatbot/tests/
test_conversation_state.py` (17 new tests), `ARCHITECTURE.md` §10.

**Verified:** every one of the plan's own 8 requested test phrases,
reproduced end-to-end against the live engine (not just unit-tested):
"What insurance did I tell you" → honest recall, no RAG. "Which doctor
did you recommend?" (the exact hallucination transcript) → "I listed Dr.
Priya Chandrasekaran" — no invented Omar Haddad. "What was the
appointment time you found?" → the real prior slot, verbatim. "What were
we just talking about?" → an honest recap from real pins. "Actually
Tuesday" after a Monday offer → re-queries Tuesday, keeps Priya, no RAG.
"The second doctor you mentioned" → correctly resolves James Whitaker,
not "I did not mention a second doctor." Negative: "What insurance do you
accept?" (no pin) still reaches SQL normally. Negative: "Actually
Tuesday" with no open doctor/availability thread does not fire
pin_amendment. 17 new backend tests. Full suite: `apps.chatbot.tests
apps.knowledge.tests` — **567/567** (550 baseline + 17 new). Eval:
**674/682 (98.8%)** — identical to the last recorded baseline, same two
pre-existing adversarial gaps, zero new failures.

**Known limitations / found but not fixed:**
- `compose_session_recall`'s "insurance" answer can be less specific than
  what the patient actually said (stores the raw extracted entity text,
  e.g. "Aetna" when they said "Aetna PPO" — honest, just occasionally
  less precise than the source utterance; not a hallucination, a fidelity
  gap).
- Everything in the "Explicitly not this phase" list above, restated
  here per the working-agreement convention.

## ✅ Phase 40 — Real patient-question audit (external datasets)

Different trigger than every prior phase in this file: not a pasted
transcript from this system, but a request to stop trusting only the
682-case synthetic eval battery and check against how real patients
actually phrase things. Downloaded five public real-question sources —
[LasseRegin/medical-question-answer-data](https://github.com/LasseRegin/medical-question-answer-data)
(WebMD, eHealthForum, iCliniq, "Question Doctor" — real forum-posted
patient questions, ~23k WebMD rows alone) and
[HealthSearchQA](https://huggingface.co/datasets/katielink/healthsearchqa)
(3,173 real consumer search queries, questions-only) — both genuinely
public and directly downloadable, unlike MedQuAD (real but professionally-
authored NIH FAQ templates, not organic patient phrasing, so not used) or
HealthAdvice/Apple's Health Query Profiles (paper-only, no downloadable
question set). Per instruction, did **not** build a new formal eval suite
from these — randomly sampled real questions across the five sources and
ran each through the **live engine** end-to-end against
`horizon-family-care` (fresh session per question, real NLU/planner/SQL/
vector/Large LLM calls — not eval-harness NLU-only) via
`ChatEngine().process(...)`, matching this session's standing discipline
of reproducing against the real system rather than trusting a script. Two
passes: an initial 25-question sample (seed 20260827), then — per explicit
follow-up instruction to use at least 70 — a second, independent 75-
question sample (seed 20260827001, no overlap with the first), for **100
real patient questions checked live in total**.

**Found five real, reproducible bugs — all present before this phase, all
missed by all 682 synthetic eval cases** (the synthetic set is
professionally-worded; real patients aren't). The first three surfaced in
the initial 25; the larger 75-question follow-up immediately surfaced two
more, including a second confirmed instance of bug 1's exact failure
mode on a different term — direct evidence the underlying pattern (short-
circuit safety/matching regexes with no length or framing guard) recurs
rather than being a one-off:

1. **Bare "stroke"/"heart attack" triggered the hard 911 override on purely
   informational questions.** `EMERGENCY_RE` (`nlu/emergency_patterns.py`)
   and `SYMPTOM_CUE_RE` both listed `heart\s+attack|stroke` as bare,
   unanchored alternatives — every other entry in both patterns requires a
   narrative symptom phrase ("chest pain", "can't breathe"). Real
   HealthSearchQA sample "What are the 4 causes of a stroke?" (a factual,
   third-person question) got: "If you are experiencing a medical
   emergency, call emergency services..." Traced end-to-end: `rules.py`'s
   `_match_safety` fires from `EMERGENCY_RE` first; even after narrowing
   that, `nlu/classifier.py`'s separate `has_symptom_cues`/
   `extract_emergency_symptoms` fallback (fed by the *same* bare term in
   `SYMPTOM_CUE_RE`) independently re-triggered it — two redundant hard
   layers, both needed the fix, not one.
2. **Off-topic subtype keyword lists used naive substring containment.**
   `response_templates.py`'s `resolve_direct_template` checked `p in msg`
   for keywords including single short words ("trip", "eat", "app "). A
   real eHealthForum message — an angry complaint about a spouse being
   "asked to **strip** down" for an exam without consent — matched "trip"
   inside "strip" and got: "Sounds like a great trip idea!" instead of the
   generic off-topic redirect.
3. **`_STRONG_CANCEL_RE` fired unconditionally on any occurrence, at any
   position, in an arbitrarily long message.** A real eHealthForum question
   about a foot bump — "...it use to hurt but **not anymore** it could be
   from trauma..." (~70 words, `not anymore` modifying `used to hurt`, zero
   cancel intent) — matched `detect_recovery`'s strong-cancel branch (the
   *only* branch with no length gate — `_WEAK_CANCEL_RE`'s branch already
   had one) and returned the generic "Sure — what would you like to do
   instead?", discarding the patient's actual question.
4. **Same failure mode as bug 1, on a different term.** The 75-question
   follow-up hit it immediately: "What is shortness of breath symptom of?"
   (real HealthSearchQA) — a purely informational question — also got the
   911 override. "shortness of breath"/"difficulty breathing" were still
   sitting in the "narrative, always trust" bucket after the first fix,
   which only carved out "stroke"/"heart attack". Proves the earlier fix's
   scoping to exactly two terms was reasonable given the evidence at the
   time, but the underlying failure mode (a term commonly used in genuine
   consumer health trivia, not anchored to a live-symptom phrase) is not
   unique to those two.
5. **Doctor-name fuzzy matching collided with a common English word inside
   a long message.** A real eHealthForum patient narrative (~90 words,
   several paragraphs about facial swelling, an ER visit, a CT scan) never
   named any doctor, but got prefixed with: "Did you mean Dr. Omar Haddad?
   Other close matches: Dr. Priya Chandrasekaran." Root cause: `_fuzzy_
   score`'s substring-match branch (`nlu/resolvers.py`, recalibrated in
   Phase 38) had no minimum length on the shorter string — "**had**" (from
   "...i had explained to the dr...") is a literal 3-letter prefix of
   "**Had**dad", scoring `0.55 + 0.35*(3/6) = 0.725`, past the medium-
   confidence "did you mean" threshold (0.65). `resolve_doctor_candidates`
   extracts *every* non-stopword word in the message as a name-evidence
   token (93 of them for this one message) and fuzzy-scores each against
   every clinic doctor — with a long enough message, a coincidental
   collision like this becomes likely, not unlikely.

**Fixes, each scoped to exactly the proven false-positive, verified not to
weaken the genuine-emergency/genuine-cancel/genuine-travel/genuine-
doctor-name cases:**

- `emergency_patterns.py`: `EXCEPTION_TERMS_RE` (stroke, heart attack,
  shortness of breath, difficulty breathing — the four terms proven prone
  to WH-question phrasing, moved out of `EMERGENCY_NARRATIVE_RE`/
  `SYMPTOM_NARRATIVE_RE`'s "always trust" bucket) plus one shared
  `is_informational_emergency_mention(text, narrative_re)` — True only
  when no narrative phrase matched, one of those four terms is present,
  the message reads as a WH question about the condition ("what/how/why
  causes/symptoms/signs/treatment/risk factors/prevention/diagnosis
  of..."), and there's no experiential framing ("I'm having", "right
  now", "currently"). Deliberately **not** generalized to every narrative
  phrase — chest pain, arm numbness, choking, suicidal/kill myself, severe
  bleeding, unconscious all stay unconditionally fail-closed; nothing in
  either data pass proved those prone to informational phrasing, and the
  cost of a missed genuine self-harm or cardiac disclosure is far worse
  than one unnecessary 911 nudge on a trivia question. Used by `rules.py`'s
  `_match_safety` and `entity_extract.py`'s `has_symptom_cues` (the
  latter's only consumer is the classifier's emergency-override path,
  confirmed by grep before changing it — the *separate*, lower-stakes
  `has_symptom_cues` in `routing/signals.py`, used for business-hours-
  answer gating, was deliberately left untouched). `EMERGENCY_RE`/
  `SYMPTOM_CUE_RE` themselves are unmodified.
- `response_templates.py`: new `_contains_word()` helper doing real
  `\bword\b` regex matching, `.strip()`-ing the manual space-padding hacks
  ("` eat`", "`app `") the old substring approach needed and no longer
  does. Applied to the five off-topic subtype lists sharing this exact
  mechanism (phone/sports/food/travel/entertainment); the greeting/
  thanks/mental-health keyword lists elsewhere in the same file weren't
  implicated by the reproduced bug and weren't touched.
- `conversation_state.py`: added `_STRONG_CANCEL_MAX_WORDS = 15` gate on
  `detect_recovery`'s strong-cancel branch, mirroring the existing
  `len(text.split()) <= 6` precedent already used for
  `_OFF_TOPIC_ABUSE_RE` in `rules.py` for the same class of problem
  (short-phrase heuristic false-triggering inside a long, unrelated
  message).
- `nlu/resolvers.py`: `_fuzzy_score`'s substring-match branch now requires
  `min(len(needle), len(candidate)) >= _MIN_SUBSTRING_MATCH_LEN` (4) before
  granting the generous `0.55 + 0.35*coverage` score; below that floor it
  falls through to plain Levenshtein scoring, which correctly scores
  "had"/"haddad" at 0.5 (under both the 0.6 default and 0.65 medium
  thresholds) instead of 0.725. Verified the Phase 38 golden cases this
  branch was tuned around are unaffected: priya/priyanka (0.769), sara/
  sarah (0.83), rjet/rajat (0.6, a different branch entirely) all
  unchanged — the floor only excludes needles shorter than 4 characters,
  which none of those are.

**Files changed:** `apps/chatbot/nlu/emergency_patterns.py`,
`apps/chatbot/nlu/rules.py`, `apps/chatbot/nlu/entity_extract.py`,
`apps/chatbot/nlu/resolvers.py`, `apps/chatbot/response_templates.py`,
`apps/chatbot/conversation_state.py`, `apps/chatbot/tests/test_nlu.py`
(+2), `apps/chatbot/tests/test_recovery_override.py` (+2), new
`apps/chatbot/tests/test_response_templates.py` (+5), `apps/chatbot/
tests/test_resolvers.py` (+2).

**Tests:** 11 new regression tests, each reproducing the exact real-data
failure string. `apps.chatbot.tests apps.knowledge.tests` —
**578/578** (567 baseline + 11 new). Eval: **674/682 (98.8%)** — identical
to baseline, `emergency`/`horizon_emergency`/`off_topic` lanes still
100%, same two pre-existing unrelated adversarial gaps, zero new
failures, checked after each of the two fix rounds. All five fixes
re-verified live (not just unit-tested): the full 100-question set (25 +
75) was re-run through `ChatEngine().process` end-to-end after every
fix, with zero engine errors and zero recurrences of any of the five
failure patterns in the final pass.

**Known limitations / found but not fixed:**
- Standard FAST stroke-symptom language ("face drooping", "slurred
  speech", "one-sided weakness") is not in `EMERGENCY_RE`/`SYMPTOM_CUE_RE`
  at all — a gap noticed while reading these patterns closely, not proven
  by either sampled batch, so not touched this phase; worth its own
  investigation.
- `SYMPTOM_CUE_RE` never included "difficulty breathing" in the first
  place (only `EMERGENCY_RE` did) — a pre-existing asymmetry between the
  two patterns, not caused by this phase and not user-visible (rules.py's
  `EMERGENCY_RE`-driven path still catches genuine "difficulty breathing"
  reports correctly), left alone rather than expanded speculatively.
- Only 100 of the ~27,000+ downloaded real questions were run across both
  passes — still a random spot check, not a systematic pass. The fact
  that the second, independent 75-question sample immediately surfaced
  two more real bugs (one a second instance of an already-"fixed" failure
  mode) is itself evidence that further sampling would likely find more;
  not pursued further this phase.
- The other three requested sources (MedQuAD, HealthAdvice, Apple's Health
  Query Profiles) were investigated but not usable as downloadable
  question sets — noted for the record rather than silently substituted.

**Recommended next phase:** the pattern is now confirmed recurring, not
hypothetical — a dedicated audit of every regex-based rule and every
fuzzy/substring-matching mechanism in `nlu/rules.py`, `nlu/resolvers.py`,
`response_templates.py`, and `conversation_state.py`, either read closely
for the same class of gap (unanchored keyword, no length floor, no
framing guard) or checked against a much larger random sample from the
same five real-question sources, would be the natural follow-up — not
started here, this phase fixed exactly the five proven cases.

## ✅ Phase 41 — Doctor-search precision + context/pronoun resolution

Triggered by the user's own real-world testing plus an external reviewer
(GPT), consulted separately, who produced a 7-failure critique, a
suggested implementation prompt, and a 45-question test matrix. Explicit
instruction this time: don't implement GPT's prompt blindly — understand
the real architecture first, verify every claim against actual code and
live traces, correct anything GPT got wrong, and only then plan (via
`EnterPlanMode`, presented and approved before any code changed) and
implement. That verification changed the diagnosis in real ways (below),
and live testing during implementation surfaced four more real bugs GPT's
own critique never mentioned.

**What GPT got right, confirmed live:** "which doctors can see children"
and "do you have female doctors" both hit `search_doctors` with zero
filters, returning the same unfiltered top-3 regardless of question
semantics. "Tell me about Priya and Omar" (bare first names) extracted
`patient_name` instead of `doctor_name` and misclassified `off_topic`.
"Aetna HMO" and "Aetna PPO" returned the identical row.

**What GPT got wrong, caught before writing any code:** GPT's suggested
mechanism was `service_filter_mode` — grepped every consumer of that
field; it's read only by the `services` SQL handler (a different concept,
"what services do you offer"), never by `search_doctors`. Implementing
GPT's suggestion would have been a plausible-looking dead end.
`search_doctors` (`sql_tool/handlers/doctors.py`) already filters
correctly by `service_id`/`specialty_id`/`doctor_id` when populated — the
real gap was entirely upstream, in two places GPT never identified: (1)
the Small LLM had **no doctor roster in its prompt at all** —
`build_document_catalog`/`build_service_catalog` exist, there was no
`build_doctor_catalog`, which is the actual root cause of the Priya/Omar
misclassification too, not a separate issue; (2) no rule mapping a
capability phrase ("see children") to the matching catalog service name,
and even with one, `_match_service`'s plain `icontains` wouldn't catch
"children" against "Pediatric Well-Child Exam" (no textual overlap). GPT
also didn't reproduce two of its own claimed failures: "Tell me about
Priya" → "What doctors do you have?" already correctly returned the full
catalog (Failure 7 didn't reproduce), and "Book Dr. Sarah Monday
afternoon" already correctly classified `book_appointment` (not
`doctor_search` as claimed) — though the underlying entity noise
(`doctor_name: ["Sarah","Sarah Monday"]`) was real, just not currently
symptomatic. GPT's pronoun-resolution design also had a real safety gap
of its own: nothing in its plan accounted for "My daughter has a fever,
can she see a doctor" — where "she" is the daughter, not a previously-
discussed doctor. Added as an explicit guard (below), not part of GPT's
own suggestion.

**Root causes and fixes, in the order found:**

1. **No doctor roster reaches the Small LLM.** New `build_doctor_catalog`
   (`routing/doc_catalog.py`), same shape as `build_service_catalog` —
   `{id, full_name, specialty}` — wired into `engine.py`'s `nlu_ctx` next
   to `services`, rendered as a new `Doctors:` line in `nlu/prompts.py`.
   One new system-prompt rule: a name matching the roster is
   `doctor_name`, not `patient_name`; two listed doctors in one message →
   `doctor_name` array of both, `doctor_search` even with no other
   clinic-fact keyword. This is the single highest-leverage fix — it's
   what let every downstream pronoun/ambiguity mechanism receive correct
   data to work with.
2. **Capability-phrase → service resolution.** New system-prompt rule:
   "which doctors can see/treat children/kids", "who provides pediatric
   care" → `doctor_search` (never `faq`), `entities.service` = the listed
   "Pediatric..." service verbatim. Measured, not assumed, reliability:
   isolated tests hit 5/5, but under the *full* prompt (with the clinic's
   membership-contract `Docs:` block also present) it measurably missed
   sometimes. Added a **deterministic Python backstop**,
   `resolve_pediatric_service_fallback` (`nlu/resolvers.py`) — age-group
   language (child/children/kid/kids/pediatric/infant/baby/toddler) with
   no service already resolved falls back to the clinic's own
   "pediatric"-named service. Scoped to `intent == DOCTOR_SEARCH` only —
   a symptom report ("my child has a fever") that happens to contain
   "child" must not get silently narrowed to only well-child-exam
   providers; that's a different question (acute vs. routine care) this
   fallback has no business answering. This is a narrow, single-concept
   heuristic (not a general synonym table, consistent with the explicit
   "no brittle keyword lists for every sentence" instruction), and
   follows the same "Python heuristics as sensors supplementing NLU"
   pattern already established in `routing/heuristics.py`.
3. **Gender questions — deterministic, not inferred.** `Doctor` has no
   gender field (confirmed, full model read). New
   `classify_gender_question` (`conversation_state.py`, regex over the
   raw message) + new `direct_mode="gender_unsupported"` planner
   short-circuit (same pattern as Phase 39's `session_recall`) — stops
   before SQL/vector/LLM entirely, fixed response explaining gender isn't
   tracked. The Large LLM never sees the doctor list for this question,
   so it can't guess from bios/names.
4. **Doctor-pronoun resolution — the "critical part" per the user's own
   framing.** Reuses 100% existing Phase 39 state
   (`ConversationTimeline.doctor`, `.shown_doctors`) — no new fields. New
   `classify_doctor_pronoun_reference` detects a doctor-directed pronoun
   ("she/he/they/the doctor") as the subject of a capability/quality/
   availability/service question. **Safety guard GPT's own plan omitted,
   added deliberately:** a family-relation noun in the same message ("my
   daughter/son/child/kid/wife/husband") blocks resolution — "she" in "my
   daughter has a fever, can she see a doctor" must not resolve to a
   previously-discussed doctor. Wiring in `engine.py`, computed alongside
   the existing `doctor_followup`/`unknown_doctor_requested` sensors:
   `len(shown_doctors) == 1` (or a single-mention `timeline.doctor` pin)
   → inject `resolved_ids.doctor_id`, same mechanism as Phase 39's
   `ordinal_doctor_id`, and correct `intent` only if it isn't already
   doctor-related (a backstop, not the primary mechanism — NLU gets it
   right unaided most of the time). `len(shown_doctors) >= 2` → new
   `direct_mode="doctor_pronoun_ambiguous"` planner branch, "Do you mean
   Dr. X or Dr. Y?" composed from `shown_doctors` names.
5. **Insurance plan-type precision (PPO vs HMO).** Two stacked causes,
   both real: (a) `insurance_accepted`'s provider matching ignored
   `plan_type` entirely; (b) `resolve_entities`'s own `_match_insurance`
   isn't plan-type aware either, and with two same-provider plans can
   silently resolve to the wrong specific one via query tie-breaking —
   which then *bypassed* the first fix, since a resolved `plan_ids`
   originally skipped type-checking. Fixed by making the type check
   independent of which path resolved a candidate: when the message names
   a type, match by provider text (not the possibly-wrong resolved
   `plan_ids`) and let the type filter pick the right row; when the named
   type genuinely isn't on file, say so honestly ("We don't see an Aetna
   PPO plan on file, but we do accept Aetna (HMO Plus)") instead of
   presenting the other type as the answer.
6. **Booking entity precision.** Strengthened NLU prompt rule: `doctor_name`
   is one clean value, never a day-of-week/time-of-day word appended, and
   never both a clean and contaminated version of the same name in the
   array — fixed `["Sarah","Sarah Monday"]` → `["Sarah"]`, 6/6 verified.
   Also fixed a real regression this same rule-strengthening pass
   introduced: the new roster/capability rules briefly made "book Dr.
   Sarah Monday afternoon" less reliably `book_appointment` (observed
   `doctor_search` under full-prompt conditions); added an explicit
   contrast ("this wins even when the message also names a doctor from
   the roster") and reconfirmed 5/5.

**Found live during implementation, not in GPT's critique at all:**

7. **A separate fuzzy-resolution path silently collapsed a correct
   multi-doctor resolution to one.** `resolve_entities` correctly
   resolves `doctor_name:["Priya","Omar"]` to both real ids — but
   `engine.py`'s free-text single-best-match resolver
   (`resolve_doctor_candidates`, used to fill gaps when NLU's *own*
   extraction is too coarse) then unconditionally overwrote that with
   whichever one scored higher, discarding the second doctor. Fixed by
   skipping that fuzzy overwrite whenever `resolved_ids.doctor_id` is
   already a genuine multi-value list.
8. **The old, narrower `doctor_followup` mechanism pre-empted the new,
   more precise one.** `_is_doctor_quality_followup`'s "is he"/"is she"/
   "are they" substring check also matches inside "When **is she**
   available?" — intercepting it with a generic bio reply instead of
   real availability data, even after the new pronoun resolver correctly
   identified Priya and NLU correctly said `doctor_availability`. Fixed
   by having pronoun resolution suppress the older flag once it resolves
   an antecedent — its own trigger set is already scoped to capability/
   availability/service phrasing, never generic "is she good"-style
   quality talk, so deferring to it is strictly more correct.
9. **"should" was extracted as a doctor's name.** "Which doctor **should**
   I see?" (an entirely natural, common phrasing) → `doctor_name:
   "should"` → zero doctors ever match a name filter for "should" →
   empty result on a completely ordinary question. `_NAME_NOISE`
   (`sql_tool/handlers/doctors.py`) — the existing defensive filter for
   exactly this class of false positive — didn't include modal verbs.
   Also found and fixed in passing: `_NAME_NOISE` was duplicated
   verbatim in two functions in the same file; consolidated into one
   shared module-level constant so a future fix to one can't drift from
   the other (which is exactly how "should" would have needed fixing
   twice).

**Files changed:** `apps/chatbot/routing/doc_catalog.py` (new
`build_doctor_catalog`), `apps/chatbot/routing/__init__.py` (export),
`apps/chatbot/engine.py` (catalog wiring, pediatric-service fallback,
pronoun-sensor computation, multi-resolution guard, doctor_followup
precedence), `apps/chatbot/nlu/prompts.py` (roster/capability/entity-
precision rules), `apps/chatbot/conversation_state.py`
(`classify_gender_question`, `classify_doctor_pronoun_reference`),
`apps/chatbot/planner.py` (`gender_unsupported`/`doctor_pronoun_ambiguous`
`direct_mode` branches), `apps/chatbot/nlu/resolvers.py`
(`resolve_pediatric_service_fallback`), `apps/chatbot/sql_tool/handlers/
insurance.py` (plan-type matching), `apps/chatbot/sql_tool/handlers/
doctors.py` (`_NAME_NOISE` consolidation + additions). Test files: new
`apps/chatbot/tests/test_doctor_context_resolution.py` (+6),
`apps/chatbot/tests/test_conversation_state.py` (+5),
`apps/chatbot/tests/test_resolvers.py` (+5),
`apps/chatbot/tests/test_sql_tool.py` (+3).

**Tests:** 19 new regression tests. `apps.chatbot.tests
apps.knowledge.tests` — **597/597** (578 baseline + 19 new). Eval:
**674/682 (98.8%)** — identical to baseline, `doctors`/`booking`/
`insurance` lanes all 100%, same two pre-existing unrelated adversarial
gaps, checked after every fix round (this phase touched NLU prompts,
planner, and three SQL handlers — regression risk was real and checked
for, not assumed away).

**Live-verified, full trace, across a 22-scenario representative subset
of GPT's own 45-question matrix** (all ten rounds; NLU intent/confidence/
entities, planner facts, SQL filters/rows, vector executed/hits, LLM
called or not, final response — not just "does the reply look right"):
capability filtering converges correctly for all 5 Round-1 phrasings;
gender questions never reach SQL for any Round-2 phrasing, including a
named doctor ("Is Dr. Priya a woman?"); the full Round-3 pronoun chain
resolves "she" → Priya across four consecutive turns including a real
availability lookup; the Round-3 ambiguous case ("Priya and Omar" → "can
she") correctly asks which doctor; all 6 Round-4/5 booking phrasings
extract clean entities and the correct intent (`book_appointment` vs.
`doctor_availability` vs. `doctor_search` for the intentionally-soft
"thinking about seeing" case); Round-6 fever+child+named-doctor cases
route correctly; Round-7 HMO/PPO precision holds through the full engine
(not just the isolated handler); Round-9 emergency priority is
unaffected; the Round-10 full context-contamination chain (catalog query
→ specific follow-up → catalog query → pronoun) resolves exactly as
specified, never letting one mode bleed into the other.

**Known limitations / found but not fixed:**
- The capability-phrase NLU rule (fix 2) is measurably not 100% reliable
  on its own under the full prompt — this is why a deterministic Python
  backstop was added rather than trusting the prompt rule alone; the
  backstop is currently scoped to pediatric/age-group language only
  (the one capability explicitly tested), not a general capability→
  service mapping.
- "Which doctors accept Aetna PPO?" (list doctors filtered by an
  insurance plan, not "does this clinic accept X") isn't handled — a
  different, more complex capability (Round 8's constraint-intersection
  territory), out of scope for this phase.
- "I have Aetna PPO. Can Dr. Omar see my child?" surfaced a real,
  pre-existing (not introduced here) data gap: the `doctor_insurances`
  junction table has zero rows for at least one real doctor in the dev
  seed data, so any doctor-scoped insurance question returns "not on
  file" regardless of what the clinic broadly accepts. Root-caused via
  direct query, not fixed — a seed-data/junction-population issue, not a
  logic bug in the fixed insurance handler.
- Round 8 (compound multi-constraint booking — pediatric + insurance +
  time in one request) and general emergency-threshold tuning remain
  explicitly out of scope, as previously documented (Phase 39, Phase 40).
- The pediatric-service backstop and pronoun resolution together close
  most of the "Deferred — Conversation state / coreference" entry below
  for the *doctor* case specifically; general coreference for other
  antecedents (a mentioned service, a mentioned insurance plan) remains
  unbuilt.

## ✅ Phase 42A — Verified booking correctness (DOB check, insurance, real Review & Confirm)

Triggered by a request to professionally redesign patient verification →
booking → confirmation, plus a marketing teaser for the closed widget and
symptom-aware doctor routing (Phases 42B/42C, not started — see below).
Explicitly planned via `EnterPlanMode` before any code changed, after
three parallel research passes into what already existed. That research
found the real starting point **much further along than the request
implied** — a backend-authoritative `BookingSession` + `BookingStep.REVIEW`
already existed and was already correctly not LLM-controlled — but also
surfaced one gap bigger than the plan itself assumed, found only by
reading the code directly rather than trusting the research summary (the
session's own standing discipline): **`BookingStep.REVIEW`'s own code
comment said the standard OTP path "already requires entering a received
code, which is itself a confirming action, so it goes straight to
CONFIRMED"** — meaning the single most common booking path (a new or
returning patient typing a phone/email OTP code) had **no review screen
at all**. The code-entry submit *was* the booking, calling
`/booking/confirm` directly and creating the `Appointment` in the same
request. Confirmed by reading `booking-wizard.tsx`'s OTP step handler
directly (`bookingService.confirm({..., otp_code})`), not just the
backend comment. This is exactly the "never book silently from
conversational context" requirement, on the majority path — closing it
became the central fix of this phase, larger than originally scoped.

### What was built

1. **DOB identity check.** `Patient.date_of_birth` already existed
   (confirmed unused anywhere in the codebase before this). Two-factor:
   OTP proves contact ownership, DOB — collected as a structured DETAILS-
   step form field, never asked about in free-text chat — proves identity
   against the record that contact resolves to, checked only *after* OTP
   succeeds (gating on DOB pre-OTP would make it a brute-forceable oracle
   with no rate limit tied to a proven channel). A patient with no stored
   DOB (new registration — `send_otp` always get-or-creates the `Patient`
   row before the code goes out, so "new" and "legacy record predating
   this check" are the same case) is captured, never compared, never
   locked out. Lockout (`Patient.dob_check_attempts`/
   `dob_check_locked_until`, new fields, migration `0004`) is scoped to
   `(clinic, patient)`, deliberately *not* the `OTPVerification` row —
   that row's own `attempts` resets to 0 on every resend (confirmed by
   reading `send_otp`: always creates a fresh row), which would let a
   resend reset a DOB brute-force counter too if it lived there. Failure
   messaging is identical for a mismatch and a lockout — never confirms
   which, or whether a record exists at all for the phone/email given.
   `apps/patients/services/patient_service.py`'s `verify_date_of_birth`;
   wired into `otp_service.verify_otp` (new `date_of_birth` param) so the
   DOB check runs inside the same call that confirms the code, and a
   wrong DOB blocks the whole verification (session never authenticated),
   same as a wrong code would — the code itself is still consumed either
   way, so retrying DOB guesses costs a fresh code request each time.
2. **The OTP→REVIEW→CONFIRMED split** (the big one). New `apply_step`
   action `verify_otp`: runs `verify_otp()` (code + DOB), stores the
   resolved `patient_id`/`dob_verified` on `BookingSession`, and lands on
   REVIEW — no `Appointment` created. The *existing* `confirm_review`
   action (already used by the two shortcut paths — an already-
   authenticated session, or `verification_mode="none"`) now also checks
   `session.patient_id` first, reusing the already-verified patient rather
   than requiring a second, impossible OTP submission (a code can only be
   consumed once). `booking_router.py`'s `/booking/confirm` keeps a
   backward-compatible fallback branch for a caller that still submits
   `otp_code` directly without the new two-step flow. Frontend: the OTP
   step's "Confirm appointment" button (labeled that regardless of what
   it actually did) now calls the new `verify_otp` step action instead of
   the direct confirm endpoint, and is relabeled "Verify code" — the
   REVIEW screen's own already-existing "Confirm booking" button (now
   "Confirm & book") is the one and only action that creates the
   `Appointment`, for every path, not just the two that already had it.
3. **Insurance actually threaded through, not string-concatenated.**
   `BookingSession` gained `insurance_plan_id`/`insurance_plan_name`.
   `BookingService._resolve_insurance` reuses `resolve_entities` (the
   exact same name→plan matcher the chat/NLU path already uses — no new
   matching logic) instead of the old behavior of folding
   `insurance_name` into the free-text `reason` and never resolving it to
   anything. `confirm()`'s `Appointment.objects.create(...)` now passes
   `insurance_plan_id=session.insurance_plan_id` — the FK existed on
   `Appointment` since before this phase and was simply never set by this
   path (confirmed: the separate admin-facing `POST /appointments`
   endpoint already did this correctly; the wizard path never did).
4. **Review & Confirm is now actually complete**, for every path. Backend
   REVIEW/CONFIRMED payloads (`serializers.py`) gained patient phone/
   email, `insurance_plan_name` (explicit `None` → frontend renders "Not
   selected", never a blank gap), `dob_verified`, a formatted clinic
   `location`, and a `review_disclaimer` (new clinic-configurable booking-
   config default, generic and accurate rather than a specific claim this
   system can't verify a given clinic meets). Frontend `ReviewStep` renders
   all of it in a plain summary block before the confirm button — patient,
   insurance, location, an "Identity verified" indicator when
   `dob_verified`, and the disclaimer text. **"Go back & edit" turned out
   to already exist** — the wizard's shared bottom Back button (calling
   the pre-existing `action="back"`/`prev_step()` mechanism) already
   renders for every non-path step including REVIEW; the initial research
   pass's narrower grep missed it, caught here by reading the actual
   render logic directly rather than trusting that finding as-is.
5. **Interrupted-booking recovery** — the plan's own flagged blocking
   prerequisite, verified before anything else was built on it. Confirmed
   real: `/chat/resume` only ever replayed historical chat messages, and
   `hydrateHistoryRow` (frontend `message-parser.ts`) deliberately stamps
   any *historical* `booking_wizard` message `completed: true` so an old,
   already-processed wizard card from real history can never mount live
   again — correct for genuine history, but it meant an interrupted,
   still-in-progress booking had no path back once the tab closed and
   reopened. New `BookingService.active_booking_payload` (read-only,
   reuses the existing `_load_active`/`serialize_step`) surfaced through a
   new `active_booking` field on `/chat/resume`'s response; the frontend
   appends it as a live (non-`completed`) `booking_wizard` message on
   resume, which `activeWizardId`'s existing "last non-completed
   booking_wizard message" logic then picks up automatically — no new
   frontend wizard-mounting logic needed, just feeding it the one signal
   it didn't have.

### Explicitly not this phase

Phase 42B (embeddable `<script>` widget-loader + closed-state marketing
teaser) and Phase 42C (per-clinic condition/specialty data model +
symptom-aware doctor search, replacing the existing 10-entry hardcoded
`_SYMPTOM_MAP` soft-suggestion-only fallback in `booking/discovery.py`) —
both fully scoped in the approved plan, neither started.

**Files changed:** `apps/patients/models.py` (+migration `0004`),
`apps/patients/services/patient_service.py` (`verify_date_of_birth`,
`IdentityVerificationError`), `apps/chatbot/services/otp_service.py`
(`date_of_birth` param, `OTPVerifyResult.dob_verified`),
`apps/chatbot/booking/state.py` (`insurance_plan_id/name`, `pending_dob`,
`dob_verified`), `apps/chatbot/booking/service.py` (`verify_otp` action,
`_resolve_insurance`, `active_booking_payload`, DOB collection/validation
in `submit_details`, insurance/DOB threaded through `confirm()`),
`apps/chatbot/booking/serializers.py` (REVIEW/CONFIRMED field
completeness, `_clinic_location`), `apps/chatbot/booking/config.py`
(`review_disclaimer` default), `apps/api/widget/booking_router.py`
(`verify_otp` DOB wiring, backward-compatible confirm fallback),
`apps/api/widget/router.py` (`active_booking` on `/chat/resume`),
`frontend/src/features/booking/booking-wizard.tsx` (DOB field, OTP-step
rewiring, Review/Confirmed field rendering), `frontend/src/features/chat/
chat-widget.tsx` (resume wiring for `active_booking`), `frontend/src/
types/api.ts`.

**Tests:** 24 new. `apps.chatbot.tests apps.knowledge.tests
apps.api.widget.tests apps.patients` — **674/674** (650 baseline-for-this-
suite-combination + 24 new). Eval: **674/682 (98.8%)** — unchanged (this
phase doesn't touch NLU/planner/routing). Frontend: `tsc --noEmit` and
`next build --turbopack` both clean (same pre-existing, unrelated
warnings already on file from earlier phases this session; one unrelated
pre-existing `/reset-password`/`/select-tenant` page-data collection
error in this dev environment, confirmed unrelated by grep — neither
route was touched).

**Known limitations / found but not fixed:**
- `useBookingConfirm` (a React Query hook wrapping the now-superseded
  direct-confirm call) has zero remaining call sites after this phase's
  frontend rewiring — left in place rather than removed, since deleting a
  hook with no traceable-by-grep dynamic usage carries more risk than the
  small cost of one unused export; flagged here rather than silently
  removed or silently left undocumented.
- `OTPVerification.attempts` resetting on every resend (confirmed by
  reading `send_otp`) is a real, pre-existing gap in the *OTP code's own*
  brute-force protection — noted because it's exactly the pattern DOB's
  lockout was deliberately built to avoid, but fixing OTP's own counter
  is a separate concern, not fixed here.
- `review_disclaimer` ships one sensible default string; no per-clinic
  admin UI to edit it yet (only via `WidgetSettings.configuration.booking`
  directly) — acceptable for this phase, a real gap for clinic operators.

### Phase 42A.1 — Live-testing follow-up: Review compactness, inline edit, closed-widget teaser

After live testing the shipped Phase 42A flow, two real gaps surfaced:
the Review screen was visually heavy (big centered icon, three stacked
headline lines, py-6 padding — tall enough to need its own internal
scroll on shorter viewports), and "Go back & edit" via the shared bottom
Back button meant walking back through OTP re-verification just to fix a
typo'd name — no actual input fields on Review itself. Separately, the
closed (bubble) state of the standalone widget had no marketing teaser at
all — Phase 42B (the full embeddable `<script>` loader + closed-state
teaser) was explicitly deferred, but the teaser rotation itself doesn't
depend on that infrastructure for the existing internal `mode="widget"`
bubble, so it was pulled forward here rather than left broken.

1. **Review screen, compacted.** `ReviewStep` (`booking-wizard.tsx`)
   dropped the big centered `size-14` icon + 3-line headline block in favor
   of a compact left-aligned icon+title row (`CalendarCheckIcon` now takes
   a `small` prop) with doctor/date/time folded into one truncated
   subline; outer padding/gaps tightened (`py-6 gap-4` → `py-1.5
   space-y-3`).
2. **Inline edit on Review.** New backend action `edit_details`
   (`apply_step` in `service.py`, gated to `session.step == REVIEW`) lets
   the patient patch `first_name`/`last_name`/`insurance_name` in place —
   insurance re-resolved through the same `_resolve_insurance` helper
   `start()` already uses, first_name required non-empty. **Deliberately
   does not accept phone/email/DOB** — those are the identity-verification
   anchor already OTP+DOB-checked to reach REVIEW at all; changing contact
   info still has to go back through real re-verification via the
   existing Back button, same rule already applied to DOB in 42A proper.
   Frontend: an "Edit" toggle on the Review summary swaps it for actual
   `<Input>` fields (first/last name, insurance) with Cancel/Save, calling
   `runStep("edit_details", ...)` — no new networking code, reuses the
   existing `runStep` plumbing every other action already goes through.
3. **Closed-widget marketing teaser** (the closed-bubble slice of Phase
   42B, pulled forward). `chat-widget.tsx`: a small rotating teaser bubble
   renders above the launcher button whenever `mode === "widget" && !open`
   — the four vetted messages from the approved plan (the "Prefer
   privacy…" variant was already dropped at planning time for making a
   confidentiality claim the platform can't guarantee). 1.4s initial
   delay so it doesn't flash on page load, 5s rotation, remounts the
   message span on each rotation (`key={teaserIndex}`) to restart a single
   320ms fade/slide-in keyframe — no bounce, shake, or continuous-loop
   motion. Clicking the bubble opens the chat directly (the actual
   conversion path). `prefers-reduced-motion` respected by extending the
   existing media-query block in `chat-widget.css` rather than a parallel
   mechanism. **Embedded mode is untouched** — it still has no closed
   state at all (forced open), since giving it one is the loader-script
   half of Phase 42B (`postMessage`-driven resize, standalone static
   loader script, origin validation) and wasn't in scope here; this only
   fixes the internal `mode="widget"` bubble, confirmed visible live by
   the user after this change.

**Files changed:** `apps/chatbot/booking/service.py` (`edit_details`
action), `frontend/src/features/booking/booking-wizard.tsx` (compact
`ReviewStep`, `CalendarCheckIcon` `small` prop, inline edit UI),
`frontend/src/features/chat/chat-widget.tsx` (teaser state/rotation +
render), `frontend/src/features/chat/chat-widget.css` (teaser keyframes +
reduced-motion).

**Tests:** 5 new (`EditDetailsAtReviewTests` in
`test_booking_otp_review_flow.py` — name/insurance update lands on REVIEW,
first name required, rejected before REVIEW, phone/email fields ignored,
edited name reaches the CONFIRMED payload). `apps.chatbot.tests
apps.knowledge.tests` — **617/617**. `apps.api.widget.tests
apps.patients.tests` — **62/62**. No eval-battery-relevant code touched.
Frontend: `tsc --noEmit` clean, `eslint` on both touched files clean (one
pre-existing, unrelated `react-hooks/exhaustive-deps` warning on a hook
this change didn't touch).

**Known limitations / found but not fixed:**
- The full Phase 42B embeddable `<script>` loader (standalone static
  loader file, `postMessage`+`ResizeObserver` cross-origin resize, origin
  validation, loader idempotency guard) is still not built — only the
  closed-state teaser for the existing internal widget bubble. A
  third-party clinic site still cannot embed this widget at all yet.
- Phase 42C (per-clinic condition/specialty data + symptom-aware doctor
  search) — still not started.
- The teaser has no per-clinic copy customization and no frequency cap
  beyond "closed" — it rotates the same four hardcoded messages every time
  the bubble is closed, for every clinic, indefinitely. Acceptable for a
  first pass; a real per-clinic admin UI and/or a soft per-session cap
  would need its own scoping.

## ✅ Phase 43 — Remove local SentenceTransformer embeddings

Triggered by an AWS/EC2 deploy: `pip install -r requirements/base.txt`
still pulled `sentence-transformers` (and therefore `torch`) even though
chat RAG already used OpenAI `text-embedding-3-small`. The local BGE
provider was leftover from the earlier switch (see Knowledge — OpenAI
embeddings below) — defaults were OpenAI, but the code path and the
dependency were still installed and `EMBEDDING_PROVIDER=local` would still
try to load a Hugging Face model at gunicorn start.

**What changed.** Deleted `apps/knowledge/embeddings/local.py`. Factory
only builds `OpenAIEmbeddingProvider`; `EMBEDDING_PROVIDER=local` raises
`EmbeddingError` telling the operator to set openai. `warm_up_embedding_service()`
is a hard no-op (does not call `get_embedding_service()`), so a leftover
`local` env var cannot import torch at process start. Dropped
`sentence-transformers` from `requirements/base.txt`.

**Files:** `apps/knowledge/embeddings/local.py` (deleted),
`apps/knowledge/embeddings/factory.py`, `apps/knowledge/apps.py` (comment),
`apps/knowledge/tests/test_embeddings.py`,
`apps/knowledge/tests/test_embedding_warmup.py`, `requirements/base.txt`,
`config/settings/base.py`, `.env.example`, `ARCHITECTURE.md` §9.

**Tests:** factory rejects `local` with "removed"; warm-up does not touch
the embedding service even when provider is still `local`. Run
`python manage.py test apps.knowledge.tests --keepdb`.

**Not this phase:** reindexing clinic documents (still required after the
768→1536 migration); NLU still uses OpenAI/Gemini as before.

## 💤 Deferred — Conversation state / coreference

Real, confirmed from transcript ("which one treats cancer?" → "Dr. Chloe
Bennet" → "book with him" fails to resolve "him"). Deliberately not folded
into Phase 11 (doctor resolution) — the two are different problems: Phase 11
is about not over-trusting weak *explicit* evidence, this is about *implicit*
reference resolution, which needs actual conversation-state design work.
**Update (Phase 39):** ordinal list-index references ("the second doctor
you mentioned", against a still-on-screen list) are now handled —
`resolve_ordinal_doctor_ref`.
**Update (Phase 41):** general subject-position pronoun resolution to the
most-recently-discussed doctor(s) is now handled too —
`classify_doctor_pronoun_reference`, including correct ambiguity handling
("Priya and Omar" both shown → "did you mean X or Y") and a family-
relation-antecedent guard ("my daughter... can she" doesn't hijack). What
remains open: pronoun/reference resolution for antecedents that *aren't*
a doctor (a previously-mentioned service, insurance plan, or specialty —
"can I get that with my HMO" after discussing a specific plan), and
object-position or possessive pronoun forms not covered by the current
classifier's trigger set. Still open, narrower than before.

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

## SaaS Lifecycle Phases

A separate initiative from the chatbot-pipeline phases above — OTP
verification, SaaS onboarding, transactional email, and Paddle billing
lifecycle. Tracked with its own `SaaS-Phase N` numbering rather than folded
into the chatbot's `Phase N` sequence above, since the two subsystems are
unrelated and sharing a counter would make both histories harder to read.
Same working agreement applies (see below): one phase, one focus, report
before starting the next, every found-but-not-fixed item gets a line here.

Repo audit before any of this started (full detail, not reproduced here):
staff auth/JWT/multi-tenant membership (`ClinicStaff`, already many-to-many),
roles, audit logging (`AuditLog`/`write_audit`), password reset/invite/
activation (`StaffAuthToken`), and Paddle webhook signature verification +
idempotency were all already real and correct. The actual gaps were
narrower than the original request assumed: a generic OTP provider
abstraction (existing OTP was patient-booking-specific, no Twilio Verify
usage), rate limiting (absent everywhere), HTML email templates (plain-text
only), reaction to Paddle `transaction.*` events (logged, never applied),
and a `DemoRequest`-shaped model that turned out to already exist as
`ClinicApplication`.

### ✅ SaaS-Phase 1 — Verification provider abstraction

**What changed.** New `apps/verification/` app: `VerificationService` (the
only entry point application code calls) → `OTPProvider` ABC → `MockOTPProvider`
/ `TwilioVerifyProvider`, selected by `OTP_PROVIDER=mock|twilio`. Both
providers return one shared `VerificationOutcome` vocabulary
(`VerificationStatus`: pending/approved/canceled/max_attempts_reached/
expired/failed/already_verified/not_found/invalid_recipient), so callers
never branch on which provider is active — proved by an AST-based test that
`service.py` never imports `twilio` or a concrete provider class.

**Root cause / design notes.**
- `TwilioVerifyProvider` uses the real Verify API (`Verifications`/
  `VerificationCheck`), not a hand-rolled state machine, per Twilio's own
  guidance. No local state — the Verify Service is authoritative. Auth via
  `TWILIO_API_KEY`/`TWILIO_API_SECRET` (Twilio's recommended production
  credential shape), separate from the legacy `TWILIO_AUTH_TOKEN` used by
  the existing raw-SMS sender.
- `MockOTPProvider` fully simulates the lifecycle locally (hashed-at-rest
  codes, expiry, resend cooldown, max attempts, already-verified, not-found)
  since there's no real backend behind it. Codes are always random
  (`secrets.randbelow`) — never a fixed value. Plaintext code
  (`dev_code`) is populated only when `settings.DEBUG` is True; Twilio never
  populates it at all.
- Wrong code vs. technical failure are kept distinct: an incorrect code with
  attempts remaining returns `PENDING` (matches Twilio's real semantics);
  `FAILED` is reserved for actual provider/API errors. An unrecognized
  Twilio status maps to `FAILED`, never `APPROVED` — the one direction that
  can't be silently wrong.
- Phone normalization requires E.164 (`+`-prefixed) input and refuses to
  guess a country code for a bare local number — this codebase already has
  one incident this session of a parser guessing wrong (see Phase 12/13
  above); this abstraction doesn't repeat that mistake.
- Hardening follow-up: added `apps/verification/checks.py`, a Django system
  check (`verification.E001`) so `OTP_PROVIDER=twilio` with incomplete
  credentials fails loudly at `check`/`runserver`/`migrate` time instead of
  silently degrading every request to `FAILED`. Verified directly (not just
  by test): partial config (this machine's real `.env`, missing only
  `TWILIO_VERIFY_SERVICE_SID`) is correctly caught and named.

**Deliberately not done in this phase:** no endpoint wired yet (added in
Phase 2 below), no UI, no rate limiting, patient-booking OTP
(`apps.chatbot.services.otp_service`) and the raw-SMS sender
(`apps.chatbot.integrations.twilio_sms`) both left untouched — confirmed via
empty `git diff` both before and after.

**Tests.** `apps/verification/tests/` — 50/50 (mock provider lifecycle
matrix, Twilio provider against a mocked HTTP boundary — no real Twilio
calls anywhere in the suite, provider-parity contract tests through
`VerificationService`, system-check tests). Full regression
(`apps.chatbot.tests apps.knowledge.tests apps.accounts apps.billing
apps.clinics`) unchanged at 506/506.

**Found but not fixed:** a pre-existing, unrelated `accounts.AuditAction`
migration drift (confirmed via `git stash` to exist independent of this
work) — folded into and resolved by SaaS-Phase 2's own accounts migration
below, since that phase touched the same field.

### ✅ SaaS-Phase 2 — Verification API + rate limiting + audit wiring

**What changed.** Real endpoints: `POST /api/v1/verification/{send,resend,
check}` (`apps/api/verification/router.py`), staff-authenticated
(`auth=staff_jwt_auth`) — today's use case is an already-logged-in user
confirming their own phone number, since in this codebase `accept-invite`
already issues a JWT before any "optional phone verification" step would
run. On a genuine `APPROVED` outcome where `to` matches the caller's own
`User.phone_number`, sets a new `User.phone_verified_at` field (mirrors the
existing `email_verified_at` pattern exactly, including a `phone_verified`
property). New `core/ratelimit.py` — a small cache-backed limiter
(`check_rate_limit(scope, identifier, limit=, window_seconds=)`, raises
`HttpError(429)`) — applied to the three new verification endpoints
(per-recipient and per-IP) and retrofitted onto the existing `/auth/login`
(per-email + per-IP), `/auth/register` (per-IP), and `/auth/forgot-password`
(per-email + per-IP) endpoints, none of which had any throttling before.
Three new `AuditAction` values (`phone_verify_requested/approved/failed`)
wired through the existing `write_audit()` helper — failures are only
logged for a *terminal* bad outcome (expired/max-attempts/not-found/failed),
not for every wrong-code keystroke (`PENDING`), to keep the audit log
meaningful rather than noisy.

**Root cause / design notes.**
- Rate limiter is intentionally minimal: `django.core.cache.cache` with an
  atomic `incr`/`set` pattern, no new dependency. Honest limitation
  documented in the module's own docstring: correct today (default
  `LocMemCache`, single process); a production deployment running multiple
  worker processes/machines needs a shared cache backend (Redis/memcached)
  for the counts to be accurate across workers — a deployment config change,
  not a code change.
- The 429 error message never echoes the rate-limited identifier (email/
  phone/IP) — covered by a dedicated test — so a 429 response can't be used
  to enumerate which emails/numbers exist.
- Generated the `accounts` migration for `phone_verified_at`; Django folded
  the pre-existing `AuditAction` choices drift (flagged, not fixed, in
  Phase 1) into the same migration since it's the same field — confirmed
  `makemigrations --check` is clean repo-wide afterward.
- Real bugs caught and fixed during this phase's own test-writing, not
  shipped: router tests initially used `**self.headers` instead of Django
  test client's `headers=self.headers` kwarg, so every "authenticated" call
  was silently hitting the endpoint unauthenticated (401) and the
  assertions were vacuous; a rate-limit test asserted per-email isolation
  without accounting for the *also-real* per-IP limiter interfering, since
  the test client reuses one IP for every request — fixed by simulating
  distinct `X-Forwarded-For` values per email in that one test, not by
  weakening either limiter.

**Tests.** `apps/accounts/tests.py` (new `AuthEndpointRateLimitTests`),
`apps/verification/tests/test_router.py` (new — auth gating, audit writes,
`phone_verified_at` side effect including the *no*-side-effect-on-a-
different-number case, cross-tenant audit scoping, rate limiting, invalid
recipient never 500s), `core/tests.py` (new `RateLimitTests`). 78/78 for
`apps.accounts apps.verification core`. Full regression
(`apps.chatbot.tests apps.knowledge.tests apps.billing apps.clinics`)
unchanged at 499/499.

**Found but not fixed:** none new this phase.

**Recommended next:** SaaS-Phase 3 (demo request → Super Admin, reusing
`ClinicApplication` rather than a new model).

### ✅ SaaS-Phase 3 — Demo request → Super Admin

**What changed.** The marketing site's "Book a Demo" form
(`/contact`) was a UI-only stub with no backend ("This form is UI-only until
a contact API exists"). Rather than building the `DemoRequest` model/status-
machine/admin-queue the original request sketched, extended the existing
`ClinicApplication` — confirmed field-for-field structurally identical
(name/email/phone/org name/message → status → super-admin review →
convert). Added `ClinicApplicationSource` (`get_started`/`demo_request`) and
made `plan_slug` optional (blank for demo requests, which don't ask the
visitor to commit to a plan). `POST /applications` now accepts `source` and
only requires a valid `plan_slug` for the `get_started` source.
`approve_application` gained an optional `plan_slug` override on
`ApproveApplicationIn`, required when the application itself has none.
`/contact` is now a real, controlled form posting to the same endpoint
`/get-started` already uses. Super Admin's applications list
(`dashboard/platform/applications`) shows a "Demo request" badge and, for a
plan-less application, a plan picker (reusing the existing `usePlans()`
hook) that must be filled before "Approve & provision" is enabled.

New internal-team notification email
(`NotificationService.send_demo_request_notification_email`, new
`PLATFORM_NOTIFICATION_EMAIL` setting, deep-links to
`/dashboard/platform/applications` — there's no per-record detail route, so
that's the accurate link) fires once per new application (not on
resubmission), for both sources — this is the one genuinely new email in
this phase, since the existing `send_application_received_email` is
applicant-facing. Demo requests get a distinct, lighter applicant
confirmation (`send_demo_request_received_email` — "We received your demo
request", not "application") rather than reusing the plan-application
copy.

**Root cause / design notes.**
- Silently skips (with a log line, not an error) when
  `PLATFORM_NOTIFICATION_EMAIL` is unset — matches this codebase's existing
  pattern for every other optional integration (Twilio/Paddle unconfigured
  in local dev).
- An unrecognized `source` value falls back to `get_started` rather than
  rejecting the request — a demo-request-shaped submission from an old
  cached frontend build should never suddenly 400.
- `approve_application`'s error message when no plan is resolvable
  (`payload.plan_slug` and `app.plan_slug` both empty) names the actual
  problem ("this application has no plan yet — provide plan_slug") instead
  of the pre-existing generic "plan no longer available" message, which
  would have been actively misleading for a demo request that never had a
  plan to begin with.

**Tests.** `apps/api/applications/tests.py` (new `DemoRequestSubmissionTests`
— no-plan-required, plan_slug ignored/cleared for demo requests, correct
applicant email copy per source, internal notification sent/skipped/not-
duplicated-on-resubmission), `apps/api/platform/tests.py` (new
`DemoRequestApprovalTests` — approval blocked without a plan with a clear
message, approval succeeds with a plan override, unknown override plan
rejected). 612/612 across
`apps.chatbot.tests apps.knowledge.tests apps.accounts apps.verification
apps.billing apps.clinics apps.api.applications apps.api.platform core`.
`npx tsc --noEmit` clean except one pre-existing, unrelated error in
`insurance-card.tsx` (confirmed via empty `git status` on that file — not
touched this phase).

**Found but not fixed:** the pre-existing `insurance-card.tsx:13` possibly-
null `plan` TypeScript error noted above — unrelated to this phase, not
fixed to keep the change scoped.

**Recommended next:** SaaS-Phase 4 (email templates + billing lifecycle
emails — the biggest remaining gap, since email today is plain-text only
and Paddle's `transaction.*` events are logged but never acted on).

### ✅ SaaS-Phase 4 — Email templates + billing lifecycle emails

**What changed.** New `apps/notifications/templating.py::render_email()` —
one Django HTML template per email (`templates/emails/*.html`, extending a
shared `base.html` layout) renders both parts; plain text is *derived* from
the HTML via `strip_tags()` rather than hand-maintained as a second copy
that drifts. `NotificationService.send_templated_email()` is purely
additive on top of the existing `send_email`/`EmailProvider` machinery —
every pre-existing plain-text email method is untouched. Six new billing
lifecycle emails (`send_payment_successful_email`,
`send_payment_failed_email`, `send_payment_past_due_email`,
`send_payment_recovered_email`, `send_subscription_paused_email`,
`send_subscription_canceled_email`), each with its own template.

Wired into `apps/billing/services/webhook_processor.py`, the one real gap
found in Phase 1's audit of otherwise-correct webhook handling:
`transaction.completed` → payment successful, `transaction.payment_failed`
→ payment failed, `transaction.past_due` → payment past due (a new
`_apply_transaction_event`, resolving the Subscription via the existing
`_find_subscription` without mutating it — transaction events are money-
movement notifications, `subscription.*` events already own state).
`_apply_subscription_event` now captures `previous_status` before mutation
and a new `_send_status_transition_email` fires on genuine transitions
only: →paused, →canceled, and specifically `past_due→active` as "payment
recovered" (not any other transition into active, e.g. trialing→active,
which isn't a recovery).

**Root cause / design notes.**
- Deliberately did **not** wire `transaction.paid` — Paddle can fire both
  `completed` and `paid` for one real payment, and `completed` is what
  Paddle's own docs point to for fulfillment confirmation; wiring both
  risks double-notifying a customer for a single payment.
- Duplicate webhook delivery must not double-send. `_apply_subscription_event`
  was already safe (its own `occurred_at` staleness guard returns before
  reaching the save+email code on a redelivery). `_apply_transaction_event`
  has no state of its own to check against, so it takes an explicit
  `send_email: bool` from the caller — `not already_processed`, using the
  exact boolean `process_webhook` already computes for its own idempotency
  check. Verified with a real duplicate-delivery test (same signed body,
  same `event_id`, posted twice) — exactly one email.
- Clinic-id resolution in `process_webhook` was scoped to `event_type.
  startswith("subscription.")` only; extended to also cover `"transaction."`
  so `BillingEvent.clinic_id` gets backfilled for transaction events too,
  reusing the existing (already-correct) `_find_subscription`/
  `_resolve_clinic_id` machinery rather than writing a second lookup path.
- Templates use inline styles (email clients don't reliably support
  external/`<style>`-block CSS) and a table-based layout for client
  compatibility; brand colors pulled from the actual frontend
  (`--navy: #0b0e2e`, `--primary: #5b21b6` in `globals.css`) rather than
  invented. CTA links point at `/dashboard/billing` (confirmed to exist).
  No unsubscribe link — every one of these is transactional, not marketing,
  per the original request's own instruction not to conflate the two.

**Tests.** `apps/notifications/tests.py` (new — every template renders
valid HTML with a clean derived text part, missing context doesn't crash,
CTA button correctly present/absent), `apps/billing/tests/
test_lifecycle_emails.py` (new — one test per transaction event type, the
deliberate `transaction.paid` non-wiring, unresolvable customer / no-email
clinic graceful skips, every transition case including the two "must NOT
send" cases: redundant same-status redelivery, and trialing→active not
mislabeled as a recovery). 630/630 across `apps.chatbot.tests
apps.knowledge.tests apps.accounts apps.verification apps.billing
apps.clinics apps.api.applications apps.api.platform apps.notifications
core`.

**Found but not fixed:** none new this phase.

**Recommended next:** SaaS-Phase 5 (billing state machine — an explicit
internal access-state layer, e.g. a grace period between `past_due` and
actually restricting access, distinct from Paddle's own subscription
status).

### ✅ SaaS-Phase 5 — Billing state machine: grace period + suspension

**What changed.** New `Subscription.access_status` property (`active` /
`grace_period` / `suspended`) and `grace_period_ends_at`, plus a new
`grace_period_started_at` field — deliberately a separate concept from
`Subscription.status` (Paddle's own vocabulary), per the module's own
docstring on why the two are decoupled. `_apply_subscription_event` now
starts the grace timer the instant a subscription first enters `past_due`
and clears it the instant it leaves (recovered or canceled) — never reset
by a redundant redelivery of the same status.

The enforcement discovery for this phase: `apps/api/auth/deps.py` already
had a `_blocked_status()` helper checked on **every** authenticated
request via `StaffJWTAuth.authenticate()`/`PatientJWTAuth.authenticate()`
(not just at login) — for `Clinic.status` suspension/cancellation only.
Extended it with `_billing_blocked()`, which checks
`subscription.access_status == SUSPENDED`, gracefully returning "not
blocked" when a clinic has no `Subscription` row at all (super-admin-
created clinics, seed/demo data never had one). This gets billing
enforcement across the whole staff dashboard *and* the patient booking
widget for free, correctly, without adding a new gate.

`GET /billing/subscription` now also returns `access_status` and
`grace_period_ends_at` so the billing UI can show "we couldn't process
your payment, you're still active while we retry" instead of a hard
failure the moment status flips to `past_due` (Part 18's own example).
One new email: `send_account_reactivated_email`, fired specifically on a
`paused→active` transition — distinct from `send_payment_recovered_email`
(Phase 4), which is specifically `past_due→active` and uses payment-
failure framing that would be wrong copy for "someone just resumed a
voluntarily-paused subscription."

**A real regression was caught by this phase's own full-suite run, not
shipped:** the first version of `access_status` mapped
`SubscriptionStatus.INCOMPLETE` (the normal state for a clinic mid-
onboarding, before Paddle confirms checkout — not a billing failure) into
`SUSPENDED`, alongside `PAUSED`/`CANCELED`. Wired into `_billing_blocked`,
this meant a clinic owner would get 401'd out of their own account while
trying to *complete* onboarding, before they'd ever had a chance to pay —
caught by `apps.clinics.tests.OnboardingBillingGateTests.
test_complete_with_pending_subscription_stays_onboarding` failing with 401
instead of 200 on the very next full-regression run. Root cause: conflating
"never started paying" with "was paying, then stopped" under one status.
Fixed by grouping `INCOMPLETE` with `ACTIVE`/`TRIALING` in `access_status`
— access control for the onboarding stage is `Clinic.status` staying
`onboarding` (a separate, pre-existing gate); this property must only
reflect an actual billing *problem*. A regression test was added at both
the property level (`test_incomplete_is_active_not_suspended`) and the
enforcement level (`test_incomplete_subscription_is_not_blocked`), not
just the one that happened to catch it.

**Root cause / design notes.**
- Grace-period exhaustion is evaluated **lazily**, at read time
  (`access_status` computes against `timezone.now()` on every access), not
  by a scheduled job flipping a stored value — this codebase has no
  Celery/cron runner. This is an honest, deliberate limitation: there is no
  way to send a proactive "your account has just been suspended" email at
  the exact moment a grace period lapses without one. The customer already
  received the payment-failed/past-due emails (Phase 4) before that point,
  and will see a clear 403 the next time they try to use the app after
  expiry — but no new email fires at the exact suspension instant. Flagged
  here rather than built around with a hack.
- `Clinic.status` itself is deliberately **not** mutated by billing
  suspension — kept as two separate signals (`Clinic.status` is admin-
  controlled, with its own meaning; `Subscription.access_status` is
  billing-derived) rather than one flipping the other and risking drift
  between an admin's manual suspension and a billing-driven one.
- `GET /billing/subscription` reports `access_status="suspended"` for a
  clinic with **no** `Subscription` row at all — deliberately inconsistent
  with `_billing_blocked`'s more lenient "never blocks" stance for that
  same case, and deliberately so: one is a display concern ("tell the
  truth about billing status"), the other an operational safety net ("don't
  lock out a clinic we forgot to bill"). Documented inline at both sites.

**Tests.** `apps/billing/tests/test_access_status.py` (new — every
`SubscriptionStatus` → `access_status` mapping including the INCOMPLETE
regression, grace-window boundary cases, configurable grace days, real
webhook-driven timer set/clear/no-redundant-reset, the `/billing/
subscription` endpoint's exposed fields), `apps/billing/tests/
test_lifecycle_emails.py` (new `account_reactivated` case, confirming it's
distinct from `payment_recovered`), `apps/accounts/tests.py` (new
`BillingAccessEnforcementTests` — every status against a real
`GET /auth/me` call, the no-subscription safety net, the INCOMPLETE
regression, and confirming `Clinic.status` suspension keeps working
independently). 654/654 across `apps.chatbot.tests apps.knowledge.tests
apps.accounts apps.verification apps.billing apps.clinics
apps.api.applications apps.api.platform apps.notifications core`
(caught the regression above, then confirmed clean after the fix).

**Found but not fixed:** the lazy-evaluation "no proactive suspension
email" gap described above — would need a scheduled-job mechanism (this
repo has none) to close properly; not building one as a side effect of
this phase.

**Recommended next:** SaaS-Phase 6 (onboarding: knowledge-base upload
formats beyond PDF, readiness-checklist copy).

### ✅ SaaS-Phase 6 — Knowledge-base upload formats; onboarding UX verified, not changed

**What changed.** `apps/knowledge`'s upload pipeline accepts CSV/XLSX
alongside PDF. `apps/knowledge/pipeline/extract.py` gained
`_extract_tabular_pages()`, reusing `apps.importer.services.parser`'s
`parse_csv`/`parse_xlsx` (headers, rows, BOM/encoding handling, malformed-
file guards) rather than a second parsing implementation — a genuinely
different downstream use than the importer's own (rows become readable
`"Header: value"` text blocks for chunking/embedding, not mapped entity
fields), but the same parsing layer. The whole table becomes one `PageText`
"page"; downstream chunking already handles splitting long text, exactly as
it does for a long PDF page — no changes needed anywhere past extraction.
`document_service.ALLOWED_FILE_TYPES` extended to `{pdf, csv, xlsx}`.
Frontend: `UploadDropzone` (already generic — `accept`/`validate`/`hint`
props existed from prior work) wired with a new
`isKnowledgeUploadFile`/`ACCEPTED_KNOWLEDGE_UPLOAD` in
`features/knowledge/utils.ts` at the one real call site
(`dashboard/knowledge/page.tsx`).

**Root cause / design notes.**
- Legacy `.xls` (binary Excel) is deliberately unsupported — matches
  `apps.importer`'s own existing scope decision (`SUPPORTED_FILE_TYPES =
  {"csv", "xlsx"}`), and adding a second Excel-parsing library for an aging
  format nothing in this codebase already needs isn't justified.
- **Investigated, found already correct, changed nothing:** the plan called
  for improving onboarding-readiness-checklist copy per the original
  request's example ("Missing: • Clinic hours • Doctor availability...").
  Direct inspection of `frontend/src/features/onboarding/steps/
  review-step.tsx` and `components/dashboard/setup-checklist.tsx` found
  this already fully built — both render the complete missing-items list
  from `GET /me/onboarding-status`'s checklist (not a single error
  message), each item links directly to the step that fixes it, and the
  wizard's "Go to Dashboard" button is `disabled` until every required item
  is ready. The backend's single-item `_MISSING_MESSAGES`/400 path in
  `complete_onboarding` is consequently unreachable from the actual UI (the
  button can't be clicked while anything is missing) — left as-is, since
  it's a reasonable defensive fallback for a direct API call and improving
  its wording further has no user-facing effect through any real screen in
  this app.

**Tests.** `apps/knowledge/tests/test_extract_tabular.py` (new — CSV/XLSX
→ readable text blocks, empty values omitted, header-only/malformed-
encoding/missing-file/unsupported-type all raise `ExtractionError` cleanly,
never leak a raw exception type), `apps/knowledge/tests/
test_upload_file_types.py` (new — CSV/XLSX/PDF accepted, unsupported types
and legacy XLS still rejected with a clear message). 667/667 across
`apps.chatbot.tests apps.knowledge.tests apps.accounts apps.verification
apps.billing apps.clinics apps.api.applications apps.api.platform
apps.notifications core`. `npx tsc --noEmit` clean except the same one
pre-existing, unrelated `insurance-card.tsx` error noted in SaaS-Phase 3.

**Found but not fixed:** none new this phase.

**Recommended next:** SaaS-Phase 7 (observability + security hardening —
structured logging for the event list from the original request, confirm
no secret is ever logged, `.env.example` sweep).

### ✅ SaaS-Phase 7 — Observability + security hardening

**What changed.** Structured `logger.info(...)` lines added for every event
in the original request's observability list that wasn't already covered:
`demo_request_created` (`apps/api/applications/router.py`, on first
creation only, matching the existing dedup-on-resubmission pattern),
`subscription_created` + `invitation_sent` (`apps/api/platform/router.py`
`approve_application`), `document_processing_started` (join the pre-
existing `completed`/`failed` lines, renamed to the same `document_
processing_*` vocabulary for consistency/greppability), `subscription_
past_due` / `subscription_suspended` / `subscription_reactivated`
(`webhook_processor.py::_send_status_transition_email` — logs the
transition even for a clinic with no email on file, since logging and
notifying are separate concerns; this was a real gap, since the function
previously returned before doing anything at all when `clinic.email` was
empty), `payment_succeeded` / `payment_failed` / `payment_past_due`
(`_apply_transaction_event`, gated on the same `send_email` dedup flag so
a duplicate webhook redelivery doesn't double-log either). Also added the
one missing `AuditLog` entry for an event that already had an `AuditAction`
enum value defined but was never actually written anywhere:
`DOCUMENT_UPLOAD`, now written in `apps/api/knowledge/router.py`'s upload
endpoint (previously only a plain `logger.info` in the service layer, not
in the Super Admin's audit trail).

Already covered before this phase, confirmed by direct inspection rather
than assumed: `account_created` (`REGISTER` audit), `account_activated`
(`EMAIL_VERIFY`/`INVITE_ACCEPTED` audit), `password_reset_requested`
(`PASSWORD_RESET` audit), `otp_requested`/`otp_verified`/`otp_failed`
(`PHONE_VERIFY_*` audit, SaaS-Phase 2).

**Security verification, not just logging additions:**
- Every `logger.*` call across all SaaS-lifecycle code (verification,
  billing, applications, platform, knowledge, notifications, auth) read
  and manually checked, one by one — none logs a password, OTP code,
  activation/invite/reset token, or Twilio/Paddle secret. The two
  `exc.code` log calls in `TwilioVerifyProvider` log Twilio's numeric
  *error* code (e.g. `20404`), never request/response payloads or
  credentials. `webhook_processor.py::verify_signature` — the one function
  in this codebase that directly handles a webhook secret — has zero
  logging calls of any kind.
- `.env.example` cross-checked against every setting actually declared in
  `config/settings/base.py` from this session's work — found and fixed two
  real gaps: `BILLING_GRACE_PERIOD_DAYS` and `PLATFORM_NOTIFICATION_EMAIL`
  were usable settings with no documented example. While in there, also
  documented three settings that predate this session but had no
  `.env.example` entry at all (`FRONTEND_URL`, `DEFAULT_FROM_EMAIL`, the
  `EMAIL_*` SMTP block) — genuinely in scope for "a full sweep," not
  unrelated cleanup, since this session's own new billing/notification
  emails depend on `FRONTEND_URL` being set correctly. Scanned the file for
  anything real-looking (`sk-`, Twilio SID/key patterns, Paddle key
  patterns) — clean, placeholders/blank only.
- Secret rotation for the previously-flagged Twilio dev credentials is the
  user's own action (confirmed explicitly), not performed here.

**Tests.** No new dedicated test suite — these are additive `logger.info`
calls with no behavioral change, verified by running the full regression
unchanged rather than writing tests that assert on log message strings
(low value for the churn risk of pinning log wording). 667/667 across
`apps.chatbot.tests apps.knowledge.tests apps.accounts apps.verification
apps.billing apps.clinics apps.api.applications apps.api.platform
apps.notifications core` — identical count to SaaS-Phase 6, confirming
zero behavioral change.

**Found but not fixed:** none new this phase.

**Recommended next:** SaaS-Phase 8 (one end-to-end journey test spanning
demo request → approval → invite → activation → onboarding → document
upload → verification → billing lifecycle; then a full, honestly-reported
regression baseline for the whole initiative).

### ✅ SaaS-Phase 8 — End-to-end journey test + final regression baseline

**What changed.** One real, HTTP-driven `TestCase`
(`apps/billing/tests/test_e2e_saas_lifecycle.py`) walking the entire chain
built across SaaS-Phases 1–7 in chronological order: demo request submitted
→ Super Admin approves with a plan override → owner accepts the invite →
onboarding checklist filled in and `complete_onboarding` correctly defers
to the billing step (real Subscription, not yet paid) → CSV knowledge-base
upload → phone verification via the mock provider → Paddle confirms the
subscription and the clinic activates → a successful payment → a failed
payment enters grace period (access still granted) → payment recovers →
subscription is canceled and the owner's own JWT is locked out on its very
next use. Every step goes through the real endpoint, not direct model
manipulation, except the onboarding prerequisites themselves
(doctor/service/hours/availability), which are pre-existing, separately-
tested CRUD — what this test verifies is that the onboarding-readiness
read path correctly sees them, not that creating a doctor works.

**Deliberately not extended into a real patient booking flow** — that's a
separate, pre-existing, already-extensively-tested subsystem (the chatbot-
pipeline phases earlier in this file). Re-deriving it here would test
something this initiative didn't touch, not something it did; the E2E test
says so explicitly in its own module docstring rather than silently
narrowing scope.

**Final baseline for the whole SaaS-lifecycle initiative** (SaaS-Phases
1–8, `apps.chatbot.tests apps.knowledge.tests apps.accounts
apps.verification apps.billing apps.clinics apps.api.applications
apps.api.platform apps.notifications core`):

- **668/668 tests pass.** Zero pre-existing failures folded in — every
  number reported in every phase above was reproduced fresh at that
  phase's own boundary, not carried forward as an assumption.
- `python manage.py makemigrations --check` — clean, zero pending
  migrations across the whole repo (this also resolved a pre-existing,
  unrelated `accounts.AuditAction` migration drift, found in SaaS-Phase 1
  and folded into SaaS-Phase 2's own migration since it touched the same
  field).
- Chatbot eval battery: **674/682 (98.8%)** — identical to the baseline
  recorded before this initiative started, with the same two known, pre-
  existing, unrelated failures (`squeeze me in`, pediatric slang).
  Confirms zero regression to the chatbot pipeline despite eight phases of
  unrelated work in the same repository.
- `npx tsc --noEmit` — clean except one pre-existing, unrelated error in
  `insurance-card.tsx:13` (confirmed via empty `git status` on that file at
  every phase boundary it was checked — never touched by this work).
- One real regression was caught and fixed during this initiative, not
  shipped: SaaS-Phase 5's `access_status` originally suspended
  `SubscriptionStatus.INCOMPLETE` (the normal pre-payment onboarding
  state), which would have 401'd clinic owners out of their own accounts
  mid-checkout. Caught by this repo's own full-regression discipline
  (`apps.clinics.tests.OnboardingBillingGateTests`), root-caused, fixed
  with a one-line change, and given regression tests at both the property
  and enforcement layers — documented in full under SaaS-Phase 5 above.

**Known limitations, stated plainly (not fixed as a side effect of this
phase):**
- No scheduled-job/cron infrastructure exists anywhere in this repo. Grace-
  period exhaustion is evaluated lazily at request time; there is no
  proactive "your account was just suspended" email at the exact moment a
  grace period lapses (SaaS-Phase 5).
- `PLATFORM_NOTIFICATION_EMAIL`/SMTP are both optional and silently
  no-op when unset in local dev — by design, matching the rest of this
  codebase's optional-integration pattern, but worth remembering when
  testing the demo-request flow manually.
- Rate limiting (`core/ratelimit.py`) is correct under the default
  single-process `LocMemCache`; a real multi-worker production deployment
  needs a shared cache backend (Redis/memcached) for the counts to be
  accurate across workers — a deployment configuration change, not a code
  change (SaaS-Phase 2).
- Legacy `.xls` (binary Excel) is not supported for knowledge-base uploads,
  matching `apps.importer`'s own existing scope decision (SaaS-Phase 6).
- `TwilioVerifyProvider` is built and fully tested against a mocked HTTP
  boundary but has never been exercised against the real Twilio Verify API
  — this project's own Twilio account is a trial account that can't
  reliably send real Verify SMS yet (stated as a known constraint at the
  very start of this initiative).

**Manual testing checklist** (for exercising this locally with a browser,
not just the automated suite):
1. `OTP_PROVIDER=mock` (default) — visit `/contact`, submit a demo request,
   confirm it appears in Super Admin → Applications with a "Demo request"
   badge and no plan shown.
2. Approve it, picking a plan from the picker that appears specifically
   because it has none — confirm a Clinic + invite email (console output in
   dev) appear.
3. Accept the invite, set a password, log in, complete onboarding —
   confirm the clinic lands on the billing step rather than activating
   immediately (a real Subscription exists, unpaid).
4. Upload a `.csv` file on the Knowledge Base page — confirm it's accepted
   and processes to "Indexed".
5. From an authenticated session, `POST /api/v1/verification/send` then
   `/check` with the `dev_code` from the response (visible because `OTP_
   PROVIDER=mock` and `DEBUG=True`) — confirm `approved`.
6. Simulate the Paddle webhooks in this phase's E2E test manually (or with
   real sandbox Paddle checkout) to watch the clinic activate, then a
   `past_due` → `active` cycle, then `canceled` — confirm the owner's
   session is rejected on the next request after cancellation.

**This closes the SaaS Lifecycle initiative (SaaS-Phases 1–8) as
originally scoped in the plan approved at the start.** Further work
(the dormant knowledge-base multi-format edge cases, a scheduled-job layer
for proactive suspension emails, real Twilio Verify sandbox testing) is
each its own future phase, not started here.

---

## Frontend — Clinic Dashboard + Analytics insight wall ✅

**What changed.** Clinic Dashboard (`/dashboard`) and Analytics
(`/dashboard/analytics`) were rebuilt off the generic white square KPI
cards and thin CSS bars. They now share an insight card language:
rectangular 10px-radius cards, royal-purple ink/wash contrast (first of
four is ink; middle of three is ink), a Notion-style clinician
illustration on the welcome banner, custom SVG area-line / rounded-bar /
concentric-ring charts, and illustrated metric glyphs. Data shown is
still the real appointment + analytics payloads — no invented series.

**Files.** `frontend/src/components/dashboard/insights/*` (new primitives),
`frontend/src/app/dashboard/page.tsx`,
`frontend/src/app/dashboard/analytics/page.tsx`,
`frontend/src/features/analytics/model-mix.tsx` (thicker purple mix bars),
`frontend/src/app/globals.css` (`--insight-*` tokens under
`.theme-instrument`). Platform overview still uses the older StatCard.

**Found but not fixed.** Change/cancel-plan still needs a clinic whose
subscription was created by real Paddle.js Checkout (placeholder IDs were
cleared from local rows earlier). Platform AI usage page was not restyled
in this pass.

**Recommended next.** Walk one clinic through sandbox Checkout if
change/cancel needs to be demoed; optionally restyle platform overview
with the same insight primitives.

---

## Frontend — Clinic dashboard analytics system (recharts + backend aggregation) ✅

**Objective.** Replace the homemade SVG insight-wall charts with a
tenant-scoped, backend-aggregated analytics system: reusable recharts
components, a lightweight `/dashboard` overview, a detailed
`/dashboard/analytics` page, and at most one supporting chart on
operational CRUD pages.

**What changed.** Dashboard overview now answers “how is my clinic
doing?” with four KPIs (conversations, appointments, patients, completed
appointments — not a fabricated conversion rate), a dual-series
conversations/appointments line, an appointment-status donut, specialty
bars, then the existing recent-conversations / upcoming-appointments
lists. `/dashboard/analytics` is the detailed page (conversations,
chatbot performance KPIs, appointments, patients, providers, AI usage,
knowledge growth). Operational pages gained 0–1 supporting charts plus
small KPI strips. Clinic / business-hours / settings / profile were left
chart-free.

**Data definitions (implemented).** All queries are `clinic_id = clinic_from(request)`. Daily buckets use `TruncDate(..., tzinfo=clinic.timezone)`.

| Metric | Source | Date field | Aggregation |
| --- | --- | --- | --- |
| Conversation volume | `ChatSession` | `created_at` | COUNT by clinic-local day |
| Appointments created | `Appointment` | `created_at` | COUNT by clinic-local day |
| Appointment status | `Appointment` | `created_at` in window | COUNT by `status` (all six statuses, including zeros). Total matches appointments booked in the same window. |
| Specialty / provider / service / insurance bars | `Appointment` → doctor specialties / doctor / service / insurance_plan | `start_time` | COUNT, top 5, distinct for specialties |
| New patients | `Patient` | `created_at` | COUNT |
| Returning patients | `Appointment` whose `patient.created_at` is before the window | appointment `created_at` | COUNT DISTINCT patient |
| Patient frequency | `Appointment` lifetime | n/a | patients with 1 / 2 / 3 / 4+ visits |
| Avg messages / duration | `ChatMessage` / `ChatSession.closed_at or last_active_at` | session `created_at` in window | COUNT / AVG |
| Outcomes | `ChatSession.status` | `created_at` | closed / escalated / active — **not** “resolved” |
| AI usage | `AIUsageLog` via existing `summarize_usage` | `created_at` | SUM tokens, COUNT calls; cost only for super-admin |
| Knowledge growth | `Document` (not soft-deleted) | `created_at` | COUNT by day |

**Intentionally not implemented.** Booking conversion and booking funnel (only the final `Appointment` row exists — no intent/slot/started events). “Resolved” vs closed. AI vs human involvement. Provider utilization (schedules/leaves exist but the available-time denominator is not accurate enough). SaaS revenue-over-time (`BillingEvent` payload is JSON, no first-class amount). Charts on clinic / business-hours / settings / profile.

**Database.** No new models, migrations, or indexes. Existing `(clinic, created_at)` / `(clinic, status, start_time)` indexes cover the aggregations.

**API.** `GET /api/v1/analytics/overview?range=`, `GET /api/v1/analytics/insights?range=`, `GET /api/v1/analytics/breakdown?dimension=&range=`. Existing `GET /api/v1/analytics?days=` (AI usage) unchanged. Ranges: `7d|30d|90d|6m|12m`, default `30d`. Super admin entering a clinic via `X-Tenant-ID` sees that clinic only.

**Frontend.** `frontend/src/components/dashboard/charts/*` (recharts wrappers, ChartCard, DateRangeSelector, MetricStat, empty/skeleton/error). Pages: dashboard, analytics, doctors, appointments, patients, services, specialties, insurance, conversations (KPI strip only), chatbot, knowledge (KPIs from the document list). `frontend/next.config.ts` sets `turbopack.root` so `next build` does not pick the parent-repo lockfile as the app root.

**Tests actually run.**
- `python manage.py test apps.api.analytics.tests apps.ai.tests --keepdb` → **28/28 OK** (tenant isolation, empty clinic, ranges 7d/30d/90d/6m/12m, timezone bucket, super-admin X-Tenant-ID, unauthenticated 401, owner-without-clinic 400, status counts, specialty/service/insurance breakdown, AI cost stripped for clinic owner).
- `frontend/node_modules/.bin/tsc --noEmit` → pass.
- `npm run build` (Next 15.5.22 turbopack) → pass after `turbopack.root` (48 static pages).
- Playwright spec added at `frontend/e2e/dashboard-analytics.spec.ts`. Chromium could not be launched here: Playwright 1.62 does not support Chromium on macOS 12 (`npx playwright install chromium` → “does not support chromium on mac12”). Spec is in place for a machine that can install the browser.
- Live API smoke (Apex Dental staff JWT): `GET /analytics/overview?range=30d` returned 295 conversations / 30 appointments / 13 patients / 31 daily points; unauthenticated request → 401.

**Found but not fixed.** Platform `/dashboard/platform` overview still uses the older StatCard language. Appointment-by-specialty counts an appointment once per linked specialty (distinct per specialty name, not per visit globally). Patient frequency is lifetime, not windowed. Playwright Chromium is not installable on this macOS 12 host with the current `@playwright/test` 1.62.

---

## Frontend — Glass month booking calendar ✅

**Objective.** Replace the dashboard’s leftover “Upcoming appointments” list (and the unused GitHub-heatmap `ActivityCalendar`) with a month-only frosted-glass calendar: clinic-local day marks for how many visits are booked, a professional today highlight, and the next upcoming visits with initial avatars. No week/day/range chrome.

**What changed.** `GET /api/v1/analytics/calendar?year=&month=` returns clinic-local day counts (pending/confirmed/completed/rescheduled only — cancelled and no-show do not mark the day) plus the next 3 upcoming visits (`start_time >= now`, pending/confirmed/rescheduled) with patient and doctor names. The dashboard right column is now `BookingCalendarCard`: photo wash + iOS-style `backdrop-blur` overlay, Sunday-start month grid, coral pips (1–3) for booking density, white filled today circle, glass upcoming rows with overlapping initials. Month chevrons only.

**Files.** `apps/api/analytics/ranges.py` (`parse_year_month`), `apps/api/analytics/service.py` (`calendar_month`), `apps/api/analytics/router.py`, `apps/api/analytics/tests.py`; `frontend/src/components/dashboard/charts/booking-calendar-card.tsx`, `frontend/public/dashboard/calendar-wash.png`, types/hooks/service, `frontend/src/app/dashboard/page.tsx`, e2e heading updated to “Bookings”.

**Found but not fixed.** `ActivityCalendar` is unused on any page (still exported). Background PNG is ~1.6MB (local asset, no Unsplash runtime). Playwright Chromium still cannot install on this macOS 12 host.

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

---

## Knowledge — OpenAI embeddings (replace local BGE) ✅

**Objective.** Stop loading `BAAI/bge-base-en-v1.5` on `runserver`; use the
OpenAI embeddings API (`text-embedding-3-small`, 1536-d) that was already
implemented behind `EMBEDDING_PROVIDER`.

**What changed.** Defaults and `.env` now select `openai` /
`text-embedding-3-small` / `1536`. pgvector column migrated 768 → 1536
(old BGE vectors cannot be cast — they were nulled). Indexed documents
were set back to `chunked` so they must be reindexed. Warm-up is a no-op
for OpenAI, so runserver no longer prints `Loading local embedding model`.

**Files.** `config/settings/base.py`, `.env.example`,
`apps/knowledge/models.py`, `apps/knowledge/migrations/0010_embedding_dimensions_1536.py`,
knowledge embedding tests, `ARCHITECTURE.md` §9,
`docs/rag/EMBEDDING-PROVIDER-SWITCH.md`.

**Found but not fixed.** Existing clinic documents need a reindex
(`POST /api/v1/documents/{id}/reindex`) before RAG search works again —
vectors were intentionally cleared. Chat completions were already OpenAI;
only the embedding backend changed.

**Follow-up (Phase 43).** The local provider and `sentence-transformers`
dep were still in the tree after this switch and broke a lean AWS install.
Removed entirely — OpenAI is the only embedding backend.

**Follow-up (Apex load).** The clinic still failed in the browser after
the backfill. Two Apex-specific problems, both now cleared:

1. Widget `avatar_url` was a ~126KB data-URI (gold seal). Every dashboard
   and embed load fetched it with `/widget/config`. Cleared; user will
   upload a new knowledge doc themselves.
2. Apex knowledge rows (live SOP + deleted seed txt, 8 chunks) were
   deleted so a fresh upload can re-embed cleanly.

Also: a stale staff JWT on `/embed/...` used to 401 `/auth/me` and bounce
the public embed to `/login`. Redirect now only happens on portal routes
(`/dashboard`, `/onboarding`, `/select-tenant`).

---

## ✅ Pre-deployment pass — debug-dump hardening, query efficiency (EC2 t3.micro, 1GB RAM)

**Objective.** User is deploying to a resource-constrained EC2 t3.micro
(1GB RAM total). Asked for three things: clear out local log/JSON debug
artifacts, confirm the dependency footprint won't strain the box (the
526MB PyTorch/sentence-transformers concern), and audit for N+1/redundant
DB queries in the request-hot paths before deploying.

**Dependency footprint — already resolved, not new work here.** Confirmed
`apps/knowledge/embeddings/local.py` is gone and `EMBEDDING_PROVIDER`
defaults to `openai` with a hard error on `local` — this is Phase 43's
own follow-up above, already done and tested (39/39 knowledge). Confirmed
directly: `torch`/`sentence-transformers` are not in any `requirements/
*.txt` (only present in this dev machine's `.venv` as an untracked
leftover, 573MB, never installed by a fresh `pip install -r requirements/
production.txt`). No numpy/pandas anywhere in `apps/` either — the
"apps.importer SIGFPE" note in CLAUDE.md is leftover from that same old
local-embedding install, not a real prod dependency. Nothing to fix.

**Debug-dump hardening.** `pipeline_debug_enabled()`
(`apps/chatbot/pipeline_debug.py`) now hard-gates on `settings.DEBUG`
before checking `DEBUG_CHAT_PIPELINE` — previously only the env var
controlled it, so a local `.env` copied to production would flood stdout
and write a JSON trace file per chat message on a disk-constrained box.
`production.py` already hardcodes `DEBUG = False` (not env-overridable),
so this was already low-risk, but it's a cheap defense-in-depth guard.
Deleted 2,686 stale debug JSON files (29MB) from `logs/chat/` — already
gitignored/untracked, pure local accumulation from this session's testing.

**Query-efficiency audit.** Delegated a codebase-wide audit (chat/booking/
widget/analytics/dashboard hot paths) to a research agent, then verified
each finding against the actual source before fixing — 8 of 9 findings
were real and fixed; 1 (doctor-catalog fetched independently 2-3x per
chat message across `engine.py`/`resolvers.py`) is real but lower-impact
and deferred, see below.

1. **`_doctor_options` (booking wizard "Choose a doctor" step) —
   confirmed up to ~1,400 queries per render.** `_next_available_slot()`
   was called once per candidate doctor (up to 20), each looping 14 days
   and re-querying schedule/leave/appointments/holds *for that one doctor
   alone* every day. Measured the exact mechanism live via
   `manage.py shell`, not estimated. Fixed with a new
   `compute_next_available_slots()` (`apps/chatbot/booking/slots.py`) that
   batches all 4 lookups (schedule, leave, appointments, holds) across
   *all* candidate doctors and the *whole* 14-day horizon into a small
   constant number of queries, then walks the horizon in pure Python per
   doctor. Extracted the slot-boundary math shared with the existing
   single-day `compute_slots_for_day` into a new pure (no-query)
   `_expand_day_slots` helper so both paths stay correct from one
   implementation instead of two. Also added `active_holds_for_range`
   (one scan of active sessions bucketed by date) and had the existing
   `active_holds_for_date` delegate to it. Regression test asserts query
   count is *identical* for 2 vs 8 doctors (not just "smaller") —
   `test_booking_query_efficiency.py`.
2. **`prefetch_related` silently defeated by `.filter()`.**
   `doctor_to_dict()` (`sql_tool/utils.py`) called
   `doc.services.filter(is_deleted=False)` — a `.filter()` on an
   already-prefetched related manager clones the queryset and re-queries
   instead of hitting the prefetch cache, a well-known Django gotcha.
   Fired on every `DOCTOR_SEARCH` chat message and on every row of
   finding #1. Fixed: `.all()` + a Python `if not s.is_deleted` filter,
   which does use the cache.
3. **`list_specialties` — per-row `.count()` N+1.** Fixed with
   `.annotate(doctor_count=Count("doctors", filter=Q(...)))`, one query
   instead of up to 20.
4. **`_service_options` — same per-row `.count()` N+1, plus no cap at
   all** on the base queryset (every other list handler in this codebase
   already bounds itself). Same `annotate(Count(...))` fix, plus a `[:100]`
   cap (the frontend does client-side search over the full "all" list, so
   this stays a full catalog, just not an unbounded one).
5. **Specialty re-fetched after already being loaded.**
   `resolve_specialty_for_service()` (`nlu/resolvers.py`) loaded a full
   `Specialty` row (including `.name`) but returned only the id;
   `engine.py` then called `_specialty_display_name()` — a second
   `.get()` purely to re-fetch `.name`. Fixed by splitting the query core
   into `resolve_specialty_object_for_service()` (returns the row) with
   `resolve_specialty_for_service()` as a thin id-only wrapper (kept
   unchanged for existing callers/tests); `engine.py` now calls the
   object-returning version directly and `_specialty_display_name` is
   deleted (dead code once the redundant call was gone). Updated one test
   mock (`test_tiered_router.py`) that was patching the now-bypassed
   wrapper.
6. **Chat history fetched twice in one request.** `engine.py` loaded
   `_load_history(session, limit=6)` for NLU context near the top of
   `process()`, then `_generate_response()` independently loaded
   `_load_history(session, limit=2)` again for the same session — same
   rows, different limit. Threaded the already-loaded `recent_turns`
   through `_compose_from_plan` → `_generate_response` (new optional
   parameter each), which now slices `recent_turns[-2:]` instead of
   re-querying; falls back to a fresh load only if not provided.
7. **Doctors dashboard list — classic unprefetched M2M N+1.**
   `apps/api/doctors/router.py::list_doctors` had no
   `select_related`/`prefetch_related`; `_serialize()` called
   `doctor.specialties.values_list(...)` / `doctor.services.values_list(
   ...)` per row — and, same gotcha as #2, `.values_list()` on a
   prefetched manager also bypasses the cache. Fixed both: added
   `.prefetch_related("specialties", "services")` to the list queryset,
   and changed `_serialize` to `.all()` + Python id extraction (works
   correctly whether or not the manager was prefetched, so the single-
   object create/retrieve/update call sites are unaffected). No test
   coverage existed for this endpoint at all — added
   `apps/doctors/tests.py::ListDoctorsQueryCountTests` (correctness +
   flat-query-count-across-page-size).
8. **Analytics `/insights` — the exact same aggregate query run twice.**
   `insights()` calls `overview()` (which already computes
   `patients_returning` via a specific filter chain) and then, right
   after, re-runs the *identical* filter chain a second time under a
   different key name. Fixed: reuse `base["summary"]["patients_returning"]`.

**Deferred, not fixed — real but lower priority.** Doctor-catalog data is
independently fetched up to 3x for the same clinic on any doctor-related
chat turn: `build_doctor_catalog` (unconditional, every message),
`resolve_entities`→`_match_doctor`, and `resolve_doctor_candidates` each
run their own query (`engine.py:93,177,354`; `nlu/resolvers.py`). Real and
confirmed reachable together, but each query is already small/bounded
(`.only()`, capped), so the win (2 queries saved per doctor-message) is
much smaller than #1 was, and the correct fix — threading one fetched
roster through all three call sites — touches NLU-resolver code this
session has repeatedly found to be correctness-sensitive (Phase 41).
Deferred rather than rushed.

**Also found, unrelated, not fixed — pre-existing test date-flake.**
`apps/appointments/tests/factories.py` hardcodes
`SLOT_START = datetime(2026, 8, 20, 15, 0, tzinfo=LA)`. Now that this
session's in-fiction "today" has advanced to 2026-08-28, that fixture is
in the past, and `compute_slots_for_day`'s (correct) "don't offer a slot
that's already passed" filter now excludes it — breaking 4 tests in
`apps/appointments/tests/` that assert a slot at that fixed time is
offered/not-offered. **Confirmed independent of this phase's changes**:
reproduced identically by temporarily restoring the pre-edit `slots.py`
and re-running — same 4 failures, same error, before touching anything.
Same shape as the Phase 9A date-flake this file's own working agreement
points to as the bar for handling this correctly: not fixed here (out of
this phase's stated scope — query efficiency, not test fixtures), flagged
plainly instead of silently working around it.

**Files changed:** `apps/chatbot/pipeline_debug.py` (+test),
`apps/chatbot/booking/slots.py` (`_expand_day_slots`,
`compute_next_available_slots`, `active_holds_for_range`),
`apps/chatbot/booking/serializers.py` (`_doctor_options`,
`_service_options`, removed dead `_next_available_slot`),
`apps/chatbot/sql_tool/utils.py` (`doctor_to_dict`),
`apps/chatbot/sql_tool/handlers/doctors.py` (`list_specialties`),
`apps/chatbot/nlu/resolvers.py` (`resolve_specialty_object_for_service`),
`apps/chatbot/engine.py` (`_specialty_display_name` removed,
`recent_turns` threaded through), `apps/api/doctors/router.py`
(`list_doctors`, `_serialize`), `apps/api/analytics/service.py`
(`insights`), `apps/chatbot/tests/test_tiered_router.py` (patch target
fix), new `apps/chatbot/tests/test_booking_query_efficiency.py` (5 tests),
new tests in `apps/doctors/tests.py` (2 tests).

**Tests:** 8 new/updated. `apps.chatbot.tests apps.knowledge.tests
apps.doctors.tests apps.api.analytics apps.api.doctors apps.api.widget.tests
apps.patients.tests` — **734/734**. `apps.appointments.tests` — 77/81, the
4 failures being the pre-existing, independently-confirmed date-flake
above (not this phase's). Eval: **674/682 (98.8%)**, unchanged (no
NLU/routing logic touched — the resolvers.py change only restructures
which function returns what, same query, same matching behavior).

**Recommended next steps (not started):** bump/relativize the
`apps/appointments/tests/factories.py` `SLOT_START` fixture so it doesn't
go stale again; consider the deferred doctor-catalog dedup above if further
tightening the chat hot path matters; for the actual EC2 deploy, size
gunicorn's worker count deliberately (`--workers 2`, not the
`(2×cpu)+1` default — a 1GB box can't afford 3 workers, `--max-requests`
to recycle any slow memory creep) — no gunicorn/Procfile config exists in
this repo yet to audit directly, this is an operational recommendation
for whatever process manager is used on the box.

---

## ✅ SMS/phone verification disabled — email-only, for now

**Objective.** Deliberate product decision: disable phone-number OTP
verification everywhere (chatbot booking, the separate "verify to view my
appointments" chat card, and any dashboard table showing a patient's
phone), keep the code intact for a later per-clinic re-enable ("future
thing," not a ripout), and prove the resulting email-only flow actually
works end to end with a real inbox.

**Root cause / mechanism.** `verification_mode` (`sms | email |
sms_or_email | none`) and the `sms_otp` feature flag
(`apps.clinics.features.DEFAULT_FEATURE_FLAGS`) already existed as the
two config knobs gating `otp_service.resolve_otp_channel()` — the single
enforcement point every OTP send/verify goes through. Both defaulted to
SMS-favoring (`verification_mode="sms"`, `sms_otp=True`). Flipped both
defaults (`sms_otp=False`, `verification_mode="email"`) rather than
deleting the sms/sms_or_email code paths — `resolve_otp_channel` still
correctly serves an explicit `sms` request if a clinic later re-enables
`sms_otp=True`, verified by a dedicated test.

**Found live, not guessed:** all 6 existing clinics in this DB (including
`horizon-family-care`, the one under active manual testing) had
`verification_mode` **and** `sms_otp` explicitly stored in
`WidgetSettings.configuration` — code-level defaults alone would not have
touched them. Backfilled all 6 rows (`verification_mode` → `"email"`,
`sms_otp` → `False`) directly; the frontend already only ever sends
`email` now regardless, so `resolve_otp_channel`'s request-honoring logic
would have papered over a stale stored `"sms"` mode anyway, but leaving
it stale would have shown wrong copy anywhere the raw value is displayed
(dashboard Settings page).

**Changes:**
1. **Backend defaults** (defense in depth, 6 call sites):
   `apps/clinics/features.py` (`DEFAULT_FEATURE_FLAGS.sms_otp`,
   `default_widget_configuration()`, `get_verification_mode()`'s
   fallback + legacy-boolean branch), `apps/chatbot/booking/config.py`,
   `apps/chatbot/booking/service.py`, `apps/chatbot/booking/
   serializers.py` (×2), `apps/api/widget/booking_router.py`.
2. **Booking wizard `DetailsStep`** (`booking-wizard.tsx`): the contact
   field is now a plain `<Input type="email">` — "Email address" only,
   `classifyContact(..., "email")` instead of the old accept-either
   `"sms_or_email"` mode. No UI path to type a phone number remains.
3. **`VerifyIdentity`** (`verify-identity.tsx` — the separate chat-inline
   card for "view/cancel my appointment," distinct from the booking
   wizard): dropped the phone/email method toggle and `PhoneInput`
   entirely; email-only, same as the wizard. `PhoneInput`
   (`chat/components/phone-input.tsx`) had no other callers — deleted.
4. **Dashboard tables/detail views showing a phone number:**
   patients list (`dashboard/patients/page.tsx`) — dropped the Phone
   column (left the staff-facing add/edit-patient dialog's phone field
   alone — that's manual CRM data entry, not chatbot verification, out
   of this change's scope). Conversations inbox
   (`dashboard/conversations/page.tsx` + backend `ConversationSummaryOut`
   /`_serialize_conversation` in `apps/api/chat/`) — swapped `phone` for
   `email` in the schema, the detail-panel subtitle, and the search
   filter (`patient__phone__icontains` → `patient__email__icontains`).
   Settings page's display fallback updated too.

**Explicitly not touched:** `Patient.phone`/`Patient.email` model fields
(no migration — phone stays a real, populated column for legacy/manual-
entry patients; the OTP path already had a synthetic-placeholder-phone
mechanism for email-only patients from earlier work, reused as-is, not
new). Twilio integration, `TwilioSMSProvider`, and every `sms`/
`sms_or_email` branch in `resolve_otp_channel`/`send_otp` — dormant, not
deleted.

**Tests:** `test_booking_otp_review_flow.py`'s `StandardOtpBookingFlowTests`
+ `EditDetailsAtReviewTests` (9 tests, written earlier this session) relied
on the old SMS default with no explicit override — updated to submit/
verify via email, matching the new standard path (same pattern as Phase
42A's own DOB-field test updates: a deliberate default change, not a bug).
New `test_sms_otp_disabled.py` (10 tests) locks in the actual
`resolve_otp_channel` behavior matrix: default clinic → email; explicit
`sms` request under default `email` mode → gracefully falls back to email
(not an error); a clinic with a stale stored `verification_mode="sms"` →
still blocked from real SMS by the `sms_otp` flag; a clinic that
explicitly re-enables `sms_otp=True` → SMS still genuinely works (proves
this is a flip-able default, not vestigial code); `send_otp` with
phone-only and no email → correctly rejected ("Email is required"), since
nothing in the UI can produce that request anymore but the backend must
still fail closed. New tests in `apps/api/chat/tests_conversations.py`
(email display + email search). `apps.chatbot.tests apps.api.chat
apps.doctors.tests apps.patients.tests apps.api.widget.tests apps.clinics
apps.knowledge.tests` — **771/772** (the 1 failure is
`test_the_earliest_opening_is_not_offered_as_a_substitute`, confirmed
unrelated: a second date-boundary flake, same family as the `SLOT_START`
one above — this session's wall-clock crossed from August into September
mid-session, and the test's own "tomorrow" check now collides with the
word "September" already present in an unrelated schedule-horizon
message; not caused by anything in this change, flagged rather than
fixed, out of scope). Eval **674/682 (98.8%)**, unchanged. Frontend
`tsc --noEmit` and `eslint` clean on every touched file.

**Live end-to-end verification (not simulated):** ran the full
start → submit_details(email only) → send_otp → verify_otp →
confirm_review pipeline via `manage.py shell` (not `manage.py test`, so
the real `ResendEmailProvider` fires, confirmed by the
`EMAIL provider=resend` log line rather than `provider=console`) against
a throwaway clinic with **no explicit verification config at all** —
proving the bare defaults work, not just an explicitly-configured
clinic. Sent a real OTP to `alihamxa366@gmail.com`; **the user
independently confirmed receiving code `499536` in their actual inbox**,
matching this run's `debug_code` exactly. The resulting `Patient` row's
`phone` field held the synthetic `email:<hash>` placeholder — confirmed
no real phone number was ever collected or stored. Throwaway
clinic/doctor/appointment/patient data deleted afterward.

**Known limitations:** the staff-facing "Add/Edit patient" dialog in the
dashboard still has a required phone field (`apps/api/patients/schemas.py`
presumably still requires it) — deliberately left alone as manual CRM
data entry, a different concern from chatbot verification; flagged in
case the user wants that changed too later.
