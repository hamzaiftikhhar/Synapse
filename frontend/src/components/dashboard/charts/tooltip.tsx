"use client";

import type { CSSProperties } from "react";
import { formatChartLabel } from "./format";

/** Keeps Recharts hover cards above donut center labels and other overlays. */
export const rechartsTooltipWrapperStyle: CSSProperties = {
  zIndex: 50,
  outline: "none",
};

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
    <div className="rounded-[10px] border border-border bg-popover px-3 py-2.5 text-popover-foreground shadow-md">
      <p className="text-[12px] font-medium text-foreground">{formatChartLabel(label)}</p>
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
              <span className="ml-auto tabular-nums text-foreground">
                {Number.isFinite(value) ? value.toLocaleString() : "—"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
