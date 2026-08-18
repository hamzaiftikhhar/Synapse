# Synapse — Agent Engineering Rules

Generic rules for any coding agent working in this repository (Claude Code,
Cursor, Codex, etc.) — not tool-specific. Claude Code additionally follows
`CLAUDE.md`; both point to `ARCHITECTURE.md` and `ROADMAP.md` for what the
system actually does and what's already been tried.

## Inspect before editing

Never change code based only on a description of what it does. Read the
implementation, its callers, its tests, and — for this repo specifically —
check `ARCHITECTURE.md`/`ROADMAP.md` for whether the area has already been
investigated. A field or function is not "dead" because it's unused in the
one file you're looking at; grep the whole repository (production code,
tests, and — for anything that might be API-facing — `apps/api/` and
`frontend/src/`) before concluding that.

## Search every consumer before removing or changing a contract

Before changing a function signature, dataclass field, return shape,
constant, route, or DB column: find every caller first. "Looks redundant"
is not proof of redundancy — see `ROADMAP.md`'s Phase 6 entry for a real
example where a matcher that looked exactly like dead code turned out to be
the only thing covering a data-completeness gap another function's default
argument silently created.

## One phase, one focus

Don't implement the next phase because it seems like the obvious next step.
Finish the requested scope, report, stop. If you find something else worth
fixing, write it down (in `ROADMAP.md` for this repo) instead of fixing it
in the same diff — unless it's a genuinely trivial, zero-risk, same-root-
cause fix (e.g. a test assertion that's simply wrong), in which case fix it
but call it out explicitly as separate from the phase's own scope.

## Small diffs

One bug → smallest correct fix → regression test → verification. Not: bug
→ refactor → rename → unrelated cleanup → formatting pass, all in one diff.
A large diff is harder to verify, harder to revert cleanly, and hides the
actual fix inside noise.

## Regression tests prove the bug, not just that code runs

Bad:
```python
result = engine.process(...)
assert result is not None
```
Better — assert the specific thing that was wrong:
```python
assert resolved_plan.vector_tasks == ["general_faq"]
assert result.route == result.lane  # the actual bug: these disagreed
```
For routing/classification changes, test the intended route, at least one
conflicting-signal case, the fallback path, and the missing-information
case — not just the happy path. Where a bug was found via a real transcript
or real measurement, reproduce that exact input, not a simplified stand-in
— see `ROADMAP.md` Phase 9A/9B for what "reproduce before fixing" looks
like in this repo (real timing numbers, real `django.setup()` runs, not
just mocked unit assertions).

## Performance claims get measured, not estimated

If a phase touches provider calls, vector search, embeddings, LLM calls, or
deadlines: measure before and after with a real number. "Should be faster"
is not a result.

## Report failures honestly

If the full suite has a pre-existing failure, a flake, or an environment
crash unrelated to your change: say so explicitly, and reproduce it in
isolation to prove it's pre-existing (re-run just that test, or stash your
changes and re-run) rather than asserting it's unrelated. Never edit a test
to make it pass unless the test itself is demonstrably wrong — and when it
is, explain why in the same terms you'd use for a production bug fix (root
cause, not just "loosened the assertion").

## Documentation upkeep

- Architectural fact changed → update `ARCHITECTURE.md`.
- Phase started/finished/found-something-deferred → update `ROADMAP.md`.
- A genuinely agent-wide (not this-repo-specific) rule emerges → update this
  file. A Claude-specific workflow preference → `CLAUDE.md`.
- Don't duplicate the same fact across files. Each file has one job (see
  the header of each for what that job is).

## Git safety

Never reset, force-push, or discard user changes without explicit
permission. Never rewrite history. Never commit `.env` or other secrets —
double-check file contents before staging anything that looks like it might
contain one, even if the filename looks innocuous. Only commit when
explicitly asked.

## This repo's chatbot-specific rule

The Small LLM produces semantics; Python (the planner) decides execution;
handlers execute what the planner authorized. See `CLAUDE.md` and
`ARCHITECTURE.md` §2/§6 for what this means concretely and where it's
still violated. Don't move an execution decision (SQL vs. vector vs.
booking, which tool to call) into an LLM prompt because it's locally
convenient — that's the exact pattern this whole refactor has been undoing.
