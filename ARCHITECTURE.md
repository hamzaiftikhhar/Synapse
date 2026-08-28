# Synapse Chatbot — Architecture (source of truth)

Scope: this document describes the **chatbot request pipeline** as it actually
exists in code today, verified by direct source reading during the routing
refactor (2026-08). `docs/Synapse-Architecture-Document.md` and
`docs/PROJECT-GUIDE.md` are earlier planning documents (July 2026) — where
they conflict with this file on chatbot internals, this file is current;
they may still be accurate for other subsystems (billing, onboarding,
importer, etc.) this document doesn't cover.

**Read this before inspecting chatbot source.** It exists so you don't have
to re-derive the pipeline from scratch every session. If something here
turns out to be wrong, fix the code/this doc together — don't silently work
around a stale description.

## 1. Request lifecycle

```
Patient message
      │
      ▼
ChatEngine.process()                          apps/chatbot/engine.py
      │
      ├─ 1. Catalogs — build_document_catalog(), build_service_catalog()
      ├─ 2. Conversation state — load_timeline() / detect_recovery()
      ├─ 3. NLU — IntentEntityService.analyze() → NLUResult
      ├─ 4. Heuristics — apply_routing_heuristics() (entity hints, phatic/
      │      emergency trust, service_filter_mode — NOT lane ownership)
      ├─ 5. Entity resolution — resolve_entities() (DB, doctor/specialty/
      │      service/insurance name → id)
      ├─ 5a. Pending uptake (Phase 16) — if the previous turn recorded an
      │      offer and this message is a whole-turn yes/no, rewrite NLU to
      │      execute that offer *before* sensors/planner see it
      ├─ 6. Sensors — compute_message_sensors() → MessageSensors
      ├─ 7. Planner — build_planner_facts() + build_execution_plan()
      │      → ExecutionPlan
      └─ 8. Executor — runs what the ExecutionPlan says (SQL / vector /
             booking / direct), composes the reply, builds ui_meta
      │
      ▼
EngineResult → API → patient
```

## 2. The core rule this refactor enforces

**The Small LLM (NLU) produces semantics. Python (the planner) decides
execution. SQL handlers execute what the planner authorized — they do not
re-decide.** This rule was NOT true before this refactor (Phase 0 baseline
found an unknown-doctor booking that showed a refusal message *and* launched
the booking wizard simultaneously, because `ui_meta.py` re-derived booking
eligibility from raw intent instead of trusting the planner). Phases 1–8
progressively closed these gaps. **It is not fully true yet** — see §7 for
the one confirmed remaining violation (service-existence questions
sometimes still reach vector/RAG instead of SQL).

### 2a. Dates are a special case of that rule (Phase 13)

**The LLM may interpret. Deterministic code decides.** Dates are not an NLU
string that downstream layers each re-read; they are a cross-layer domain
object resolved exactly once, in `apps/chatbot/temporal.py`:

```
message → scan_temporal_expressions()  ─┐
        → entity_extract (weekday/rel) ─┼→ rank by TemporalPrecision,
        → NLU entities (grounded-check)─┘  then groundedness
                                        → TemporalQuery (canonical)
                                        → horizon validation
                                        → SQL scan │ reply text │ chips │ booking
```

`TemporalQuery` is the single source of truth. Nothing downstream re-derives
a date from the patient's words — not `formatter.py`, not `ui_meta.py`, and
not `BookingService`, which consumed its own `parse_natural_date(dates[0])`
until Phase 13. Ranking is by precision (EXPLICIT_DATE > MONTH > WEEKDAY >
RELATIVE > FLEXIBLE) and never by entity order, so "16 oct friday" means
October 16 and the weekday is only a consistency check.

Statuses `PAST`, `UNRESOLVED`, `AMBIGUOUS`, and `BEYOND_HORIZON` are
*authoritative refusals*: `ChatEngine._temporal_refusal_text()` returns them
verbatim before any lane can reach the response LLM, and `ui_meta.py` renders
no chips for them. The horizon comes from the clinic's configured
`date_horizon_days` (default 30), never a hard-coded window.

