"use client";

import { Info } from "lucide-react";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { AppointmentSourceRadarPoint } from "@/types/api";
import { cn } from "@/lib/utils";
import { rechartsTooltipWrapperStyle } from "./tooltip";

const SERIES = [
  { key: "phone" as const, label: "Calls", color: "#f59e0b" },
  { key: "walk_in" as const, label: "Walk-in", color: "#ec4899" },
  { key: "chatbot" as const, label: "Chatbot", color: "#818cf8" },
];

function DarkRadarTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value?: number; name?: string; color?: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-[148px] rounded-[12px] border border-border bg-popover px-3 py-2.5 text-popover-foreground shadow-md">
      <p className="text-[12px] font-medium">{label}</p>
      <ul className="mt-1.5 space-y-1">
        {payload.map((item) => (
          <li key={item.name} className="flex items-center gap-2 text-[12px]">
            <span
              className="size-1.5 rounded-full"
              style={{ background: String(item.color) }}
            />
            <span className="text-muted-foreground">{item.name}</span>
            <span className="ml-auto tabular-nums">
              {Number(item.value ?? 0).toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AppointmentSourceRadarCard({
  data,
  isLoading,
  isError,
  onRetry,
  className,
}: {
  data: AppointmentSourceRadarPoint[];
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  className?: string;
}) {
  const hasData = data.some((row) =>
    SERIES.some((s) => Number(row[s.key] ?? 0) > 0)
  );

  return (
    <section
      className={cn(
        "relative flex min-h-[420px] flex-col overflow-hidden rounded-[24px] p-8",
        className
      )}
      style={{
        background:
          "radial-gradient(120% 90% at 80% -10%, rgba(99,102,241,0.18), transparent 46%), #0d1425",
        boxShadow: "0 28px 80px rgba(2, 6, 23, 0.42)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-[17px] font-medium tracking-[-0.02em] text-white">
          Booking analysis
        </h2>
        <span
          className="flex size-7 items-center justify-center rounded-full text-white/35"
          title="Compares Calls, Walk-in, and Chatbot bookings across status in this date range."
        >
          <Info className="size-4" strokeWidth={1.6} />
        </span>
      </div>

      <ul className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
        {SERIES.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-[13px] text-white">
            <span className="size-2 rounded-full" style={{ background: s.color }} />
            {s.label}
          </li>
        ))}
      </ul>

      <div className="mt-5 min-h-0 flex-1">
        {isLoading ? (
          <div className="mx-auto mt-8 size-[240px] animate-pulse rounded-full bg-white/6" />
        ) : isError ? (
          <div className="flex h-[280px] flex-col items-center justify-center text-center">
            <p className="text-sm font-medium text-white">Unable to load analytics</p>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                className="mt-2 text-[13px] font-medium text-indigo-300 hover:underline"
              >
                Try again
              </button>
            ) : null}
          </div>
        ) : !hasData ? (
          <div className="flex h-[280px] flex-col items-center justify-center px-6 text-center">
            <p className="text-sm font-medium text-white">No channel mix yet</p>
            <p className="mt-1 max-w-[220px] text-[13px] leading-relaxed text-white/50">
              Calls, walk-ins, and chatbot bookings will draw overlapping profiles here.
            </p>
          </div>
        ) : (
          <div className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={data} cx="50%" cy="52%" outerRadius="68%">
                <PolarGrid
                  gridType="polygon"
                  stroke="rgba(148, 163, 184, 0.22)"
                  radialLines
                />
                <PolarAngleAxis
                  dataKey="axis"
                  tick={{
                    fill: "rgba(226, 232, 240, 0.78)",
                    fontSize: 12,
                    fontWeight: 400,
                  }}
                  tickLine={false}
                />
                <PolarRadiusAxis tick={false} axisLine={false} />
                <Tooltip
                  content={<DarkRadarTooltip />}
                  wrapperStyle={rechartsTooltipWrapperStyle}
                />
                {SERIES.map((s) => (
                  <Radar
                    key={s.key}
                    name={s.label}
                    dataKey={s.key}
                    stroke={s.color}
                    fill={s.color}
                    fillOpacity={0.34}
                    strokeWidth={1.75}
                    dot={false}
                  />
                ))}
              </RadarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </section>
  );
}
