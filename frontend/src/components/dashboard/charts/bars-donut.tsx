"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AnalyticsTooltip } from "./tooltip";
import { CHART } from "./colors";

export function AnalyticsHorizontalBarChart({
  data,
  height = 240,
  color = CHART.purple,
}: {
  data: { label: string; count: number }[];
  height?: number;
  color?: string;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 12, left: 8, bottom: 0 }}
        >
          <CartesianGrid horizontal={false} strokeDasharray="3 6" stroke={CHART.track} />
          <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <YAxis
            type="category"
            dataKey="label"
            width={110}
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 12, fill: "var(--navy)" }}
          />
          <Tooltip content={<AnalyticsTooltip />} />
          <Bar dataKey="count" name="Appointments" fill={color} radius={[0, 4, 4, 0]} barSize={14} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AnalyticsStackedBarChart({
  data,
  height = 260,
}: {
  data: { label: string; completed: number; cancelled: number; no_show: number }[];
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 6" stroke={CHART.track} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <YAxis allowDecimals={false} width={32} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} />
          <Tooltip content={<AnalyticsTooltip />} />
          <Bar dataKey="completed" name="Completed" stackId="s" fill={CHART.green} radius={[0, 0, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="cancelled" name="Cancelled" stackId="s" fill={CHART.red} isAnimationActive={false} />
          <Bar dataKey="no_show" name="No-show" stackId="s" fill={CHART.gray} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AnalyticsDonutChart({
  data,
  height = 260,
}: {
  data: { status: string; count: number; color: string; label: string }[];
  height?: number;
}) {
  const total = data.reduce((sum, d) => sum + d.count, 0);
  return (
    <div className="flex h-full flex-col items-center sm:flex-row sm:items-center" style={{ minHeight: height }}>
      <div className="relative h-[220px] w-full max-w-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="count"
              nameKey="label"
              innerRadius={62}
              outerRadius={88}
              paddingAngle={2}
              stroke="none"
              isAnimationActive={false}
            >
              {data.map((d) => (
                <Cell key={d.status} fill={d.color} />
              ))}
            </Pie>
            <Tooltip content={<AnalyticsTooltip />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <p className="text-[11px] text-muted-foreground">Total</p>
          <p className="text-2xl font-semibold tabular-nums text-navy">{total.toLocaleString()}</p>
        </div>
      </div>
      <ul className="mt-3 w-full space-y-2 sm:mt-0 sm:flex-1">
        {data.map((d) => (
          <li key={d.status} className="flex items-center gap-2 text-[13px]">
            <span className="size-2.5 rounded-full" style={{ background: d.color }} />
            <span className="flex-1 text-foreground">{d.label}</span>
            <span className="tabular-nums text-navy">{d.count}</span>
            <span className="w-10 text-right text-[11px] text-muted-foreground">
              {total ? `${((d.count / total) * 100).toFixed(0)}%` : "—"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
