"use client";

import { formatChartLabel } from "./format";

export function AnalyticsTooltip({
  active,
  label,
  payload,
}: {
  active?: boolean;
  label?: string | number;
  payload?: Array<{
    value?: number | string;
    name?: string;
    color?: string;
    dataKey?: string | number;
  }>;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-[10px] border border-border bg-card px-3 py-2.5 shadow-md">
      <p className="text-[12px] font-medium text-navy">{formatChartLabel(label)}</p>
      <ul className="mt-1.5 space-y-1">
        {payload.map((item) => {
          const value = typeof item.value === "number" ? item.value : Number(item.value ?? 0);
          const name = String(item.name ?? item.dataKey ?? "");
          return (
            <li key={name} className="flex items-center gap-2 text-[12px]">
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ background: String(item.color) }}
              />
              <span className="text-muted-foreground">{name}</span>
              <span className="ml-auto tabular-nums text-navy">
                {Number.isFinite(value) ? value.toLocaleString() : "—"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
