"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Label,
  LabelList,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { STATUS_LABEL } from "@/features/appointments/constants";
import { useAnalyticsDoctorStatusBreakdown } from "@/hooks/api";
import type { DoctorStatusBreakdownRow } from "@/types/api";
import { ChartPanel } from "./chart-card";
import { DOCTOR_STATUS_COLORS, type AnalyticsRange } from "./colors";
import { DateRangeSelector } from "./date-range-selector";
import { seriesHasValues } from "./format";
import { AnalyticsLegend } from "./legend";
import { rechartsTooltipWrapperStyle } from "./tooltip";

/** Legend order — darkest (bar base) to lightest (bar top). */
const STATUS_KEYS = [
  "completed",
  "confirmed",
  "pending",
  "rescheduled",
  "no_show",
  "cancelled",
] as const;

/** Recharts stacks first segment at the bottom — dark base, light top. */
const STACK_ORDER = [...STATUS_KEYS];

const COMPACT_BREAKPOINT = 480;
const COMPACT_PAGE_SIZE = 12;

type ChartLayout =
  | { mode: "chart"; pageSize: number }
  | { mode: "compact"; pageSize: number };

type ChartRow = DoctorStatusBreakdownRow & {
  shortLabel: string;
  total: number;
};

function rowTotal(row: DoctorStatusBreakdownRow): number {
  return (
    row.completed +
    row.confirmed +
    row.pending +
    row.rescheduled +
    row.no_show +
    row.cancelled
  );
}

function shortenDoctorName(name: string, max = 14): string {
  const trimmed = name.trim();
  if (trimmed.length <= max) return trimmed;
  const parts = trimmed.split(/\s+/);
  if (parts[0]?.replace(/\./g, "").toLowerCase() === "dr" && parts.length >= 2) {
    const short = `Dr. ${parts[parts.length - 1]}`;
    if (short.length <= max) return short;
  }
  return `${trimmed.slice(0, max - 1)}…`;
}

function resolveLayout(width: number): ChartLayout {
  if (width > 0 && width < COMPACT_BREAKPOINT) {
    return { mode: "compact", pageSize: COMPACT_PAGE_SIZE };
  }

  let pageSize = 8;
  if (width >= 1280) pageSize = 8;
  else if (width >= 1100) pageSize = 7;
  else if (width >= 960) pageSize = 6;
  else if (width >= 820) pageSize = 5;
  else if (width >= 680) pageSize = 4;
  else if (width >= 560) pageSize = 3;
  else pageSize = 3;

  return { mode: "chart", pageSize };
}

function DoctorStatusTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: ChartRow; color?: string; name?: string; value?: number }>;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;

  const entries = STATUS_KEYS.map((key) => ({
    key,
    name: STATUS_LABEL[key] ?? key,
    value: row[key],
    color: DOCTOR_STATUS_COLORS[key],
  })).filter((entry) => entry.value > 0);

  return (
    <div className="rounded-[10px] border border-border bg-popover px-3 py-2.5 text-popover-foreground shadow-md">
      <p className="text-[12px] font-medium text-foreground">{row.label}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">
        {rowTotal(row).toLocaleString()} appointments
      </p>
      <ul className="mt-2 space-y-1">
        {entries.map((entry) => (
          <li key={entry.key} className="flex items-center gap-2 text-[12px]">
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ background: entry.color }}
            />
            <span className="text-muted-foreground">{entry.name}</span>
            <span className="ml-auto tabular-nums text-foreground">
              {entry.value.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DoctorStatusCompactRow({ row }: { row: ChartRow }) {
  const total = row.total;
  const segments = STACK_ORDER.map((key) => ({
    key,
    value: row[key],
    color: DOCTOR_STATUS_COLORS[key],
  })).filter((segment) => segment.value > 0);

  return (
    <li className="rounded-xl border border-border/60 bg-muted/15 px-3 py-2.5 sm:px-4 sm:py-3">
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-foreground">
          {row.label}
        </p>
        <span className="shrink-0 text-sm font-semibold tabular-nums text-foreground">
          {total.toLocaleString()}
        </span>
      </div>
      {segments.length > 0 ? (
        <div
          className="mt-2 flex h-2.5 overflow-hidden rounded-full bg-muted/50"
          role="img"
          aria-label={`${row.label}: ${segments.map((s) => `${STATUS_LABEL[s.key]} ${s.value}`).join(", ")}`}
        >
          {segments.map((segment) => (
            <div
              key={segment.key}
              className="h-full min-w-px"
              style={{
                width: `${total ? (segment.value / total) * 100 : 0}%`,
                backgroundColor: segment.color,
              }}
              title={`${STATUS_LABEL[segment.key]}: ${segment.value}`}
            />
          ))}
        </div>
      ) : null}
    </li>
  );
}

function DoctorStatusCompactList({ rows }: { rows: ChartRow[] }) {
  return (
    <ul className="space-y-2" aria-label="Appointments by doctor">
      {rows.map((row) => (
        <DoctorStatusCompactRow key={row.label} row={row} />
      ))}
    </ul>
  );
}

function DoctorStatusVerticalChart({ rows, width }: { rows: ChartRow[]; width: number }) {
  const perBar = rows.length ? width / rows.length : width;
  const tickAngle = perBar >= 92 ? 0 : -34;
  const bottomMargin = tickAngle === 0 ? 32 : 56;
  const labelMax = perBar >= 100 ? 14 : perBar >= 80 ? 11 : 9;
  const maxBarSize = Math.min(42, Math.max(30, Math.floor(perBar * 0.52)));
  const categoryGap = width >= 960 ? "22%" : width >= 680 ? "26%" : "30%";

  const chartRows = rows.map((row) => ({
    ...row,
    shortLabel: shortenDoctorName(row.label, labelMax),
  }));

  return (
    <div className="h-[320px] w-full min-w-0 px-1 sm:px-2">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={chartRows}
          margin={{ top: 28, right: 12, left: 4, bottom: bottomMargin }}
          barCategoryGap={categoryGap}
          barGap={3}
        >
          <CartesianGrid vertical={false} strokeDasharray="3 6" stroke="var(--border)" />
          <XAxis
            dataKey="shortLabel"
            tickLine={false}
            axisLine={{ stroke: "var(--border)" }}
            tick={{
              fontSize: 10,
              fill: "var(--muted-foreground)",
            }}
            interval={0}
            angle={tickAngle}
            textAnchor={tickAngle === 0 ? "middle" : "end"}
            height={tickAngle === 0 ? 36 : 56}
          >
            <Label
              value="Doctor"
              offset={tickAngle === 0 ? -2 : 6}
              position="insideBottom"
              fill="var(--muted-foreground)"
              fontSize={11}
            />
          </XAxis>
          <YAxis
            allowDecimals={false}
            width={38}
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
          >
            <Label
              value="Appointments"
              angle={-90}
              position="insideLeft"
              fill="var(--muted-foreground)"
              fontSize={11}
              style={{ textAnchor: "middle" }}
            />
          </YAxis>
          <Tooltip
            content={<DoctorStatusTooltip />}
            wrapperStyle={rechartsTooltipWrapperStyle}
            cursor={{ fill: "transparent" }}
          />
          {STACK_ORDER.map((key, idx) => (
            <Bar
              key={key}
              dataKey={key}
              name={STATUS_LABEL[key]}
              stackId="status"
              fill={DOCTOR_STATUS_COLORS[key]}
              maxBarSize={maxBarSize}
              radius={idx === STACK_ORDER.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]}
              isAnimationActive={false}
            />
          ))}
          <Line
            type="monotone"
            dataKey="total"
            name="Total"
            stroke="var(--muted-foreground)"
            strokeWidth={1.5}
            dot={{
              r: 3,
              fill: "var(--card)",
              stroke: "var(--muted-foreground)",
              strokeWidth: 1.5,
            }}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="total"
              position="top"
              fill="var(--foreground)"
              fontSize={10}
              formatter={(label) => {
                const value = Number(label);
                return Number.isFinite(value) && value > 0 ? value.toLocaleString() : "";
              }}
            />
          </Line>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DoctorStatusStackCard({
  title = "Appointments by doctor",
  description = "Status mix per provider in the selected period",
  emptyTitle = "No appointments yet",
  emptyDescription = "Booked visits will appear here grouped by doctor and status.",
}: {
  title?: string;
  description?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const [range, setRange] = useState<AnalyticsRange>("30d");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [containerWidth, setContainerWidth] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const query = useAnalyticsDoctorStatusBreakdown(range);
  const items = query.data?.items ?? [];

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const update = () => setContainerWidth(node.getBoundingClientRect().width);
    update();

    const observer = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [query.isLoading, query.isSuccess]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter((row) => row.label.toLowerCase().includes(q));
  }, [items, search]);

  const layout = useMemo(() => resolveLayout(containerWidth), [containerWidth]);
  const pageSize = layout.pageSize;
  const showChart = layout.mode === "chart";

  useEffect(() => {
    setPage(0);
  }, [search, range, pageSize, showChart]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);

  const pageData = useMemo<ChartRow[]>(() => {
    const start = safePage * pageSize;
    return filtered.slice(start, start + pageSize).map((row) => ({
      ...row,
      shortLabel: shortenDoctorName(row.label),
      total: rowTotal(row),
    }));
  }, [filtered, safePage, pageSize]);

  const hasData = seriesHasValues(items, [...STATUS_KEYS]);
  const hasFilteredData = filtered.length > 0;

  const legendItems = [...STATUS_KEYS].reverse().map((key) => ({
    label: STATUS_LABEL[key] ?? key,
    color: DOCTOR_STATUS_COLORS[key],
  }));

  const rangeStart = filtered.length ? safePage * pageSize + 1 : 0;
  const rangeEnd = Math.min((safePage + 1) * pageSize, filtered.length);

  return (
    <ChartPanel
      title={title}
      description={description}
      isLoading={query.isLoading}
      isError={query.isError}
      onRetry={() => void query.refetch()}
      hasData={hasData}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      action={<DateRangeSelector value={range} onChange={setRange} className="w-full sm:w-auto" />}
    >
      <div ref={containerRef} className="min-w-0">
        <div className="mb-4 flex flex-col gap-3">
          <div className="relative w-full sm:max-w-xs">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              placeholder="Search doctors…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 pl-8"
              aria-label="Search doctors on chart"
            />
          </div>
          <AnalyticsLegend items={legendItems} />
        </div>

        {!hasFilteredData ? (
          <div className="flex min-h-[220px] flex-col items-center justify-center px-6 py-10 text-center">
            <p className="text-sm font-medium text-foreground">No matching doctors</p>
            <p className="mt-1 max-w-sm text-[13px] text-muted-foreground">
              Try a different name or clear the search filter.
            </p>
          </div>
        ) : (
          <>
            {showChart ? (
              <DoctorStatusVerticalChart rows={pageData} width={containerWidth} />
            ) : (
              <DoctorStatusCompactList rows={pageData} />
            )}

            {filtered.length > pageSize ? (
              <div className="mt-3 flex flex-col gap-2 text-[12px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
                <span>
                  Showing {rangeStart}–{rangeEnd} of {filtered.length} doctors
                </span>
                <div className="flex items-center justify-end gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    disabled={safePage === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    aria-label="Previous doctors"
                  >
                    <ChevronLeft className="size-3.5" />
                  </Button>
                  <span className="min-w-[3rem] text-center tabular-nums">
                    {safePage + 1} / {pageCount}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    disabled={safePage >= pageCount - 1}
                    onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                    aria-label="Next doctors"
                  >
                    <ChevronRight className="size-3.5" />
                  </Button>
                </div>
              </div>
            ) : filtered.length > 0 ? (
              <p className="mt-3 text-[12px] text-muted-foreground">
                {filtered.length} doctor{filtered.length === 1 ? "" : "s"} in this period
              </p>
            ) : null}
          </>
        )}
      </div>
    </ChartPanel>
  );
}
