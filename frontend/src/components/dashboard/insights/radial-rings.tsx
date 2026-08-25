"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

export type RingSlice = {
  label: string;
  value: number;
  color: string;
};

export function RadialRings({
  slices,
  centerValue,
  centerLabel,
  className,
}: {
  slices: RingSlice[];
  centerValue: string;
  centerLabel: string;
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const size = 220;
  const cx = size / 2;
  const cy = size / 2;
  const total = slices.reduce((s, r) => s + r.value, 0) || 1;
  const rings = slices.slice(0, 3);
  const radii = [84, 62, 40];
  const stroke = 12;

  return (
    <div className={cn("flex flex-col", className)}>
      <div className="relative mx-auto w-full max-w-[220px]">
        <svg viewBox={`0 0 ${size} ${size}`} className="h-auto w-full" role="img">
          <defs>
            {rings.map((r, i) => (
              <linearGradient key={i} id={`ring-${uid}-${i}`} x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor={r.color} />
                <stop offset="100%" stopColor={r.color} stopOpacity="0.72" />
              </linearGradient>
            ))}
          </defs>
          {rings.map((r, i) => {
            const rad = radii[i];
            const c = 2 * Math.PI * rad;
            const pct = r.value / total;
            const dash = Math.max(pct * c, r.value > 0 ? 8 : 0);
            return (
              <g key={r.label}>
                <circle
                  cx={cx}
                  cy={cy}
                  r={rad}
                  fill="none"
                  stroke="currentColor"
                  className="text-foreground/8"
                  strokeWidth={stroke}
                />
                <circle
                  cx={cx}
                  cy={cy}
                  r={rad}
                  fill="none"
                  stroke={`url(#ring-${uid}-${i})`}
                  strokeWidth={stroke}
                  strokeLinecap="round"
                  strokeDasharray={`${dash} ${c}`}
                  transform={`rotate(-90 ${cx} ${cy})`}
                />
              </g>
            );
          })}
          <text
            x={cx}
            y={cy - 4}
            textAnchor="middle"
            className="fill-navy"
            fontSize="28"
            fontWeight="700"
          >
            {centerValue}
          </text>
          <text
            x={cx}
            y={cy + 16}
            textAnchor="middle"
            className="fill-muted-foreground"
            fontSize="11"
          >
            {centerLabel}
          </text>
        </svg>
      </div>
      <ul className="mt-4 space-y-2.5">
        {rings.map((r) => (
          <li key={r.label} className="flex items-center gap-2.5 text-[13px]">
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ background: r.color }}
            />
            <span className="flex-1 text-foreground">{r.label}</span>
            <span className="tabular-nums text-navy">{r.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
