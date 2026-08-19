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
