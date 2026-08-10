"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  businessHoursToWeekly,
  WeeklyScheduleEditor,
  type WeeklyDayValue,
} from "@/components/dashboard/weekly-schedule-editor";
import { useBusinessHours, useUpdateBusinessHours } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

export function HoursStep({ onNext }: OnboardingStepProps) {
  const { data, isLoading } = useBusinessHours();
  const update = useUpdateBusinessHours();
  const [rows, setRows] = useState<WeeklyDayValue[] | null>(null);

  const value = rows ?? businessHoursToWeekly(data);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const openWithoutRange = value.find(
      (row) => row.isOpen && (!row.start || !row.end || row.end <= row.start)
    );
    if (openWithoutRange) {
      toast.error("Closing time must be after opening time.");
      return;
    }
    try {
      await update.mutateAsync(
        value.map((row) => ({
          day_of_week: row.day,
          is_closed: !row.isOpen,
          open_time: row.isOpen ? `${row.start}:00` : null,
          close_time: row.isOpen ? `${row.end}:00` : null,
        }))
      );
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading && !rows) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit}>
      <WeeklyScheduleEditor value={value} onChange={setRows} />
    </form>
  );
}
