"use client";

import { toast } from "sonner";
import {
  DoctorHoursEditor,
  useDoctorHoursState,
  weeklyToDoctorSchedule,
} from "@/features/doctors/doctor-hours-editor";
import { ensureDoctorCatalogLinks } from "@/features/onboarding/doctor-catalog-links";
import { useServices, useUpdateDoctor, useUpdateDoctorSchedule } from "@/hooks/api";
import { getApiErrorMessage } from "@/lib/api/client";
import { StepHint } from "../step-hint";
import { ONBOARDING_FORM_ID, type OnboardingStepProps } from "../steps";

export function AvailabilityStep({ onNext }: OnboardingStepProps) {
  const hours = useDoctorHoursState();
  const { data: servicesData } = useServices({ limit: 100 });
  const updateSchedule = useUpdateDoctorSchedule();
  const updateDoctor = useUpdateDoctor();
  const services = servicesData?.results ?? [];

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const perDoctor = hours.allDoctorRows();
    const error = hours.validateRows(perDoctor);
    if (error) {
      toast.error(error);
      return;
    }
    try {
      await Promise.all(
        perDoctor.map(({ id, rows }) =>
          updateSchedule.mutateAsync({
            id,
            input: weeklyToDoctorSchedule(rows),
          })
        )
      );
      await ensureDoctorCatalogLinks({
        doctors: hours.doctors,
        specialties: [],
        services,
        updateDoctor: (args) => updateDoctor.mutateAsync(args),
        kind: "services",
      });
      onNext();
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    }
  }

  return (
    <form id={ONBOARDING_FORM_ID} onSubmit={onSubmit} className="space-y-4">
      <StepHint>
        Each provider starts from clinic hours. Closed days mean they can&apos;t
        be booked.
      </StepHint>
      <DoctorHoursEditor
        state={hours}
        empty={
          <div className="rounded-xl border border-dashed border-border px-6 py-10 text-center">
            <p className="text-sm font-medium text-navy">No providers yet</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Add a provider first, then come back here to set when patients can
              book with them. You can always do this later from the dashboard.
            </p>
          </div>
        }
      />
    </form>
  );
}
