"use client";

import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { useQueries } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  businessHoursToWeekly,
  defaultWeeklySchedule,
  validateWeeklySchedule,
  WeeklyScheduleEditor,
  type WeeklyDayValue,
} from "@/components/dashboard/weekly-schedule-editor";
import { queryKeys, useBusinessHours, useDoctors } from "@/hooks/api";
import { cn } from "@/lib/utils";
import { doctorsService } from "@/services";
import type { Doctor, DoctorScheduleInput, DoctorScheduleSlot } from "@/types/api";

const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function providerInitials(name: string) {
  const parts = name.replace(/^dr\.?\s*/i, "").trim().split(/\s+/);
  return parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

export function hoursSummary(rows: WeeklyDayValue[]): string {
  const open = rows.filter((r) => r.isOpen);
  if (open.length === 0) return "Closed all week";
  if (open.length === 7) return "Every day";
  if (open.length === 5 && open.every((d) => d.day < 5)) return "Mon–Fri";
  return open.map((d) => DAY_SHORT[d.day]).join(", ");
}

export function scheduleToWeekly(
  rows: DoctorScheduleSlot[] | undefined,
  clinicDefaults: WeeklyDayValue[]
): WeeklyDayValue[] {
  if (!rows || rows.length === 0) {
    return clinicDefaults.map((d) => ({
      ...d,
      intervals: d.intervals.map((iv) => ({ ...iv })),
    }));
  }
  const active = rows.filter((r) => r.is_active);
  const closedWeek = defaultWeeklySchedule().map((d) => ({
    ...d,
    isOpen: false,
    intervals: [],
  }));
  return closedWeek.map((fallback) => {
    const dayRows = active.filter((r) => r.day_of_week === fallback.day);
    if (dayRows.length === 0) return fallback;
    return {
      day: fallback.day,
      isOpen: true,
      intervals: dayRows
        .slice()
        .sort((a, b) => a.start_time.localeCompare(b.start_time))
        .map((r) => ({
          start: r.start_time.slice(0, 5),
          end: r.end_time.slice(0, 5),
        })),
    };
  });
}

export function weeklyToDoctorSchedule(rows: WeeklyDayValue[]): DoctorScheduleInput[] {
  return rows
    .filter((row) => row.isOpen)
    .flatMap((row) =>
      row.intervals.map((iv) => ({
        day_of_week: row.day,
        start_time: `${iv.start}:00`,
        end_time: `${iv.end}:00`,
        slot_duration_min: 30,
      }))
    );
}

export function useDoctorHoursState(options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true;
  const { data: doctorsData, isLoading: doctorsLoading } = useDoctors({ limit: 100 });
  const { data: businessHours } = useBusinessHours();
  const doctors = useMemo(() => doctorsData?.results ?? [], [doctorsData]);
  const clinicDefaults = useMemo(
    () => businessHoursToWeekly(businessHours),
    [businessHours]
  );

  const scheduleQueries = useQueries({
    queries: doctors.map((doctor) => ({
      queryKey: queryKeys.doctorSchedule(doctor.id),
      queryFn: () => doctorsService.getSchedule(doctor.id),
      enabled,
    })),
  });
  const schedulesLoading = enabled && scheduleQueries.some((q) => q.isLoading);

  const [activeId, setActiveId] = useState("");
  const [edits, setEdits] = useState<Record<string, WeeklyDayValue[]>>({});
  const [query, setQuery] = useState("");

  const effectiveActiveId = activeId || doctors[0]?.id || "";
  const activeIndex = Math.max(
    0,
    doctors.findIndex((d) => d.id === effectiveActiveId)
  );
  const activeDoctor = doctors[activeIndex] ?? doctors[0];
  const visibleDoctors = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return doctors;
    return doctors.filter(
      (d) =>
        d.full_name.toLowerCase().includes(q) ||
        d.title.toLowerCase().includes(q)
    );
  }, [doctors, query]);

  function valueFor(doctorId: string): WeeklyDayValue[] {
    if (edits[doctorId]) return edits[doctorId];
    const idx = doctors.findIndex((d) => d.id === doctorId);
    return scheduleToWeekly(scheduleQueries[idx]?.data, clinicDefaults);
  }

  function setValueFor(doctorId: string, rows: WeeklyDayValue[]) {
    setEdits((prev) => ({ ...prev, [doctorId]: rows }));
  }

  function selectByOffset(delta: number) {
    const next = doctors[activeIndex + delta];
    if (next) setActiveId(next.id);
  }

  function onRosterKeyDown(e: KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      selectByOffset(e.key === "ArrowDown" ? 1 : -1);
    }
  }

  function allDoctorRows() {
    return doctors.map((doctor) => ({
      id: doctor.id,
      rows: valueFor(doctor.id),
    }));
  }

  function dirtyAndActiveRows() {
    const ids = new Set(Object.keys(edits));
    if (effectiveActiveId) ids.add(effectiveActiveId);
    return doctors
      .filter((d) => ids.has(d.id))
      .map((d) => ({ id: d.id, rows: valueFor(d.id) }));
  }

  function validateRows(entries: { id: string; rows: WeeklyDayValue[] }[]) {
    const bad = entries.find(({ rows }) => validateWeeklySchedule(rows) !== null);
    return bad ? validateWeeklySchedule(bad.rows) : null;
  }

  function markSaved(ids: string[]) {
    setEdits((prev) => {
      const next = { ...prev };
      for (const id of ids) delete next[id];
      return next;
    });
  }

  return {
    doctors,
    isLoading: doctorsLoading || schedulesLoading,
    edits,
    query,
    setQuery,
    effectiveActiveId,
    activeIndex,
    activeDoctor,
    visibleDoctors,
    valueFor,
    setValueFor,
    setActiveId,
    selectByOffset,
    onRosterKeyDown,
    allDoctorRows,
    dirtyAndActiveRows,
    validateRows,
    markSaved,
    hasDirty: Object.keys(edits).length > 0,
  };
}

