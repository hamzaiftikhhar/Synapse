"use client";

import { cn } from "@/lib/utils";

export function MetricChange({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="text-[12px] text-muted-foreground">vs prior period</span>;
  }
  const up = value >= 0;
  return (
    <span
      className={cn(
        "text-[12px] font-medium tabular-nums",
        up ? "text-success" : "text-destructive"
      )}
    >
      {up ? "+" : ""}
      {value.toFixed(1)}% vs prior period
    </span>
  );
}

export function MetricStat({
  label,
  value,
  hint,
  change,
  accent = "purple",
}: {
  label: string;
  value: string | number;
  hint?: string;
  change?: number | null;
  accent?: "purple" | "green" | "amber";
}) {
  const bar =
    accent === "green"
      ? "bg-success"
      : accent === "amber"
        ? "bg-warning"
        : "bg-[var(--insight-royal)]";
  return (
    <div className="insight-card relative overflow-hidden bg-card p-5 ring-1 ring-foreground/[0.06]">
      <span className={cn("absolute inset-y-0 left-0 w-[3px]", bar)} />
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="mt-2 text-[1.75rem] font-semibold tracking-tight text-navy tabular-nums">
        {value}
      </p>
      <div className="mt-2">
        {hint ? <p className="text-[12px] text-muted-foreground">{hint}</p> : null}
        {change !== undefined ? <MetricChange value={change} /> : null}
      </div>
    </div>
  );
}
