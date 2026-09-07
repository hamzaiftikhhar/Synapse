/** Shared date-of-birth helpers — keep in sync with apps/patients/dob.py */
export const DOB_MAX_AGE_YEARS = 120;

export type DobIssue =
  | "required"
  | "invalid"
  | "future"
  | "too_old";

const ISSUE_MESSAGE: Record<DobIssue, string> = {
  required: "Required",
  invalid: "Enter a valid date",
  future: "Date of birth cannot be in the future",
  too_old: `Date of birth cannot be more than ${DOB_MAX_AGE_YEARS} years ago`,
};

export function dobIssueMessage(issue: DobIssue): string {
  return ISSUE_MESSAGE[issue];
}

/** Local calendar today as YYYY-MM-DD (browser local). */
export function localTodayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function earliestDobIso(todayIso = localTodayIso()): string {
  const [y, m, d] = todayIso.split("-").map(Number);
  return `${y - DOB_MAX_AGE_YEARS}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

/**
 * Validate an ISO date (YYYY-MM-DD). Returns null when valid.
 */
export function validateDobIso(
  value: string,
  opts: { required?: boolean; todayIso?: string } = {}
): DobIssue | null {
  const trimmed = value.trim();
  if (!trimmed) return opts.required === false ? null : "required";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return "invalid";

  const [y, m, d] = trimmed.split("-").map(Number);
  const asDate = new Date(y, m - 1, d);
  if (
    asDate.getFullYear() !== y ||
    asDate.getMonth() !== m - 1 ||
    asDate.getDate() !== d
  ) {
    return "invalid";
  }

  const today = opts.todayIso ?? localTodayIso();
  if (trimmed > today) return "future";
  if (trimmed < earliestDobIso(today)) return "too_old";
  return null;
}

export function daysInMonth(year: number, month1to12: number): number {
  return new Date(year, month1to12, 0).getDate();
}

export function parseDobParts(iso: string): {
  year: number | null;
  month: number | null;
  day: number | null;
} {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    return { year: null, month: null, day: null };
  }
  const [y, m, d] = iso.split("-").map(Number);
  return { year: y, month: m, day: d };
}

export function formatDobIso(
  year: number | null,
  month: number | null,
  day: number | null
): string {
  if (!year || !month || !day) return "";
  const max = daysInMonth(year, month);
  const safeDay = Math.min(day, max);
  return `${year}-${String(month).padStart(2, "0")}-${String(safeDay).padStart(2, "0")}`;
}

export const DOB_MONTHS = [
  { value: 1, label: "January" },
  { value: 2, label: "February" },
  { value: 3, label: "March" },
  { value: 4, label: "April" },
  { value: 5, label: "May" },
  { value: 6, label: "June" },
  { value: 7, label: "July" },
  { value: 8, label: "August" },
  { value: 9, label: "September" },
  { value: 10, label: "October" },
  { value: 11, label: "November" },
  { value: 12, label: "December" },
] as const;
