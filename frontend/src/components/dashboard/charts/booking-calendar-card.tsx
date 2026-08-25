"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Clock } from "lucide-react";
import { ClinicianIllustration } from "@/components/dashboard/insights/illustrations";
import { useAnalyticsCalendar } from "@/hooks/api";
import {
  clinicTodayDate,
  formatClinicTimeRange,
  isoToClinicParts,
} from "@/lib/timezone";
import { cn } from "@/lib/utils";
import type { AnalyticsCalendarDay, AnalyticsCalendarUpcoming } from "@/types/api";

const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"] as const;

function clampCursor(year: number, month: number) {
  if (!Number.isFinite(year) || !Number.isFinite(month)) {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() + 1 };
  }
  let y = Math.trunc(year);
  let m = Math.trunc(month);
  while (m < 1) {
    m += 12;
    y -= 1;
  }
  while (m > 12) {
    m -= 12;
    y += 1;
  }
  if (y < 2000) return { year: 2000, month: 1 };
  if (y > 2100) return { year: 2100, month: 12 };
  return { year: y, month: m };
}

function pad2(n: number) {
  return String(n).padStart(2, "0");
}

function monthCells(year: number, month: number) {
  const { year: y, month: m } = clampCursor(year, month);
  const firstWeekday = new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const cells: Array<{ day: number; date: string } | null> = [];
  for (let i = 0; i < firstWeekday; i += 1) cells.push(null);
  for (let d = 1; d <= last; d += 1) {
    cells.push({ day: d, date: `${y}-${pad2(m)}-${pad2(d)}` });
  }
  while (cells.length % 7 !== 0) cells.push(null);
  return cells.slice(0, 42);
}

function countByDate(days: AnalyticsCalendarDay[] | undefined) {
  const map = new Map<string, number>();
  if (!Array.isArray(days)) return map;
  for (const row of days) {
    const date = String(row?.date ?? "").slice(0, 10);
    const n = Number(row?.count);
    if (!date || date.length !== 10 || !Number.isFinite(n) || n <= 0) continue;
    map.set(date, n);
  }
  return map;
}

function monthLabel(year: number, month: number) {
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(Date.UTC(year, month - 1, 1)));
  } catch {
    return `${year}-${pad2(month)}`;
  }
}

function monthSpan(year: number, month: number) {
  try {
    const start = new Date(Date.UTC(year, month - 1, 1));
    const end = new Date(Date.UTC(year, month, 0));
    const fmt = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
    return `${fmt.format(start)} – ${fmt.format(end)}`;
  } catch {
    return "";
  }
}

function headingDate(iso: string, timeZone: string) {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone,
      day: "2-digit",
      month: "long",
      year: "numeric",
    }).format(new Date(iso));
  } catch {
    return "";
  }
}

function pipCount(n: number) {
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(3, Math.max(1, Math.trunc(n)));
}

function GlassButton({
  children,
  disabled,
  onClick,
  label,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-[9px] border border-white/35 bg-white/20 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.4)] backdrop-blur-xl backdrop-saturate-150 transition enabled:hover:bg-white/30 disabled:opacity-35"
    >
      {children}
    </button>
  );
}

function DoctorMark({ name }: { name: string }) {
  const [photoOk, setPhotoOk] = useState(true);
  const label = name.trim() || "Unassigned";
  return (
    <div className="flex shrink-0 flex-col items-center gap-1 pl-2">
      <span className="relative size-10 overflow-hidden rounded-full bg-[#efe8ff] ring-2 ring-white/70 shadow-[0_6px_14px_rgba(15,10,40,0.35)]">
        {photoOk ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src="/dashboard/calendar-doctor.png"
            alt=""
            className="h-full w-full object-cover"
            onError={() => setPhotoOk(false)}
          />
        ) : (
          <ClinicianIllustration className="absolute -top-1 left-1/2 h-[52px] w-[52px] -translate-x-1/2" />
        )}
      </span>
      <span className="max-w-[84px] text-center leading-tight">
        <span className="block text-[9px] font-semibold uppercase tracking-[0.12em] text-white/90">
          Doctor
        </span>
        <span className="mt-0.5 block truncate text-[11px] font-semibold text-white [text-shadow:0_1px_8px_rgba(15,10,40,0.55)]">
          {label}
        </span>
      </span>
    </div>
  );
}

