"use client";

import { formatTokens, niceAxisTicks } from "@/lib/analytics-format";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export type TokenPoint = {
  date?: string;
  label: string;
  total_tokens: number;
  calls?: number;
};

function xTickIndexes(length: number): number[] {
  if (length <= 8) return Array.from({ length }, (_, i) => i);
  const last = length - 1;
  const ticks = new Set<number>([0, last]);
  const step = length > 21 ? 7 : 4;
  for (let i = step; i < last; i += step) {
    if (last - i >= 3) ticks.add(i);
  }
  return [...ticks].sort((a, b) => a - b);
}

function fullDateLabel(point: TokenPoint): string {
  if (!point.date) return point.label;
  const d = new Date(`${point.date}T12:00:00`);
  if (Number.isNaN(d.getTime())) return point.label;
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function TokenSparkline({
  points,
  className,
}: {
  points: TokenPoint[];
  className?: string;
}) {
  const max = Math.max(...points.map((p) => p.total_tokens), 0);
  const hasData = points.some((p) => p.total_tokens > 0);
  const ticks = niceAxisTicks(max);
  const scaleMax = ticks[ticks.length - 1] || 1;
  const yTicks = [...ticks].reverse();
  const labeled = new Set(xTickIndexes(points.length));

  if (!hasData) {
    return (
      <div className={cn("flex h-52 items-center justify-center", className)}>
        <p className="text-sm text-muted-foreground">No model calls in this window.</p>
      </div>
    );
  }

  return (
    <div className={cn("flex gap-3", className)}>
      <div
        className="flex h-52 shrink-0 flex-col justify-between pt-0.5 pb-px text-right font-mono text-[10px] leading-none tabular-nums text-muted-foreground"
        aria-hidden
      >
        {yTicks.map((tick) => (
          <span key={tick}>{formatTokens(tick)}</span>
        ))}
      </div>

      <div className="min-w-0 flex-1">
        <div className="relative h-52">
          <div className="pointer-events-none absolute inset-0 flex flex-col justify-between">
            {yTicks.map((tick, i) => (
              <div
                key={tick}
                className={cn(
                  "border-t",
                  i === yTicks.length - 1 ? "border-foreground/20" : "border-border/80"
                )}
              />
            ))}
          </div>

          <div className="group/plot relative flex h-full items-end gap-[3px]">
            {points.map((p, i) => {
              const pct = (p.total_tokens / scaleMax) * 100;
              const height = p.total_tokens === 0 ? 0 : Math.max(pct, 1.5);
              return (
                <div key={`${p.date ?? p.label}-${i}`} className="h-full min-w-0 flex-1">
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <button
                          type="button"
                          aria-label={`${fullDateLabel(p)}: ${p.total_tokens.toLocaleString()} tokens${
                            p.calls != null ? `, ${p.calls.toLocaleString()} calls` : ""
                          }`}
                          className="group/bar relative flex h-full w-full cursor-pointer items-end rounded-sm border-0 bg-transparent p-0 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      }
                    >
                      <span
                        className="w-full rounded-t-[3px] bg-primary/80 transition-[height,background-color,opacity] duration-150 group-hover/plot:opacity-35 group-hover/bar:!bg-primary group-hover/bar:!opacity-100 group-focus-visible/bar:!bg-primary group-focus-visible/bar:!opacity-100"
                        style={{ height: `${height}%` }}
                      />
                      {p.total_tokens === 0 ? (
                        <span className="absolute inset-x-0 bottom-0 h-px bg-primary/25" />
                      ) : null}
                    </TooltipTrigger>
                    <TooltipContent
                      side="top"
                      sideOffset={8}
                      className="flex-col items-start gap-0.5 px-3 py-2"
                    >
                      <span className="text-[11px] text-background/70">{fullDateLabel(p)}</span>
                      <span className="text-sm font-medium tabular-nums">
                        {p.total_tokens.toLocaleString()} tokens
                      </span>
                      {p.calls != null ? (
                        <span className="text-[11px] tabular-nums text-background/70">
                          {p.calls.toLocaleString()} {p.calls === 1 ? "call" : "calls"}
                        </span>
                      ) : null}
                    </TooltipContent>
                  </Tooltip>
                </div>
              );
            })}
          </div>
        </div>

        <div className="relative mt-2 h-4">
          {points.map((p, i) =>
            labeled.has(i) ? (
              <span
                key={`${p.date ?? p.label}-x-${i}`}
                className="absolute top-0 text-[10px] leading-none text-muted-foreground"
                style={{
                  left: `${points.length === 1 ? 0 : (i / (points.length - 1)) * 100}%`,
                  transform:
                    i === 0
                      ? "none"
                      : i === points.length - 1
                        ? "translateX(-100%)"
                        : "translateX(-50%)",
                }}
              >
                {p.label}
              </span>
            ) : null
          )}
        </div>
      </div>
    </div>
  );
}
