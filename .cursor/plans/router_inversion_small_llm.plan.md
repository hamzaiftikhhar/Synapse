---
name: ""
overview: ""
todos: []
isProject: false
---

# Synapse Chat Router Reset — Small-LLM-First Architecture

## Verdict

GPT is right. The foundation (SQL-first facts, vector for policy, booking wizard, multi-tenant catalogs, eval battery) is strong. What went wrong is that **intelligence migrated into the routing layer**.

Roughly **~1,150 LOC** of `rules.py` + `heuristics.py` + `signals.py` + `confidence.py` now try to understand English. That produces intermittent “good” answers and intermittent disasters — exactly what your Horizon log shows.

**Wrong answers from overconfident rules are more harmful than a slightly slower Small LLM call.** So the tough decision is:

> **Demote regex to a thin safety/phatic gate. Make Small LLM the primary semantic router. Keep SQL/Vector/Booking as dumb executors.**

---

## Diagnosis from your Horizon transcript

| User message | What happened | Real cause |
|---|---|---|
| “what things do you provide / specialties / doctor ali / ulcer” | Unable to connect | NLU hits Gemini **6.5s timeout** → frontend generic error (not “bad answer”) |
| “pain in the brain” | Pseudo-emergency / portal blurb | Soft-medical / RAG mismatch; not clean specialty SQL |
| “PURPOSE AND BACKGROUND” / refund | Good RAG | Vector path worked when lane was correct |
| Saturday hours / Aetna / adult physical price | Good SQL | Structured facts still work |
| Cancel &lt;24h fee? | **Full service price list** | Heuristics treated “cancel/fee” like pricing/services, not policy FAQ |
| Dispensary meds pricing | Matched **Blood Draw** | `match_services_in_message` over-matched “routine” |
| Cancel appointment how? | “Patient not authenticated” | Cancel SQL without auth UX — executor issue |
| Book urgent | Booking OK | Transactional path worked |
| Medicare + Dr Rostova checkup | Only “we accept Medicare” | Missed compound: insurance **+** doctor **+** out-of-pocket nuance |
| Sulphuric acid dissolve time | **Service list** | Duration/pricing heuristics stole “how much time” |
| Chest pressure → arm 1 hour | **Clinic hours** | Emergency rules missed narrative; hours heuristic stole “right now”/open |
| Membership reactivate | Unable to connect | Timeout again |
| Membership refund mid-year | Good RAG | Docs path OK |
| “how many times visit specialized doctor” | Urgent Care Visit $135 | Service token match on “visit” / “urgent” |
| Skin treatment prevention | Unrelated portal policy | Wrong RAG chunk / wrong lane after timeout |
| “What urgent care do you provide?” | Single Urgent Care Visit | **List question collapsed to one service hit** (`confidence 0.5`, `nlu_ms: 6503`) |

Pattern: **when Small LLM times out or is skipped, heuristics invent a lane. Invented lanes look confident and are often wrong.**

---

## Current pipeline (why it feels messier each prompt)

```
message
  → rules_fast (greet/bye)
  → rules_strong (MANY semantic regex — often wins, skips Small LLM)
  → Small LLM (only if rules miss) [timeout 6.5s]
  → rules_fallback / unknown@0.5
  → heuristics (rewrites intent again: hours/services/insurance/knowledge…)
  → confidence policy (another rewrite)
  → DecisionEngine
  → resolve_lane
  → executor (SQL / booking / vector / clarify)
```

Problems baked in:

1. **`NLU_RULES_BEFORE_LLM=True`** — strong regex frequently **prevents** the Small LLM from ever running.
2. **Heuristics run after NLU and override it** — even a correct LLM JSON can be overwritten by `service_hit`.
3. **`match_services_in_message` is used for routing**, not just entity fill — list questions become single-service SQL.
4. **Timeout → confidence 0.5 + heuristic recovery** — worst of both worlds (slow + wrong).
5. **Eval battery greenwashed** — 582 routing cases pass *without* live NLU, so they don’t catch “urgent care services” vs “Urgent Care Visit”.

Industry pattern (2025–26 agent routers): **thin rules → (optional embeddings) → small classifier → executors**. Rules are not allowed to own open-domain English.

---

## Target architecture (locked design)

```
User message
    │
    ▼
┌───────────────────────────┐
│  Gate A — Safety (rules)  │  emergency / self-harm / clear abuse
│  Fail CLOSED to template  │  NEVER wait for LLM on chest-pressure-to-arm
└───────────┬───────────────┘
            │ not safety
            ▼
┌───────────────────────────┐
│  Gate B — Phatic (rules)  │  short hi/bye/thanks only
│  Exact / tiny patterns    │
└───────────┬───────────────┘
            │ else ALWAYS
            ▼
┌───────────────────────────┐
│  Small LLM Router         │  sole semantic brain
│  JSON lane + entities     │  catalogs as HINTS only
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│  Validator (dumb)         │  tenant-scope entity IDs; drop forged clinic ids
│  NO intent rewriting      │  service match = suggestion, not forced filter
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│  Executor                 │
│  • SQL_FAST               │  hours, insurance, doctors, specialties, services, pricing
│  • BOOKING                │  wizard only if transactional
│  • VECTOR_RAG + Large LLM │  policy/membership/refund/SOP/post-op
│  • DIRECT                 │  templates (off-topic, greet, emergency)
│  • CLARIFY                │  last resort
└───────────────────────────┘
```

