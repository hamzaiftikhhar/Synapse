"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { InsightCard } from "@/components/dashboard/insights/insight-card";
import { STATUS_LABEL } from "@/features/appointments/constants";
import { cn } from "@/lib/utils";
import type { AnalyticsStatusCount } from "@/types/api";
import { STATUS_COLOR } from "./colors";

const ORDER = [
  "confirmed",
  "pending",
  "completed",
  "cancelled",
  "no_show",
  "rescheduled",
] as const;

type StatusRow = {
  status: string;
  count: number;
  label: string;
  color: string;
};

function normalize(data: AnalyticsStatusCount[] | undefined): StatusRow[] {
  const raw = new Map<string, number>();
  if (Array.isArray(data)) {
    for (const row of data) {
      const key = String(row?.status ?? "");
      const n = Number(row?.count);
      if (!key || !Number.isFinite(n) || n < 0) continue;
      raw.set(key, n);
    }
  }
  return ORDER.map((status) => ({
    status,
    count: raw.get(status) ?? 0,
    label: STATUS_LABEL[status] ?? status,
    color: STATUS_COLOR[status] ?? "#8B95A7",
  }));
}

function StatusTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ name?: string; value?: number; payload?: StatusRow }>;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0];
  return (
    <div className="rounded-[10px] border border-[#152038]/10 bg-white px-3 py-2 shadow-[0_12px_32px_rgba(21,32,56,0.12)]">
      <p className="text-[12px] font-medium text-[#152038]">{row.name}</p>
      <p className="mt-0.5 text-[13px] tabular-nums text-[#152038]">
        {Number(row.value ?? 0).toLocaleString()}
      </p>
    </div>
  );
}

export function AppointmentStatusCard({
  data,
  isLoading,
  isError,
  onRetry,
  className,
}: {
  data: AnalyticsStatusCount[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  className?: string;
}) {
  const rows = normalize(data);
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const slices = rows.filter((row) => row.count > 0);
  const hasData = total > 0;

  return (
    <InsightCard overflow="hidden" className={cn("flex h-full p-6", className)}>
      <div>
        <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#152038]">
          Appointment status
        </h2>
        <p className="mt-0.5 text-[12px] leading-relaxed text-[#6B7280]">
          Status of appointments booked in this period
        </p>
      </div>

      {isLoading ? (
        <div className="mt-5 h-[240px] animate-pulse rounded-[12px] bg-[#F4F6F9]" />
      ) : isError ? (
        <div className="mt-5 flex h-[240px] flex-col items-center justify-center text-center">
          <p className="text-sm font-medium text-[#152038]">Unable to load status</p>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 text-[13px] font-medium text-[#3D7EFF] hover:underline"
            >
              Try again
            </button>
          ) : null}
        </div>
      ) : !hasData ? (
        <div className="mt-5 flex h-[240px] flex-col items-center justify-center px-4 text-center">
          <p className="text-sm font-medium text-[#152038]">No visits booked yet</p>
          <p className="mt-1 max-w-[220px] text-[13px] leading-relaxed text-[#6B7280]">
            Status mix appears once appointments are created in this period.
          </p>
        </div>
      ) : (
        <div className="mt-5 flex min-h-0 flex-1 flex-col gap-6 sm:flex-row sm:items-center">
          <div className="relative mx-auto h-[200px] w-[200px] shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="count"
                  nameKey="label"
                  innerRadius={64}
                  outerRadius={86}
                  paddingAngle={3}
                  stroke="#fff"
                  strokeWidth={3}
                  isAnimationActive={false}
                >
                  {slices.map((row) => (
                    <Cell key={row.status} fill={row.color} />
                  ))}
                </Pie>
                <Tooltip content={<StatusTooltip />} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#8B95A7]">
                Booked
              </p>
              <p className="text-[28px] font-semibold leading-none tabular-nums tracking-[-0.04em] text-[#152038]">
                {total.toLocaleString()}
              </p>
            </div>
          </div>

          <ul className="min-w-0 flex-1 space-y-3">
            {rows.map((row) => {
              const pct = total ? Math.round((row.count / total) * 100) : 0;
              return (
                <li key={row.status} className="flex items-center gap-2.5 text-[13px]">
                  <span
                    className="size-2.5 shrink-0 rounded-[3px]"
                    style={{ background: row.color }}
                  />
                  <span className="min-w-0 flex-1 truncate text-[#152038]">{row.label}</span>
                  <span className="tabular-nums font-semibold text-[#152038]">
                    {row.count.toLocaleString()}
                  </span>
                  <span className="w-9 text-right text-[12px] tabular-nums text-[#8B95A7]">
                    {pct}%
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </InsightCard>
  );
}
