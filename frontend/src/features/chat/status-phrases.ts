/**
 * Calm wait-status copy while the assistant is working.
 *
 * Keep the set small (6–8). Prefer patient-facing reassurance over
 * fake internals ("querying vector DB"). Progress by elapsed time;
 * optionally bias the sequence from the user's last message.
 */

export type StatusPhrase = string;

const GENERAL: StatusPhrase[] = [
  "Thinking",
  "Understanding your request",
  "Looking into that",
  "Preparing your response",
  "Almost ready",
];

const BOOKING: StatusPhrase[] = [
  "Thinking",
  "Understanding your request",
  "Preparing your appointment",
  "Checking availability",
  "Finalizing",
];

const CLINIC_FACTS: StatusPhrase[] = [
  "Thinking",
  "Understanding your request",
  "Checking clinic information",
  "Preparing your response",
  "Almost ready",
];

const POLICY: StatusPhrase[] = [
  "Thinking",
  "Understanding your request",
  "Finding relevant information",
  "Preparing your response",
  "Almost ready",
];

/** Elapsed-ms thresholds to advance to the next phrase in the sequence. */
export const STATUS_STEP_MS = [0, 1200, 2800, 4500, 7000] as const;

export function statusSequenceForMessage(message: string): StatusPhrase[] {
  const text = (message || "").toLowerCase();

  if (
    /\b(book|schedule|appointment|reschedule|start booking)\b/.test(text)
  ) {
    return BOOKING;
  }

  if (
    /\b(hours?|open|close|insurance|aetna|cigna|medicare|medicaid|doctor|physician|location|address|services?)\b/.test(
      text
    )
  ) {
    return CLINIC_FACTS;
  }

  if (
    /\b(policy|cancel|cancellation|cover|coverage|what (does|is)|include|membership|faq)\b/.test(
      text
    )
  ) {
    return POLICY;
  }

  return GENERAL;
}

export function statusPhraseAt(
  sequence: StatusPhrase[],
  elapsedMs: number
): StatusPhrase {
  if (!sequence.length) return "Thinking";
  let index = 0;
  for (let i = 0; i < STATUS_STEP_MS.length; i++) {
    if (elapsedMs >= STATUS_STEP_MS[i]!) index = i;
  }
  return sequence[Math.min(index, sequence.length - 1)]!;
}
