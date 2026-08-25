import { InsightCard, type InsightTone } from "./insight-card";
import { MiniSparkline } from "./rounded-bar-chart";
import { cn } from "@/lib/utils";

/**
 * Sparkline-left / number-right KPI card for the dashboard overview's top
 * row. Distinct from `KpiTile` (spark sits below the number there) — this
 * shape was asked for explicitly to match a reference layout.
 */
export function KpiSparkCard({
  tone = "paper",
  label,
  value,
  change,
  spark,
  color,
  className,
}: {
  tone?: InsightTone;
  label: string;
  value: string | number;
  change?: number | null;
  spark?: number[];
  color: string;
  className?: string;
}) {
  const onInk = tone === "ink";
  const hasSpark = spark && spark.some((v) => v > 0);
  return (
    <InsightCard tone={tone} className={cn("p-4", className)}>
      <div className="flex items-center gap-3.5">
        <div className="h-11 w-[38%] shrink-0">
          {hasSpark ? (
            <MiniSparkline values={spark} color={onInk ? "#fff" : color} className="h-11 w-full" />
          ) : (
            <div
              className={cn(
                "h-full w-full rounded-md",
                onInk ? "bg-white/10" : "bg-foreground/[0.04]"
              )}
            />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            <p
              className={cn(
                "text-[1.6rem] leading-none font-semibold tracking-tight tabular-nums",
                onInk ? "text-white" : "text-navy"
              )}
            >
              {value}
            </p>
            {change !== undefined ? <MetricChangeCompact value={change} /> : null}
          </div>
        </div>
      </div>
      <p className={cn("mt-3 text-[13px]", onInk ? "text-white/70" : "text-muted-foreground")}>
        {label}
      </p>
    </InsightCard>
  );
}

function MetricChangeCompact({ value }: { value: number | null | undefined }) {
  if (value == null) return null;
  const up = value >= 0;
  return (
    <span className={cn("text-[12px] font-medium tabular-nums", up ? "text-success" : "text-destructive")}>
      {up ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}