`UNSPECIFIED` is the established "no date constraint — forward-scan"
status. Flexible phrases (`earliest`, `asap`, `next available`,
`instantly`, `immediately`, `right away`, …) use that status, including
when they appear only in the message and NLU extracted no date entity.
They must not be treated as an unreadable constraint.
`yesterday` is `PAST`. A new temporal status is not required for either.
`instantly` / `immediately` / `right away` are also `is_asap_request` so
booking seeds today the same way `asap` does. They are **not** date-extract
patterns — extracting them would rescue an unreadable date
(`coming januray instantly` stays `UNRESOLVED`).

### 2b. A new booking utterance only inherits pins it supplied (Phase 15)

`BookingService._apply_prefill` (`apps/chatbot/booking/service.py`) drops a
leftover service when this call names a doctor and not a service
(`stale_service`), and drops a leftover held slot / DETAILS / OTP / REVIEW
commitment when this call names a doctor or service without an explicit
`slot_start` (`stale_commitment`). `start()` forwards `slot_start` into
`_apply_prefill` so a real chip tap is not treated as leftover REVIEW.

`ui_meta.build_ui_meta` injects `last_service` only when this turn named a
service, or named neither doctor nor service (true continuation). Naming a
doctor without a service must not carry Adult Cleaning into the next draft.
`last_doctor` / `last_specialty` still inject on a non-generic restart.

## 3. NLU — `apps/chatbot/nlu/`

**The system prompt is already minimal and semantic-only** — verified by
reading `apps/chatbot/nlu/prompts.py` directly, not inferred:

```
Fields: intent, secondary_intents, confidence, entities, is_emergency,
        is_off_topic, clarification_needed, clarification_question,
        can_respond_directly, reasoning_short, service_filter_mode, topic
Deprecated (optional, ignored for routing): needs_sql, needs_vector,
        needs_llm, sql_tool, document_needed
```

The LLM is **not asked** to produce execution fields. If you see
`nlu_result.needs_vector == True` in a pipeline-debug trace, that is very
likely `apply_plan_to_nlu(nlu, exec_plan)` (engine.py, called ~line 294,
*before* the debug trace is captured ~line 551) writing the **planner's**
decision back onto the NLU object for legacy-consumer compatibility — not
proof the LLM emitted it. Don't misdiagnose this as "NLU contract
pollution" without checking `apply_plan_to_nlu` call order first; this was
already investigated and settled (see ROADMAP.md, Phase 9 background).

**Classifier chain** (`nlu/classifier.py::classify_message`):
```
safety rules → phatic/fast rules → [optional strong rules] →
primary provider → openai_fallback (mini) → gemini → rules_fallback/clarify
```
Bounded by `NLU_TOTAL_BUDGET_SECONDS` (default 5.0) across the whole
provider loop — see §8.

**Rule tiers are not equally active in production.** `nlu/rules.py`'s
`try_rule_classify(..., tier=...)` has four tiers: `safety`/`fast` are
"always safe for pre-LLM" and run unconditionally; `strong` is explicitly
"legacy semantic regex (opt-in via `NLU_RULES_BEFORE_LLM`)" —
**`NLU_RULES_BEFORE_LLM` defaults to `False`**, so every `strong`-tier
pattern (informal booking phrasing like "squeeze me in", doctor+
availability regex, etc.) is dormant in a default deployment and every
matching message falls through to the LLM instead. **`eval/runner.py`
calls `tier="strong"` unconditionally** (no `NLU_RULES_BEFORE_LLM` check at
all) — so eval passing a case does not prove production handles it; it
only proves the regex itself is correct. Confirmed concretely: the
`adversarial_booking_slang_squeeze` eval case ("squeeze me in") passes via
the dormant strong-tier rule in eval, but the same phrasing reaches the
real LLM in production. A near-identical, newly-found production bug
("hope me in"/"slip me in" reaching the LLM and getting misclassified as
`faq`) was fixed by adding a *new* pattern to the `fast` tier specifically
(always active), not by touching `NLU_RULES_BEFORE_LLM` or the existing
dormant `strong`-tier rule — see ROADMAP.md's "Off-roadmap" entry for why.
The rest of the `strong` tier has not been individually audited for
whether it should also move to `fast`, be deleted, or stay opt-in — treat
any `strong`-tier-only behavior as unverified in production until checked.