export function DoctorHoursEditor({
  state,
  empty,
}: {
  state: ReturnType<typeof useDoctorHoursState>;
  empty?: ReactNode;
}) {
  const {
    doctors,
    isLoading,
    edits,
    query,
    setQuery,
    effectiveActiveId,
    activeIndex,
    activeDoctor,
    visibleDoctors,
    valueFor,
    setValueFor,
    setActiveId,
    selectByOffset,
    onRosterKeyDown,
  } = state;

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  if (doctors.length === 0) {
    return (
      empty ?? (
        <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium text-navy">No providers yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Add a provider first, then set when patients can book with them.
          </p>
        </div>
      )
    );
  }

  if (doctors.length === 1 && activeDoctor) {
    return (
      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="border-b border-border px-5 py-4">
          <ProviderPaneHeader
            doctor={activeDoctor}
            summary={hoursSummary(valueFor(activeDoctor.id))}
          />
        </div>
        <div className="p-5 sm:p-6">
          <WeeklyScheduleEditor
            value={valueFor(activeDoctor.id)}
            onChange={(rows) => setValueFor(activeDoctor.id, rows)}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-card">
      <div className="grid md:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="border-b border-border md:border-r md:border-b-0">
          <div className="flex items-center justify-between px-4 pt-4 pb-2.5">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Providers
            </p>
            <span className="text-[11px] text-muted-foreground tabular-nums">
              {activeIndex + 1}/{doctors.length}
            </span>
          </div>
          {doctors.length > 6 ? (
            <div className="px-4 pb-3">
              <div className="relative">
                <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Find a provider"
                  className="h-7 pl-7 text-xs"
                  aria-label="Find a provider"
                />
              </div>
            </div>
          ) : null}

          <div className="flex gap-2 overflow-x-auto px-4 pb-4 md:hidden">
            {visibleDoctors.map((doctor) => (
              <ProviderChip
                key={doctor.id}
                doctor={doctor}
                selected={doctor.id === effectiveActiveId}
                customized={Boolean(edits[doctor.id])}
                onSelect={() => setActiveId(doctor.id)}
              />
            ))}
          </div>

          <div
            role="listbox"
            aria-label="Providers"
            tabIndex={0}
            onKeyDown={onRosterKeyDown}
            className="hidden max-h-[32rem] overflow-y-auto md:block"
          >
            {visibleDoctors.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                No match
              </p>
            ) : (
              visibleDoctors.map((doctor) => (
                <ProviderRow
                  key={doctor.id}
                  doctor={doctor}
                  selected={doctor.id === effectiveActiveId}
                  customized={Boolean(edits[doctor.id])}
                  summary={hoursSummary(valueFor(doctor.id))}
                  onSelect={() => setActiveId(doctor.id)}
                />
              ))
            )}
          </div>
        </aside>

        <section className="min-w-0">
          {activeDoctor ? (
            <>
              <div className="flex items-center gap-3 border-b border-border px-5 py-4">
                <div className="min-w-0 flex-1">
                  <ProviderPaneHeader
                    doctor={activeDoctor}
                    summary={
                      edits[activeDoctor.id]
                        ? `Custom · ${hoursSummary(valueFor(activeDoctor.id))}`
                        : `Clinic hours · ${hoursSummary(valueFor(activeDoctor.id))}`
                    }
                  />
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Previous provider"
                    disabled={activeIndex === 0}
                    onClick={() => selectByOffset(-1)}
                  >
                    <ChevronLeft className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Next provider"
                    disabled={activeIndex === doctors.length - 1}
                    onClick={() => selectByOffset(1)}
                  >
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
              </div>
              <div className="p-5 sm:p-6">
                <WeeklyScheduleEditor
                  value={valueFor(activeDoctor.id)}
                  onChange={(rows) => setValueFor(activeDoctor.id, rows)}
                />
              </div>
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function ProviderPaneHeader({ doctor, summary }: { doctor: Doctor; summary: string }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <ProviderAvatar doctor={doctor} />
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-navy">{doctor.full_name}</p>
        <p className="truncate text-xs text-muted-foreground">
          {[doctor.title, summary].filter(Boolean).join(" · ")}
        </p>
      </div>
    </div>
  );
}

function ProviderAvatar({
  doctor,
  size = "default",
}: {
  doctor: Doctor;
  size?: "default" | "sm";
}) {
  return (
    <Avatar size={size} className="bg-primary/10">
      {doctor.photo_url ? <AvatarImage src={doctor.photo_url} alt="" /> : null}
      <AvatarFallback className="bg-primary/10 text-xs font-medium text-primary">
        {providerInitials(doctor.full_name)}
      </AvatarFallback>
    </Avatar>
  );
}

function ProviderRow({
  doctor,
  selected,
  customized,
  summary,
  onSelect,
}: {
  doctor: Doctor;
  selected: boolean;
  customized: boolean;
  summary: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-3 border-l-2 px-4 py-3 text-left transition-colors",
        selected
          ? "border-l-primary bg-primary/10"
          : "border-l-transparent hover:bg-muted/60"
      )}
    >
      <ProviderAvatar doctor={doctor} size="sm" />
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-[13px]",
            selected ? "font-semibold text-navy" : "font-medium text-foreground"
          )}
        >
          {doctor.full_name}
        </span>
        <span className="block truncate text-[11px] text-muted-foreground">
          {summary}
        </span>
      </span>
      {customized ? (
        <Check className="size-3.5 shrink-0 text-primary" aria-label="Hours customized" />
      ) : null}
    </button>
  );
}

function ProviderChip({
  doctor,
  selected,
  customized,
  onSelect,
}: {
  doctor: Doctor;
  selected: boolean;
  customized: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex shrink-0 items-center gap-2 rounded-full border py-1 pr-3 pl-1 text-left transition-colors",
        selected
          ? "border-primary bg-primary/10 shadow-sm"
          : "border-border bg-muted/40 hover:bg-muted"
      )}
    >
      <ProviderAvatar doctor={doctor} size="sm" />
      <span className="max-w-[7.5rem] truncate text-xs font-medium">
        {doctor.full_name}
      </span>
      {customized ? <Check className="size-3 shrink-0 text-primary" /> : null}
    </button>
  );
}
