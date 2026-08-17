"use client";

import { cn } from "@/lib/utils";
import { formatTokens } from "@/lib/analytics-format";

export function TokenSparkline({
  points,
  className,
}: {
  points: { label: string; total_tokens: number }[];
  className?: string;
}) {
  const max = Math.max(...points.map((p) => p.total_tokens), 1);
  const hasData = points.some((p) => p.total_tokens > 0);

  if (!hasData) {
    return (
      <div className={cn("flex h-40 items-center justify-center", className)}>
        <p className="text-sm text-muted-foreground">No model calls in this window.</p>
      </div>
    );
  }

  return (
    <div className={cn("flex h-40 items-end gap-px", className)}>
      {points.map((p, i) => {
        const pct = p.total_tokens === 0 ? 0 : Math.max((p.total_tokens / max) * 100, 6);
        return (
          <div
            key={`${p.label}-${i}`}
            className="group relative flex min-w-0 flex-1 flex-col items-center justify-end"
            title={`${p.label}: ${formatTokens(p.total_tokens)} tokens`}
          >
            <div
              className="w-full rounded-sm bg-navy/85 transition-colors group-hover:bg-primary"
              style={{ height: `${pct}%` }}
            />
          </div>
        );
      })}
    </div>
  );
}