**Entity resolution** (`nlu/resolvers.py`, DB-backed, fuzzy):
- `resolve_doctor_candidates` / `resolve_doctor_from_text` — confidence-banded (high/medium/low) doctor matching. Token-fuzzy only runs on `_name_evidence_tokens` (Phase 20): honorific-only "Schedule me with Dr." is `unknown`, not a weak match on `"schedule"`. Exact last-name / full-name substring still resolves.
- `sanitize_entities` / `clean_doctor_name` (Phase 18) — peel temporal/ASAP tokens the model glued onto `doctor_name` (`"maya yesterday"` → `"maya"`). Grounding alone is not enough because both tokens appear in the message.
- `_match_specialty`, `_match_insurance`, `_match_service` — per-entity DB fuzzy resolvers, feed `NLUResult.resolved_ids`.

## 4. Planner — `apps/chatbot/planner.py`

Pure, no I/O (this is an enforced convention — DB/network calls belong to
the engine, never the planner).

- **`MessageSensors`** (`compute_message_sensors()`) — the single shared,
  I/O-free sensor computation. Called by *both* `engine.py` (production) and
  `eval/runner.py` (the 682-case offline battery), so the two can't
  independently drift. Fields: `matched_services`, `matched_service_ids`,
  `service_hit`, `knowledge_q`, `booking_commit`, `is_booking_intent`,
  `soft_medical`, `matched_docs`, `has_catalog`, `doc_match`, `degraded`,
  `doctor_ranking_request`, `instruction_injection`,
  `doctor_availability_query`, `urgent_availability`, `policy` (full
  `ConfidencePolicyResult`), `nlu` (post-confidence-policy NLUResult — use
  the *returned* one, the input may be stale).
- **`PlannerFacts`** (`build_planner_facts()`) — assembles sensor output +
  DB-dependent facts (`unknown_doctor_requested`, `doctor_followup` — these
  need a real clinic/session, so `compute_message_sensors` can't produce
  them) into the planner's input. As of Phase 7, does **not** carry
  `booking_commit`, `service_hit`, `prefer_vector`, `confidence_band`, or
  `matched_doc_ids` — those were computed, serialized, and never read by
  anything; removed.
- **`ExecutionPlan`** (`build_execution_plan()`) — the actual decision:
  `emergency`, `clarify`, `direct`/`direct_mode`, `booking`, `sql_tasks`,
  `vector_tasks`, `use_response_llm`, `fallback_vector_tasks` (pre-authorized
  SQL→vector escalation, see §6), `resolved_service_ids` (see §5). Derived:
  `.primary_lane` → `Lane`, `.to_route()` → `Route`.
- **`resolve_plan_after_sql(plan, *, sql_found)`** — the *only* legitimate
  way a plan changes after SQL executes. Activates `fallback_vector_tasks`
  into real `vector_tasks` when SQL came back empty. Called once, by the
  engine; the engine reassigns its `exec_plan` local to the result so every
  downstream read (booking prep, compose, ui_meta, logging, EngineResult)
  sees the resolved plan with no second variable to go stale.
