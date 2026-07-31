/**
 * Natural reply pacing — industry practice for instant rule/template paths.
 *
 * Never add delay when the network/LLM already took meaningful time.
 * Only pad sub-~300ms replies so greetings/off-topic don't feel hardcoded.
 */

const FAST_THRESHOLD_MS = 300;
const MIN_VISIBLE_MS = 320;
const MAX_VISIBLE_MS = 480;

export function naturalReplyDelayMs(elapsedMs: number): number {
  if (elapsedMs >= FAST_THRESHOLD_MS) return 0;
  const target =
    MIN_VISIBLE_MS +
    Math.floor(Math.random() * (MAX_VISIBLE_MS - MIN_VISIBLE_MS + 1));
  return Math.max(0, target - elapsedMs);
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export async function waitForNaturalReplyPace(startedAt: number): Promise<void> {
  if (prefersReducedMotion()) return;
  const elapsed = performance.now() - startedAt;
  const delay = naturalReplyDelayMs(elapsed);
  if (delay <= 0) return;
  await new Promise((r) => setTimeout(r, delay));
}
