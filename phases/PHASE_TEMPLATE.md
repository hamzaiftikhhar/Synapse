# Phase <N> — <Name>

Status: 🔄 in progress

Copy this file to `phases/phase_<N>_<slug>.md` when starting a phase that's
substantial enough to deserve its own document (most phases just get a
section in `ROADMAP.md` — use this template when the investigation itself
is long enough that it would bloat the roadmap entry). Fill in every
section; delete none. When done, fold a condensed version back into
`ROADMAP.md` and mark this file's status ✅.

## Objective

One paragraph. Exactly what this phase accomplishes — not what it might
also touch.

## Problem

Current behavior, concretely. Prefer a real transcript/trace/measurement
over a description. Example shape:

```
User: "do you have hydrafacial"
Current: NLU → medical_question → planner → vector_rag → generic policy
         chunk → LLM invents availability
Expected: NLU → services_offered-shaped → planner → SQL → grounded
          exists/doesn't-exist answer
```

## Root cause

Only findings verified by reading source — no speculation. For each:

```
File: apps/chatbot/...
Function: ...
Current behavior: ...
Why it causes the reported problem: ...
```

If you can't verify a suspected cause from source, say that explicitly
instead of presenting a guess as a finding.

## Scope

**Included:**
-
-

**Explicitly excluded** (goes in ROADMAP.md as a new deferred/planned entry,
not fixed here even if related):
-
-

## Files expected to change

- `apps/...`
- `apps/chatbot/tests/...`

If the real diff needs a file not listed here, explain why before changing
it.

## Implementation plan

1. Smallest change that fixes the stated problem.
2. (Only if genuinely required) next smallest change.
3. Regression tests.

## Regression tests

One per behavior the bug fix must guarantee — not just "runs without
error." State input and expected output explicitly.

**Test 1**
- Input:
- Expected:

**Test 2**
- Input:
- Expected:

## Verification

```
python manage.py test <targeted label> --keepdb
python manage.py test apps.chatbot.tests --keepdb
python manage.py run_chat_eval --target 520
```

Compare against the last recorded baseline in `ROADMAP.md`. If a number
changes, explain why — a drop isn't automatically a regression (it might be
eval/tests correctly seeing something for the first time) but it's never
silently acceptable either.

## Performance (if applicable)

Before: <real measured number>
After: <real measured number>
How measured: <exact command/script>

## Safety / regression risk

What else could this touch? (e.g. "changing service routing could affect
doctor/service intersection, category mode, named mode, booking".)

## Results

- Files changed:
- Tests added:
- Test results:
- Eval results:
- Behavior change (one sentence):

## Known limitations / found but not fixed

Anything discovered during this phase that's real but out of scope. Copy
these into `ROADMAP.md` as new 💤/⏳ entries — don't let them live only here.

## Recommended next phase

State it. Do not start it in this document.
