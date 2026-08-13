"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { BusinessHour, BusinessHourInput } from "@/types/api";

export type WeeklyInterval = {
  start: string; // "HH:MM"
  end: string; // "HH:MM"
};

export type WeeklyDayValue = {
  day: number; // 0 = Monday .. 6 = Sunday
  isOpen: boolean;
  intervals: WeeklyInterval[];
};

const DAY_LABELS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

const DEFAULT_INTERVAL: WeeklyInterval = { start: "13:00", end: "17:00" };

export function defaultWeeklySchedule(
  overrides?: Partial<Record<number, Partial<WeeklyDayValue>>>
): WeeklyDayValue[] {
  return Array.from({ length: 7 }, (_, day) => ({
    day,
    isOpen: day < 5,
    intervals: day < 5 ? [{ start: "09:00", end: day === 4 ? "15:00" : "17:00" }] : [],
    ...(overrides?.[day] ?? {}),
  }));
}

/** Convert saved ClinicBusinessHours rows (flat, 0..N per day — the API no
 * longer synthesizes placeholder rows) into editor values. A day with no
 * rows at all falls back to the Mon–Fri 9–5 default; a day with a single
 * `is_closed` row is closed; a day with one or more open rows becomes that
 * many stacked intervals, sorted by start time. */
export function businessHoursToWeekly(hours: BusinessHour[] | undefined): WeeklyDayValue[] {
  const defaults = defaultWeeklySchedule();
  if (!hours || hours.length === 0) return defaults;

  const byDay = new Map<number, BusinessHour[]>();
  for (const row of hours) {
    const bucket = byDay.get(row.day_of_week);
    if (bucket) bucket.push(row);
    else byDay.set(row.day_of_week, [row]);
  }

  return defaults.map((fallback) => {
    const rows = byDay.get(fallback.day);
    if (!rows || rows.length === 0) return fallback;
    if (rows.some((r) => r.is_closed)) {
      return { day: fallback.day, isOpen: false, intervals: [] };
    }
    const openRows = rows.filter((r) => r.open_time && r.close_time);
    if (openRows.length === 0) return fallback;
    return {
      day: fallback.day,
      isOpen: true,
      intervals: openRows
        .slice()
        .sort((a, b) => (a.open_time ?? "").localeCompare(b.open_time ?? ""))
        .map((r) => ({ start: r.open_time!.slice(0, 5), end: r.close_time!.slice(0, 5) })),
    };
  });
}

/** Client-side mirror of the backend's overlap/end-after-start validation
 * (apps/api/clinics/router.py::_validate_business_hours) — catches the
 * common mistakes before a round trip, not a replacement for it. Returns
 * a human-readable error, or null if the schedule is valid. */
export function validateWeeklySchedule(value: WeeklyDayValue[]): string | null {
  for (const row of value) {
    if (!row.isOpen) continue;
    if (row.intervals.length === 0) return `${DAY_LABELS[row.day]} is open but has no hours set.`;
    for (const iv of row.intervals) {
      if (!iv.start || !iv.end || iv.end <= iv.start) {
        return "Closing time must be after opening time.";
      }
    }
    const sorted = row.intervals.slice().sort((a, b) => a.start.localeCompare(b.start));
    for (let i = 0; i < sorted.length - 1; i++) {
      if (sorted[i].end > sorted[i + 1].start) {
        return `${DAY_LABELS[row.day]} has overlapping hours.`;
      }
    }
  }
  return null;
}

/** Flatten editor values into one BusinessHourInput row per interval (a
 * closed day still needs exactly one `is_closed` row so the day isn't
 * silently dropped by the API's delete+recreate). */
export function weeklyToBusinessHours(value: WeeklyDayValue[]): BusinessHourInput[] {
  return value.flatMap((row): BusinessHourInput[] => {
    if (!row.isOpen) return [{ day_of_week: row.day, is_closed: true }];
    return row.intervals.map((iv) => ({
      day_of_week: row.day,
      is_closed: false,
      open_time: `${iv.start}:00`,
      close_time: `${iv.end}:00`,
    }));
  });
}

