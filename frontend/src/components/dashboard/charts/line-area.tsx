"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AnalyticsTooltip, rechartsTooltipWrapperStyle } from "./tooltip";
import { CHART } from "./colors";
import { formatChartTick } from "./format";

export type Point = Record<string, string | number>;

const axis = {
  tick: { fill: "var(--muted-foreground)", fontSize: 11 },
  axisLine: false as const,
  tickLine: false as const,
};

function xInterval(length: number) {
  if (length <= 8) return 0;
  if (length <= 16) return 1;
  if (length <= 32) return 3;
  if (length <= 90) return 6;
  return 14;
}

export function AnalyticsLineChart({
  data,
  xKey = "date",
  series,
  height = 260,
}: {
  data: Point[];
  xKey?: string;
  series: { key: string; label: string; color: string }[];
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 6" stroke={CHART.track} />
          <XAxis
            dataKey={xKey}
            interval={xInterval(data.length)}
            tickFormatter={(v: string) => formatChartTick(String(v), data.length)}
            {...axis}
          />
          <YAxis allowDecimals={false} width={36} {...axis} />
          <Tooltip content={<AnalyticsTooltip />} wrapperStyle={rechartsTooltipWrapperStyle} />
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AnalyticsAreaChart({
  data,
  xKey = "date",
  dataKey,
  label,
  color = CHART.purple,
  fill = CHART.purpleFill,
  height = 260,
}: {
  data: Point[];
  xKey?: string;
  dataKey: string;
  label: string;
  color?: string;
  fill?: string;
  height?: number;
}) {
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 6" stroke={CHART.track} />
          <XAxis
            dataKey={xKey}
            interval={xInterval(data.length)}
            tickFormatter={(v: string) => formatChartTick(String(v), data.length)}
            {...axis}
          />
          <YAxis allowDecimals={false} width={36} {...axis} />
          <Tooltip content={<AnalyticsTooltip />} wrapperStyle={rechartsTooltipWrapperStyle} />
          <Area
            type="monotone"
            dataKey={dataKey}
            name={label}
            stroke={color}
            fill={fill}
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