function UpcomingRow({
  row,
  timeZone,
  showHeading,
}: {
  row: AnalyticsCalendarUpcoming;
  timeZone: string;
  showHeading: boolean;
}) {
  const heading = headingDate(row.start_time, timeZone);
  let range = "";
  try {
    if (row.start_time && row.end_time) {
      range = formatClinicTimeRange(row.start_time, row.end_time, timeZone);
    }
  } catch {
    range = "";
  }
  const patient = row.patient_name?.trim() || "Patient";
  const service = row.service_name?.trim();
  return (
    <div>
      {showHeading && heading ? (
        <p className="mb-2 text-[12px] font-semibold tracking-[-0.01em] text-white [text-shadow:0_1px_10px_rgba(15,10,40,0.55)]">
          {heading}
        </p>
      ) : null}
      <div className="flex items-center gap-2 rounded-[14px] border border-white/35 bg-white/18 px-3 py-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.28)] backdrop-blur-xl backdrop-saturate-150">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold tracking-[-0.02em] text-white [text-shadow:0_1px_8px_rgba(15,10,40,0.45)]">
            {patient}
          </p>
          {service ? (
            <p className="mt-0.5 truncate text-[11px] font-medium text-white/90">
              {service}
            </p>
          ) : null}
          {range ? (
            <p className="mt-0.5 flex items-center gap-1.5 text-[11px] font-medium text-white/90">
              <Clock className="size-3 shrink-0" strokeWidth={2.2} />
              <span className="truncate">{range}</span>
            </p>
          ) : null}
        </div>
        <DoctorMark name={row.doctor_name} />
      </div>
    </div>
  );
}

