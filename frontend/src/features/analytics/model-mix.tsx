"use client";

import { OPERATION_HINT, OPERATION_LABEL, formatTokens, formatUsd } from "@/lib/analytics-format";
import type { AnalyticsModelRow, AnalyticsOperationRow } from "@/types/api";

const MIX_TONES = ["#6b3cf0", "#9b7dff", "#c4b5fd", "#e45a9a"];

function ShareBar({ share, index }: { share: number; index: number }) {
  return (
    <div className="h-2.5 overflow-hidden rounded-[5px] bg-[var(--insight-wash)]">
      <div
        className="h-full rounded-[5px]"
        style={{
          width: `${Math.max(share, share > 0 ? 2 : 0)}%`,
          background: MIX_TONES[index % MIX_TONES.length],
        }}
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
      {rows.map((row, i) => {
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
            <ShareBar share={share} index={i} />
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
      {display.map((row, i) => {
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
            <ShareBar share={share} index={i} />
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              {OPERATION_HINT[row.operation] ?? row.operation}
            </p>
          </li>
        );
      })}
    </ul>
  );
}
