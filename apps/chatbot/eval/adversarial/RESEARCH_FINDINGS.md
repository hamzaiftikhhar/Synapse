# External research findings — Phase 51 adversarial evaluation

Gathered via live web search (September 2026) before designing the
adversarial corpus, specifically so the corpus reflects documented
real-world failure modes rather than only the bugs this project has
already found on its own. Kept separate from the clinic-specific corpus
per the phase's own instruction — this file is external reference
material, not a Synapse-specific test.

## Medical hallucination benchmarks

- **MedHalu** (arXiv:2409.19492) — hallucination benchmark built from
  *real patient-posed, layperson healthcare queries* (not clinician
  exam questions), with hallucinated spans annotated by type. Directly
  relevant to us: Synapse's own users are laypeople, not clinicians, so
  a benchmark grounded in patient phrasing is the closer analogue than
  clinician-exam benchmarks (MedQA/MedMCQA).
- **Med-HALT** (arXiv:2307.15343) — splits hallucination testing into
  *reasoning* hallucination (the model invents a plausible-sounding
  chain of reasoning) and *memory-based* hallucination (the model
  states a specific fact — a name, a number, a date — that doesn't
  exist). The memory-based category is the one directly applicable to
  Synapse: a fabricated doctor name, insurance plan, or appointment
  time is a memory-based hallucination, not a reasoning one.
- **MedHallu** (ACL Anthology, EMNLP 2025) — benchmark specifically for
  *detecting* medical hallucinations, reinforcing that hallucination
  detection (not just generation-side mitigation) is treated as its own
  research problem — motivates building explicit hallucination checks
  into the eval harness rather than relying on the response "reading
  plausibly."
- **"Large language models provide unsafe answers to patient-posed
  medical questions"** (arXiv:2507.18905) — found real, layperson-style
  medical questions provoke unsafe answers at a non-trivial rate even
  from strong general-purpose models — directly motivates §5 of this
  phase (safety boundary testing) rather than assuming a clinic
  administrative bot is exempt just because it isn't a "medical" bot by
  design.

## Chatbot safety / red-teaming methodology

