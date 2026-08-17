export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 1 : 2)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1_000) return `${(n / 1000).toFixed(1)}k`;
  return n.toLocaleString();
}

export function formatUsd(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export const OPERATION_LABEL: Record<string, string> = {
  intent_classification: "Routing",
  chat_completion: "Replies",
  embedding: "Knowledge",
};

export const OPERATION_HINT: Record<string, string> = {
  intent_classification: "Reads the visit and picks a path",
  chat_completion: "Writes the assistant reply",
  embedding: "Searches clinic knowledge",
};

export function niceAxisTicks(maxValue: number, count = 5): number[] {
  if (maxValue <= 0) return [0, 1];
  const raw = maxValue / Math.max(count - 1, 1);
  const exp = 10 ** Math.floor(Math.log10(raw));
  const f = raw / exp;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  const step = nice * exp;
  const top = Math.ceil(maxValue / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(v);
  return ticks;
}

function toDayKey(value: string | Date): string {
  if (typeof value === "string") return value.slice(0, 10);
  const y = value.getFullYear();
  const m = String(value.getMonth() + 1).padStart(2, "0");
  const d = String(value.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function fillDailySeries(
  rows: { date: string; total_tokens: number; calls: number }[],
  days: number
): { date: string; label: string; total_tokens: number; calls: number }[] {
  const byDate = new Map(rows.map((r) => [toDayKey(r.date), r]));
  const out = [];
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const key = toDayKey(d);
    const row = byDate.get(key);
    out.push({
      date: key,
      label: d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      total_tokens: row?.total_tokens ?? 0,
      calls: row?.calls ?? 0,
    });
  }
  return out;
}
