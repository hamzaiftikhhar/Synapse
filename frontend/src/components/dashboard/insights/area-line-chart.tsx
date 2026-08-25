"use client";

import { useId, useMemo } from "react";
import { splinePath, areaPath, type ChartPt } from "./chart-geom";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type SeriesPoint = {
  label: string;
  value: number;
  hint?: string;
};

export function AreaLineChart({
  points,
  height = 220,
  color = "var(--insight-royal)",
  fill = "var(--insight-orchid)",
  onInk = false,
  emptyLabel = "Nothing in this window yet",
  formatValue,
  className,
}: {
  points: SeriesPoint[];
  height?: number;
  color?: string;
  fill?: string;
  onInk?: boolean;
  emptyLabel?: string;
  formatValue?: (n: number) => string;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const pad = { top: 16, right: 8, bottom: 28, left: 8 };
  const width = 640;
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(...points.map((p) => p.value), 0);
  const hasData = points.some((p) => p.value > 0);

  const coords = useMemo<ChartPt[]>(() => {
    if (!points.length) return [];
    const span = Math.max(points.length - 1, 1);
    return points.map((p, i) => ({
      x: pad.left + (i / span) * innerW,
      y: pad.top + innerH - (max === 0 ? 0 : (p.value / max) * innerH),
    }));
  }, [points, innerW, innerH, max, pad.left, pad.top]);

  const line = splinePath(coords);
  const area = areaPath(line, coords, pad.top + innerH);
  const xTicks = tickIndexes(points.length);

  if (!hasData) {
    return (
      <div className={cn("flex items-center justify-center", className)} style={{ height }}>
        <p className={cn("text-sm", onInk ? "text-white/70" : "text-muted-foreground")}>
          {emptyLabel}
        </p>
      </div>
    );
  }

  const fmt = formatValue ?? ((n: number) => n.toLocaleString());
  const grid = onInk ? "rgb(255 255 255 / 12%)" : "rgb(42 24 72 / 8%)";
  const tickFill = onInk ? "rgb(255 255 255 / 55%)" : "var(--muted-foreground)";

  return (
    <div className={cn("relative w-full", className)}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label="Trend chart"
      >
        <defs>
          <linearGradient id={`area-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={fill} stopOpacity={onInk ? 0.45 : 0.35} />
            <stop offset="100%" stopColor={fill} stopOpacity={0} />
          </linearGradient>
          <filter id={`glow-${uid}`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const y = pad.top + innerH * t;
          return (
            <line
              key={t}
              x1={pad.left}
              x2={width - pad.right}
              y1={y}
              y2={y}
              stroke={grid}
              strokeDasharray="3 5"
              strokeWidth="1"
            />
          );
        })}
        <path d={area} fill={`url(#area-${uid})`} />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth="2.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          filter={`url(#glow-${uid})`}
        />
        {coords.map((c, i) =>
          i === highlightIndex(points) ? (
            <circle
              key={i}
              cx={c.x}
              cy={c.y}
              r="4.5"
              fill={onInk ? "#fff" : color}
              stroke={onInk ? color : "#fff"}
              strokeWidth="2"
            />
          ) : null
        )}
        {xTicks.map((i) => (
          <text
            key={i}
            x={coords[i]?.x ?? 0}
            y={height - 8}
            textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
            fill={tickFill}
            fontSize="11"
          >
            {points[i].label}
          </text>
        ))}
      </svg>
      <div className="pointer-events-none absolute inset-0" style={{ paddingBottom: 28 }}>
        <div className="flex h-full">
          {points.map((p, i) => (
            <Tooltip key={`${p.label}-${i}`}>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    className="pointer-events-auto h-full min-w-0 flex-1 cursor-pointer border-0 bg-transparent p-0 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`${p.label}: ${fmt(p.value)}${p.hint ? `, ${p.hint}` : ""}`}
                  />
                }
              />
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
          ))}
        </div>
      </div>
    </div>
  );
}

function tickIndexes(length: number): number[] {
  if (length <= 8) return Array.from({ length }, (_, i) => i);
  const last = length - 1;
  const ticks = new Set<number>([0, last]);
  const step = length > 21 ? 7 : 4;
  for (let i = step; i < last; i += step) {
    if (last - i >= 3) ticks.add(i);
  }
  return [...ticks].sort((a, b) => a - b);
}

function highlightIndex(points: SeriesPoint[]): number {
  let best = 0;
  points.forEach((p, i) => {
    if (p.value >= points[best].value) best = i;
  });
  return best;
}
