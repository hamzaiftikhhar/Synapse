# Synapse — Claude Instructions

Synapse is a multi-tenant clinical chatbot platform (Django + PostgreSQL +
pgvector). This file is how to work in this repo. It intentionally does not
re-explain the architecture or the phase history — those live in their own
files so this one stays short enough to actually read every session:

- **`ARCHITECTURE.md`** — how the chatbot pipeline actually works, verified
  against source. Read this before inspecting chatbot code from scratch.
- **`ROADMAP.md`** — what's been done, what broke, what's still open, and
  why decisions were made the way they were. Read the relevant phase entry
  before starting related work — don't re-derive history that's already
  written down.
- **`AGENTS.md`** — engineering rules that apply to any coding agent in this
  repo, not Claude-specific.
- **`phases/PHASE_TEMPLATE.md`** — the shape a phase report should take.

If you're about to spend a long tool-call chain rediscovering something
(what fields NLU actually produces, why a matcher wasn't deleted, what
Phase 6 found) — stop and check ARCHITECTURE.md/ROADMAP.md first. If it's
not there, or turns out to be wrong, do the work *and* fix the doc.

## Phase discipline

This codebase is worked in small, numbered phases, one at a time:

1. State the exact objective for *this* phase only.
2. Inspect the relevant source, its callers, and its existing tests before
   writing anything. Don't assume a field is unused because one file
   doesn't reference it — grep the whole repo.
3. Reproduce the bug first where possible. A latency claim gets measured
   (see Phase 9A/9B in ROADMAP.md for what that looks like: real numbers,
   not estimates). A routing claim gets a real call through the actual
   code path, not a guess about what the code "probably" does.
4. Make the smallest change that fixes the stated problem. Don't bundle in
   adjacent cleanup, refactors, or "while I'm here" improvements — write
   them into ROADMAP.md as a new deferred/planned entry instead.
5. Add a regression test that would have caught the original bug — not
   just "the function runs without error."
6. Run the relevant tests, then the full suite, then the eval battery (see
   commands below). Compare against the last recorded baseline in
   ROADMAP.md, not a guess.
7. Report: files changed, root cause, fix, tests added, test/eval results,
   anything found but not fixed, recommended next phase.
8. **Stop.** Update ROADMAP.md. Do not continue into the next phase without
   being asked, even if it seems like the obvious next step.

## Don't guess — verify, including things you were told

If a prior session, another agent, or a pasted report claims something is
already fixed or already true, check it against the actual current file
state before building on it — `git status`/`git diff`, not the prose
summary. This has mattered in practice: verifying an external agent's NLU
timeout fix directly (re-reading the diff, re-running the tests myself,
confirming a specific numeric claim against the actual clamp value in
`deadline.py`) is what caught that its test suite, while excellent, hadn't
covered a real multi-turn scenario — which then surfaced a genuine (and
correct, once understood) emergent behavior neither side had modeled. Trust
is not a substitute for reading the diff.

Never invent a file, function, field, or test result. If the repo doesn't
prove it, say so and go look, or say you don't know.

## Commands

```bash
# Full chatbot suite — bare `manage.py test` (no args) is broken in this
# repo (apps/chatbot/tests.py and apps/chatbot/tests/ both exist; same for
# apps/knowledge). Always use an explicit label:
python manage.py test apps.chatbot.tests --keepdb

# Add apps.knowledge.tests when touching embeddings/vector search:
python manage.py test apps.chatbot.tests apps.knowledge.tests --keepdb

# Offline routing eval battery (682 synthetic cases, no live LLM calls):
python manage.py run_chat_eval --target 520

# A single test file/class/method:
python manage.py test apps.chatbot.tests.test_nlu.NLUTotalBudgetTests --keepdb -v 2
```

Current baseline (see ROADMAP.md for the phase that produced it): **759/759
chatbot+knowledge tests, 674/682 (98.8%) eval.** Anything that changes
either number needs an explanation in the phase report — a drop isn't
automatically a regression (see Phase 3 in ROADMAP.md for a real example of
a "regression" that was actually eval correctly seeing a pre-existing
production behavior for the first time) but it always needs to be
understood, not shrugged off.

`apps.importer` crashes the interpreter on this machine (SIGFPE in numpy's
import-time self-check) — exclude it from combined full-suite runs; this is
pre-existing and unrelated to chatbot work.

## The one rule that matters most for this codebase

**The Small LLM (NLU) produces semantics. Python (the planner) decides
execution. SQL/vector handlers execute what the planner authorized — they
don't re-decide.** This was violated in several places before this
refactor and is still not 100% true today (see ARCHITECTURE.md §6 for the
one confirmed remaining gap). Any change that makes an LLM responsible for
choosing SQL vs. vector vs. booking, or that makes a downstream handler
re-interpret the user's message instead of trusting what the planner
already resolved, is moving the wrong direction — flag it even if it seems
locally convenient.

## Reporting format

End every phase with:

- **What changed** — one paragraph.
- **Files changed** — list, with what changed in each.
- **Root cause** — what was actually true in the code, with file:line
  references where it matters.
- **Tests** — what was added, exact commands run, exact results.
- **Eval** — score, compared to the last recorded baseline.
- **Known limitations / found-but-not-fixed** — say it plainly, put it in
  ROADMAP.md too.
- **Recommended next phase** — state it, don't start it.

Report failures honestly. A full-suite run with one pre-existing, unrelated
flake is "346/346 relevant, 1 pre-existing unrelated flake reproduced in
isolation" — not "all passing" and not "broken." Never edit a test to make
it pass unless the test itself is demonstrably wrong (and say so explicitly
when you do — see the Phase 9A date-flake fix in ROADMAP.md for the bar:
reproduce *why* it's wrong, don't just loosen the assertion).