- **`choose_plan()`** — legacy compatibility wrapper (`PlannerDecision`
  projection). Internally calls `build_planner_facts` + `build_execution_plan`
  same as production. Kept because `eval/runner.py` and several tests still
  call it directly; its signature is intentionally frozen (deprecated params
  like `needs_vector`, `booking_commit`, `service_hit`, `prefer_vector`,
  `matched_doc_ids`, `confidence_band` are accepted-then-`del`eted so
  existing callers don't need updating when `PlannerFacts` sheds a field).

## 5. Service resolution — three algorithms, one authority

There are three genuinely different service-matching implementations, none
of them redundant (audited in Phase 6 — do not delete on sight):

| Algorithm | Where | Input | Purpose |
|---|---|---|---|
| `match_services_in_message()` | `routing/signals.py` | raw message + pre-fetched catalog (`build_service_catalog`, capped at 40) | **Canonical resolver.** Feeds `MessageSensors.matched_service_ids` → `ExecutionPlan.resolved_service_ids`. |
| `_match_service()` | `nlu/resolvers.py` | one NLU-extracted entity string + live DB query (fuzzy, threshold 0.55) | Feeds `NLUResult.resolved_ids.service_id`. Highest-priority signal in `services_offered()`. |
| `_match_services_strict()` | `sql_tool/handlers/services.py` | raw message + **uncapped** live DB query | Legacy last-resort fallback. **Not deletable yet** — `build_service_catalog`'s `limit=40` means a clinic with >40 active services has services invisible to the canonical resolver; this is the only thing that still finds them. Proven by `LegacyMatcherCatalogLimitTests`. Full reasoning: `docs/decisions/0002-keep-legacy-service-matcher.md`. |

**Precedence inside `services_offered()`** (`sql_tool/handlers/services.py`),
by `service_filter_mode`:
- **named** mode: `resolved_ids.service_id` → raw `entities.service` icontains → `resolved_service_ids`/`_match_services_strict` fallback.
- **category** mode (Phase 5): `resolved_ids.service_id` → hardcoded category phrase → `resolved_service_ids`/`_match_services_strict` fallback. Category mode deliberately does **not** fall back to raw `entities.service` icontains — that string is LLM-extracted and often a paraphrase (e.g. "laser treatment"), so `icontains` against it can silently match zero rows even when a resolver above/below it has a real answer. This was a real, shipped bug; fixed in Phase 5.
- **none** mode: no filter, full browse (by design — list/browse queries never collapse to one SKU).

`SQLContext.resolved_service_ids` is threaded from `ExecutionPlan` through
`SQLTool.run_tasks()` (the planner-driven path). `SQLTool.run()` (legacy,
only used by `test_sql_tool.py` and dead in production — `ChatEngine._run_sql`
is never called) does not populate it, so it always falls to the legacy
matcher — by design, not an oversight.

## 6. SQL vs. Vector — current boundary, and its known gap

**SQL** (`sql_tool/handlers/`) is the source of truth for structured facts:
doctors, specialties, services, pricing, insurance, hours, location,
availability, patient appointments.

**Vector/RAG** (`response_llm.py::synthesize_clinic_reply`, backed by
`apps/knowledge`) is for unstructured clinic documents: policies, post-op
instructions, membership terms, arrival instructions.

**Hybrid escalation** (`resolve_plan_after_sql`, Phase 2): a plan that is
SQL-only pre-authorizes a `fallback_vector_tasks` entry at planning time
(never invented ad hoc after the fact) for intents in `HYBRID_SQL_INTENTS`
(`routing/lanes.py`) or knowledge-shaped messages. If the SQL task comes
back empty, the engine activates the fallback and runs vector + Large LLM.
**Exception (Phase 17):** `availability` is never pre-authorized. An empty
day is a resolved answer; RAG must not invent slots. Insurance / services /
FAQ empty still may hybrid.

**Known, unfixed gap (target of Phase 10):** "Do you have X?" / "Do you
offer X?" / "Are you sure you have X?" phrasings do not reliably classify
into the same SQL-triggering bucket as "How much is X?" / "What services do
you offer?" — verified against a real transcript where a clinic without
HydraFacial gave four *different* answers across four phrasings of the same
question, only converging on the correct "we don't offer that" for the
pricing-shaped phrasing. Root cause is intent/mode classification, **not**
RAG being allowed to override SQL facts — when the SQL task *does* run,
`response_llm.py`'s prompt builder (`_user_block`, ~line 220) already
includes SQL results and the LLM respects them correctly. The bug is
upstream: some existence-question phrasings never attach a SQL task at all
and go pure-vector, where a generic "cosmetic procedures deposit policy"
document gets misread as confirming the specific service exists.

## 7. RAG degraded states (target of Phase 9C, not yet fixed)

`_compose_from_plan` / `_generate_response` (`engine.py`) call
`empty_rag_reply()` (`response_llm.py`) from **four** different branches:
genuinely-empty `vector_rows`, budget-exhausted-before-LLM-call, LLM
timeout, LLM error. Only the first is actually "nothing found" — the other
three can have real, relevant `vector_rows` (verified: a real transcript
turn had 3 hits at 0.61/0.58/0.50 similarity, then said "I couldn't find
clinic-specific information" because the budget ran out before the LLM call,
not because retrieval failed). Not yet fixed — planned as Phase 9C.

## 8. NLU provider budget (Phase 9A, done)

`classify_message`'s provider loop used to let each attempt claim its own
full timeout independently (primary 3.5s + openai_fallback 3.0s + gemini
3.0s → up to ~9.5–10.9s observed on a real failure chain). Fixed: one
`total_budget` (`NLU_TOTAL_BUDGET_SECONDS`, default 5.0) measured from loop
start; each attempt gets `min(per_provider_cap, remaining)` — **cap-then-
remaining, not an even upfront split** (the primary keeps its full 3.5s
when it's the only/first attempt, so today's normal ~2.3s successful
classifications are unaffected; only the failure-chain worst case is
bounded). A skipped (circuit-open) provider costs no budget and doesn't
trip its own breaker further. Full reasoning for cap-then-remaining vs. an
even split: `docs/decisions/0001-nlu-budget-cap-then-remaining.md`.

**Verified emergent behavior** (not a bug, confirmed by test): during a
*sustained* total outage, `openai` and `openai_fallback` fail every turn
and both open their breakers after 5 consecutive failures (the shared
`LLM_CIRCUIT_FAILURE_THRESHOLD`). `gemini`, third in the chain, is starved
of budget during those turns and hasn't failed yet — so it briefly absorbs
the whole freed-up budget alone, until it too opens 5 turns later. After
that, all three are skipped and `classify_message` returns near-instantly
(rules fallback) rather than continuing to pay latency turn after turn.

**Known limitation, not fixed:** `nlu/deadline.py::run_with_deadline` wraps
calls in a 4-worker `ThreadPoolExecutor`. On timeout it calls
`future.cancel()`, which is a no-op once a future is `RUNNING` (only works
while still `PENDING`) — the abandoned HTTP call keeps running on its
worker thread until the *provider's own* transport timeout fires. Under
concurrent load, enough abandoned calls can saturate the 4 workers, and a
newly-submitted attempt can burn its whole slice just waiting to be
scheduled. The caller-side ceiling still holds either way, but the budget
buys fewer real attempts than it looks like under saturation. Deferred —
see ROADMAP.md.

## 9. Embedding / vector search

`EMBEDDING_PROVIDER=openai`, model `text-embedding-3-small` (1536-d)
(`apps/knowledge/embeddings/openai_provider.py`). The local
SentenceTransformer / BGE provider (`apps/knowledge/embeddings/local.py`)
was **removed** — it pulled `torch` via `sentence-transformers` and broke
lean AWS installs. `EMBEDDING_PROVIDER=local` now raises `EmbeddingError`
with instructions to use OpenAI. pgvector HNSW is `idx_kc_embedding_hnsw`
(`0001_initial.py` → `0007` 768-d → `0010` 1536-d). Query and stored
vectors must share that dimension.

`KnowledgeConfig.ready()` still calls `warm_up_embedding_service()`. That
is a **no-op** (OpenAI has nothing to preload; leftover `local` must not
try to import torch at gunicorn start).

## 10. Conversation state — `apps/chatbot/conversation_state.py`

`ConversationTimeline` is the planner's **working context** — Python-owned
session memory the planner reads, not something the Small LLM is ever
asked to reconstruct from a message window. Nine slots as of Phase 39:
the original four (`doctor`, `service`, `insurance`, `availability_target`)
plus `pending_clarification`, and five added in Phase 39 —
`shown_doctors` (ordered, capped at 6, overwritten not appended — "the
list still on screen"), `last_recommendation` (`{id, name, reason}`,
`reason="listed"` vs. an actual recommendation — never invented), `last_slots`
(capped at 8, from the actual `doctor_availability` SQL rows a turn
produced), `problem` (this-turn `entities.symptom`), `preview_only` (a
per-turn flag, reset each turn unless re-asserted).

`pending_clarification` is bound, not decorative (Phase 16). After entity
resolution, `classify_uptake(message)` is a whole-message speech-act (max
48 characters) → `affirm` / `decline` / `None`. `"Yep."` is not an intent;
it takes up the offer the previous turn recorded. `apply_pending_uptake`
rewrites NLU before the planner: `availability_alternative` →
`DOCTOR_AVAILABILITY` with the offered `doctor_id` on `resolved_ids` (do
**not** put `doctor_name` on entities — that would make
`resolve_doctor_candidates(clinic, "Yep.")` run); `service_followup` →
availability for that service, not a forced booking; `slot_confirmation`
(Phase 38) → `BOOK_APPOINTMENT` with the offered doctor resolved, for a
*found* slot ("Earliest opening: Dr Priya at 12 PM") — the empty-day
"check another day?" case and a genuinely-found, specific slot are
different offer shapes, tracked separately.
`mark_pending_decline` → `OFF_TOPIC` with a dedicated fast-path reply.
`"yes, Thursday morning"` is a new request, not uptake — `_AFFIRM_REFERENCE_RE`
(Phase 38) extends the affirm vocabulary to short confirmation-plus-
pronoun phrasing ("yes i want her", "book it", "that doctor") but stays a
small, fixed pattern set for exactly this reason: a named *different*
doctor or a specific day must still fail to match and fall through to
ordinary NLU classification, never get silently absorbed as uptake.
`pending_offer_from_turn` records the offer after compose (empty searchable
availability, a *found* slot, or a service-answer that matched a service).
Do not add `if text.lower() in ["sure", "yes"]`.

**Session recall (Phase 39)** — `classify_session_recall(message)` detects
whole-sentence *meta* questions about this conversation itself ("what
insurance did I tell you", "which doctor did you recommend", "what were
we just talking about", "what was the appointment time you found") and
routes them to `direct_mode="session_recall"` in `build_execution_plan`
— a hard stop before vector/SQL/the Large LLM ever run. `compose_session_recall`
answers from `ConversationTimeline` slots via a plain template, never a
second model pass. This exists because the alternative genuinely
hallucinated: reproduced directly against real trace logs, "Based on what
we already discussed, who did you recommend?" reached the Large LLM with
only a thin `_load_history(limit=2)` window as grounding, and it invented
"I recommended Dr. Omar Haddad" — a recommendation that was never
actually made (the real prior turn for that fever question had returned
an unrelated "I couldn't verify that doctor" refusal). An unset pin
answers honestly ("You haven't told me your insurance yet") rather than
guessing. A genuine new clinic question ("What insurance do you accept?")
does **not** match `classify_session_recall` and reaches SQL normally —
this is meta-conversation detection, not a general question-answering
short-circuit.

**Pin amendment (Phase 39)** — `classify_pin_amendment(message, timeline)`
recognizes a bare date/time retarget on a search already in progress
("Actually Tuesday", "No, Monday was better. Keep everything else the
same", "make it tomorrow") *only* when `timeline.availability_target` or
`timeline.doctor` is set and there is no confirmed booking
(`timeline.booking_stage != "confirmed"`) — that last guard is load-
bearing: it's what keeps this from ever stealing a real reschedule of an
existing appointment, which correctly still requires identity
verification via a completely separate path. When it fires, `engine.py`
overrides `nlu.intent` to `DOCTOR_AVAILABILITY` and keeps the resolved
doctor pin, trusting the NLU's own date/time entity extraction as-is —
never inventing what the message didn't state, same discipline as
`apply_pending_uptake`.

**Ordinal doctor reference (Phase 39)** — `resolve_ordinal_doctor_ref`
resolves "the second doctor you mentioned" / "the first one" against
`timeline.shown_doctors` by list index. This is **list-index coreference
only** — a narrower, different problem from general pronoun resolution.

**Doctor-pronoun resolution (Phase 41)** —
`classify_doctor_pronoun_reference` detects a doctor-directed pronoun
("she"/"he"/"they"/"the doctor"/"this doctor"/"that doctor") in *subject*
position of a capability/quality/availability/service question ("can
she...", "does he provide...", "when is she available", "what services
does she offer"). Computed in `engine.py` alongside `doctor_followup`/
`unknown_doctor_requested`, resolved purely from existing
`ConversationTimeline` state — `shown_doctors` (Phase 39, reliable source
of "who was actually shown," overwritten only when `search_doctors`
itself returns rows) is authoritative over the single-mention
`timeline.doctor` pin:
- exactly one shown doctor (or a single-mention pin with none shown) →
  inject `resolved_ids.doctor_id`, same mechanism as
  `resolve_ordinal_doctor_ref`/`ordinal_doctor_id`; intent is corrected to
  `DOCTOR_SEARCH` only if it isn't already doctor-related (a backstop —
  NLU gets these right unaided most of the time, confirmed live).
- two or more shown doctors → `direct_mode="doctor_pronoun_ambiguous"`
  (same hard-stop pattern as `session_recall`/`gender_unsupported`),
  composing "Do you mean Dr. X or Dr. Y?" from `shown_doctors` — never a
  guess, never the full catalog dumped back.
- no antecedent at all → falls through unchanged.

**Safety guard, deliberately not present in the external plan this was
built from:** a family-relation noun in the *same* message ("my
daughter/son/child/kid/wife/husband/mother/father") blocks resolution
entirely — "My daughter has a fever, can she see a doctor?" must not
resolve "she" to a previously-discussed doctor; "she" is the daughter.
Verified live and by test (`test_doctor_context_resolution.py`).

One precedence fix this required: `_is_doctor_quality_followup`'s "is
he"/"is she"/"are they" substring check also matches inside "When **is
she** available?", intercepting it with a generic bio-only reply
(`_doctor_followup_reply`) before the message ever reached real
availability data — reproduced live. Pronoun resolution now suppresses
that older `doctor_followup` flag once it resolves an antecedent, since
its own trigger set is scoped to capability/availability/service
phrasing (never generic "is she good"-style quality talk, which stays
`doctor_followup`'s alone).

**Still no general coreference** — only the doctor case above is
resolved. A previously-mentioned service, insurance plan, or specialty
("can I get that with my HMO" after discussing a specific plan) still
isn't resolved; neither are object-position or possessive pronoun forms
outside `classify_doctor_pronoun_reference`'s trigger set. Confirmed by
reading the file. Deliberately deferred — do not patch ad hoc into
doctor resolution or booking; a fuller general mechanism needs its own
phase (see ROADMAP.md).

**Preview-only (Phase 39)** — `classify_preview_only` ("don't book
anything until you show me...", "just show me the available times") sets
a per-turn timeline flag that suppresses `exec_plan.booking` (no wizard
launch) while leaving availability SQL untouched — the patient sees
times, nothing gets committed. Not sticky: recomputed and re-persisted
every turn, so it only applies to the turn that actually said it.

## 11. Multi-tenancy

Every clinic-scoped query must filter by `clinic`/`clinic_id`. This applies
to doctors, services, specialties, appointments, insurance, knowledge
chunks, patients. Not re-audited end-to-end during this refactor — assume
existing scoping is correct unless a specific phase says otherwise, and
flag anything that looks unscoped rather than assuming it's fine.

## 12. Known issues not yet addressed (see ROADMAP.md for phase status)

- Service-existence question routing (§6) — Phase 10.
- RAG degraded-state mislabeling (§7) — Phase 9C.
- `ThreadPoolExecutor` saturation under concurrent NLU load (§8) — deferred, no phase assigned yet.
- No *general* coreference/reference resolution (§10) — the doctor-pronoun
  case is resolved as of Phase 41; a mentioned service/insurance/specialty
  as an antecedent still isn't, deferred, needs its own phase.
- `ExecutionPlan.scores` / `PlannerScores` — computed, serialized, never read by anything (confirmed: no engine/ui_meta/test/API/frontend consumer). Not removed in Phase 7 because it's a bigger structural change (whole class, ~9 construction sites) than the single-field cleanup done there — deferred to its own small phase.
- `apps/chatbot/tests.py` (3-line stub) coexists with `apps/chatbot/tests/` (real package) — breaks bare `python manage.py test` with no args (`ImportError: 'tests' module incorrectly imported`). Same issue exists for `apps/knowledge`. Always use explicit labels: `python manage.py test apps.chatbot.tests --keepdb`. Pre-existing, not fixed.
- `apps/importer` crashes the interpreter (`SIGFPE` inside numpy's macOS `_mac_os_check` at import time, triggered via openpyxl) when run in the same process as other apps in this dev environment — pre-existing, unrelated to chatbot work, exclude it from combined full-suite runs on this machine.

## 13. Source-of-truth files (chatbot)

| Concern | File |
|---|---|
| NLU prompt contract | `apps/chatbot/nlu/prompts.py` |
| NLU provider chain / budget | `apps/chatbot/nlu/classifier.py` |
| NLU deadline mechanics | `apps/chatbot/nlu/deadline.py` |
| Entity/doctor/service resolution (DB) | `apps/chatbot/nlu/resolvers.py` |
| Doctor-name sanitization | `apps/chatbot/nlu/entity_extract.py` (`clean_doctor_name`), `entity_guard.py` |
| Confidence policy | `apps/chatbot/routing/confidence.py` |
| Pure message sensors (shared prod/eval) | `apps/chatbot/planner.py::compute_message_sensors` |
| Planner / ExecutionPlan | `apps/chatbot/planner.py` |
| Engine orchestration | `apps/chatbot/engine.py` |
| Service SQL handler | `apps/chatbot/sql_tool/handlers/services.py` |
| SQL dispatch | `apps/chatbot/sql_tool/service.py` |
| Vector search | `apps/knowledge/services/similarity_search.py` |
| OpenAI embedding provider | `apps/knowledge/embeddings/openai_provider.py` |
| Embedding factory / warm-up (no-op) | `apps/knowledge/embeddings/factory.py`, `apps/knowledge/apps.py` |
| Large LLM synthesis | `apps/chatbot/response_llm.py` |
| Booking UI eligibility | `apps/chatbot/ui_meta.py` |
| Booking draft isolation | `apps/chatbot/booking/service.py` (`_apply_prefill`) |
| Conversation state / pending uptake | `apps/chatbot/conversation_state.py` |
| Offline eval battery | `apps/chatbot/eval/runner.py`, `apps/chatbot/eval/cases.py` |
| NLU tests | `apps/chatbot/tests/test_nlu.py` |
| Service resolution tests | `apps/chatbot/tests/test_service_resolver_authority.py`, `apps/chatbot/tests/test_services_category_filter.py` |
| Embedding warm-up tests | `apps/knowledge/tests/test_embedding_warmup.py` |

If this document conflicts with actual code, trust the code, then fix
whichever one is wrong — including this file.
