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

## Working agreement (why phases stay this small)

- One phase, one focus. Report before starting the next.
- Every "found this too" gets a line in this file, not a same-turn fix,
  unless the phase's own scope already covers it.
- Every bug fix reproduces the failure first (with a real number/trace
  where possible — see 9A/9B above for what that looks like), then makes
  the smallest change, then adds a regression test that would have caught
  it.
- Full command reference: see `CLAUDE.md`.
