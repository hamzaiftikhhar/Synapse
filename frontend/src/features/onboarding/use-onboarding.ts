"use client";

import { useMemo, useState } from "react";
import { useUpdateClinicProfile } from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";
import {
  isOnboardingStepSlug,
  ONBOARDING_STEPS,
  stageIndexForStep,
  type OnboardingStepSlug,
} from "./steps";

export function useOnboarding() {
  const { clinic } = useAuth();
  const updateProfile = useUpdateClinicProfile();

  const initialSlug = useMemo<OnboardingStepSlug>(() => {
    return isOnboardingStepSlug(clinic?.onboarding_step)
      ? clinic!.onboarding_step!
      : ONBOARDING_STEPS[0].slug;
    // Only ever read on first mount — the flow owns step navigation after that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [stepSlug, setStepSlug] = useState<OnboardingStepSlug>(initialSlug);
  const index = ONBOARDING_STEPS.findIndex((s) => s.slug === stepSlug);

  function persistStepPointer(slug: OnboardingStepSlug) {
    // Best-effort resume-cursor tracking — not the source of truth for any
    // actual clinic data, so it's fire-and-forget rather than blocking nav.
    updateProfile.mutate({ onboarding_step: slug });
  }

  function goTo(slug: OnboardingStepSlug) {
    setStepSlug(slug);
    persistStepPointer(slug);
  }

  function goNext() {
    const next = ONBOARDING_STEPS[index + 1];
    if (next) goTo(next.slug);
  }

  function goBack() {
    const prev = ONBOARDING_STEPS[index - 1];
    if (prev) goTo(prev.slug);
  }

  return {
    stepSlug,
    stepIndex: index,
    stageIndex: stageIndexForStep(stepSlug),
    isFirst: index === 0,
    isLast: index === ONBOARDING_STEPS.length - 1,
    goTo,
    goNext,
    goBack,
  };
}
