"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  businessHoursToWeekly,
  validateWeeklySchedule,
  weeklyToBusinessHours,
  WeeklyScheduleEditor,
  type WeeklyDayValue,
} from "@/components/dashboard/weekly-schedule-editor";
import { useBusinessHours, useUpdateBusinessHours } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { StepHint } from "../step-hint";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

export function HoursStep({ onNext }: OnboardingStepProps) {
  const { data, isLoading } = useBusinessHours();
  const update = useUpdateBusinessHours();
  const [rows, setRows] = useState<WeeklyDayValue[] | null>(null);

  const value = rows ?? businessHoursToWeekly(data);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const error = validateWeeklySchedule(value);
    if (error) {
      toast.error(error);
      return;
    }
    try {
      await update.mutateAsync(weeklyToBusinessHours(value));
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  if (isLoading && !rows) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit} className="space-y-4">
      <StepHint>Closed days here mean the whole clinic is closed.</StepHint>
      <WeeklyScheduleEditor value={value} onChange={setRows} />
    </form>
  );
}