export function WeeklyScheduleEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: WeeklyDayValue[];
  onChange: (rows: WeeklyDayValue[]) => void;
  disabled?: boolean;
}) {
  function updateDay(day: number, patch: Partial<WeeklyDayValue>) {
    onChange(value.map((row) => (row.day === day ? { ...row, ...patch } : row)));
  }

  function toggleOpen(day: number, isOpen: boolean) {
    updateDay(day, {
      isOpen,
      intervals: isOpen
        ? value.find((row) => row.day === day)?.intervals.length
          ? value.find((row) => row.day === day)!.intervals
          : [{ ...DEFAULT_INTERVAL, start: "09:00", end: "17:00" }]
        : [],
    });
  }

  function updateInterval(day: number, index: number, patch: Partial<WeeklyInterval>) {
    onChange(
      value.map((row) =>
        row.day === day
          ? {
              ...row,
              intervals: row.intervals.map((iv, i) => (i === index ? { ...iv, ...patch } : iv)),
            }
          : row
      )
    );
  }

  function addInterval(day: number) {
    onChange(
      value.map((row) =>
        row.day === day ? { ...row, intervals: [...row.intervals, { ...DEFAULT_INTERVAL }] } : row
      )
    );
  }

  function removeInterval(day: number, index: number) {
    onChange(
      value.map((row) =>
        row.day === day
          ? { ...row, intervals: row.intervals.filter((_, i) => i !== index) }
          : row
      )
    );
  }

  function copyMondayToOthers() {
    const monday = value.find((row) => row.day === 0);
    if (!monday) return;
    onChange(
      value.map((row) =>
        row.day === 0
          ? row
          : { ...row, isOpen: monday.isOpen, intervals: monday.intervals.map((iv) => ({ ...iv })) }
      )
    );
  }

  function applyToWeekdays() {
    const monday = value.find((row) => row.day === 0);
    if (!monday) return;
    onChange(
      value.map((row) =>
        row.day >= 1 && row.day <= 4
          ? { ...row, isOpen: monday.isOpen, intervals: monday.intervals.map((iv) => ({ ...iv })) }
          : row
      )
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={copyMondayToOthers} disabled={disabled}>
          Copy Monday to other days
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={applyToWeekdays} disabled={disabled}>
          Apply to weekdays
        </Button>
      </div>
      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
        {value
          .slice()
          .sort((a, b) => a.day - b.day)
          .map((row) => (
            <div
              key={row.day}
              className={cn(
                "flex flex-col gap-2.5 px-5 py-3.5 sm:flex-row sm:items-start sm:gap-6",
                !row.isOpen && "bg-muted/30"
              )}
            >
              <label className="flex w-36 shrink-0 items-center gap-2.5 pt-2 text-sm font-medium">
                <Checkbox
                  checked={row.isOpen}
                  onCheckedChange={(checked) => toggleOpen(row.day, Boolean(checked))}
                  disabled={disabled}
                />
                {DAY_LABELS[row.day]}
              </label>
              {row.isOpen ? (
                <div className="flex flex-1 flex-col gap-2">
                  {row.intervals.map((iv, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <Input
                        type="time"
                        value={iv.start}
                        onChange={(e) => updateInterval(row.day, index, { start: e.target.value })}
                        disabled={disabled}
                        className="w-36"
                        aria-label={`${DAY_LABELS[row.day]} interval ${index + 1} start time`}
                      />
                      <span className="text-sm text-muted-foreground">to</span>
                      <Input
                        type="time"
                        value={iv.end}
                        onChange={(e) => updateInterval(row.day, index, { end: e.target.value })}
                        disabled={disabled}
                        className="w-36"
                        aria-label={`${DAY_LABELS[row.day]} interval ${index + 1} end time`}
                      />
                      {row.intervals.length > 1 ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          onClick={() => removeInterval(row.day, index)}
                          disabled={disabled}
                          aria-label={`Remove ${DAY_LABELS[row.day]} interval ${index + 1}`}
                        >
                          <X className="size-3.5" />
                        </Button>
                      ) : null}
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="w-fit text-xs text-primary hover:text-primary"
                    onClick={() => addInterval(row.day)}
                    disabled={disabled}
                  >
                    + Add interval
                  </Button>
                </div>
              ) : (
                <p className="pt-2 text-sm text-muted-foreground">Closed</p>
              )}
            </div>
          ))}
      </div>
    </div>
  );
}