- **"Toward trustworthy chatbots: a protocol for red teaming for
  health-related conversations"** (Scientific Reports, nature.com) —
  proposes a three-pillar protocol: *error stratification* (classify
  failures by type/severity rather than a flat pass/fail), *dual-pronged
  testing* (both single-turn probes and multi-turn stress sequences),
  and *vulnerability-informed mitigation* (fix what's actually
  exploitable, not everything that's theoretically imperfect). This
  phase's structure (severity model + multi-turn corpus + "don't fix
  everything" instruction) mirrors this directly — confirmed
  independently, not just asserted.
- A separately-found large-scale evaluation (157k+ conversation turns
  across major models) found failure modes were **frequently invisible
  to single-turn testing** and only appeared under multi-turn stress —
  with error rates for advice-shaped queries spiking sharply in
  multi-turn sequences versus single-turn checks. Directly motivates
  testing corrections/topic-switching/context-retention as real
  multi-turn `ChatSession` sequences in this corpus, not synthetic
  one-shot NLU calls.
- Mental-health chatbot safety literature documents "crisis escalation
  failure" — missing an indirectly-expressed crisis signal — as a
  distinct, common failure category, separate from outright wrong
  factual answers. Informs the phrasing of some safety-boundary test
  cases below (indirect distress framing, not just textbook ER
  keywords).

## Robustness to noisy real-world input

- Multiple 2025-2026 studies confirm LLMs are measurably sensitive to
  small character-level perturbations — accuracy on reasoning
  benchmarks dropping meaningfully from single-character edits, further
  with compounding edits — and that this class of noise (typos,
  informal grammar, inconsistent punctuation) is a *realistic*
  distribution of real user input, not an edge case. Directly motivates
  the spelling/grammar/punctuation/casual-language categories below.

## Multi-intent / compound-query dialogue research

- Industry data cited in current multi-intent SLU research: **roughly
  half of real utterances in a large voice-assistant dataset contained
  more than one intent.** This is strong external validation that
  compound-query handling (the subject of this session's Phases
  47–50) is not a niche edge case for a chatbot like this — it should
  be expected as a large fraction of real traffic, not a rare
  adversarial trick.
- Standard joint intent-detection/slot-filling architectures are
  explicitly documented as *not* extracting relationships between
  slots when multiple intents are present — i.e., the literature
  describes the exact "which entity belongs to which intent" gap this
  project found and fixed in Phase 50 as a known, general limitation
  class of this architecture family, not a Synapse-specific defect.

## LLM overconfidence / calibration

- Consistent finding across several 2025-2026 papers: LLM verbalized
  confidence is **poorly calibrated and does not reliably track
  correctness**, and models keep answering confidently even when
  explicitly told information is insufficient. Directly motivates
  testing "false premise" and "leading question" cases (§4 below) —
  the literature says a model's fluent, confident tone is not evidence
  it's grounded in real data, which is exactly what Synapse's
  catalog-grounded architecture is supposed to prevent structurally
  (SQL execution, not LLM assertion, is the source of truth) — this
  phase tests whether that architectural guarantee actually holds at
  the response-composition layer.

## What does and doesn't apply to Synapse specifically

Synapse is an **administrative/scheduling** clinic chatbot backed by a
deterministic SQL/vector pipeline (per `ARCHITECTURE.md`), not a
free-generation clinical-diagnosis model. This materially changes which
research applies directly:

- **Applies directly:** memory-based hallucination (fabricated
  doctors/services/plans/appointments), entity/slot cross-contamination
  in compound queries, noisy-input robustness, overconfidence framing,
  prompt-injection/data-boundary attacks (this is still an LLM-backed
  application with real tenant data behind it).
- **Applies, but scoped down:** clinical safety — Synapse is not meant
  to *diagnose*, so the correct benchmark isn't "does it answer medical
  questions correctly" (MedQA-style) but "does it correctly recognize
  when a question is outside its scope and hand off/escalate instead of
  fabricating an answer" — evaluated as a boundary, per the phase's own
  instruction, not as a medical-QA accuracy score.
- **Does not apply / out of scope:** reasoning-hallucination benchmarks
  built around multi-step clinical differential diagnosis, and
  mental-health-specific "vulnerability-amplifying interaction loop"
  research — Synapse has no therapeutic/counseling surface at all.

## Sources

- [MedHalu: Hallucinations in Responses to Healthcare Queries by Large Language Models](https://arxiv.org/abs/2409.19492)
- [Med-HALT: Medical Domain Hallucination Test for Large Language Models](https://arxiv.org/pdf/2307.15343)
- [MedHallu: A Comprehensive Benchmark for Detecting Medical Hallucinations](https://aclanthology.org/2025.emnlp-main.143.pdf)
- [Large language models provide unsafe answers to patient-posed medical questions](https://arxiv.org/pdf/2507.18905)
- [Toward trustworthy chatbots: a protocol for red teaming for health related conversations](https://www.nature.com/articles/s41598-026-45719-3)
- [AI in Healthcare: Benefits, New Failure Modes and Implications for Patient Safety](https://healthmanagement.org/c/healthmanagement/IssueArticle/ai-in-healthcare-benefits-new-failure-modes-and-implications-for-patient-safety)
- [HealthSearchQA / MultiMedQA — Large Language Models Encode Clinical Knowledge](https://arxiv.org/pdf/2212.13138)
- [LLM01:2025 Prompt Injection — OWASP Gen AI Security Project](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [Prompt injection: types, real-world CVEs, and enterprise defenses](https://www.vectra.ai/topics/prompt-injection)
- [Large language models robustness against perturbation](https://www.nature.com/articles/s41598-025-29770-0)
- [Multi-Intent Spoken Language Understanding: Methods, Trends, and Challenges](https://arxiv.org/pdf/2512.11258)
- [When Confidence Fails: Overconfidence in LLMs under Uncertainty and Missing Clinical Information](https://arxiv.org/html/2608.09080)
- [Token Probabilities to Mitigate LLM Overconfidence in Answering Medical Questions](https://www.jmir.org/2025/1/e64348)
