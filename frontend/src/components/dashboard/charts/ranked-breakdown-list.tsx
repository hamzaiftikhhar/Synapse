"use client";

type Item = { label: string; count: number };

/**
 * Lightweight ranked list — no Recharts, no cursor band on hover.
 * Used for doctor/service/specialty/insurance breakdowns.
 */
export function RankedBreakdownList({
  items,
  valueLabel = "appointments",
}: {
  items: Item[];
  valueLabel?: string;
}) {
  const rows = items.filter((row) => row.label && row.count > 0);
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const max = rows.reduce((n, row) => Math.max(n, row.count), 0);

  if (!rows.length) return null;

  return (
    <ol className="space-y-1.5" aria-label={`Top ${valueLabel}`}>
      {rows.map((row, index) => {
        const share = total ? Math.round((row.count / total) * 100) : 0;
        const width = max ? Math.max(6, Math.round((row.count / max) * 100)) : 0;
        return (
          <li
            key={row.label}
            className="group relative overflow-hidden rounded-xl bg-muted/25 transition-colors hover:bg-muted/45"
          >
            <div
              className="absolute inset-y-0 left-0 bg-primary/12"
              style={{ width: `${width}%` }}
              aria-hidden
            />
            <div className="relative flex items-center gap-3 px-3.5 py-2.5 sm:px-4 sm:py-3">
              <span className="w-5 shrink-0 text-[11px] font-medium tabular-nums text-muted-foreground">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span
                className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground"
                title={row.label}
              >
                {row.label}
              </span>
              <span className="shrink-0 text-sm font-semibold tabular-nums text-foreground">
                {row.count.toLocaleString()}
              </span>
              <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
                {share}%
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