### Router JSON (replace overgrown intent soup for routing)

Keep rich intents internally if useful, but the **contract the executor needs** is:

```json
{
  "lane": "sql|booking|vector_rag|direct|clarify",
  "sql_tool": "hours|location|insurance|doctors|specialties|services|pricing|appointments|null",
  "confidence": 0.0,
  "emergency": false,
  "off_topic": false,
  "entities": {
    "doctor_name": null,
    "specialty": null,
    "service": null,
    "insurance_provider": null,
    "date": null,
    "symptom": null
  },
  "service_filter_mode": "none|named|category",
  "document_needed": false,
  "clarification_question": null,
  "reasoning_short": "..."
}
```

Critical field: **`service_filter_mode`**

- `"none"` → list all / category browse (fixes “what urgent care do you provide?”)
- `"named"` → filter to one service (fixes pricing of “Adult Physical”)
- `"category"` → filter by category keyword without pretending a single SKU

### What rules may still do (whitelist)

| Keep as rules | Why |
|---|---|
| Emergency / self-harm | Fail-closed, &lt;5ms, legal/safety |
| Exact greetings / farewells | Cheap UX |
| Transactional booking commit phrases (`start booking`) | UI glue |
| OTP / auth gates | Not NLU |

### What rules/heuristics must STOP doing

| Delete or demote | Why |
|---|---|
| Strong regex for hours/insurance/services/pricing/FAQ | Steals Small LLM |
| Heuristics that rewrite `intent` after NLU | Second brain |
| Using `match_services_in_message` to set lane/SQL filter on list questions | Semantic error |
| Auto `vector_rag` on every unknown just because PDFs exist | Already partially fixed; keep strict |
| Duration/price regex catching “how much time” on off-topic | Sulphuric acid bug |
| Confidence policy that “keeps SQL” on timeout@0.5 for service hits | Your meta dump: `band=low\|low_keep_sql` |

---

## Executor upgrades (smarter tools, dumber router)

### SQL
- **Specialties tool** must exist and answer “what specialties do you provide?” (today this often dies on timeout or wrong lane).
- **Doctors**: name lookup (`Ali Hamza` → not found honesty), qualifications/title/bio.
- **Services**: honor `service_filter_mode`; category “urgent care” returns all UC services, not one SKU.
- **Insurance**: keep accepted/rejected; compound questions may return insurance + soft note (doctor accepts plan) without inventing coverage.
- **Cancel appointment**: if unauthenticated → clear “verify to see appointments” + booking CTA, not raw internal error string.

### Vector
- Only when `lane=vector_rag` or `document_needed=true`.
- Prefer hybrid: empty/thin SQL on pricing/membership → one RAG pass (policy), never invent.

### Safety
- Expand emergency gate beyond short keyword list: **chest pressure/tightness + arm radiation + timeframe** must fire before any hours/SQL heuristic.
- Off-topic harm (acids, disposal of bodies): Small LLM `off_topic` / refuse — never duration→services.

### Reliability (“Unable to connect”)
- Treat as **P0 ops bug**, not UX copy.
- Fail-faster NLU (e.g. 2.5–3.5s) + OpenAI fallback on timeout (today timeout skips OpenAI).
- Never leave the client with empty 500 after 6.5s of silence; return clarify/direct with `meta.degraded=true`.
- Fix Gemini key / provider health (logs already warn key format).

---

## Migration plan (phased — no big-bang rewrite of booking/RAG)

### Phase 0 — Freeze (day 0)
- **Stop adding heuristics/signals for new English.**
- Tag current Horizon failures as golden regression cases (must be in eval).

### Phase 1 — Router inversion (core, ~2–4 days)
1. Change classifier order to: **safety/phatic → Small LLM → (optional) tiny fallback**.
2. Disable strong semantic rules via `NLU_RULES_BEFORE_LLM=False` or delete strong semantic branches.
3. Shrink `apply_routing_heuristics` to **entity hints only** (or remove intent mutation entirely).
4. Rewrite NLU system prompt around **lanes + `service_filter_mode`**, not 30 intents.
5. Expand emergency gate for narrative cardiac symptoms.

### Phase 2 — Executor honesty (~1–2 days)
1. Services SQL respects filter mode.
2. Specialties SQL wired for “what specialties…”.
3. Cancel-appointment unauth message cleaned.
4. Hybrid SQL→RAG only when router asked for docs or SQL empty on policy-ish tools.

