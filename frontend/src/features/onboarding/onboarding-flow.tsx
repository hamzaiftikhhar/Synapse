"use client";

import { OnboardingShell } from "./onboarding-shell";
import { AvailabilityStep } from "./steps/availability-step";
import { BillingStep } from "./steps/billing-step";
import { BookingStep } from "./steps/booking-step";
import { ClinicStep } from "./steps/clinic-step";
import { HoursStep } from "./steps/hours-step";
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
    subtitle: "Add clinicians by hand, or import a CSV / Excel using the sample format below.",
  },
  specialties: {
    title: "What areas of care do you offer?",
    subtitle: "Add specialties if you use them — this step is optional.",
  },
  services: {
    title: "What can patients book?",
    subtitle: "Add the services patients will schedule, or import them from a spreadsheet.",
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

export function OnboardingFlow() {
  const { stepSlug, stageIndex, isFirst, goNext, goBack, goTo } = useOnboarding();
  const copy = STEP_COPY[stepSlug];

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
    >
      {stepSlug === "clinic" ? <ClinicStep onNext={goNext} /> : null}
      {stepSlug === "location" ? <LocationStep onNext={goNext} /> : null}
      {stepSlug === "providers" ? <ProvidersStep onNext={goNext} /> : null}
      {stepSlug === "specialties" ? <SpecialtiesStep onNext={goNext} /> : null}
      {stepSlug === "services" ? <ServicesStep onNext={goNext} /> : null}
      {stepSlug === "hours" ? <HoursStep onNext={goNext} /> : null}
      {stepSlug === "availability" ? <AvailabilityStep onNext={goNext} /> : null}
      {stepSlug === "booking" ? <BookingStep onNext={goNext} /> : null}
    </OnboardingShell>
  );
}
