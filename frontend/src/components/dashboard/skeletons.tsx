"use client";

import { cn } from "@/lib/utils";

/** Card-shaped placeholder used while clinic home analytics hydrate. */
export function MetricCardSkeleton({
  className,
  lines = 2,
}: {
  className?: string;
  lines?: 1 | 2 | 3;
}) {
  return (
    <div
      className={cn(
        "rounded-[10px] border border-border/70 bg-card p-5 shadow-[0_1px_0_0_rgba(0,0,0,0.02)]",
        className
      )}
      aria-hidden
    >
      <div className="h-3 w-[38%] animate-pulse rounded bg-muted" />
      <div className="mt-3 h-8 w-[28%] animate-pulse rounded bg-muted" />
      {lines >= 2 ? (
        <div className="mt-3 h-2.5 w-[52%] animate-pulse rounded bg-muted" />
      ) : null}
      {lines >= 3 ? (
        <div className="mt-2 h-2.5 w-[40%] animate-pulse rounded bg-muted" />
      ) : null}
    </div>
  );
}

export function PanelSkeleton({
  className,
  chartHeight = 240,
}: {
  className?: string;
  chartHeight?: number;
}) {
  return (
    <div
      className={cn(
        "rounded-[10px] border border-border/70 bg-card p-5 shadow-[0_1px_0_0_rgba(0,0,0,0.02)]",
        className
      )}
      aria-hidden
    >
      <div className="h-3.5 w-40 animate-pulse rounded bg-muted" />
      <div className="mt-2 h-2.5 w-56 animate-pulse rounded bg-muted" />
      <div className="mt-4 flex gap-6">
        <div className="h-7 w-16 animate-pulse rounded bg-muted" />
        <div className="h-7 w-16 animate-pulse rounded bg-muted" />
      </div>
      <div
        className="mt-4 animate-pulse rounded-[10px] bg-muted/70"
        style={{ height: chartHeight }}
      />
    </div>
  );
}

export function ListCardSkeleton({
  className,
  rows = 4,
}: {
  className?: string;
  rows?: number;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-[10px] border border-border/70 bg-card shadow-[0_1px_0_0_rgba(0,0,0,0.02)]",
        className
      )}
      aria-hidden
    >
      <div className="border-b border-border px-5 py-3">
        <div className="h-3.5 w-36 animate-pulse rounded bg-muted" />
      </div>
      <div className="divide-y divide-border/70 px-5">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="h-3 w-[42%] animate-pulse rounded bg-muted" />
              <div className="h-2.5 w-14 animate-pulse rounded bg-muted" />
            </div>
            <div className="mt-2 h-2.5 w-[68%] animate-pulse rounded bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