### Phase 3 — Eval that matches reality (~2 days)
Replace “routing-only green” with:

| Bucket | Count (target) |
|---|---|
| SQL structured | 300 |
| RAG policy | 300 |
| Booking transactional vs informational | 200 |
| Safety / emergency / off-topic harm | 200 |
| Ambiguous / timeout degraded | 200 |

Each case stores: message, expected_lane, expected_sql_tool, expected_filter_mode, must_not_contain, max_latency_ms.

Gate CI: fail if pass rate &lt; target or if any **safety** case fails.

### Phase 4 — Optional (later)
- Embedding pre-router for ultra-common FAQ clusters (cost/latency).
- Small LLM natural-language polish for SQL rows (optional; templates stay default for hours/prices).

---

## Explicit non-goals

- Do not rebuild booking wizard / OTP.
- Do not add clinic-specific keyword packs (Apex Invisalign, Lumina Botox lists in router).
- Do not keep growing `signals.py` for every specialty vocabulary.
- Do not require Large LLM for hours/insurance/prices.

---

## Success metrics

| Metric | Today (symptom) | Target |
|---|---|---|
| Wrong-lane rate on golden set | High on semantic Qs | &lt;5% |
| Safety misses (cardiac narrative) | Missed → hours | 0 |
| “Unable to connect” on normal Qs | Common after 6.5s | &lt;1% |
| p95 latency SQL lane | Often 6.5s+ when LLM involved | &lt;1.5s when rules/LLM healthy; degraded &lt;3.5s |
| Heuristics/rules LOC for semantics | ~1k+ | &lt;200 safety/phatic |
| New clinic onboarding | Needs new regex | Catalogs only |

---

## Decision asked of you

Approve **Router Inversion (Phase 1–3)** as the next implementation track:

1. Small LLM is default semantic router  
2. Rules = safety + phatic + booking-commit only  
3. Heuristics stop rewriting intents  
4. Service matching becomes filter-mode aware  
5. Eval expands to live semantic/safety golden set  

If you say **go**, implementation starts with Phase 1 (classifier order + gut strong heuristics + emergency gate + `service_filter_mode`) and the Horizon golden cases from this transcript as the acceptance suite.

---

## Audit appendix (codebase verification)

Confirmed by [Audit chat routing complexity](f92f7e61-3621-47d0-b421-c699eb1c7c23).

### Exact pipeline (`ChatEngine.process` + `classify_message`)

```
0. Catalogs (docs + services) injected into nlu_ctx
1. NLU: rules_fast → rules_strong (if NLU_RULES_BEFORE_LLM, not compound)
     → Small LLM (≤~6.5s) → OpenAI fallback only if primary ≠ timeout
     → rules_fallback / clarify on failure
2. apply_routing_heuristics  (mutates intent + flags)
3. apply_confidence_policy   (bands; may force SQL on service_hit)
4. DecisionEngine.decide
5. Engine speech-act overlays (booking commit / soft medical / doc match)
6. resolve_lane → execute (Large LLM only on vector_rag)
```

### Complexity evidence

| File | ~LOC | Steal surface |
|------|-----:|---------------|
| `nlu/rules.py` | 563 | Strong semantic regex before LLM |
| `routing/signals.py` | 358 | Fuzzy `match_services_in_message` (single-token ≥5) |
| `routing/heuristics.py` | 297 | Post-NLU intent rewrite (~27 if / 25 elif) |
| `routing/confidence.py` | 237 | Mid/low band can keep SQL on service_hit |
| `sql_tool/handlers/services.py` | 87 | Duplicate fuzzy matcher at execute time |
| `engine.py` | 799 | Orchestration + soft-medical overlays |

Combined heuristics+signals: ~17 `re.compile`, ~67 if-nodes; rules.py adds ~95 regex alternation arms.

### Highest-ROI cut order (Phase 1 start)

1. Harden `match_services_in_message` (+ SQL twin): drop single-token ≥5 and loose 40% overlap; require full name or ≥2 significant tokens or LLM entity.
2. Knowledge frame (`cancellation|refund|deposit|policy`) beats fee/pricing strong rule.
3. Expand emergency (`chest hurt(s)`, pressure + arm radiation); block hours rule when symptom cues present.
4. On NLU timeout: vector if knowledge/doc overlap, else clarify — **never** open SQL services via UNKNOWN+service_hit.
5. Shrink post-heuristics to: phatic force, emergency trust, timeout recovery only.

### “Unable to connect” nuance

Frontend axios default timeout is **30s** (`frontend/src/lib/api/client.ts`). Stack can be NLU 6.5s + optional second LLM + vector + Large LLM (≤12s) → client timeout. On NLU timeout, OpenAI fallback is **skipped**, then clarify can still escalate to vector_rag → another slow Large LLM call. Fix is both: fail-faster NLU + no SQL invent on timeout + avoid vector escalate after NLU timeout unless docs clearly match.