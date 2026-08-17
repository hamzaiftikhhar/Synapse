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

export function fillDailySeries(
  rows: { date: string; total_tokens: number; calls: number }[],
  days: number
): { date: string; label: string; total_tokens: number; calls: number }[] {
  const byDate = new Map(rows.map((r) => [r.date, r]));
  const out = [];
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    const key = d.toISOString().slice(0, 10);
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
