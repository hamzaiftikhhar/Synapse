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

  async function goTo(slug: OnboardingStepSlug) {
    // Wait for the resume-cursor save before showing the new step, so a
    // refresh immediately after navigating can't land back one step behind.
    // The actual step data was already saved (awaited) before this is
    // called, so on failure we still advance locally rather than trap the
    // user — worst case they resume one step early next time, not lose work.
    try {
      await updateProfile.mutateAsync({ onboarding_step: slug });
    } catch {
      // swallow — see comment above
    }
    setStepSlug(slug);
  }

  function goNext() {
    const next = ONBOARDING_STEPS[index + 1];
    if (next) void goTo(next.slug);
  }

  function goBack() {
    const prev = ONBOARDING_STEPS[index - 1];
    if (prev) void goTo(prev.slug);
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
