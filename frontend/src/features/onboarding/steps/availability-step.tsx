"use client";

import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  businessHoursToWeekly,
  defaultWeeklySchedule,
  WeeklyScheduleEditor,
  type WeeklyDayValue,
} from "@/components/dashboard/weekly-schedule-editor";
import { queryKeys } from "@/hooks/api";
import {
  useBusinessHours,
  useDoctors,
  useUpdateDoctorSchedule,
} from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { doctorsService } from "@/services";
import type { DoctorScheduleSlot } from "@/types/api";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

function scheduleToWeekly(
  rows: DoctorScheduleSlot[] | undefined,
  clinicDefaults: WeeklyDayValue[]
): WeeklyDayValue[] {
  if (!rows || rows.length === 0) return clinicDefaults.map((d) => ({ ...d }));
  const closedWeek = defaultWeeklySchedule().map((d) => ({ ...d, isOpen: false }));
  return closedWeek.map((fallback) => {
    const row = rows.find((r) => r.day_of_week === fallback.day && r.is_active);
    if (!row) return fallback;
    return {
      day: fallback.day,
      isOpen: true,
      start: row.start_time.slice(0, 5),
      end: row.end_time.slice(0, 5),
    };
  });
}

export function AvailabilityStep({ onNext }: OnboardingStepProps) {
  const { data: doctorsData, isLoading: doctorsLoading } = useDoctors({ limit: 100 });
  const { data: businessHours } = useBusinessHours();
  const updateSchedule = useUpdateDoctorSchedule();
  const doctors = useMemo(() => doctorsData?.results ?? [], [doctorsData]);
  const clinicDefaults = useMemo(() => businessHoursToWeekly(businessHours), [businessHours]);

  // Every provider's schedule is fetched up front (not just the active tab)
  // so Continue can save whatever is currently shown for each provider —
  // including untouched tabs still showing the clinic-hours smart default.
  const scheduleQueries = useQueries({
    queries: doctors.map((doctor) => ({
      queryKey: queryKeys.doctorSchedule(doctor.id),
      queryFn: () => doctorsService.getSchedule(doctor.id),
    })),
  });
  const schedulesLoading = scheduleQueries.some((q) => q.isLoading);

  const [activeId, setActiveId] = useState<string>("");
  const [edits, setEdits] = useState<Record<string, WeeklyDayValue[]>>({});

  const effectiveActiveId = activeId || doctors[0]?.id || "";

  function valueFor(doctorId: string): WeeklyDayValue[] {
    if (edits[doctorId]) return edits[doctorId];
    const idx = doctors.findIndex((d) => d.id === doctorId);
    return scheduleToWeekly(scheduleQueries[idx]?.data, clinicDefaults);
  }

  function setValueFor(doctorId: string, rows: WeeklyDayValue[]) {
    setEdits((prev) => ({ ...prev, [doctorId]: rows }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const perDoctor = doctors.map((doctor) => ({
      id: doctor.id,
      rows: valueFor(doctor.id),
    }));
    const bad = perDoctor.find(({ rows }) =>
      rows.some((row) => row.isOpen && (!row.start || !row.end || row.end <= row.start))
    );
    if (bad) {
      toast.error("Closing time must be after opening time.");
      return;
    }
    try {
      await Promise.all(
        perDoctor.map(({ id, rows }) =>
          updateSchedule.mutateAsync({
            id,
            input: rows
              .filter((row) => row.isOpen)
              .map((row) => ({
                day_of_week: row.day,
                start_time: `${row.start}:00`,
                end_time: `${row.end}:00`,
                slot_duration_min: 30,
              })),
          })
        )
      );
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (doctorsLoading || schedulesLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  if (doctors.length === 0) {
    return (
      <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit}>
        <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
          <p className="text-sm font-medium text-navy">No providers yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Add a provider first, then come back here to set when patients can
            book with them. You can always do this later from the dashboard.
          </p>
        </div>
      </form>
    );
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit} className="space-y-4">
      <p className="text-sm text-muted-foreground">
        We started each provider from your clinic hours — adjust anyone whose
        schedule is different.
      </p>
      <Tabs value={effectiveActiveId} onValueChange={(v) => setActiveId(v as string)}>
        <TabsList className="w-full flex-wrap justify-start">
          {doctors.map((doctor) => (
            <TabsTrigger key={doctor.id} value={doctor.id}>
              {doctor.full_name}
              {edits[doctor.id] ? " •" : ""}
            </TabsTrigger>
          ))}
        </TabsList>
        {doctors.map((doctor) => (
          <TabsContent key={doctor.id} value={doctor.id} className="mt-4">
            {effectiveActiveId === doctor.id ? (
              <WeeklyScheduleEditor
                value={valueFor(doctor.id)}
                onChange={(rows) => setValueFor(doctor.id, rows)}
              />
            ) : null}
          </TabsContent>
        ))}
      </Tabs>
    </form>
  );
}
