/** Shared phone validation — keep in sync with the E.164 check the backend
 * OTP/verification flow already requires (apps/verification/outcomes.py). */

export type PhoneIssue = "required" | "invalid";

const ISSUE_MESSAGE: Record<PhoneIssue, string> = {
  required: "Phone number is required",
  invalid: "Enter a valid phone number, e.g. +1 415 555 0123",
};

export function phoneIssueMessage(issue: PhoneIssue): string {
  return ISSUE_MESSAGE[issue];
}

// E.164: optional leading +, then 7-15 digits, first digit non-zero.
const E164_RE = /^\+?[1-9]\d{6,14}$/;

/**
 * Validate a phone number as typed. Accepts common human formatting
 * (spaces, dashes, dots, parens) and checks the underlying digits against
 * E.164 shape — the same standard the backend's phone-OTP verification
 * requires, so a patient record that passes this can actually receive a
 * verification code later. Returns null when valid.
 */
export function validatePhone(
  value: string,
  opts: { required?: boolean } = {}
): PhoneIssue | null {
  const trimmed = value.trim();
  if (!trimmed) return opts.required === false ? null : "required";

  // Strip human formatting characters before shape-checking the digits —
  // "(415) 555-0123" and "+1 415 555 0123" are both fine to type.
  const compact = trimmed.replace(/[\s().-]/g, "");
  if (!E164_RE.test(compact)) return "invalid";
  return null;
}

/** Normalize to a plain +-prefixed digit string for submission, assuming
 * validatePhone() already returned null for this value. US-assumes a bare
 * 10-digit number (no country code typed) means +1 — the common case for
 * front-desk staff typing a local number — never guesses for anything
 * else (a number that already has 11+ digits, or an explicit "+", is left
 * exactly as typed rather than reinterpreted). */
export function normalizePhone(value: string): string {
  const compact = value.trim().replace(/[\s().-]/g, "");
  if (compact.startsWith("+")) return compact;
  if (/^\d{10}$/.test(compact)) return `+1${compact}`;
  return `+${compact}`;
}
