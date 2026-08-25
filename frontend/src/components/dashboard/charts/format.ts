import { format, parseISO } from "date-fns";

export function formatChartLabel(value: string | number | undefined): string {
  const raw = String(value ?? "");
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    try {
      return format(parseISO(raw.slice(0, 10)), "MMM d, yyyy");
    } catch {
      return raw;
    }
  }
  return raw;
}

export function formatChartTick(value: string, pointCount: number): string {
  if (!/^\d{4}-\d{2}-\d{2}/.test(value)) return value;
  try {
    const d = parseISO(value.slice(0, 10));
    if (pointCount <= 10) return format(d, "EEE d");
    if (pointCount <= 100) return format(d, "MMM d");
    return format(d, "MMM");
  } catch {
    return value;
  }
}

export function formatDurationSeconds(total: number): string {
  if (!total) return "—";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m`;
  return `${total}s`;
}

export function seriesHasValues(
  rows: Array<Record<string, unknown>>,
  keys: string[]
): boolean {
  return rows.some((row) => keys.some((key) => Number(row[key] ?? 0) > 0));
}

export function greetingForHour(hour: number, name: string): string {
  const hello =
    hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `${hello}, ${name}`;
}
