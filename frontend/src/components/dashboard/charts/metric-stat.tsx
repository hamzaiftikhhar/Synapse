"use client";

import { InsightCard } from "@/components/dashboard/insights/insight-card";
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

/**
 * Quiet KPI tile — same InsightCard chrome as the dashboard overview.
 * `accent` is accepted but unused (left-edge color bars were removed).
 */
export function MetricStat({
  label,
  value,
  hint,
  change,
}: {
  label: string;
  value: string | number;
  hint?: string;
  change?: number | null;
  accent?: "purple" | "green" | "amber";
}) {
  return (
    <InsightCard className="p-5">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="mt-2 text-[1.75rem] font-semibold tracking-tight text-navy tabular-nums">
        {value}
      </p>
      <div className="mt-2">
        {hint ? <p className="text-[12px] text-muted-foreground">{hint}</p> : null}
        {change !== undefined ? <MetricChange value={change} /> : null}
      </div>
    </InsightCard>
  );
}
