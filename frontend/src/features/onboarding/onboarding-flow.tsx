"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { OnboardingShell } from "./onboarding-shell";
import { AvailabilityStep } from "./steps/availability-step";
import { BillingStep } from "./steps/billing-step";
import { BookingStep } from "./steps/booking-step";
import { ClinicStep } from "./steps/clinic-step";
import { HoursStep } from "./steps/hours-step";
import { InsuranceStep } from "./steps/insurance-step";
import { LocationStep } from "./steps/location-step";
import { ProvidersStep } from "./steps/providers-step";
import { ReviewStep } from "./steps/review-step";
import { ServicesStep } from "./steps/services-step";
import { SpecialtiesStep } from "./steps/specialties-step";
import { ONBOARDING_FORM_ID } from "./steps";
import { useOnboarding } from "./use-onboarding";

const STEP_COPY: Record<string, { title: string; subtitle: string }> = {
  clinic: {
    title: "Let's set up your clinic",
    subtitle: "We'll start with a few basics. You can change everything later from your dashboard.",
  },
  location: {
    title: "Where do you see patients?",
    subtitle: "The essentials for your primary location.",
  },
  providers: {
    title: "Who provides care at your clinic?",
    subtitle: "Add clinicians by hand, or import a spreadsheet.",
  },
  specialties: {
    title: "What areas of care do you offer?",
    subtitle: "Optional. Add a few by hand, or import a spreadsheet if you already have a list.",
  },
  services: {
    title: "What can patients book?",
    subtitle: "Add the services patients will schedule, or import them from a spreadsheet.",
  },
  insurance: {
    title: "Which insurance do you accept?",
    subtitle: "Optional — a payer name is enough. You can add plans later from the dashboard.",
  },
  hours: {
    title: "When is your clinic open?",
    subtitle: "We'll use this as the default for booking availability.",
  },
  availability: {
    title: "When can patients book with each provider?",
    subtitle: "We'll configure the basics now — you can manage detailed schedules anytime from the dashboard.",
  },
  booking: {
    title: "A few booking basics",
    subtitle: "Optional settings that help patients know what to expect.",
  },
  review: {
    title: "You're almost ready",
    subtitle: "Review your setup before we activate your clinic.",
  },
  billing: {
    title: "Activate your Synapse plan",
    subtitle: "One last step — payment activates your clinic's subscription.",
  },
};

/** Steps a user can genuinely have nothing on — the shell offers a Skip
 * next to Continue for these while they're empty. Every other step either
 * requires its own fields (Clinic, Location) or already lands on
 * sensible non-empty defaults (Hours, Availability, Booking), so Skip
 * would be meaningless there. */
const SKIPPABLE_STEPS = new Set(["specialties", "insurance"]);

export function OnboardingFlow() {
  const { stepSlug, stageIndex, isFirst, goNext, goBack, goTo } = useOnboarding();
  const copy = STEP_COPY[stepSlug];

  // Whether the current step has reported that it's empty. Reset on every
  // step change so a stale "empty" from the previous step can't flash a
  // Skip button before the new step's own data has reported in.
  const [stepIsEmpty, setStepIsEmpty] = useState(false);
  useEffect(() => {
    setStepIsEmpty(false);
  }, [stepSlug]);

  const onDataPresenceChange = useCallback((hasData: boolean) => {
    setStepIsEmpty(!hasData);
  }, []);

  const canSkip = SKIPPABLE_STEPS.has(stepSlug) && stepIsEmpty;
  const skipAction = canSkip ? (
    <Button type="button" variant="ghost" onClick={goNext}>
      Skip
    </Button>
  ) : undefined;

  if (stepSlug === "review") {
    return (
      <OnboardingShell
        stageIndex={stageIndex}
        title={copy.title}
        subtitle={copy.subtitle}
        onBack={goBack}
        hideFooter
      >
        <ReviewStep onGoToStep={goTo} />
      </OnboardingShell>
    );
  }

  if (stepSlug === "billing") {
    return (
      <OnboardingShell
        stageIndex={stageIndex}
        title={copy.title}
        subtitle={copy.subtitle}
        onBack={goBack}
        hideFooter
      >
        <BillingStep />
      </OnboardingShell>
    );
  }

  return (
    <OnboardingShell
      stageIndex={stageIndex}
      title={copy.title}
      subtitle={copy.subtitle}
      onBack={isFirst ? undefined : goBack}
      formId={ONBOARDING_FORM_ID}
      secondaryAction={skipAction}
          wide={
            stepSlug === "hours" ||
            stepSlug === "availability" ||
            stepSlug === "booking"
          }
    >
      {stepSlug === "clinic" ? <ClinicStep onNext={goNext} /> : null}
      {stepSlug === "location" ? <LocationStep onNext={goNext} /> : null}
      {stepSlug === "providers" ? <ProvidersStep onNext={goNext} /> : null}
      {stepSlug === "specialties" ? (
        <SpecialtiesStep onNext={goNext} onDataPresenceChange={onDataPresenceChange} />
      ) : null}
      {stepSlug === "services" ? <ServicesStep onNext={goNext} /> : null}
      {stepSlug === "insurance" ? (
        <InsuranceStep onNext={goNext} onDataPresenceChange={onDataPresenceChange} />
      ) : null}
      {stepSlug === "hours" ? <HoursStep onNext={goNext} /> : null}
      {stepSlug === "availability" ? <AvailabilityStep onNext={goNext} /> : null}
      {stepSlug === "booking" ? <BookingStep onNext={goNext} /> : null}
    </OnboardingShell>
  );
}