export function BookingCalendarCard({
  timeZone,
  className,
}: {
  timeZone: string;
  className?: string;
}) {
  const tz = timeZone || "UTC";
  const clinicToday = clinicTodayDate(tz);
  const [cursor, setCursor] = useState(() => {
    const [y, m] = clinicToday.split("-").map(Number);
    return clampCursor(y, m);
  });
  const [bgOk, setBgOk] = useState(true);
  const lastTz = useRef(tz);

  useEffect(() => {
    if (lastTz.current === tz) return;
    lastTz.current = tz;
    const [y, m] = clinicTodayDate(tz).split("-").map(Number);
    setCursor(clampCursor(y, m));
  }, [tz]);

  const query = useAnalyticsCalendar(cursor.year, cursor.month);
  const counts = useMemo(
    () => countByDate(query.data?.days),
    [query.data?.days]
  );
  const upcoming = Array.isArray(query.data?.upcoming)
    ? query.data.upcoming.filter((row) => row?.id && row?.start_time)
    : [];
  const today = String(query.data?.today || clinicToday).slice(0, 10);
  const cells = useMemo(
    () => monthCells(cursor.year, cursor.month),
    [cursor.year, cursor.month]
  );
  const canPrev = !(cursor.year === 2000 && cursor.month === 1);
  const canNext = !(cursor.year === 2100 && cursor.month === 12);
  const label = monthLabel(cursor.year, cursor.month);
  const span = monthSpan(cursor.year, cursor.month);

  return (
    <section
      className={cn(
        "relative isolate overflow-hidden rounded-[28px] text-white shadow-[0_28px_80px_rgba(15,10,40,0.42)]",
        className
      )}
    >
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(165deg, #0f172a 0%, #312e81 48%, #6d28d9 100%)",
        }}
      />
      {bgOk ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src="/dashboard/calendar-wash.png"
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => setBgOk(false)}
        />
      ) : null}
      <div className="absolute inset-0 bg-gradient-to-b from-[#020617]/55 via-[#1e1b4b]/42 to-[#2e1065]/58" />

      <div className="relative flex flex-col px-4 pb-4 pt-5 sm:px-5">
        <header>
          <h2 className="text-[24px] font-semibold leading-none tracking-[-0.04em] text-white [text-shadow:0_2px_16px_rgba(8,6,24,0.55)]">
            Bookings
          </h2>
          <p className="mt-1.5 text-[12px] font-medium text-white/90 [text-shadow:0_1px_10px_rgba(8,6,24,0.5)]">
            {span}
          </p>
        </header>

        <div className="mt-5 flex items-center justify-between gap-3">
          <p className="text-[14px] font-semibold tracking-[-0.02em] text-white [text-shadow:0_1px_10px_rgba(8,6,24,0.5)]">
            Calendar
          </p>
        </div>
        <div className="mt-2 h-px bg-white/30" />

        <div className="mt-3 flex items-center gap-2">
          <div className="flex items-center gap-1.5">
            <GlassButton
              label="Previous month"
              disabled={!canPrev}
              onClick={() => setCursor((c) => clampCursor(c.year, c.month - 1))}
            >
              <ChevronLeft className="size-3.5" strokeWidth={2.2} />
            </GlassButton>
            <GlassButton
              label="Next month"
              disabled={!canNext}
              onClick={() => setCursor((c) => clampCursor(c.year, c.month + 1))}
            >
              <ChevronRight className="size-3.5" strokeWidth={2.2} />
            </GlassButton>
          </div>
          <div className="flex flex-1 justify-center">
            <div className="rounded-full border border-white/35 bg-white/20 px-3 py-1 text-[12px] font-semibold tracking-[-0.01em] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.35)] backdrop-blur-xl backdrop-saturate-150">
              {label}
            </div>
          </div>
        </div>

        <div className="mt-3">
          <div className="grid grid-cols-7 text-center text-[10px] font-semibold uppercase tracking-[0.04em] text-white/80">
            {WEEKDAYS.map((d) => (
              <span key={d} className="py-1">
                {d}
              </span>
            ))}
          </div>
          {query.isError ? (
            <div className="flex h-[200px] flex-col items-center justify-center text-center">
              <p className="text-sm font-medium">Unable to load calendar</p>
              <button
                type="button"
                onClick={() => void query.refetch()}
                className="mt-2 text-[13px] font-medium text-white underline-offset-2 hover:underline"
              >
                Try again
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-7">
              {cells.map((cell, i) => {
                if (!cell) return <div key={`empty-${i}`} className="h-10" />;
                const count = counts.get(cell.date) ?? 0;
                const pips = pipCount(count);
                const isToday = cell.date === today;
                const labelForDay =
                  count > 0
                    ? `${count} ${count === 1 ? "appointment" : "appointments"}`
                    : isToday
                      ? "Today"
                      : undefined;
                return (
                  <div
                    key={cell.date}
                    className="flex h-10 flex-col items-center justify-center"
                    title={labelForDay}
                    aria-label={
                      labelForDay
                        ? `${cell.day}, ${labelForDay}`
                        : String(cell.day)
                    }
                  >
                    <span
                      className={cn(
                        "flex size-6 items-center justify-center text-[12px] tabular-nums",
                        isToday
                          ? "rounded-full bg-white font-semibold text-[#1e1b4b] shadow-[0_6px_16px_rgba(255,255,255,0.4)]"
                          : "font-semibold text-white [text-shadow:0_1px_8px_rgba(8,6,24,0.65)]"
                      )}
                    >
                      {cell.day}
                    </span>
                    <span className="mt-0.5 flex h-1.5 items-center justify-center gap-[3px]">
                      {query.isLoading
                        ? null
                        : Array.from({ length: pips }).map((_, pi) => (
                            <span
                              key={pi}
                              className="size-[3.5px] rounded-full bg-[#fb7185] shadow-[0_0_6px_rgba(251,113,133,0.8)]"
                            />
                          ))}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="mt-2 h-px bg-white/30" />

        <div className="mt-3 min-h-[108px]">
          <p className="mb-2.5 text-[14px] font-semibold tracking-[-0.02em] text-white [text-shadow:0_1px_10px_rgba(8,6,24,0.5)]">
            Upcoming appointments
          </p>
          {query.isLoading ? (
            <div className="h-[72px] animate-pulse rounded-[14px] bg-white/15" />
          ) : query.isError ? null : upcoming.length === 0 ? (
            <p className="py-2 text-[12px] font-medium text-white/85">
              No upcoming visits
            </p>
          ) : (
            <div className="flex max-h-[188px] flex-col gap-2.5 overflow-y-auto pr-0.5">
              {upcoming.map((row, i) => {
                const prev = upcoming[i - 1];
                let day = "";
                let prevDay = "";
                try {
                  day = isoToClinicParts(row.start_time, tz).date;
                  prevDay = prev
                    ? isoToClinicParts(prev.start_time, tz).date
                    : "";
                } catch {
                  day = "";
                  prevDay = "";
                }
                return (
                  <UpcomingRow
                    key={row.id}
                    row={row}
                    timeZone={tz}
                    showHeading={i === 0 || day !== prevDay}
                  />
                );
              })}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
