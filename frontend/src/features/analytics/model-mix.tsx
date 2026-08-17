"use client";

import { OPERATION_HINT, OPERATION_LABEL, formatTokens, formatUsd } from "@/lib/analytics-format";
import type { AnalyticsModelRow, AnalyticsOperationRow } from "@/types/api";

function ShareBar({ share }: { share: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-primary/10">
      <div
        className="h-full rounded-full bg-primary"
        style={{ width: `${Math.max(share, share > 0 ? 2 : 0)}%` }}
      />
    </div>
  );
}

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
            <ShareBar share={share} />
            <p className="mt-1.5 text-[11px] tabular-nums text-muted-foreground">
              {row.prompt_tokens.toLocaleString()} in · {row.completion_tokens.toLocaleString()} out
              · {row.calls.toLocaleString()} calls
            </p>
          </li>
        );
      })}
    </ul>
  );
}

const JOBS = ["intent_classification", "chat_completion", "embedding"] as const;

export function OperationMix({ rows }: { rows: AnalyticsOperationRow[] }) {
  const byOp = new Map(rows.map((r) => [r.operation, r]));
  const extras = rows.filter((r) => !JOBS.includes(r.operation as (typeof JOBS)[number]));
  const display: AnalyticsOperationRow[] = [
    ...JOBS.map(
      (operation) =>
        byOp.get(operation) ?? { operation, total_tokens: 0, calls: 0 }
    ),
    ...extras,
  ];
  const total = display.reduce((sum, r) => sum + r.total_tokens, 0) || 1;

  if (!rows.length) {
    return <p className="text-sm text-muted-foreground">No calls yet.</p>;
  }

  return (
    <ul className="space-y-4">
      {display.map((row) => {
        const share = (row.total_tokens / total) * 100;
        const label = OPERATION_LABEL[row.operation] ?? row.operation;
        return (
          <li key={row.operation}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
              <span className="text-[13px] font-medium text-navy">{label}</span>
              <span className="text-[13px] tabular-nums text-muted-foreground">
                {formatTokens(row.total_tokens)}
                <span className="ml-1.5 text-[11px]">
                  {row.calls.toLocaleString()} {row.calls === 1 ? "call" : "calls"}
                </span>
              </span>
            </div>
            <ShareBar share={share} />
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              {OPERATION_HINT[row.operation] ?? row.operation}
            </p>
          </li>
        );
      })}
    </ul>
  );
}
