"use client";

import { formatTokens, formatUsd } from "@/lib/analytics-format";
import { cn } from "@/lib/utils";
import type { AnalyticsModelRow } from "@/types/api";

export function ModelMix({
  rows,
  showCost,
}: {
  rows: AnalyticsModelRow[];
  showCost: boolean;
}) {
  const total = rows.reduce((sum, r) => sum + r.total_tokens, 0) || 1;

  if (!rows.length) {
    return <p className="text-sm text-muted-foreground">No models recorded yet.</p>;
  }

  return (
    <ul className="space-y-4">
      {rows.map((row) => {
        const share = (row.total_tokens / total) * 100;
        return (
          <li key={row.model}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
              <span className="font-mono text-[13px] text-navy">{row.model}</span>
              <span className="text-[13px] tabular-nums text-muted-foreground">
                {formatTokens(row.total_tokens)}
                {showCost && row.estimated_usd != null ? (
                  <span className="ml-2 text-navy">{formatUsd(row.estimated_usd)}</span>
                ) : null}
              </span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-muted">
              <div
                className={cn("h-full rounded-full bg-navy")}
                style={{ width: `${Math.max(share, 2)}%` }}
              />
            </div>
            <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
              {row.prompt_tokens.toLocaleString()} in · {row.completion_tokens.toLocaleString()} out
              · {row.calls.toLocaleString()} calls
            </p>
          </li>
        );
      })}
    </ul>
  );
}
