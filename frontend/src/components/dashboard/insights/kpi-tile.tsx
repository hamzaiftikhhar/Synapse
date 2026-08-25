import Link from "next/link";
import { InsightCard, type InsightTone } from "./insight-card";
import { MiniSparkline } from "./rounded-bar-chart";
import { MetricGlyph, type GlyphName } from "./illustrations";
import { cn } from "@/lib/utils";

export function KpiTile({
  tone = "paper",
  label,
  value,
  hint,
  href,
  spark,
  glyph,
  className,
}: {
  tone?: InsightTone;
  label: string;
  value: string | number;
  hint?: string;
  href?: string;
  spark?: number[];
  glyph?: GlyphName;
  className?: string;
}) {
  const onInk = tone === "ink";
  const inner = (
    <InsightCard tone={tone} className={cn("h-full justify-between p-5", className)}>
      <div className="flex items-start justify-between gap-3">
        <p
          className={cn(
            "text-[13px] font-medium",
            onInk ? "text-white/70" : "text-muted-foreground"
          )}
        >
          {label}
        </p>
        {glyph ? <MetricGlyph name={glyph} className="size-10 shrink-0" /> : null}
      </div>
      <p
        className={cn(
          "mt-3 text-[1.75rem] font-semibold tracking-tight tabular-nums",
          onInk ? "text-white" : "text-navy"
        )}
      >
        {value}
      </p>
      {hint ? (
        <p className={cn("mt-1 text-[11px]", onInk ? "text-white/60" : "text-muted-foreground")}>
          {hint}
        </p>
      ) : null}
      {spark && spark.some((v) => v > 0) ? (
        <div className="mt-4">
          <MiniSparkline values={spark} onInk={onInk} />
        </div>
      ) : null}
    </InsightCard>
  );

  if (!href) return inner;
  return (
    <Link href={href} className="block h-full rounded-[10px] outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {inner}
    </Link>
  );
}

export function GlyphStat({
  label,
  value,
  href,
  glyph,
  hint,
  tone = "paper",
}: {
  label: string;
  value: string | number;
  href?: string;
  glyph: GlyphName;
  hint?: string;
  tone?: InsightTone;
}) {
  const onInk = tone === "ink";
  const inner = (
    <InsightCard tone={tone} className="h-full p-5">
      <MetricGlyph name={glyph} className="size-11" />
      <p className={cn("mt-4 text-[13px]", onInk ? "text-white/70" : "text-muted-foreground")}>
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-2xl font-semibold tracking-tight tabular-nums",
          onInk ? "text-white" : "text-navy"
        )}
      >
        {value}
      </p>
      {hint ? (
        <p className={cn("mt-1 text-[11px]", onInk ? "text-white/60" : "text-muted-foreground")}>
          {hint}
        </p>
      ) : null}
    </InsightCard>
  );
  if (!href) return inner;
  return (
    <Link
      href={href}
      className="block rounded-[10px] outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {inner}
    </Link>
  );
}
