"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useDoctorAvailabilityCalendar } from "@/hooks/api";
import { cn } from "@/lib/utils";
import type { AvailabilityDensity } from "@/types/api";

const WEEKDAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];

const DENSITY_CELL: Record<AvailabilityDensity, string> = {
  plenty:
    "border-emerald-200 bg-emerald-50/70 hover:border-emerald-300 dark:border-emerald-900/40 dark:bg-emerald-950/20",
  few: "border-amber-200 bg-amber-50/70 hover:border-amber-300 dark:border-amber-900/40 dark:bg-amber-950/20",
  almost_full:
    "border-rose-200 bg-rose-50/60 hover:border-rose-300 dark:border-rose-900/40 dark:bg-rose-950/20",
  closed: "border-border bg-muted/30 text-muted-foreground/40 cursor-not-allowed",
};

const DENSITY_DOT: Record<AvailabilityDensity, string> = {
  plenty: "bg-emerald-500",
  few: "bg-amber-500",
  almost_full: "bg-rose-500",
  closed: "bg-transparent",
};

function monthBounds(year: number, month: number): { start: string; end: string } {
  const start = new Date(Date.UTC(year, month, 1));
  const end = new Date(Date.UTC(year, month + 1, 0));
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

function labelForMonth(year: number, month: number): string {
  return new Date(Date.UTC(year, month, 1)).toLocaleString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function parseYm(isoDate: string): { year: number; month: number } {
  const [y, m] = isoDate.split("-").map(Number);
  return { year: y, month: m - 1 };
}

type Props = {
  doctorId: string;
  selectedDate: string;
  today: string;
  /** Earliest selectable day (YYYY-MM-DD). Defaults to today. */
  minDate?: string;
  /** When true (default), jump off a closed selected day to the next open one. */
  autoCorrectClosed?: boolean;
  onSelect: (date: string) => void;
};

export function DoctorAvailabilityCalendar({
  doctorId,
  selectedDate,
  today,
  minDate,
  autoCorrectClosed = true,
  onSelect,
}: Props) {
  const earliest = minDate ?? today;
  const initial = parseYm(selectedDate || today);
  const [year, setYear] = useState(initial.year);
  const [month, setMonth] = useState(initial.month);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const next = parseYm(selectedDate || today);
    setYear(next.year);
    setMonth(next.month);
  }, [doctorId]); // reset view when doctor changes

  const { start, end } = useMemo(() => monthBounds(year, month), [year, month]);
  const { data: days, isFetching } = useDoctorAvailabilityCalendar(
    doctorId,
    start,
    end
  );

  const byDate = useMemo(() => {
    const map = new Map<string, { density: AvailabilityDensity; reason: string }>();
    for (const d of days ?? []) {
      map.set(d.date, { density: d.density, reason: d.reason });
    }
    return map;
  }, [days]);

  // If the selected date is closed (or empty), jump to the first open day
  // in the visible month on/after minDate so staff don't land on a dead day.
  useEffect(() => {
    if (!autoCorrectClosed || !days?.length) return;
    const selected = selectedDate
      ? days.find((d) => d.date === selectedDate)
      : undefined;
    if (selected && selected.density !== "closed") return;
    const firstOpen = days.find(
      (d) => d.density !== "closed" && d.date >= earliest
    );
    if (firstOpen && firstOpen.date !== selectedDate) {
      onSelectRef.current(firstOpen.date);
    }
  }, [days, selectedDate, earliest, autoCorrectClosed]);

  const leadingBlanks = new Date(`${start}T12:00:00`).getDay();

  function shiftMonth(delta: number) {
    const d = new Date(Date.UTC(year, month + delta, 1));
    setYear(d.getUTCFullYear());
    setMonth(d.getUTCMonth());
  }

  const earliestYm = parseYm(earliest);
  const canGoPrev =
    year > earliestYm.year ||
    (year === earliestYm.year && month > earliestYm.month);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30"
          onClick={() => shiftMonth(-1)}
          disabled={!canGoPrev}
          aria-label="Previous month"
        >
          <ChevronLeft className="size-4" />
        </button>
        <p className="text-xs font-medium text-foreground">
          {labelForMonth(year, month)}
        </p>
        <button
          type="button"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={() => shiftMonth(1)}
          aria-label="Next month"
        >
          <ChevronRight className="size-4" />
        </button>
      </div>

      <div
        className={cn(
          "rounded-lg border border-border/60 p-1.5 transition-opacity",
          isFetching && "opacity-60"
        )}
      >
        <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-medium text-muted-foreground">
          {WEEKDAY_LABELS.map((w, i) => (
            <div key={i} className="py-0.5">
              {w}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: leadingBlanks }).map((_, i) => (
            <div key={`blank-${i}`} aria-hidden />
          ))}
          {Array.from({ length: Number(end.slice(-2)) }).map((_, i) => {
            const dayNum = i + 1;
            const date = `${start.slice(0, 8)}${String(dayNum).padStart(2, "0")}`;
            const info = byDate.get(date);
            const density = info?.density ?? "closed";
            const beforeMin = date < earliest;
            const closed = density === "closed" || beforeMin;
            const isSelected = date === selectedDate;
            const isToday = date === today;
            return (
              <button
                key={date}
                type="button"
                disabled={closed}
                onClick={() => onSelect(date)}
                title={
                  closed
                    ? beforeMin
                      ? "Past date"
                      : info?.reason === "closed"
                        ? "Clinic closed"
                        : "No availability"
                    : undefined
                }
                className={cn(
                  "relative aspect-square rounded-md border text-[11px] transition-colors",
                  DENSITY_CELL[density],
                  beforeMin && density !== "closed" && "opacity-40",
                  isToday && !closed && "font-semibold text-primary",
                  isSelected && "ring-2 ring-primary/50"
                )}
              >
                {dayNum}
                {!closed ? (
                  <span
                    className={cn(
                      "absolute bottom-0.5 left-1/2 size-1 -translate-x-1/2 rounded-full",
                      DENSITY_DOT[density]
                    )}
                    aria-hidden
                  />
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-emerald-500" /> Plenty
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-amber-500" /> Few left
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-rose-500" /> Almost full
        </span>
        <span className="flex items-center gap-1">
          <span className="size-1.5 rounded-full bg-muted-foreground/30" /> Unavailable
        </span>
      </div>
    </div>
  );
}
