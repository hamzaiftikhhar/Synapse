"use client";

import { useId } from "react";
import { roundTopBar } from "./chart-geom";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type BarPoint = {
  label: string;
  value: number;
  hint?: string;
};

export function RoundedBarChart({
  points,
  height = 180,
  onInk = false,
  emptyLabel = "Nothing in this window yet",
  formatValue,
  className,
}: {
  points: BarPoint[];
  height?: number;
  onInk?: boolean;
  emptyLabel?: string;
  formatValue?: (n: number) => string;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const max = Math.max(...points.map((p) => p.value), 0);
  const hasData = points.some((p) => p.value > 0);
  const fmt = formatValue ?? ((n: number) => n.toLocaleString());

  if (!hasData) {
    return (
      <div className={cn("flex items-center justify-center", className)} style={{ height }}>
        <p className={cn("text-sm", onInk ? "text-white/70" : "text-muted-foreground")}>
          {emptyLabel}
        </p>
      </div>
    );
  }

  const vbH = 140;
  const vbW = 12;
  const barW = points.length > 20 ? 6.5 : 8;

  return (
    <div className={cn("w-full", className)}>
      <div className="flex items-end gap-[3px]" style={{ height }}>
        {points.map((p, i) => {
          const h = max === 0 ? 0 : (p.value / max) * vbH;
          const x = (vbW - barW) / 2;
          const y = vbH - h;
          return (
            <Tooltip key={`${p.label}-${i}`}>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    className="flex h-full min-w-0 flex-1 cursor-pointer items-end border-0 bg-transparent p-0 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`${p.label}: ${fmt(p.value)}`}
                  />
                }
              >
                <svg viewBox={`0 0 ${vbW} ${vbH}`} className="h-full w-full overflow-visible" preserveAspectRatio="none">
                  <defs>
                    <linearGradient id={`bar-${uid}-${i}`} x1="0" y1="1" x2="0" y2="0">
                      <stop
                        offset="0%"
                        stopColor={onInk ? "rgb(255 255 255 / 35%)" : "var(--insight-lilac)"}
                      />
                      <stop
                        offset="100%"
                        stopColor={onInk ? "#fff" : "var(--insight-royal)"}
                      />
                    </linearGradient>
                  </defs>
                  <path
                    d={roundTopBar(x, y, barW, Math.max(h, p.value > 0 ? 4 : 0), 2.4)}
                    fill={`url(#bar-${uid}-${i})`}
                  />
                </svg>
              </TooltipTrigger>
              <TooltipContent
                side="top"
                className="flex-col items-start gap-0.5 bg-[var(--insight-ink-deep)] px-3 py-2 text-white"
              >
                <span className="text-[11px] text-white/65">{p.label}</span>
                <span className="text-sm font-medium tabular-nums">{fmt(p.value)}</span>
                {p.hint ? (
                  <span className="text-[11px] text-white/65">{p.hint}</span>
                ) : null}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}

export function MiniSparkline({
  values,
  onInk = false,
  color,
  className,
}: {
  values: number[];
  onInk?: boolean;
  /** Overrides the default royal-purple stroke/fill — used to give each KPI
   * card its own line color (see dashboard/page.tsx's top row) instead of
   * every sparkline defaulting to the same purple. */
  color?: string;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const stroke = color ?? (onInk ? "#fff" : "var(--insight-royal)");
  const max = Math.max(...values, 1);
  const w = 120;
  const h = 42;
  const pts = values.map((v, i) => {
    const x = values.length === 1 ? w / 2 : (i / (values.length - 1)) * w;
    const y = h - (v / max) * (h - 4) - 2;
    return `${x},${y}`;
  });
  const d = values.length
    ? `M ${pts[0]} ` +
      values
        .slice(1)
        .map((_, i) => {
          const [x, y] = pts[i + 1].split(",");
          return `L ${x} ${y}`;
        })
        .join(" ")
    : "";

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={cn("h-10 w-full", className)} aria-hidden>
      <defs>
        <linearGradient id={`spark-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      {values.length > 1 ? (
        <polygon
          points={`0,${h} ${pts.join(" ")} ${w},${h}`}
          fill={`url(#spark-${uid})`}
        />
      ) : null}
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
